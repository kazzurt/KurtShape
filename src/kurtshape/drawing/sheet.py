"""Drawing sheet on a DXF template, drafted with ezdxf (MIT), rendered to PDF with matplotlib.

Coordinates: the template sheet lives in DXF modelspace at 1:1 paper millimetres. A view is
placed with :meth:`Sheet.place` at a sheet origin and a scale; every annotation method takes
points in that view's true-size coordinates (``pv``) or plain sheet coordinates.
Dimensions are real DIMENSION entities whose dimstyle carries DIMLFAC = 1/scale, so they read
true size in any CAD program.

What the sheet checks, so a drawing cannot silently say something the model does not:

- every dimension's definition points lie on the projected view geometry or at the centre of
  one of its circles or arcs (inside the detail circle for a detail view); radius dimensions
  need a real arc of that radius and centre;
  angular dimensions check a point on each leg;
- the rendered dimension text equals the text the spec expects (``expect=``);
- hatch loops are closed and non-degenerate;
- :meth:`Sheet.lint` finds text that touches other text, view geometry, frames or hatching.

A sheet also enforces the Aerial Hedra engineering drawing standard (``STANDARD_DOC``; read it
before writing a spec): notes on sheet 1 only and never repeating the title block or a callout,
no loose text, complete hole and thread callouts (:meth:`Sheet.callout`, :meth:`Sheet.hole_callout`),
radial leaders to holes with centre marks, no crossing leaders, view labels that carry only the
view's name (:meth:`Sheet.view_label`), sections and details paired with their cutting-plane line
and detail circle, one scale, a stated weight (:meth:`Sheet.set_weight`), and a clear title block.
``Sheet(..., standard=False)`` (or ``sheet.standard = False`` after a helper opens the sheet) is for
the script of a drawing released before the standard, until that drawing is next revised.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import sys

from . import VENDOR_DIRNAME

_ROOT = Path(__file__).resolve().parents[3]          # the KurtShape checkout
_VENDOR = _ROOT / "runtime" / "vendor" / VENDOR_DIRNAME
_CACHE = _ROOT / "runtime" / "vendor" / (VENDOR_DIRNAME + "-cache")
if _VENDOR.is_dir() and str(_VENDOR) not in sys.path:
    sys.path.append(str(_VENDOR))                       # appended: the runtime's numpy etc. win
os.environ.setdefault("XDG_CACHE_HOME", str(_CACHE))    # private ezdxf font cache (a stale user cache mismatches fonts)

import ezdxf                                            # noqa: E402
from ezdxf import recover                               # noqa: E402
from ezdxf.enums import MTextEntityAlignment            # noqa: E402

TEMPLATES = Path(__file__).resolve().parent / "templates"

LATIN_FONT = ("AH-LATIN", "NotoSans-Regular.ttf", "Noto Sans")
LATIN_BOLD = ("AH-LATIN-BOLD", "NotoSans-Bold.ttf", "Noto Sans")
CJK_FONT = ("AH-CJK", "msyh.ttc", "Microsoft YaHei")

LAYERS = {   # name: (lineweight 1/100 mm, linetype)
    "AH_VISIBLE": (50, "CONTINUOUS"),
    "AH_THIN": (25, "CONTINUOUS"),
    "AH_HIDDEN": (25, "AH_HIDDEN"),
    "AH_CENTER": (18, "AH_CENTER"),
    "AH_HATCH": (18, "CONTINUOUS"),
    "AH_DIM": (18, "CONTINUOUS"),
    "AH_TEXT": (25, "CONTINUOUS"),
    "AH_CUTLINE": (50, "CONTINUOUS"),
}
STYLE_LAYER = {"visible": "AH_VISIBLE", "section": "AH_VISIBLE", "smooth": "AH_THIN", "hidden": "AH_HIDDEN",
               "thin": "AH_THIN", "center": "AH_CENTER"}

DIM_TEXT = 3.0          # ASME Y14.2: 3 mm minimum for dimensions, tolerances and notes on A-C sizes
TOL_FACTOR = 1.0        # tolerances at the dimension's own height
ARROW = 2.5
PT_PER_MM = 72.0 / 25.4  # ezdxf's matplotlib backend takes lineweights in points
MIN_LINEWEIGHT = 0.13    # mm, the thinnest ISO 128 line
GEOMETRY_LAYERS = ("AH_VISIBLE", "AH_THIN", "AH_HIDDEN", "AH_CENTER", "AH_CUTLINE")

# ---- Aerial Hedra engineering drawing standard (Kurt Zeller, 2026-11-11) --------------------
# The rules are written in STANDARD_DOC. A Sheet enforces the ones a program can decide: lint()
# reports them (kinds in STANDARD_KINDS) and save() refuses a sheet that has any. A drawing
# released before the standard passes Sheet(..., standard=False) until it is next revised.
STANDARD = "Aerial Hedra drawing standard 2026-11-11"
STANDARD_DOC = r"C:\Users\Kurtz\Documents\Dodec\Drawing Template\Engineering Drawing Standard.md"
STANDARD_HINT = (f" Read {STANDARD_DOC}. The script of a drawing released before 2026-11-11 may switch the "
                 "standard off until that drawing is next revised: Sheet(..., standard=False), or "
                 "sheet.standard = False right after a helper opens the sheet. A new or revised drawing never does.")
SCALE_SERIES = (0.05, 0.1, 0.2, 0.25, 0.5, 1.0, 2.0, 4.0, 5.0, 10.0, 20.0)   # 1:20 ... 20:1
WAIVABLE = ("leader-extension",)      # findings Sheet.allow() may waive, with a stated reason
STANDARD_KINDS = (
    "loose-text", "note-title-block", "note-thread", "note-sheet-reference", "right-hand",   # rules 1-3
    "leader-not-radial", "hole-no-centre-mark",                                              # rule 4
    "leader-leader", "leader-dimension", "leader-extension", "unused-waiver",                # rule 5
    "view-label", "section-line", "detail-circle", "view-arrow",                             # rules 6-7
    "scale", "weight",                                                                       # rules 8, 10
    "title-block", "revision-table", "outside-frame",                                        # rule 11
)
_UN_THREAD = re.compile(r"(\d+/\d+|\d+ \d+/\d+|#\d+|\d*\.\d+|\d+)-\d+ UN[A-Z]{0,2}-[123][AB]( LH)?")
_M_THREAD = re.compile(r"M\d+(\.\d+)?( ?[x×] ?\d+(\.\d+)?)?-\d[A-Za-z](\d[A-Za-z])?( LH)?")
_THREAD_IN_TEXT = re.compile(r"(?<![\d.])(\d+/\d+|#\d+|\d*\.?\d+)\s*-\s*\d+(\.\d+)?\s*UN[A-Z]*|\bM\d+(\.\d+)?\s*[X×]\s*\d",
                             re.I)
_VIEW_NAME = re.compile(r"[A-Z0-9][A-Z0-9 \-]*")
_SYMBOL_TOKEN = re.compile(r"(\{cbore\}|\{csink\}|\{depth\})")


class DrawingError(RuntimeError):
    pass


@dataclass
class Placed:
    view: object
    origin: tuple
    scale: float
    name: str
    clip: tuple = None        # (centre_view_xy, radius_view) for detail views
    kind: str = "view"        # view | section | detail
    letter: str = None        # section or detail letter
    parent_sheet: int = None  # sheet that carries the cutting-plane line / detail circle, when not this one
    scale_reason: str = None  # why this view is not at the sheet scale (standard rule 8)

    def s(self, p):
        return (self.origin[0] + self.scale * p[0], self.origin[1] + self.scale * p[1])


def _fmt(v, dec):
    return f"{v:.{dec}f}"


def scale_text(scale):
    """A view scale as printed: 2:1, 1:2."""
    return f"{scale:g}:1" if scale >= 1.0 else f"1:{1.0 / scale:g}"


def weight_text(grams, units):
    """Part weight as the title block states it (standard rule 10): pounds on inch drawings;
    kilograms on metric drawings, grams under 0.100 kg. Never 'REF'."""
    if units == "in":
        return f"{grams / 453.59237:.3f} lb"
    if grams < 100.0:
        return f"{grams:.1f} g" if grams < 10.0 else f"{grams:.0f} g"
    return f"{grams / 1000.0:.3f} kg"


class Sheet:
    def __init__(self, template, template_map="aerial_hedra_b_mm.json", lang="en", standard=True):
        """``standard``: enforce the Aerial Hedra drawing standard (STANDARD_DOC). False is for a
        drawing released before 2026-11-11, until it is next revised."""
        self.lang = lang
        self.standard = bool(standard)
        self.scale = None             # the sheet scale: the title block's SCALE (fill) or set_scale()
        self.sheet_no = None          # from the SHEET field ("2 OF 3")
        self.sheet_total = None
        self._placed = []             # every Placed view, in order
        self._labelled = set()        # id(Placed) of views that have a view_label
        self._cut_letters = {}        # cutting-plane letter -> sheet of its section view (None: this sheet)
        self._detail_letters = {}     # detail-circle letter -> sheet of its detail view (None: this sheet)
        self._view_letters = set()    # letters of viewing-direction arrows (auxiliary views, this sheet)
        self._notes_items = []
        self._rev_bottom = None       # y under the lowest revision row the drawing added
        self._revision_form_fields = []
        self._allow = []              # waivers given with allow()
        self._fitted_circles = []     # (sheet centre, sheet radius) of B-spline loops accepted as holes
        self.map = json.loads((TEMPLATES / template_map).read_text(encoding="utf-8"))
        self.is_continuation = (("notes_label" in self.map and self.map["notes_label"] is None)
                                or str(self.map.get("sheet", "1")) != "1")
        self.units = self.map.get("units", "mm")        # "mm" or "in": how dimension values print (paper stays mm)
        self.dec = 3 if self.units == "in" else 2       # default decimals for dimensions and tolerances
        self.doc, auditor = recover.readfile(str(template))
        self.doc.audit()
        self.doc.dxfversion = "AC1032"          # R2018: UTF-8 text (CJK) without \U+ escapes
        h = self.doc.header
        h["$INSUNITS"] = 4
        h["$MEASUREMENT"] = 1
        h["$LTSCALE"] = 1.0
        h["$PSLTSCALE"] = 1
        h["$LUNITS"] = 2
        h["$DIMDSEP"] = ord(".")
        self.msp = self.doc.modelspace()
        self._template_handles = {e.dxf.handle for e in self.msp}
        self._touched = set()     # template texts the drawing rewrote: lint tests them like its own texts
        self._owner = {}          # entity handle -> annotation group (lint skips a group's own parts)
        self._group_seq = 0
        self.logo = self._logo_png()
        self._setup_styles()
        self._dimstyles = {}
        self.checks = []          # dimension definition-point and text checks (for the report)
        self.issues = []
        self._fonts = {}

    # ------------------------------------------------------------------ setup
    def _setup_styles(self):
        d = self.doc
        for name, font, family in (LATIN_FONT, LATIN_BOLD, CJK_FONT):
            if name not in d.styles:
                st = d.styles.add(name, font=font)
                st.set_extended_font_data(family=family, bold=(name == LATIN_BOLD[0]))
        # Onshape's family-only styles fall back to odd faces in ezdxf; pin them to Noto Sans.
        for st in d.styles:
            font = (st.dxf.get("font", "") or "").strip()
            if font in ("", "Noto Sans"):
                st.dxf.font = "NotoSans-Regular.ttf"
        if "AH_CENTER" not in d.linetypes:
            d.linetypes.add("AH_CENTER", pattern=[16.0, 10.0, -2.0, 2.0, -2.0], description="Centre ___ _ ___")
        if "AH_HIDDEN" not in d.linetypes:
            d.linetypes.add("AH_HIDDEN", pattern=[4.5, 3.0, -1.5], description="Hidden __ __")
        for name, (lw, lt) in LAYERS.items():
            if name not in d.layers:
                d.layers.add(name, color=7, linetype=lt, lineweight=lw)
        for name, lw in self.map.get("lineweights", {}).items():
            if name in d.layers:
                d.layers.get(name).dxf.lineweight = lw
        for handle in self.map.get("projection_symbol_handles", []):
            e = d.entitydb.get(handle)
            if e is not None:
                e.dxf.lineweight = 30
        self.text_style = CJK_FONT[0] if self.lang == "zh" else LATIN_FONT[0]

    def dimstyle(self, scale):
        key = (scale, self.lang)
        if key in self._dimstyles:
            return self._dimstyles[key]
        name = f"AH-{self.lang.upper()}-{str(scale).replace('.', 'p')}"
        ds = self.doc.dimstyles.new(name)
        dx = ds.dxf
        dx.dimtxsty = self.text_style
        dx.dimtxt = DIM_TEXT
        dx.dimasz = ARROW
        dx.dimexo = 1.0
        dx.dimexe = 1.5
        dx.dimgap = 0.8
        dx.dimtad = 1
        dx.dimtih = 0
        dx.dimtoh = 0
        dx.dimdec = self.dec
        dx.dimtdec = self.dec
        dx.dimadec = 0
        # inch sheets print ASME style without a leading zero (.500); the model stays in mm, so
        # DIMLFAC also converts 25.4 mm to 1.000 (tolerances are given in inches by the spec)
        dx.dimzin = 4 if self.units == "in" else 0
        dx.dimtzin = 4 if self.units == "in" else 0
        dx.dimazin = 0
        dx.dimtfac = TOL_FACTOR
        dx.dimlfac = 1.0 / scale / (25.4 if self.units == "in" else 1.0)
        dx.dimscale = 1.0
        dx.dimdsep = ord(".")
        dx.dimcen = 0
        dx.dimtmove = 0
        dx.dimlunit = 2
        dx.dimaunit = 0
        dx.dimtolj = 1
        dx.dimlwd = 18
        dx.dimlwe = 18
        dx.dimclrd = dx.dimclre = dx.dimclrt = 7
        self._dimstyles[key] = name
        return name

    # ------------------------------------------------------------------ annotation groups
    @contextmanager
    def group(self, name=None):
        """Entities added inside the block form one annotation (lint does not test its parts
        against each other: a leader against its own note, a frame against its own value)."""
        self._group_seq += 1
        gid = getattr(self, "_inner_group", None) or f"{name or 'group'}#{self._group_seq}"
        start = len(self.msp)
        yield gid
        for e in list(self.msp)[start:]:
            self._owner.setdefault(e.dxf.handle, gid)

    def touch(self, handle):
        """Mark a template text the drawing rewrote, so lint checks it."""
        self._touched.add(handle)

    # ------------------------------------------------------------------ text helpers
    def style_for(self, content):
        return CJK_FONT[0] if _has_cjk(content or "") else self.text_style

    def text(self, pos, content, h=2.5, attach="TOP_LEFT", style=None, layer="AH_TEXT", rotation=0.0, width=0.0,
             mask=False):
        e = self.msp.add_mtext(content, dxfattribs={"style": style or self.style_for(content), "char_height": h,
                                                     "layer": layer, "insert": pos, "width": width,
                                                     "rotation": rotation})
        e.dxf.attachment_point = getattr(MTextEntityAlignment, attach)
        if mask:
            e.set_bg_color("canvas", scale=1.2)
        if _has_cjk(content) and e.dxf.style != CJK_FONT[0]:
            raise DrawingError(f"CJK text in a non-CJK style: {content!r}")
        return e

    def line(self, p, q, layer="AH_THIN", lw=None):
        attrs = {"layer": layer}
        if lw is not None:
            attrs["lineweight"] = lw
        return self.msp.add_line(p, q, dxfattribs=attrs)

    def font(self, style, h):
        """ezdxf font measurer for a text style at cap height h."""
        key = (style, round(h, 4))
        if key not in self._fonts:
            from ezdxf.fonts import fonts
            file = {LATIN_FONT[0]: LATIN_FONT[1], LATIN_BOLD[0]: LATIN_BOLD[1], CJK_FONT[0]: CJK_FONT[1]}.get(
                style, LATIN_FONT[1])
            self._fonts[key] = fonts.make_font(file, cap_height=h)
        return self._fonts[key]

    def text_width(self, s, h, style=None):
        return self.font(style or self.style_for(s), h).text_width(s)

    # ------------------------------------------------------------------ views
    def place(self, view, origin, scale, name=None, styles=("visible", "section", "smooth"), clip=None,
              hatch=True, hatch_scale=0.7, smooth_layer="AH_THIN", letter=None, parent_sheet=None,
              scale_reason=None):
        """Put a view on the sheet. ``clip=(centre, r)`` makes a detail view. Under the standard:

        - ``scale`` comes from SCALE_SERIES, and a view that is not a detail and not at the sheet
          scale states why in ``scale_reason`` (rule 8);
        - a section view (one with cut faces) and a detail view carry their ``letter``; its
          cutting-plane line or detail circle is on this sheet, or on ``parent_sheet`` (rule 7)."""
        kind = "detail" if clip else ("section" if view.hatch else "view")
        pv = Placed(view, origin, scale, name or view.name, clip=clip, kind=kind, letter=letter,
                    parent_sheet=parent_sheet, scale_reason=scale_reason)
        if self.standard:
            if not any(abs(scale - s) <= 1e-9 * max(s, 1.0) for s in SCALE_SERIES) and not scale_reason:
                raise DrawingError(f"{pv.name}: scale {scale_text(scale)} is not a standard scale "
                                   f"({', '.join(scale_text(s) for s in SCALE_SERIES)}); rule 8 of {STANDARD}."
                                   + STANDARD_HINT)
            if kind != "view" and not letter:
                raise DrawingError(f"{pv.name}: a {kind} view needs its letter (place(..., letter='A')), matching "
                                   f"its {'detail circle' if kind == 'detail' else 'cutting-plane line'}; "
                                   f"rule 7 of {STANDARD}." + STANDARD_HINT)
        self._placed.append(pv)
        with self.group(f"view:{pv.name}"):
            for c in view.curves:
                if c.style not in styles:
                    continue
                layer = STYLE_LAYER[c.style] if c.style != "smooth" else smooth_layer
                self._draw_curve(pv, c, layer)
            if hatch and view.hatch:
                loops = view.hatch
                if clip:
                    loops = [l for l in (_clip_polygon_circle(lp, clip[0], clip[1]) for lp in loops) if len(l) >= 3]
                for lp in loops:
                    a = _area(lp)
                    if abs(a) < 1e-6:
                        raise DrawingError(f"{pv.name}: degenerate hatch loop (area {a:.2e} mm2)")
                    if not _is_simple(lp):
                        # e.g. a detail circle that splits a cut face in two: Sutherland-Hodgman
                        # joins the pieces with zero-width bridges
                        raise DrawingError(f"{pv.name}: hatch loop crosses or overlaps itself")
                h = self.msp.add_hatch(color=7, dxfattribs={"layer": "AH_HATCH"})
                h.set_pattern_fill("ANSI31", scale=hatch_scale, angle=0.0)
                for lp in loops:
                    h.paths.add_polyline_path([pv.s(p) for p in lp], is_closed=True)
            if clip:
                c, r = clip
                self.msp.add_circle(pv.s(c), r * scale, dxfattribs={"layer": "AH_THIN"})
        return pv

    def _draw_curve(self, pv, c, layer):
        if pv.clip:
            for seg in _clip_samples(c.sample(96) if c.kind != "line" else [c.p, c.q], *pv.clip):
                if len(seg) >= 2:
                    self.msp.add_lwpolyline([pv.s(p) for p in seg], dxfattribs={"layer": layer})
            return
        if c.kind == "line":
            self.msp.add_line(pv.s(c.p), pv.s(c.q), dxfattribs={"layer": layer})
        elif c.kind == "circle":
            self.msp.add_circle(pv.s(c.c), c.r * pv.scale, dxfattribs={"layer": layer})
        elif c.kind == "arc":
            self.msp.add_arc(pv.s(c.c), c.r * pv.scale, c.a0, c.a1, dxfattribs={"layer": layer})
        else:
            self.msp.add_lwpolyline([pv.s(p) for p in c.pts], dxfattribs={"layer": layer})

    def vline(self, pv, p, q, layer="AH_THIN"):
        """A line given in view coordinates (cosmetic thread lines, thread-limit lines)."""
        with self.group(f"view:{pv.name}"):
            if pv.clip:
                for seg in _clip_samples([p, q], *pv.clip):
                    if len(seg) >= 2:
                        self.msp.add_lwpolyline([pv.s(x) for x in seg], dxfattribs={"layer": layer})
                return
            self.msp.add_line(pv.s(p), pv.s(q), dxfattribs={"layer": layer})

    def centerline(self, pv, p, q, ext=3.0):
        a, b = pv.s(p), pv.s(q)
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy)
        ux, uy = dx / L, dy / L
        with self.group(f"view:{pv.name}"):
            self.msp.add_line((a[0] - ux * ext, a[1] - uy * ext), (b[0] + ux * ext, b[1] + uy * ext),
                              dxfattribs={"layer": "AH_CENTER"})

    def centre_mark(self, pv, centre, r, ext=2.0):
        """Centre lines through a circle seen end-on (view point ``centre``, view radius ``r``):
        two crossing lines reaching ``ext`` mm of paper beyond it. A centre line already running
        through the centre in that direction is not drawn twice."""
        c = pv.s(centre)
        half = r * pv.scale + ext
        have = self._centre_dirs(c)
        with self.group(f"view:{pv.name}"):
            for ang, (dx, dy) in ((0.0, (1.0, 0.0)), (math.pi / 2, (0.0, 1.0))):
                if any(min(abs(a - ang), math.pi - abs(a - ang)) < math.radians(1.0) for a in have):
                    continue
                self.msp.add_line((c[0] - dx * half, c[1] - dy * half), (c[0] + dx * half, c[1] + dy * half),
                                  dxfattribs={"layer": "AH_CENTER"})

    def _centre_dirs(self, c, tol=0.1):
        """Directions (0..pi) of the centre lines that pass through sheet point ``c``."""
        out = []
        for e in self.msp.query("LINE"):
            if e.dxf.layer != "AH_CENTER":
                continue
            a, b = (e.dxf.start[0], e.dxf.start[1]), (e.dxf.end[0], e.dxf.end[1])
            if _pt_seg_dist(c, a, b) < tol:
                out.append(math.atan2(b[1] - a[1], b[0] - a[0]) % math.pi)
        return out

    def label(self, pos, lines, h=3.5, attach="TOP_CENTER", sub_h=2.8):
        """Free-text view label. Under the standard a view is labelled with :meth:`view_label`,
        which writes only the view's name and, when it differs from the sheet's, its scale."""
        if self.standard:
            raise DrawingError(f"label() writes free text; label a view with view_label() (rule 6 of {STANDARD})."
                               + STANDARD_HINT)
        with self.group("label"):
            content = lines[0] if isinstance(lines, (list, tuple)) else lines
            e = self.text(pos, content, h=h, attach=attach)
            if isinstance(lines, (list, tuple)) and len(lines) > 1:
                self.text((pos[0], pos[1] - h * 1.6), "\\P".join(lines[1:]), h=sub_h, attach=attach)
        return e

    def set_scale(self, scale):
        """The sheet scale, for a template without a SCALE field (fill() reads it from SCALE)."""
        self.scale = float(scale)

    def view_label(self, pv, pos, name=None, rotated=None, h=3.5, sub_h=2.8, attach="TOP_CENTER"):
        """Label of a placed view (standard rule 6): its name and nothing else.

        - a section reads SECTION A-A and a detail DETAIL B, from the view's letter; any other
          view takes ``name`` (at most four words: FRONT VIEW, ISOMETRIC);
        - '(SHEET n)' follows when the cutting-plane line or detail circle is on another sheet;
        - ``rotated`` ('20.9° CW') is stated for a view turned out of projection;
        - the scale is printed only when it differs from the sheet scale.

        On a sheet in another language pass the whole title as ``name``."""
        if self.scale is None:
            raise DrawingError("fill the title block SCALE (or call set_scale) before labelling views")
        if self.lang == "en" and pv.kind == "section":
            title = f"SECTION {pv.letter}-{pv.letter}"
        elif self.lang == "en" and pv.kind == "detail":
            title = f"DETAIL {pv.letter}"
        elif self.lang == "en" and pv.kind == "view" and pv.letter and not name:
            title = f"VIEW {pv.letter}"                   # an auxiliary view named by its arrow
        else:
            if not name:
                raise DrawingError(f"{pv.name}: view_label needs a name for this view")
            if self.lang == "en" and (not _VIEW_NAME.fullmatch(name) or len(name.split()) > 4):
                raise DrawingError(f"view name {name!r}: at most four words of capitals and digits; what a view "
                                   f"shows is read from the view, not from its label (rule 6 of {STANDARD})")
            title = name
        if pv.parent_sheet:
            title += f" (SHEET {pv.parent_sheet})"
        sub = []
        if rotated:
            sub.append(f"ROTATED {rotated}")
        if abs(pv.scale - self.scale) > 1e-9:
            sub.append(f"SCALE {scale_text(pv.scale)}")
        with self.group("view-label"):
            e = self.text(pos, title, h=h, attach=attach)
            if sub:
                self.text((pos[0], pos[1] - h * 1.6), "\\P".join(sub), h=sub_h, attach=attach)
        self._labelled.add(id(pv))
        return e

    # ------------------------------------------------------------------ verification
    def _verify(self, pv, pts, what, tol=0.01):
        for p in pts:
            d = pv.view.distance(p)
            rec = {"dim": what, "view": pv.name, "point": [round(p[0], 4), round(p[1], 4)], "distance": round(d, 6)}
            if pv.clip:
                rec["inside_detail"] = math.hypot(p[0] - pv.clip[0][0], p[1] - pv.clip[0][1]) <= pv.clip[1] + 1e-9
            if d > tol and any(c.kind in ("circle", "arc") and math.hypot(p[0] - c.c[0], p[1] - c.c[1]) <= tol
                               for c in pv.view.curves):
                rec["on"] = "centre of a circle or arc"      # a hole is located by its centre
                d = 0.0
            elif d > tol and any(math.hypot(pv.s(p)[0] - c[0], pv.s(p)[1] - c[1]) <= tol * pv.scale
                                 for c, _ in self._fitted_circles):
                rec["on"] = "centre of a hole accepted with fit_tol"
                d = 0.0
            self.checks.append(rec)
            if d > tol:
                raise DrawingError(f"{what}: point {p} is {d:.4f} mm off the {pv.name} geometry")
            if pv.clip and not rec["inside_detail"]:
                raise DrawingError(f"{what}: point {p} lies outside detail {pv.name}")

    def _check_text(self, dim, expect, what):
        """Compare the rendered dimension text with what the spec expects."""
        got = _dim_text(dim.dimension)
        rec = {"dim": what, "text": got}
        if expect is not None:
            rec["expect"] = expect
            if _norm(got) != _norm(expect):
                self.checks.append(rec)
                raise DrawingError(f"{what}: dimension reads {got!r}, expected {expect!r}")
        self.checks.append(rec)
        return got

    # ------------------------------------------------------------------ dimensions
    def _tol(self, dim, tol):
        if tol is None:
            return
        kind = tol[0]
        if kind == "sym":
            dim.set_tolerance(tol[1], hfactor=TOL_FACTOR, dec=tol[2] if len(tol) > 2 else self.dec)
        elif kind == "dev":                   # ("dev", upper, lower)  e.g. ("dev", 0.08, 0)
            upper, lower = tol[1], tol[2]
            if lower > 0 or upper < 0:
                raise DrawingError(f"deviation tolerance must straddle zero: {tol}")
            dim.set_tolerance(upper, -lower, hfactor=TOL_FACTOR, dec=tol[3] if len(tol) > 3 else self.dec)
            # the zero deviation prints as '0' (ezdxf prints a nil deviation that way whatever
            # DIMTZIN says). That is ASME Y14.5's millimetre form; in inches Y14.5 wants the
            # other value's decimals and a sign ('+.00' over '-.02'): write that in the text.
            dim["dimtzin"] = 8 | (4 if self.units == "in" else 0)
        elif kind == "limits":
            dim.set_limits(tol[1], tol[2], hfactor=TOL_FACTOR, dec=tol[3] if len(tol) > 3 else self.dec)

    def dim_linear(self, pv, p1, p2, base, angle=0, text="<>", tol=None, dec=None, verify=True, what=None,
                   override=None, text_pos=None, expect=None, mask=False):
        """Linear dimension between view points p1, p2; ``base`` is a view point the dimension
        line passes through (angle 0 horizontal, 90 vertical). ``mask`` blanks the lines behind
        its text (DIMTFILL). ``dec`` defaults to the sheet's (2 for mm, 3 for inch)."""
        what = what or text
        dec = self.dec if dec is None else dec
        if verify:
            self._verify(pv, (p1, p2), what)
        a = math.radians(angle)
        gap = abs((p2[0] - p1[0]) * math.cos(a) + (p2[1] - p1[1]) * math.sin(a)) * pv.scale
        if gap < 2 * ARROW + 0.5:
            raise DrawingError(f"{what}: {gap:.2f} mm between extension lines cannot hold two {ARROW} mm arrows; "
                               "use a larger view scale or a detail view")
        ov = {"dimdec": dec, "dimtdec": dec}
        if mask:
            ov["dimtfill"] = 1
        ov.update(override or {})
        dim = self.msp.add_linear_dim(base=pv.s(base), p1=pv.s(p1), p2=pv.s(p2), angle=angle, text=text,
                                      dimstyle=self.dimstyle(pv.scale), override=ov,
                                      dxfattribs={"layer": "AH_DIM"})
        self._tol(dim, tol)
        if text_pos is not None:
            dim.set_location(pv.s(text_pos), leader=False)
        dim.render()
        self._check_text(dim, expect, what)
        if text_pos is not None:
            self._extend_to_text(dim, pv, p1, p2, base, angle)
        return dim

    def _extend_to_text(self, dim, pv, p1, p2, base, angle):
        """A value moved beyond the extension lines along its dimension line gets the dimension
        line carried on to it (ASME Y14.5), so it cannot be read as belonging to something else."""
        geoms = [_mtext_geom(ve) for ve in dim.dimension.virtual_entities() if ve.dxftype() == "MTEXT"]
        if not geoms or geoms[0] is None:
            return
        a = math.radians(angle)
        ux, uy = math.cos(a), math.sin(a)
        b = pv.s(base)
        ends = sorted((pv.s(p)[0] * ux + pv.s(p)[1] * uy) for p in (p1, p2))
        # the value's extent along the dimension line, from its real (possibly turned) corners
        proj = [c[0] * ux + c[1] * uy for c in geoms[0][0]]
        lo, hi = min(proj), max(proj)
        offset = b[0] * -uy + b[1] * ux                       # the dimension line, across its direction
        if lo > ends[1]:
            start, stop = ends[1], lo - 0.8
        elif hi < ends[0]:
            start, stop = ends[0], hi + 0.8
        else:
            return                                              # the value sits between the extension lines
        line = self.msp.add_line((start * ux - offset * uy, start * uy + offset * ux),
                                 (stop * ux - offset * uy, stop * uy + offset * ux), dxfattribs={"layer": "AH_DIM"})
        self._owner[line.dxf.handle] = dim.dimension.dxf.handle + "/own"

    def _fitted_arcs(self, pv, centre, r, fit_tol):
        """Polylines of the view (projected B-spline edges, e.g. the cut edge of a rolling-ball
        fillet in its symmetry plane) whose every point lies within ``fit_tol`` mm of the circle
        (centre, r). Returns [(max deviation, swept angle in degrees)]."""
        out = []
        for c in pv.view.curves:
            if c.kind != "poly" or len(c.pts) < 3:
                continue
            devs = [abs(math.hypot(p[0] - centre[0], p[1] - centre[1]) - r) for p in c.pts]
            if max(devs) <= fit_tol:
                angs = [math.atan2(p[1] - centre[1], p[0] - centre[0]) for p in (c.pts[0], c.pts[-1])]
                sweep = abs(math.degrees((angs[1] - angs[0] + math.pi) % (2 * math.pi) - math.pi))
                out.append((max(devs), sweep))
        return out

    def _full_circle(self, pv, centre, r, fit_tol=None, tol=1e-3):
        """A full circle (view centre, radius) in the view: a circle curve, or with ``fit_tol`` a
        closed polyline (a projected B-spline loop, as STEP files often carry an oblique hole's
        edge) whose every point lies within fit_tol of it. Returns a check record or None."""
        if any(c.kind == "circle" and abs(c.r - r) < tol and math.hypot(c.c[0] - centre[0], c.c[1] - centre[1]) < tol
               for c in pv.view.curves):
            return {"circle_found": True}
        if fit_tol is None:
            return None
        if not 0.0 < fit_tol <= 0.02:
            raise DrawingError("fit_tol is a fitting tolerance for B-spline circles: 0 to 0.02 mm")
        for c in pv.view.curves:
            if c.kind != "poly" or len(c.pts) < 8 or math.hypot(c.pts[0][0] - c.pts[-1][0], c.pts[0][1] - c.pts[-1][1]) > 1e-6:
                continue
            devs = [abs(math.hypot(p[0] - centre[0], p[1] - centre[1]) - r) for p in c.pts]
            if max(devs) <= fit_tol:
                self._fitted_circles.append((pv.s(centre), r * pv.scale))
                return {"circle_found": True, "fitted_bspline_loop_max_deviation_mm": round(max(devs), 5)}
        # a loop split into several open B-spline pieces (a radial hole in a tube projects its
        # saddle edge as two halves): the pieces lying on the circle must cover all 360 degrees
        bins = [False] * 360
        worst, pieces = 0.0, 0
        for c in pv.view.curves:
            if c.kind != "poly" or len(c.pts) < 2:
                continue
            devs = [abs(math.hypot(p[0] - centre[0], p[1] - centre[1]) - r) for p in c.pts]
            if max(devs) > fit_tol:
                continue
            pieces += 1
            worst = max(worst, max(devs))
            angs = [math.degrees(math.atan2(p[1] - centre[1], p[0] - centre[0])) for p in c.pts]
            for a0, a1 in zip(angs, angs[1:]):
                d = (a1 - a0 + 180.0) % 360.0 - 180.0           # the short way between neighbours
                n = max(1, int(abs(d) * 4))
                for k in range(n + 1):
                    bins[int(math.floor((a0 + d * k / n) % 360.0)) % 360] = True
        if pieces and all(bins):
            self._fitted_circles.append((pv.s(centre), r * pv.scale))
            return {"circle_found": True, "fitted_bspline_pieces": pieces,
                    "fitted_bspline_loop_max_deviation_mm": round(worst, 5)}
        return None

    def dim_radius(self, pv, centre, r, angle, text="<>", tol=None, dec=None, location=None, verify=True, what=None,
                   expect=None, fit_tol=None):
        """Radius dimension. ezdxf writes the 'R' prefix itself, so ``text`` holds only what goes
        around the value ('4X <>'); the old default 'R<>' printed 'RR'. The view must hold an arc
        of that radius and centre; with ``fit_tol`` (mm, at most 0.02) a projected B-spline edge
        whose points all lie that close to the circle also counts (a fillet modelled as a
        B-spline surface), and its deviation is recorded."""
        what = what or text
        dec = self.dec if dec is None else dec
        if fit_tol is not None and not 0.0 < fit_tol <= 0.02:
            raise DrawingError("fit_tol is a fitting tolerance for B-spline arcs: 0 to 0.02 mm")
        if verify:
            a = math.radians(angle)
            self._verify(pv, ((centre[0] + r * math.cos(a), centre[1] + r * math.sin(a)),), what,
                         tol=max(0.01, fit_tol or 0.0))
            arcs = [c for c in pv.view.curves if c.kind in ("arc", "circle") and abs(c.r - r) < 1e-4
                    and math.hypot(c.c[0] - centre[0], c.c[1] - centre[1]) < 1e-4]
            fitted = self._fitted_arcs(pv, centre, r, fit_tol) if (fit_tol and not arcs) else []
            rec = {"dim": what, "view": pv.name, "arc_found": bool(arcs)}
            if fitted:
                rec["fitted_bspline_arcs"] = [{"max_deviation_mm": round(d, 5), "sweep_deg": round(s, 2)}
                                              for d, s in fitted]
            self.checks.append(rec)
            if not arcs and not fitted:
                raise DrawingError(f"{what}: no arc of radius {r} centred at {centre} in {pv.name}")
        # horizontal (unidirectional) text on the leader, as radius callouts are read
        # (and lifted off the landing so the leader's leg clears the last character); no line from
        # the centre to the arc (DIMTOFL 0): a small radius is called out from outside only
        # DIMLFAC as dimstyle() sets it: true size, and inches on an inch sheet (the override used to
        # drop the 25.4 and printed an inch sheet's radii in millimetres)
        lfac = 1.0 / pv.scale / (25.4 if self.units == "in" else 1.0)
        ov = {"dimdec": dec, "dimtdec": dec, "dimtmove": 1, "dimlfac": lfac, "dimtih": 1, "dimtoh": 1,
              "dimgap": 2.0, "dimtofl": 0}
        dim = self.msp.add_radius_dim(center=pv.s(centre), radius=r * pv.scale, angle=angle, text=text,
                                      dimstyle=self.dimstyle(pv.scale), override=ov, dxfattribs={"layer": "AH_DIM"})
        self._tol(dim, tol)
        if location is not None:
            dim.set_location(location, leader=True)
        dim.render()
        self._check_text(dim, expect, what)
        return dim

    def dim_diameter(self, pv, centre, r, angle, text="<>", tol=None, dec=None, location=None, verify=True,
                     what=None, expect=None, pattern=0, fit_tol=None):
        """Diameter dimension of a circle seen end-on (view point ``centre``, view radius ``r``);
        the dimension line runs through the centre at ``angle`` degrees, and ``location`` (sheet)
        moves the value outside on a leader. ezdxf writes the 'Ø' itself.

        With ``location`` the value is called out from outside, as a hole is (rule 4): one radial
        leader from the value to the near side of the circle, its arrow pointing in toward the
        centre. The leader's angle is then taken from the location (``angle`` is ignored), and no
        line is drawn across the circle (DIMTOFL 0; Kurt, 12 Nov 2026).

        The view must hold that circle: a full circle, or arcs of it on which both ends of the
        dimension line lie (a boss whose outline is broken into arcs); ``fit_tol`` as in
        :meth:`hole_callout`. ``pattern=n`` dimensions a bolt circle instead: n or more circle
        centres of the view must lie on it (0.01 mm), and its centre-line circle is drawn; holes
        are then located by their centres (rule 4)."""
        what = what or text
        dec = self.dec if dec is None else dec
        if verify:
            if pattern:
                on = [c for c in pv.view.curves if c.kind == "circle"
                      and abs(math.hypot(c.c[0] - centre[0], c.c[1] - centre[1]) - r) < 0.01]
                ctrs = {(round(c.c[0], 3), round(c.c[1], 3)) for c in on}
                self.checks.append({"dim": what, "view": pv.name, "pattern_centres": len(ctrs)})
                if len(ctrs) < pattern:
                    raise DrawingError(f"{what}: {len(ctrs)} circle centres lie on the bolt circle, {pattern} expected")
            else:
                rec = self._full_circle(pv, centre, r, fit_tol, tol=1e-4)
                if rec is None and any(c.kind == "arc" and abs(c.r - r) < 1e-4
                                       and math.hypot(c.c[0] - centre[0], c.c[1] - centre[1]) < 1e-4
                                       for c in pv.view.curves):
                    a = math.radians(angle)
                    ends = [(centre[0] + s * r * math.cos(a), centre[1] + s * r * math.sin(a)) for s in (1, -1)]
                    self._verify(pv, ends, what)          # both ends of the dimension line on the arcs
                    rec = {"arcs_found": True}
                self.checks.append({"dim": what, "view": pv.name, **(rec or {"circle_found": False})})
                if rec is None:
                    raise DrawingError(f"{what}: no circle of radius {r} centred at {centre} in {pv.name}")
        if pattern:
            with self.group(f"view:{pv.name}"):
                self.msp.add_circle(pv.s(centre), r * pv.scale, dxfattribs={"layer": "AH_CENTER"})
        lfac = 1.0 / pv.scale / (25.4 if self.units == "in" else 1.0)
        ov = {"dimdec": dec, "dimtdec": dec, "dimlfac": lfac, "dimtih": 1, "dimtoh": 1, "dimgap": 1.0}
        if location is not None:
            c = pv.s(centre)
            dx, dy = location[0] - c[0], location[1] - c[1]
            if math.hypot(dx, dy) < r * pv.scale + 3.0:
                raise DrawingError(f"{what}: the value's location lies inside the circle; a diameter called out "
                                   "from outside sits clear of it")
            # radial, meeting the near side: ezdxf puts a diameter's arrow at the far end of the
            # dimension angle, so the angle points away from the value
            angle = math.degrees(math.atan2(dy, dx)) + 180.0
            ov.update({"dimtmove": 1, "dimgap": 2.0, "dimtofl": 0})
        dim = self.msp.add_diameter_dim(center=pv.s(centre), radius=r * pv.scale, angle=angle, text=text,
                                        dimstyle=self.dimstyle(pv.scale), override=ov,
                                        dxfattribs={"layer": "AH_DIM"})
        self._tol(dim, tol)
        if location is not None:
            dim.set_location(location, leader=True)
        dim.render()
        self._check_text(dim, expect, what)
        return dim

    def dim_angle(self, pv, centre, p1, p2, base, text="<>", tol=None, dec=0, verify_pts=None, what=None,
                  leg_check=None, expect=None):
        """Angular dimension from p1 to p2 (counter-clockwise) about ``centre``; ``base`` is a view
        point on the dimension arc. ``leg_check`` (mm) also verifies a point that far along each
        leg from p1 and p2 (positive: away from the centre, negative: toward it), so the legs
        follow real edges, not just their end points."""
        what = what or text
        pts = list(verify_pts or [])
        if leg_check:
            for p in (p1, p2):
                L = math.hypot(p[0] - centre[0], p[1] - centre[1])
                pts.append((p[0] + leg_check * (p[0] - centre[0]) / L, p[1] + leg_check * (p[1] - centre[1]) / L))
        if pts:
            self._verify(pv, pts, what)
        ov = {"dimadec": dec, "dimtdec": dec}
        dim = self.msp.add_angular_dim_3p(base=pv.s(base), center=pv.s(centre), p1=pv.s(p1), p2=pv.s(p2),
                                          text=text, dimstyle=self.dimstyle(pv.scale), override=ov,
                                          dxfattribs={"layer": "AH_DIM"})
        self._tol(dim, tol)
        dim.render()
        self._check_text(dim, expect, what)
        return dim

    # ------------------------------------------------------------------ leaders, symbols
    def leader(self, target, text_pos, content, h=DIM_TEXT, side=None, pv=None, verify=True, what=None, arrow=True,
               group="leader"):
        """Leader from ``target`` (view point when pv is given, else sheet point) to a note at
        ``text_pos`` (sheet). The text sits on a short shoulder, left or right of the elbow.
        ``content`` is a string, or a list of lines as :meth:`callout` returns them (they may
        hold the symbol tokens ``{cbore}``, ``{csink}`` and ``{depth}``)."""
        lines = list(content) if isinstance(content, (list, tuple)) else None
        if pv is not None:
            if verify:
                self._verify(pv, (target,), what or (" / ".join(lines) if lines else content))
            t = pv.s(target)
        else:
            t = target
        side = side or ("right" if text_pos[0] >= t[0] else "left")
        shoulder = 3.0 if side == "right" else -3.0
        elbow = text_pos
        end = (elbow[0] + shoulder, elbow[1])
        with self.group(group):
            if arrow:
                self.msp.add_leader([t, elbow, end], dimstyle=self.dimstyle(1.0), dxfattribs={"layer": "AH_DIM"})
            else:
                self.msp.add_lwpolyline([t, elbow, end], dxfattribs={"layer": "AH_DIM"})
            if not content:
                return None
            if lines is None and not _SYMBOL_TOKEN.search(content):
                attach = "MIDDLE_LEFT" if side == "right" else "MIDDLE_RIGHT"
                tx = end[0] + (0.8 if side == "right" else -0.8)
                return self.text((tx, end[1]), content, h=h, attach=attach, layer="AH_DIM")
            return self._callout_text(end, side, lines if lines is not None else content.split("\n"), h)

    # ------------------------------------------------------------------ hole and thread callouts
    def num(self, value, dec=None):
        """A number as this sheet prints it: inches to three decimals without a leading zero
        (.500), millimetres without trailing zeros (12.5)."""
        if self.units == "in":
            s = f"{value:.{3 if dec is None else dec}f}"
            return s[1:] if s.startswith("0.") else ("-" + s[2:] if s.startswith("-0.") else s)
        s = f"{value:.{2 if dec is None else dec}f}"
        return s.rstrip("0").rstrip(".") if "." in s else s

    def callout(self, qty=None, thread=None, dia=None, tol=None, thru=False, depth=None, depth_qual=None,
                cbore=None, csink=None, extra=()):
        """Lines of a complete hole or thread callout (standard rule 3), for :meth:`hole_callout`
        or :meth:`leader`. Values are in the sheet's units.

        - ``thread``: the full designation with its class ('1/4-20 UNC-2B', 'M6x1-6H'). Right
          hand and the thread standard are implied and not written; a left-hand thread ends ' LH'.
        - ``dia`` (+ ``tol`` text such as '±.0005' or '+.005/-0') for a plain hole.
        - a hole or internal thread states ``thru=True`` or ``depth`` (``depth_qual``: 'MIN').
        - ``cbore=(dia, depth)`` or ``(dia, depth, tol)``; ``csink=(dia, angle_deg)``.
        - ``extra``: further lines ('EQ SP')."""
        if (thread is None) == (dia is None):
            raise DrawingError("a callout takes either thread= or dia=")
        if thread is not None:
            if not (_UN_THREAD.fullmatch(thread) or _M_THREAD.fullmatch(thread)):
                raise DrawingError(f"thread {thread!r}: give size, pitch or series, and class, e.g. '1/4-20 UNC-2B' or "
                                   f"'M6x1-6H' (' LH' for left hand); rule 3 of {STANDARD}")
            cls = thread.replace(" LH", "").rsplit("-", 1)[1]
            internal = cls[-1] == "B" if "UN" in thread else cls[-1].isupper()
            first = thread
        else:
            internal = True
            first = f"Ø{self.num(dia)}" + (f" {tol}" if tol else "")
        if thru and depth is not None:
            raise DrawingError("a callout is THRU or has a depth, not both")
        if internal and not thru and depth is None:
            raise DrawingError(f"callout {first!r}: a hole or internal thread states THRU or its depth; "
                               f"rule 3 of {STANDARD}")
        if qty and qty > 1:
            first = f"{int(qty)}X {first}"
        if thru:
            first += " THRU"
        elif depth is not None:
            first += f" {{depth}}{self.num(depth)}" + (f" {depth_qual}" if depth_qual else "")
        lines = [first]
        if cbore:
            lines.append(f"{{cbore}} Ø{self.num(cbore[0])}" + (f" {cbore[2]}" if len(cbore) > 2 and cbore[2] else "")
                         + f" {{depth}}{self.num(cbore[1])}")
        if csink:
            lines.append(f"{{csink}} Ø{self.num(csink[0])} × {csink[1]:g}°")
        lines.extend(extra)
        return lines

    def hole_callout(self, pv, centre, r, text_pos, lines, side=None, h=DIM_TEXT, what=None, fit_tol=None):
        """Callout of a hole seen straight down its axis (standard rule 4): the circle of view
        radius ``r`` at view point ``centre`` gets its centre mark, and the leader runs from the
        elbow at ``text_pos`` (sheet) radially to the near side of the circle, in line with the
        centre. ``lines`` come from :meth:`callout`. With ``fit_tol`` (mm, at most 0.02) a closed
        projected B-spline loop lying that close to the circle counts as the hole, and lint then
        tests the leader against it like any circle."""
        what = what or " / ".join(lines)
        rec = self._full_circle(pv, centre, r, fit_tol)
        self.checks.append({"dim": what, "view": pv.name, **(rec or {"circle_found": False})})
        if rec is None:
            raise DrawingError(f"{what}: no full circle of radius {r} centred at {centre} in {pv.name}; a hole "
                               "callout goes on the view that looks down the hole")
        if pv.clip and math.hypot(centre[0] - pv.clip[0][0], centre[1] - pv.clip[0][1]) + r > pv.clip[1]:
            raise DrawingError(f"{what}: the hole lies outside detail {pv.name}")
        c = pv.s(centre)
        radius = r * pv.scale
        dx, dy = text_pos[0] - c[0], text_pos[1] - c[1]
        dist = math.hypot(dx, dy)
        if dist < radius + 2 * ARROW:
            raise DrawingError(f"{what}: the callout's elbow must stand clear of the hole")
        tip = (c[0] + dx / dist * radius, c[1] + dy / dist * radius)
        self.centre_mark(pv, centre, r)
        return self.leader(tip, text_pos, lines, h=h, side=side, group="hole-callout")

    def _callout_text(self, end, side, lines, h):
        """Callout lines at a leader shoulder ending at ``end``; the tokens {cbore}, {csink} and
        {depth} are drawn as the ASME Y14.5 symbols. The block is centred on the shoulder."""
        gap = 0.3 * h
        sym_w = {"{cbore}": 1.6 * h, "{csink}": 1.6 * h, "{depth}": 0.6 * h}
        rows = []
        for ln in lines:
            parts = [p.strip() for p in _SYMBOL_TOKEN.split(ln)]
            parts = [p for p in parts if p]
            widths = [sym_w[p] if p in sym_w else self.text_width(p, h) for p in parts]
            rows.append((parts, widths, sum(widths) + gap * (len(parts) - 1)))
        pitch = 1.6 * h
        y = end[1] + pitch * (len(rows) - 1) / 2.0
        first = None
        for parts, widths, total in rows:
            x = end[0] + 0.8 if side == "right" else end[0] - 0.8 - total
            for p, w in zip(parts, widths):
                if p in sym_w:
                    self._callout_symbol(p, x, y, h)
                else:
                    e = self.text((x, y), p, h=h, attach="MIDDLE_LEFT", layer="AH_DIM")
                    first = first or e
                x += w + gap
            y -= pitch
        return first

    def _callout_symbol(self, token, x, y, h):
        """Counterbore, countersink or depth symbol with its left edge at x, centred on y."""
        lay = {"layer": "AH_DIM", "lineweight": 25}
        y += 0.08 * h                                     # a middle-attached text line sets that much high
        top, bot = y + 0.5 * h, y - 0.5 * h
        if token == "{cbore}":
            w, t = 1.6 * h, y + 0.3 * h
            for a, b in (((x, t), (x, bot)), ((x, bot), (x + w, bot)), ((x + w, bot), (x + w, t))):
                self.msp.add_line(a, b, dxfattribs=lay)
        elif token == "{csink}":
            w = 1.6 * h                                   # 90 degrees included: 0.8 h deep
            self.msp.add_line((x, y + 0.3 * h), (x + w / 2, bot), dxfattribs=lay)
            self.msp.add_line((x + w / 2, bot), (x + w, y + 0.3 * h), dxfattribs=lay)
        else:                                             # depth: a bar with an arrow down from it
            w = 0.6 * h
            xm = x + w / 2
            self.msp.add_line((x, top), (x + w, top), dxfattribs=lay)
            self.msp.add_line((xm, top), (xm, bot + 0.4 * h), dxfattribs=lay)
            head = self.msp.add_hatch(color=7, dxfattribs={"layer": "AH_DIM"})
            head.paths.add_polyline_path([(xm, bot), (xm - 0.2 * h, bot + 0.45 * h), (xm + 0.2 * h, bot + 0.45 * h)],
                                         is_closed=True)

    def fcf(self, pos, symbol, value, datums=(), h=DIM_TEXT, attach="left", mask=True):
        """Feature control frame (one row) with its lower-left corner at ``pos`` (sheet).
        ``symbol``: 'runout' | 'total_runout' | 'position' | 'perpendicularity' | 'concentricity'.
        ``mask`` blanks whatever lies under the frame (a WIPEOUT, e.g. a centre line).
        Returns (x0, y0, x1, y1)."""
        hh = h * 1.9
        vw = self.text_width(value, h, LATIN_FONT[0])
        cw = [hh] + [max(hh, vw + 2.4)] + [hh for _ in datums]
        x0, y0 = pos
        if attach == "right":
            x0 -= sum(cw)
        x = x0
        boxes = []
        for w in cw:
            boxes.append((x, y0, x + w, y0 + hh))
            x += w
        with self.group("fcf"):
            if mask:
                wo = self.msp.add_wipeout([(x0, y0), (x, y0), (x, y0 + hh), (x0, y0 + hh)])
                wo.dxf.layer = "AH_DIM"            # ezdxf's add_wipeout drops dxfattribs['layer']
            for bx in boxes:
                self.msp.add_lwpolyline([(bx[0], bx[1]), (bx[2], bx[1]), (bx[2], bx[3]), (bx[0], bx[3])], close=True,
                                        dxfattribs={"layer": "AH_DIM", "lineweight": 25})
            self._gdt_symbol(symbol, boxes[0], h)
            self.text(((boxes[1][0] + boxes[1][2]) / 2, y0 + hh / 2), value, h=h, attach="MIDDLE_CENTER",
                      style=LATIN_FONT[0], layer="AH_DIM")
            for bx, dtm in zip(boxes[2:], datums):
                self.text(((bx[0] + bx[2]) / 2, y0 + hh / 2), dtm, h=h, attach="MIDDLE_CENTER",
                          style=LATIN_FONT[0], layer="AH_DIM")
        return (x0, y0, x, y0 + hh)

    def fcf_width(self, value, datums=(), h=DIM_TEXT):
        hh = h * 1.9
        return hh + max(hh, self.text_width(value, h, LATIN_FONT[0]) + 2.4) + hh * len(datums)

    def _gdt_symbol(self, symbol, box, h):
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        s = h * 0.55
        lay = {"layer": "AH_DIM", "lineweight": 25}
        if symbol in ("runout", "total_runout"):
            # circular runout: one arrow at 45 deg; total runout: two arrows on a base line
            def arrow(ox):
                a, b = (cx - s * 0.75 + ox, cy - s * 0.85), (cx + s * 0.75 + ox, cy + s * 0.85)
                self.msp.add_line(a, b, dxfattribs=lay)
                ux, uy = (b[0] - a[0]), (b[1] - a[1])
                L = math.hypot(ux, uy)
                ux, uy = ux / L, uy / L
                tip = b
                w = s * 0.45
                base = (tip[0] - ux * w * 1.6, tip[1] - uy * w * 1.6)
                left = (base[0] - uy * w * 0.6, base[1] + ux * w * 0.6)
                right = (base[0] + uy * w * 0.6, base[1] - ux * w * 0.6)
                hatch = self.msp.add_hatch(color=7, dxfattribs={"layer": "AH_DIM"})
                hatch.paths.add_polyline_path([tip, left, right], is_closed=True)
            if symbol == "runout":
                arrow(0.0)
            else:
                arrow(-s * 0.45)
                arrow(s * 0.45)
                self.msp.add_line((cx - s * 1.3, cy - s * 0.85), (cx + s * 0.9, cy - s * 0.85), dxfattribs=lay)
        elif symbol == "perpendicularity":
            self.msp.add_line((cx - s, cy - s * 0.8), (cx + s, cy - s * 0.8), dxfattribs=lay)
            self.msp.add_line((cx, cy - s * 0.8), (cx, cy + s * 0.9), dxfattribs=lay)
        elif symbol == "concentricity":
            self.msp.add_circle((cx, cy), s * 0.9, dxfattribs=lay)
            self.msp.add_circle((cx, cy), s * 0.45, dxfattribs=lay)
        elif symbol == "position":
            self.msp.add_circle((cx, cy), s * 0.65, dxfattribs=lay)
            self.msp.add_line((cx - s, cy), (cx + s, cy), dxfattribs=lay)
            self.msp.add_line((cx, cy - s), (cx, cy + s), dxfattribs=lay)
        else:
            raise DrawingError(f"unknown GD&T symbol {symbol}")

    def datum(self, letter, frame_pos, foot, h=DIM_TEXT):
        """Datum feature symbol: square frame centred at ``frame_pos`` (sheet), stem down to a
        filled triangle whose base sits on ``foot`` (sheet point on the feature / its extension)."""
        a = h * 2.0
        x, y = frame_pos
        with self.group("datum"):
            self.msp.add_lwpolyline([(x - a / 2, y - a / 2), (x + a / 2, y - a / 2), (x + a / 2, y + a / 2),
                                     (x - a / 2, y + a / 2)], close=True, dxfattribs={"layer": "AH_DIM", "lineweight": 25})
            self.text((x, y), letter, h=h, attach="MIDDLE_CENTER", style=LATIN_FONT[0], layer="AH_DIM")
            fx, fy = foot
            top = (x, y - a / 2) if fy < y else (x, y + a / 2)
            self.msp.add_line(top, (fx, fy + (1.6 if fy < y else -1.6)), dxfattribs={"layer": "AH_DIM"})
            tri = [(fx - 1.6, fy), (fx + 1.6, fy), (fx, fy + (1.6 if fy < y else -1.6) * 1.0)]
            hatch = self.msp.add_hatch(color=7, dxfattribs={"layer": "AH_DIM"})
            hatch.paths.add_polyline_path(tri, is_closed=True)
            self.msp.add_lwpolyline(tri, close=True, dxfattribs={"layer": "AH_DIM"})

    def roughness(self, tip, value, direction=-90.0, h=DIM_TEXT):
        """Surface texture symbol (ISO 1302 / ASME Y14.36, material removal required) whose vertex
        touches the surface (or a leader shoulder) at ``tip`` (sheet). ``direction`` is the
        direction from the symbol toward the surface: -90 = standing on a surface below it,
        0 = against a surface on its right (read from the right of the sheet). The requirement
        ('Ra 0.8') sits under the horizontal bar, ISO 1302 position a. Symbols must read from the
        bottom or the right, so a surface above the symbol or on its left takes
        :meth:`roughness_leader`."""
        d = direction % 360.0
        if not (abs(d - 270.0) < 1e-9 or abs(d) < 1e-9):
            raise DrawingError(f"a roughness symbol at {direction} deg would read upside down or from the left; "
                               "use roughness_leader")
        rad = math.radians(d)
        ux, uy = math.cos(rad), math.sin(rad)        # toward the surface
        vx, vy = -uy, ux                              # along the surface, the reading direction
        hh = h * 1.4
        t30 = math.tan(math.radians(30))

        def P(a, b):  # a: away from the surface, b: along it
            return (tip[0] - ux * a + vx * b, tip[1] - uy * a + vy * b)
        tw = self.text_width(value, h, LATIN_FONT[0])
        short = P(hh, -hh * t30)
        longp = P(hh * 2.0, hh * 2.0 * t30)
        bar_end = P(hh * 2.0, hh * 2.0 * t30 + tw + 1.2)
        rot = math.degrees(math.atan2(vy, vx))
        with self.group("roughness"):
            lay = {"layer": "AH_DIM", "lineweight": 25}
            self.msp.add_line(short, tip, dxfattribs=lay)
            self.msp.add_line(tip, longp, dxfattribs=lay)
            self.msp.add_line(short, P(hh, hh * t30), dxfattribs=lay)       # closing bar: material removal
            self.msp.add_line(longp, bar_end, dxfattribs=lay)
            anchor = P(hh * 2.0 - 0.6, hh * 2.0 * t30 + 0.6)             # just under the bar, right of the leg
            self.text(anchor, value, h=h, attach="TOP_LEFT", style=LATIN_FONT[0], layer="AH_DIM", rotation=rot)

    def roughness_leader(self, target, elbow, value, h=DIM_TEXT, side="right"):
        """Surface texture symbol on a leader: arrowhead on the surface at ``target``, elbow at
        ``elbow`` (sheet), the symbol upright on the horizontal shoulder."""
        hh = h * 1.4
        tw = self.text_width(value, h, LATIN_FONT[0])
        length = hh * 2.0 * math.tan(math.radians(30)) + tw + 3.0
        sgn = 1.0 if side == "right" else -1.0
        end = (elbow[0] + sgn * length, elbow[1])
        x_tip = elbow[0] + sgn * 1.5 if side == "right" else end[0] + 1.5
        with self.group("roughness-leader") as gid:
            self.msp.add_leader([target, elbow, end], dimstyle=self.dimstyle(1.0), dxfattribs={"layer": "AH_DIM"})
            self._inner_group = gid                 # the symbol joins the leader's group
            try:
                self.roughness((x_tip, elbow[1]), value, direction=-90.0, h=h)
            finally:
                self._inner_group = None

    def cutting_plane(self, pv, p, q, letter, toward, h=4.0, view_sheet=None, arrow=7.0):
        """Section cutting-plane line between view points p, q with arrows pointing ``toward``
        (unit 2D direction of sight) and the section letter at both ends. ``view_sheet``: the
        sheet that carries the section view, when it is not this one (standard rule 7).
        ``arrow``: the arrow's length in sheet mm (shorter where a plane lies close to an edge)."""
        if arrow < 4.0:
            raise DrawingError("a cutting-plane arrow needs at least 4 mm for its 3 mm head")
        self._cut_letters[letter] = view_sheet
        a, b = pv.s(p), pv.s(q)
        ux, uy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(ux, uy)
        ux, uy = ux / L, uy / L
        seg = 6.0
        with self.group("cutting-plane"):
            for end, sgn in ((a, 1), (b, -1)):
                inner = (end[0] + sgn * ux * seg, end[1] + sgn * uy * seg)
                self.msp.add_line(end, inner, dxfattribs={"layer": "AH_CUTLINE"})
                head = (end[0] + toward[0] * arrow, end[1] + toward[1] * arrow)
                self.msp.add_line(end, head, dxfattribs={"layer": "AH_DIM"})
                w = 1.2
                base = (head[0] - toward[0] * 3.0, head[1] - toward[1] * 3.0)
                tri = [head, (base[0] - toward[1] * w, base[1] + toward[0] * w),
                       (base[0] + toward[1] * w, base[1] - toward[0] * w)]
                hatch = self.msp.add_hatch(color=7, dxfattribs={"layer": "AH_DIM"})
                hatch.paths.add_polyline_path(tri, is_closed=True)
                lp = (head[0] + toward[0] * 2.5 - sgn * ux * 2.5, head[1] + toward[1] * 2.5 - sgn * uy * 2.5)
                self.text(lp, letter, h=h, attach="MIDDLE_CENTER", style=LATIN_FONT[0], layer="AH_TEXT")
            self.msp.add_line(a, b, dxfattribs={"layer": "AH_CENTER"})

    def detail_circle(self, pv, centre, r, letter, label_at, h=4.0, view_sheet=None):
        """Circle on the parent view around the region a detail view enlarges, with the detail
        letter at ``label_at`` (sheet). ``view_sheet``: the sheet that carries the detail view,
        when it is not this one (standard rule 7)."""
        self._detail_letters[letter] = view_sheet
        c = pv.s(centre)
        with self.group("detail-circle"):
            self.msp.add_circle(c, r * pv.scale, dxfattribs={"layer": "AH_THIN"})
            self.text(label_at, letter, h=h, attach="MIDDLE_CENTER", style=LATIN_FONT[0], layer="AH_TEXT")

    def view_arrow(self, pv, tip, toward, letter, length=12.0, h=4.0):
        """Viewing-direction arrow for an auxiliary view (VIEW B): it ends at view point ``tip``,
        points along ``toward`` (sheet direction of sight) and carries the view's letter at its
        tail. The view itself is placed with ``place(..., letter=)`` on the same sheet and its
        :meth:`view_label` reads VIEW B (rule 7: lint pairs the two)."""
        self._view_letters.add(letter)
        L = math.hypot(*toward)
        ux, uy = toward[0] / L, toward[1] / L
        t = pv.s(tip)
        tail = (t[0] - ux * length, t[1] - uy * length)
        with self.group("view-arrow"):
            self.msp.add_line(tail, t, dxfattribs={"layer": "AH_DIM"})
            w, base = 1.2, (t[0] - ux * 3.0, t[1] - uy * 3.0)
            head = self.msp.add_hatch(color=7, dxfattribs={"layer": "AH_DIM"})
            head.paths.add_polyline_path([t, (base[0] - uy * w, base[1] + ux * w), (base[0] + uy * w, base[1] - ux * w)],
                                         is_closed=True)
            self.text((tail[0] - ux * 3.0, tail[1] - uy * 3.0), letter, h=h, attach="MIDDLE_CENTER",
                      style=LATIN_FONT[0], layer="AH_TEXT")

    # ------------------------------------------------------------------ title block / template text
    def fill(self, fields):
        for key, value in fields.items():
            spec = self.map["fields"].get(key)
            if spec is None:
                if key in {"APPROVED_NAME", "APPROVED_DATE"}:
                    if not str(value or "").strip():
                        continue  # Older specs may explicitly clear the removed title-block cells.
                    raise DrawingError(f"{key} was removed; put approval in revision_row()")
                raise DrawingError(f"template has no field {key}")
            e = self.doc.entitydb.get(spec["handle"])
            if e is None:
                raise DrawingError(f"field {key}: handle {spec['handle']} missing in template")
            e.text = value if value is not None else ""
            bold = e.dxf.style == LATIN_BOLD[0]          # a bold placeholder (DWG NO., REV) stays bold
            e.dxf.style = CJK_FONT[0] if _has_cjk(value or "") else (LATIN_BOLD[0] if bold else LATIN_FONT[0])
            if "ch" in spec:
                e.dxf.char_height = spec["ch"]
            if "width" in spec:
                e.dxf.width = spec["width"]
            self.touch(spec["handle"])
            if key == "SCALE":
                m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)\s*", value or "")
                self.scale = float(m.group(1)) / float(m.group(2)) if m and float(m.group(2)) else None
            elif key == "SHEET":
                m = re.fullmatch(r"\s*(\d+)\s+OF\s+(\d+)\s*", (value or "").upper())
                self.sheet_no, self.sheet_total = (int(m.group(1)), int(m.group(2))) if m else (None, None)

    def set_weight(self, volume_mm3, density_g_cm3):
        """Fill WEIGHT from the model (standard rule 10): pounds on an inch sheet; kilograms on a
        metric sheet, grams under 0.100 kg. Returns the text."""
        text = weight_text(volume_mm3 / 1000.0 * density_g_cm3, self.units)
        self.fill({"WEIGHT": text})
        return text

    def _field_text(self, key):
        spec = self.map.get("fields", {}).get(key)
        e = self.doc.entitydb.get(spec["handle"]) if spec else None
        return " ".join(e.plain_text().split()) if e is not None else ""

    def allow(self, kind, at, reason):
        """Waive one finding of a waivable kind (WAIVABLE: a leader that has to cross an extension
        line) near sheet point ``at``, with the reason. The waiver is listed in
        :meth:`standard_report`; one that waives nothing is itself a finding."""
        if kind not in WAIVABLE:
            raise DrawingError(f"{kind!r} cannot be waived (waivable: {', '.join(WAIVABLE)})")
        if not reason or len(reason.strip()) < 10:
            raise DrawingError("allow(): state the reason the layout cannot avoid it")
        self._allow.append({"kind": kind, "at": (float(at[0]), float(at[1])), "reason": reason.strip(), "used": False})

    def set_text(self, handle, value, min_height=None, inset=0.0):
        """Rewrite a fixed template text (by handle), switching to the CJK style for CJK. A
        leading padding run of the template ('{...\\W5.94; }', Onshape's centring) is kept;
        ``inset`` moves the text right (mm) off a cell border."""
        e = self.doc.entitydb.get(handle)
        if e is None:
            raise DrawingError(f"template text {handle} missing")
        old = e.text
        if old.startswith("{") and "}" in old and e.plain_text().startswith(" ") and value:
            value = old[:old.index("}") + 1] + value
        e.text = value
        if inset:
            ins = e.dxf.insert
            e.dxf.insert = (ins[0] + inset, ins[1], ins[2] if len(ins) > 2 else 0.0)
        if _has_cjk(value):
            e.dxf.style = CJK_FONT[0]
            if min_height:
                e.dxf.char_height = max(e.dxf.char_height, min_height)
        self.touch(handle)
        return e

    def set_fixed(self, name, value, **kw):
        """Rewrite a fixed template text by its name in the map's ``fixed_texts`` (UNITS, TOL1_VALUE,
        ROUGHNESS, EDGES, NO_SCALE, PROJECTION, COMPANY1 ... in the Aerial Hedra templates); the
        keyword arguments are :meth:`set_text`'s."""
        spec = self.map.get("fixed_texts", {}).get(name)
        if not isinstance(spec, dict) or "handle" not in spec:
            raise DrawingError(f"template has no fixed text {name}")
        return self.set_text(spec["handle"], value, **kw)

    def blank_placeholders(self):
        """Blank the template's '----' / '-' field placeholders (Onshape's own PDF hides them; the
        Aerial Hedra templates list theirs under ``placeholders``)."""
        marks = tuple(self.map.get("placeholders", ("----", "-"))) + ("",)
        for e in self.msp.query("MTEXT"):
            if e.plain_text().strip() in marks:
                e.text = ""

    def replace_template_text(self, mapping, style=None, height_floor=None):
        """Replace template MTEXT whose plain text matches a key (exact, whitespace-normalised).
        Also looks inside the revision table block. Returns the keys that were found."""
        found = set()
        norm = {" ".join(k.split()): v for k, v in mapping.items()}
        containers = [self.msp] + [b for b in self.doc.blocks if b.name.startswith("*T")]
        for cont in containers:
            for e in cont.query("MTEXT"):
                key = " ".join(e.plain_text().split())
                if key in norm:
                    e.text = norm[key]
                    if style or _has_cjk(norm[key]):
                        e.dxf.style = style or CJK_FONT[0]
                    if height_floor and e.dxf.char_height < height_floor:
                        e.dxf.char_height = height_floor
                    found.add(key)
        return found

    def revision_row(self, index, rev, description, approved="", h=None, height=None, min_h=2.5, date=""):
        """Revision table row (index 1 = first added row, standard height unless ``height`` is
        given): under the header of the Aerial Hedra templates (``next_row_top``), under row A of
        the Onshape template. A long description wraps onto as many lines as the row holds, its
        text shrinking until it fits; below ``min_h`` the drawing fails (shorten the description
        or give the row more height). ``date`` fills a DATE column where the template has one."""
        rt = self.map["revision_table"]
        if not rt:
            raise DrawingError("this template has no revision table (continuation sheet)")
        height = height or rt["row_height"]
        y1 = rt.get("next_row_top", rt["first_row_y"][0]) - (index - 1) * rt["row_height"]
        y0 = y1 - height
        cols = rt["columns_x"]
        x0, x1 = cols["REV"][0], cols["APPROVED"][1]
        inset = rt.get("text_inset", 1.524)
        lay = {"layer": "TABLES", "lineweight": 25}
        h = h or rt["data_ch"]
        ym = (y0 + y1) / 2
        avail = cols["DESCRIPTION"][1] - cols["DESCRIPTION"][0] - 2 * inset - 0.5
        if date and "DATE" not in cols:
            raise DrawingError("this template's revision table has no DATE column")
        self._rev_bottom = y0 if self._rev_bottom is None else min(self._rev_bottom, y0)
        with self.group("revision-row"):
            self.msp.add_line((x0, y0), (x1, y0), dxfattribs=lay)
            for xs in sorted({x for span in cols.values() for x in span}):
                self.msp.add_line((xs, y0), (xs, y1), dxfattribs=lay)
            self.text((cols["REV"][0] + inset, ym), rev, h=h, attach="MIDDLE_LEFT", layer="TABLES")
            if date:
                self.text((cols["DATE"][0] + inset, ym), date, h=h, attach="MIDDLE_LEFT", layer="TABLES")
            dh = h
            while True:
                lines = [description] if self.text_width(description, dh) <= avail else self.wrap(description, avail, dh)
                if len(lines) * dh * 1.6 <= height - 0.8:
                    break
                dh *= 0.95
                if dh < min_h:
                    raise DrawingError(f"revision {rev}: description does not fit the cell at {min_h} mm text")
            self.revision_text_height = dh
            # a multi-line block sets slightly high of its middle attachment: centre its ink in the row
            ym_text = ym - (0.12 * dh if len(lines) > 1 else 0.0)
            self.text((cols["DESCRIPTION"][0] + inset, ym_text), "\\P".join(_plain(ln) for ln in lines), h=dh,
                      attach="MIDDLE_LEFT", layer="TABLES")
            if approved:
                self.text((cols["APPROVED"][0] + inset, ym), approved, h=h, attach="MIDDLE_LEFT", layer="TABLES")

        if rt.get("pdf_approval_fields") and not approved:
            for column, value, label in (("DATE", date, "Approval date (YYYY-MM-DD)"), ("APPROVED", approved, "Approved by")):
                if column in cols:
                    self._revision_form_fields.append({
                        "name": f"REV_{index}_{column}", "label": f"Revision {rev or index}: {label}",
                        "rect": [cols[column][0] + .6, y0 + .6, cols[column][1] - .6, y1 - .6],
                        "value": value, "height_mm": h, "max_length": 10 if column == "DATE" else 40,
                    })

    def pdf_form_fields(self):
        """Editable sign-off cells; completed revision rows remain printed history."""
        marks = set(self.map.get("placeholders", ("----", "-")))
        result = []
        for spec in self.map.get("pdf_form_fields", []):
            value = self._field_text(spec["name"])
            result.append(dict(spec, value="" if value in marks else value))
        return result + self._revision_form_fields

    def set_block_text(self, block, handle, value):
        b = self.doc.blocks.get(block)
        for e in b:
            if e.dxf.handle == handle:
                e.text = value
                return
        raise DrawingError(f"{block}: no entity {handle}")

    def wrap(self, text, width_mm, h, style=None):
        """Break ``text`` into lines no wider than ``width_mm`` at cap height h (measured with the
        real font). Latin words and numbers stay whole; CJK breaks between characters, never
        before closing punctuation or after opening punctuation."""
        style = style or self.style_for(text)
        f = self.font(style, h)

        def width(toks):
            return f.text_width(_plain("".join(toks)).rstrip())
        lines, cur = [], []
        for tok in _tokens(text):
            if not cur and not tok.strip():
                continue
            if cur and tok.strip() and width(cur + [tok]) > width_mm:
                carry = []
                if tok[0] in _NO_LINE_START:
                    # a closing mark may not start a line: take tokens down with it until the new
                    # line starts with one that may ('上限）' + '，' moves '限），' down)
                    while cur and not cur[-1].strip():
                        cur.pop()
                    while len(cur) > 1 and (not carry or carry[0][0] in _NO_LINE_START):
                        carry.insert(0, cur.pop())
                        while cur and not cur[-1].strip():
                            cur.pop()
                    if not carry or carry[0][0] in _NO_LINE_START:
                        cur.extend(carry + [tok])    # nothing left to break before: let it overflow
                        continue
                while cur and cur[-1][-1] in _NO_LINE_END:  # opening punctuation moves down
                    carry.insert(0, cur.pop())
                lines.append("".join(cur).rstrip())
                cur = carry + [tok]
            else:
                cur.append(tok)
        if cur and "".join(cur).strip():
            lines.append("".join(cur).rstrip())
        return lines

    def notes(self, pos, title, items, h=DIM_TEXT, width_mm=None, width_at=None, line_gap=1.55, item_gap=0.6,
              bottom=None, width_chars=None):
        """Numbered notes block with measured line breaks (ezdxf's MTEXT wrap is unreliable).
        ``width_at(y_top)`` gives the text width available for a line whose top is at y, so the
        block can flow around views; ``bottom`` raises if the notes run below it. Returns the y
        under the last line. Under the standard notes go on sheet 1 only (rule 2) and state only
        what no view, callout or title-block field states (rule 1; lint checks the certain cases)."""
        if self.standard and self.is_continuation:
            raise DrawingError(f"notes go on sheet 1 only; this is a continuation sheet (rule 2 of {STANDARD})."
                               + STANDARD_HINT)
        self._notes_items.extend(items)
        placed, y_end = self.layout_notes(pos, title, items, h, width_mm, width_at, line_gap, item_gap, width_chars)
        bad_starts = [s for (_, s, _) in placed if _plain(s)[:1] in _NO_LINE_START]
        if bad_starts:
            raise DrawingError(f"note lines start with closing punctuation: {bad_starts[:3]}")
        if bottom is not None and y_end < bottom:
            raise DrawingError(f"notes run below y={bottom:.1f} (end at {y_end:.1f}); shorten or shrink them")
        with self.group("notes"):
            for (px, py), s, hh in placed:
                # U+00A0 / U+2060 only tell the wrapper "keep together"; the DXF gets plain text
                self.text((px, py), _plain(s), h=hh, attach="TOP_LEFT")
        return y_end

    def layout_notes(self, pos, title, items, h=DIM_TEXT, width_mm=None, width_at=None, line_gap=1.55,
                     item_gap=0.6, width_chars=None):
        """Dry run of :meth:`notes`: the texts it would place and the y under the last line."""
        x, y = pos
        # the text starts clear of the widest number ('12.' as well as '1.')
        indent = max(h * 2.2, self.text_width(f"{len(items)}.", h) + 0.6 * h)
        placed = []
        if title:
            placed.append(((x, y), title, h * 1.2))
            y -= h * 1.2 * line_gap + h * 0.6
        for i, item in enumerate(items, 1):
            if width_chars and not (width_mm or width_at):
                lines = _wrap(item, width_chars)
            else:
                lines = self._flow(item, y, h, line_gap, width_mm, width_at, indent)
            placed.append(((x, y), f"{i}.", h))
            for ln in lines:
                placed.append(((x + indent, y), ln, h))
                y -= h * line_gap
            y -= h * item_gap
        return placed, y + h * item_gap + h * (line_gap - 1.0)      # the bottom of the last line's text

    def _flow(self, text, y, h, line_gap, width_mm, width_at, indent):
        """Wrap line by line, each line to the width available at its own height."""
        style = self.style_for(text)
        lines, rest, yy = [], text, y
        while rest:
            w = (width_at(yy) if width_at else width_mm) - indent
            first = self.wrap(rest, w, h, style)
            if not first:
                break
            used = len(_consumed(rest, first[0]))
            if used == 0:                       # cannot place anything: keep the rest whole
                lines.append(rest)
                break
            lines.append(first[0])
            rest = rest[used:].lstrip()
            yy -= h * line_gap
        # no orphan: a CJK last line of one character (plus punctuation) takes one more from above
        if len(lines) >= 2 and _has_cjk(lines[-1]) and len([c for c in lines[-1] if c not in _NO_LINE_START]) <= 1:
            prev = _tokens(lines[-2])
            if len(prev) > 2 and _has_cjk(prev[-1]):
                lines[-2] = "".join(prev[:-1]).rstrip()
                lines[-1] = prev[-1] + lines[-1]
        return lines

    # ------------------------------------------------------------------ layout check
    def lint(self, clearance=0.4, ignore=()):
        """Find layout clashes. Returns a list of records, each with a ``kind``:

        - text-text: annotation texts closer than ``clearance`` (template texts included);
        - text-line / text-hatch: text crossing view geometry, frames, leaders, dimension lines
          (its own included, except a leader's shoulder) or lying on hatching. Masked text
          (DIMTFILL, background fill, inside its own WIPEOUT) may sit on lines, not on text;
        - symbol-line: a roughness, datum or feature-frame stroke crossing a view, dimension or
          leader line of another annotation (touching at a stroke end is allowed);
        - mask-geometry / mask-hatch: a WIPEOUT hiding view geometry, another annotation's lines
          or hatching (centre lines may be masked).

        With ``standard`` on, also the findings against the drawing standard (STANDARD_KINDS,
        each with its ``rule`` number; see :meth:`_standard_lint`). :meth:`save` refuses a sheet
        that has any of those."""
        import numpy as np
        from ezdxf import path as ezpath

        texts, segs, hatches, wipeouts = [], [], [], []
        ann, leaders = [], []       # leader / dimension-line / extension-line segments; (tip, elbow, gid)

        def owner(e, fallback):
            return self._owner.get(e.dxf.handle, fallback)

        def add_text(e, gid, masked, label, loose=False):
            try:
                box = _mtext_box(e)
            except Exception as exc:  # noqa: BLE001
                self.issues.append(f"lint: cannot measure text {label!r}: {exc}")
                return
            if box is None:
                return
            rot = (e.dxf.get("rotation", 0.0) or 0.0) % 180.0
            try:
                obox = _mtext_obox(e)               # text turned off the axes: tested by its own rectangle
            except Exception:  # noqa: BLE001
                obox = None
            texts.append({"box": box, "gid": gid, "masked": masked, "label": label, "loose": loose,
                          "full": e.plain_text(), "obox": obox,
                          "h": e.dxf.get("char_height", 2.5), "upright": not (45.0 < rot < 135.0)})

        def add_path(p, gid, layer, role=None):
            pts = list(p.flattening(0.02))
            for a, b in zip(pts[:-1], pts[1:]):
                segs.append((a.x, a.y, b.x, b.y, gid, layer))
                if role:
                    ann.append((a.x, a.y, b.x, b.y, gid, role))

        for e in self.msp:
            t = e.dxftype()
            h = e.dxf.handle
            if h in self._touched:
                gid = f"template-touched#{h}"       # rewritten template text: tested like drawing text
            else:
                gid = owner(e, "template" if h in self._template_handles else h)
            if t == "MTEXT":
                if e.plain_text().strip():
                    # untouched template texts take part as obstacles (gid 'template': never
                    # tested against the template's own lines or texts)
                    masked = bool(e.dxf.get("bg_fill", 0))
                    # text the spec wrote with text() itself belongs to no annotation: loose text
                    loose = h not in self._template_handles and h not in self._owner
                    add_text(e, gid, masked, e.plain_text().replace("\n", " | ")[:60], loose=loose)
            elif t == "DIMENSION":
                masked = bool(e.override().get("dimtfill", 0))
                dtype = int(e.dxf.get("dimtype", 0)) & 7       # 0 linear, 1 aligned, 2/5 angular, 3 diameter, 4 radius
                along = None                                    # direction of a linear dimension line
                if dtype == 0:
                    along = math.radians(e.dxf.get("angle", 0.0))
                elif dtype == 1:
                    p2, p3 = e.dxf.defpoint2, e.dxf.defpoint3
                    along = math.atan2(p3[1] - p2[1], p3[0] - p2[0])
                for ve in e.virtual_entities():
                    vt = ve.dxftype()
                    if vt == "MTEXT":
                        add_text(ve, gid, masked, "dim " + ve.plain_text().replace("\n", " ")[:40])
                    elif vt in ("LINE", "ARC"):
                        # a dimension's own lines are tested against its own text too: text sits
                        # clear of its dimension and extension lines, never across a leader
                        if dtype in (3, 4):
                            role = "leader"                     # a radius or diameter dimension reads as a leader
                        elif vt == "ARC":
                            role = "dimline"
                        elif along is None:
                            role = "ext"
                        else:
                            d = ve.dxf.end - ve.dxf.start
                            turn = (math.atan2(d[1], d[0]) - along) % math.pi
                            role = "dimline" if min(turn, math.pi - turn) < math.radians(1.0) else "ext"
                        add_path(ezpath.make_path(ve), gid + "/own", "AH_DIM", role)
            elif t in ("LINE", "LWPOLYLINE", "ARC", "CIRCLE", "POLYLINE", "SPLINE"):
                role = None
                if e.dxf.layer == "AH_DIM":
                    if t == "LWPOLYLINE" and gid.split("#")[0] in ("leader", "hole-callout"):
                        role = "leader"                         # a leader drawn without an arrowhead
                    elif gid.endswith("/own"):
                        role = "dimline"                        # a dimension line carried on to its value
                try:
                    add_path(ezpath.make_path(e), gid, e.dxf.layer, role)
                except Exception:  # noqa: BLE001
                    pass
            elif t == "LEADER":
                # the shoulder (last segment) belongs to its note; the legs must not cross that note
                v = [tuple(p)[:2] for p in e.vertices]
                for k, (a, b) in enumerate(zip(v[:-1], v[1:])):
                    segs.append((a[0], a[1], b[0], b[1], gid if k == len(v) - 2 else gid + "/leg", "AH_DIM"))
                    ann.append((a[0], a[1], b[0], b[1], gid, "leader"))
                if len(v) >= 2:
                    leaders.append((v[0], v[1], gid))
            elif t == "HATCH" and e.dxf.layer == "AH_HATCH":
                loops = []
                for bp in e.paths:
                    if hasattr(bp, "vertices"):
                        loops.append([(v[0], v[1]) for v in bp.vertices])
                hatches.append((loops, gid))
            elif t == "WIPEOUT":
                wipeouts.append(([(v[0], v[1]) for v in e.boundary_path_wcs()], gid))

        S = np.array([s[:4] for s in segs], dtype=float) if segs else np.zeros((0, 4))
        smin_x, smax_x = np.minimum(S[:, 0], S[:, 2]), np.maximum(S[:, 0], S[:, 2])
        smin_y, smax_y = np.minimum(S[:, 1], S[:, 3]), np.maximum(S[:, 1], S[:, 3])
        clashes = []
        shrink = 0.12
        # text inside its own annotation's WIPEOUT (a feature control frame) is masked like DIMTFILL
        for t in texts:
            x0, y0, x1, y1 = t["box"]
            corners = ((x0, y0), (x1, y0), (x0, y1), (x1, y1))
            if any(gid == t["gid"] and all(_inside_evenodd(c, [poly]) for c in corners) for poly, gid in wipeouts):
                t["masked"] = True
                t["in_wipeout"] = True
        for i, t in enumerate(texts):
            x0, y0, x1, y1 = t["box"]
            if not t["masked"]:
                # the measured box is cap height; brackets, ascenders and descenders reach about
                # 0.15 h beyond it across the text's lines
                ink = 0.15 * t["h"]
                if t["upright"]:
                    bx0, by0, bx1, by1 = x0 + shrink, y0 - ink, x1 - shrink, y1 + ink
                else:
                    bx0, by0, bx1, by1 = x0 - ink, y0 + shrink, x1 + ink, y1 - shrink
                ob = t["obox"]
                cand = np.nonzero((smax_x >= bx0) & (smin_x <= bx1) & (smax_y >= by0) & (smin_y <= by1))[0]
                for k in cand:
                    sx0, sy0, sx1, sy1, gid, layer = segs[k]
                    if gid == t["gid"]:
                        continue
                    hit = (_seg_hits_obox(sx0, sy0, sx1, sy1, ob, -shrink, ink) if ob
                           else _seg_hits_box(sx0, sy0, sx1, sy1, bx0, by0, bx1, by1))
                    if hit:
                        clashes.append({"kind": "text-line", "text": t["label"], "with": f"{layer} ({gid})",
                                        "at": [round((x0 + x1) / 2, 2), round((y0 + y1) / 2, 2)]})
                        break
                for loops, gid in hatches:
                    if gid == t["gid"]:
                        continue
                    probes = ((_obox_corners(ob, -shrink, -shrink) + [(ob[0], ob[1])]) if ob else
                              [(x0 + shrink, y0 + shrink), (x1 - shrink, y0 + shrink), (x0 + shrink, y1 - shrink),
                               (x1 - shrink, y1 - shrink), ((x0 + x1) / 2, (y0 + y1) / 2)])
                    if any(_inside_evenodd(p, loops) for p in probes):
                        clashes.append({"kind": "text-hatch", "text": t["label"], "with": gid,
                                        "at": [round((x0 + x1) / 2, 2), round((y0 + y1) / 2, 2)]})
                        break
            for j in range(i + 1, len(texts)):
                u = texts[j]
                if u["gid"] == t["gid"]:
                    continue
                # inside the title block a rewritten cell keeps the template's own spacing: only
                # a real overlap with another template text counts
                pair = {t["gid"].split("#")[0], u["gid"].split("#")[0]}
                c = 0.0 if pair <= {"template", "template-touched"} else clearance
                a = (x0 - c / 2, y0 - c / 2, x1 + c / 2, y1 + c / 2)
                b = u["box"]
                b = (b[0] - c / 2, b[1] - c / 2, b[2] + c / 2, b[3] + c / 2)
                hit = a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
                if hit and (t["obox"] or u["obox"]):
                    # a turned text: test the two real rectangles, not their axis-aligned boxes
                    def quad(x, bx):
                        return (_obox_corners(x["obox"], c / 2, c / 2) if x["obox"] else
                                [(bx[0], bx[1]), (bx[2], bx[1]), (bx[2], bx[3]), (bx[0], bx[3])])
                    hit = _rects_overlap(quad(t, a), quad(u, b))
                if hit:
                    clashes.append({"kind": "text-text", "text": t["label"], "with": u["label"],
                                    "at": [round((x0 + x1) / 2, 2), round((y0 + y1) / 2, 2)]})

        def base(gid):
            return gid.split("/")[0]
        # symbol strokes against other annotations' and the views' lines
        symbol_groups = ("roughness", "datum", "fcf")
        crossable = ("AH_VISIBLE", "AH_THIN", "AH_HIDDEN", "AH_DIM", "AH_CUTLINE")
        for k, s in enumerate(segs):
            if not base(s[4]).startswith(symbol_groups):
                continue
            a, b = (s[0], s[1]), (s[2], s[3])
            cand = np.nonzero((smax_x >= min(s[0], s[2])) & (smin_x <= max(s[0], s[2])) &
                              (smax_y >= min(s[1], s[3])) & (smin_y <= max(s[1], s[3])))[0]
            for m in cand:
                o = segs[m]
                if base(o[4]) == base(s[4]) or o[5] not in crossable:
                    continue
                if _cross_properly(a, b, (o[0], o[1]), (o[2], o[3])):
                    clashes.append({"kind": "symbol-line", "text": base(s[4]), "with": f"{o[5]} ({o[4]})",
                                    "at": [round((s[0] + s[2]) / 2, 2), round((s[1] + s[3]) / 2, 2)]})
                    break
        # masked texts (DIMTFILL, background fill) are masks too: their boxes join the WIPEOUTs
        for t in texts:
            if t["masked"] and not t.get("in_wipeout"):
                x0, y0, x1, y1 = t["box"]
                wipeouts.append(([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], t["gid"]))
        # masks must hide nothing but centre lines
        for poly, gid in wipeouts:
            xs, ys = [p[0] for p in poly], [p[1] for p in poly]
            bx0, by0, bx1, by1 = min(xs) + 0.05, min(ys) + 0.05, max(xs) - 0.05, max(ys) - 0.05
            cand = np.nonzero((smax_x >= bx0) & (smin_x <= bx1) & (smax_y >= by0) & (smin_y <= by1))[0]
            for m in cand:
                o = segs[m]
                if base(o[4]) == base(gid) or o[5] in ("AH_CENTER",):
                    continue
                if _seg_hits_box(o[0], o[1], o[2], o[3], bx0, by0, bx1, by1):
                    clashes.append({"kind": "mask-geometry", "text": gid, "with": f"{o[5]} ({o[4]})",
                                    "at": [round((bx0 + bx1) / 2, 2), round((by0 + by1) / 2, 2)]})
                    break
            probes = [(bx0, by0), (bx1, by0), (bx0, by1), (bx1, by1), ((bx0 + bx1) / 2, (by0 + by1) / 2)]
            for loops, hg in hatches:
                if any(_inside_evenodd(p, loops) for p in probes):
                    clashes.append({"kind": "mask-hatch", "text": gid, "with": hg,
                                    "at": [round((bx0 + bx1) / 2, 2), round((by0 + by1) / 2, 2)]})
                    break
        if self.standard:
            clashes.extend(self._standard_lint(texts, segs, ann, leaders))
        out = [c for c in clashes if not any(s in c["text"] or s in c["with"] for s in ignore)]
        return out

    def _standard_lint(self, texts, segs, ann, leaders):
        """Findings against the drawing standard (STANDARD_DOC), the rules a program can decide:

        - rule 1, notes: a note that repeats a title-block entry (note-title-block) or names a
          sheet (note-sheet-reference);
        - rule 2: text that is no view label, callout or numbered note (loose-text);
        - rule 3: thread information in a note (note-thread), 'RIGHT HAND' anywhere (right-hand);
        - rule 4: a leader to a circle that is not radial to its near side (leader-not-radial) or
          whose circle has no centre mark (hole-no-centre-mark);
        - rule 5: a leader crossing a leader (leader-leader), a dimension line (leader-dimension)
          or an extension line (leader-extension, the one kind :meth:`allow` can waive);
        - rules 6, 7: a section, a detail or an off-scale view without its view_label
          (view-label); a section without its cutting-plane line or a detail without its circle,
          and the reverse (section-line, detail-circle);
        - rule 8: a title block without the sheet scale, a main view off it without a reason (scale);
        - rule 10: a blank or wrongly stated weight (weight);
        - rule 11: anything in the title block or revision table, or outside the frame."""
        out = []

        def base(gid):
            return gid.split("/")[0]
        names = {}
        for t in texts:
            names.setdefault(base(t["gid"]), t["label"])

        def name(gid):
            return names.get(base(gid), base(gid))

        def add(kind, rule, text, with_="", at=None):
            out.append({"kind": kind, "rule": rule, "text": text, "with": with_,
                        "at": [round(v, 2) for v in at] if at else []})

        # ---- rules 1 to 3: what is written
        for t in texts:
            x0, y0, x1, y1 = t["box"]
            mid = ((x0 + x1) / 2, (y0 + y1) / 2)
            if t["loose"]:
                add("loose-text", 2, t["label"], "text is a view label, a callout on a leader or a numbered note "
                    "on sheet 1; a requirement is dimensioned on a view, not described", mid)
            if not t["gid"].startswith("template") and "RIGHT HAND" in t["full"].upper():
                add("right-hand", 3, t["label"], "right hand is implied; only a left-hand thread is marked (LH)", mid)
        fixed = self.map.get("fixed_texts") or {}
        material = re.sub(r"[^A-Z0-9]", "", self._field_text("MATERIAL").upper())
        finish = re.sub(r"[^A-Z0-9]", "", self._field_text("FINISH").upper())
        for item in self._notes_items:
            u = " ".join(_plain(item).upper().split())
            flat = re.sub(r"[^A-Z0-9]", "", u)
            dup = None
            if u.startswith("MATERIAL") or (len(material) >= 4 and material in flat):
                dup = "the material"
            elif len(finish) >= 6 and finish in flat:
                dup = "the finish"
            elif "NO_SCALE" in fixed and "DO NOT SCALE" in u:
                dup = "DO NOT SCALE DRAWING"
            elif "EDGES" in fixed and ("BREAK SHARP EDGES" in u or "DEBURR" in u
                                       or re.search(r"\bREMOVE (ALL )?BURRS\b", u)):
                dup = "the edge break"
            if dup:
                add("note-title-block", 1, u[:60], f"the title block already states {dup}")
            if _THREAD_IN_TEXT.search(u) or "SHOWN CONVENTIONALLY" in u:
                add("note-thread", 3, u[:60], "thread information belongs in the thread callout, complete")
            if re.search(r"\bSHEETS? \d", u):
                add("note-sheet-reference", 1, u[:60], "a note does not say which sheet holds what")

        # ---- rule 11: the title block, the revision table and the frame are kept clear
        boxes = [("title-block", self.map.get("title_block_box")), ("revision-table", self.map.get("revision_table_box"))]
        if boxes[1][1] and self._rev_bottom is not None:
            b = boxes[1][1]
            boxes[1] = ("revision-table", [b[0], min(b[1], self._rev_bottom), b[2], b[3]])
        frame = self.map.get("frame_box")
        flagged = set()

        def own(gid):
            b = base(gid)
            return not (b.startswith("template") or b.startswith("revision-row"))

        def keep_out(gid, x0, y0, x1, y1, is_seg):
            mid = ((x0 + x1) / 2, (y0 + y1) / 2)
            for kind, box in boxes:
                if not box or (kind, base(gid)) in flagged:
                    continue
                bx0, by0, bx1, by1 = box[0] + 0.05, box[1] + 0.05, box[2] - 0.05, box[3] - 0.05
                hit = (_seg_hits_box(x0, y0, x1, y1, bx0, by0, bx1, by1) if is_seg
                       else (x0 < bx1 and bx0 < x1 and y0 < by1 and by0 < y1))
                if hit:
                    flagged.add((kind, base(gid)))
                    add(kind, 11, name(gid), f"enters the {kind.replace('-', ' ')}", mid)
            if frame and ("outside-frame", base(gid)) not in flagged:
                if not all(frame[0] - 1e-6 <= x <= frame[2] + 1e-6 and frame[1] - 1e-6 <= y <= frame[3] + 1e-6
                           for x, y in ((x0, y0), (x1, y1))):
                    flagged.add(("outside-frame", base(gid)))
                    add("outside-frame", 11, name(gid), "reaches outside the drawing frame", mid)
        for s in segs:
            if own(s[4]):
                keep_out(s[4], s[0], s[1], s[2], s[3], True)
        for t in texts:
            if own(t["gid"]):
                keep_out(t["gid"], *t["box"], False)

        # ---- rule 5: leaders cross neither leaders nor dimension lines (extension lines: allow())
        for w in self._allow:
            w["used"] = False
        lead = [a for a in ann if a[5] == "leader"]
        rest = [a for a in ann if a[5] != "leader"]
        kinds = {"leader": "leader-leader", "dimline": "leader-dimension", "ext": "leader-extension"}
        seen = set()
        for i, s in enumerate(lead):
            for o in lead[i + 1:] + rest:
                if base(o[4]) == base(s[4]):
                    continue
                a, b, c, d = (s[0], s[1]), (s[2], s[3]), (o[0], o[1]), (o[2], o[3])
                if not _cross_properly(a, b, c, d):
                    continue
                kind = kinds[o[5]]
                key = (kind, base(s[4]), base(o[4]))
                if key in seen:
                    continue
                seen.add(key)
                at = _seg_x(a, b, c, d)
                if kind in WAIVABLE and self._waived(kind, at):
                    continue
                add(kind, 5, name(s[4]), name(o[4]), at)
        for w in self._allow:
            if not w["used"]:
                add("unused-waiver", 5, f"allow({w['kind']!r}, at={w['at']})", "waives nothing; remove it", w["at"])

        # ---- rule 4: a leader to a circle is radial, and the circle has its centre mark
        circles = []
        for pv in self._placed:
            for c in pv.view.curves:
                if c.kind != "circle" or c.style not in ("visible", "section", "hidden"):
                    continue
                if pv.clip and math.hypot(c.c[0] - pv.clip[0][0], c.c[1] - pv.clip[0][1]) + c.r > pv.clip[1]:
                    continue
                circles.append((pv.s(c.c), c.r * pv.scale))
        circles.extend(self._fitted_circles)
        centre_lines = [s for s in segs if s[5] == "AH_CENTER"]
        for tip, elbow, gid in leaders:
            hits = [c for c in circles if abs(math.hypot(tip[0] - c[0][0], tip[1] - c[0][1]) - c[1]) < 0.05]
            if not hits:
                continue
            cc, radius = min(hits, key=lambda c: c[1])
            ex, ey, tx, ty = elbow[0] - cc[0], elbow[1] - cc[1], tip[0] - cc[0], tip[1] - cc[1]
            reach = math.hypot(ex, ey)
            off = abs(ex * ty - ey * tx) / max(reach * radius, 1e-9)       # sine of the angle off radial
            if reach <= radius or ex * tx + ey * ty <= 0 or off > math.sin(math.radians(2.0)):
                add("leader-not-radial", 4, name(gid), "a leader to a circle points at its centre and stops on "
                    "the near side (hole_callout() does both)", tip)
            dirs = [math.atan2(s[3] - s[1], s[2] - s[0]) % math.pi for s in centre_lines
                    if _pt_seg_dist(cc, (s[0], s[1]), (s[2], s[3])) < 0.1]
            if not any(min(abs(a - b), math.pi - abs(a - b)) > math.radians(20.0) for a in dirs for b in dirs):
                add("hole-no-centre-mark", 4, name(gid), "the circle it points to has no centre mark "
                    "(centre_mark(), or hole_callout())", cc)

        # ---- rules 6 to 8 and 10: labels, section and detail pairing, scale, weight
        fields = self.map.get("fields") or {}
        marks = tuple(self.map.get("placeholders", ("----", "-"))) + ("",)
        if "WEIGHT" in fields:
            w = self._field_text("WEIGHT")
            pattern = r"\d+\.\d{3} lb" if self.units == "in" else r"\d+\.\d{3} kg|\d+(\.\d)? g"
            if w in marks:
                add("weight", 10, "WEIGHT is blank", "fill it from the model with set_weight(volume_mm3, density_g_cm3)")
            elif not re.fullmatch(pattern, w) or (w.endswith(" kg") and float(w[:-3]) < 0.1):
                add("weight", 10, f"WEIGHT {w!r}", "pounds on an inch drawing; kilograms on a metric one, grams under "
                    "0.100 kg; never REF (set_weight() writes it)")
        if "SCALE" in fields and self.scale is None:
            add("scale", 8, f"SCALE {self._field_text('SCALE')!r}", "the title block states the scale of the main "
                "views as N:M; only a view off that scale is labelled with its own")
        for pv in self._placed:
            off = self.scale is not None and abs(pv.scale - self.scale) > 1e-9
            if off and pv.kind != "detail" and not pv.scale_reason:
                add("scale", 8, f"view {pv.name} at {scale_text(pv.scale)}", f"the sheet scale is {scale_text(self.scale)}: "
                    "the main views share one scale; if this one cannot, place(..., scale_reason=) says why")
            if (off or pv.kind != "view" or pv.letter) and id(pv) not in self._labelled:
                add("view-label", 6, f"view {pv.name}", "a section, a detail and a view off the sheet scale take a view_label()")
            if pv.kind == "section" and not pv.parent_sheet and pv.letter not in self._cut_letters:
                add("section-line", 7, f"section {pv.letter}-{pv.letter}", "no cutting-plane line with this letter on the "
                    "sheet (cutting_plane() on a view that sees the plane edge-on; parent_sheet= if it is on another sheet)")
            if pv.kind == "detail" and not pv.parent_sheet and pv.letter not in self._detail_letters:
                add("detail-circle", 7, f"detail {pv.letter}", "no detail circle with this letter on the sheet "
                    "(detail_circle() on the parent view; parent_sheet= if it is on another sheet)")
        for letter, sheet in self._cut_letters.items():
            if sheet is None and not any(pv.kind == "section" and pv.letter == letter for pv in self._placed):
                add("section-line", 7, f"cutting plane {letter}-{letter}", "its section view is not on this sheet "
                    "(view_sheet= if it is on another)")
        for letter, sheet in self._detail_letters.items():
            if sheet is None and not any(pv.kind == "detail" and pv.letter == letter for pv in self._placed):
                add("detail-circle", 7, f"detail circle {letter}", "its detail view is not on this sheet "
                    "(view_sheet= if it is on another)")
        for pv in self._placed:
            if pv.kind == "view" and pv.letter and pv.letter not in self._view_letters:
                add("view-arrow", 7, f"view {pv.letter}", "no viewing-direction arrow with this letter on the sheet "
                    "(view_arrow() on the view it is projected from)")
        for letter in self._view_letters:
            if not any(pv.kind == "view" and pv.letter == letter for pv in self._placed):
                add("view-arrow", 7, f"view arrow {letter}", "its view is not on this sheet")
        return out

    def _waived(self, kind, at, reach=5.0):
        for w in self._allow:
            if w["kind"] == kind and math.hypot(at[0] - w["at"][0], at[1] - w["at"][1]) <= reach:
                w["used"] = True
                return True
        return False

    def standard_report(self):
        """What the sheet declares under the standard, for the drawing's check record."""
        return {"standard": STANDARD if self.standard else None, "sheet": self.sheet_no,
                "sheet_scale": scale_text(self.scale) if self.scale else None,
                "weight": self._field_text("WEIGHT") if "WEIGHT" in (self.map.get("fields") or {}) else None,
                "views": [{"name": pv.name, "kind": pv.kind, "letter": pv.letter, "scale": scale_text(pv.scale),
                           "scale_reason": pv.scale_reason, "parent_sheet": pv.parent_sheet} for pv in self._placed],
                "cutting_planes": dict(self._cut_letters), "detail_circles": dict(self._detail_letters),
                "view_arrows": sorted(self._view_letters),
                "notes": len(self._notes_items), "waivers": [dict(w) for w in self._allow]}

    # ------------------------------------------------------------------ output
    def save(self, path):
        if self.standard:
            found = [c for c in self.lint() if c["kind"] in STANDARD_KINDS]
            if found:
                head = "; ".join(f"[{c['kind']}, rule {c['rule']}] {c['text']}: {c['with']}" for c in found[:6])
                raise DrawingError(f"{len(found)} finding(s) against the {STANDARD}: {head}"
                                   f"{' ...' if len(found) > 6 else ''}." + STANDARD_HINT)
        nl = self.map.get("notes_label") or {}
        if self.standard and not self.is_continuation and not self._notes_items and nl.get("handle"):
            # a sheet 1 with no notes drops the template's empty NOTES: heading (rule 12 readers, 12 Nov 2026)
            label = self.doc.entitydb.get(nl["handle"])
            if label is not None and label.is_alive:
                self.msp.delete_entity(label)
        x0, y0, x1, y1 = self.map["sheet_box"]
        self.doc.header["$EXTMIN"] = (x0, y0, 0)
        self.doc.header["$EXTMAX"] = (x1, y1, 0)
        bad = []
        for cont in [self.msp] + list(self.doc.blocks):
            for e in cont.query("MTEXT TEXT"):
                s = e.plain_text() if e.dxftype() == "MTEXT" else e.dxf.text
                if _has_cjk(s) and e.dxf.style != CJK_FONT[0] and not self._style_has_cjk(e.dxf.style):
                    bad.append(s[:30])
        if bad:
            raise DrawingError(f"CJK text in non-CJK styles: {bad[:5]}")
        missing = self.missing_glyphs()
        if missing:
            raise DrawingError(f"characters missing from their fonts (would print as boxes): {missing[:8]}")
        self.doc.saveas(str(path))
        aud = ezdxf.readfile(str(path)).audit()
        if aud.has_errors:
            raise DrawingError(f"{path}: DXF audit errors {[str(e) for e in aud.errors][:5]}")
        return path

    def missing_glyphs(self):
        """Characters of the drawing's texts (dimension texts included) that their style's font
        does not contain. Returns [(char, text, font)]."""
        from ezdxf.fonts import fonts
        cmaps = {}

        def cmap(font_file):
            if font_file not in cmaps:
                try:
                    cmaps[font_file] = set(fonts.font_manager.get_ttf_font(font_file).getBestCmap())
                except Exception:  # noqa: BLE001 - an unresolvable font is reported once
                    cmaps[font_file] = None
            return cmaps[font_file]

        def check(e, out):
            st = self.doc.styles.get(e.dxf.style) if e.dxf.style in self.doc.styles else None
            font_file = (st.dxf.get("font", "") if st else "") or LATIN_FONT[1]
            cm = cmap(font_file)
            if cm is None:
                out.append(("?", e.plain_text()[:30], font_file))
                return
            text = _norm(_plain(e.plain_text()))
            for ch in sorted(set(text)):
                if not ch.isspace() and ord(ch) not in cm:
                    out.append((ch, text[:30], font_file))

        out = []
        for e in self.msp:
            if e.dxftype() == "MTEXT" and (e.dxf.handle not in self._template_handles or
                                           e.dxf.handle in self._touched):
                check(e, out)
            elif e.dxftype() == "DIMENSION":
                for ve in e.virtual_entities():
                    if ve.dxftype() == "MTEXT":
                        check(ve, out)
        return out

    def _style_has_cjk(self, name):
        st = self.doc.styles.get(name) if name in self.doc.styles else None
        font = (st.dxf.get("font", "") if st else "").lower()
        return any(k in font for k in ("msyh", "simsun", "simhei", "notosanssc", "notosanscjk", "yahei"))

    def render(self, pdf_path, png_path=None, dpi=200, title=None):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from ezdxf.addons.drawing import Frontend, RenderContext
        from ezdxf.addons.drawing import frontend as ezfrontend
        from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration, LineweightPolicy
        # ezdxf draws MTEXT background masks (DIMTFILL, bg fill) only on its "complex" MTEXT path,
        # which plain one-line texts never take: send masked texts down that path.
        if not getattr(ezfrontend.is_complex_mtext, "_kurtshape_masks", False):
            plain_check = ezfrontend.is_complex_mtext

            def is_complex_mtext(mtext):
                return bool(mtext.dxf.get("bg_fill", 0)) or plain_check(mtext)
            is_complex_mtext._kurtshape_masks = True
            ezfrontend.is_complex_mtext = is_complex_mtext
        x0, y0, x1, y1 = self.map["sheet_box"]
        fig = plt.figure(figsize=((x1 - x0) / 25.4, (y1 - y0) / 25.4))
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_axis_off()
        # The matplotlib backend reads lineweights as points: scale mm -> pt so 0.50 mm prints 0.50 mm.
        # COLOR, not BLACK: BLACK also blackens WIPEOUTs and text masks (they take the background
        # colour); on a white background colour 7 prints black anyway. check_render() catches colour.
        cfg = Configuration(color_policy=ColorPolicy.COLOR, background_policy=BackgroundPolicy.WHITE,
                            lineweight_policy=LineweightPolicy.ABSOLUTE, lineweight_scaling=PT_PER_MM,
                            min_lineweight=MIN_LINEWEIGHT * PT_PER_MM)
        # ezdxf cannot know the "canvas colour" a DXF mask asks for and skips it; for the PDF only,
        # paint such masks white with a tight margin (the DXF keeps canvas-colour masks).
        masked = []
        for cont in [self.msp] + list(self.doc.blocks):
            for m in cont.query("MTEXT"):
                if (m.dxf.get("bg_fill", 0) & 3) == 3:
                    masked.append((m, {k: m.dxf.get(k) for k in ("bg_fill", "bg_fill_color", "bg_fill_true_color",
                                                                 "box_fill_scale")}))
                    m.dxf.bg_fill = 1
                    m.dxf.bg_fill_color = 7
                    m.dxf.bg_fill_true_color = ezdxf.rgb2int((255, 255, 255))
                    m.dxf.box_fill_scale = 1.1
        try:
            Frontend(RenderContext(self.doc), _glyph_safe_backend(ax), config=cfg).draw_layout(self.msp, finalize=True)
        finally:
            for m, old in masked:
                for k, v in old.items():
                    if v is None:
                        m.dxf.discard(k)
                    else:
                        m.dxf.set(k, v)
        if self.logo is not None:
            lb = self.map["logo_box"]
            ax.imshow(self.logo, extent=(lb[0], lb[2], lb[1], lb[3]), zorder=10, interpolation="lanczos")
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)
        ax.set_aspect("equal", adjustable="box")
        meta = {"Title": title or "Drawing", "Subject": title or "Drawing", "Creator": "KurtShape drawing pipeline"}
        fig.savefig(str(pdf_path), facecolor="white", metadata=meta)
        if png_path:
            fig.savefig(str(png_path), dpi=dpi, facecolor="white")
            self.check_render(png_path, dpi)
        plt.close(fig)
        fields = self.pdf_form_fields()
        if fields:
            from .pdf_forms import add_signoff_fields
            add_signoff_fields(pdf_path, fields, self.map["sheet_box"])

    def check_render(self, png_path, dpi):
        """The preview must be black on white outside the logo: no coloured pixels, and no
        solid black blocks (a mask or frame filled black) larger than a heavy line."""
        import numpy as np
        from PIL import Image
        img = np.asarray(Image.open(png_path).convert("RGB")).astype(int)
        H, W, _ = img.shape
        x0, y0, x1, y1 = self.map["sheet_box"]
        px = W / (x1 - x0)

        def to_px(x, y):
            return int((x - x0) * px), int(H - (y - y0) * px)
        lb = self.map["logo_box"]
        lx0, ly1 = to_px(lb[0], lb[1])
        lx1, ly0 = to_px(lb[2], lb[3])
        mask = np.ones((H, W), bool)
        mask[max(ly0 - 2, 0):ly1 + 2, max(lx0 - 2, 0):lx1 + 2] = False
        spread = img.max(axis=2) - img.min(axis=2)
        coloured = int(((spread > 40) & mask).sum())
        if coloured:
            self.issues.append(f"render: {coloured} coloured pixels outside the logo")
        dark = (img.max(axis=2) < 60) & mask
        k = max(8, int(1.5 * px))     # a 1.5 mm square of solid black is no line, arrowhead or glyph
        if px * 25.4 < 150:
            self.issues.append("render: preview below 150 dpi, black-block check is unreliable")
        cs = np.cumsum(np.cumsum(dark, 0), 1)
        win = cs[k:, k:] - cs[:-k, k:] - cs[k:, :-k] + cs[:-k, :-k]
        blobs = int((win == k * k).sum())
        if blobs:
            ys, xs = np.nonzero(win == k * k)
            at = [round(x0 + xs[0] / px, 1), round(y0 + (H - ys[0]) / px, 1)]
            self.issues.append(f"render: solid black block near sheet {at}")

    def _logo_png(self):
        """The template's logo is an OLE2FRAME holding a BMP (Paintbrush object); ezdxf cannot
        draw it, so the BMP is pulled out of the OLE data and stamped onto the PDF."""
        try:
            import io
            import numpy as np
            import olefile
            from PIL import Image
            for e in self.msp.query("OLE2FRAME"):
                data = e.binary_data()
                start = data.find(olefile.MAGIC)          # an AutoCAD header precedes the compound file
                ole = olefile.OleFileIO(io.BytesIO(data[start:]))
                for path in ole.listdir():
                    raw = ole.openstream(path).read()
                    i = raw.find(b"BM")
                    if i < 0:
                        continue
                    size = int.from_bytes(raw[i + 2:i + 6], "little")
                    img = Image.open(io.BytesIO(raw[i:i + size])).convert("RGB")
                    return np.asarray(img)
        except Exception as exc:  # noqa: BLE001 - a missing logo is reported, not fatal
            self.issues = getattr(self, "issues", []) + [f"logo: {exc}"]
        return None


