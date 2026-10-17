"""Native, persistent face extrusion and selected datum/axis inputs.

All geometry lives in FreeCAD's dependency graph. Selected planar faces are
traced by native ShapeBinders; revolution and mirror use their native LinkSub
inputs. No cached shape or Python feature is needed to rebuild a saved file.
"""
from __future__ import annotations

import FreeCAD as App
import Part
import json
import math
import re

from . import reference_tools, selectors, studio
from .bodies import origin_plane, owner

OPS = {"create_plane", "extrude_face", "move_face"}
# Mutually exclusive datum-plane definitions. Fields shared by every mode are
# id, name, body and offset; "offset" mode is the original support/origin plane.
PLANE_MODES = {
    "offset": ("support", "base_plane"),
    "point_normal": ("origin", "normal", "x_direction"),
    "three_points": ("points",),
    "line_angle": ("axis", "reference_normal", "angle"),
}
ARGS = {
    "create_plane": {"id", "name", "body", "offset"} | {key for keys in PLANE_MODES.values() for key in keys},
    "extrude_face": {"id", "name", "face", "length", "reversed", "operation", "merge_scope"},
    "move_face": {"id", "name", "part", "faces", "distance"},
}


def _error(code, message, **details):
    from .core import OperationError
    return OperationError(code, message, **details)


def _number(value, name, positive=False):
    from .core import number
    return number(value, name, positive)


def _reference(doc, spec, entity_type, before=None):
    return selectors.native_reference(doc, reference_tools.selector_value(spec),
                                      entity_type=entity_type, before=before)


def _shape(doc, reference):
    from .assembly import global_shape
    obj = doc.getObject(reference["feature"])
    return obj, global_shape(obj).getElement(reference["subelement"])


def planar_reference(doc, spec, before=None):
    """Resolve an origin/datum plane itself or exactly one planar face."""
    if isinstance(spec, str):
        spec = {"feature": spec}
    if isinstance(spec, dict) and set(spec) <= {"feature", "subelement"}:
        obj = doc.getObject(spec.get("feature", ""))
        if obj is None:
            raise _error("missing_reference", "Selected plane does not exist")
        if obj.TypeId in {"App::Plane", "PartDesign::Plane"}:
            if spec.get("subelement"):
                raise _error("invalid_reference", "Select the datum plane itself")
            if not studio.is_active(obj):
                raise _error("missing_reference", "Selected plane is behind the rollback bar")
            return obj, ""
    reference = _reference(doc, spec, "face", before=before)
    obj, face = _shape(doc, reference)
    if not isinstance(face.Surface, Part.Plane):
        raise _error("nonplanar_support", "Choose a datum plane or planar face")
    return obj, reference["subelement"]


def named_plane_candidates(doc):
    """Return explicit native plane references for sketch/mirror pickers."""
    return [{"id": obj.Name, "name": obj.Label, "reference": {"feature": obj.Name}}
            for obj in doc.Objects if obj.TypeId in {"App::Plane", "PartDesign::Plane"}
            and not getattr(obj, "KurtShapeInternal", False) and studio.is_active(obj)
            and not (owner(doc, obj) and getattr(owner(doc, obj), "KurtShapeInternal", False))]


def bind_mirror_plane(doc, tool, spec):
    obj, element = planar_reference(doc, spec, before=tool)
    if obj.TypeId in {"App::Plane", "PartDesign::Plane"}:
        # FreeCAD 1.1.4 identifies PartDesign datum planes by a "Plane"
        # substring in their internal Name (FeatureMirroring.cpp). A native
        # attached driver works for user-authored names such as "TopDatum" and
        # also carries the support into its proper world attachment frame.
        driver = doc.addObject("PartDesign::Plane", tool.Name + "MirrorPlane")
        driver.AttachmentSupport = [(obj, [""])]
        driver.MapMode = "Deactivated"
        parent = owner(doc, obj)
        placement = (parent.Name + ".Placement * " if parent else "") + obj.Name + ".Placement"
        driver.setExpression("Placement", placement)
        studio._prop(driver, "App::PropertyBool", "KurtShapeInternal", True)
        doc.recompute()
        obj = driver
    tool.MirrorPlane = (obj, [element])
    if reference_tools.is_selector(spec):
        selectors.bind(tool, "mirror_plane", reference_tools.selector_value(spec),
                       native_property="MirrorPlane")


