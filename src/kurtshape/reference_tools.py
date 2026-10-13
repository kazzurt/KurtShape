"""Typed native consumers of geometry references and authored selectors."""
import FreeCAD as App
from . import selectors
from .bodies import owner

OPS = {"fillet", "chamfer", "shell", "project_geometry"}
ARGS = {
    "fillet": {"id", "part", "edges", "radius"},
    "chamfer": {"id", "part", "edges", "size"},
    "shell": {"id", "part", "faces", "thickness", "reversed"},
    "project_geometry": {"sketch", "references", "defining"},
}


def is_selector(value):
    return isinstance(value, dict) and ("kind" in value or "selector" in value)


def selector_value(value):
    return value.get("selector", value)


def _references(doc, specs, entity_type, base, before=None):
    from .core import OperationError
    if not isinstance(specs, list) or not specs or len(specs) > 128:
        raise OperationError("invalid_argument", "Choose one or more geometry references (maximum 128)")
    resolved = []
    for spec in specs:
        reference = selectors.native_reference(doc, spec, before=before, entity_type=entity_type)
        source = doc.getObject(reference["feature"])
        element = reference["subelement"]
        if base is not None and source != base:
            mapped = source.Shape.getElementMappedName(element)
            element = base.Shape.getElementIndexedName(mapped) if mapped else ""
            if not element or not element.startswith(entity_type.capitalize()):
                raise OperationError("missing_reference", "Reference does not resolve on the current part; select it again or use a selector")
        if element in [entry["subelement"] for entry in resolved]:
            raise OperationError("invalid_argument", "The same geometry was selected more than once")
        resolved.append({"feature": (base or source).Name, "subelement": element})
    return resolved


def handle(core, doc, req):
    from .core import OperationError, number
    op = req["op"]
    if op == "project_geometry":
        from .sketch_tools import project_geometry
        return project_geometry(core, doc, req)

    body_request = dict(req)
    if "part" in req:
        body_request["body"] = req["part"]
    body = core._body(doc, body_request)
    tip = body.Tip
    if tip is None or tip.Shape.isNull() or not tip.Shape.Solids:
        raise OperationError("missing_body", "Choose a current solid part")
    field, entity_type = ("faces", "face") if op == "shell" else ("edges", "edge")
    refs = _references(doc, req.get(field), entity_type, tip)
    type_id = {"fillet": "PartDesign::Fillet", "chamfer": "PartDesign::Chamfer", "shell": "PartDesign::Thickness"}[op]
    feature = body.newObject(type_id, core._id(doc, req, {"fillet": "Fillet", "chamfer": "Chamfer", "shell": "Shell"}[op]))
    feature.Base = (tip, [reference["subelement"] for reference in refs])
    if op == "fillet":
        feature.Radius = number(req.get("radius"), "Radius", True)
    elif op == "chamfer":
        feature.Size = number(req.get("size"), "Chamfer size", True)
    else:
        thickness = number(req.get("thickness"), "Thickness", True)
        reversed_direction = req.get("reversed", False)
        if not isinstance(reversed_direction, bool):
            raise OperationError("invalid_argument", "reversed must be boolean")
        feature.Value = thickness
        feature.Reversed = reversed_direction
    for index, spec in enumerate(req[field]):
        if is_selector(spec):
            selectors.bind(feature, field + "_" + str(index), selector_value(spec),
                           native_property="Base", mode="linksub_index", index=index)
    core._recompute(doc)
    if feature.Shape.isNull() or len(feature.Shape.Solids) != 1 or {"Invalid", "Error"} & set(feature.State):
        raise OperationError("build_failed", "Native feature could not create one valid solid", feature=feature.Name)
    body.Tip = feature
    return feature.Name
