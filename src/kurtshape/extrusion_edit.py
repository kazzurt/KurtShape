"""Reopen and edit existing Extrude/Remove features from authoritative native state.

``KurtShapeStudioOperation`` text records the original creation request. It is
used only to identify the feature family; current depth, formula, direction
and end condition are always read from native properties. Edits change those
properties in place, so feature identity and downstream references survive.
"""
from __future__ import annotations

import json
import re

import FreeCAD as App

EXPRESSION_PATTERN = r"[A-Za-z0-9_ .+*/()\[\]-]+"
END_TYPES = ("blind", "through_all", "up_to_face")
_NATIVE_END = {"Length": "blind", "ThroughAll": "through_all", "UpToFace": "up_to_face"}


def _error(code, message, **details):
    from .core import OperationError
    return OperationError(code, message, **details)


def _expression(obj, prop):
    return next((value for path, value in obj.ExpressionEngine if path.lstrip(".") == prop), None)


def _label(obj):
    return obj.Label if obj is not None else None


def _wire_endpoints(wire):
    """Vertices used by exactly one edge, by topological identity (no rounding)."""
    uses = []
    for edge in wire.Edges:
        for vertex in edge.Vertexes:
            match = next((entry for entry in uses if entry[0].isSame(vertex)), None)
            if match is None:
                uses.append([vertex, 1])
            else:
                match[1] += 1
    ends = [vertex for vertex, count in uses if count == 1]
    if not ends:
        ordered = wire.OrderedVertexes
        ends = [ordered[0], ordered[-1]] if len(ordered) > 1 else []
    return ends


def profile_gaps(profile):
    """Free endpoints of open wires in a sketch's non-construction geometry.

    Coordinates are sketch-local millimetres: the sketch Shape carries the
    sketch Placement inside its Body, so only that placement is removed.
    An empty list means every wire closes; it does not prove the native face
    maker accepts the profile.
    """
    shape = getattr(profile, "Shape", None)
    if shape is None or shape.isNull():
        return []
    inverse = shape.Placement.inverse()
    gaps = []
    for index, wire in enumerate(shape.Wires):
        if wire.isClosed():
            continue
        for vertex in _wire_endpoints(wire):
            local = inverse.multVec(vertex.Point)
            gaps.append({"wire": index, "point_mm": [round(local.x, 9), round(local.y, 9)]})
    return gaps


def open_profile_error(profile, prefix="Profile is open"):
    """Actionable open-profile error, or None only when every wire is closed."""
    shape = getattr(profile, "Shape", None)
    open_wires = [wire for wire in shape.Wires if not wire.isClosed()] if shape is not None and not shape.isNull() else []
    if not open_wires:
        return None
    gaps = profile_gaps(profile)
    if not gaps:
        return _error("open_profile", f"{prefix}: {len(open_wires)} open curve chain(s) in {profile.Label}. "
                      "Close the gaps or mark the open curves as construction.",
                      profile=profile.Name, open_endpoints=[])
    points = "; ".join("({:.6g}, {:.6g})".format(*gap["point_mm"]) for gap in gaps[:4])
    more = f" and {len(gaps) - 4} more" if len(gaps) > 4 else ""
    return _error("open_profile", f"{prefix}: {len(gaps)} free endpoint(s) in {profile.Label} at {points}{more} mm "
                  "(sketch coordinates). Close the gaps or mark the open curves as construction.",
                  profile=profile.Name, open_endpoints=gaps)


def _studio_parts(doc, obj):
    """Return (creation intent, native extrusion tool) for a studio Extrude/Remove."""
    text = getattr(obj, "KurtShapeStudioOperation", "")
    if not text:
        return None
    intent = json.loads(text)
    if intent.get("op") not in {"pad", "pocket"}:
        return None
    tool = getattr(obj, "KurtShapeTool", None) or obj
    if tool.TypeId not in {"Part::Extrusion", "PartDesign::Pad"}:
        return None
    return intent, tool