def bind_revolve_axis(doc, tool, spec):
    if isinstance(spec, dict) and set(spec) <= {"feature", "subelement"}:
        sketch = doc.getObject(spec.get("feature", ""))
        if sketch and sketch.TypeId == "Sketcher::SketchObject":
            match = re.fullmatch(r"[Ee]dge([1-9][0-9]*)", str(spec.get("subelement", "")))
            index = int(match.group(1)) - 1 if match else -1
            if not 0 <= index < sketch.GeometryCount:
                raise _error("missing_reference", "Selected sketch axis no longer exists")
            line = sketch.Geometry[index]
            if not isinstance(line, (Part.Line, Part.LineSegment)):
                raise _error("unsupported_axis", "Revolve axis must be a straight, nonzero sketch line")
            # Lowercase edgeN is FreeCAD's native sketch Geometry reference.
            # Uppercase EdgeN addresses the result Shape, which omits
            # construction lines and can have a different edge ordering.
            element = "edge" + str(index + 1)
            edge = sketch.getSubObject(element)
            if edge is None or edge.isNull() or edge.Length < 1e-9:
                raise _error("unsupported_axis", "Revolve axis must be a straight, nonzero sketch line")
            _neutral_axis(doc, tool, sketch, element, spec)
            return
    reference = _reference(doc, spec, "edge", before=tool)
    obj, edge = _shape(doc, reference)
    if not isinstance(edge.Curve, (Part.Line, Part.LineSegment)) or edge.Length < 1e-9:
        raise _error("unsupported_axis", "Revolve axis must be a straight, nonzero edge")
    _neutral_axis(doc, tool, obj, reference["subelement"], spec)


def _neutral_axis(doc, tool, source, element, spec, bind_selector=True):
    """Native tangent attachment plus a finite root line avoid illegal links.

    Sketch construction geometry is available to the native attachment engine
    even though ShapeBinder omits it. A finite line avoids the enormous start
    point of a datum's infinite line in the Part revolution axis calculation.
    """
    body = owner(doc, source)
    tip = body.Tip if body else None
    datum = body.newObject("PartDesign::Line", tool.Name + "AxisDatum") if body else doc.addObject("PartDesign::Line", tool.Name + "AxisDatum")
    datum.AttachmentSupport = [(source, [element])]
    datum.MapMode = "Tangent"
    studio._prop(datum, "App::PropertyBool", "KurtShapeInternal", True)
    operation = getattr(tool, "KurtShapeOperationOwner", "") or tool.Name
    studio._prop(datum, "App::PropertyString", "KurtShapeOperationOwner", operation)
    if body and body.Tip != tip:
        body.Tip = tip
    if bind_selector and reference_tools.is_selector(spec):
        selectors.bind(datum, "axis", reference_tools.selector_value(spec), native_property="AttachmentSupport", mode="linksublist")
    line = doc.addObject("Part::Line", tool.Name + "AxisLine")
    line.X1 = line.Y1 = line.Z1 = line.X2 = line.Y2 = 0
    line.Z2 = 1
    line.setExpression("Placement", (body.Name + ".Placement * " if body else "") + datum.Name + ".Placement")
    studio._prop(line, "App::PropertyBool", "KurtShapeInternal", True)
    studio._prop(line, "App::PropertyString", "KurtShapeOperationOwner", operation)
    studio._prop(line, "App::PropertyLinkGlobal", "KurtShapeAxisDatum", datum)
    tool.AxisLink = (line, ["Edge1"])
    return line