# ---------------------------------------------------------------------- rendering
def _glyph_safe_backend(ax):
    """ezdxf's matplotlib backend fills every path with hole detection, which misreads glyphs
    whose counter is split by a stroke (Ø printed half black). Glyphs carry their own TrueType
    winding, so text is filled without hole detection; hatches keep it."""
    from matplotlib.patches import PathPatch
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    from ezdxf.addons.drawing.pipeline import RenderPipeline2d
    from ezdxf.npshapes import to_matplotlib_path

    if not getattr(RenderPipeline2d.draw_text, "_kurtshape_glyphs", False):
        plain_draw_text = RenderPipeline2d.draw_text

        def draw_text(self, *args, **kwargs):
            backend = self.backend
            before = getattr(backend, "in_text", False)
            backend.in_text = True
            try:
                return plain_draw_text(self, *args, **kwargs)
            finally:
                backend.in_text = before
        draw_text._kurtshape_glyphs = True
        RenderPipeline2d.draw_text = draw_text

    class GlyphSafeBackend(MatplotlibBackend):
        in_text = False

        def draw_filled_paths(self, paths, properties):
            if not self.in_text:
                return super().draw_filled_paths(paths, properties)
            try:
                patch = PathPatch(to_matplotlib_path(paths, detect_holes=False), color=properties.color,
                                  linewidth=0, fill=True, zorder=self._get_z())
            except ValueError:
                return
            self.ax.add_patch(patch)

    return GlyphSafeBackend(ax, adjust_figure=False)