def describe(doc, feature):
    """Current editable settings; raises unsupported_feature outside this dialog's scope."""
    obj = doc.getObject(feature) if isinstance(feature, str) else None
    if obj is None:
        raise _error("missing_reference", "Feature ID does not exist")
    limitations = []
    if obj.TypeId in {"PartDesign::Pad", "PartDesign::Pocket"} and not getattr(obj, "KurtShapeStudioOperation", ""):
        native_type = str(obj.Type)
        end_type = _NATIVE_END.get(native_type)
        kind = "remove" if obj.TypeId == "PartDesign::Pocket" else "extrude"
        if end_type is None or kind == "extrude" and end_type == "through_all":
            raise _error("unsupported_feature", f"The {native_type} end condition is not editable in this dialog",
                         end_condition=native_type)
        end_types = [end_type]
        if kind == "remove" and end_type in {"blind", "through_all"}:
            end_types = ["blind", "through_all"]
        if _expression(obj, "Type"):
            end_types = [end_type]
            limitations.append("End condition is driven by a formula")
        elif len(end_types) == 1:
            limitations.append("Changing this end condition is not supported yet")
        profile = obj.Profile[0] if obj.Profile else None
        stop = obj.UpToFace[0] if end_type == "up_to_face" and obj.UpToFace else None
        reverse_reason = None
        if getattr(obj, "Midplane", False):
            reverse_reason = "Symmetric extrusion has no single direction"
        elif _expression(obj, "Reversed"):
            reverse_reason = "Direction is driven by a formula"
        # Native Pad extends along the sketch normal; native Pocket cuts against it.
        along = bool(obj.Reversed) if kind == "remove" else not obj.Reversed
        return {"feature": obj.Name, "label": obj.Label, "family": "partdesign", "kind": kind,
                "operation": "remove" if kind == "remove" else "add",
                "profile": {"id": profile.Name if profile else None, "label": _label(profile), "face": False},
                "end_type": end_type, "end_types": end_types, "end_face": _label(stop),
                "length": {"value": float(obj.Length.Value), "expression": _expression(obj, "Length"),
                           "native_feature": obj.Name, "native_property": "Length"},
                "reversed": bool(obj.Reversed), "reverse_editable": reverse_reason is None,
                "reverse_reason": reverse_reason, "_display_default": False,
                "direction": "both" if getattr(obj, "Midplane", False) else _signed_direction(
                    "along" if along else "against", obj.Length.Value, limitations),
                "direction_reference": "sketch normal", "limitations": limitations}
    parts = _studio_parts(doc, obj)
    if parts is None:
        raise _error("unsupported_feature", "Only Extrude and Remove features open in this dialog")
    intent, tool = parts
    operation = intent.get("operation", "remove" if intent["op"] == "pocket" else "new")
    kind = "remove" if intent["op"] == "pocket" or operation in {"remove", "intersect"} else "extrude"
    face_mode = "face" in intent
    if tool.TypeId == "PartDesign::Pad":
        if str(tool.Type) != "UpToFace":
            raise _error("unsupported_feature", "This extrusion tool is not editable in this dialog")
        end_type, display_default = "up_to_face", False
        # The carrier's stop binder wraps the user's chosen face.
        stop = tool.UpToFace[0] if tool.UpToFace else None
        support = getattr(stop, "Support", None)
        stop_label = _label(support[0][0] if support else stop)
        length = {"value": None, "expression": None, "native_feature": tool.Name, "native_property": None}
    else:
        # A two-sided native extrusion is the studio Through all; its lengths
        # are computed scope bounds, never the user's depth.
        two_sided = float(tool.LengthRev.Value) > 1e-9 or _expression(tool, "LengthRev") is not None
        end_type = "through_all" if two_sided else "blind"
        # Studio sketch Remove defaults to Reversed (into the material); face
        # tools and Extrude record the GUI checkbox directly.
        display_default = intent["op"] == "pocket" and not face_mode
        stop_label = None
        length = {"value": float(tool.LengthFwd.Value), "expression": _expression(tool, "LengthFwd"),
                  "native_feature": tool.Name, "native_property": "LengthFwd"}
    profile_id = intent.get("profile")
    profile = doc.getObject(profile_id) if isinstance(profile_id, str) else None
    reverse_reason = None
    if end_type == "through_all":
        reverse_reason = "Through all extends in both directions"
    elif _expression(tool, "Reversed"):
        reverse_reason = "Direction is driven by a formula"
    limitations.append("Changing the end condition of a part studio feature is not supported yet")
    return {"feature": obj.Name, "label": obj.Label, "family": "studio", "kind": kind, "operation": operation,
            "profile": {"id": profile.Name if profile else None,
                        "label": "Selected face" if face_mode else _label(profile), "face": face_mode},
            "end_type": end_type, "end_types": [end_type], "end_face": stop_label, "length": length,
            "reversed": end_type != "through_all" and bool(tool.Reversed) != display_default,
            "reverse_editable": reverse_reason is None,
            "reverse_reason": reverse_reason, "_display_default": display_default,
            "direction": "both" if end_type == "through_all" else _signed_direction(
                "against" if tool.Reversed else "along", length["value"], limitations),
            "direction_reference": "face normal" if face_mode else "sketch normal", "limitations": limitations}


def _signed_direction(direction, depth, limitations):
    """A formula can evaluate negative; the solid then extends the other way."""
    if depth is not None and depth < 0:
        limitations.append("The depth formula evaluates negative, so the feature extends opposite its direction setting")
        return "against" if direction == "along" else "along"
    return direction


def public(info):
    return {key: value for key, value in info.items() if not key.startswith("_")}


def direction_after(info, reversed_value):
    """Physical direction after toggling the dialog's Reverse checkbox."""
    if info["direction"] == "both":
        return "both"
    if bool(reversed_value) == info["reversed"]:
        return info["direction"]
    return "against" if info["direction"] == "along" else "along"


def _failed(obj):
    return bool({"Invalid", "Error"} & set(obj.State))