def migrate_axis_scopes(doc):
    """Upgrade saved direct sketch/Body axis links to the legal native driver."""
    import json
    changed = False
    for tool in list(doc.Objects):
        if tool.TypeId != "Part::Revolution" or not (getattr(tool, "KurtShapeStudioOperation", "")
                                                    or getattr(tool, "KurtShapeOperationOwner", "")):
            continue
        axis_link = tool.AxisLink
        if not axis_link:
            continue
        source, elements = axis_link
        if source is None or source.TypeId == "PartDesign::Body" or owner(doc, source) is None or not elements:
            continue
        inputs = selectors._json(tool, "QueryInputs")
        axis = inputs.pop("axis", None)
        spec = axis["selector"] if axis else {"feature": source.Name, "subelement": elements[0]}
        line = _neutral_axis(doc, tool, source, elements[0], spec, bind_selector=False)
        changed = True
        if axis:
            # Transfer already-authored metadata, without adding a migration
            # Undo step that could restore the invalid native link on reopen.
            datum = line.KurtShapeAxisDatum
            binding = dict(axis, native_property="AttachmentSupport", mode="linksublist")
            binding["resolved"] = [{"feature": source.Name, "subelement": elements[0]}]
            selectors._property(datum, "QueryInputs", json.dumps({"axis": binding}, sort_keys=True))
            selectors._property(datum, "QuerySources", selectors._sources(doc, spec, before=tool), "App::PropertyLinkListGlobal")
            health = selectors._health(tool)
            selectors._write_health(datum, {"axis": health.pop("axis", {"status": "healthy", "count": 1})})
            logs = json.loads(getattr(tool, "QueryResolutionLog", "[]"))
            selectors._property(datum, "QueryResolutionLog", json.dumps([entry for entry in logs if entry.get("input") == "axis"], sort_keys=True))
            if inputs:
                selectors._property(tool, "QueryInputs", json.dumps(inputs, sort_keys=True))
                sources = {obj.Name: obj for info in inputs.values() for obj in selectors._sources(doc, info["selector"], before=tool)}
                selectors._property(tool, "QuerySources", list(sources.values()), "App::PropertyLinkListGlobal")
                selectors._write_health(tool, health)
                selectors._property(tool, "QueryResolutionLog", json.dumps([entry for entry in logs if entry.get("input") != "axis"], sort_keys=True))
            else:
                for prop in ("QueryInputs", "QuerySources", "QueryHealth", "QueryResolutionLog"):
                    if prop in tool.PropertiesList:
                        tool.removeProperty(prop)
    return changed


def is_reference(value):
    return isinstance(value, dict) and ("feature" in value or reference_tools.is_selector(value))


def make_face_tool(core, doc, req, name):
    """Create an editable native extrusion from one selected planar face."""
    if req.get("end_type", "blind") != "blind" or "up_to_face" in req:
        raise _error("invalid_argument", "Face extrusion currently requires a finite distance")
    reference = _reference(doc, req.get("face"), "face")
    source, face = _shape(doc, reference)
    if not isinstance(face.Surface, Part.Plane):
        raise _error("nonplanar_support", "Extrude requires a planar face")
    binder = doc.addObject("PartDesign::ShapeBinder", name + "Face")
    binder.Support = [(source, [reference["subelement"]])]
    binder.TraceSupport = True
    studio._prop(binder, "App::PropertyBool", "KurtShapeInternal", True)
    if reference_tools.is_selector(req.get("face")):
        selectors.bind(binder, "face", reference_tools.selector_value(req["face"]),
                       native_property="Support", mode="linksublist")
    tool = doc.addObject("Part::Extrusion", name)
    tool.Base, tool.DirMode, tool.Solid = binder, "Normal", True
    tool.LengthFwd = _number(req.get("length"), "Length", True)
    tool.Reversed = studio._bool(req, "reversed", req.get("op") == "pocket")
    studio._prop(tool, "App::PropertyBool", "KurtShapeInternal", True)
    doc.recompute()
    if tool.Shape.isNull() or len(tool.Shape.Solids) != 1 or studio._native_failed(tool):
        raise _error("build_failed", "Selected face could not produce a solid extrusion",
                     feature=tool.Name, status=tool.getStatusString())
    return tool