# ---------------------------------------------------------------------- helpers
_NO_LINE_START = set("，。；：、）)」』！？,.;:!?%°")
_NO_LINE_END = set("（(「『")


def _has_cjk(s):
    return any("　" <= ch <= "鿿" or "＀" <= ch <= "￯" for ch in s)


_GLUE = " ⁠"      # no-break space, word joiner: never break here


def _tokens(text):
    """Break opportunities: a CJK character (or full-width mark) is its own token, a run of
    Latin characters stays whole, and spaces are separate tokens. A no-break space or word
    joiner glues its neighbours into one token, Latin or CJK ('630\\u00a0型' stays whole)."""
    raw, cur = [], ""
    for ch in text:
        if ch == " ":
            if cur:
                raw.append(cur)
                cur = ""
            raw.append(" ")
        elif _has_cjk(ch):
            if cur:
                raw.append(cur)
                cur = ""
            raw.append(ch)
        else:
            cur += ch
    if cur:
        raw.append(cur)
    out = []
    for tok in raw:
        if out and (out[-1][-1] in _GLUE or tok[0] in _GLUE):
            out[-1] += tok
        else:
            out.append(tok)
    return out


def _plain(s):
    """Text as printed: glue marks become an ordinary space or nothing."""
    return s.replace(" ", " ").replace("⁠", "")


