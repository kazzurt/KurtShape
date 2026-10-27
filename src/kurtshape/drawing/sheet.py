"""Drawing sheet on a DXF template, drafted with ezdxf (MIT), rendered to PDF with matplotlib.

Coordinates: the template sheet lives in DXF modelspace at 1:1 paper millimetres. A view is
placed with :meth:`Sheet.place` at a sheet origin and a scale; every annotation method takes
points in that view's true-size coordinates (``pv``) or plain sheet coordinates.
Dimensions are real DIMENSION entities whose dimstyle carries DIMLFAC = 1/scale, so they read
true size in any CAD program.

What the sheet checks, so a drawing cannot silently say something the model does not:

- every dimension's definition points lie on the projected view geometry (inside the detail
  circle for a detail view); radius dimensions need a real arc of that radius and centre;
  angular dimensions check a point on each leg;
- the rendered dimension text equals the text the spec expects (``expect=``);
- hatch loops are closed and non-degenerate;
- :meth:`Sheet.lint` finds text that touches other text, view geometry, frames or hatching.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
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


class DrawingError(RuntimeError):
    pass


@dataclass
class Placed:
    view: object
    origin: tuple
    scale: float
    name: str
    clip: tuple = None        # (centre_view_xy, radius_view) for detail views

    def s(self, p):
        return (self.origin[0] + self.scale * p[0], self.origin[1] + self.scale * p[1])


def _fmt(v, dec):
    return f"{v:.{dec}f}"


class Sheet:
    def __init__(self, template, template_map="aerial_hedra_b_mm.json", lang="en"):
        self.lang = lang
        self.map = json.loads((TEMPLATES / template_map).read_text(encoding="utf-8"))
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
        dx.dimdec = 2
        dx.dimtdec = 2
        dx.dimadec = 0
        dx.dimzin = 0
        dx.dimtzin = 0
        dx.dimazin = 0
        dx.dimtfac = TOL_FACTOR
        dx.dimlfac = 1.0 / scale
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
              hatch=True, hatch_scale=0.7, smooth_layer="AH_THIN"):
        pv = Placed(view, origin, scale, name or view.name, clip=clip)
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

    def label(self, pos, lines, h=3.5, attach="TOP_CENTER", sub_h=2.8):
        with self.group("label"):
            content = lines[0] if isinstance(lines, (list, tuple)) else lines
            e = self.text(pos, content, h=h, attach=attach)
            if isinstance(lines, (list, tuple)) and len(lines) > 1:
                self.text((pos[0], pos[1] - h * 1.6), "\\P".join(lines[1:]), h=sub_h, attach=attach)
        return e

    # ------------------------------------------------------------------ verification
    def _verify(self, pv, pts, what, tol=0.01):
        for p in pts:
            d = pv.view.distance(p)
            rec = {"dim": what, "view": pv.name, "point": [round(p[0], 4), round(p[1], 4)], "distance": round(d, 6)}
            if pv.clip:
                rec["inside_detail"] = math.hypot(p[0] - pv.clip[0][0], p[1] - pv.clip[0][1]) <= pv.clip[1] + 1e-9
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
            dim.set_tolerance(tol[1], hfactor=TOL_FACTOR, dec=tol[2] if len(tol) > 2 else 2)
        elif kind == "dev":                   # ("dev", upper, lower)  e.g. ("dev", 0.08, 0)
            upper, lower = tol[1], tol[2]
            if lower > 0 or upper < 0:
                raise DrawingError(f"deviation tolerance must straddle zero: {tol}")
            dim.set_tolerance(upper, -lower, hfactor=TOL_FACTOR, dec=tol[3] if len(tol) > 3 else 2)
            dim["dimtzin"] = 8             # print the zero deviation as '0', not '0.00'
        elif kind == "limits":
            dim.set_limits(tol[1], tol[2], hfactor=TOL_FACTOR, dec=tol[3] if len(tol) > 3 else 2)

    def dim_linear(self, pv, p1, p2, base, angle=0, text="<>", tol=None, dec=2, verify=True, what=None,
                   override=None, text_pos=None, expect=None, mask=False):
        """Linear dimension between view points p1, p2; ``base`` is a view point the dimension
        line passes through (angle 0 horizontal, 90 vertical). ``mask`` blanks the lines behind
        its text (DIMTFILL)."""
        what = what or text
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
        boxes = [_mtext_box(ve) for ve in dim.dimension.virtual_entities() if ve.dxftype() == "MTEXT"]
        if not boxes or boxes[0] is None:
            return
        x0, y0, x1, y1 = boxes[0]
        a = math.radians(angle)
        ux, uy = math.cos(a), math.sin(a)
        b = pv.s(base)
        ends = sorted((pv.s(p)[0] * ux + pv.s(p)[1] * uy) for p in (p1, p2))
        lo, hi = sorted(((x0 * ux + y0 * uy), (x1 * ux + y1 * uy)))
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

    def dim_radius(self, pv, centre, r, angle, text="R<>", tol=None, dec=2, location=None, verify=True, what=None,
                   expect=None):
        what = what or text
        if verify:
            a = math.radians(angle)
            self._verify(pv, ((centre[0] + r * math.cos(a), centre[1] + r * math.sin(a)),), what)
            arcs = [c for c in pv.view.curves if c.kind in ("arc", "circle") and abs(c.r - r) < 1e-4
                    and math.hypot(c.c[0] - centre[0], c.c[1] - centre[1]) < 1e-4]
            self.checks.append({"dim": what, "view": pv.name, "arc_found": bool(arcs)})
            if not arcs:
                raise DrawingError(f"{what}: no arc of radius {r} centred at {centre} in {pv.name}")
        # horizontal (unidirectional) text on the leader, as radius callouts are read
        # (and lifted off the landing so the leader's leg clears the last character); no line from
        # the centre to the arc (DIMTOFL 0): a small radius is called out from outside only
        ov = {"dimdec": dec, "dimtdec": dec, "dimtmove": 1, "dimlfac": 1.0 / pv.scale, "dimtih": 1, "dimtoh": 1,
              "dimgap": 2.0, "dimtofl": 0}
        dim = self.msp.add_radius_dim(center=pv.s(centre), radius=r * pv.scale, angle=angle, text=text,
                                      dimstyle=self.dimstyle(pv.scale), override=ov, dxfattribs={"layer": "AH_DIM"})
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
    def leader(self, target, text_pos, content, h=DIM_TEXT, side=None, pv=None, verify=True, what=None, arrow=True):
        """Leader from ``target`` (view point when pv is given, else sheet point) to a note at
        ``text_pos`` (sheet). The text sits on a short shoulder, left or right of the elbow."""
        if pv is not None:
            if verify:
                self._verify(pv, (target,), what or content)
            t = pv.s(target)
        else:
            t = target
        side = side or ("right" if text_pos[0] >= t[0] else "left")
        shoulder = 3.0 if side == "right" else -3.0
        elbow = text_pos
        end = (elbow[0] + shoulder, elbow[1])
        with self.group("leader"):
            if arrow:
                self.msp.add_leader([t, elbow, end], dimstyle=self.dimstyle(1.0), dxfattribs={"layer": "AH_DIM"})
            else:
                self.msp.add_lwpolyline([t, elbow, end], dxfattribs={"layer": "AH_DIM"})
            if not content:
                return None
            attach = "MIDDLE_LEFT" if side == "right" else "MIDDLE_RIGHT"
            tx = end[0] + (0.8 if side == "right" else -0.8)
            return self.text((tx, end[1]), content, h=h, attach=attach, layer="AH_DIM")

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

    def cutting_plane(self, pv, p, q, letter, toward, h=4.0):
        """Section cutting-plane line between view points p, q with arrows pointing ``toward``
        (unit 2D direction of sight) and the section letter at both ends."""
        a, b = pv.s(p), pv.s(q)
        ux, uy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(ux, uy)
        ux, uy = ux / L, uy / L
        seg = 6.0
        with self.group("cutting-plane"):
            for end, sgn in ((a, 1), (b, -1)):
                inner = (end[0] + sgn * ux * seg, end[1] + sgn * uy * seg)
                self.msp.add_line(end, inner, dxfattribs={"layer": "AH_CUTLINE"})
                head = (end[0] + toward[0] * 7.0, end[1] + toward[1] * 7.0)
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

    def detail_circle(self, pv, centre, r, letter, label_at, h=4.0):
        c = pv.s(centre)
        with self.group("detail-circle"):
            self.msp.add_circle(c, r * pv.scale, dxfattribs={"layer": "AH_THIN"})
            self.text(label_at, letter, h=h, attach="MIDDLE_CENTER", style=LATIN_FONT[0], layer="AH_TEXT")

    # ------------------------------------------------------------------ title block / template text
    def fill(self, fields):
        for key, value in fields.items():
            spec = self.map["fields"].get(key)
            if spec is None:
                raise DrawingError(f"template has no field {key}")
            e = self.doc.entitydb.get(spec["handle"])
            if e is None:
                raise DrawingError(f"field {key}: handle {spec['handle']} missing in template")
            e.text = value if value is not None else ""
            e.dxf.style = CJK_FONT[0] if _has_cjk(value or "") else LATIN_FONT[0]
            if "ch" in spec:
                e.dxf.char_height = spec["ch"]
            if "width" in spec:
                e.dxf.width = spec["width"]
            self.touch(spec["handle"])

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

    def blank_placeholders(self):
        """Onshape leaves '----' / '-' placeholders that its own PDF hides."""
        for e in self.msp.query("MTEXT"):
            if e.plain_text().strip() in ("----", "-", ""):
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

    def revision_row(self, index, rev, description, approved="", h=None, height=None, min_h=2.5):
        """Revision table row below the template's row A (index 1 = first added row, standard
        height unless ``height`` is given). A long description wraps onto as many lines as the
        row holds, its text shrinking until it fits; below ``min_h`` the drawing fails (shorten
        the description or give the row more height)."""
        rt = self.map["revision_table"]
        height = height or rt["row_height"]
        y1 = rt["first_row_y"][0] - (index - 1) * rt["row_height"]
        y0 = y1 - height
        cols = rt["columns_x"]
        x0, x1 = cols["REV"][0], cols["APPROVED"][1]
        lay = {"layer": "TABLES", "lineweight": 25}
        h = h or rt["data_ch"]
        ym = (y0 + y1) / 2
        avail = cols["DESCRIPTION"][1] - cols["DESCRIPTION"][0] - 3.0
        with self.group("revision-row"):
            self.msp.add_line((x0, y0), (x1, y0), dxfattribs=lay)
            for xs in (x0, cols["DESCRIPTION"][0], cols["APPROVED"][0], x1):
                self.msp.add_line((xs, y0), (xs, y1), dxfattribs=lay)
            self.text((cols["REV"][0] + 1.524, ym), rev, h=h, attach="MIDDLE_LEFT", layer="TABLES")
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
            self.text((cols["DESCRIPTION"][0] + 1.524, ym_text), "\\P".join(_plain(ln) for ln in lines), h=dh,
                      attach="MIDDLE_LEFT", layer="TABLES")
            if approved:
                self.text((cols["APPROVED"][0] + 1.524, ym), approved, h=h, attach="MIDDLE_LEFT", layer="TABLES")

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
        under the last line."""
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
          or hatching (centre lines may be masked)."""
        import numpy as np
        from ezdxf import path as ezpath

        texts, segs, hatches, wipeouts = [], [], [], []

        def owner(e, fallback):
            return self._owner.get(e.dxf.handle, fallback)

        def add_text(e, gid, masked, label):
            try:
                box = _mtext_box(e)
            except Exception as exc:  # noqa: BLE001
                self.issues.append(f"lint: cannot measure text {label!r}: {exc}")
                return
            if box is None:
                return
            rot = (e.dxf.get("rotation", 0.0) or 0.0) % 180.0
            texts.append({"box": box, "gid": gid, "masked": masked, "label": label,
                          "h": e.dxf.get("char_height", 2.5), "upright": not (45.0 < rot < 135.0)})

        def add_path(p, gid, layer):
            pts = list(p.flattening(0.02))
            for a, b in zip(pts[:-1], pts[1:]):
                segs.append((a.x, a.y, b.x, b.y, gid, layer))

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
                    add_text(e, gid, masked, e.plain_text().replace("\n", " | ")[:60])
            elif t == "DIMENSION":
                masked = bool(e.override().get("dimtfill", 0))
                for ve in e.virtual_entities():
                    vt = ve.dxftype()
                    if vt == "MTEXT":
                        add_text(ve, gid, masked, "dim " + ve.plain_text().replace("\n", " ")[:40])
                    elif vt in ("LINE", "ARC"):
                        # a dimension's own lines are tested against its own text too: text sits
                        # clear of its dimension and extension lines, never across a leader
                        add_path(ezpath.make_path(ve), gid + "/own", "AH_DIM")
            elif t in ("LINE", "LWPOLYLINE", "ARC", "CIRCLE", "POLYLINE", "SPLINE"):
                try:
                    add_path(ezpath.make_path(e), gid, e.dxf.layer)
                except Exception:  # noqa: BLE001
                    pass
            elif t == "LEADER":
                # the shoulder (last segment) belongs to its note; the legs must not cross that note
                v = [tuple(p)[:2] for p in e.vertices]
                for k, (a, b) in enumerate(zip(v[:-1], v[1:])):
                    segs.append((a[0], a[1], b[0], b[1], gid if k == len(v) - 2 else gid + "/leg", "AH_DIM"))
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
                cand = np.nonzero((smax_x >= bx0) & (smin_x <= bx1) & (smax_y >= by0) & (smin_y <= by1))[0]
                for k in cand:
                    sx0, sy0, sx1, sy1, gid, layer = segs[k]
                    if gid == t["gid"]:
                        continue
                    if _seg_hits_box(sx0, sy0, sx1, sy1, bx0, by0, bx1, by1):
                        clashes.append({"kind": "text-line", "text": t["label"], "with": f"{layer} ({gid})",
                                        "at": [round((x0 + x1) / 2, 2), round((y0 + y1) / 2, 2)]})
                        break
                for loops, gid in hatches:
                    if gid == t["gid"]:
                        continue
                    probes = [(x0 + shrink, y0 + shrink), (x1 - shrink, y0 + shrink), (x0 + shrink, y1 - shrink),
                              (x1 - shrink, y1 - shrink), ((x0 + x1) / 2, (y0 + y1) / 2)]
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
                if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
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
        out = [c for c in clashes if not any(s in c["text"] or s in c["with"] for s in ignore)]
        return out

    # ------------------------------------------------------------------ output
    def save(self, path):
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
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


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
