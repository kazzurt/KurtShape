"""Concept mockups for the Fable deep review (labelled concepts, not screenshots).

Draws with the bundled runtime's Qt offscreen, using the real KurtShape SVG icon set
and Segoe UI, and writes PNG (2x) plus editable SVG for each concept.
"""
import math
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtSvg  # noqa: E402

ROOT = Path(__file__).resolve().parents[4]
ICONS = ROOT / "resources" / "icons"
OUT = ROOT / "docs" / "fable-deep-review" / "visual-proposals" / "concepts"

C = dict(workspace="#f5f6f7", surface="#ffffff", viewport="#ffffff", chrome="#f5f6f7",
         alternate="#fafafa", ink="#2d3338", muted="#59636c", placeholder="#65717c",
         disabled="#f1f3f5", disabled_ink="#646f78", divider="#d6dadf", border="#8a949e",
         hover="#edf2f6", selection="#e6f1fa", selection_ink="#204f79", accent="#185fa5",
         accent_pressed="#124b83", error="#bd3039", warning="#8c6005", success="#247a43",
         tooltip="#353a40", icon_ink="#51575d", icon_mid="#b8bdc2",
         preselect="#cfe6f7", select="#9dc6ec")

W, H = 1600, 1000
_svg_cache = {}


def col(c, alpha=None):
    q = QtGui.QColor(c)
    if alpha is not None:
        q.setAlphaF(alpha)
    return q


class Canvas:
    def __init__(self, painter):
        self.p = painter

    def font(self, size=13, weight=400, italic=False):
        f = QtGui.QFont("Segoe UI")
        f.setPixelSize(size)
        f.setWeight({400: QtGui.QFont.Weight.Normal, 600: QtGui.QFont.Weight.DemiBold,
                     700: QtGui.QFont.Weight.Bold}.get(weight, QtGui.QFont.Weight.Normal))
        f.setItalic(italic)
        return f

    def rect(self, x, y, w, h, fill=None, stroke=None, r=0, sw=1):
        self.p.setPen(QtGui.QPen(col(stroke), sw) if stroke else QtCore.Qt.PenStyle.NoPen)
        self.p.setBrush(QtGui.QBrush(col(fill)) if fill else QtCore.Qt.BrushStyle.NoBrush)
        if r:
            self.p.drawRoundedRect(QtCore.QRectF(x, y, w, h), r, r)
        else:
            self.p.drawRect(QtCore.QRectF(x, y, w, h))

    def line(self, x1, y1, x2, y2, color=C["divider"], sw=1, dash=False):
        pen = QtGui.QPen(col(color), sw)
        if dash:
            pen.setStyle(QtCore.Qt.PenStyle.DashLine)
        self.p.setPen(pen)
        self.p.drawLine(QtCore.QPointF(x1, y1), QtCore.QPointF(x2, y2))

    def text(self, x, y, s, size=13, weight=400, color=C["ink"], align="left", w=None, h=None, italic=False):
        self.p.setFont(self.font(size, weight, italic))
        self.p.setPen(QtGui.QPen(col(color)))
        flags = {"left": QtCore.Qt.AlignmentFlag.AlignLeft, "center": QtCore.Qt.AlignmentFlag.AlignHCenter,
                 "right": QtCore.Qt.AlignmentFlag.AlignRight}[align] | QtCore.Qt.AlignmentFlag.AlignVCenter
        width = w if w is not None else 2000
        height = h if h is not None else size * 1.6
        rx = x if align == "left" else (x - width / 2 if align == "center" else x - width)
        self.p.drawText(QtCore.QRectF(rx, y, width, height), flags, s)

    def text_width(self, s, size=13, weight=400):
        return QtGui.QFontMetricsF(self.font(size, weight)).horizontalAdvance(s)

    def icon(self, name, x, y, size=20, tint=None, opacity=1.0):
        path = ICONS / (name + ".svg")
        if not path.is_file():
            self.rect(x, y, size, size, stroke=C["border"])
            return
        if name not in _svg_cache:
            _svg_cache[name] = QtSvg.QSvgRenderer(str(path))
        renderer = _svg_cache[name]
        if tint is None and opacity == 1.0:
            renderer.render(self.p, QtCore.QRectF(x, y, size, size))
            return
        scale = 4
        img = QtGui.QImage(size * scale, size * scale, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QtCore.Qt.GlobalColor.transparent)
        ip = QtGui.QPainter(img)
        ip.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        renderer.render(ip, QtCore.QRectF(0, 0, size * scale, size * scale))
        if tint is not None:
            ip.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceIn)
            ip.fillRect(img.rect(), col(tint))
        ip.end()
        self.p.setOpacity(opacity)
        self.p.drawImage(QtCore.QRectF(x, y, size, size), img)
        self.p.setOpacity(1.0)

    def circle(self, cx, cy, r, fill=None, stroke=None, sw=1):
        self.p.setPen(QtGui.QPen(col(stroke), sw) if stroke else QtCore.Qt.PenStyle.NoPen)
        self.p.setBrush(QtGui.QBrush(col(fill)) if fill else QtCore.Qt.BrushStyle.NoBrush)
        self.p.drawEllipse(QtCore.QPointF(cx, cy), r, r)

    def ellipse(self, cx, cy, rx, ry, fill=None, stroke=None, sw=1):
        self.p.setPen(QtGui.QPen(col(stroke), sw) if stroke else QtCore.Qt.PenStyle.NoPen)
        self.p.setBrush(QtGui.QBrush(col(fill)) if fill else QtCore.Qt.BrushStyle.NoBrush)
        self.p.drawEllipse(QtCore.QPointF(cx, cy), rx, ry)

    def poly(self, points, fill=None, stroke=None, sw=1, gradient=None):
        self.p.setPen(QtGui.QPen(col(stroke), sw) if stroke else QtCore.Qt.PenStyle.NoPen)
        if gradient is not None:
            self.p.setBrush(QtGui.QBrush(gradient))
        else:
            self.p.setBrush(QtGui.QBrush(col(fill)) if fill else QtCore.Qt.BrushStyle.NoBrush)
        self.p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(*pt) for pt in points]))

    def chevron(self, x, y, size=8, color=C["muted"]):
        self.line(x, y, x + size / 2, y + size / 2, color, 1.3)
        self.line(x + size / 2, y + size / 2, x + size, y, color, 1.3)

    def chip(self, x, y, label, fg, bg, size=12, icon=None, h=20):
        tw = self.text_width(label, size, 600)
        w = tw + 16 + (18 if icon else 0)
        self.rect(x, y, w, h, fill=bg, r=3)
        if icon:
            self.icon(icon, x + 6, y + (h - 14) / 2, 14, tint=fg)
        self.text(x + 8 + (18 if icon else 0), y, label, size, 600, fg, h=h)
        return w

    def callout(self, x, y, n, color=C["accent"], r=11):
        self.circle(x, y, r, fill=color, stroke="#ffffff", sw=1.5)
        self.text(x, y - r, str(n), 13, 700, "#ffffff", align="center", w=2 * r, h=2 * r)

    def button(self, x, y, w, h, label, primary=False, enabled=True, icon=None):
        if primary:
            self.rect(x, y, w, h, fill=C["accent"] if enabled else C["disabled"], r=2)
            fg = "#ffffff" if enabled else C["disabled_ink"]
        else:
            self.rect(x, y, w, h, fill=C["surface"], stroke=C["border"], r=2)
            fg = C["ink"] if enabled else C["disabled_ink"]
        tx = x + w / 2
        if icon:
            self.icon(icon, x + 8, y + (h - 14) / 2, 14, tint=fg)
            tx = x + w / 2 + 7
        self.text(tx, y, label, 13, 600 if primary else 400, fg, align="center", w=w, h=h)

    def field(self, x, y, w, h, value, placeholder=False, focus=False, invalid=False, unit=None):
        stroke = C["error"] if invalid else (C["accent"] if focus else C["border"])
        self.rect(x, y, w, h, fill=C["surface"], stroke=stroke, r=2, sw=1.5 if (focus or invalid) else 1)
        self.text(x + 7, y, value, 13, 400, C["placeholder"] if placeholder else C["ink"], h=h)
        if unit:
            self.text(x + w - 8, y, unit, 12, 400, C["muted"], align="right", w=60, h=h)


