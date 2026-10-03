"""Native multi-part studio operations and persisted feature ordering.

The model remains a FreeCAD dependency graph. Native Bodies carry logical part
identity; neutral Part tools and native PartDesign Booleans carry geometry.
The properties below describe operation order, not a second editable graph.
"""
from __future__ import annotations
import json
import math

import FreeCAD as App
import Part

OPS = {"revolve", "sweep", "loft", "boolean_parts", "split_part",
       "transform_part", "delete_part", "linear_pattern_parts", "circular_pattern_parts",
       "mirror_parts", "rollback", "set_part_appearance"}
RESULT_FIELDS = {"operation", "merge_scope", "name"}
ARGS = {
    "pad": RESULT_FIELDS, "pocket": RESULT_FIELDS,
    "revolve": {"id", "name", "profile", "axis", "angle", "operation", "merge_scope", "body"},
    "sweep": {"id", "name", "profile", "path", "operation", "merge_scope", "body", "frenet"},
    "loft": {"id", "name", "sections", "operation", "merge_scope", "body", "ruled", "closed"},
    "boolean_parts": {"id", "name", "targets", "tools", "kind", "keep_tools"},
    "split_part": {"id", "name", "part", "plane", "face", "sketch"},
    "transform_part": {"id", "name", "part", "translation", "rotation", "coordinate_system", "copy"},
    "delete_part": {"id", "name", "part"},
    "linear_pattern_parts": {"id", "name", "parts", "direction", "spacing", "count", "operation", "merge_scope"},
    "circular_pattern_parts": {"id", "name", "parts", "axis", "angle", "count", "operation", "merge_scope"},
    "mirror_parts": {"id", "name", "parts", "origin", "normal", "operation", "merge_scope"},
    "rollback": {"index"},
    "set_part_appearance": {"part", "name", "visible", "color"},
}
META = "KurtShapeProject"
_AUTO_SCOPE_CACHE = {}


def native_recomputed(doc):
    """Cheap invalidation only; no kernel evaluation on observer/idle paths."""
    _AUTO_SCOPE_CACHE.pop(doc.Name, None)


def _error(code, message, **details):
    from .core import OperationError
    return OperationError(code, message, **details)


def _number(value, name, positive=False, unit="mm"):
    from .core import number
    return number(value, name, positive, unit)


def _vector(value, name, default=None, direction=False):
    value = default if value is None else value
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise _error("invalid_argument", name + " requires three coordinates")
    result = App.Vector(*[_number(x, name) for x in value])
    if direction:
        if result.Length < 1e-10:
            raise _error("invalid_argument", name + " must be a nonzero direction")
        result.normalize()
    return result


def _bool(req, name, default=False):
    value = req.get(name, default)
    if not isinstance(value, bool):
        raise _error("invalid_argument", name + " must be boolean")
    return value


def _prop(obj, kind, name, value=None):
    if name not in obj.PropertiesList:
        obj.addProperty(kind, name, "KurtShape studio")
    if value is not None and getattr(obj, name) != value:
        setattr(obj, name, value)


def enabled(doc):
    meta = doc.getObject(META)
    return bool(meta and getattr(meta, "KurtShapeStudioEnabled", False))


def _meta(doc, create=False):
    meta = doc.getObject(META)
    if create:
        from .core import metadata
        meta = metadata(doc)
        _prop(meta, "App::PropertyBool", "KurtShapeStudioEnabled", True)
        _prop(meta, "App::PropertyLinkList", "KurtShapeFeatureOrder")
        _prop(meta, "App::PropertyInteger", "KurtShapeRollbackIndex")
        # Unhashed native names retain all composite merge ancestors.
        doc.UseHasher = False
    return meta


def _body_owner(obj):
    if obj.TypeId == "PartDesign::Body":
        return obj
    from .bodies import owner
    return owner(obj.Document, obj)


def part_id(obj):
    body = _body_owner(obj)
    return getattr(body, "KurtShapePartId", body.Name) if body else getattr(obj, "KurtShapePartId", obj.Name)


def _eligible(obj):
    base_owner = _body_owner(obj) if obj.TypeId == "PartDesign::FeatureBase" else None
    adopted_base = bool(base_owner and not getattr(base_owner, "KurtShapeInternal", False)
                        and not getattr(base_owner, "KurtShapeOutputGeneration", False))
    return (obj.TypeId == "Sketcher::SketchObject" or
            obj.TypeId.startswith("PartDesign::") and obj.TypeId not in
            {"PartDesign::Body", "PartDesign::FeatureBase", "PartDesign::SubShapeBinder"} or
            bool(getattr(obj, "KurtShapeStudioOperation", "")) or adopted_base) and not getattr(obj, "KurtShapeInternal", False)


def order(doc):
    if enabled(doc):
        return list(_meta(doc).KurtShapeFeatureOrder)
    return [obj for obj in doc.Objects if _eligible(obj)]


def reconcile(doc):
    if not enabled(doc):
        return
    meta = _meta(doc)
    prior = list(meta.KurtShapeFeatureOrder)
    discovered = [obj for obj in doc.Objects if _eligible(obj) and obj not in prior]
    bar = min(max(0, meta.KurtShapeRollbackIndex), len(prior))
    if discovered:
        meta.KurtShapeFeatureOrder = prior[:bar] + discovered + prior[bar:]
        meta.KurtShapeRollbackIndex = bar + len(discovered)
    for obj in doc.Objects:
        if obj.TypeId == "PartDesign::Body" and not getattr(obj, "KurtShapeInternal", False):
            _prop(obj, "App::PropertyString", "KurtShapePartId", getattr(obj, "KurtShapePartId", obj.Name))


def _enable(doc):
    if not enabled(doc):
        initial = order(doc)
        meta = _meta(doc, True)
        meta.KurtShapeFeatureOrder = initial
        meta.KurtShapeRollbackIndex = len(initial)
        reconcile(doc)
    return _meta(doc)


def _cutoff(doc, before=None):
    features = order(doc)
    if before is not None:
        name = before.Name if hasattr(before, "Name") else before
        index = next((i for i, obj in enumerate(features) if obj.Name == name), None)
        if index is not None:
            return index
        # Auxiliary consumer belongs to its operation or the native Body order.
        operation = getattr(doc.getObject(name), "KurtShapeOperationOwner", "")
        index = next((i for i, obj in enumerate(features) if obj.Name == operation), None)
        if index is not None:
            return index
    return min(max(0, _meta(doc).KurtShapeRollbackIndex), len(features)) if enabled(doc) else len(features)


