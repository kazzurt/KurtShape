"""Aerial Hedra drawing templates for the KurtShape drawing pipeline (kurtshape.drawing).

Writes four ANSI B landscape (431.8 x 279.4 mm) DXF templates, each with its field map (JSON) and
a PDF/PNG preview rendered by the pipeline's own renderer:

    AH-B-mm-sheet1   millimetre drawing, first sheet: full title block, revision table, NOTES label
    AH-B-mm-sheetN   millimetre drawing, continuation sheet: short title block
    AH-B-in-sheet1   inch drawing, first sheet
    AH-B-in-sheetN   inch drawing, continuation sheet

Everything is vector. The logo is solid HATCH bands (the hexagon mark) and glyph outlines (the
wordmark in Century Gothic Bold), so any DXF reader and the pipeline's renderer draw it without
OLE or IMAGE objects. Paper coordinates are millimetres in both units variants: the pipeline lays
out in paper mm, and the inch variant differs in its units/tolerance block and in how the pipeline
formats dimension values (docs/DRAWINGS.md, "Templates").

Field placeholders are MTEXT entities. The map records their handles, so `Sheet.fill` finds them
by name; the map is written from the entities just created, so it cannot drift from the DXF.

Run with the bundled interpreter, output to a file (no console window):

    runtime/freecad-1.1.4/FreeCAD_1.1.4-Windows-x86_64-py311/bin/pythonw.exe -B tools/make_drawing_templates.py
        --out "C:/Users/Kurtz/Documents/Dodec/Drawing Template" > runtime/make_templates.txt 2>&1
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kurtshape.drawing import VENDOR_DIRNAME  # noqa: E402

_VENDOR = ROOT / "runtime" / "vendor" / VENDOR_DIRNAME
if _VENDOR.is_dir() and str(_VENDOR) not in sys.path:
    sys.path.append(str(_VENDOR))
os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / "runtime" / "vendor" / (VENDOR_DIRNAME + "-cache")))

import ezdxf  # noqa: E402
from ezdxf import const  # noqa: E402
from ezdxf import path as ezpath  # noqa: E402
from ezdxf.addons import text2path  # noqa: E402
from ezdxf.enums import MTextEntityAlignment, TextEntityAlignment  # noqa: E402
from ezdxf.fonts import fonts  # noqa: E402
from ezdxf.math import Matrix44  # noqa: E402

LATIN = ("AH-LATIN", "NotoSans-Regular.ttf", "Noto Sans")
BOLD = ("AH-LATIN-BOLD", "NotoSans-Bold.ttf", "Noto Sans")
WORDMARK_FONT = "GOTHICB.TTF"           # Century Gothic Bold: the face of the Aerial Hedra wordmark

# ---------------------------------------------------------------- sheet: ANSI B landscape, paper mm
SHEET_W, SHEET_H = 431.8, 279.4
MARGIN = 12.7
FX0, FY0, FX1, FY1 = MARGIN, MARGIN, SHEET_W - MARGIN, SHEET_H - MARGIN
ZONE_COLS, ZONE_ROWS = 4, 4
ZONE_TEXT = 6.0

# lineweights, 1/100 mm
LW_FRAME, LW_ZONE, LW_BLOCK, LW_CELL, LW_SYMBOL = 70, 35, 50, 25, 35
LAYERS = {
    "BORDER_FRAME": LW_FRAME,
    "BORDER_ZONES": LW_ZONE,
    "TITLE_BLOCK": LW_BLOCK,         # outlines of the title block and its three columns
    "TITLE_BLOCK_THIN": LW_CELL,     # cell dividers
    "TABLES": LW_CELL,               # revision table (the pipeline adds rows on this layer)
    "TEMPLATE_TEXT": LW_CELL,
    "AH_LOGO": LW_CELL,
}

# text cap heights, mm
H_LABEL = 1.6          # cell labels (TITLE, DWG NO., ...)
H_FIXED = 1.7          # tolerance block lines
H_VALUE = 2.5          # scale, weight, sheet
H_NAME = 2.0           # names and dates
H_MATERIAL = 2.2
H_TITLE = 3.5
H_NUMBER = 5.0         # size, drawing number, revision

# ---------------------------------------------------------------- title block geometry (sheet 1)
TB_W, TB_H = 203.2, 50.8                               # 8 x 2 in
TB_X0, TB_X1, TB_Y0, TB_Y1 = FX1 - TB_W, FX1, FY0, FY0 + TB_H
COL_A = (TB_X0, TB_X0 + 50.8)                          # general tolerances, projection
COL_B = (COL_A[1], COL_A[1] + 61.0)                    # approvals, material, finish
COL_C = (COL_B[1], TB_X1)                              # company, title, numbers (also the sheet-N block)
ROW_C = (TB_Y1, TB_Y1 - 17.5, TB_Y1 - 32.0, TB_Y1 - 42.5, TB_Y0)   # 63.5 46.0 31.5 21.0 12.7
XS_NUMBER = (COL_C[0], COL_C[0] + 12.7, COL_C[1] - 15.2, COL_C[1])   # SIZE | DWG NO. | REV
XS_SCALE = (COL_C[0], COL_C[0] + 27.9, COL_C[1] - 30.1, COL_C[1])    # SCALE | WEIGHT | SHEET
ROW_B = (TB_Y1, TB_Y1 - 7.0, TB_Y1 - 14.0)                         # DRAWN / CHECKED
XS_APPROVAL = (COL_B[0], COL_B[0] + 14.5, COL_B[0] + 43.0, COL_B[1])  # label | name (28.5) | date (18.0)
Y_MATERIAL = (ROW_B[-1], (ROW_B[-1] + TB_Y0) / 2, TB_Y0)               # MATERIAL over FINISH
Y_PROJECTION = TB_Y0 + 12.0                                          # top of the projection cell

# revision table (sheet 1), top right inside the frame
REV_COLS = (("REV", 12.7), ("DESCRIPTION", 85.0), ("DATE", 22.0), ("APPROVED", 24.0))
REV_X1 = FX1
REV_X0 = REV_X1 - sum(w for _, w in REV_COLS)
REV_TITLE_H, REV_HEAD_H, REV_ROW_H = 5.0, 5.7, 7.0
REV_Y_TITLE = (FY1, FY1 - REV_TITLE_H)
REV_Y_HEAD = (REV_Y_TITLE[1], REV_Y_TITLE[1] - REV_HEAD_H)
REV_FIRST_ROW = (REV_Y_HEAD[1] - REV_ROW_H, REV_Y_HEAD[1])

NOTES_INSERT = (FX0 + 2.6, FY1 - 4.2)

TEXTS = {
    "mm": {
        "UNITS": "DIMENSIONS ARE IN MILLIMETERS",
        "TOL": (("X", "±0.5"), ("X.X", "±0.25"), ("X.XX", "±0.10"), ("ANGLES", "±0.5°")),
        "ROUGHNESS": "SURFACE ROUGHNESS Ra 3.2 µm",
    },
    "in": {
        "UNITS": "DIMENSIONS ARE IN INCHES",
        "TOL": ((".X", "±.03"), (".XX", "±.010"), (".XXX", "±.005"), ("ANGLES", "±0.5°")),
        "ROUGHNESS": "SURFACE ROUGHNESS Ra 125 µin",
    },
}
COMPANY_LINES = ("San Diego, California", "kzeller94@gmail.com")


def hexagon(cx, cy, r, pointy=True):
    a0 = 90.0 if pointy else 0.0
    return [(cx + r * math.cos(math.radians(a0 + 60 * k)), cy + r * math.sin(math.radians(a0 + 60 * k)))
            for k in range(6)]


def regular(cx, cy, r, n, a0):
    return [(cx + r * math.cos(math.radians(a0 + 360.0 * k / n)), cy + r * math.sin(math.radians(a0 + 360.0 * k / n)))
            for k in range(n)]


class Template:
    def __init__(self, name, units, sheet):
        self.name, self.units, self.sheet = name, units, sheet
        self.doc = ezdxf.new("R2018", setup=False)
        self.msp = self.doc.modelspace()
        self.map = {"fields": {}, "fixed_texts": {}}
        self.projection_handles = []
        self._fonts = {}
        self._setup()

    # ------------------------------------------------------------ document setup
    def _setup(self):
        d = self.doc
        h = d.header
        h["$INSUNITS"] = 4
        h["$MEASUREMENT"] = 1
        h["$LUNITS"] = 2
        h["$LUPREC"] = 2
        h["$LTSCALE"] = 1.0
        h["$PSLTSCALE"] = 1
        h["$LWDISPLAY"] = 1
        h["$DIMDSEP"] = ord(".")
        h["$EXTMIN"] = (0.0, 0.0, 0.0)
        h["$EXTMAX"] = (SHEET_W, SHEET_H, 0.0)
        h["$LIMMIN"] = (0.0, 0.0)
        h["$LIMMAX"] = (SHEET_W, SHEET_H)
        for name, lw in LAYERS.items():
            d.layers.add(name, color=7, lineweight=lw)
        for name, font, family in (LATIN, BOLD):
            st = d.styles.add(name, font=font)
            st.set_extended_font_data(family=family, bold=(name == BOLD[0]))
        h["$TEXTSTYLE"] = LATIN[0]
        d.set_modelspace_vport(height=SHEET_H * 1.05, center=(SHEET_W / 2, SHEET_H / 2))

    # ------------------------------------------------------------ primitives
    def line(self, p, q, layer="TITLE_BLOCK_THIN", lw=None):
        attrs = {"layer": layer}
        if lw is not None:
            attrs["lineweight"] = lw
        return self.msp.add_line(p, q, dxfattribs=attrs)

    def rect(self, x0, y0, x1, y1, layer="TITLE_BLOCK"):
        return self.msp.add_lwpolyline([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], close=True,
                                       dxfattribs={"layer": layer})

    def text(self, pos, s, h, attach="MIDDLE_LEFT", bold=False, width=0.0, layer="TEMPLATE_TEXT"):
        e = self.msp.add_mtext(s, dxfattribs={"style": BOLD[0] if bold else LATIN[0], "char_height": h,
                                              "layer": layer, "insert": (pos[0], pos[1], 0.0), "width": width,
                                              "line_spacing_factor": 1.0})
        e.dxf.attachment_point = getattr(MTextEntityAlignment, attach)
        return e

    def font(self, file, h):
        key = (file, round(h, 4))
        if key not in self._fonts:
            self._fonts[key] = fonts.make_font(file, cap_height=h)
        return self._fonts[key]

    def width(self, s, h, bold=False):
        return self.font(BOLD[1] if bold else LATIN[1], h).text_width(s)

    def label(self, x0, y1, s):
        """Cell label in the cell's top-left corner."""
        return self.text((x0 + 0.9, y1 - 0.55), s, H_LABEL, attach="TOP_LEFT")

    def field(self, key, pos, placeholder, h, attach="MIDDLE_CENTER", bold=False, width=0.0):
        e = self.text(pos, placeholder, h, attach=attach, bold=bold, width=width)
        spec = {"handle": e.dxf.handle, "ch": h, "attach": attach, "insert": [round(pos[0], 3), round(pos[1], 3)]}
        if width:
            spec["width"] = width
        self.map["fields"][key] = spec
        return e

    def fixed(self, key, pos, s, h, attach="TOP_LEFT", bold=False):
        e = self.text(pos, s, h, attach=attach, bold=bold)
        self.map["fixed_texts"][key] = {"handle": e.dxf.handle, "text": s, "ch": h,
                                        "insert": [round(pos[0], 3), round(pos[1], 3)]}
        return e

    def solid(self, points):
        h = self.msp.add_hatch(color=7, dxfattribs={"layer": "AH_LOGO"})
        h.dxf.hatch_style = const.HATCH_STYLE_NESTED
        h.paths.add_polyline_path(points, is_closed=True, flags=const.BOUNDARY_PATH_EXTERNAL)
        return h

    def band(self, outer, inner):
        h = self.msp.add_hatch(color=7, dxfattribs={"layer": "AH_LOGO"})
        h.dxf.hatch_style = const.HATCH_STYLE_NESTED
        h.paths.add_polyline_path(outer, is_closed=True, flags=const.BOUNDARY_PATH_EXTERNAL)
        h.paths.add_polyline_path(inner, is_closed=True, flags=const.BOUNDARY_PATH_OUTERMOST)
        return h

    def bar(self, p, q, w):
        """Solid rectangle of width w along the segment p-q (butt ends)."""
        dx, dy = q[0] - p[0], q[1] - p[1]
        n = math.hypot(dx, dy)
        ux, uy = -dy / n * w / 2, dx / n * w / 2
        return self.solid([(p[0] + ux, p[1] + uy), (q[0] + ux, q[1] + uy), (q[0] - ux, q[1] - uy),
                           (p[0] - ux, p[1] - uy)])

    # ------------------------------------------------------------ frame and zones
    def frame(self):
        self.rect(FX0, FY0, FX1, FY1, layer="BORDER_FRAME")
        col_w, row_h = (FX1 - FX0) / ZONE_COLS, (FY1 - FY0) / ZONE_ROWS
        for k in range(1, ZONE_COLS):
            x = FX0 + k * col_w
            self.line((x, 0.0), (x, FY0), "BORDER_ZONES")
            self.line((x, FY1), (x, SHEET_H), "BORDER_ZONES")
        for k in range(1, ZONE_ROWS):
            y = FY0 + k * row_h
            self.line((0.0, y), (FX0, y), "BORDER_ZONES")
            self.line((FX1, y), (SHEET_W, y), "BORDER_ZONES")
        # centering marks on the four sides (ASME Y14.1)
        cx, cy = SHEET_W / 2, SHEET_H / 2
        self.line((cx, 0.0), (cx, FY0), "BORDER_FRAME")
        self.line((cx, FY1), (cx, SHEET_H), "BORDER_FRAME")
        self.line((0.0, cy), (FX0, cy), "BORDER_FRAME")
        self.line((FX1, cy), (SHEET_W, cy), "BORDER_FRAME")
        for k in range(ZONE_COLS):                       # numbers run right to left: 4 3 2 1
            x = FX0 + (k + 0.5) * col_w
            for y in (MARGIN / 2, SHEET_H - MARGIN / 2):
                self.text((x, y), str(ZONE_COLS - k), ZONE_TEXT, attach="MIDDLE_CENTER", layer="BORDER_ZONES")
        for k in range(ZONE_ROWS):                       # letters run bottom to top: A B C D
            y = FY0 + (k + 0.5) * row_h
            for x in (MARGIN / 2, SHEET_W - MARGIN / 2):
                self.text((x, y), chr(ord("A") + k), ZONE_TEXT, attach="MIDDLE_CENTER", layer="BORDER_ZONES")
        self.map["sheet_box"] = [0.0, 0.0, SHEET_W, SHEET_H]
        self.map["frame_box"] = [FX0, FY0, FX1, FY1]
        self.map["zones"] = {"columns": ZONE_COLS, "rows": ZONE_ROWS, "column_width": col_w, "row_height": row_h}

    # ------------------------------------------------------------ title block
    def column_c(self):
        """Company, title and number cells: the whole title block of a continuation sheet."""
        x0, x1 = COL_C
        y = ROW_C
        self.rect(x0, TB_Y0, x1, TB_Y1, layer="TITLE_BLOCK")
        for yy in y[1:4]:
            self.line((x0, yy), (x1, yy))
        # TITLE
        self.label(x0, y[1], "TITLE")
        self.field("TITLE", ((x0 + x1) / 2, (y[1] + y[2]) / 2 - 0.9), "----", H_TITLE, width=(x1 - x0) - 3.0)
        # SIZE | DWG NO. | REV
        for xx in XS_NUMBER[1:3]:
            self.line((xx, y[2]), (xx, y[3]))
        self.label(XS_NUMBER[0], y[2], "SIZE")
        self.label(XS_NUMBER[1], y[2], "DWG NO.")
        self.label(XS_NUMBER[2], y[2], "REV")
        ym = (y[2] + y[3]) / 2 - 0.8
        self.field("SIZE", ((XS_NUMBER[0] + XS_NUMBER[1]) / 2, ym), "B", H_NUMBER, bold=True)
        self.field("DWG_NO", ((XS_NUMBER[1] + XS_NUMBER[2]) / 2, ym), "----", H_NUMBER, bold=True)
        self.field("REV", ((XS_NUMBER[2] + XS_NUMBER[3]) / 2, ym), "-", H_NUMBER, bold=True)
        # SCALE | WEIGHT | SHEET
        for xx in XS_SCALE[1:3]:
            self.line((xx, y[3]), (xx, y[4]))
        self.label(XS_SCALE[0], y[3], "SCALE")
        self.label(XS_SCALE[1], y[3], "WEIGHT")
        self.label(XS_SCALE[2], y[3], "SHEET")
        ym = (y[3] + y[4]) / 2 - 0.7
        self.field("SCALE", ((XS_SCALE[0] + XS_SCALE[1]) / 2, ym), "----", H_VALUE)
        self.field("WEIGHT", ((XS_SCALE[1] + XS_SCALE[2]) / 2, ym), "----", H_VALUE)
        self.field("SHEET", ((XS_SCALE[2] + XS_SCALE[3]) / 2, ym), "----", H_VALUE)
        self.company(x0, y[1], x1, y[0])

    def column_b(self):
        x0, x1 = COL_B
        self.line((x0, TB_Y0), (x0, TB_Y1), "TITLE_BLOCK")
        for i, key in enumerate(("DRAWN", "CHECKED")):
            y1, y0 = ROW_B[i], ROW_B[i + 1]
            self.line((x0, y0), (x1, y0))
            ym = (y0 + y1) / 2
            self.text((x0 + 0.9, ym), key, H_LABEL, attach="MIDDLE_LEFT")
            self.field(f"{key}_NAME", (XS_APPROVAL[1] + 1.0, ym), "----", H_NAME, attach="MIDDLE_LEFT")
            self.field(f"{key}_DATE", (XS_APPROVAL[2] + 1.0, ym), "----", H_NAME, attach="MIDDLE_LEFT")
        # PDF fields follow the same cells as the DXF text; borders stay outside them.
        self.map["pdf_form_fields"] = [
            {"name": "CHECKED_NAME", "label": "Checked by", "rect": [XS_APPROVAL[1] + .6, ROW_B[2] + .6, XS_APPROVAL[2] - .6, ROW_B[1] - .6], "height_mm": H_NAME},
            {"name": "CHECKED_DATE", "label": "Checked date (YYYY-MM-DD)", "rect": [XS_APPROVAL[2] + .6, ROW_B[2] + .6, XS_APPROVAL[3] - .6, ROW_B[1] - .6], "height_mm": H_NAME, "max_length": 10},
        ]
        for xx in XS_APPROVAL[1:3]:
            self.line((xx, ROW_B[-1]), (xx, ROW_B[0]))
        for key, (y1, y0) in (("MATERIAL", Y_MATERIAL[0:2]), ("FINISH", Y_MATERIAL[1:3])):
            self.label(x0, y1, key)
            self.field(key, ((x0 + x1) / 2, (y0 + y1) / 2 - 0.9), "----", H_MATERIAL, width=(x1 - x0) - 3.0)
        self.line((x0, Y_MATERIAL[1]), (x1, Y_MATERIAL[1]))

    def column_a(self):
        x0, x1 = COL_A
        t = TEXTS[self.units]
        self.line((x0, TB_Y0), (x0, TB_Y1), "TITLE_BLOCK")
        self.line((x0, TB_Y1), (COL_C[0], TB_Y1), "TITLE_BLOCK")
        self.line((x0, TB_Y0), (COL_C[0], TB_Y0), "TITLE_BLOCK")
        pitch = 3.6
        y = TB_Y1 - 0.9
        xk, xv = x0 + 1.3, x0 + 15.5
        self.text((xk, y), "UNLESS OTHERWISE SPECIFIED:", H_FIXED, attach="TOP_LEFT")
        y -= pitch
        self.fixed("UNITS", (xk, y), t["UNITS"], H_FIXED, bold=True)
        y -= pitch
        self.text((xk, y), "TOLERANCES:", H_FIXED, attach="TOP_LEFT")
        for i, (k, v) in enumerate(t["TOL"]):
            y -= pitch
            self.fixed(f"TOL{i + 1}_KEY", (xk + 2.0, y), k, H_FIXED)
            self.fixed(f"TOL{i + 1}_VALUE", (xv, y), v, H_FIXED)
        y -= pitch
        self.fixed("ROUGHNESS", (xk, y), t["ROUGHNESS"], H_FIXED)
        y -= pitch
        self.fixed("EDGES", (xk, y), "BREAK SHARP EDGES, REMOVE BURRS", H_FIXED)
        y -= pitch
        self.fixed("NO_SCALE", (xk, y), "DO NOT SCALE DRAWING", H_FIXED)
        # projection cell
        self.line((x0, Y_PROJECTION), (x1, Y_PROJECTION))
        self.projection_symbol(x0 + 7.4, (TB_Y0 + Y_PROJECTION) / 2)
        self.fixed("PROJECTION", (x0 + 37.2, (TB_Y0 + Y_PROJECTION) / 2 + 2.0), "THIRD ANGLE", H_FIXED,
                   attach="MIDDLE_CENTER")
        self.fixed("PROJECTION2", (x0 + 37.2, (TB_Y0 + Y_PROJECTION) / 2 - 2.0), "PROJECTION", H_FIXED,
                   attach="MIDDLE_CENTER")

    def projection_symbol(self, cx, cy):
        """Third-angle symbol: end view (two circles) on the left of the truncated cone."""
        r1, r2 = 1.83, 3.66
        ents = [self.msp.add_circle((cx, cy), r1, dxfattribs={"layer": "TITLE_BLOCK_THIN", "lineweight": LW_SYMBOL}),
                self.msp.add_circle((cx, cy), r2, dxfattribs={"layer": "TITLE_BLOCK_THIN", "lineweight": LW_SYMBOL})]
        ext = r2 + 1.0
        for p, q in (((cx - ext, cy), (cx + ext, cy)), ((cx, cy - ext), (cx, cy + ext))):
            ents.append(self.line(p, q, lw=LW_CELL))
        xa, xb = cx + 5.9, cx + 13.2                      # small end left, large end right
        ha, hb = r1, r2
        pts = [(xa, cy - ha), (xb, cy - hb), (xb, cy + hb), (xa, cy + ha)]
        ents.append(self.msp.add_lwpolyline(pts, close=True,
                                            dxfattribs={"layer": "TITLE_BLOCK_THIN", "lineweight": LW_SYMBOL}))
        ents.append(self.line((xa - 1.0, cy), (xb + 1.0, cy), lw=LW_CELL))
        self.projection_handles = [e.dxf.handle for e in ents]

    # ------------------------------------------------------------ company cell: logo lockup + address
    def company(self, x0, y0, x1, y1):
        cy = (y0 + y1) / 2
        r = 6.6
        mcx = x0 + 1.6 + r * math.cos(math.radians(30))
        self.logo_mark(mcx, cy, r, w=0.04 * r)
        wx = mcx + r * math.cos(math.radians(30)) + 2.6
        box = self.wordmark(wx, cy)
        self.map["logo_box"] = [round(mcx - r * 0.87 - 0.3, 2), round(cy - r - 0.3, 2), round(box[2] + 0.3, 2),
                                round(cy + r + 0.3, 2)]
        for i, s in enumerate(COMPANY_LINES):
            self.fixed(f"COMPANY{i + 1}", (x1 - 1.6, cy + 1.7 - 3.4 * i), s, H_NAME, attach="MIDDLE_RIGHT")

    def logo_mark(self, cx, cy, r, w):
        """The Aerial Hedra mark: a regular hexagon, the hexagram on its vertices, the three
        diameters, and the hexagon through the midpoints of the triangle edges (vertex radius r/2),
        drawn as solid bands of width w (mitred by offsetting the polygons about the centre)."""
        k6, k3 = (w / 2) / math.cos(math.radians(30)), (w / 2) / math.cos(math.radians(60))
        self.band(hexagon(cx, cy, r + k6), hexagon(cx, cy, r - k6))
        for a0 in (90.0, 270.0):
            self.band(regular(cx, cy, r + k3, 3, a0), regular(cx, cy, r - k3, 3, a0))
        self.band(hexagon(cx, cy, r / 2 + k6), hexagon(cx, cy, r / 2 - k6))
        v = hexagon(cx, cy, r)
        for k in range(3):
            self.bar(v[k], v[k + 3], w)

    def wordmark(self, x, cy):
        """AERIAL HEDRA LLC on one line (capital A and H, small caps for the rest) in Century Gothic
        Bold, as glyph outlines, the capitals centred on the mark's axis. Returns its box."""
        face = fonts.FontFace(filename=WORDMARK_FONT)
        cap, sc = 4.0, 0.78 * 4.0
        y_base = cy - cap / 2
        track, word_gap = 0.05 * cap, 0.42 * cap

        def extent(s, size):
            b = ezpath.bbox(text2path.make_paths_from_str(s, face, size, align=TextEntityAlignment.LEFT))
            return b.extmin.x, b.extmax.x

        def place(s, size, x_left):
            hs = text2path.make_hatches_from_str(s, face, size, align=TextEntityAlignment.LEFT,
                                                 dxfattribs={"layer": "AH_LOGO", "color": 7},
                                                 m=Matrix44.translate(x_left, y_base, 0))
            for h in hs:
                h.dxf.hatch_style = const.HATCH_STYLE_NESTED
                self.msp.add_entity(h)

        xc = x
        for s, size in (("A", cap), ("ERIAL", sc), (None, word_gap), ("H", cap), ("EDRA", sc), (None, word_gap),
                        ("LLC", sc)):
            if s is None:
                xc += size
                continue
            x0, x1 = extent(s, size)
            place(s, size, xc - x0)
            xc += (x1 - x0) + track
        return (x, y_base, xc - track, y_base + cap)

    # ------------------------------------------------------------ revision table and notes label
    def revision_table(self):
        xs = [REV_X0]
        for _, w in REV_COLS:
            xs.append(xs[-1] + w)
        self.rect(REV_X0, REV_Y_HEAD[1], REV_X1, FY1, layer="TITLE_BLOCK")
        self.line((REV_X0, REV_Y_TITLE[1]), (REV_X1, REV_Y_TITLE[1]), "TABLES")
        self.text(((REV_X0 + REV_X1) / 2, sum(REV_Y_TITLE) / 2), "REVISIONS", 2.5, attach="MIDDLE_CENTER", bold=True,
                  layer="TABLES")
        for xx in xs[1:-1]:
            self.line((xx, REV_Y_HEAD[1]), (xx, REV_Y_HEAD[0]), "TABLES")
        for (name, _), x0, x1 in zip(REV_COLS, xs[:-1], xs[1:]):
            self.text(((x0 + x1) / 2, sum(REV_Y_HEAD) / 2), name, 2.0, attach="MIDDLE_CENTER", bold=True,
                      layer="TABLES")
        self.map["revision_table_box"] = [REV_X0, REV_Y_HEAD[1], REV_X1, FY1]
        self.map["revision_table"] = {
            "columns_x": {name: [x0, x1] for (name, _), x0, x1 in zip(REV_COLS, xs[:-1], xs[1:])},
            "row_height": REV_ROW_H, "first_row_y": list(REV_FIRST_ROW), "next_row_top": REV_FIRST_ROW[1],
            "data_ch": 2.5, "text_inset": 1.2, "pdf_approval_fields": True,
            "note": "The template has no data rows: Sheet.revision_row(1, ...) adds the first row under the "
                    "header (its top at next_row_top), later rows below it, drawing their own cell lines on "
                    "layer TABLES.",
        }

    def notes_label(self):
        e = self.text(NOTES_INSERT, "NOTES:", 3.0, attach="TOP_LEFT")
        self.map["notes_label"] = {"handle": e.dxf.handle, "insert": list(NOTES_INSERT), "ch": 3.0}

    # ------------------------------------------------------------ build and save
    def build(self):
        self.frame()
        self.column_c()
        if self.sheet == "1":
            self.column_b()
            self.column_a()
            self.revision_table()
            self.notes_label()
            tb_x0 = TB_X0
            views_top = REV_Y_HEAD[1] - 2.5
        else:
            tb_x0 = COL_C[0]
            views_top = FY1 - 2.5
            self.map["revision_table_box"] = None
            self.map["revision_table"] = None
            self.map["notes_label"] = None
        self.map["title_block_box"] = [tb_x0, TB_Y0, TB_X1, TB_Y1]
        self.map["usable"] = {
            "views": [FX0 + 2.0, TB_Y1 + 2.5, FX1 - 2.0, views_top],
            "notes": [FX0 + 2.0, TB_Y1 + 2.5, 140.0, FY1 - 8.5] if self.sheet == "1" else
                     [FX0 + 2.0, TB_Y1 + 2.5, 140.0, FY1 - 2.5],
            "upper_band": [142.0, 198.0, REV_X0 - 2.5, FY1 - 2.5] if self.sheet == "1" else None,
            "left_of_title_block": [FX0 + 2.0, FY0 + 2.0, tb_x0 - 2.5, TB_Y1],
        }
        self.map["projection_symbol_handles"] = self.projection_handles
        self.map["lineweights"] = {}
        self.map["styles"] = {"latin": LATIN[0], "bold": BOLD[0]}
        self.map["placeholders"] = ["----", "-"]
        return self

    def save(self, out_dir):
        out_dir = Path(out_dir)
        dxf = out_dir / f"{self.name}.dxf"
        self.doc.audit()
        self.doc.saveas(str(dxf))
        head = {
            "_about": f"Field map for the Aerial Hedra template {self.name} (ANSI B landscape, paper mm, "
                      f"{'inch' if self.units == 'in' else 'millimetre'} dimensions, "
                      f"{'first sheet' if self.sheet == '1' else 'continuation sheet'}). Written by "
                      "tools/make_drawing_templates.py together with the DXF; handles are read from the "
                      "entities as created.",
            "template": self.name, "dxf": dxf.name, "size": "B", "paper_units": "mm", "units": self.units,
            "sheet": self.sheet,
        }
        head.update(self.map)
        (out_dir / f"{self.name}.json").write_text(json.dumps(head, indent=2, ensure_ascii=False) + "\n",
                                                   encoding="utf-8")
        return dxf, out_dir / f"{self.name}.json"