# ---------------------------------------------------------------- geometry helpers
def iso_projector(ox, oy, s):
    def iso(x, y, z):
        return (ox + (x - y) * 0.8660 * s, oy + (x + y) * 0.5 * s - z * s)
    return iso


def shade(base, k):
    q = QtGui.QColor(base)
    hsv = q.toHsv()
    v = max(0, min(255, int(hsv.value() * k)))
    return QtGui.QColor.fromHsv(hsv.hue(), hsv.saturation(), v).name()


def draw_model(c, iso, variant, base="#9aa3ac", edges=C["ink"], section=False, highlight_face=None,
               preview=None, edge_w=1.0):
    """A plate with a cylindrical boss and a through hole; optional preview volume."""
    W_, D_, H_ = 120, 80, 14
    tone = {"top": shade(base, 1.18), "left": shade(base, 0.95), "right": shade(base, 0.74)}
    if variant == "ambitious":
        tone = {"top": shade(base, 1.22), "left": shade(base, 1.0), "right": shade(base, 0.8)}
    # plate faces
    top = [iso(0, 0, H_), iso(W_, 0, H_), iso(W_, D_, H_), iso(0, D_, H_)]
    left = [iso(0, D_, 0), iso(W_, D_, 0), iso(W_, D_, H_), iso(0, D_, H_)]
    right = [iso(W_, 0, 0), iso(W_, D_, 0), iso(W_, D_, H_), iso(W_, 0, H_)]
    ew = edge_w
    if section:
        # cut the plate at y = D_/2: show hatched cut face
        Dc = D_ / 2
        top = [iso(0, 0, H_), iso(W_, 0, H_), iso(W_, Dc, H_), iso(0, Dc, H_)]
        left = [iso(0, Dc, 0), iso(W_, Dc, 0), iso(W_, Dc, H_), iso(0, Dc, H_)]
        right = [iso(W_, 0, 0), iso(W_, Dc, 0), iso(W_, Dc, H_), iso(W_, 0, H_)]
    c.poly(left, fill=tone["left"], stroke=edges, sw=ew)
    c.poly(right, fill=tone["right"], stroke=edges, sw=ew)
    c.poly(top, fill=tone["top"] if highlight_face != "top" else C["select"], stroke=edges, sw=ew)
    if section:
        # hatch the cut face
        c.poly(left, fill="#e9d8c5", stroke=edges, sw=ew)
        x0, y0 = iso(0, D_ / 2, 0)
        for i in range(0, 130, 6):
            a = iso(i, D_ / 2, 0)
            b = iso(i + 14, D_ / 2, H_)
            c.line(a[0], a[1], b[0], b[1], "#9a7b5a", 0.8)
    # boss (cylinder) on top
    cx, cy, r, h = 80, 40 if not section else 40, 22, 22
    hole_r = 11
    steps = 48
    ring_top = [iso(cx + r * math.cos(t), cy + r * math.sin(t), H_ + h) for t in
                (2 * math.pi * i / steps for i in range(steps))]
    ring_bot = [iso(cx + r * math.cos(t), cy + r * math.sin(t), H_) for t in
                (2 * math.pi * i / steps for i in range(steps))]
    # visible side: normal·(1,1) > 0  -> t in (-45deg, 135deg)
    side_idx = [i for i in range(steps) if math.cos(2 * math.pi * i / steps) + math.sin(2 * math.pi * i / steps) > -0.02]
    side_idx.sort(key=lambda i: ((2 * math.pi * i / steps) + math.pi / 4) % (2 * math.pi))
    side = [ring_top[i] for i in side_idx] + [ring_bot[i] for i in reversed(side_idx)]
    xs = [pt[0] for pt in side]
    grad = QtGui.QLinearGradient(min(xs), 0, max(xs), 0)
    if variant == "ambitious":
        grad.setColorAt(0.0, col(shade(base, 0.92)))
        grad.setColorAt(0.45, col(shade(base, 1.12)))
        grad.setColorAt(1.0, col(shade(base, 0.68)))
    else:
        grad.setColorAt(0.0, col(shade(base, 0.9)))
        grad.setColorAt(0.5, col(shade(base, 1.0)))
        grad.setColorAt(1.0, col(shade(base, 0.74)))
    c.poly(side, gradient=grad, stroke=edges, sw=ew)
    c.poly(ring_top, fill=tone["top"], stroke=edges, sw=ew)
    # hole
    hole = [iso(cx + hole_r * math.cos(t), cy + hole_r * math.sin(t), H_ + h) for t in
            (2 * math.pi * i / steps for i in range(steps))]
    c.poly(hole, fill=shade(base, 0.55), stroke=edges, sw=ew)
    inner = [iso(cx + hole_r * math.cos(t), cy + hole_r * math.sin(t), H_ + h - 9) for t in
             (2 * math.pi * i / steps for i in range(steps))]
    back_idx = [i for i in range(steps) if math.cos(2 * math.pi * i / steps) + math.sin(2 * math.pi * i / steps) < 0.02]
    back_idx.sort(key=lambda i: ((2 * math.pi * i / steps) - 3 * math.pi / 4) % (2 * math.pi))
    wall = [hole[i] for i in back_idx] + [inner[i] for i in reversed(back_idx)]
    c.poly(wall, fill=shade(base, 0.7), stroke=None)
    c.poly(hole, fill=None, stroke=edges, sw=ew)
    if preview:
        # translucent preview block on the plate's right side
        px, py, pw, pd, ph = 10, 10, 30, 20, 30
        t = [iso(px, py, H_ + ph), iso(px + pw, py, H_ + ph), iso(px + pw, py + pd, H_ + ph), iso(px, py + pd, H_ + ph)]
        l = [iso(px, py + pd, H_), iso(px + pw, py + pd, H_), iso(px + pw, py + pd, H_ + ph), iso(px, py + pd, H_ + ph)]
        rr = [iso(px + pw, py, H_), iso(px + pw, py + pd, H_), iso(px + pw, py + pd, H_ + ph), iso(px + pw, py, H_ + ph)]
        fill = {"pending": "#b9d7f0", "valid": "#9fcfe9", "error": "#f1c4c7"}[preview]
        stroke = {"pending": "#5a8fbf", "valid": C["accent"], "error": C["error"]}[preview]
        c.p.setOpacity(0.55)
        c.poly(l, fill=fill, stroke=stroke, sw=1)
        c.poly(rr, fill=shade(fill, 0.9), stroke=stroke, sw=1)
        c.poly(t, fill=shade(fill, 1.05), stroke=stroke, sw=1)
        c.p.setOpacity(1.0)
        if preview == "pending":
            c.p.setOpacity(0.9)
            pen = QtGui.QPen(col(stroke), 1)
            pen.setStyle(QtCore.Qt.PenStyle.DashLine)
            c.p.setPen(pen)
            c.p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            c.p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(*pt) for pt in t]))
            c.p.setOpacity(1.0)