PLANE_GROUP = "KurtShape plane"
_X, _Y, _Z = App.Vector(1, 0, 0), App.Vector(0, 1, 0), App.Vector(0, 0, 1)
# Offset always moves along the finished plane's own normal (local +Z).
_ALONG_NORMAL = " * placement(vector(0; 0; Offset / 1 mm); create(<<rotation>>))"
# Native expressions drive AttachmentOffset from the Body-coordinate inputs
# below, so editing any of them (or Offset/Angle) moves the plane and every
# sketch attached to it. "ZXY" keeps the normal exact and projects X into it.
PLANE_EXPRESSIONS = {
    "point_normal": "placement(PlaneOrigin; create(<<rotation>>; PlaneXDirection; vector(0; 0; 0); PlaneNormal; <<ZXY>>))"
                    + _ALONG_NORMAL,
    "three_points": "placement(PlanePoint1; create(<<rotation>>; PlanePoint2 - PlanePoint1; vector(0; 0; 0); "
                    "vcross(PlanePoint2 - PlanePoint1; PlanePoint3 - PlanePoint1); <<ZXY>>))" + _ALONG_NORMAL,
    "line_angle": "placement(PlaneAxisOrigin; rotation(PlaneAxisDirection; Angle) * create(<<rotation>>; PlaneAxisDirection; "
                  "vector(0; 0; 0); PlaneReferenceNormal; <<XZY>>))" + _ALONG_NORMAL,
}
PLANE_PROPERTIES = {
    "point_normal": (("App::PropertyPosition", "PlaneOrigin", "Plane origin before Offset, in Body coordinates"),
                     ("App::PropertyVector", "PlaneNormal", "Plane normal and sketch +Z, in Body coordinates"),
                     ("App::PropertyVector", "PlaneXDirection", "Sketch +X, projected into the plane, in Body coordinates")),
    "three_points": (("App::PropertyPosition", "PlanePoint1", "Plane origin, in Body coordinates"),
                     ("App::PropertyPosition", "PlanePoint2", "Point on sketch +X, in Body coordinates"),
                     ("App::PropertyPosition", "PlanePoint3", "Point on the sketch +Y side; normal is (P2-P1)x(P3-P1)")),
    "line_angle": (("App::PropertyPosition", "PlaneAxisOrigin", "Point on the contained line and plane origin, in Body coordinates"),
                   ("App::PropertyVector", "PlaneAxisDirection", "Contained line direction and sketch +X, in Body coordinates"),
                   ("App::PropertyVector", "PlaneReferenceNormal", "Plane normal at Angle 0, perpendicular to the line"),
                   ("App::PropertyAngle", "Angle", "Right-handed rotation about the line from the reference normal")),
}


def plane_mode(req):
    """Return the single requested datum-plane definition."""
    present = [mode for mode, keys in PLANE_MODES.items() if any(key in req for key in keys)]
    if len(present) > 1:
        raise _error("invalid_argument", "Choose one plane definition: support/base_plane, origin+normal, "
                     "points, or axis+reference_normal", modes=present)
    return present[0] if present else "offset"


def _require(spec, keys, label):
    missing = [key for key in keys if key not in spec]
    if missing:
        raise _error("invalid_argument", label + " requires " + " and ".join(keys), missing=missing)


def _direction(value, name):
    return studio._vector(value, name, direction=True)


def _perpendicular(vector, normal, name, reference):
    """Unit component of a unit vector perpendicular to a unit normal."""
    projected = vector - normal * vector.dot(normal)
    if projected.Length < 1e-7:
        raise _error("invalid_argument", name + " must not be parallel to the " + reference)
    return projected.normalize()


def default_x_direction(normal):
    """World +X projected into the plane, or world +Y for a normal along X."""
    for axis in (_X, _Y):
        projected = axis - normal * axis.dot(normal)
        if projected.Length > 1e-6:
            return projected.normalize()


def _line(doc, spec):
    """A line as (origin, unit direction) in world coordinates."""
    if isinstance(spec, dict) and set(spec) <= {"origin", "direction"}:
        _require(spec, ("origin", "direction"), "axis")
        return studio._vector(spec["origin"], "axis.origin"), _direction(spec["direction"], "axis.direction"), None
    if not is_reference(spec):
        raise _error("invalid_argument", "axis requires {origin,direction} or one straight edge reference")
    reference = _reference(doc, spec, "edge")
    _, edge = _shape(doc, reference)
    if not isinstance(edge.Curve, (Part.Line, Part.LineSegment)) or edge.Length < 1e-9:
        raise _error("unsupported_axis", "Plane axis must be a straight, nonzero edge")
    start, end = edge.valueAt(edge.FirstParameter), edge.valueAt(edge.LastParameter)
    return start, (end - start).normalize(), reference