def apply(core, doc, req):
    """Change native properties in the caller's transaction; validation raises."""
    from .core import number
    info = describe(doc, req.get("feature"))
    obj = doc.getObject(info["feature"])
    target = doc.getObject(info["length"]["native_feature"])
    prop = info["length"]["native_property"]
    end_type = req.get("end_type", info["end_type"])
    if end_type not in END_TYPES:
        raise _error("invalid_argument", "end_type must be blind, through_all or up_to_face")
    if end_type != info["end_type"]:
        if end_type not in info["end_types"]:
            raise _error("unsupported_transition",
                         f"Changing {info['label']} from {info['end_type'].replace('_', ' ')} to "
                         f"{end_type.replace('_', ' ')} is not supported yet; its current end condition is unchanged",
                         supported=info["end_types"])
        obj.Type = "Length" if end_type == "blind" else "ThroughAll"
    if "expression" in req and "length" in req and req["expression"] is not None:
        raise _error("invalid_argument", "Provide either a depth or a depth formula")
    if ("expression" in req or "length" in req) and end_type != "blind":
        raise _error("invalid_argument", "Depth applies only to a Blind end condition")
    if "expression" in req:
        expression = req["expression"]
        if expression is not None and (not isinstance(expression, str) or len(expression) > 512
                                       or not re.fullmatch(EXPRESSION_PATTERN, expression)):
            raise _error("invalid_argument", "Use a dimensional formula with named properties and arithmetic")
        target.setExpression(prop, expression)
    if "length" in req:
        current = _expression(target, prop)
        if current is not None:
            raise _error("expression_driven", "Depth is driven by the formula " + current
                         + "; edit or clear the formula instead", expression=current)
        setattr(target, prop, number(req["length"], "length", True))
    if "reversed" in req:
        if not isinstance(req["reversed"], bool):
            raise _error("invalid_argument", "reversed must be boolean")
        if req["reversed"] != info["reversed"]:
            if not info["reverse_editable"]:
                raise _error("unsupported_parameter", info["reverse_reason"])
            target_obj = doc.getObject(info["length"]["native_feature"])
            target_obj.Reversed = req["reversed"] != info["_display_default"]
    core._recompute(doc)
    if "expression" in req and req["expression"] is not None and _failed(target):
        raise _error("invalid_expression", "Formula is invalid, has a missing reference, or has incompatible units",
                     status=target.getStatusString())
    for item in {obj, target}:
        if _failed(item):
            profile = doc.getObject(info["profile"]["id"] or "")
            gap = open_profile_error(profile) if profile is not None else None
            if gap is not None:
                raise gap
            raise _error("build_failed", "The edited feature could not rebuild: " + item.getStatusString(),
                         feature=item.Name)
    if info["family"] == "partdesign":
        base = obj.BaseFeature
        if info["kind"] == "remove" and base is not None and not base.Shape.isNull():
            if obj.Shape.isNull() or obj.Shape.Volume >= base.Shape.Volume - 1e-7:
                raise _error("empty_cut", "Remove material removes no material in the requested direction")
        return None
    # Validate this operation's recorded output tips. Its output Bodies can be
    # legitimately empty when later history consumed them: studio rollback
    # moves their Tips, so a Body shape is not this feature's result.
    outputs = [doc.getObject(name) for name in getattr(obj, "KurtShapeOutputTips", [])]
    for tip in outputs:
        if tip is None or tip.Shape.isNull() or len(tip.Shape.Solids) != 1 or _failed(tip):
            raise _error("build_failed", "Each part result must be one valid solid",
                         feature=getattr(tip, "Name", None))
    if info["operation"] == "remove":
        sources = list(getattr(obj, "KurtShapeInputSnapshots", []))
        if sources and not any(result.Shape.Volume < source.Shape.Volume - 1e-7
                               for result, source in zip(outputs, sources)):
            raise _error("empty_cut", "Remove did not remove material from the selected scope")
    return None


def step_shape(doc, feature):
    """World geometry produced by this feature at its own history position."""
    from .extrusion_preview import _world_shape
    import Part
    obj = doc.getObject(feature)
    if obj is None:
        return Part.Shape()
    if not getattr(obj, "KurtShapeStudioOperation", ""):
        return _world_shape(obj) if not obj.Shape.isNull() else Part.Shape()
    # Recorded output tips stay bound to this operation even when a later
    # rollback or native consumer moves its output Body's Tip.
    shapes = []
    for name in getattr(obj, "KurtShapeOutputTips", []):
        tip = doc.getObject(name)
        if tip is not None and not tip.Shape.isNull():
            shapes.append(_world_shape(tip))
    return Part.makeCompound(shapes) if shapes else Part.Shape()


def change_material(before, after):
    """Symmetric volume change between two step shapes, or None when unchanged."""
    if before.isNull() or after.isNull():
        return None
    try:
        changed = after.cut(before).fuse(before.cut(after))
    except Exception:
        return None
    if changed.isNull() or not changed.Solids or changed.Volume <= 1e-7:
        return None
    return changed