def nav_cube(c, x, y, variant):
    if variant == "ambitious":
        # compact Onshape-like cube: 64px, light gray, labelled faces
        s = 58
        iso = iso_projector(x + s / 2, y + s / 2 - 4, 0.42)
        top = [iso(-30, -30, 30), iso(30, -30, 30), iso(30, 30, 30), iso(-30, 30, 30)]
        left = [iso(-30, 30, -30), iso(30, 30, -30), iso(30, 30, 30), iso(-30, 30, 30)]
        right = [iso(30, -30, -30), iso(30, 30, -30), iso(30, 30, 30), iso(30, -30, 30)]
        c.poly(left, fill="#eef0f2", stroke=C["border"], sw=0.8)
        c.poly(right, fill="#dfe3e7", stroke=C["border"], sw=0.8)
        c.poly(top, fill="#f8f9fa", stroke=C["border"], sw=0.8)
        c.text(x + s / 2, y + 4, "TOP", 9, 600, C["muted"], align="center", w=60, h=14)
        c.text(x + 4, y + 34, "FRONT", 7, 600, C["muted"], w=40, h=12)
        c.text(x + 34, y + 34, "RIGHT", 7, 600, C["muted"], w=40, h=12)
        c.text(x + s / 2, y + s + 2, "home", 9, 400, C["placeholder"], align="center", w=80, h=12)
    else:
        s = 92
        iso = iso_projector(x + s / 2, y + s / 2, 0.55)
        top = [iso(-30, -30, 30), iso(30, -30, 30), iso(30, 30, 30), iso(-30, 30, 30)]
        left = [iso(-30, 30, -30), iso(30, 30, -30), iso(30, 30, 30), iso(-30, 30, 30)]
        right = [iso(30, -30, -30), iso(30, 30, -30), iso(30, 30, 30), iso(30, -30, 30)]
        c.poly(left, fill="#f3f4f6", stroke=C["border"], sw=0.8)
        c.poly(right, fill="#e6e9ec", stroke=C["border"], sw=0.8)
        c.poly(top, fill="#fbfbfc", stroke=C["border"], sw=0.8)
        c.text(x + s / 2, y + 8, "TOP", 10, 600, C["muted"], align="center", w=60, h=14)
        c.text(x + 14, y + 50, "FRONT", 9, 600, C["muted"], w=40, h=12)
        c.text(x + 54, y + 50, "RIGHT", 9, 600, C["muted"], w=40, h=12)
        for (ax, ay, bx, by) in [(x - 6, y + s / 2, x - 14, y + s / 2), (x + s + 6, y + s / 2, x + s + 14, y + s / 2)]:
            c.line(ax, ay, bx, by, C["border"], 1.2)


def axes_triad(c, x, y):
    c.line(x, y, x + 22, y + 8, "#c0392b", 1.5)
    c.line(x, y, x - 14, y + 12, "#27ae60", 1.5)
    c.line(x, y, x, y - 24, "#2980b9", 1.5)
    c.text(x + 24, y + 2, "x", 9, 400, "#c0392b", h=12)
    c.text(x - 24, y + 8, "y", 9, 400, "#27ae60", h=12)
    c.text(x + 3, y - 32, "z", 9, 400, "#2980b9", h=12)


# ---------------------------------------------------------------- shell pieces
MODEL_TOOLS = [["undo", "redo"], ["new-part", "sketch", "extrude", "remove"], ["revolve", "sweep", "loft"],
               ["fillet", "chamfer", "shell", "draft", "move-face"], ["linear-pattern", "circular-pattern", "mirror"],
               ["boolean", "split", "transform", "plane"], ["more"], ["rebuild", "check-geometry", "fit", "normal", "isometric"]]
SKETCH_TOOLS = [["undo", "redo"], ["polyline", "rectangle", "circle", "arc", "spline", "point"], ["dimension", "trim", "construction"],
                ["geometry-menu", "constraints-menu", "edit-menu", "pierce"], ["normal", "isometric"], ["confirm", "cancel"]]


def document_row(c, title, saved, variant, mode="Part Studio", build=None):
    c.rect(0, 0, W, 44, fill=C["chrome"])
    c.line(0, 44, W, 44)
    c.text(14, 0, "KurtShape", 16, 600, C["ink"], h=44)
    c.icon("document-menu", 112, 12, 20)
    x = 148
    c.text(x, 0, title, 14, 600, C["ink"], h=44)
    x += c.text_width(title, 14, 600) + 10
    if variant == "restrained":
        c.text(x, 0, "·  " + ("Saved" if saved else "Unsaved changes"), 13, 400, C["muted"] if saved else C["warning"], h=44)
    else:
        c.chip(x, 12, "Saved" if saved else "Unsaved", C["muted"] if saved else "#7a4f00", C["disabled"] if saved else "#fff1cc", 11, h=20)
        x += 86
        if build:
            label, color, bg, icon = build
            c.chip(x, 12, label, color, bg, 11, icon=icon, h=20)
    # right cluster
    c.rect(W - 260, 8, 110, 28, fill=C["surface"], stroke=C["border"], r=2)
    c.text(W - 252, 8, mode, 13, 400, C["ink"], h=28)
    c.chevron(W - 170, 19)
    c.icon("save", W - 128, 12, 20, opacity=0.5 if saved else 1.0)
    c.icon("shortcuts", W - 92, 12, 20)
    c.icon("settings", W - 56, 12, 20)


def toolbar(c, groups, y, variant, active=None, labels=None):
    c.rect(0, y, W, 40, fill=C["chrome"])
    c.line(0, y + 40, W, y + 40)
    x = 14
    size = 20 if variant == "restrained" else 22
    pitch = 34 if variant == "restrained" else 36
    for gi, group in enumerate(groups):
        for name in group:
            if name == active:
                c.rect(x - 7, y + 6, size + 14, 28, fill=C["selection"], r=2)
                c.icon(name, x, y + 10, size, tint=C["accent"])
            else:
                c.icon(name, x, y + 10, size)
            x += pitch
        if gi < len(groups) - 1:
            if variant == "ambitious" and labels:
                c.line(x - 8, y + 9, x - 8, y + 31, C["divider"], 1)
            else:
                c.line(x - 7, y + 11, x - 7, y + 29, C["divider"], 1)
            x += 10
    # search
    sx = x + 14
    c.rect(sx, y + 7, 190, 26, fill=C["surface"], stroke=C["border"], r=2)
    c.icon("search", sx + 6, y + 13, 14, tint=C["muted"])
    c.text(sx + 26, y + 7, "Search tools…  Alt+C", 12, 400, C["placeholder"], h=26)
    return x


def left_dock(c, y0, variant, features, active_part="Plate", parts=("Plate",), rollback_after=None, held=(), sketch=False):
    x0, w = 0, 250
    c.rect(x0, y0, w, H - y0 - 36, fill=C["workspace"])
    c.line(w, y0, w, H - 36)
    c.text(10, y0 + 4, "Feature history", 13, 600, C["ink"], h=24)
    c.rect(8, y0 + 32, w - 16, 26, fill=C["surface"], stroke=C["border"], r=2)
    c.text(16, y0 + 32, "Filter features", 12, 400, C["placeholder"], h=26)
    c.text(10, y0 + 64, f"Features ({len(features)})", 12, 600, C["muted"], h=20)
    y = y0 + 88
    # origin planes collapsed row
    c.text(12, y, "▸", 11, 400, C["muted"], h=22)
    c.icon("plane", 26, y + 3, 16)
    c.text(48, y, "Origin  ·  Top · Front · Right", 13, 400, C["ink"], h=22)
    y += 26
    for i, (icon, name, state) in enumerate(features):
        is_held = name in held
        if state == "selected":
            c.rect(0, y, w, 24, fill=C["selection"])
        if state == "editing":
            c.rect(0, y, w, 24, fill=C["selection"])
            c.rect(0, y, 3, 24, fill=C["accent"])
        tint = None
        if variant == "restrained":
            tint = C["disabled_ink"] if is_held else None
        else:
            tint = C["accent"] if icon == "sketch" and not is_held else (C["disabled_ink"] if is_held else None)
        c.icon(icon, 26, y + 4, 16, tint=tint, opacity=0.6 if is_held else 1.0)
        color = C["disabled_ink"] if is_held else (C["error"] if state == "failed" else C["ink"])
        c.text(48, y, name, 13, 400, color, h=24, italic=is_held)
        if state == "failed":
            c.icon("cancel", w - 44, y + 4, 16, tint=C["error"])
        if state == "hidden":
            c.text(w - 40, y, "hidden", 10, 400, C["placeholder"], h=24)
        if variant == "ambitious" and state == "editing":
            c.text(w - 60, y, "editing", 10, 600, C["accent"], h=24)
        y += 24
        if rollback_after == name:
            # rollback handle
            c.line(8, y + 5, w - 8, y + 5, C["accent"], 2)
            c.rect(8, y, 14, 10, fill=C["accent"], r=2)
            c.text(28, y + 8, "Rolled back here · drag to move", 10, 400, C["accent"], h=14)
            y += 22
    if rollback_after is None:
        c.line(8, y + 5, w - 8, y + 5, C["accent"], 2)
        c.rect(8, y, 14, 10, fill=C["accent"], r=2)
        c.text(28, y + 8, "End of history · drag to roll back", 10, 400, C["accent"], h=14)
        y += 22
    # Parts
    py = H - 36 - 150
    c.line(8, py - 8, w - 8, py - 8)
    c.text(10, py - 4, f"Parts ({len(parts)})", 12, 600, C["muted"], h=20)
    yy = py + 20
    for name in parts:
        active = name == active_part
        if variant == "restrained":
            c.rect(0, yy, w, 24, fill=C["surface"] if active else None)
            c.rect(10, yy + 6, 12, 12, fill=C["surface"], stroke=C["border"], r=2)
            c.icon("confirm", 11, yy + 7, 10, tint=C["ink"])
            c.icon("new-part", 30, yy + 4, 16)
            c.text(52, yy, name, 13, 700 if active else 400, C["ink"], h=24)
            if active:
                c.text(w - 10 - c.text_width("Active", 10, 600) - 12, yy, "Active", 10, 600, C["accent"], h=24)
        else:
            c.rect(6, yy, w - 12, 26, fill=C["surface"], stroke=C["accent"] if active else C["divider"], r=3)
            c.rect(14, yy + 7, 12, 12, fill="#7f93a8" if name == "Plate" else "#c9a560", r=2)
            c.text(34, yy, name, 13, 700 if active else 400, C["ink"], h=26)
            if active:
                c.chip(w - 68, yy + 4, "Active", "#ffffff", C["accent"], 10, h=18)
        yy += 28
    if variant == "restrained":
        c.text(10, yy + 2, "Bold = target for new features · right-click to change", 10, 400, C["placeholder"], h=14)
    else:
        c.text(10, yy + 2, "Click a part to select · right-click to make it the target", 10, 400, C["placeholder"], h=14)


