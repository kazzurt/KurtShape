"""Typed native consumers of geometry references and authored selectors."""
import re

import FreeCAD as App
from . import hole_tools, selectors
from .bodies import owner

OPS = {"fillet", "chamfer", "shell", "project_geometry", "edit_dress_up", "hole"}
ARGS = {
    "fillet": {"id", "part", "edges", "radius"},
    "chamfer": {"id", "part", "edges", "size"},
    "shell": {"id", "part", "faces", "thickness", "reversed"},
    "project_geometry": {"sketch", "references", "defining"},
    "edit_dress_up": {"feature", "edges", "radius", "size", "expression"},
    "hole": set(hole_tools.ARGS),
}


def is_selector(value):
    return isinstance(value, dict) and ("kind" in value or "selector" in value)


def selector_value(value):
    return value.get("selector", value)


def _on_base(doc, spec, entity_type, base, before=None):
    """The one element a reference names, as a subelement of ``base``."""
    from .core import OperationError
    reference = selectors.native_reference(doc, spec, before=before, entity_type=entity_type)
    source = doc.getObject(reference["feature"])
    element = reference["subelement"]
    if base is not None and source != base:
        mapped = source.Shape.getElementMappedName(element)
        element = base.Shape.getElementIndexedName(mapped) if mapped else ""
        if not element or not element.startswith(entity_type.capitalize()):
            raise OperationError("missing_reference", "Reference does not resolve on the current part; select it again or use a selector")
    return {"feature": (base or source).Name, "subelement": element}


def _references(doc, specs, entity_type, base, before=None):
    from .core import OperationError
    if not isinstance(specs, list) or not specs or len(specs) > 128:
        raise OperationError("invalid_argument", "Choose one or more geometry references (maximum 128)")
    resolved = []
    for spec in specs:
        reference = _on_base(doc, spec, entity_type, base, before)
        if reference["subelement"] in [entry["subelement"] for entry in resolved]:
            raise OperationError("invalid_argument", "The same geometry was selected more than once")
        resolved.append(reference)
    return resolved


# Multi references: {"selector": <query>, "all": true} in an edges list stands
# for every edge of the current part the query matches, re-evaluated at each
# regeneration (selectors.GROUP_MODE). Lists without it keep the per-slot path.
MULTI_FIELDS = {"selector", "all"}


def _edge_specs(specs):
    """Validate multi-reference entries; returns (specs, any_multi).

    A list with no ``all`` key is returned unchanged. ``all:false`` is the
    plain single selector ``{selector:<query>}``.
    """
    from .core import OperationError
    if not isinstance(specs, list) or not any(isinstance(spec, dict) and "all" in spec for spec in specs):
        return specs, False
    normalized, multi = [], False
    for spec in specs:
        if not isinstance(spec, dict) or "all" not in spec:
            normalized.append(spec)
            continue
        if "selector" not in spec:
            raise OperationError("invalid_argument", "all applies to a selector query; write {selector:<query>, all:true}")
        unknown = sorted(set(spec) - MULTI_FIELDS)
        if unknown:
            raise OperationError("unknown_argument", "Unknown multi reference field", fields=unknown)
        if not isinstance(spec["all"], bool):
            raise OperationError("invalid_argument", "all must be true or false")
        if not spec["all"]:
            normalized.append({"selector": spec["selector"]})
            continue
        if not isinstance(spec["selector"], dict) or "kind" not in spec["selector"]:
            raise OperationError("invalid_argument", "all:true needs a selector query (an object with kind), not a native element name")
        normalized.append(spec)
        multi = True
    for spec in normalized if multi else ():
        # A multi list unwraps {selector:...} entries itself, so it checks
        # their fields here; a typo such as "All" must not drop the intent.
        if isinstance(spec, dict) and "selector" in spec and "all" not in spec and set(spec) != {"selector"}:
            raise OperationError("unknown_argument", "Unknown reference field; a {selector:<query>} entry takes only "
                                 "selector and all", fields=sorted(set(spec) - MULTI_FIELDS))
    return normalized, multi