def _state(doc, cutoff):
    """Read current logical parts directly from native ordered operation metadata."""
    state = {}
    for obj in order(doc)[:cutoff]:
        if getattr(obj, "KurtShapeStudioOperation", ""):
            for key in getattr(obj, "KurtShapeConsumedParts", []):
                state.pop(key, None)
            names = list(getattr(obj, "KurtShapeOutputParts", []))
            tips = list(getattr(obj, "KurtShapeOutputTips", []))
            for index, name in enumerate(names):
                body = doc.getObject(name)
                if body:
                    tip = doc.getObject(tips[index]) if index < len(tips) else body.Tip
                    state[part_id(body)] = (body, tip)
        elif hasattr(obj, "Shape") and obj.TypeId.startswith("PartDesign::"):
            body = _body_owner(obj)
            if body and not getattr(body, "KurtShapeInternal", False) and not obj.Shape.isNull() and obj.Shape.Solids:
                state[part_id(body)] = (body, obj)
    return state


def current_parts(doc, before=None):
    if not enabled(doc):
        from .bodies import bodies
        return bodies(doc)
    return [entry[0] for entry in _state(doc, _cutoff(doc, before)).values()]


def current_part(doc, part, before=None):
    candidates = current_parts(doc, before)
    match = [obj for obj in candidates if part in {obj.Name, part_id(obj)}]
    if len(match) != 1:
        raise _error("missing_part", "Choose a current part ID", part=part)
    return match[0]


def current_body(doc, part, before=None):
    try:
        return current_part(doc, part, before)
    except Exception:
        obj = doc.getObject(part) if isinstance(part, str) else None
        if (obj and obj.TypeId == "PartDesign::Body" and not getattr(obj, "KurtShapeInternal", False)
                and not getattr(obj, "KurtShapeOutputGeneration", False) and obj.Shape.isNull()):
            return obj
        raise


def results(doc, before=None):
    if not enabled(doc):
        return None
    entries = _state(doc, _cutoff(doc, before)).values()
    # Historical consumers must not reference their final containing Body.
    return [entry[1] if before is not None else entry[0] for entry in entries]


def is_active(obj):
    doc = obj.Document
    if not enabled(doc):
        return True
    body_owner = _body_owner(obj)
    if getattr(obj, "KurtShapeObsolete", False) or body_owner and getattr(body_owner, "KurtShapeObsolete", False):
        return False
    op = getattr(obj, "KurtShapeOperationOwner", "")
    target = doc.getObject(op) if op else obj
    if target in order(doc):
        return order(doc).index(target) < _cutoff(doc)
    if obj.TypeId == "PartDesign::Body" and not getattr(obj, "KurtShapeInternal", False):
        return any(entry[0] == obj for entry in _state(doc, _cutoff(doc)).values())
    return True


def _snapshot(doc, body, feature, name):
    snap = doc.addObject("PartDesign::Body", name)
    _prop(snap, "App::PropertyBool", "KurtShapeInternal", True)
    binder = doc.addObject("PartDesign::ShapeBinder", name + "Source")
    binder.Support = [(feature, [""])]
    binder.TraceSupport = True
    _prop(binder, "App::PropertyBool", "KurtShapeInternal", True)
    # The traced binder supplies pose only. Its copied Shape has no native
    # element map; geometry must come directly from the authoritative Tip.
    snap.BaseFeature = feature
    snap.setExpression("Placement", binder.Name + ".Placement")
    _prop(snap, "App::PropertyLink", "KurtShapeInputBinder", binder)
    if App.GuiUp:
        snap.ViewObject.Visibility = False
    return snap


def _output(doc, source, name, key=None, label=None):
    previous = next((obj for obj in current_parts(doc) if part_id(obj) == key), None) if key else None
    body = doc.addObject("PartDesign::Body", name)
    body.BaseFeature = source
    body.setExpression("Placement", source.Name + ".Placement")
    _prop(body, "App::PropertyString", "KurtShapePartId", key or body.Name)
    _prop(body, "App::PropertyBool", "KurtShapeOutputGeneration", True)
    if label:
        body.Label = label
        _prop(body, "App::PropertyString", "KurtShapePartName", label)
    if previous:
        for kind, prop in [("App::PropertyBool", "KurtShapePartVisible"), ("App::PropertyColor", "KurtShapePartColor")]:
            if prop in previous.PropertiesList:
                _prop(body, kind, prop, getattr(previous, prop))
        if App.GuiUp and "KurtShapePartColor" in body.PropertiesList:
            body.ViewObject.ShapeColor = tuple(body.KurtShapePartColor[:3])
    return body


def _validate(doc, objects):
    doc.recompute()
    for obj in objects:
        if obj.Shape.isNull() or not obj.Shape.isValid() or len(obj.Shape.Solids) != 1:
            raise _error("build_failed", "Each part result must be one valid solid", feature=obj.Name,
                         status=obj.getStatusString())


def _record(doc, representative, req, outputs, consumed=(), snapshots=()):
    meta = _enable(doc)
    _prop(representative, "App::PropertyString", "KurtShapeStudioOperation", json.dumps(req, sort_keys=True))
    _prop(representative, "App::PropertyBool", "KurtShapeInternal", False)
    # Linking an operation to its containing output Body creates a native
    # dependency cycle. Persist result names as descriptive native metadata.
    _prop(representative, "App::PropertyStringList", "KurtShapeOutputParts", [obj.Name for obj in outputs])
    _prop(representative, "App::PropertyStringList", "KurtShapeOutputTips", [obj.Tip.Name for obj in outputs])
    _prop(representative, "App::PropertyStringList", "KurtShapeConsumedParts", list(consumed))
    _prop(representative, "App::PropertyLinkList", "KurtShapeInputSnapshots", [x[1] for x in snapshots])
    _prop(representative, "App::PropertyStringList", "KurtShapeInputPartIds", [x[0] for x in snapshots])
    all_existing = set(order(doc))
    # Established source containers remain inputs when traversing auxiliaries.
    all_existing.update(body for body in (_body_owner(obj) for obj in order(doc)) if body)
    for body in outputs:
        _prop(body, "App::PropertyString", "KurtShapeOperationOwner", representative.Name)
    for key, body in snapshots:
        _prop(body, "App::PropertyString", "KurtShapeOperationOwner", representative.Name)
    # Mark all auxiliaries created by this operation through their native closure.
    seen = set()
    def visit(obj):
        if obj in seen or obj in all_existing:
            return
        seen.add(obj)
        if obj != representative and obj not in outputs:
            _prop(obj, "App::PropertyBool", "KurtShapeInternal", True)
            _prop(obj, "App::PropertyString", "KurtShapeOperationOwner", representative.Name)
        for child in getattr(obj, "OutList", []):
            if child.TypeId.startswith(("PartDesign::", "Part::", "App::Link")) and child not in all_existing:
                visit(child)
    # Output closures include native inputs; only objects explicitly created as
    # outputs/snapshots are traversed, and established order features are guarded.
    for body in outputs + [x[1] for x in snapshots]:
        visit(body)
    sequence = list(meta.KurtShapeFeatureOrder)
    bar = _cutoff(doc)
    if representative not in sequence:
        sequence.insert(bar, representative)
        meta.KurtShapeFeatureOrder = sequence
        meta.KurtShapeRollbackIndex = bar + 1
    return representative.Name