def _consumed(text, line):
    """The prefix of ``text`` that produced ``line`` (line breaks drop spaces only)."""
    i = j = 0
    while j < len(line) and i < len(text):
        if text[i] == line[j]:
            i += 1
            j += 1
        elif text[i] == " ":
            i += 1
        else:
            break
    return text[:i]


def _wrap(text, width):
    """Character-count wrap (kept for callers that pass width_chars)."""
    if _has_cjk(text):
        out, cur, w = [], "", 0.0
        for tok in _tokens(text):
            tw = sum(1.0 if _has_cjk(c) else 0.55 for c in tok)
            if cur and w + tw > width and tok not in _NO_LINE_START and tok.strip():
                out.append(cur.rstrip())
                cur, w = "", 0.0
                if not tok.strip():
                    continue
            cur += tok
            w += tw
        if cur.strip():
            out.append(cur.rstrip())
        return [ln.lstrip() for ln in out]
    words, out, cur = text.split(), [], ""
    for wd in words:
        if cur and len(cur) + 1 + len(wd) > width:
            out.append(cur)
            cur = wd
        else:
            cur = f"{cur} {wd}" if cur else wd
    if cur:
        out.append(cur)
    return out


def _area(loop):
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(loop, list(loop[1:]) + [loop[0]]))


