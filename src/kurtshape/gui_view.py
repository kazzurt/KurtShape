"""set_view: aim the running app's own 3D view (a GUI view operation, 2026-10-20).

The camera is orthographic, looks along the view direction and is centred on the frame. FreeCAD
saves a document's camera in its FCStd (GuiDocument.xml) and restores it when the file opens, so
a camera set in a hidden app before ``save`` is the view the file opens with anywhere.

Like ``render_view`` it never changes the document, its revision, undo history or Modified flag.
The headless Controller has no 3D view: it computes the same camera and reports ``applied:false``.
"""
from __future__ import annotations

import math
import re

import FreeCAD as App

from .core import OperationError, number

VIEWS = {
    # Same directions and ups as render_view (model_render.VIEWS).
    "iso": ((-1.0, 1.0, -1.0), (0.0, 0.0, 1.0)),
    "front": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "back": ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
    "right": ((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "left": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "top": ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
    "bottom": ((0.0, 0.0, 1.0), (0.0, -1.0, 0.0)),
}
VIEW_NAMES = tuple(VIEWS)
FRAMES = ("model",)
PARALLEL_COS = 0.999
MODEL_MARGIN = 1.1        # the model frame leaves 5 % on each side of the projected box
EMPTY_HEIGHT_MM = 100.0   # model frame of a document that shows no solid or face
NOTE = ("Changes only the app's 3D view (orthographic; the window's shorter side spans height_mm). "
        "FreeCAD saves the camera in the FCStd and restores it on open.")


def _invalid(field, message, reason="value", **details):
    return OperationError("invalid_argument", message, fields=[field], reason=reason, **details)


def _vector(value, field, label):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise _invalid(field, label + " must be three numbers", "type")
    result = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float, str)):
            raise _invalid(field, label + " must be three numbers", "type")
        try:
            result.append(float(number(item, label)))
        except OperationError as exc:
            raise _invalid(field, str(exc), "type") from None
    return result


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _unit(v):
    length = math.sqrt(_dot(v, v))
    return [c / length for c in v]


def _clean(v, digits=9):
    return [round(c, digits) + 0.0 for c in v]


def basis(direction, up=None, field="view"):
    """(d, u, r): view direction, screen up (orthogonalized) and screen right r = d x u."""
    if math.sqrt(_dot(direction, direction)) < 1e-12:
        raise _invalid(field, "view direction must be nonzero", "zero_vector")
    d = _unit(direction)
    if up is None:
        up = (0.0, 1.0, 0.0) if abs(d[2]) >= PARALLEL_COS else (0.0, 0.0, 1.0)
    if math.sqrt(_dot(up, up)) < 1e-12:
        raise _invalid(field, "view up must be nonzero", "zero_vector")
    if abs(_dot(_unit(up), d)) >= PARALLEL_COS:
        raise _invalid(field, "view up must not be parallel to the view direction", "parallel_up")
    u = _unit([a - _dot(up, d) * b for a, b in zip(up, d)])
    return d, u, _cross(d, u)


def normalize(request):
    """The request's view and frame: {name, direction, up, right, frame}."""
    view = request.get("view", "iso")
    if isinstance(view, str):
        if view not in VIEWS:
            raise _invalid("view", "Unknown view " + repr(view)[:40], "value", allowed=list(VIEW_NAMES))
        name, (direction, up) = view, VIEWS[view]
    elif isinstance(view, dict):
        if "direction" not in view or set(view) - {"direction", "up"}:
            raise _invalid("view", "A custom view is {direction, up?}", "type")
        name = "custom"
        direction = _vector(view["direction"], "view", "view direction")
        up = None if view.get("up") is None else _vector(view["up"], "view", "view up")
    else:
        raise _invalid("view", "view is a view name or {direction, up?}", "type")
    d, u, r = basis(direction, up)
    frame = request.get("frame", "model")
    if isinstance(frame, dict):
        if set(frame) != {"center_mm", "width_mm"}:
            raise _invalid("frame", "An explicit frame is {center_mm, width_mm}", "type")
        center = _vector(frame["center_mm"], "frame", "frame center_mm")
        try:
            width = float(number(frame["width_mm"], "frame width_mm"))
        except OperationError as exc:
            raise _invalid("frame", str(exc), "type") from None
        if not (width > 0 and math.isfinite(width)):
            raise _invalid("frame", "frame width_mm must be > 0", "range")
        frame = {"center_mm": center, "width_mm": width}
    elif frame not in FRAMES:
        raise _invalid("frame", "frame is model or {center_mm, width_mm}", "value")
    return {"name": name, "direction": d, "up": u, "right": r, "frame": frame}


def shown_box(doc):
    """World box of the top-level objects that show solids or faces (None if nothing is shown)."""
    gui = getattr(App, "GuiUp", False)
    box = None
    for obj in doc.Objects:
        shape = getattr(obj, "Shape", None)
        if shape is None or getattr(obj, "KurtShapeInternal", False):
            continue
        try:
            if obj.getParentGeoFeatureGroup() is not None or shape.isNull() or not shape.Faces:
                continue
            view = getattr(obj, "ViewObject", None) if gui else None
            if not (view.Visibility if view is not None else obj.Visibility):
                continue
            bound = shape.BoundBox
        except Exception:
            continue
        if bound.isValid():
            box = App.BoundBox(bound) if box is None else box.united(bound) or box
    return box