def prepare_recompute(doc):
    if not enabled(doc):
        return
    native_recomputed(doc)
    features = order(doc)
    bar = _cutoff(doc)
    # Rebind only native inputs already recorded with explicit logical part IDs.
    for index, obj in enumerate(features):
        if not getattr(obj, "KurtShapeStudioOperation", ""):
            continue
        available = _state(doc, index)
        for key, snapshot in zip(obj.KurtShapeInputPartIds, obj.KurtShapeInputSnapshots):
            entry = available.get(key)
            if entry:
                body, tip = entry
                if "KurtShapeInputBinder" in snapshot.PropertiesList:
                    binder = snapshot.KurtShapeInputBinder
                    if snapshot.BaseFeature != tip:
                        snapshot.BaseFeature = tip
                    if binder.Support != [(tip, ("",))] and binder.Support != [(tip, [""])]:
                        binder.Support = [(tip, [""])]
                else:
                    if snapshot.BaseFeature != tip:
                        snapshot.BaseFeature = tip
                    if snapshot.Placement != body.Placement:
                        snapshot.Placement = body.Placement
    visible_state = _state(doc, bar)
    for body in [obj for obj in doc.Objects if obj.TypeId == "PartDesign::Body"]:
        selected_tip = next((entry[1] for entry in visible_state.values() if entry[0] == body), None)
        if selected_tip and body.Tip != selected_tip:
            body.Tip = selected_tip
        elif not selected_tip and not getattr(body, "KurtShapeInternal", False):
            own_active = [obj for obj in features[:bar] if _body_owner(obj) == body and obj.TypeId.startswith("PartDesign::")]
            tip = own_active[-1] if own_active else None
            if body.Tip != tip:
                body.Tip = tip
        if App.GuiUp:
            active = any(entry[0] == body for entry in visible_state.values())
            desired = getattr(body, "KurtShapePartVisible", True)
            body.ViewObject.Visibility = bool(active and desired and not getattr(body, "KurtShapeInternal", False))
    hide_internal(doc)


def hide_internal(doc):
    if App.GuiUp:
        for obj in doc.Objects:
            neutral_result = obj.TypeId.startswith("Part::") and bool(getattr(obj, "KurtShapeStudioOperation", ""))
            if (getattr(obj, "KurtShapeInternal", False) or neutral_result) and hasattr(obj, "ViewObject"):
                obj.ViewObject.Visibility = False
        # A Body draws its current native Tip through that child's view provider.
        # Generated FeatureBase/Boolean tips are bookkeeping auxiliaries, but
        # must be visible when their logical output part is visible.
        if not enabled(doc):
            return
        for body in current_parts(doc) or []:
            visible = bool(getattr(body, "KurtShapePartVisible", True))
            body.ViewObject.Visibility = visible
            if body.Tip:
                body.Tip.ViewObject.Visibility = visible


def validation_errors(doc):
    if not enabled(doc):
        return []
    errors = []
    for index, obj in enumerate(order(doc)[:_cutoff(doc)]):
        if not getattr(obj, "KurtShapeStudioOperation", ""):
            continue
        available = _state(doc, index)
        for key in getattr(obj, "KurtShapeInputPartIds", []):
            if key not in available:
                errors.append({"feature": obj.Name, "part": key, "message": "Part input is missing at this history position"})
    if doc.Name not in _AUTO_SCOPE_CACHE:
        scope_errors = []
        for index, obj in enumerate(order(doc)[:_cutoff(doc)]):
            request_text = getattr(obj, "KurtShapeStudioOperation", "")
            if not request_text:
                continue
            request = json.loads(request_text)
            operation = request.get("operation", "remove" if request["op"] == "pocket" else "new")
            if operation == "new" or request.get("merge_scope", "auto") != "auto" or "KurtShapeMergePartIds" not in obj.PropertiesList:
                continue
            if "KurtShapeTool" in obj.PropertiesList:
                tool_shapes = [obj.KurtShapeTool.Shape]
            else:
                tool_shapes = [doc.getObject(name).Shape for name in getattr(obj, "KurtShapePatternToolParts", []) if doc.getObject(name)]
            if not tool_shapes or any(shape.isNull() for shape in tool_shapes):
                continue
            desired = []
            for key, (body, tip) in _state(doc, index).items():
                shape = tip.Shape.copy()
                shape.Placement = body.Placement * shape.Placement
                if any(shape.common(tool).Volume > 1e-8 or operation == "add" and shape.distToShape(tool)[0] <= 1e-7
                       for tool in tool_shapes):
                    desired.append(key)
            recorded = list(obj.KurtShapeMergePartIds)
            if set(desired) != set(recorded):
                scope_errors.append({"feature": obj.Name, "code": "auto_merge_scope_changed",
                    "message": "Auto merge scope changed; run a managed rebuild, or reapply the operation if its native consumers prevent part migration",
                    "recorded_parts": recorded, "intended_parts": desired})
        _AUTO_SCOPE_CACHE[doc.Name] = scope_errors
    errors.extend(_AUTO_SCOPE_CACHE[doc.Name])
    return errors


def _scope_parts(doc, operation, tool_shapes, before):
    desired = []
    for key, (body, tip) in _state(doc, before).items():
        shape = tip.Shape.copy()
        shape.Placement = body.Placement * shape.Placement
        if any(shape.common(tool).Volume > 1e-8 or operation == "add" and shape.distToShape(tool)[0] <= 1e-7
               for tool in tool_shapes):
            desired.append(key)
    return desired