def _norm(s):
    s = s.replace("%%c", "Ø").replace("%%C", "Ø").replace("%%d", "°").replace("%%D", "°")
    s = s.replace("%%p", "±").replace("%%P", "±").replace("⌀", "Ø")
    return "".join(s.split())


def _dim_text(dim_entity):
    """Plain text of a rendered DIMENSION (its geometry block's MTEXT)."""
    parts = []
    for e in dim_entity.virtual_entities():
        if e.dxftype() == "MTEXT":
            parts.append(e.plain_text())
        elif e.dxftype() == "TEXT":
            parts.append(e.dxf.text)
    return _norm(" ".join(parts))


def _orient(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _cross_properly(a, b, c, d, eps=1e-9):
    """Segments ab and cd cross at a point inside both (touching ends or collinear: no)."""
    o1, o2 = _orient(a, b, c), _orient(a, b, d)
    o3, o4 = _orient(c, d, a), _orient(c, d, b)
    return o1 * o2 < -eps and o3 * o4 < -eps


def _seg_x(a, b, c, d):
    """Point where the lines through ab and cd meet (the caller knows they cross)."""
    den = (b[0] - a[0]) * (d[1] - c[1]) - (b[1] - a[1]) * (d[0] - c[0])
    if abs(den) < 1e-12:
        return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    t = ((c[0] - a[0]) * (d[1] - c[1]) - (c[1] - a[1]) * (d[0] - c[0])) / den
    return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))


