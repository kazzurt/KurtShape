"""Typed native consumers of geometry references and authored selectors."""
import re

import FreeCAD as App
from . import selectors
from .bodies import owner

OPS = {"fillet", "chamfer", "shell", "project_geometry", "edit_dress_up"}
ARGS = {
    "fillet": {"id", "part", "edges", "radius"},
    "chamfer": {"id", "part", "edges", "size"},
    "shell": {"id", "part", "faces", "thickness", "reversed"},
    "project_geometry": {"sketch", "references", "defining"},
    "edit_dress_up": {"feature", "edges", "radius", "size", "expression"},
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
    if op == "edit_dress_up":
        return edit_dress_up(core, doc, req)

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


# Editing existing Fillet/Chamfer features ------------------------------------

DRESS_UP = {"PartDesign::Fillet": ("fillet", "Radius", "radius"),
            "PartDesign::Chamfer": ("chamfer", "Size", "size")}
EXPRESSION_PATTERN = r"[A-Za-z0-9_ .+*/()\[\]-]+"


def _dress_up(doc, name):
    from .core import OperationError
    feature = doc.getObject(name) if isinstance(name, str) else None
    if feature is None or feature.TypeId not in DRESS_UP:
        raise OperationError("missing_reference", "Choose an existing Fillet or Chamfer feature")
    base = feature.Base[0] if feature.Base else None
    if base is None or not hasattr(base, "Shape") or base.Shape.isNull() or not base.Shape.Solids:
        raise OperationError("missing_reference", f"{feature.Label} has no solid input to select edges from")
    return feature, base


def _edge_inputs(feature):
    inputs = selectors._json(feature, "QueryInputs")
    return {name: info for name, info in inputs.items() if name.startswith("edges_")}


def _forget_edge_inputs(feature):
    """Drop edge selector entries without removing native properties.

    Native Undo does not restore a dynamic property that one transaction
    removes and adds again, so metadata values are rewritten in place.
    """
    import json
    inputs = selectors._json(feature, "QueryInputs")
    if not any(name.startswith("edges_") for name in inputs):
        return
    inputs = {name: info for name, info in inputs.items() if not name.startswith("edges_")}
    feature.QueryInputs = json.dumps(inputs, sort_keys=True)
    if "QuerySources" in feature.PropertiesList:
        feature.QuerySources = list({obj.Name: obj for info in inputs.values()
                                     for obj in selectors._sources(feature.Document, info["selector"], before=feature)}.values())
    if "QueryHealth" in feature.PropertiesList:
        selectors._write_health(feature, {name: value for name, value in selectors._health(feature).items()
                                          if not name.startswith("edges_")})
    if "QueryResolutionLog" in feature.PropertiesList:
        logs = json.loads(feature.QueryResolutionLog or "[]")
        feature.QueryResolutionLog = json.dumps([entry for entry in logs if not str(entry.get("input", "")).startswith("edges_")],
                                                sort_keys=True)


def describe_dress_up(doc, name):
    """Current native settings and selected edges of a Fillet/Chamfer.

    Edges are subelements of the feature's own input (its Base), so edges
    the completed feature rounded away stay selectable while editing. A bound
    selector is returned as the reference so an untouched edge stays
    associative when it is sent back.
    """
    feature, base = _dress_up(doc, name)
    kind, prop, key = DRESS_UP[feature.TypeId]
    inputs = _edge_inputs(feature)
    edges = []
    for index, element in enumerate(feature.Base[1]):
        bound = inputs.get("edges_" + str(index))
        reference = ({"selector": bound["selector"]} if bound else {"feature": base.Name, "subelement": element})
        edges.append({"reference": reference, "subelement": element, "label": base.Label + " · " + element})
    expression = next((value for path, value in feature.ExpressionEngine if path.lstrip(".") == prop), None)
    limitations = []
    if getattr(feature, "UseAllEdges", False):
        limitations.append("This feature rounds all edges; selected edges are ignored until Use all edges is turned off")
    chamfer_type = getattr(feature, "ChamferType", None)
    if chamfer_type is not None and chamfer_type != "Equal distance":
        limitations.append("Its " + str(chamfer_type).lower() + " settings are kept; only Size and edges are edited here")
    return {"feature": feature.Name, "label": feature.Label, "kind": kind, "key": key,
            "base": base.Name, "base_label": base.Label, "edges": edges,
            "value": {"value": float(getattr(feature, prop).getValueAs("mm")), "expression": expression,
                      "native_property": prop},
            "limitations": limitations}


def edit_dress_up(core, doc, req):
    """Change edges and size of an existing Fillet/Chamfer in place.

    Runs inside the caller's native transaction, so a successful edit is one
    Undo step. The feature keeps its name, so downstream references remain.
    """
    from .core import OperationError, number
    feature, base = _dress_up(doc, req.get("feature"))
    kind, prop, key = DRESS_UP[feature.TypeId]
    other = "size" if key == "radius" else "radius"
    if other in req:
        raise OperationError("invalid_argument", f"A {kind} uses {key}, not {other}")
    if "expression" in req and req.get(key) is not None and req["expression"]:
        raise OperationError("invalid_argument", f"Provide either a {key} or a formula")
    if "edges" in req:
        specs = req["edges"]
        if not isinstance(specs, list) or not specs:
            raise OperationError("invalid_argument", f"Select one or more edges for {feature.Label}")
        # Resolve against history before this feature: its input shape.
        refs = _references(doc, specs, "edge", base, before=feature)
        _forget_edge_inputs(feature)
        feature.Base = (base, [reference["subelement"] for reference in refs])
        for index, spec in enumerate(specs):
            if is_selector(spec):
                selectors.bind(feature, "edges_" + str(index), selector_value(spec),
                               native_property="Base", mode="linksub_index", index=index)
    if "expression" in req:
        expression = req["expression"] or None
        if expression is not None and (not isinstance(expression, str) or len(expression) > 512
                                       or not re.fullmatch(EXPRESSION_PATTERN, expression)):
            raise OperationError("invalid_argument", "Use a dimensional formula with named properties and arithmetic")
        feature.setExpression(prop, expression)
    if key in req:
        current = next((value for path, value in feature.ExpressionEngine if path.lstrip(".") == prop), None)
        if current is not None:
            raise OperationError("expression_driven", f"{prop} is driven by the formula {current}; "
                                 "edit or clear the formula instead", expression=current)
        setattr(feature, prop, number(req[key], prop, True))
    core._recompute(doc)
    if "expression" in req and req["expression"] and {"Invalid", "Error"} & set(feature.State):
        raise OperationError("invalid_expression", "Formula is invalid, has a missing reference, or has incompatible units",
                             status=feature.getStatusString())
    if feature.Shape.isNull() or len(feature.Shape.Solids) != 1 or {"Invalid", "Error"} & set(feature.State):
        detail = feature.getStatusString() if {"Invalid", "Error"} & set(feature.State) else ""
        raise OperationError("build_failed", f"The {kind} could not be built on the selected edges"
                             + (f" ({detail})" if detail and detail != "Valid" else "")
                             + f"; try a smaller {key} or different edges", feature=feature.Name)
    return None
