"""Orthographic and section views of a solid as exact 2D geometry (FreeCAD / OCCT HLR).

A view frame is two orthonormal world vectors ``x_axis`` and ``y_axis``; the viewer looks from
``x_axis x y_axis`` toward the model (third- or first-angle placement is the sheet's business).
Results are true-size 2D curves in that frame: ``View.curves`` (lines, arcs, circles and
polylines, each with a style) and ``View.hatch`` (closed section-face loops).

Styles: ``visible`` (sharp and silhouette edges), ``smooth`` (visible tangent edges, drafting
convention draws them thin or not at all), ``hidden`` (hidden sharp and silhouette edges) and
``section`` (boundary of a cut face; also visible).
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

import FreeCAD as App
import Part
import TechDraw

V = App.Vector
POLY_DEFLECTION = 0.002     # mm, chordal tolerance for B-spline / ellipse edges
EPS = 1e-7


@dataclass
class Curve:
    kind: str                 # line | arc | circle | poly
    style: str
    p: tuple = None           # line start
    q: tuple = None           # line end
    c: tuple = None           # arc / circle centre
    r: float = None
    a0: float = None          # arc start angle (deg, CCW)
    a1: float = None          # arc end angle (deg, CCW)
    pts: list = None          # polyline points

    def to_dict(self):
        return {k: v for k, v in self.__dict__.items() if v is not None}

    def sample(self, n=48):
        if self.kind == "line":
            return [self.p, self.q]
        if self.kind == "poly":
            return list(self.pts)
        a0, a1 = (0.0, 360.0) if self.kind == "circle" else (self.a0, self.a1 if self.a1 > self.a0 else self.a1 + 360)
        return [(self.c[0] + self.r * math.cos(math.radians(a0 + (a1 - a0) * k / n)),
                 self.c[1] + self.r * math.sin(math.radians(a0 + (a1 - a0) * k / n))) for k in range(n + 1)]

    def distance(self, pt):
        x, y = pt
        if self.kind in ("circle", "arc"):
            dx, dy = x - self.c[0], y - self.c[1]
            d = abs(math.hypot(dx, dy) - self.r)
            if self.kind == "circle":
                return d
            ang = math.degrees(math.atan2(dy, dx)) % 360
            a0, a1 = self.a0 % 360, self.a1 % 360
            inside = (a0 <= ang <= a1) if a0 <= a1 else (ang >= a0 or ang <= a1)
            if inside:
                return d
            ends = self.sample(1)
            return min(math.hypot(x - e[0], y - e[1]) for e in (ends[0], ends[-1]))
        pts = self.sample()
        return min(_seg_dist(pt, a, b) for a, b in zip(pts[:-1], pts[1:]))


def _seg_dist(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 < 1e-18 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    return math.hypot(p[0] - ax - t * dx, p[1] - ay - t * dy)


@dataclass
class View:
    name: str
    curves: list = field(default_factory=list)
    hatch: list = field(default_factory=list)     # list of closed loops [(x, y), ...]
    meta: dict = field(default_factory=dict)

    def bbox(self, styles=("visible", "section", "hidden", "smooth")):
        xs, ys = [], []
        for c in self.curves:
            if c.style in styles:
                for x, y in c.sample(16):
                    xs.append(x)
                    ys.append(y)
        return (min(xs), min(ys), max(xs), max(ys)) if xs else (0, 0, 0, 0)

    def distance(self, pt, styles=("visible", "section", "hidden", "smooth")):
        """Distance from a view point to the nearest curve of the given styles."""
        return min((c.distance(pt) for c in self.curves if c.style in styles), default=float("inf"))

    def add(self, curve):
        self.curves.append(curve)
        return curve

    def to_dict(self):
        return {"name": self.name, "curves": [c.to_dict() for c in self.curves], "hatch": self.hatch, "meta": self.meta}


def _frame_matrix(x_axis, y_axis):
    x = V(*x_axis)
    y = V(*y_axis)
    x.normalize()
    y.normalize()
    if abs(x.dot(y)) > 1e-9:
        raise ValueError("view axes must be orthogonal")
    n = x.cross(y)
    m = App.Matrix(x.x, x.y, x.z, 0, y.x, y.y, y.z, 0, n.x, n.y, n.z, 0, 0, 0, 0, 1)
    return m


def to_view_frame(shape, x_axis, y_axis):
    """Copy of ``shape`` rotated so the view frame becomes world X, Y (viewer on +Z)."""
    m = _frame_matrix(x_axis, y_axis)
    s = shape.copy()
    s.transformShape(m, True)
    return s


def _edge_curves(edge, style):
    """Projected edge (in the XY plane) -> list of Curve."""
    if edge.Length < 1e-9:
        return []
    c = edge.Curve
    t = type(c).__name__
    if t in ("Line", "LineSegment"):
        a, b = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
        return [Curve("line", style, p=(a.x, a.y), q=(b.x, b.y))]
    if t == "Circle":
        centre, r = c.Center, c.Radius
        if edge.isClosed() or abs(edge.Length - 2 * math.pi * r) < 1e-7:
            return [Curve("circle", style, c=(centre.x, centre.y), r=r)]
        p0 = edge.valueAt(edge.FirstParameter)
        p1 = edge.valueAt(edge.LastParameter)
        pm = edge.valueAt(0.5 * (edge.FirstParameter + edge.LastParameter))
        a0 = math.degrees(math.atan2(p0.y - centre.y, p0.x - centre.x))
        a1 = math.degrees(math.atan2(p1.y - centre.y, p1.x - centre.x))
        am = math.degrees(math.atan2(pm.y - centre.y, pm.x - centre.x))
        # choose the CCW direction that passes through the mid point
        if not _ccw_contains(a0, a1, am):
            a0, a1 = a1, a0
        return [Curve("arc", style, c=(centre.x, centre.y), r=r, a0=a0 % 360, a1=a1 % 360)]
    pts = edge.discretize(Deflection=POLY_DEFLECTION)
    return [Curve("poly", style, pts=[(p.x, p.y) for p in pts])]


def _ccw_contains(a0, a1, am):
    sweep = (a1 - a0) % 360
    return (am - a0) % 360 <= sweep + 1e-9


def _collect(view, compound, style):
    if compound is None or compound.isNull():
        return
    for e in compound.Edges:
        for curve in _edge_curves(e, style):
            view.add(curve)


def project(shape, x_axis, y_axis, name="view", hidden=False, smooth=True):
    """Hidden-line-removed orthographic view of ``shape`` in the frame (x_axis, y_axis)."""
    s = to_view_frame(shape, x_axis, y_axis)
    res = TechDraw.projectEx(s, V(0, 0, 1))
    # [V, V1, VN, VO, VI, H, H1, HN, HO, HI]: sharp, smooth, seam, outline, iso (visible / hidden)
    view = View(name, meta={"x_axis": list(x_axis), "y_axis": list(y_axis)})
    _collect(view, res[0], "visible")
    _collect(view, res[3], "visible")
    if smooth:
        _collect(view, res[1], "smooth")
    if hidden:
        _collect(view, res[5], "hidden")
        _collect(view, res[8], "hidden")
    return view


def section(shape, x_axis, y_axis, offset=0.0, name="section", hidden=False, smooth=True, big=1000.0):
    """Section view: the material on the viewer's side of the plane (normal x_axis x y_axis,
    through ``offset`` along it) is removed; the rest is projected and its cut faces hatched."""
    s = to_view_frame(shape, x_axis, y_axis)
    box = Part.makeBox(2 * big, 2 * big, big, V(-big, -big, offset))
    kept = s.cut(box)
    if kept.isNull() or not kept.Solids or not kept.isValid():
        raise RuntimeError(f"{name}: the section cut failed (invalid solid); use a BOP-valid drawing body")
    res = TechDraw.projectEx(kept, V(0, 0, 1))
    view = View(name, meta={"x_axis": list(x_axis), "y_axis": list(y_axis), "offset": offset,
                            "kept_volume": kept.Volume})
    _collect(view, res[0], "visible")
    _collect(view, res[3], "visible")
    if smooth:
        _collect(view, res[1], "smooth")
    if hidden:
        _collect(view, res[5], "hidden")
        _collect(view, res[8], "hidden")
    for f in kept.Faces:
        srf = f.Surface
        if type(srf).__name__ != "Plane":
            continue
        # A cut face lies in the plane. Vertices alone are not enough: a half-annulus end face of
        # a revolved part also has all its vertices on the cut line but stands across the plane.
        if abs(abs(srf.Axis.z) - 1.0) < 1e-9 and abs(srf.Position.z - offset) < 1e-6:
            loops = [_wire_loop(w) for w in f.Wires]
            # outer minus inner loops must give the face's own area (catches a mis-ordered loop)
            areas = sorted((abs(_area(lp)) for lp in loops), reverse=True)
            net = areas[0] - sum(areas[1:])
            if abs(net - f.Area) > 1e-3 * max(f.Area, 1e-9) + 1e-6:
                raise RuntimeError(f"{name}: cut-face loops give area {net:.6f}, the face has {f.Area:.6f}")
            view.hatch.extend(loops)
    if not view.hatch:
        raise RuntimeError(f"{name}: no cut face found in the section plane")
    return view


def _wire_loop(w):
    """Closed 2D point loop of a wire in its own edge order (no closing duplicate)."""
    edges = Part.__sortEdges__(w.Edges)
    loop = []
    for k, e in enumerate(edges):
        seq = [(p.x, p.y) for p in e.discretize(Deflection=POLY_DEFLECTION)]
        if k == 0 and len(edges) > 1:
            # orient the first edge so that its end meets the second edge
            nxt = [(v.Point.x, v.Point.y) for v in edges[1].Vertexes]
            d_end = min(math.hypot(seq[-1][0] - q[0], seq[-1][1] - q[1]) for q in nxt)
            d_start = min(math.hypot(seq[0][0] - q[0], seq[0][1] - q[1]) for q in nxt)
            if d_start < d_end:
                seq.reverse()
        elif loop and math.hypot(loop[-1][0] - seq[0][0], loop[-1][1] - seq[0][1]) > \
                math.hypot(loop[-1][0] - seq[-1][0], loop[-1][1] - seq[-1][1]):
            seq.reverse()
        if loop and math.hypot(loop[-1][0] - seq[0][0], loop[-1][1] - seq[0][1]) > 1e-6:
            raise RuntimeError(f"cut-face loop has a gap of {math.hypot(loop[-1][0] - seq[0][0], loop[-1][1] - seq[0][1]):.2e} mm")
        loop.extend(seq if not loop else seq[1:])
    if len(loop) > 2 and math.hypot(loop[0][0] - loop[-1][0], loop[0][1] - loop[-1][1]) < 1e-6:
        loop.pop()
    elif len(loop) > 2:
        raise RuntimeError("cut-face loop does not close")
    return loop


def _area(loop):
    return 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(loop, loop[1:] + loop[:1]))


def load_brep(path):
    s = Part.Shape()
    s.read(str(path))
    return s