def tabs_and_status(c, variant, tabs, status_left, status_mid, messages=0, busy=None):
    y = H - 36
    c.rect(0, y - 30, W, 30, fill=C["chrome"])
    c.line(0, y - 30, W, y - 30)
    x = 258
    for name, active, modified in tabs:
        tw = c.text_width(name, 13, 600 if active else 400) + 46
        if active:
            c.rect(x, y - 30, tw, 30, fill=C["surface"])
            c.rect(x, y - 30, tw, 2, fill=C["accent"])
        c.icon("new-document", x + 8, y - 22, 14, tint=C["muted"])
        c.text(x + 26, y - 30, name + ("  •" if modified else ""), 13, 600 if active else 400, C["ink"] if active else C["muted"], h=30)
        x += tw + 4
    c.rect(0, y, W, 36, fill=C["chrome"])
    c.line(0, y, W, y)
    # left: build / status zone
    x = 10
    for label, color, bg, icon in status_left:
        x += c.chip(x, y + 8, label, color, bg, 11, icon=icon, h=20) + 6
    # middle: view context
    c.text(W / 2, y, status_mid, 12, 400, C["muted"], align="center", w=600, h=36)
    # right: busy + messages
    rx = W - 14
    label = f"Messages ({messages})" if messages else "Messages"
    tw = c.text_width(label, 12, 600)
    c.text(rx - tw, y, label, 12, 600, C["accent"] if messages else C["muted"], h=36)
    if messages:
        c.circle(rx - tw - 10, y + 18, 4, fill=C["error"])
    if busy:
        bx = rx - tw - 330
        c.rect(bx, y + 14, 100, 6, fill=C["disabled"], r=3)
        c.rect(bx, y + 14, 42, 6, fill=C["accent"], r=3)
        c.text(bx + 108, y, busy, 11, 400, C["muted"], h=36)


def editor_panel(c, x, y, w, title, rows, verdict, state, variant, h=None, step=None):
    """A FeaturePanel-style floating editor. rows: list of (label, kind, value, opts)."""
    extra = 0
    for _, kind, _, opts in rows:
        if kind == "picker":
            extra += 24 * len(opts.get("refs", [])) + (4 if opts.get("refs") else 0)
        if kind == "field" and opts.get("hint"):
            extra += 14
    fm = QtGui.QFontMetricsF(c.font(11))
    wrapped = []
    source = verdict if isinstance(verdict, list) else [verdict]
    for i, line in enumerate(source):
        words, cur = line.split(), ""
        for wd in words:
            trial = (cur + " " + wd).strip()
            if fm.horizontalAdvance(trial) <= w - 50 or not cur:
                cur = trial
            else:
                wrapped.append(cur)
                cur = wd
        if cur:
            wrapped.append(cur)
    strip_h = 12 + 16 * len(wrapped)
    h = h or (44 + 34 * len(rows) + extra + 8 + strip_h)
    c.rect(x, y, w, h, fill=C["surface"], stroke=C["border"], r=3)
    c.rect(x, y, w, 34, fill=C["chrome"], r=3)
    c.rect(x, y + 20, w, 14, fill=C["chrome"])
    c.line(x, y + 34, x + w, y + 34)
    if variant == "ambitious" and step:
        c.text(x + 10, y, step, 10, 600, C["muted"], h=34)
        c.text(x + 10 + c.text_width(step, 10, 600) + 8, y, title, 14, 600, C["ink"], h=34)
    else:
        c.text(x + 10, y, title, 14, 600, C["ink"], h=34)
    ok = state == "valid"
    if variant == "restrained":
        c.rect(x + w - 66, y + 4, 28, 26, fill=C["selection"] if ok else None, r=2)
        c.icon("confirm", x + w - 62, y + 7, 20, tint=C["accent"] if ok else C["icon_mid"])
        c.icon("cancel", x + w - 30, y + 7, 20)
    else:
        c.button(x + w - 158, y + 5, 78, 24, "Confirm", primary=True, enabled=ok)
        c.button(x + w - 74, y + 5, 64, 24, "Cancel")
    yy = y + 44
    for label, kind, value, opts in rows:
        c.text(x + 10, yy, label, 13, 400, C["muted"], h=26, w=90)
        fx = x + 100
        fw = w - 110
        if kind == "field":
            c.field(fx, yy, fw, 26, value, focus=opts.get("focus"), invalid=opts.get("invalid"), unit=opts.get("unit"))
            if opts.get("hint"):
                c.text(fx, yy + 26, opts["hint"], 10, 400, C["error"] if opts.get("invalid") else C["placeholder"], h=14)
                yy += 14
        elif kind == "combo":
            c.rect(fx, yy, fw, 26, fill=C["surface"], stroke=C["border"], r=2)
            c.text(fx + 7, yy, value, 13, 400, C["ink"], h=26)
            c.chevron(fx + fw - 18, yy + 10)
        elif kind == "picker":
            active = opts.get("active")
            invalid = opts.get("invalid")
            c.rect(fx, yy, fw, 26, fill=C["selection"] if active else C["surface"],
                   stroke=C["error"] if invalid else (C["accent"] if active else C["border"]), r=2, sw=1.5 if (active or invalid) else 1)
            c.text(fx + 7, yy, value, 13, 400, C["selection_ink"] if active else C["ink"], h=26)
            for i, ref in enumerate(opts.get("refs", [])):
                ry = yy + 28 + i * 24
                c.rect(fx, ry, fw, 22, fill=C["alternate"], stroke=C["divider"], r=2)
                c.text(fx + 7, ry, ref, 12, 400, C["ink"] if not opts.get("missing") == ref else C["error"], h=22)
                c.icon("cancel", fx + fw - 20, ry + 4, 14, tint=C["muted"])
                if opts.get("missing") == ref:
                    c.text(fx + fw - 90, ry, "missing", 10, 600, C["error"], h=22)
            yy += 24 * len(opts.get("refs", [])) + (4 if opts.get("refs") else 0)
        elif kind == "check":
            c.rect(fx, yy + 6, 14, 14, fill=C["surface"], stroke=C["border"], r=2)
            if value:
                c.icon("confirm", fx + 1, yy + 7, 12, tint=C["ink"])
            c.text(fx + 20, yy, opts.get("text", ""), 13, 400, C["ink"], h=26)
        elif kind == "segment":
            segs = opts["options"]
            sw_ = fw / len(segs)
            for i, s in enumerate(segs):
                on = s == value
                c.rect(fx + i * sw_, yy, sw_, 26, fill=C["selection"] if on else C["surface"], stroke=C["accent"] if on else C["border"], r=2)
                c.text(fx + i * sw_ + sw_ / 2, yy, s, 12, 600 if on else 400, C["selection_ink"] if on else C["ink"], align="center", w=sw_, h=26)
        yy += 34
    # verdict
    vy = y + h - strip_h
    c.line(x, vy - 2, x + w, vy - 2)
    color = {"pending": C["muted"], "valid": C["success"], "error": C["error"]}[state]
    bg = {"pending": C["alternate"], "valid": "#eaf5ee", "error": "#fbecec"}[state]
    c.rect(x + 1, vy, w - 2, strip_h - 1, fill=bg)
    c.rect(x + 1, vy, 4, strip_h - 1, fill=color)
    icon = {"pending": None, "valid": "confirm", "error": "cancel"}[state]
    if state == "pending":
        # spinner
        c.p.setPen(QtGui.QPen(col(C["accent"]), 2))
        c.p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        c.p.drawArc(QtCore.QRectF(x + 14, vy + 10, 16, 16), 30 * 16, 270 * 16)
    else:
        c.icon(icon, x + 12, vy + 8, 18, tint=color)
    for i, line in enumerate(wrapped):
        first = i == 0
        c.text(x + 38, vy + 6 + i * 16, line, 12 if first else 11, 600 if first else 400, color if first else C["ink"], h=16, w=w - 42)
    return h