def sync_auto_scopes(doc):
    """Synchronize existing native result graphs after a transactional rebuild.

    Native dimensional properties remain authoritative. Only native part inputs,
    output generations and Boolean links change. An unsupported dependency
    migration remains an explicit failed scope rather than guessed geometry.
    """
    from . import selectors
    if not enabled(doc) or not selectors._in_transaction(doc):
        return False
    changed = False
    features = order(doc)
    for index, representative in enumerate(features[:_cutoff(doc)]):
        request_text = getattr(representative, "KurtShapeStudioOperation", "")
        if not request_text or "KurtShapeNeutralToolBody" not in representative.PropertiesList:
            continue
        request = json.loads(request_text)
        operation = request.get("operation", "remove" if request["op"] == "pocket" else "new")
        if operation == "new" or request.get("merge_scope", "auto") != "auto":
            continue
        tool = representative.KurtShapeTool
        if tool.Shape.isNull():
            continue
        desired = _scope_parts(doc, operation, [tool.Shape], index)
        if not desired or set(desired) == set(representative.KurtShapeMergePartIds):
            continue
        available = _state(doc, index)
        outputs = [doc.getObject(name) for name in representative.KurtShapeOutputParts]
        tips = [doc.getObject(name) for name in representative.KurtShapeOutputTips]
        existing = {part_id(body): (body, tip) for body, tip in zip(outputs, tips)}
        primary = _body_owner(representative)
        primary_key = part_id(primary)
        # Reassigning an existing native feature to another Body could destroy
        # attachment/edge intent. Reject that rare migration when it has native
        # consumers; ordinary later studio operations rebind by stable part ID.
        def native_consumers(body, tip):
            return [obj for obj in features[index + 1:] if _body_owner(obj) == body and obj != tip]
        dropped = [entry for key, entry in existing.items() if key not in desired]
        if any(native_consumers(*entry) for entry in dropped):
            continue
        if primary_key not in desired:
            replacement = next((key for key in desired if key not in existing), desired[0])
            displaced = existing.get(replacement)
            if native_consumers(primary, representative) or displaced and native_consumers(*displaced):
                continue
            primary_key = replacement
        desired = [primary_key] + [key for key in desired if key != primary_key]
        old_inputs = dict(zip(representative.KurtShapeInputPartIds, representative.KurtShapeInputSnapshots))
        snapshots = []
        for key in desired:
            body, tip = available[key]
            snapshot = old_inputs.get(key)
            if not snapshot:
                snapshot = _snapshot(doc, body, tip, representative.Name + "AutoInput")
                _prop(snapshot, "App::PropertyString", "KurtShapeOperationOwner", representative.Name)
            elif "KurtShapeInputBinder" in snapshot.PropertiesList:
                snapshot.BaseFeature = tip
                snapshot.KurtShapeInputBinder.Support = [(tip, [""])]
            elif snapshot.BaseFeature != tip:
                snapshot.BaseFeature = tip
                snapshot.Placement = body.Placement
            snapshots.append((key, snapshot))
        doc.recompute()
        neutral = representative.KurtShapeNeutralToolBody
        # The public representative retains its exact native Name and its
        # dimensional-tool link. Native output Names survive while their part
        # IDs survive; the same primary Boolean is retargeted when safe.
        primary.KurtShapePartId = primary_key
        label = getattr(available[primary_key][0], "KurtShapePartName", available[primary_key][0].Label)
        primary.Label = label
        _prop(primary, "App::PropertyString", "KurtShapePartName", label)
        original = available[primary_key][0]
        for kind, prop in [("App::PropertyBool", "KurtShapePartVisible"), ("App::PropertyColor", "KurtShapePartColor")]:
            if prop in original.PropertiesList:
                _prop(primary, kind, prop, getattr(original, prop))
        primary.BaseFeature = snapshots[0][1]
        primary.setExpression("Placement", snapshots[0][1].Name + ".Placement")
        doc.recompute()
        base = next(obj for obj in primary.Group if obj.TypeId == "PartDesign::FeatureBase")
        representative.BaseFeature = base
        old_group = list(representative.Group)
        representative.Group = []
        for helper in old_group:
            _prop(helper, "App::PropertyBool", "KurtShapeObsolete", True)
        first_tools = [neutral] + ([item[1] for item in snapshots[1:]] if operation == "add" else [])
        group = [_boolean_tool(doc, primary, body, representative.Name + "AutoTool") for body in first_tools]
        for body in group:
            _prop(body, "App::PropertyString", "KurtShapeOperationOwner", representative.Name)
        doc.recompute()
        representative.Group = group
        _prop(primary, "App::PropertyBool", "KurtShapeObsolete", False)
        _prop(primary, "App::PropertyBool", "KurtShapeInternal", False)
        new_outputs, new_tips = [primary], [representative]
        if operation != "add":
            for key, snapshot in snapshots[1:]:
                entry = existing.get(key)
                if entry and entry[0] != primary:
                    body, boolean = entry
                    body.BaseFeature = snapshot
                    body.setExpression("Placement", snapshot.Name + ".Placement")
                    doc.recompute()
                    boolean.BaseFeature = next(obj for obj in body.Group if obj.TypeId == "PartDesign::FeatureBase")
                    if "KurtShapeObsolete" in body.PropertiesList:
                        body.KurtShapeObsolete = False
                else:
                    original = available[key][0]
                    body, boolean = _native_boolean(doc, snapshot, [neutral], representative.Name + "AutoResult",
                            key, getattr(original, "KurtShapePartName", original.Label),
                            "subtract" if operation == "remove" else "intersect")
                    _prop(body, "App::PropertyString", "KurtShapeOperationOwner", representative.Name)
                    _prop(boolean, "App::PropertyBool", "KurtShapeInternal", True)
                    _prop(boolean, "App::PropertyString", "KurtShapeOperationOwner", representative.Name)
                new_outputs.append(body); new_tips.append(boolean)
        for body in outputs:
            if body not in new_outputs:
                _prop(body, "App::PropertyBool", "KurtShapeObsolete", True)
                _prop(body, "App::PropertyBool", "KurtShapeInternal", True)
        representative.KurtShapeInputPartIds = [key for key, body in snapshots]
        representative.KurtShapeInputSnapshots = [body for key, body in snapshots]
        representative.KurtShapeMergePartIds = desired
        representative.KurtShapeConsumedParts = desired
        representative.KurtShapeOutputParts = [body.Name for body in new_outputs]
        representative.KurtShapeOutputTips = [tip.Name for tip in new_tips]
        if "KurtShapeScopeBounds" in representative.PropertiesList:
            representative.KurtShapeScopeBounds.Links = [body for key, body in snapshots]
        _validate(doc, new_outputs)
        changed = True
        prepare_recompute(doc)
    if changed:
        native_recomputed(doc)
    return changed


def rollback(doc, index):
    meta = _enable(doc)
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index <= len(order(doc)):
        raise _error("invalid_argument", "Rollback index must be within the feature list")
    meta.KurtShapeRollbackIndex = index
    prepare_recompute(doc)
    return None


def inspect(doc):
    if not enabled(doc):
        return {"enabled": False, "feature_order": [obj.Name for obj in order(doc)],
                "rollback_index": len(order(doc)), "parts": []}
    parts = []
    for body in current_parts(doc):
        color = list(getattr(body, "KurtShapePartColor", (.78, .8, .84)))[:3]
        parts.append({"id": part_id(body), "name": getattr(body, "KurtShapePartName", body.Label), "body": body.Name,
                      "feature": body.Tip.Name if body.Tip else None,
                      "visible": bool(getattr(body, "KurtShapePartVisible", True)), "color": color})
    return {"enabled": True, "feature_order": [obj.Name for obj in order(doc)],
            "rollback_index": _cutoff(doc), "parts": parts}


def _inputs(doc, ids, prefix):
    if not isinstance(ids, list) or not ids or len(set(ids)) != len(ids):
        raise _error("invalid_argument", "Choose a nonempty list of distinct current part IDs")
    available = _state(doc, _cutoff(doc))
    result = []
    for key in ids:
        body = current_part(doc, key)
        entry = available.get(part_id(body))
        if not entry:
            raise _error("missing_part", "The selected part has no solid at the rollback bar", part=key)
        snap = _snapshot(doc, body, entry[1], prefix + "Input")
        result.append((part_id(body), snap))
    doc.recompute()
    return result


