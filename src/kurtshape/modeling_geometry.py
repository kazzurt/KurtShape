"""Native, persistent face extrusion and selected datum/axis inputs.

All geometry lives in FreeCAD's dependency graph. Selected planar faces are
traced by native ShapeBinders; revolution and mirror use their native LinkSub
inputs. No cached shape or Python feature is needed to rebuild a saved file.
"""
from __future__ import annotations

import FreeCAD as App
import Part
import re

from . import reference_tools, selectors, studio
from .bodies import origin_plane, owner

OPS = {"create_plane", "extrude_face", "move_face"}
ARGS = {
    "create_plane": {"id", "name", "body", "support", "base_plane", "offset"},
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


def _container_chain(doc, obj):
    """Placement expression prefix for every geometry group containing obj."""
    chain, parent = [], obj.getParentGeoFeatureGroup()
    while parent is not None:
        chain.insert(0, parent.Name + ".Placement * ")
        parent = parent.getParentGeoFeatureGroup()
    return "".join(chain)


def reference_driver(doc, kind, source, element, mode, name, operation, spec=None, input_name="reference"):
    """World-frame native driver for geometry that may live inside a Body.

    A root-level attached datum follows the source element in its container's
    frame without a scoped link (attachment links are document-wide). The
    driver composes every container placement by expression, so editing the
    source geometry or moving/rotating its Body moves the driver. Consumers
    link the driver, which shares their root scope.
    """
    datum = doc.addObject("PartDesign::Line" if kind == "line" else "PartDesign::Plane", name + "Datum")
    datum.AttachmentSupport = [(source, [element])]
    datum.MapMode = mode
    if kind == "line":
        driver = doc.addObject("Part::Line", name)
        driver.X1 = driver.Y1 = driver.Z1 = driver.X2 = driver.Y2 = 0
        driver.Z2 = 1
    else:
        # FreeCAD 1.1.4 recognizes a PartDesign datum plane by a "Plane"
        # substring in its Name; callers include it in ``name``.
        driver = doc.addObject("PartDesign::Plane", name)
        driver.MapMode = "Deactivated"
    driver.setExpression("Placement", _container_chain(doc, source) + datum.Name + ".Placement")
    for obj in (datum, driver):
        studio._prop(obj, "App::PropertyBool", "KurtShapeInternal", True)
        studio._prop(obj, "App::PropertyString", "KurtShapeOperationOwner", operation)
        if App.GuiUp:
            obj.ViewObject.Visibility = False
    studio._prop(driver, "App::PropertyLinkGlobal", "KurtShapeReferenceDatum", datum)
    if reference_tools.is_selector(spec):
        selectors.bind(datum, input_name, reference_tools.selector_value(spec),
                       native_property="AttachmentSupport", mode="linksublist")
    doc.recompute()
    if datum.Shape.isNull() or {"Invalid", "Error"} & set(datum.State) or {"Invalid", "Error"} & set(driver.State):
        raise _error("missing_reference", "The selected reference could not be attached")
    return driver, datum


def edge_reference(doc, spec):
    """Resolve a straight edge/line or circle/arc reference for a pattern.

    Returns (source, element, attachment mode, "line" | "circle"). Sketch
    references may use native lowercase ``edgeN`` (construction included).
    """
    if isinstance(spec, dict) and set(spec) <= {"feature", "subelement"}:
        source = doc.getObject(spec.get("feature", "") or "")
        element = spec.get("subelement", "") or ""
        if source is None:
            raise _error("missing_reference", "The selected reference no longer exists")
    else:
        reference = _reference(doc, spec, "edge")
        source, element = doc.getObject(reference["feature"]), reference["subelement"]
    if not re.fullmatch(r"[Ee]dge[1-9][0-9]*", element):
        raise _error("unsupported_reference", "Select a straight edge, sketch line, circle or arc")
    if not studio.reference_available(source):
        raise _error("missing_reference", "The selected reference is behind the rollback bar")
    try:
        edge = source.getSubObject(element) if source.TypeId == "Sketcher::SketchObject" else source.Shape.getElement(element)
    except Exception:
        edge = None
    if edge is None or edge.isNull() or not hasattr(edge, "Curve"):
        raise _error("missing_reference", "The selected edge no longer exists")
    if isinstance(edge.Curve, (Part.Line, Part.LineSegment)) and edge.Length > 1e-9:
        return source, element, "Tangent", "line"
    if isinstance(edge.Curve, Part.Circle):
        return source, element, "AxisOfCurvature", "circle"
    raise _error("unsupported_reference", "Select a straight edge or line, or a circle or arc; "
                 + type(edge.Curve).__name__ + " edges cannot define a pattern direction or axis")


def bind_mirror_plane(doc, tool, spec):
    obj, element = planar_reference(doc, spec, before=tool)
    operation = getattr(tool, "KurtShapeOperationOwner", "") or tool.Name
    if obj.TypeId not in {"App::Plane", "PartDesign::Plane"} and obj.getParentGeoFeatureGroup() is not None:
        # A planar face inside a Body: a direct MirrorPlane link would leave the
        # Mirror's scope ("go out of the allowed scope"). Follow it natively.
        driver, _ = reference_driver(doc, "plane", obj, element, "FlatFace", tool.Name + "MirrorPlane",
                                     operation, spec, "mirror_plane")
        tool.MirrorPlane = (driver, [""])
        return
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


def migrate_mirror_scopes(doc):
    """Relink saved studio mirrors whose MirrorPlane points inside a Body.

    The Mirror keeps its name, Source and outputs; only MirrorPlane moves to a
    native driver that follows the same face, so geometry is unchanged.
    """
    changed = False
    for tool in list(doc.Objects):
        if tool.TypeId != "Part::Mirroring" or not (getattr(tool, "KurtShapeStudioOperation", "")
                                                   or getattr(tool, "KurtShapeOperationOwner", "")):
            continue
        source, elements = tool.MirrorPlane if tool.MirrorPlane else (None, [])
        if (source is None or source.getParentGeoFeatureGroup() is None
                or source.TypeId in {"App::Plane", "PartDesign::Plane"} or not elements):
            continue
        face = source.Shape.getElement(elements[0]) if hasattr(source, "Shape") else None
        if face is None or not isinstance(getattr(face, "Surface", None), Part.Plane):
            continue  # Left as is; the build status reports a broken/nonplanar plane.
        operation = getattr(tool, "KurtShapeOperationOwner", "") or tool.Name
        driver, datum = reference_driver(doc, "plane", source, elements[0], "FlatFace",
                                         tool.Name + "MirrorPlane", operation)
        tool.MirrorPlane = (driver, [""])
        selectors.move_binding(tool, datum, "mirror_plane", "AttachmentSupport", "linksublist")
        changed = True
    return changed


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


def _create_plane(core, doc, req):
    if "support" in req and "base_plane" in req:
        raise _error("invalid_argument", "Choose one support or one origin plane")
    body = core._body(doc, req)
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