def native_tasks(c, x, y, w, h, variant, dof_text):
    c.rect(x, y, w, h, fill=C["workspace"])
    c.line(x, y, x, y + h)
    c.text(x + w / 2, y + 4, "Tasks", 13, 400, C["ink"], align="center", w=w, h=24)
    c.button(x + w / 2 - 30, y + 32, 60, 26, "Close")
    c.icon("sketch", x + 12, y + 74, 16)
    c.text(x + 34, y + 70, "Sketch Edit", 13, 700, C["ink"], h=24)
    c.line(x + 10, y + 94, x + w - 10, y + 94)
    c.text(x + 12, y + 100, dof_text, 13, 400, C["ink"], h=26, w=w - 100)
    c.icon("rebuild", x + w - 72, y + 104, 18)
    c.icon("tools", x + w - 46, y + 104, 18)
    c.text(x + 12, y + 146, "Constraints", 13, 700, C["ink"], h=24)
    c.line(x + 10, y + 170, x + w - 10, y + 170)
    for i, n in enumerate(["Constraint1", "Constraint2", "Constraint3", "Constraint4"]):
        c.rect(x + 14, y + 182 + i * 24, 12, 12, fill=C["surface"], stroke=C["border"])
        c.text(x + 34, y + 176 + i * 24, n, 12, 400, C["ink"], h=24)
    c.text(x + 12, y + 300, "Elements", 13, 700, C["ink"], h=24)
    c.line(x + 10, y + 324, x + w - 10, y + 324)
    for i, n in enumerate(["1-Line", "2-Line", "3-Line", "4-Line", "5-Circle"]):
        c.rect(x + 14, y + 336 + i * 24, 12, 12, fill=C["surface"], stroke=C["border"])
        c.text(x + 34, y + 330 + i * 24, n, 12, 400, C["ink"], h=24)


# ---------------------------------------------------------------- scenes
def scene_workspace(c, variant):
    legend = []
    build = ("Build valid", C["success"], "#eaf5ee", "confirm") if variant == "ambitious" else None
    document_row(c, "Bracket plate", False, variant, build=build)
    toolbar(c, MODEL_TOOLS, 44, variant, labels=True)
    features = [("sketch", "Plate profile", ""), ("extrude", "Plate", ""), ("sketch", "Boss profile", ""),
                ("extrude", "Boss", "selected"), ("sketch", "Hole profile", ""), ("remove", "Through hole", ""),
                ("fillet", "Edge round", "")]
    left_dock(c, 84, variant, features, parts=("Plate", "Lid") if variant == "ambitious" else ("Plate",))
    # viewport
    vx, vy, vw, vh = 251, 85, W - 251, H - 36 - 30 - 85
    c.rect(vx, vy, vw, vh, fill=C["viewport"])
    iso = iso_projector(vx + vw * 0.48, vy + vh * 0.46, 3.0)
    if variant == "ambitious":
        draw_model(c, iso, variant, base="#8fa3b8", edges="#3d4650", edge_w=1.0, highlight_face=None)
    else:
        draw_model(c, iso, variant, base="#9aa3ac", edges=C["ink"], edge_w=1.0)
    axes_triad(c, vx + 40, vy + vh - 40)
    nav_cube(c, W - 130, vy + 12, variant)
    if variant == "ambitious":
        # right view rail
        rx = W - 44
        c.rect(rx, vy + 120, 34, 230, fill=C["surface"], stroke=C["divider"], r=3)
        for i, name in enumerate(["fit", "isometric", "normal", "split", "measure", "check-geometry"]):
            c.icon(name, rx + 7, vy + 128 + i * 36, 20, tint=C["accent"] if name == "split" else None)
        c.text(rx - 150, vy + 362, "Section · Display · Quality", 10, 400, C["placeholder"], w=180, h=14, align="right")
        # quality preset popover
        c.rect(rx - 176, vy + 310, 170, 46, fill=C["surface"], stroke=C["border"], r=3)
        for i, (name, on) in enumerate([("Draft", False), ("Standard", True), ("Present", False)]):
            sx = rx - 172 + i * 56
            c.rect(sx, vy + 316, 52, 20, fill=C["selection"] if on else C["surface"], stroke=C["accent"] if on else C["divider"], r=2)
            c.text(sx + 26, vy + 316, name, 10, 600 if on else 400, C["selection_ink"] if on else C["ink"], align="center", w=52, h=20)
        c.text(rx - 172, vy + 338, "MSAA 4x · 0.2 % / 12° tessellation · edges 3 px", 9, 400, C["placeholder"], w=170, h=14)
        # selection feedback chip near model
        c.chip(vx + 20, vy + 14, "Boss · Face3 (cylinder r 22)", C["selection_ink"], C["selection"], 11, h=22)
    else:
        c.text(vx + 14, vy + 10, "Boss · selected feature", 11, 400, C["muted"], h=20)
    tabs = [("Bracket plate", True, True), ("Lid", False, False)]
    status_left = [("1 solid · 42,118 mm³", C["muted"], C["disabled"], None),
                   ("Build valid", C["success"], "#eaf5ee", "confirm"),
                   ("Unsaved", "#7a4f00", "#fff1cc", None)]
    if variant == "ambitious":
        status_left = [("1 solid · 42,118 mm³", C["muted"], C["disabled"], None), ("Checked", C["success"], "#eaf5ee", "check-geometry")]
    tabs_and_status(c, variant, tabs, status_left, "mm  ·  view 57.2 × 36.9 mm  ·  SolidWorks navigation",
                    messages=0, busy="Checking geometry…" if variant == "ambitious" else None)
    # callouts
    if variant == "restrained":
        c.callout(226, 62, 1); legend.append("Toolbar families separated by thin dividers and a consistent 34 px pitch; the same 20 px grayscale SVG language everywhere (no native fallback glyphs in persistent rows).")
        c.callout(230, 200, 2); legend.append("History icons use the grayscale set with state carried by text/row (italic + muted when rolled back, red cross when failed), not by native colored glyphs.")
        c.callout(230, 300, 3); legend.append("Rollback line gets a 14 px handle and a label that says what it does; dragging stays the only way to roll back.")
        c.callout(230, 836, 4); legend.append("Parts: one list, no duplicate chooser; the active target is bold with an 'Active' tag and a one-line explanation.")
        c.callout(1200, 985, 5); legend.append("Status bar zones: left = model truth (solid count, build state, unsaved), centre = view context, right = Messages. No transient completion text here.")
        c.callout(W - 150, 190, 6); legend.append("NaviCube drawn lighter and without rotation arrows (native NaviCube settings: size, colors, arrows off).")
        c.callout(640, 940, 7); legend.append("Document tabs show a modified dot, not the native ' : 1*' suffix; the close glyph is neutral gray.")
        c.callout(1060, 620, 8); legend.append("Viewport: unchanged renderer; MSAA 4x and the 12-degree angular deflection preset (Mod/Part MeshAngularDeflection) smooth silhouettes and fillets; edges stay black 1 px; the preview ghost tessellates with the same rule as the model.")
    else:
        c.callout(226, 62, 1); legend.append("22 px icons at a 36 px pitch in one lighter-stroke family; the active context family (here Modify) is tinted blue when a tool is armed.")
        c.callout(330, 20, 2); legend.append("Document row carries Saved/Unsaved and Build state chips beside the name, so model truth is readable without reading the status bar.")
        c.callout(230, 836, 3); legend.append("Parts as cards with color swatches (per-part appearance) and an explicit Active chip; selecting a part never changes the target.")
        c.callout(W - 60, 300, 4); legend.append("Right view rail: fit, iso, normal, section, measure, check; a Quality preset popover (Draft/Standard/Present) with its real parameter summary.")
        c.callout(1200, 985, 5); legend.append("Background jobs (geometry check, STEP export) show a progress bar in the status bar; Messages shows an unread dot and count.")
        c.callout(W - 150, 180, 6); legend.append("Compact 58 px NaviCube with a home glyph; drawn in chrome grays so it recedes.")
        c.callout(1060, 620, 7); legend.append("Material response: cool-gray default ShapeAppearance with lower shininess (session-only satin preset), thinner dark-gray edges (DefaultShapeLineWidth per DPI) and MSAA 8x in Presentation: all native parameters; no lighting change is assumed.")
        c.callout(420, 108, 8); legend.append("Selection chip names what is selected (feature · element · geometry type) so picks are verifiable without reading the native tree.")
    return legend