def _pt_seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 < 1e-18 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def check_set(sheets):
    """Checks across the sheets of one drawing (each a :class:`Sheet` whose SHEET field reads
    'n OF N'), which a single sheet cannot make: sheet numbering, the title-block entries every
    sheet repeats, and that a section or detail drawn on one sheet has its cutting-plane line or
    detail circle on the sheet it names (standard rule 7), both ways. Returns findings like
    :meth:`Sheet.lint`; a multi-sheet drawing ships with none."""
    out = []

    def add(kind, rule, text, with_):
        out.append({"kind": kind, "rule": rule, "text": text, "with": with_, "at": []})
    by_no = {sh.sheet_no: sh for sh in sheets}
    total = len(sheets)
    if sorted(k for k in by_no if k is not None) != list(range(1, total + 1)) or \
            any(sh.sheet_total != total for sh in sheets):
        add("sheet-numbers", 0, f"sheets {[(sh.sheet_no, sh.sheet_total) for sh in sheets]}",
            f"the SHEET fields must read 1 OF {total} to {total} OF {total}")
    for key in ("TITLE", "DWG_NO", "REV", "SCALE", "WEIGHT"):
        values = {sh._field_text(key) for sh in sheets if key in (sh.map.get("fields") or {})}
        if len(values) > 1:
            add("set-field", 0, f"{key}: {sorted(values)}", "every sheet of a drawing states the same value")
    for sh in sheets:
        for pv in sh._placed:
            if not pv.parent_sheet:
                continue
            parent = by_no.get(pv.parent_sheet)
            letters = {} if parent is None else (parent._cut_letters if pv.kind == "section" else parent._detail_letters)
            if letters.get(pv.letter) != sh.sheet_no:
                add("section-line" if pv.kind == "section" else "detail-circle", 7,
                    f"{pv.kind} {pv.letter} on sheet {sh.sheet_no}",
                    f"sheet {pv.parent_sheet} has no matching "
                    f"{'cutting_plane' if pv.kind == 'section' else 'detail_circle'}(..., view_sheet={sh.sheet_no})")
        for letters, kind in ((sh._cut_letters, "section"), (sh._detail_letters, "detail")):
            for letter, target in letters.items():
                if target is None:
                    continue
                other = by_no.get(target)
                if other is None or not any(pv.kind == kind and pv.letter == letter and pv.parent_sheet == sh.sheet_no
                                            for pv in other._placed):
                    add("section-line" if kind == "section" else "detail-circle", 7,
                        f"{'cutting plane' if kind == 'section' else 'detail circle'} {letter} on sheet {sh.sheet_no}",
                        f"sheet {target} has no {kind} view {letter} placed with parent_sheet={sh.sheet_no}")
    return out