def _native_boolean(doc, source, tools, name, key, label, kind):
    result = _output(doc, source, name + "Part", key, label)
    doc.recompute()
    tip = result.Tip
    boolean = result.newObject("PartDesign::Boolean", name)
    boolean.BaseFeature = tip
    boolean.Type = {"union": 0, "subtract": 1, "intersect": 2}[kind]
    # Boolean.Group claims its tool Bodies in a GeoFeatureGroup. Every Boolean
    # therefore owns private native wrappers around a shared tool's native Tip.
    private_tools = [_boolean_tool(doc, result, tool, name + "BooleanTool") for tool in tools]
    doc.recompute()
    boolean.Group = private_tools
    boolean.Refine = True
    doc.recompute()
    return result, boolean


def _boolean_tool(doc, result, tool, name):
    """Provide world tool geometry in the native Boolean's Body-local frame."""
    binder = result.newObject("PartDesign::ShapeBinder", name + "Frame")
    binder.Support = [(tool.Tip, [""])]
    binder.TraceSupport = True
    _prop(binder, "App::PropertyBool", "KurtShapeInternal", True)
    private = doc.addObject("PartDesign::Body", name)
    private.BaseFeature = tool.Tip
    private.setExpression("Placement", binder.Name + ".Placement")
    _prop(private, "App::PropertyBool", "KurtShapeInternal", True)
    doc.recompute()
    return private


def _axis(req):
    axis = req.get("axis", {})
    if not isinstance(axis, dict) or set(axis) - {"origin", "direction"}:
        raise _error("invalid_argument", "Axis requires origin and direction")
    return (_vector(axis.get("origin"), "axis.origin", [0, 0, 0]),
            _vector(axis.get("direction"), "axis.direction", [0, 0, 1], True))


def _world_profile(doc, profile, name):
    """Expose native local sketch geometry in its owning Body's world frame."""
    owner = _body_owner(profile)
    if not owner:
        return profile
    native = doc.addObject("PartDesign::ShapeBinder", name)
    native.Support = [(profile, [""])]
    native.TraceSupport = True
    _prop(native, "App::PropertyBool", "KurtShapeInternal", True)
    doc.recompute()
    return native


def _tool(controller, doc, req, name):
    op = req["op"]
    if op in {"pad", "pocket", "revolve", "sweep"}:
        profile = controller._profile(doc, req.get("profile"))
        if not profile.Shape.Wires:
            raise _error("open_profile", "Profile must contain closed geometry")
    if op in {"pad", "pocket"}:
        end_type = req.get("end_type", "blind")
        if end_type not in {"blind", "through_all", "up_to_face"}:
            raise _error("invalid_argument", "end_type must be blind, through_all or up_to_face")
        if end_type == "up_to_face" or "up_to_face" in req:
            from . import selectors, reference_tools
            reference = selectors.native_reference(doc, req.get("up_to_face"), entity_type="face")
            target = doc.getObject(reference["feature"])
            aux = doc.addObject("PartDesign::Body", name + "Carrier")
            _prop(aux, "App::PropertyBool", "KurtShapeInternal", True)
            tool = aux.newObject("PartDesign::Pad", name)
            tool.Profile = _world_profile(doc, profile, name + "Profile")
            tool.Type = "UpToFace"
            tool.UpToFace = (target, [reference["subelement"]])
            tool.Reversed = _bool(req, "reversed", False)
            _prop(tool, "App::PropertyBool", "KurtShapeInternal", True)
            if reference_tools.is_selector(req["up_to_face"]):
                selectors.bind(tool, "up_to_face", reference_tools.selector_value(req["up_to_face"]), native_property="UpToFace")
            doc.recompute()
            if tool.Shape.isNull() or not tool.Shape.isValid():
                raise _error("build_failed", "The up-to-face tool did not produce valid geometry", status=tool.getStatusString())
            return tool
        tool = doc.addObject("Part::Extrusion", name)
        tool.Base = _world_profile(doc, profile, name + "Profile")
        tool.DirMode = "Normal"
        tool.Solid = True
        through = end_type == "through_all" or op == "pocket" and _bool(req, "through_all", True)
        if through:
            shapes = [obj.Shape for obj in current_parts(doc) if not obj.Shape.isNull()]
            bounds = Part.makeCompound(shapes).BoundBox if shapes else None
            depth = bounds.DiagonalLength * 2 + (profile.Placement.Base - bounds.Center).Length * 2 + 2 if bounds else 10
            tool.LengthFwd, tool.LengthRev = depth, depth
        else:
            depth = _number(req.get("length"), "length", True)
            tool.LengthFwd = depth
            tool.Reversed = _bool(req, "reversed", op == "pocket")
    elif op == "revolve":
        origin, direction = _axis(req)
        tool = doc.addObject("Part::Revolution", name)
        tool.Source = _world_profile(doc, profile, name + "Profile")
        tool.Base, tool.Axis = origin, direction
        tool.Angle = math.degrees(_number(req.get("angle", "360 deg"), "angle", True, "rad"))
        tool.Solid = True
    elif op == "sweep":
        path_spec = req.get("path", "")
        path_ref = None
        if isinstance(path_spec, dict):
            from . import selectors, reference_tools
            path_ref = selectors.native_reference(doc, path_spec, entity_type="edge")
            path = doc.getObject(path_ref["feature"])
        else:
            path = doc.getObject(path_spec)
        if not path or not hasattr(path, "Shape") or not path.Shape.Edges:
            raise _error("missing_reference", "Sweep path must name a native curve feature")
        if path_ref:
            spine = doc.addObject("PartDesign::ShapeBinder", name + "Path")
            spine.Support = [(path, [path_ref["subelement"]])]
            spine.TraceSupport = True
            _prop(spine, "App::PropertyBool", "KurtShapeInternal", True)
            if reference_tools.is_selector(path_spec):
                selectors.bind(spine, "path", reference_tools.selector_value(path_spec),
                               native_property="Support", mode="linksublist")
            doc.recompute()
        else:
            spine = _world_profile(doc, path, name + "Path")
        tool = doc.addObject("Part::Sweep", name)
        tool.Sections = [_world_profile(doc, profile, name + "Profile")]
        tool.Spine = (spine, [])
        tool.Solid = True
        tool.Frenet = _bool(req, "frenet", False)
    elif op == "loft":
        sections = req.get("sections")
        if not isinstance(sections, list) or len(sections) < 2:
            raise _error("invalid_argument", "Loft needs at least two sketch sections")
        profiles = [controller._profile(doc, item) for item in sections]
        tool = doc.addObject("Part::Loft", name)
        tool.Sections = [_world_profile(doc, profile, name + "Section") for profile in profiles]
        tool.Solid = True
        tool.Ruled, tool.Closed = _bool(req, "ruled"), _bool(req, "closed")
    else:
        raise _error("unsupported_operation", "Unsupported studio tool")
    _prop(tool, "App::PropertyBool", "KurtShapeInternal", True)
    doc.recompute()
    if tool.Shape.isNull() or not tool.Shape.isValid() or not tool.Shape.Solids:
        raise _error("build_failed", "The native tool did not produce valid solid geometry", status=tool.getStatusString())
    return tool