def render_preview(dxf, map_json, out_dir, png_dir):
    """PDF preview through the pipeline's own renderer (which also proves the template loads in
    it); the PNG, written to ``png_dir``, feeds the pipeline's render check."""
    from kurtshape.drawing import sheet as SH
    sh = SH.Sheet(dxf, template_map=str(map_json))
    # A template has no part scale or weight. Populate those two fields only while
    # checking the layout, then restore placeholders for the blank template PDF.
    sh.fill({"SCALE": "1:1"})
    sh.set_weight(1.0, 1.0)
    if sh.map.get("revision_table"):
        sh.revision_row(1, "", "")
    lint = sh.lint()
    sh.fill({"SCALE": "----", "WEIGHT": "----"})
    stem = Path(dxf).stem
    sh.render(Path(out_dir) / f"{stem}.pdf", Path(png_dir) / f"{stem}.png", dpi=200,
              title=f"Aerial Hedra template {stem}")
    return list(sh.issues), lint


# The example follows the engineering drawing standard (Documents/Dodec/Drawing Template/
# Engineering Drawing Standard.md): the weight comes from set_weight (grams on the metric sheet,
# pounds on the inch sheet) and the notes repeat neither the title block nor a thread callout.
EXAMPLE = {
    "volume_mm3": 535.0, "density_g_cm3": 7.85,
    "fields": {
        "TITLE": "BOLT, 5/16-18 × 25, T40 CONE HEAD, WITH O-RING",
        "DWG_NO": "D021", "REV": "B", "SCALE": "2:1", "SHEET": "1 OF 1",
        "MATERIAL": "ALLOY STEEL, CLASS 10.9", "FINISH": "BLACK ZINC FLAKE, 8 µm MIN",
        "DRAWN_NAME": "KURTSHAPE", "DRAWN_DATE": "2026-10-23",
        "CHECKED_NAME": "", "CHECKED_DATE": "",
    },
    "revisions": [("A", "INITIAL RELEASE", "", "", 1),
                  ("B", "THREAD SHORTENED 1.5 MM; RECESS CHANGED TO ISO 10664 T40; TORQUE NOTE ADDED",
                   "", "", 2)],
    "notes": ["TORX T40 RECESS PER ISO 10664.",
              "DIMENSIONS APPLY AFTER COATING.",
              "O-RING SUPPLIED SEPARATELY; DO NOT INSTALL."],
}