def _plane_frame(doc, req, mode):
    """World origin, x axis, normal and authored inputs for a frame mode."""
    if mode == "point_normal":
        _require(req, ("origin", "normal"), "A point-normal plane")
        origin = studio._vector(req["origin"], "origin")
        normal = _direction(req["normal"], "normal")
        x = (_perpendicular(_direction(req["x_direction"], "x_direction"), normal, "x_direction", "plane normal")
             if "x_direction" in req else default_x_direction(normal))
        return origin, x, normal, {"PlaneOrigin": origin, "PlaneNormal": normal, "PlaneXDirection": x}, None
    if mode == "three_points":
        points = req["points"]
        if not isinstance(points, (list, tuple)) or len(points) != 3:
            raise _error("invalid_argument", "points requires three [x,y,z] points")
        p1, p2, p3 = [studio._vector(point, "points[" + str(index) + "]") for index, point in enumerate(points)]
        first, second = p2 - p1, p3 - p1
        if first.Length < 1e-7 or second.Length < 1e-7:
            raise _error("invalid_argument", "points must be three distinct points")
        normal = first.cross(second)
        if normal.Length <= 1e-7 * first.Length * second.Length:
            raise _error("invalid_argument", "points must not be collinear")
        return (p1, App.Vector(first).normalize(), normal.normalize(),
                {"PlanePoint1": p1, "PlanePoint2": p2, "PlanePoint3": p3}, None)
    _require(req, ("axis", "reference_normal"), "A line-angle plane")
    origin, direction, edge = _line(doc, req["axis"])
    reference = _perpendicular(_direction(req["reference_normal"], "reference_normal"), direction,
                               "reference_normal", "axis direction")
    angle = studio._number(req.get("angle", 0), "angle", unit="rad")
    normal = App.Rotation(direction, math.degrees(angle)).multVec(reference)
    return (origin, direction, normal, {"PlaneAxisOrigin": origin, "PlaneAxisDirection": direction,
                                       "PlaneReferenceNormal": reference, "Angle": angle}, edge)


def _create_frame_plane(core, doc, req, body, mode):
    """Native datum plane at an arbitrary frame, attached to the Body origin.

    The plane keeps FreeCAD's FlatFace attachment to the Body XY plane; its
    AttachmentOffset is a native expression of the stored inputs, so the
    file rebuilds without KurtShape and edits update downstream sketches.
    """
    origin, x, normal, inputs, edge = _plane_frame(doc, req, mode)
    offset = _number(req.get("offset", 0), "Offset")
    # Requests use world millimetres; the plane is stored in its Body's frame.
    inverse = body.getGlobalPlacement().inverse()
    tip = body.Tip
    plane = body.newObject("PartDesign::Plane", core._id(doc, req, "Plane"))
    if req.get("name"):
        plane.Label = req["name"]
    plane.AttachmentSupport = [(origin_plane(body, "XY"), [""])]
    plane.MapMode = "FlatFace"
    plane.addProperty("App::PropertyString", "PlaneMode", PLANE_GROUP, "Datum plane definition")
    plane.PlaneMode = mode
    plane.setEditorMode("PlaneMode", 1)
    for kind, name, description in PLANE_PROPERTIES[mode]:
        plane.addProperty(kind, name, PLANE_GROUP, description)
        value = inputs[name]
        if name == "Angle":
            plane.Angle = math.degrees(value)
        else:
            setattr(plane, name, inverse.multVec(value) if kind == "App::PropertyPosition" else inverse.Rotation.multVec(value))
    if edge is not None:
        plane.addProperty("App::PropertyString", "PlaneAxisReference", PLANE_GROUP,
                          "Edge whose line was copied into PlaneAxisOrigin/PlaneAxisDirection at creation (not tracked)")
        plane.PlaneAxisReference = json.dumps(edge, sort_keys=True)
        plane.setEditorMode("PlaneAxisReference", 1)
    plane.addProperty("App::PropertyDistance", "Offset", PLANE_GROUP, "Signed offset along the plane normal")
    plane.Offset = offset
    plane.AttachmentOffset = inverse * App.Placement(origin + normal * offset, App.Rotation(x, App.Vector(), normal, "ZXY"))
    plane.setExpression("AttachmentOffset", PLANE_EXPRESSIONS[mode])
    body.Tip = tip
    core._recompute(doc)
    if studio._native_failed(plane):
        raise _error("attachment_failed", "The plane could not attach to its Body origin", status=plane.getStatusString())
    actual = plane.getGlobalPlacement()
    if ((actual.Base - (origin + normal * offset)).Length > 1e-7 or (actual.Rotation.multVec(_X) - x).Length > 1e-9
            or (actual.Rotation.multVec(_Z) - normal).Length > 1e-9):
        raise _error("attachment_failed", "The native plane did not reach the requested frame")
    if App.GuiUp:
        plane.ViewObject.Visibility = True
    return plane.Name