def _result_operation(controller, doc, req, name):
    operation = req.get("operation", "remove" if req["op"] == "pocket" else "new")
    if operation not in {"new", "add", "remove", "intersect"}:
        raise _error("invalid_argument", "Operation must be new, add, remove or intersect")
    tool = _tool(controller, doc, req, name if operation == "new" else name + "Tool")
    tool_body = _output(doc, tool, name + "ToolBody")
    _prop(tool_body, "App::PropertyBool", "KurtShapeInternal", True)
    doc.recompute()
    if operation == "new":
        _prop(tool_body, "App::PropertyBool", "KurtShapeInternal", False)
        profile = doc.getObject(req.get("profile", "") or (req.get("sections", [""])[0] if req.get("sections") else ""))
        source_owner = _body_owner(profile) if profile else None
        if source_owner and part_id(source_owner) not in _state(doc, _cutoff(doc)):
            tool_body.KurtShapePartId = part_id(source_owner)
            label = req.get("name", getattr(source_owner, "KurtShapePartName", source_owner.Label))
        else:
            label = req.get("name", "Part " + str(len(current_parts(doc)) + 1))
        tool_body.Label = label
        _prop(tool_body, "App::PropertyString", "KurtShapePartName", label)
        _validate(doc, [tool_body])
        return _record(doc, tool, req, [tool_body])
    scope = req.get("merge_scope", "auto")
    parts = current_parts(doc)
    if scope == "auto":
        chosen = []
        for body in parts:
            shape = body.Shape
            if shape.isNull():
                continue
            overlap = shape.common(tool.Shape).Volume > 1e-8
            touching = operation == "add" and shape.distToShape(tool.Shape)[0] <= 1e-7
            if overlap or touching:
                chosen.append(part_id(body))
    elif isinstance(scope, list) and scope:
        chosen = [part_id(current_part(doc, item)) for item in scope]
        if len(set(chosen)) != len(chosen):
            raise _error("invalid_argument", "Merge scope must contain distinct part IDs")
    else:
        raise _error("invalid_argument", "Merge scope must be auto or a nonempty part list")
    if not chosen:
        raise _error("empty_merge_scope", "The result does not touch a part in the selected scope")
    snapshots = _inputs(doc, chosen, name)
    through = req.get("end_type") == "through_all" or req["op"] == "pocket" and req.get("through_all", True)
    if through and tool.TypeId == "Part::Extrusion":
        bounds = doc.addObject("Part::Compound", name + "ScopeBounds")
        bounds.Links = [entry[1] for entry in snapshots]
        _prop(bounds, "App::PropertyBool", "KurtShapeInternal", True)
        profile = doc.getObject(req["profile"])
        length = f"{bounds.Name}.Shape.BoundBox.DiagonalLength * 2 + 2"
        for axis in ["x", "y", "z"]:
            length += f" + abs({profile.Name}.Placement.Base.{axis} / 1 mm - {bounds.Name}.Shape.BoundBox.Center.{axis}) * 2"
        tool.setExpression("LengthFwd", "(" + length + ") * 1 mm")
        tool.setExpression("LengthRev", "(" + length + ") * 1 mm")
        doc.recompute()
    outputs, reps = [], []
    if operation == "add":
        first = current_part(doc, snapshots[0][0])
        result, rep = _native_boolean(doc, snapshots[0][1], [tool_body] + [x[1] for x in snapshots[1:]],
                                      name, snapshots[0][0], getattr(first, "KurtShapePartName", first.Label), "union")
        outputs.append(result)
        reps.append(rep)
    else:
        for index, (key, source) in enumerate(snapshots):
            original = current_part(doc, key)
            result, rep = _native_boolean(doc, source, [tool_body], name if index == 0 else name + "Result", key,
                                          getattr(original, "KurtShapePartName", original.Label),
                                          "subtract" if operation == "remove" else "intersect")
            outputs.append(result)
            reps.append(rep)
    _validate(doc, outputs)
    if operation == "remove" and not any(result.Shape.Volume < source.Shape.Volume - 1e-7
                                          for result, (key, source) in zip(outputs, snapshots)):
        raise _error("empty_cut", "Remove did not remove material from the selected scope")
    _prop(reps[0], "App::PropertyLink", "KurtShapeTool", tool)
    _prop(reps[0], "App::PropertyLink", "KurtShapeNeutralToolBody", tool_body)
    if through and tool.TypeId == "Part::Extrusion":
        _prop(reps[0], "App::PropertyLink", "KurtShapeScopeBounds", bounds)
    _prop(reps[0], "App::PropertyStringList", "KurtShapeMergePartIds", chosen)
    return _record(doc, reps[0], req, outputs, chosen, snapshots)


def _transform(req):
    translation = _vector(req.get("translation"), "translation", [0, 0, 0])
    rotation = req.get("rotation", {})
    if not isinstance(rotation, dict) or set(rotation) - {"axis", "angle"}:
        raise _error("invalid_argument", "Rotation requires axis and angle")
    angle = math.degrees(_number(rotation.get("angle", 0), "rotation.angle", unit="rad"))
    axis = _vector(rotation.get("axis"), "rotation.axis", [0, 0, 1], True)
    placement = App.Placement(translation, App.Rotation(axis, angle))
    coordinate = req.get("coordinate_system")
    if coordinate is not None:
        if not isinstance(coordinate, dict) or set(coordinate) != {"origin", "x", "y", "z"}:
            raise _error("invalid_argument", "Coordinate system requires origin and x/y/z axes")
        x, y, z = [_vector(coordinate[key], "coordinate_system." + key, direction=True) for key in ["x", "y", "z"]]
        if max(abs(x.dot(y)), abs(y.dot(z)), abs(z.dot(x))) > 1e-7 or x.cross(y).dot(z) < .999999:
            raise _error("invalid_argument", "Coordinate system must be orthogonal and right handed")
        placement = App.Placement(_vector(coordinate["origin"], "coordinate_system.origin"), App.Rotation(x, y, z, "ZXY")) * placement
    return placement


def _copy_result(doc, snapshot, placement, name, key=None, mirror=None):
    if mirror:
        shape = doc.addObject("Part::Mirroring", name)
        shape.Source = snapshot
        shape.Base, shape.Normal = mirror
    else:
        link = doc.addObject("App::Link", name + "Link")
        link.setLink(snapshot)
        link.Placement = placement * snapshot.Placement
        _prop(link, "App::PropertyBool", "KurtShapeInternal", True)
        shape = doc.addObject("Part::Compound", name)
        shape.Links = [link]
    _prop(shape, "App::PropertyBool", "KurtShapeInternal", True)
    doc.recompute()
    body = _output(doc, shape, name + "Part", key)
    return body, shape