def write_example(dxf, map_json, out_dir, png_dir):
    """A filled first sheet (title block, approvals, two revision rows, notes), as the pipeline
    would fill it: shows the template in use and exercises every field of the map."""
    from kurtshape.drawing import sheet as SH
    sh = SH.Sheet(dxf, template_map=str(map_json))
    sh.fill(EXAMPLE["fields"])
    sh.set_weight(EXAMPLE["volume_mm3"], EXAMPLE["density_g_cm3"])
    sh.blank_placeholders()
    index = 1
    for rev, desc, date, who, rows in EXAMPLE["revisions"]:
        sh.revision_row(index, rev, desc, who, date=date, height=rows * sh.map["revision_table"]["row_height"])
        index += rows
    nl = sh.map["notes_label"]["insert"]
    sh.notes((nl[0], nl[1] - 5.0), None, EXAMPLE["notes"], h=2.5, width_mm=118.0)
    clashes = sh.lint()
    stem = Path(dxf).stem + "-example"
    sh.render(Path(out_dir) / f"{stem}.pdf", Path(png_dir) / f"{stem}.png", dpi=200, title=f"example {stem}")
    return list(sh.issues), clashes


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True, help="folder for the DXF, JSON map and PDF previews")
    ap.add_argument("--png-dir", default=None, help="folder for the PNG previews (default: a temp folder)")
    ap.add_argument("--only", nargs="*", default=None, help="template names to write (default: all four)")
    ap.add_argument("--no-preview", action="store_true")
    ap.add_argument("--example", action="store_true", help="also write a filled example PDF of each first sheet")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    png_dir = Path(args.png_dir) if args.png_dir else Path(tempfile.gettempdir()) / "ah-drawing-templates"
    png_dir.mkdir(parents=True, exist_ok=True)
    names = args.only or ["AH-B-mm-sheet1", "AH-B-mm-sheetN", "AH-B-in-sheet1", "AH-B-in-sheetN"]
    failed = False
    for name in names:
        _, _, units, sheet = name.split("-")
        t = Template(name, units, sheet[-1]).build()
        dxf, mp = t.save(out)
        print("wrote", dxf.name, "fields", len(t.map["fields"]), "fixed", len(t.map["fixed_texts"]))
        if not args.no_preview:
            issues, lint = render_preview(dxf, mp, out, png_dir)
            print("  preview issues:", issues or "none")
            print("  lint:", lint or "clean")
            failed = failed or bool(issues or lint)
        if args.example and sheet[-1] == "1":
            issues, lint = write_example(dxf, mp, out, png_dir)
            print("  example issues:", issues or "none")
            print("  example lint:", lint or "clean")
            failed = failed or bool(issues or lint)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