def scene_sketch(c, variant):
    legend = []
    document_row(c, "Bracket plate", False, variant)
    toolbar(c, SKETCH_TOOLS, 44, variant, active="rectangle", labels=True)
    features = [("sketch", "Plate profile", ""), ("extrude", "Plate", ""), ("sketch", "Boss profile", "editing"),
                ("extrude", "Boss", ""), ("sketch", "Hole profile", ""), ("remove", "Through hole", "")]
    left_dock(c, 84, variant, features, held=("Boss", "Hole profile", "Through hole") if variant == "restrained" else ("Boss", "Hole profile", "Through hole"))
    vx, vy, vw, vh = 251, 85, W - 251, H - 36 - 30 - 85
    if variant == "restrained":
        tasks_w = 0
    else:
        tasks_w = 0
    c.rect(vx, vy, vw - tasks_w, vh, fill=C["viewport"])
    # sketch plane view (normal): plate top face outline faint, profile rectangle + circle
    ox, oy = vx + (vw - tasks_w) / 2 - 40, vy + vh / 2 + 10
    s = 3.2
    # plate outline (existing geometry, gray)
    c.rect(ox - 60 * s, oy - 40 * s, 120 * s, 80 * s, fill="#f7f8f9", stroke="#b8bdc2", r=0)
    # origin axes
    c.line(ox - 70 * s, oy, ox + 70 * s, oy, "#d9534f", 1)
    c.line(ox, oy - 50 * s, ox, oy + 50 * s, "#5cb85c", 1)
    # profile: rectangle 40x30 at (-20,-15) (fixed, black) and circle r 22 (free, blue)
    rx, ry, rw, rh = ox - 20 * s, oy - 15 * s, 40 * s, 30 * s
    c.rect(rx, ry, rw, rh, fill="#ebebeb")
    c.rect(rx, ry, rw, rh, stroke=C["ink"], sw=1.6)
    for (px, py) in [(rx, ry), (rx + rw, ry), (rx, ry + rh), (rx + rw, ry + rh)]:
        c.circle(px, py, 3, fill=C["ink"])
    ccx, ccy = ox + 32 * s, oy - 2 * s
    c.circle(ccx, ccy, 14 * s, fill="#ebebeb")
    c.circle(ccx, ccy, 14 * s, stroke=C["accent"], sw=1.6)
    c.circle(ccx, ccy, 3, fill=C["accent"])
    # dimensions upright
    c.line(rx, ry - 26, rx + rw, ry - 26, C["ink"], 1)
    c.line(rx, ry - 32, rx, ry - 8, C["ink"], 1)
    c.line(rx + rw, ry - 32, rx + rw, ry - 8, C["ink"], 1)
    c.rect(rx + rw / 2 - 28, ry - 36, 56, 18, fill=C["surface"])
    c.text(rx + rw / 2, ry - 36, "40 mm", 12, 400, C["ink"], align="center", w=60, h=18)
    c.line(rx - 36, ry, rx - 36, ry + rh, C["ink"], 1)
    c.rect(rx - 86, ry + rh / 2 - 9, 50, 18, fill=C["surface"])
    c.text(rx - 61, ry + rh / 2 - 9, "30 mm", 12, 400, C["ink"], align="center", w=50, h=18)
    # constraint glyphs (ambitious shows them; restrained keeps native style)
    if variant == "ambitious":
        for (gx, gy, g) in [(rx + rw / 2, ry - 6, "—"), (rx + rw / 2, ry + rh + 2, "—"), (rx - 10, ry + rh / 2, "|"), (rx + rw + 4, ry + rh / 2, "|")]:
            c.rect(gx - 7, gy - 7, 14, 14, fill="#eef5fb", stroke="#9dc6ec", r=2)
            c.text(gx - 7, gy - 7, g, 10, 700, C["selection_ink"], align="center", w=14, h=14)
        # inline dimension input at the circle
        c.rect(ccx + 14 * s + 10, ccy - 14, 92, 28, fill=C["surface"], stroke=C["accent"], r=3, sw=1.5)
        c.text(ccx + 14 * s + 18, ccy - 14, "Ø 28", 13, 600, C["ink"], h=28)
        c.text(ccx + 14 * s + 60, ccy - 14, "mm · Enter", 11, 400, C["muted"], h=28)
        c.text(ccx + 14 * s + 10, ccy + 16, "Type a value or expression · Tab for next", 10, 400, C["placeholder"], h=14)
        # cursor hint
        c.text(ccx - 60, ccy + 14 * s + 10, "Snap: circle center to plate edge midpoint", 10, 400, C["accent"], h=14)
    # KurtShape sketch box
    bx, by, bw = vx + 14, vy + 14, 300
    if variant == "restrained":
        bh = 184
        c.rect(bx, by, bw, bh, fill=C["surface"], stroke=C["border"], r=3)
        c.rect(bx, by, bw, 34, fill=C["chrome"], r=3)
        c.rect(bx, by + 20, bw, 14, fill=C["chrome"])
        c.line(bx, by + 34, bx + bw, by + 34)
        c.icon("sketch", bx + 10, by + 7, 20)
        c.text(bx + 36, by, "Boss profile", 14, 600, C["ink"], h=34)
        c.rect(bx + bw - 66, by + 4, 28, 26, fill=C["selection"], r=2)
        c.icon("confirm", bx + bw - 62, by + 7, 20, tint=C["accent"])
        c.icon("cancel", bx + bw - 30, by + 7, 20)
        c.text(bx + 10, by + 42, "On", 12, 400, C["muted"], h=26, w=40)
        c.rect(bx + 50, by + 42, bw - 60, 26, fill=C["surface"], stroke=C["border"], r=2)
        c.text(bx + 57, by + 42, "Plate · Face6 (top)", 12, 400, C["ink"], h=26)
        c.icon("cancel", bx + bw - 30, by + 48, 14, tint=C["muted"])
        # solver line (full text, never truncated; wraps)
        c.rect(bx + 1, by + 76, bw - 2, 40, fill="#fff7e0")
        c.rect(bx + 1, by + 76, 4, 40, fill=C["warning"])
        c.text(bx + 14, by + 78, "Under-constrained · 2 degrees of freedom", 12, 600, C["warning"], h=18)
        c.text(bx + 14, by + 96, "Circle radius and its position along X are free", 11, 400, C["ink"], h=16, w=bw - 24)
        c.text(bx + 10, by + 122, "Constraints  12 · dimensions 4 · conflicts 0", 11, 400, C["muted"], h=18)
        c.text(bx + 10, by + 140, "Native panel ›", 11, 600, C["accent"], h=18)
        c.text(bx + 120, by + 140, "Finish Enter · Cancel Esc · N normal · Shift+7 iso", 10, 400, C["placeholder"], h=18)
        c.text(bx + 10, by + 160, "Later features are hidden while you edit this sketch", 10, 400, C["placeholder"], h=16)
    else:
        bh = 150
        c.rect(bx, by, bw, bh, fill=C["surface"], stroke=C["border"], r=3)
        c.rect(bx, by, bw, 34, fill=C["chrome"], r=3)
        c.rect(bx, by + 20, bw, 14, fill=C["chrome"])
        c.line(bx, by + 34, bx + bw, by + 34)
        c.icon("sketch", bx + 10, by + 7, 20, tint=C["accent"])
        c.text(bx + 36, by, "Boss profile", 14, 600, C["ink"], h=34)
        c.button(bx + bw - 150, by + 5, 72, 24, "Finish", primary=True)
        c.button(bx + bw - 72, by + 5, 62, 24, "Cancel")
        c.text(bx + 10, by + 40, "On", 12, 400, C["muted"], h=24, w=40)
        c.chip(bx + 40, by + 42, "Plate · Face6 (top)", C["selection_ink"], C["selection"], 11, icon="plane", h=20)
        c.text(bx + 10, by + 70, "Shows", 12, 400, C["muted"], h=24, w=60)
        for i, (name, on) in enumerate([("Constraints", True), ("Dimensions", True), ("Construction", False), ("Later features", False)]):
            sx = bx + 58 + i * 59
            c.rect(sx, by + 73, 56, 18, fill=C["selection"] if on else C["surface"], stroke=C["accent"] if on else C["divider"], r=2)
            c.text(sx + 28, by + 73, name, 9, 600 if on else 400, C["selection_ink"] if on else C["muted"], align="center", w=56, h=18)
        c.text(bx + 10, by + 100, "Native Sketcher panel", 11, 600, C["accent"], h=18)
        c.text(bx + 150, by + 100, "· constraints list, elements, solver tools", 10, 400, C["placeholder"], h=18)
        c.text(bx + 10, by + 122, "Finish Enter · Cancel Esc · N normal · Shift+7 iso · D dimension", 10, 400, C["placeholder"], h=18)
        # DoF badge bottom-left of viewport
        c.rect(vx + 14, vy + vh - 44, 230, 30, fill="#fff7e0", stroke="#e8c76a", r=3)
        c.circle(vx + 28, vy + vh - 29, 5, fill=C["warning"])
        c.text(vx + 40, vy + vh - 44, "2 DoF free · drag blue geometry", 12, 600, "#7a4f00", h=30)
    axes_triad(c, vx + 40, vy + vh - 64 if variant == "ambitious" else vy + vh - 40)
    nav_cube(c, W - 130, vy + 12, variant)
    tabs = [("Bracket plate", True, True)]
    status_left = [("Editing sketch", C["selection_ink"], C["selection"], "sketch")]
    tabs_and_status(c, variant, tabs, status_left, "mm  ·  L line · G rectangle · C circle · D dimension · Esc ends tool", messages=0)
    if variant == "restrained":
        c.callout(bx + bw + 12, by + 10, 1); legend.append("One sketch box, one check/cross pair (the toolbar pair at the row end is the same actions): no Normal/Isometric buttons inside, no third native 'Close'.")
        c.callout(bx + bw + 12, by + 96, 2); legend.append("Solver verdict is a wrapped, colored status line with the DoF count and a plain-language cause; never elided (QLabel word-wrap + tooltip, fed from Sketcher's solver signals).")
        c.callout(bx + bw + 12, by + 140, 3); legend.append("Native Tasks panel hidden by default behind 'Native panel ▸'; constraints/elements counts summarised instead. Viewport gains ~30% width.")
        c.callout(rx + rw / 2 + 50, ry - 36, 4); legend.append("Dimension text drawn upright with a white halo (Sketcher 'dimension text rotation'/font settings; verify in the pinned build, see B findings).")
        c.callout(230, 300, 5); legend.append("Later features rolled back and shown muted/italic while editing an earlier sketch, with the box saying so.")
        c.callout(1200, 985, 6); legend.append("Status bar left chip says 'Editing sketch'; hints move to the centre zone and are elided with a tooltip, never truncated mid-word.")
    else:
        c.callout(bx + bw + 12, by + 10, 1); legend.append("Sketch box with text Finish/Cancel buttons, support chip, and 'Shows' toggles for constraints, dimensions, construction and later features.")
        c.callout(ccx + 14 * s + 110, ccy - 10, 2); legend.append("Inline dimension entry at placement: a floating QLineEdit over the viewport (like the existing QuantityField) accepting expressions; Tab cycles the next free dimension.")
        c.callout(rx + rw / 2 + 50, ry - 36, 3); legend.append("Constraint glyph badges on geometry (horizontal, vertical, coincident), drawn as Coin SoAnnotation overlays from native constraint data; click to delete.")
        c.callout(vx + 260, vy + vh - 30, 4); legend.append("Persistent DoF badge at the viewport corner: amber while free, green when fully constrained, red on conflict.")
        c.callout(ccx - 70, ccy + 14 * s + 18, 5); legend.append("Snap narration: the current snap target is named near the cursor, which the existing snapping module already knows.")
        c.callout(230, 300, 6); legend.append("History shows an 'editing' tag on the active sketch row and mutes later rows.")
    return legend