def _plane(doc, req):
    choices = [key for key in ["plane", "face", "sketch"] if key in req]
    if len(choices) != 1:
        raise _error("invalid_argument", "Split requires one plane, face or sketch")
    if choices[0] == "plane":
        plane = req["plane"]
        if not isinstance(plane, dict) or set(plane) - {"origin", "normal"}:
            raise _error("invalid_argument", "Plane requires origin and normal")
        return (_vector(plane.get("origin"), "plane.origin", [0, 0, 0]),
                _vector(plane.get("normal"), "plane.normal", [0, 0, 1], True))
    if choices[0] == "sketch":
        sk = doc.getObject(req["sketch"])
        if not sk or sk.TypeId != "Sketcher::SketchObject":
            raise _error("missing_reference", "Split sketch must name a native sketch")
        return sk.Placement.Base, sk.Placement.Rotation.multVec(App.Vector(0, 0, 1))
    ref = req["face"]
    if not isinstance(ref, dict):
        raise _error("invalid_argument", "Split face requires a native reference")
    obj = doc.getObject(ref.get("feature", ""))
    if not obj or not hasattr(obj, "Shape"):
        raise _error("missing_reference", "Split face feature is missing")
    try:
        face = obj.Shape.getElement(ref.get("subelement", ""))
    except Exception as exc:
        raise _error("missing_reference", "Split face is missing") from exc
    if not isinstance(face, Part.Face) or not isinstance(face.Surface, Part.Plane):
        raise _error("unsupported_split_surface", "This native split requires a planar face")
    return face.CenterOfMass, face.normalAt(0, 0)