def _is_simple(loop, eps=1e-9):
    """A closed polygon that neither crosses itself nor runs back along its own edges."""
    n = len(loop)
    edges = [(loop[i], loop[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        a, b = edges[i]
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            c, d = edges[j]
            if _cross_properly(a, b, c, d):
                return False
            if abs(_orient(a, b, c)) < eps and abs(_orient(a, b, d)) < eps:   # collinear: overlap?
                ux, uy = b[0] - a[0], b[1] - a[1]
                L2 = ux * ux + uy * uy
                if L2 < eps:
                    continue
                t0 = ((c[0] - a[0]) * ux + (c[1] - a[1]) * uy) / L2
                t1 = ((d[0] - a[0]) * ux + (d[1] - a[1]) * uy) / L2
                if min(max(t0, t1), 1.0) - max(min(t0, t1), 0.0) > 1e-6:
                    return False
    return True


def _mtext_box(e):
    """Axis-aligned sheet box of an MTEXT, from ezdxf's layout of its real fonts."""
    g = _mtext_geom(e)
    if g is None:
        return None
    xs, ys = [p[0] for p in g[0]], [p[1] for p in g[0]]
    return (min(xs), min(ys), max(xs), max(ys))


def _mtext_obox(e):
    """The MTEXT's own rectangle when it is turned off the sheet axes (an aligned dimension's
    value): (centre x, centre y, width, height, angle in radians); None for upright or
    quarter-turned text, whose axis-aligned box is already exact."""
    g = _mtext_geom(e)
    if g is None:
        return None
    pts, ang, w, hgt = g
    if abs(math.sin(2.0 * ang)) < 1e-6:
        return None
    return (sum(p[0] for p in pts) / 4.0, sum(p[1] for p in pts) / 4.0, w, hgt, ang)


def _obox_corners(ob, grow_w=0.0, grow_h=0.0):
    cx, cy, w, hgt, ang = ob
    c, s = math.cos(ang), math.sin(ang)
    hw, hh = w / 2 + grow_w, hgt / 2 + grow_h
    return [(cx + c * x - s * y, cy + s * x + c * y) for x, y in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))]


def _seg_hits_obox(x0, y0, x1, y1, ob, grow_w=0.0, grow_h=0.0):
    """Does a segment enter a rotated text rectangle (grown by grow_w / grow_h per side)?"""
    cx, cy, w, hgt, ang = ob
    c, s = math.cos(ang), math.sin(ang)

    def loc(x, y):
        dx, dy = x - cx, y - cy
        return c * dx + s * dy, -s * dx + c * dy
    a, b = loc(x0, y0), loc(x1, y1)
    hw, hh = w / 2 + grow_w, hgt / 2 + grow_h
    return _seg_hits_box(a[0], a[1], b[0], b[1], -hw, -hh, hw, hh)


def _rects_overlap(p, q):
    """Separating-axis test of two convex quadrilaterals (corner lists)."""
    for poly in (p, q):
        for i in range(4):
            ax, ay = poly[i]
            bx, by = poly[(i + 1) % 4]
            nx, ny = ay - by, bx - ax
            pa = [nx * x + ny * y for x, y in p]
            pb = [nx * x + ny * y for x, y in q]
            if max(pa) <= min(pb) or max(pb) <= min(pa):
                return False
    return True


def _mtext_geom(e):
    """Corners of an MTEXT's laid-out rectangle on the sheet, its angle, width and height."""
    from ezdxf.tools.text_size import mtext_size
    if not e.plain_text().strip():
        return None
    size = mtext_size(e)
    w, hgt = size.total_width, size.total_height
    if w <= 0 or hgt <= 0:
        return None
    if e.dxf.get("width", 0) and e.doc is not None:
        # a fixed-width column (template cells) spans the whole cell: measure the ink instead
        from ezdxf.fonts import fonts
        st = e.doc.styles.get(e.dxf.style) if e.dxf.style in e.doc.styles else None
        font = fonts.make_font((st.dxf.get("font", "") if st else "") or LATIN_FONT[1], e.dxf.char_height)
        ink = max((font.text_width(ln) for ln in e.plain_text().split("\n") if ln.strip()), default=0.0)
        if 0 < ink < w:
            w = ink
    ap = int(e.dxf.get("attachment_point", 1))
    col, row = (ap - 1) % 3, (ap - 1) // 3                 # 0 left/top, 1 centre/middle, 2 right/bottom
    lx = (0.0, -w / 2, -w)[col]
    ly = (-hgt, -hgt / 2, 0.0)[row]
    # leading blank lines ('\P' used to push text down a cell) carry no ink: drop them from the box
    lines = e.plain_text().split("\n")
    lead = len(lines) - len(e.plain_text().lstrip("\n").split("\n"))
    if 0 < lead < len(lines):
        hgt -= hgt * lead / len(lines)
    if e.dxf.hasattr("text_direction"):
        d = e.dxf.text_direction
        ang = math.atan2(d[1], d[0])
    else:
        ang = math.radians(e.dxf.get("rotation", 0.0))
    c, s = math.cos(ang), math.sin(ang)
    ix, iy = e.dxf.insert[0], e.dxf.insert[1]
    pts = [(ix + c * x - s * y, iy + s * x + c * y) for x, y in ((lx, ly), (lx + w, ly), (lx + w, ly + hgt), (lx, ly + hgt))]
    return pts, ang, w, hgt


def _seg_hits_box(x0, y0, x1, y1, bx0, by0, bx1, by1):
    """Liang-Barsky: does segment (x0,y0)-(x1,y1) enter the box?"""
    if bx1 <= bx0 or by1 <= by0:
        return False
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - bx0), (dx, bx1 - x0), (-dy, y0 - by0), (dy, by1 - y0)):
        if abs(p) < 1e-12:
            if q < 0:
                return False
        else:
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 > t1:
                return False
    return True