def _group_entries(doc, specs, entity_type, base, before=None):
    """Members for selectors.bind_group: literals on ``base``, single and multi selectors."""
    from .core import OperationError
    if not specs or len(specs) > 128:
        raise OperationError("invalid_argument", "Choose one or more geometry references (maximum 128)")
    entries = []
    for spec in specs:
        if isinstance(spec, dict) and spec.get("all") is True:
            entries.append({"selector": spec["selector"], "many": True})
        elif is_selector(spec):
            entries.append({"selector": selector_value(spec)})
        else:
            entries.append({"literal": _on_base(doc, spec, entity_type, base, before)})
    return entries


def handle(core, doc, req):
    from .core import OperationError, number
    op = req["op"]
    if op == "project_geometry":
        from .sketch_tools import project_geometry
        return project_geometry(core, doc, req)
    if op == "edit_dress_up":
        return edit_dress_up(core, doc, req)
    if op == "hole":
        return hole_tools.handle(core, doc, req)

    body_request = dict(req)
    if "part" in req:
        body_request["body"] = req["part"]
    body = core._body(doc, body_request)
    tip = body.Tip
    if tip is None or tip.Shape.isNull() or not tip.Shape.Solids:
        raise OperationError("missing_body", "Choose a current solid part")
    field, entity_type = ("faces", "face") if op == "shell" else ("edges", "edge")
    specs, multi = (req.get(field), False) if op == "shell" else _edge_specs(req.get(field))
    if multi:
        entries, refs = _group_entries(doc, specs, entity_type, tip), None
    else:
        refs = _references(doc, specs, entity_type, tip)
    type_id = {"fillet": "PartDesign::Fillet", "chamfer": "PartDesign::Chamfer", "shell": "PartDesign::Thickness"}[op]
    feature = body.newObject(type_id, core._id(doc, req, {"fillet": "Fillet", "chamfer": "Chamfer", "shell": "Shell"}[op]))
    if multi:
        selectors.bind_group(feature, field, entries, tip, native_property="Base", entity_type=entity_type)
    else:
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
    for index, spec in enumerate(specs):
        if not multi and is_selector(spec):
            selectors.bind(feature, field + "_" + str(index), selector_value(spec),
                           native_property="Base", mode="linksub_index", index=index)
    core._recompute(doc)
    if feature.Shape.isNull() or len(feature.Shape.Solids) != 1 or {"Invalid", "Error"} & set(feature.State):
        raise OperationError("build_failed", "Native feature could not create one valid solid", feature=feature.Name)
    if op != "shell":
        _require_plausible_volume(feature, tip.Shape,
                                  list(feature.Base[1]) if multi else [reference["subelement"] for reference in refs],
                                  feature.Radius.Value if op == "fillet" else feature.Size.Value, op,
                                  "radius" if op == "fillet" else "size")
    body.Tip = feature
    return feature.Name


# A rolling-ball fillet or equal chamfer of size s adds or removes at most
# s^2 * cot(theta/2) of section per unit edge length; 20 covers dihedral
# angles down to about 6 degrees.
DRESS_UP_SECTION_LIMIT = 20.0


def _require_plausible_volume(feature, base_shape, edges, size, kind, key):
    """Dress-up kernels can report success with a self-intersecting solid.

    A native R3 fillet fading into a near-tangent crease returned one solid,
    state Valid, 28,000 mm3 larger than its 66,000 mm3 input. BRepCheck stays
    an explicit request (interactive paths never run it), so reject that
    gross failure from volumes alone.
    """
    from .core import OperationError
    length = 0.0
    for element in edges:
        try:
            length += base_shape.getElement(element).Length
        except Exception:
            continue
    before, after = base_shape.Volume, feature.Shape.Volume
    limit = DRESS_UP_SECTION_LIMIT * size * size * length + 1e-6 * abs(before)
    if after <= 0 or abs(after - before) > limit:
        raise OperationError("invalid_geometry", f"The {kind} produced an implausible solid (volume changed by "
                             f"{after - before:.6g} mm3 for {length:.6g} mm of edges); the kernel result is likely "
                             f"self-intersecting. Try a different {key}, fewer edges or another order",
                             feature=feature.Name, volume_change_mm3=after - before, limit_mm3=limit)


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