def handle(controller, doc, req):
    op = req["op"]
    if op not in OPS | {"pad", "pocket"} or op in {"pad", "pocket"} and "operation" not in req and "merge_scope" not in req:
        return None
    _enable(doc)
    if op == "rollback":
        return rollback(doc, req.get("index"))
    if op == "set_part_appearance":
        body = current_part(doc, req.get("part"))
        if "name" in req:
            name = req["name"]
            if not isinstance(name, str) or not 1 <= len(name) <= 120 or not name.isprintable():
                raise _error("invalid_argument", "Part name must contain 1–120 printable characters")
            for obj in doc.Objects:
                if obj.TypeId == "PartDesign::Body" and part_id(obj) == part_id(body):
                    obj.Label = name
                    _prop(obj, "App::PropertyString", "KurtShapePartName", name)
        if "visible" in req:
            for obj in doc.Objects:
                if obj.TypeId == "PartDesign::Body" and part_id(obj) == part_id(body):
                    _prop(obj, "App::PropertyBool", "KurtShapePartVisible", _bool(req, "visible"))
        if "color" in req:
            color = req["color"]
            if not isinstance(color, list) or len(color) != 3 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or not 0 <= x <= 1 for x in color):
                raise _error("invalid_argument", "Color requires three values between zero and one")
            for obj in doc.Objects:
                if obj.TypeId == "PartDesign::Body" and part_id(obj) == part_id(body):
                    _prop(obj, "App::PropertyColor", "KurtShapePartColor", tuple(color))
                    if App.GuiUp:
                        obj.ViewObject.ShapeColor = tuple(color)
        return body.Name
    name = controller._id(doc, req, {"pad": "Extrude", "pocket": "Remove"}.get(op, "StudioFeature"))
    if op in {"pad", "pocket", "revolve", "sweep", "loft"}:
        return _result_operation(controller, doc, req, name)
    if op == "delete_part":
        key = part_id(current_part(doc, req.get("part")))
        record = doc.addObject("App::DocumentObjectGroup", name)
        return _record(doc, record, req, [], [key])
    if op == "boolean_parts":
        kind = req.get("kind", "union")
        if kind not in {"union", "subtract", "intersect"}:
            raise _error("invalid_argument", "Boolean kind must be union, subtract or intersect")
        targets, tools = req.get("targets"), req.get("tools")
        if not isinstance(targets, list) or not targets or not isinstance(tools, list) or not tools or set(targets) & set(tools):
            raise _error("invalid_argument", "Choose separate target and tool part lists")
        snapshots = _inputs(doc, targets + tools, name)
        ntarget = len(targets)
        tool_snaps = [x[1] for x in snapshots[ntarget:]]
        outputs, representatives = [], []
        selected = snapshots[:ntarget] if kind == "subtract" else snapshots[:1]
        for index, (key, source) in enumerate(selected):
            original = current_part(doc, key)
            output, representative = _native_boolean(doc, source,
                tool_snaps if kind == "subtract" else [x[1] for x in snapshots[1:ntarget]] + tool_snaps,
                name if index == 0 else name + "Result", key, getattr(original, "KurtShapePartName", original.Label), kind)
            outputs.append(output)
            representatives.append(representative)
        _validate(doc, outputs)
        consumed = [x[0] for x in snapshots[:ntarget]]
        if not _bool(req, "keep_tools", False):
            consumed += [x[0] for x in snapshots[ntarget:]]
        return _record(doc, representatives[0], req, outputs, consumed, snapshots)
    if op == "split_part":
        original = current_part(doc, req.get("part"))
        snapshots = _inputs(doc, [part_id(original)], name)
        source = snapshots[0][1]
        origin, normal = _plane(doc, req)
        # A cube bounded by source diagonal and plane-origin distance is a finite
        # exact halfspace for this input. Bounds remain native expressions.
        plane = doc.addObject("PartDesign::Plane", name + "CuttingPlane")
        _prop(plane, "App::PropertyBool", "KurtShapeInternal", True)
        _prop(plane, "App::PropertyLength", "KurtShapeExtent", 1.0)
        cutter = doc.addObject("Part::Box", name + "Halfspace")
        _prop(cutter, "App::PropertyBool", "KurtShapeInternal", True)
        _prop(plane, "App::PropertyFloat", "KurtShapePlaneX", origin.x)
        _prop(plane, "App::PropertyFloat", "KurtShapePlaneY", origin.y)
        _prop(plane, "App::PropertyFloat", "KurtShapePlaneZ", origin.z)
        size = (f"{source.Name}.Shape.BoundBox.DiagonalLength * 2 + "
                f"abs({source.Name}.Shape.BoundBox.Center.x - KurtShapePlaneX) * 2 + "
                f"abs({source.Name}.Shape.BoundBox.Center.y - KurtShapePlaneY) * 2 + "
                f"abs({source.Name}.Shape.BoundBox.Center.z - KurtShapePlaneZ) * 2 + 2")
        plane.setExpression("KurtShapeExtent", "(" + size + ") * 1 mm")
        for dim in ["Length", "Width", "Height"]:
            cutter.setExpression(dim, plane.Name + ".KurtShapeExtent")
        if "face" in req:
            reference = req["face"]
            support = (doc.getObject(reference["feature"]), [reference["subelement"]])
        elif "sketch" in req:
            support = (doc.getObject(req["sketch"]), [""])
        else:
            support = None
            plane.Placement = App.Placement(origin, App.Rotation(App.Vector(0, 0, 1), normal))
        if support:
            plane.AttachmentSupport = [support]
            plane.MapMode = "FlatFace"
            plane.setExpression("AttachmentOffset.Base.x", "-KurtShapeExtent / 2")
            plane.setExpression("AttachmentOffset.Base.y", "-KurtShapeExtent / 2")
        else:
            # Constant authored plane: center the finite halfspace using native
            # property expressions in its native coordinate frame.
            rotation = plane.Placement.Rotation
            xdir, ydir = rotation.multVec(App.Vector(1, 0, 0)), rotation.multVec(App.Vector(0, 1, 0))
            for component in ["x", "y", "z"]:
                plane.setExpression("Placement.Base." + component,
                    f"{getattr(origin, component):.17g} mm - KurtShapeExtent * {getattr(xdir, component)/2:.17g} - KurtShapeExtent * {getattr(ydir, component)/2:.17g}")
        cutter.setExpression("Placement", plane.Name + ".Placement")
        # Attached support is native, so upstream face/sketch movement changes
        # the cutting plane even during an ordinary FreeCAD recompute.
        if req.get("_face_selector"):
            from . import selectors
            selectors.bind(plane, "split_face", req["_face_selector"], native_property="AttachmentSupport")
        positive = doc.addObject("Part::Common", name)
        negative = doc.addObject("Part::Cut", name + "Negative")
        positive.Base, positive.Tool = source, cutter
        negative.Base, negative.Tool = source, cutter
        positive.Refine, negative.Refine = False, False
        for shape in [positive, negative]:
            _prop(shape, "App::PropertyBool", "KurtShapeInternal", True)
        doc.recompute()
        label = getattr(original, "KurtShapePartName", original.Label)
        outputs = [_output(doc, negative, name + "NegativePart", part_id(original), label),
                   _output(doc, positive, name + "PositivePart", label=label + " split")]
        _validate(doc, outputs)
        return _record(doc, positive, req, outputs, [part_id(original)], snapshots)
    if op == "transform_part":
        original = current_part(doc, req.get("part"))
        snapshots = _inputs(doc, [part_id(original)], name)
        copy = _bool(req, "copy", False)
        output, representative = _copy_result(doc, snapshots[0][1], _transform(req), name,
                                              None if copy else part_id(original))
        output.Label = req.get("name", original.Label + (" copy" if copy else ""))
        _validate(doc, [output])
        return _record(doc, representative, req, [output], [] if copy else [part_id(original)], snapshots)
    if op in {"linear_pattern_parts", "circular_pattern_parts", "mirror_parts"}:
        operation = req.get("operation", "new")
        if operation not in {"new", "add", "remove", "intersect"}:
            raise _error("invalid_argument", "Operation must be new, add, remove or intersect")
        snapshots = _inputs(doc, req.get("parts"), name)
        count = req.get("count", 2)
        if isinstance(count, bool) or not isinstance(count, int) or not 2 <= count <= 100:
            raise _error("invalid_argument", "Pattern count must be between two and one hundred")
        placements = []
        mirror = None
        if op == "linear_pattern_parts":
            direction = _vector(req.get("direction"), "direction", [1, 0, 0], True)
            spacing = _number(req.get("spacing"), "spacing", True)
            placements = [App.Placement(direction * spacing * i, App.Rotation()) for i in range(1, count)]
        elif op == "circular_pattern_parts":
            origin, axis = _axis(req)
            angle = _number(req.get("angle", "360 deg"), "angle", True, "rad")
            step = angle / count if abs(angle - 2 * math.pi) < 1e-8 else angle / (count - 1)
            placements = [App.Placement(App.Vector(), App.Rotation(axis, math.degrees(step * i)), origin) for i in range(1, count)]
        else:
            mirror = (_vector(req.get("origin"), "origin", [0, 0, 0]),
                      _vector(req.get("normal"), "normal", [1, 0, 0], True))
            placements = [App.Placement()]
        outputs, reps = [], []
        for key, source in snapshots:
            for placement in placements:
                output, rep = _copy_result(doc, source, placement, name if not reps else name + "Instance", mirror=mirror)
                output.Label = current_part(doc, key).Label + " pattern"
                outputs.append(output)
                reps.append(rep)
        _validate(doc, outputs)
        if operation != "new":
            copies = outputs
            for body in copies:
                _prop(body, "App::PropertyBool", "KurtShapeInternal", True)
            scope = req.get("merge_scope", "auto")
            candidates = current_parts(doc) if scope == "auto" else [current_part(doc, key) for key in scope] if isinstance(scope, list) and scope else []
            if not candidates:
                raise _error("empty_merge_scope", "Pattern merge scope must be auto or a nonempty part list")
            relevant = {}
            for body in candidates:
                matching = [copy for copy in copies if body.Shape.common(copy.Shape).Volume > 1e-8 or
                            operation == "add" and body.Shape.distToShape(copy.Shape)[0] <= 1e-7]
                if matching:
                    relevant[part_id(body)] = matching
            if not relevant:
                raise _error("empty_merge_scope", "Pattern copies do not touch the selected scope")
            target_inputs = _inputs(doc, list(relevant), name + "Target")
            snapshots += target_inputs
            inputs_by_id = dict(target_inputs)
            # Add merges targets connected through the same copied solid.
            groups = []
            for key in relevant:
                connected = {key}
                if operation == "add":
                    changed = True
                    while changed:
                        changed = False
                        group_tools = {copy.Name for item in connected for copy in relevant[item]}
                        for other, tools in relevant.items():
                            if other not in connected and group_tools & {copy.Name for copy in tools}:
                                connected.add(other); changed = True
                if not any(connected & group for group in groups):
                    groups.append(connected)
            outputs, boolean_reps = [], []
            for group in groups:
                keys = [key for key in relevant if key in group]
                tools = list({copy.Name: copy for key in keys for copy in relevant[key]}.values())
                source = inputs_by_id[keys[0]]
                original = current_part(doc, keys[0])
                result, rep = _native_boolean(doc, source,
                    tools + [inputs_by_id[key] for key in keys[1:]], name + "Result", keys[0],
                    getattr(original, "KurtShapePartName", original.Label),
                    {"add": "union", "remove": "subtract", "intersect": "intersect"}[operation])
                outputs.append(result); boolean_reps.append(rep)
            _validate(doc, outputs)
            _prop(reps[0], "App::PropertyStringList", "KurtShapeMergePartIds", list(relevant))
            _prop(reps[0], "App::PropertyStringList", "KurtShapePatternToolParts", [copy.Name for copy in copies])
            return _record(doc, reps[0], req, outputs, list(relevant), snapshots)
        return _record(doc, reps[0], req, outputs, snapshots=snapshots)
    raise _error("unsupported_operation", "Unsupported studio operation")