def _vector_list(value):
    return [value.x, value.y, value.z]


def _frame(placement):
    rotation = placement.Rotation
    return {"origin_mm": _vector_list(placement.Base), "x_direction": _vector_list(rotation.multVec(_X)),
            "y_direction": _vector_list(rotation.multVec(_Y)), "normal": _vector_list(rotation.multVec(_Z))}


def plane_summary(obj):
    """Inspection record of a native datum plane and its sketch frame.

    `frame` is in world coordinates and is exactly the frame of a sketch
    attached to the plane. `definition` repeats the authored request fields
    in Body coordinates (world when the Body is at identity).
    """
    mode = getattr(obj, "PlaneMode", "") or ("offset" if "Offset" in obj.PropertiesList else "native")
    definition = {}
    if mode == "point_normal":
        definition = {"origin": _vector_list(obj.PlaneOrigin), "normal": _vector_list(obj.PlaneNormal),
                      "x_direction": _vector_list(obj.PlaneXDirection)}
    elif mode == "three_points":
        definition = {"points": [_vector_list(getattr(obj, "PlanePoint" + str(index))) for index in (1, 2, 3)]}
    elif mode == "line_angle":
        definition = {"axis": {"origin": _vector_list(obj.PlaneAxisOrigin), "direction": _vector_list(obj.PlaneAxisDirection)},
                      "reference_normal": _vector_list(obj.PlaneReferenceNormal), "angle": math.radians(obj.Angle.Value)}
        if "PlaneAxisReference" in obj.PropertiesList:
            definition["axis_reference"] = json.loads(obj.PlaneAxisReference)
    if "Offset" in obj.PropertiesList:
        definition["offset"] = obj.Offset.Value
    return {"mode": mode, "frame": _frame(obj.getGlobalPlacement()),
            "placement": {"position_mm": _vector_list(obj.Placement.Base), "rotation_xyzw": list(obj.Placement.Rotation.Q)},
            "support": [{"feature": linked.Name, "subelements": list(elements)} for linked, elements in obj.AttachmentSupport],
            "map_mode": str(obj.MapMode), "definition": definition}


def plane_parameters(obj):
    """Signed driving Angle of a line-angle plane (Offset is reported by core)."""
    if getattr(obj, "PlaneMode", "") != "line_angle" or "Angle" not in obj.PropertiesList:
        return {}
    expression = next((value for path, value in obj.ExpressionEngine if path.lstrip(".") == "Angle"), None)
    return {"Angle": {"value": math.radians(obj.Angle.Value), "unit": "rad", "editable": expression is None,
                      "expression": expression, "native_property": "Angle", "signed": True}}


def _create_plane(core, doc, req):
    if "support" in req and "base_plane" in req:
        raise _error("invalid_argument", "Choose one support or one origin plane")
    mode = plane_mode(req)
    body = core._body(doc, req)
    if mode != "offset":
        return _create_frame_plane(core, doc, req, body, mode)
    spec = req.get("support")
    if spec is None:
        plane_name = req.get("base_plane", "XY")
        if plane_name not in {"XY", "XZ", "YZ"}:
            raise _error("unsupported_plane", "Origin plane must be XY, XZ or YZ")
        source, element = origin_plane(body, plane_name), ""
    else:
        source, element = planar_reference(doc, spec)
    tip = body.Tip
    plane = body.newObject("PartDesign::Plane", core._id(doc, req, "Plane"))
    if req.get("name"):
        plane.Label = req["name"]
    plane.AttachmentSupport = [(source, [element])]
    plane.MapMode = "FlatFace"
    plane.addProperty("App::PropertyDistance", "Offset", "KurtShape plane", "Signed normal offset from the selected support")
    plane.Offset = _number(req.get("offset", 0), "Offset")
    plane.setExpression("AttachmentOffset.Base.z", "Offset")
    if reference_tools.is_selector(spec):
        selectors.bind(plane, "support", reference_tools.selector_value(spec), native_property="AttachmentSupport")
    body.Tip = tip
    core._recompute(doc)
    if studio._native_failed(plane):
        raise _error("attachment_failed", "The plane could not attach to its selected support", status=plane.getStatusString())
    if App.GuiUp:
        plane.ViewObject.Visibility = True
    return plane.Name