def _inside_evenodd(pt, loops):
    x, y = pt
    inside = False
    for lp in loops:
        n = len(lp)
        for i in range(n):
            (ax, ay), (bx, by) = lp[i], lp[(i + 1) % n]
            if (ay > y) != (by > y):
                xc = ax + (y - ay) * (bx - ax) / (by - ay)
                if xc > x:
                    inside = not inside
    return inside


def _clip_samples(pts, centre, r):
    """Split a polyline into the runs inside the circle (centre, r) (view coordinates)."""
    cx, cy = centre

    def inside(p):
        return math.hypot(p[0] - cx, p[1] - cy) <= r
    dense = []
    for a, b in zip(pts[:-1], pts[1:]):
        n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / (r / 200.0)))
        for k in range(n):
            dense.append((a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n))
    dense.append(pts[-1])
    runs, cur = [], []
    for p in dense:
        if inside(p):
            cur.append(p)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return runs


def _clip_polygon_circle(poly, centre, r, n=128):
    """Sutherland-Hodgman clip of a polygon against a circle (approximated by an n-gon)."""
    cx, cy = centre
    clip = [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)]
    out = list(poly)
    for i in range(n):
        a, b = clip[i], clip[(i + 1) % n]
        inp, out = out, []
        if not inp:
            break

        def side(p):
            return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])

        def cross(p, q):
            sp, sq = side(p), side(q)
            t = sp / (sp - sq)
            return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)
        s = inp[-1]
        for e in inp:
            if side(e) >= 0:
                if side(s) < 0:
                    out.append(cross(s, e))
                out.append(e)
            elif side(s) >= 0:
                out.append(cross(s, e))
            s = e
    return out