def scene_editor_states(c, variant):
    legend = []
    c.rect(0, 0, W, H, fill=C["viewport"])
    c.text(20, 10, ("Restrained" if variant == "restrained" else "Ambitious") + " feature editor: pending → valid → error", 16, 600, C["ink"], h=28)
    c.text(20, 36, "Same FeaturePanel skeleton (header · scrolling form · verdict strip); states driven by the existing preview sequence/generation keys.", 12, 400, C["muted"], h=20)
    panels = [
        ("pending", "Extrude", [
            ("Operation", "segment", "Add", {"options": ["New", "Add", "Cut", "Intersect"]}),
            ("Profile", "picker", "Boss profile", {"refs": ["Boss profile (sketch)"]}),
            ("End", "combo", "Blind", {}),
            ("Depth", "field", "22", {"unit": "mm", "focus": True}),
            ("Direction", "check", False, {"text": "Reverse"}),
        ], ["Evaluating exact geometry…", "Provisional preview shown · Confirm waits for the exact result"]),
        ("valid", "Extrude", [
            ("Operation", "segment", "Add", {"options": ["New", "Add", "Cut", "Intersect"]}),
            ("Profile", "picker", "Boss profile", {"refs": ["Boss profile (sketch)"]}),
            ("End", "combo", "Blind", {}),
            ("Depth", "field", "22", {"unit": "mm"}),
            ("Direction", "check", False, {"text": "Reverse"}),
        ], ["Preview valid · adds 33,446 mm³ · 1 solid", "Merges with Plate · Confirm (Enter) commits one Undo step"]),
        ("error", "Fillet", [
            ("Edges", "picker", "Pick edges in viewport", {"active": True, "invalid": True, "refs": ["Boss · Edge7", "Plate · Edge2"], "missing": "Plate · Edge2"}),
            ("Radius", "field", "6", {"unit": "mm", "invalid": True, "hint": "6 mm exceeds the 4.5 mm wall beside Edge7"}),
        ], ["Fillet failed: radius too large for Edge7", "Reduce the radius below 4.5 mm or remove Edge7 · values kept", "Plate · Edge2 no longer exists after the last edit"]),
    ]
    x = 30
    for state, title, rows, verdict in panels:
        # mini viewport behind each panel
        vx, vy, vw, vh = x, 70, 500, 850
        c.rect(vx, vy, vw, vh, fill="#fbfbfc", stroke=C["divider"])
        iso = iso_projector(vx + 300, vy + 600, 2.3)
        draw_model(c, iso, variant, preview=state if title == "Extrude" else None,
                   base="#8fa3b8" if variant == "ambitious" else "#9aa3ac", edges="#3d4650" if variant == "ambitious" else C["ink"])
        if title == "Fillet":
            # highlight the problematic edge
            a, b = iso(80 + 22, 40, 36), iso(80, 40 + 22, 36)
            c.line(a[0], a[1], b[0], b[1], C["error"], 3)
            c.line(b[0], b[1], b[0] - 60, b[1] - 50, C["error"], 1)
            c.text(b[0] - 150, b[1] - 64, "Edge7 · 4.5 mm wall", 10, 600, C["error"], h=14)
        editor_panel(c, vx + 12, vy + 12, 340, title, rows, verdict, state, variant,
                          step="Feature 4 of 7" if variant == "ambitious" else None)
        label = {"pending": "PENDING", "valid": "VALID", "error": "ERROR"}[state]
        c.chip(vx + vw - 90, vy + 12, label, "#ffffff", {"pending": C["muted"], "valid": C["success"], "error": C["error"]}[state], 11, h=20)
        if variant == "ambitious":
            if state == "valid":
                c.chip(vx + 300, vy + 800, "+33,446 mm³ · 1 solid", C["success"], "#eaf5ee", 11, h=20)
                # direction flip handle in viewport
                tip = iso(25, 20, 44 + 30)
                c.circle(tip[0], tip[1], 9, fill=C["surface"], stroke=C["accent"], sw=1.5)
                c.icon("transform", tip[0] - 7, tip[1] - 7, 14, tint=C["accent"])
                c.text(tip[0] + 14, tip[1] - 8, "flip direction", 10, 400, C["accent"], h=14)
            if state == "pending":
                c.text(vx + 300, vy + 802, "~ 0.4 s · exact worker", 10, 400, C["muted"], h=16)
            if state == "error":
                c.button(vx + 300, vy + 796, 130, 24, "Use 4.5 mm", primary=False)
        x += 520
    if variant == "restrained":
        legend += [
            "Header keeps icon-only Confirm/Cancel but uses the toolbar's own SVG check/cross (presentation_icons) instead of QStyle standard icons; Confirm tinted blue only when the exact preview is valid.",
            "Verdict strip gains a 4 px semantic edge, an icon or spinner, and a second line that names the consequence ('adds 33,446 mm³ · 1 solid') from the existing preview measurements.",
            "Pending: spinner + 'Provisional preview shown'; the viewport preview is dashed/translucent so provisional geometry is never mistaken for the exact result.",
            "Error: the verdict names the failing input, a next step and that entered values are kept; the offending field and reference row get the theme's existing invalid outline; missing references are tagged inline.",
            "Operation as a segmented control instead of a combo (New/Add/Cut/Intersect are 4 fixed choices); End condition stays a combo.",
            "No new widgets outside FeaturePanel: set_status(text, severity) extended with a second line and an icon; ReferencePicker rows gain a 'missing' state.",
        ]
    else:
        legend += [
            "Text Confirm/Cancel buttons (primary blue when valid) and a 'Feature 4 of 7' position so the editor says where in history the feature lands.",
            "In-viewport affordances: a flip-direction handle at the preview tip and a volume delta chip beside the preview, both Coin SoAnnotation overlays bound to the preview result.",
            "Pending shows the expected wait ('~0.4 s · exact worker') from the responsiveness timing samples, so a slow model explains itself.",
            "Error offers a one-click repair ('Use 4.5 mm') when the kernel diagnostic can propose one (fillet max radius probe), otherwise the same text guidance as the restrained option.",
            "Missing references are shown in red with a 'missing' tag and the reference picker outline turns red; the healthy edge stays listed so the user removes only the broken one.",
            "Cost: needs a kernel-side probe for the suggested value and an overlay layer; the restrained option needs neither.",
        ]
    return legend