def _group_reference(base, info, element):
    if info.get("literal"):
        return {"feature": base.Name, "subelement": element}
    if info.get("many"):
        return {"selector": info["selector"], "all": True}
    return {"selector": info["selector"]}


def _group_rows(feature, base, members):
    """Edge rows of a multi-reference feature (selectors.GROUP_MODE).

    One row per Base slot, with the reference of the entry that owns it, and
    one row with ``subelement`` None for each entry that owns no slot because
    earlier entries already include its edges, placed at its entry position.
    Sending the distinct references back in row order reproduces the
    authored list, so such an entry is not lost by an edit. A literal whose
    edge no longer exists is left out (never sent back as a stale index) and
    reported in ``notes``.
    """
    names = list(feature.Base[1])
    health = selectors._health(feature)
    layout_intact = len(names) == sum(len(info.get("slots", [])) for _, info in members)
    owners = {slot: (member, info) for member, info in members for slot in info.get("slots", [])}
    pending, last, notes = {}, -1, []
    for member, info in members:
        if info.get("slots"):
            last = max(last, max(info["slots"]))
            continue
        if info.get("literal"):
            element = selectors.literal_element(base, info, names, layout_intact)
            if element is None:
                notes.append("A picked edge (" + info["selector"]["subelement"] + ") no longer exists on "
                             + base.Label + "; it is left out of the edge list, pick it again to keep it")
                continue
            label = base.Label + " · " + element + " (also included by an earlier reference)"
        else:
            element = None
            label = base.Label + (" · every match of a query" if info.get("many") else " · query") \
                + " (its edges are already included by an earlier reference)"
        pending.setdefault(last, []).append(
            {"reference": _group_reference(base, info, element), "subelement": None, "label": label})
    edges = list(pending.pop(-1, []))
    for index, element in enumerate(names):
        member, info = owners.get(index, (None, None))
        label = base.Label + " · " + element
        if info is None:
            reference = {"feature": base.Name, "subelement": element}
        else:
            reference = _group_reference(base, info, element)
            if info.get("many"):
                label += " (one of %d query matches)" % health.get(member, {}).get("count", len(info["slots"]))
        edges.append({"reference": reference, "subelement": element, "label": label})
        edges.extend(pending.pop(index, []))
    for index in sorted(pending):
        edges.extend(pending[index])
    return edges, notes


def describe_dress_up(doc, name):
    """Current native settings and selected edges of a Fillet/Chamfer.

    Edges are subelements of the feature's own input (its Base), so edges
    the completed feature rounded away stay selectable while editing. A bound
    selector is returned as the reference so an untouched edge stays
    associative when it is sent back. A row whose ``subelement`` is None is
    a multi-reference entry whose edges earlier entries already include.
    """
    feature, base = _dress_up(doc, name)
    kind, prop, key = DRESS_UP[feature.TypeId]
    inputs = _edge_inputs(feature)
    members = selectors._group_members(inputs, "Base")
    limitations = []
    if members:
        edges, limitations = _group_rows(feature, base, members)
    else:
        edges = []
        for index, element in enumerate(feature.Base[1]):
            bound = inputs.get("edges_" + str(index))
            reference = ({"selector": bound["selector"]} if bound else {"feature": base.Name, "subelement": element})
            edges.append({"reference": reference, "subelement": element, "label": base.Label + " · " + element})
    expression = next((value for path, value in feature.ExpressionEngine if path.lstrip(".") == prop), None)
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
        specs, multi = _edge_specs(specs)
        if multi:
            entries = _group_entries(doc, specs, "edge", base, before=feature)
            _forget_edge_inputs(feature)
            selectors.bind_group(feature, "edges", entries, base, native_property="Base", entity_type="edge")
        else:
            # Resolve against history before this feature: its input shape.
            refs = _references(doc, specs, "edge", base, before=feature)
            _forget_edge_inputs(feature)
            feature.Base = (base, [reference["subelement"] for reference in refs])
        for index, spec in enumerate(specs):
            if not multi and is_selector(spec):
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
    _require_plausible_volume(feature, base.Shape, list(feature.Base[1]), getattr(feature, prop).Value, kind, key)
    return None