def _check_offset_walls(shape, face):
    """A prism faithfully offsets a face only when its walls follow its normal.

    Reject tapered/filleted boundaries instead of quietly introducing a step.
    A complete general move-face operation needs extension and retrimming of
    adjacent surfaces, which these built-in native features do not provide.
    """
    normal = face.normalAt(0, 0)
    for other in shape.Faces:
        if other.isSame(face) or not any(edge.isSame(boundary) for edge in other.Edges for boundary in face.Edges):
            continue
        surface = other.Surface
        if isinstance(surface, Part.Plane) and abs(other.normalAt(0, 0).dot(normal)) < 1e-7:
            continue
        if isinstance(surface, Part.Cylinder) and abs(abs(surface.Axis.dot(normal)) - 1) < 1e-7:
            continue
        raise _error("unsupported_face_move", "Move face currently requires perpendicular planar walls or cylinders parallel to its normal")


def _move_face(core, doc, req):
    distance = _number(req.get("distance"), "Distance")
    if abs(distance) < 1e-9:
        raise _error("invalid_argument", "Move face requires a nonzero distance")
    body_request = {"body": req["part"]} if "part" in req else req
    body = core._body(doc, body_request)
    tip = body.Tip
    if tip is None or tip.Shape.isNull() or not tip.Shape.Solids:
        raise _error("missing_body", "Choose a current solid part")
    refs = reference_tools._references(doc, req.get("faces"), "face", tip)
    first_normal = None
    for reference in refs:
        face = tip.Shape.getElement(reference["subelement"])
        if not isinstance(face.Surface, Part.Plane):
            raise _error("nonplanar_support", "Move face currently supports planar offsets")
        normal = face.normalAt(0, 0)
        if first_normal is not None and abs(abs(first_normal.dot(normal)) - 1) > 1e-7:
            raise _error("unsupported_face_move", "Move face together currently requires parallel selected faces")
        first_normal = normal
        _check_offset_walls(tip.Shape, face)
    studio._enable(doc)
    key = studio.part_id(body)
    name = core._id(doc, req, "MoveFace")
    snapshots = studio._inputs(doc, [key], name)
    tools = []
    for index, spec in enumerate(req["faces"]):
        tool = make_face_tool(core, doc, {"op": "pad", "face": spec, "length": abs(distance), "reversed": distance < 0},
                              name + "Offset" + str(index + 1))
        tool_body = studio._output(doc, tool, name + "OffsetPart" + str(index + 1))
        studio._prop(tool_body, "App::PropertyBool", "KurtShapeInternal", True)
        tools.append(tool_body)
        if index:
            tool.setExpression("LengthFwd", tools[0].BaseFeature.Name + ".LengthFwd")
    doc.recompute()
    output, representative = studio._native_boolean(doc, snapshots[0][1], tools, name, key,
                                                    getattr(body, "KurtShapePartName", body.Label),
                                                    "union" if distance > 0 else "subtract")
    studio._validate(doc, [output])
    if abs(output.Shape.Volume - body.Shape.Volume) < 1e-7:
        raise _error("empty_cut", "Move face did not change the selected part")
    # Keep the useful native driving distance visible in the existing parameter
    # editor through the first extrusion's native LengthFwd property.
    studio._prop(representative, "App::PropertyLinkGlobal", "KurtShapeTool", tools[0].BaseFeature)
    return studio._record(doc, representative, req, [output], [key], snapshots)


def handle(core, doc, req):
    if req["op"] == "create_plane":
        return _create_plane(core, doc, req)
    if req["op"] == "move_face":
        return _move_face(core, doc, req)
    if req["op"] == "extrude_face":
        normalized = dict(req, op="pad")
        normalized.setdefault("operation", "add")
        normalized.setdefault("reversed", normalized["operation"] == "remove")
        studio._enable(doc)
        return studio._result_operation(core, doc, normalized, core._id(doc, req, "ExtrudeFace"))
    raise _error("unsupported_operation", "Unsupported face or datum operation")