SCENES = {
    "workspace-restrained": (scene_workspace, "restrained", "Main workspace · restrained polish", "Keeps the light shell, icon-only rows, SolidWorks navigation and the native renderer; changes are styling, grouping and status placement."),
    "workspace-ambitious": (scene_workspace, "ambitious", "Main workspace · ambitious direction", "Adds a right view rail with quality presets, document-row state chips, part cards with color and a compact NaviCube; viewport loses 40 px on the right."),
    "sketch-restrained": (scene_sketch, "restrained", "Sketch editing · restrained polish", "Native Sketcher stays the editor; KurtShape's box becomes the single status/acceptance surface and the Tasks dock is hidden by default."),
    "sketch-ambitious": (scene_sketch, "ambitious", "Sketch editing · ambitious direction", "Inline dimension entry, constraint badges, DoF badge and snap narration drawn as overlays; native solver and tools unchanged."),
    "feature-editor-states-restrained": (scene_editor_states, "restrained", "Feature editor states · restrained", "Pending, valid and error states of the existing FeaturePanel with semantic verdict strip and consistent icons."),
    "feature-editor-states-ambitious": (scene_editor_states, "ambitious", "Feature editor states · ambitious", "Adds in-viewport handles, expected wait, one-click repairs and history position."),
}


def render(name, scene_fn, variant, title, subtitle, scale=2):
    legend_h = 250 if "feature-editor" not in name else 230
    total_h = H + legend_h
    img = QtGui.QImage(W * scale, total_h * scale, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(col(C["surface"]))
    svg_path = OUT / (name + ".svg")
    gen = QtSvg.QSvgGenerator()
    gen.setFileName(str(svg_path))
    gen.setSize(QtCore.QSize(W, total_h))
    gen.setViewBox(QtCore.QRect(0, 0, W, total_h))
    gen.setTitle("KurtShape concept mockup: " + title)
    gen.setDescription("Concept mockup, not a screenshot. " + subtitle)
    legends = []
    for target in (img, gen):
        painter = QtGui.QPainter(target)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing)
        painter.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
        if target is img:
            painter.scale(scale, scale)
        c = Canvas(painter)
        c.rect(0, 0, W, total_h, fill=C["surface"])
        legend = scene_fn(c, variant)
        # frame + concept banner
        c.rect(0, 0, W, H, stroke=C["border"])
        c.rect(W - 330, H - 36 - 30 - 40, 316, 24, fill="#fff1cc", stroke="#e8c76a", r=3)
        c.text(W - 322, H - 36 - 30 - 40, "CONCEPT MOCKUP · not a screenshot of implemented behavior", 10, 700, "#7a4f00", h=24)
        # legend
        c.rect(0, H, W, legend_h, fill=C["workspace"])
        c.line(0, H, W, H)
        c.text(20, H + 8, title, 16, 700, C["ink"], h=26)
        c.text(20, H + 32, subtitle, 11, 400, C["muted"], h=18, w=W - 40)
        colw = (W - 60) / 2
        ys = [H + 58, H + 58]
        for i, entry in enumerate(legend):
            ci = i % 2 if "feature-editor" in name else (0 if i < (len(legend) + 1) // 2 else 1)
            x = 20 + ci * (colw + 20)
            y = ys[ci]
            c.callout(x + 11, y + 10, i + 1, r=10)
            # wrap text
            fm = QtGui.QFontMetricsF(c.font(11))
            words, lines, line = entry.split(), [], ""
            for wd in words:
                t = (line + " " + wd).strip()
                if fm.horizontalAdvance(t) <= colw - 40:
                    line = t
                else:
                    lines.append(line)
                    line = wd
            if line:
                lines.append(line)
            for li, ln in enumerate(lines):
                c.text(x + 30, y + li * 15, ln, 11, 400, C["ink"], h=16)
            ys[ci] = y + max(1, len(lines)) * 15 + 8
        painter.end()
        legends = legend
    img.save(str(OUT / (name + ".png")))
    return legends


def main():
    app = QtGui.QGuiApplication(sys.argv)  # noqa: F841
    # The offscreen platform has no system font database on Windows: register Segoe UI explicitly.
    for file in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf", "segoeuii.ttf"):
        QtGui.QFontDatabase.addApplicationFont("C:/Windows/Fonts/" + file)
    print("families with Segoe:", [f for f in QtGui.QFontDatabase.families() if "Segoe" in f])
    OUT.mkdir(parents=True, exist_ok=True)
    only = sys.argv[1:] or list(SCENES)
    for name in only:
        fn, variant, title, subtitle = SCENES[name]
        legend = render(name, fn, variant, title, subtitle)
        print(name, "ok", len(legend), "legend entries")


if __name__ == "__main__":
    main()