def camera(doc, settings):
    """Orthographic camera {direction, up, right, center_mm, height_mm, distance_mm} for the settings."""
    d, u, r = settings["direction"], settings["up"], settings["right"]
    box = shown_box(doc)
    corners = [] if box is None else [(x, y, z) for x in (box.XMin, box.XMax)
                                      for y in (box.YMin, box.YMax) for z in (box.ZMin, box.ZMax)]
    frame = settings["frame"]
    if isinstance(frame, dict):
        center, height = list(frame["center_mm"]), frame["width_mm"]
    elif corners:
        center = [box.Center.x, box.Center.y, box.Center.z]
        extent = max(max(_dot(c, axis) for c in corners) - min(_dot(c, axis) for c in corners) for axis in (u, r))
        height = max(extent * MODEL_MARGIN, 1e-3)
    else:
        center, height = [0.0, 0.0, 0.0], EMPTY_HEIGHT_MM
    # The camera stands in front of everything shown, so nothing between it and the frame is clipped.
    ahead = max([_dot([a - b for a, b in zip(c, center)], [-x for x in d]) for c in corners] + [0.0])
    distance = ahead + max(height, 10.0)
    return {"projection": "orthographic", "direction": _clean(d), "up": _clean(u), "right": _clean(r),
            "center_mm": _clean(center, 6), "height_mm": round(height, 6), "distance_mm": round(distance, 6)}


def rotation(direction, up):
    """App.Rotation that turns the Inventor camera frame (looks along -Z, up +Y) to direction and up."""
    d, u = _unit(direction), _unit(up)
    r = _cross(d, u)
    matrix = App.Matrix(r[0], u[0], -d[0], 0, r[1], u[1], -d[1], 0, r[2], u[2], -d[2], 0, 0, 0, 0, 1)
    return App.Rotation(matrix)


def camera_text(cam):
    """Inventor camera description that View3DInventor.setCamera accepts."""
    rot = rotation(cam["direction"], cam["up"])
    axis, angle = rot.Axis, rot.Angle
    position = [c - x * cam["distance_mm"] for c, x in zip(cam["center_mm"], cam["direction"])]
    return ("#Inventor V2.1 ascii\n\nOrthographicCamera {\n  viewportMapping ADJUST_CAMERA\n"
            "  position %.9g %.9g %.9g\n  orientation %.12g %.12g %.12g %.12g\n"
            "  nearDistance 0\n  farDistance %.9g\n  aspectRatio 1\n  focalDistance %.9g\n  height %.9g\n}\n"
            % (*position, axis.x, axis.y, axis.z, angle, 2 * cam["distance_mm"] + cam["height_mm"],
               cam["distance_mm"], cam["height_mm"]))


_NUMBER = r"([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)"


def parse_camera(text):
    """The camera a view reports (getCamera text): {projection, direction, up, right, center_mm, height_mm}."""
    def values(key, count):
        match = re.search(r"\b" + key + r"\s+" + r"\s+".join([_NUMBER] * count), text)
        return [float(v) for v in match.groups()] if match else None
    position, orientation = values("position", 3), values("orientation", 4)
    focal, height = values("focalDistance", 1), values("height", 1)
    if position is None or orientation is None or focal is None:
        return None
    rot = App.Rotation(App.Vector(*orientation[:3]), math.degrees(orientation[3]))
    d, u = rot.multVec(App.Vector(0, 0, -1)), rot.multVec(App.Vector(0, 1, 0))
    d, u = [d.x, d.y, d.z], [u.x, u.y, u.z]
    center = [p + x * focal[0] for p, x in zip(position, d)]
    return {"projection": "orthographic" if "OrthographicCamera" in text else "perspective",
            "direction": _clean(d), "up": _clean(u), "right": _clean(_cross(d, u)),
            "center_mm": _clean(center, 6), "height_mm": None if height is None else round(height[0], 6)}


def _document_view(doc):
    import FreeCADGui as Gui
    gui_document = Gui.getDocument(doc.Name)
    if gui_document is None:
        return None
    view = gui_document.activeView()
    if view is not None and hasattr(view, "setCamera"):
        return view
    views = [item for item in gui_document.mdiViewsOfType("Gui::View3DInventor") if hasattr(item, "setCamera")]
    return views[0] if views else None


def set_view(controller, doc, request):
    """Handle one set_view request on an open document."""
    identifier = controller.identifier(doc)
    if (identifier in controller.sketch_edits
            or getattr(App, "GuiUp", False) and controller._native_edit_active()):
        raise OperationError("sketch_edit_active", "Finish or cancel the active edit before moving the view")
    meta = controller._meta(doc)
    if "expected_revision" in request and request["expected_revision"] != meta.Revision:
        raise OperationError("stale_revision", "Inspect the current document before moving its view",
                             expected=request["expected_revision"], actual=meta.Revision)
    settings = normalize(request)
    cam = camera(doc, settings)
    applied, reason = False, "no_gui"
    if getattr(App, "GuiUp", False):
        view = _document_view(doc)
        reason = "no_view"
        if view is not None:
            view.setCameraType("Orthographic")
            view.setCamera(camera_text(cam))
            if hasattr(view, "redraw"):
                view.redraw()
            reported = parse_camera(view.getCamera())
            applied, reason = True, None
            if reported is not None:
                cam = dict(cam, **{key: value for key, value in reported.items() if value is not None})
    return {"document_id": identifier, "revision": meta.Revision, "view": settings["name"],
            "frame": settings["frame"], "applied": applied, "reason": reason, "camera": cam, "note": NOTE}
