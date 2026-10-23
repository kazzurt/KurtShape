"""Native multi-part studio operations and persisted feature ordering.

The model remains a FreeCAD dependency graph. Native Bodies carry logical part
identity; neutral Part tools and native PartDesign Booleans carry geometry.
The properties below describe operation order, not a second editable graph.
"""
from __future__ import annotations
from collections import OrderedDict
import json
import math
import time

import FreeCAD as App
import Part
from . import document_index, extrusion_edit, geometry

OPS = {"revolve", "sweep", "loft", "boolean_parts", "split_part",
       "transform_part", "delete_part", "linear_pattern_parts", "circular_pattern_parts",
       "mirror_parts", "rollback", "set_part_appearance"}
RESULT_FIELDS = {"operation", "merge_scope", "name", "refine"}
# Result-operation and Boolean kinds; operation_schemas reads these enums.
RESULT_OPERATIONS = ("new", "add", "remove", "intersect")
BOOLEAN_KINDS = ("union", "subtract", "intersect")
ARGS = {
    "pad": RESULT_FIELDS | {"face"}, "pocket": RESULT_FIELDS | {"face"},
    "revolve": {"id", "name", "profile", "axis", "angle", "operation", "merge_scope", "body", "refine"},
    "sweep": {"id", "name", "profile", "path", "operation", "merge_scope", "body", "frenet", "refine"},
    "loft": {"id", "name", "sections", "operation", "merge_scope", "body", "ruled", "closed", "refine"},
    "boolean_parts": {"id", "name", "targets", "tools", "kind", "keep_tools"},
    "split_part": {"id", "name", "part", "plane", "face", "sketch"},
    "transform_part": {"id", "name", "part", "translation", "rotation", "coordinate_system", "copy"},
    "delete_part": {"id", "name", "part"},
    "linear_pattern_parts": {"id", "name", "parts", "direction", "spacing", "count", "operation", "merge_scope",
                             "include_source"},
    "circular_pattern_parts": {"id", "name", "parts", "axis", "angle", "count", "operation", "merge_scope",
                               "include_source"},
    "mirror_parts": {"id", "name", "parts", "plane", "origin", "normal", "operation", "merge_scope", "include_source"},
    "rollback": {"index"},
    "set_part_appearance": {"part", "name", "visible", "color"},
}
META = "KurtShapeProject"
_AUTO_SCOPE_CACHE = {}
_SCOPE_MEMBERSHIP_LIMIT = 64


def native_recomputed(doc):
    """Cheap invalidation only; no kernel evaluation on observer/idle paths."""
    _AUTO_SCOPE_CACHE.pop(doc.Name, None)


def _native_failed(obj):
    # A failed native feature can retain its previously accepted nonnull Shape.
    return bool({"Invalid", "Error"} & set(obj.State))


def _shape_frame(shape):
    placement = shape.Placement
    return tuple(placement.Base) + tuple(placement.Rotation.Q)


def _pair_matches(doc, left, right, operation, first=None, second=None, dependencies=(), parameters=()):
    """Exact scope membership, with conservative boxes and scalar pair facts."""
    first = left.Shape if first is None else first
    second = right.Shape if second is None else second
    if not geometry.bboxes_overlap(geometry.bounding_box(first), geometry.bounding_box(second), tolerance=1e-7):
        return False
    cache = geometry.provider(doc)
    objects = (left, right, *dependencies)
    key = (parameters, _shape_frame(first), _shape_frame(second))
    def scalar(kind, compute):
        return cache.memo(kind, objects, key, compute) if cache is not None else compute()
    if scalar("studio_common_volume", lambda: geometry.common_volume(first, second)) > 1e-8:
        return True
    return operation == "add" and scalar("studio_distance", lambda: geometry.distance(first, second)) <= 1e-7


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


# B2 (slice A/B U9): one direction vocabulary for pad, pocket and hole. ``direction`` names the side of
# the profile normal (a sketch's +Z, a selected face's outward normal) the tool runs to. ``reversed``
# stays accepted for one release with its per-operation meaning; REVERSED_ALONG is the ``reversed``
# value that means "along" for each kind and REVERSED_DEFAULT what an omitted ``reversed`` means.
DIRECTIONS = ("along", "against")
REVERSED_ALONG = {"pad": False, "pocket": False, "legacy_pocket": True, "hole": True}
REVERSED_DEFAULT = {"pad": False, "pocket": True, "legacy_pocket": False, "hole": False}


def direction_kind(req):
    """The polarity kind of a pad, pocket or hole request: a pocket without a studio result is legacy."""
    op = req.get("op")
    if op == "pocket" and "operation" not in req and "merge_scope" not in req:
        return "legacy_pocket"
    return op


def apply_direction(req):
    """``req`` with ``direction`` translated into the operation's own ``reversed`` (B2, U9).

    Without ``direction`` the request is returned unchanged. ``direction`` and ``reversed`` together,
    or a value other than ``"along"``/``"against"``, reject with ``invalid_argument``.
    """
    if "direction" not in req:
        return req
    if "reversed" in req:
        raise _error("invalid_argument", "Give direction or reversed, not both (reversed is kept for one release)",
                     fields=["direction", "reversed"])
    direction = req["direction"]
    if direction not in DIRECTIONS:
        raise _error("invalid_argument", 'direction must be "along" or "against" (the profile normal)',
                     fields=["direction"])
    along = REVERSED_ALONG[direction_kind(req)]
    result = {key: value for key, value in req.items() if key != "direction"}
    result["reversed"] = along if direction == "along" else not along
    return result


def direction_of(req, reversed_value=None):
    """``"along"`` or ``"against"``: the side of the profile normal a pad, pocket or hole request runs to."""
    kind = direction_kind(req)
    if reversed_value is None:
        reversed_value = req.get("reversed", REVERSED_DEFAULT[kind])
    return "along" if bool(reversed_value) == REVERSED_ALONG[kind] else "against"


def _both_ways(req):
    """Whether a studio extrusion runs both ways from the profile plane (through all), so direction cannot help."""
    if "operation" not in req and "merge_scope" not in req or "face" in req:
        return False
    if "up_to_face" in req or req.get("end_type") == "up_to_face":
        return False
    return req.get("end_type") == "through_all" or req.get("op") == "pocket" and req.get("through_all", True) is True


def direction_hint(req, outcome, reversed_value=None):
    """Fix-hint details for an extrusion or hole that changed nothing (B3, slice A/B U9).

    ``outcome`` says what happened ("removed no material", ...). Where the direction decides the
    outcome the details carry ``direction_used`` and ``try_direction`` (the other side of the profile
    normal) beside the ``hint`` text; a studio through-all tool runs both ways, so its hint names the
    profile's position instead, and other tools get a position hint only. An up-to-face end decides
    its own side (``direction`` has no effect there), so it gets a position hint too.
    """
    if req.get("op") not in {"pad", "pocket", "hole"}:
        return {"hint": f"The tool {outcome}; check where the profile sits relative to the part"}
    if req.get("op") != "hole" and ("up_to_face" in req or req.get("end_type") == "up_to_face"):
        return {"hint": f"The up-to-face tool {outcome}; direction has no effect on an up-to-face end, so check "
                        "where the profile sits relative to the end face"}
    if _both_ways(req):
        return {"hint": f"The through-all tool {outcome}; it runs both ways from the profile plane, so move the "
                        "profile or name the parts in merge_scope"}
    used = direction_of(req, reversed_value)
    other = "against" if used == "along" else "along"
    return {"hint": f'The tool runs {used} the profile normal and {outcome}; try direction:"{other}", '
                    "or check where the profile sits", "direction_used": used, "try_direction": other}


def _prop(obj, kind, name, value=None):
    if name in obj.PropertiesList and obj.getTypeIdOfProperty(name) != kind:
        # Metadata links intentionally span Body containers. Older documents
        # used local-scope links, which produced native scope warnings on every
        # recompute. Retain their exact objects when changing the dynamic type.
        prior = getattr(obj, name)
        editor_mode = obj.getEditorMode(name)
        obj.removeProperty(name)
        obj.addProperty(kind, name, "KurtShape studio")
        setattr(obj, name, prior)
        obj.setEditorMode(name, editor_mode)
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
        _prop(meta, "App::PropertyLinkListGlobal", "KurtShapeFeatureOrder")
        _prop(meta, "App::PropertyInteger", "KurtShapeRollbackIndex")
        # Unhashed native names retain all composite merge ancestors.
        doc.UseHasher = False
    return meta


def migrate_link_scopes(doc):
    """Upgrade adapter-owned document-wide links without altering geometry."""
    changed = False
    for obj in doc.Objects:
        for name, kind in (("KurtShapeFeatureOrder", "App::PropertyLinkListGlobal"),
                           ("KurtShapeInputSnapshots", "App::PropertyLinkListGlobal"),
                           ("KurtShapeInputBinder", "App::PropertyLinkGlobal"),
                           ("KurtShapeGeometryBinder", "App::PropertyLinkGlobal"),
                           ("KurtShapeTool", "App::PropertyLinkGlobal"),
                           ("KurtShapeNeutralToolBody", "App::PropertyLinkGlobal"),
                           ("KurtShapeScopeBounds", "App::PropertyLinkGlobal")):
            if name in obj.PropertiesList and obj.getTypeIdOfProperty(name) != kind:
                _prop(obj, kind, name)
    changed = _migrate_up_to_face_scopes(doc) or changed
    for obj in list(doc.Objects):
        if obj.TypeId == "PartDesign::Body" and (getattr(obj, "KurtShapeInternal", False)
                                                or getattr(obj, "KurtShapeOutputGeneration", False)) and obj.BaseFeature:
            geometry_binder = getattr(obj, "KurtShapeGeometryBinder", None)
            source = geometry_binder.Support[0][0] if geometry_binder and geometry_binder.Support else obj.BaseFeature
            if source.TypeId != "PartDesign::Body" and _body_owner(source):
                parent = next((_body_owner(user) for user in obj.InList if user.TypeId == "PartDesign::Boolean" and obj in user.Group), None)
                output = getattr(obj, "KurtShapeOutputGeneration", False) and source.TypeId == "PartDesign::Pad"
                changed = (_set_boolean_body_input(obj, source) if parent or output else _set_body_input(obj, source)) or changed
    from .modeling_geometry import migrate_axis_scopes
    return migrate_axis_scopes(doc) or changed


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
    index = document_index.get(doc)
    if index is not None and "order" in index.derived:
        return list(index.derived["order"])
    meta = _meta(doc)
    if enabled(doc):
        result = list(meta.KurtShapeFeatureOrder)
    else:
        objects = index.objects() if index is not None else doc.Objects
        discovered = [obj for obj in objects if _eligible(obj)]
        if meta and "KurtShapeFeatureOrder" in meta.PropertiesList:
            prior = list(meta.KurtShapeFeatureOrder)
            result = prior + [obj for obj in discovered if obj not in prior]
        else:
            result = discovered
    if index is not None:
        index.derived["order"] = tuple(result)
        index.derived["positions"] = {obj.Name: position for position, obj in enumerate(result)}
    return result


def _positions(doc):
    index = document_index.get(doc)
    if index is not None:
        if "positions" not in index.derived:
            order(doc)
        return index.derived["positions"]
    return {obj.Name: position for position, obj in enumerate(order(doc))}


def record_legacy_order(doc):
    """Keep native chronological links without enabling multi-part semantics.

    Document.Objects reflects native allocation order, which changes when Undo
    recreates a deletion. Establish this property before feature transactions
    so Undo restores the accepted links rather than reconstructing chronology.
    """
    meta = _meta(doc)
    if meta is None or enabled(doc):
        return
    sequence = order(doc)
    _prop(meta, "App::PropertyLinkListGlobal", "KurtShapeFeatureOrder", sequence)


def reconcile(doc):
    if not enabled(doc):
        record_legacy_order(doc)
        return
    migrate_link_scopes(doc)
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
        positions = _positions(doc)
        index = positions.get(name)
        if index is not None:
            return index
        # Auxiliary consumer belongs to its operation or the native Body order.
        operation = getattr(doc.getObject(name), "KurtShapeOperationOwner", "")
        index = positions.get(operation)
        if index is not None:
            return index
    return min(max(0, _meta(doc).KurtShapeRollbackIndex), len(features)) if enabled(doc) else len(features)


def _state(doc, cutoff):
    """Read current logical parts directly from native ordered operation metadata."""
    features = order(doc)[:cutoff]
    cutoff = len(features)
    cache = document_index.get(doc)
    states = cache.derived.setdefault("part_states", {0: {}}) if cache is not None else {0: {}}
    if cutoff in states:
        return dict(states[cutoff])
    start = max(position for position in states if position <= cutoff)
    state = dict(states[start])
    for obj in features[start:]:
        if cache is not None:
            cache.counts["history_steps"] += 1
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
    if cache is not None:
        states[cutoff] = dict(state)
    return state


def current_parts(doc, before=None):
    if not enabled(doc):
        from .bodies import bodies
        return bodies(doc)
    return [entry[0] for entry in _state(doc, _cutoff(doc, before)).values()]


PART_CHOICE_LIMIT = 20


def part_choices(parts, wanted=None):
    """``[{id, name}]`` of current parts for a ``missing_part`` fix hint (B3, slice A/B U9).

    Names closest to ``wanted`` come first, then document order; at most PART_CHOICE_LIMIT rows.
    """
    import difflib
    rows, seen = [], set()
    for body in parts:
        key = part_id(body)
        if key not in seen:
            seen.add(key)
            rows.append({"id": key, "name": getattr(body, "KurtShapePartName", body.Label)})
    if isinstance(wanted, str) and wanted:
        def closeness(row):
            return max(difflib.SequenceMatcher(None, wanted.lower(), str(text).lower()).ratio()
                       for text in (row["id"], row["name"]))
        rows.sort(key=lambda row: -closeness(row))
    return rows[:PART_CHOICE_LIMIT]


def current_part(doc, part, before=None):
    candidates = current_parts(doc, before)
    match = [obj for obj in candidates if part in {obj.Name, part_id(obj)}]
    if len(match) != 1:
        raise _error("missing_part", "Choose a current part ID", part=part,
                     current_parts=part_choices(candidates, part))
    return match[0]


def held_part_ids(doc):
    """Logical part IDs that exist only beyond the rollback bar."""
    if not enabled(doc):
        return set()
    features = order(doc)
    bar = _cutoff(doc)
    if bar >= len(features):
        return set()
    current = {part_id(entry[0]) for entry in _state(doc, bar).values()}
    held_ids = set()
    for obj in features[bar:]:
        body = _body_owner(obj)
        if body is not None:
            held_ids.add(part_id(body))
        for name in getattr(obj, "KurtShapeOutputParts", []):
            output = doc.getObject(name)
            if output is not None:
                held_ids.add(part_id(output))
    return held_ids - current


def held_bodies(doc):
    """Generated result Bodies of parts that exist only beyond the bar.

    New work there would model against future results. Original authoring
    Bodies remain valid sketch containers (including before the first solid);
    held_part_ids still keeps new results from adopting a future identity.
    """
    ids = held_part_ids(doc)
    return {body.Name for body in doc.Objects if body.TypeId == "PartDesign::Body" and part_id(body) in ids
            and (getattr(body, "KurtShapeOutputGeneration", False) or getattr(body, "KurtShapeInternal", False))}


def current_body(doc, part, before=None):
    try:
        return current_part(doc, part, before)
    except Exception:
        obj = doc.getObject(part) if isinstance(part, str) else None
        if obj is not None and obj.Name in held_bodies(doc):
            raise _error("held_part", "This part is created later in the rolled-back history; roll forward to add features to it",
                         part=part)
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
    position = _positions(doc).get(target.Name) if target else None
    if position is not None:
        return position < _cutoff(doc)
    if obj.TypeId == "PartDesign::Body" and not getattr(obj, "KurtShapeInternal", False):
        return any(entry[0] == obj for entry in _state(doc, _cutoff(doc)).values())
    return True


def _set_body_input(body, source):
    """A root SubShapeBinder preserves maps across native Body link scopes."""
    changed = False
    if source.TypeId != "PartDesign::Body" and _body_owner(source):
        binder = getattr(body, "KurtShapeGeometryBinder", None)
        if binder is None:
            binder = body.Document.addObject("PartDesign::SubShapeBinder", body.Name + "Geometry")
            _prop(binder, "App::PropertyBool", "KurtShapeInternal", True)
            _prop(body, "App::PropertyLinkGlobal", "KurtShapeGeometryBinder", binder)
            changed = True
        if not binder.Relative:
            # Native relative binding also preserves transformations embedded
            # in generated Compound/Link geometry; root context stays local.
            binder.Relative = True
            changed = True
        if binder.Support != [(source, ("",))] and binder.Support != [(source, [""])]:
            binder.Support = [(source, [""])]
            changed = True
        operation = getattr(body, "KurtShapeOperationOwner", "")
        if operation:
            _prop(binder, "App::PropertyString", "KurtShapeOperationOwner", operation)
        source = binder
    if body.BaseFeature != source:
        body.BaseFeature = source
        changed = True
    return changed


def _set_boolean_body_input(body, source):
    """Keep a private Boolean Body's scoped input empty; its native base is global.

    Boolean.Group moves tool Bodies into its own native coordinate scope. A
    manually authored FeatureBase has the supported global input scope and
    carries the authoritative source Tip's full geometry and element map.
    """
    changed = False
    if body.BaseFeature:
        body.BaseFeature = None
        changed = True
    base = next((obj for obj in body.Group if obj.TypeId == "PartDesign::FeatureBase"), None)
    if base is None:
        base = body.newObject("PartDesign::FeatureBase", body.Name + "Base")
        changed = True
    if base.BaseFeature != source:
        base.BaseFeature = source
        changed = True
    _prop(base, "App::PropertyBool", "KurtShapeInternal", True)
    operation = getattr(body, "KurtShapeOperationOwner", "")
    if operation:
        _prop(base, "App::PropertyString", "KurtShapeOperationOwner", operation)
    binder = getattr(body, "KurtShapeGeometryBinder", None)
    if binder:
        body.removeProperty("KurtShapeGeometryBinder")
        if getattr(binder, "KurtShapeInternal", False) and not binder.InList:
            body.Document.removeObject(binder.Name)
        changed = True
    if body.Tip != base:
        body.Tip = base
        changed = True
    return changed


def _snapshot(doc, body, feature, name, refine=None):
    snap = doc.addObject("PartDesign::Body", name)
    _prop(snap, "App::PropertyBool", "KurtShapeInternal", True)
    binder = doc.addObject("PartDesign::ShapeBinder", name + "Source")
    binder.Support = [(feature, [""])]
    binder.TraceSupport = True
    _prop(binder, "App::PropertyBool", "KurtShapeInternal", True)
    # ShapeBinder supplies pose; SubShapeBinder preserves the source's native
    # element map while allowing the Body's root-scope BaseFeature link.
    _set_body_input(snap, feature)
    if refine is not None:
        _set_refine([(None, snap)], [], refine)
    snap.setExpression("Placement", binder.Name + ".Placement")
    _prop(snap, "App::PropertyLinkGlobal", "KurtShapeInputBinder", binder)
    if App.GuiUp:
        snap.ViewObject.Visibility = False
    return snap


def _output(doc, source, name, key=None, label=None):
    previous = next((obj for obj in current_parts(doc) if part_id(obj) == key), None) if key else None
    body = doc.addObject("PartDesign::Body", name)
    if source.TypeId != "PartDesign::Body" and _body_owner(source):
        # Native carrier features retain their local Shape/Placement contract
        # through a global FeatureBase, without a scoped Body input link.
        _set_boolean_body_input(body, source)
    else:
        body.BaseFeature = source
    body.setExpression("Placement", source.Name + ".Placement")
    _prop(body, "App::PropertyString", "KurtShapePartId", key or body.Name)
    _prop(body, "App::PropertyBool", "KurtShapeOutputGeneration", True)
    if previous and not label:
        # A moved part keeps its name in its new generation.
        label = getattr(previous, "KurtShapePartName", "")
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


def _name_part(doc, body, name):
    """Give a part's current Body exactly this native Label.

    FreeCAD keeps labels unique. While the part's authoring Body or a
    superseded generation still holds the name, the current Body would get a
    numeric suffix ("Bone Mallet003"). The other Bodies of the part become
    "<name> (history n)" in creation order; labels that change are first
    released to the unique native Name so no assignment collides.
    """
    key = part_id(body)
    others = [obj for obj in doc.Objects if obj.TypeId == "PartDesign::Body" and obj != body and part_id(obj) == key]
    wanted = [(obj, f"{name} (history {index})") for index, obj in enumerate(others, 1)] + [(body, name)]
    stale = [(obj, label) for obj, label in wanted if obj.Label != label]
    for obj, _ in stale:
        obj.Label = obj.Name
    for obj, label in stale:
        obj.Label = label


def _validate(doc, objects):
    doc.recompute()
    for obj in objects:
        tip = obj.Tip if obj.TypeId == "PartDesign::Body" else None
        if obj.Shape.isNull() or len(obj.Shape.Solids) != 1 or _native_failed(obj) or tip and _native_failed(tip):
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
    _prop(representative, "App::PropertyLinkListGlobal", "KurtShapeInputSnapshots", [x[1] for x in snapshots])
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
        existing = getattr(obj, "KurtShapeOperationOwner", "")
        claimed = doc.getObject(existing) if existing and existing != representative.Name else None
        # Intermediate owners (e.g. this operation's own tool) are retagged;
        # objects owned by another studio operation never are.
        if (claimed is not None and getattr(claimed, "KurtShapeStudioOperation", "")) or (
                obj not in outputs and _owned_elsewhere(obj, representative.Name)):
            # A shared input that belongs to an earlier operation's part.
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
    # Outputs are now the current Bodies of their parts.
    for body in outputs:
        if getattr(body, "KurtShapePartName", ""):
            _name_part(doc, body, body.KurtShapePartName)
    return representative.Name


def record_curve(doc, curve, req):
    """Enter a top-level path curve (create_helix) in the feature history.

    It joins the order like a sketch: an operation without parts, so a later
    sweep keeps it as an input instead of claiming it as a helper. It does not
    enable the Part Studio, which would change the document's Body defaults.
    """
    if enabled(doc):
        return _record(doc, curve, req, [])
    _prop(curve, "App::PropertyString", "KurtShapeStudioOperation", json.dumps(req, sort_keys=True))
    _prop(curve, "App::PropertyBool", "KurtShapeInternal", False)
    for name in ("KurtShapeOutputParts", "KurtShapeOutputTips", "KurtShapeConsumedParts", "KurtShapeInputPartIds"):
        _prop(curve, "App::PropertyStringList", name, [])
    _prop(curve, "App::PropertyLinkListGlobal", "KurtShapeInputSnapshots", [])
    return curve.Name


def operation_members(doc, owner_name):
    """Objects created for one studio operation, by their recorded owner tag.

    Earlier releases also re-tagged shared inputs reached through
    dependencies, such as a prior part's FeatureBase. An object inside a Body
    owned by a different operation is that operation's input and is kept.
    Helpers placed in an untagged user Body (such as an axis datum) remain.
    """
    tagged = [obj for obj in doc.Objects if getattr(obj, "KurtShapeOperationOwner", "") == owner_name]
    # Pattern copies consumed by Add/Remove/Intersect were untagged before
    # 2026-10-17; their recorded tool Bodies still belong to the operation.
    owner = doc.getObject(owner_name)
    recorded = [doc.getObject(name) for name in getattr(owner, "KurtShapePatternToolParts", [])] if owner else []
    tagged += [obj for obj in recorded if obj is not None and obj not in tagged and getattr(obj, "KurtShapeInternal", False)
               and not getattr(obj, "KurtShapeOperationOwner", "")]
    return [obj for obj in tagged if not _owned_elsewhere(obj, owner_name)]


def _owned_elsewhere(obj, owner_name):
    container = _body_owner(obj) if obj.TypeId != "PartDesign::Body" else None
    if container is None:
        return False
    other = getattr(container, "KurtShapeOperationOwner", "")
    return bool(other) and other != owner_name


def native_closure(doc, names):
    """Everything FreeCAD removes with these objects.

    Removing a Body also removes its Origin with the origin axes and planes;
    those implicit children must count for consumers and impact reports.
    """
    result = set(names)
    for name in list(result):
        obj = doc.getObject(name)
        origin = getattr(obj, "Origin", None) if obj is not None and obj.TypeId == "PartDesign::Body" else None
        if origin is not None:
            result.add(origin.Name)
            result.update(feature.Name for feature in getattr(origin, "OriginFeatures", []))
    return result


def closure_report(doc, members):
    """Consumers outside a removal set, and the shared inputs it only reads."""
    names = {obj.Name for obj in members}
    consumers, inputs = set(), set()
    for obj in members:
        for dependent in obj.InList:
            if dependent.Name not in names and dependent.Name != META:
                consumers.add(dependent.Name)
        for source in obj.OutList:
            if source.Name not in names:
                inputs.add(source.Name)
    return sorted(consumers), sorted(inputs)


def orphan_groups(doc):
    """Read-only: helpers whose owning operation no longer exists.

    A group is repairable only when nothing outside it still depends on it.
    Its inputs (profiles, source parts) are reported and always kept.
    """
    groups = {}
    for obj in doc.Objects:
        owner_name = getattr(obj, "KurtShapeOperationOwner", "")
        if owner_name and doc.getObject(owner_name) is None:
            groups.setdefault(owner_name, []).append(obj)
    report = []
    for owner_name, members in sorted(groups.items()):
        # A Hole's private profile helpers live in the part's Body, which the
        # part's own operation owns; that Body only contains them.
        members = [obj for obj in members if getattr(obj, "KurtShapeHoleHelper", False)
                   or not _owned_elsewhere(obj, owner_name)]
        containers = {_body_owner(obj).Name for obj in members
                      if getattr(obj, "KurtShapeHoleHelper", False) and _body_owner(obj) is not None}
        removed = native_closure(doc, {obj.Name for obj in members})
        consumers, inputs = closure_report(doc, [doc.getObject(name) for name in removed])
        consumers = [name for name in consumers if name not in containers]
        report.append({"owner": owner_name, "objects": sorted(removed),
                       "tagged_objects": sorted(obj.Name for obj in members),
                       "consumers": consumers, "inputs": inputs, "repairable": not consumers})
    return report


def remove_objects(doc, names):
    """Remove a dependency-closed set, consumers before their sources."""
    names = set(names)
    ordered, visiting = [], set()
    def upstream(obj):
        if obj.Name in visiting:
            return
        visiting.add(obj.Name)
        for source in obj.OutList:
            if source.Name in names:
                upstream(source)
        ordered.append(obj.Name)
    for name in sorted(names):
        obj = doc.getObject(name)
        if obj is not None:
            upstream(obj)
    for name in reversed(ordered):
        if doc.getObject(name) is not None:
            doc.removeObject(name)
    return ordered


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
                    _set_body_input(snapshot, tip)
                    if binder.Support != [(tip, ("",))] and binder.Support != [(tip, [""])]:
                        binder.Support = [(tip, [""])]
                else:
                    _set_body_input(snapshot, tip)
                    if snapshot.Placement != body.Placement:
                        snapshot.Placement = body.Placement
    visible_state = _state(doc, bar)
    for body in [obj for obj in doc.Objects if obj.TypeId == "PartDesign::Body"]:
        selected_tip = next((entry[1] for entry in visible_state.values() if entry[0] == body), None)
        if selected_tip and body.Tip != selected_tip:
            body.Tip = selected_tip
        elif not selected_tip and not getattr(body, "KurtShapeInternal", False):
            own_active = [obj for obj in features[:bar] if _body_owner(obj) == body
                          and obj.isDerivedFrom("PartDesign::Feature") and not obj.Shape.isNull() and obj.Shape.Solids]
            tip = own_active[-1] if own_active else None
            if body.Tip != tip:
                body.Tip = tip
    _show_bodies(doc, visible_state)
    hide_internal(doc)


def _show_bodies(doc, visible_state):
    """Show the Bodies of the parts at the bar and of visible unused sketches."""
    if not App.GuiUp:
        return
    sketches = _rollback_sketch_visibility(doc)
    from .sketch_tools import unconsumed_sketches
    sketch_bodies = {_body_owner(sketch) for sketch in unconsumed_sketches(doc)
                     if sketch.ViewObject and sketch.ViewObject.Visibility}
    for body in [obj for obj in doc.Objects if obj.TypeId == "PartDesign::Body"]:
        active = body in sketch_bodies or any(entry[0] == body for entry in visible_state.values())
        desired = getattr(body, "KurtShapePartVisible", True)
        body.ViewObject.Visibility = bool(active and desired and not getattr(body, "KurtShapeInternal", False))
    # A Body can propagate visibility to a sketch Tip. Apply the individual
    # history state after the containers, including explicitly hidden sketches.
    for sketch, visible in sketches:
        if sketch.ViewObject.Visibility != visible:
            sketch.ViewObject.Visibility = visible


def _rollback_sketch_visibility(doc):
    """Hide future sketches while retaining their saved presentation choice.

    Keep the pre-rollback value on the native view provider so saving a model
    at an earlier history position does not lose it. This is presentation,
    rather than a modeling parameter, and never changes a sketch's geometry.
    """
    property_name = "KurtShapeRollbackVisible"
    sequence = order(doc)
    cutoff = _cutoff(doc)
    result = []
    for index, sketch in enumerate(sequence):
        if (sketch.TypeId != "Sketcher::SketchObject" or getattr(sketch, "KurtShapeInternal", False)
                or not sketch.ViewObject):
            continue
        view = sketch.ViewObject
        visible = bool(view.Visibility)
        if index >= cutoff:
            if property_name not in view.PropertiesList:
                view.addProperty("App::PropertyBool", property_name, "KurtShape presentation")
                setattr(view, property_name, visible)
                view.setEditorMode(property_name, 2)
            visible = False
        elif property_name in view.PropertiesList:
            visible = bool(getattr(view, property_name))
            view.removeProperty(property_name)
        if view.Visibility != visible:
            view.Visibility = visible
        result.append((sketch, visible))
    return result


def present(doc):
    """Apply the managed view state to a document FreeCAD just opened.

    View state normally comes from GuiDocument.xml. A Part Studio saved
    without the GUI (the headless Controller) has none, and FreeCAD's restore
    then hides every Body and feature and draws them in its default color.
    Show the parts at the rollback bar in their stored colors and hide the
    auxiliaries, as a managed rebuild does. Only view providers change.
    """
    if not App.GuiUp:
        return
    if enabled(doc):
        _show_bodies(doc, _state(doc, _cutoff(doc)))
        for body in doc.Objects:
            if body.TypeId == "PartDesign::Body" and "KurtShapePartColor" in body.PropertiesList:
                color = tuple(body.KurtShapePartColor[:3])
                if any(abs(a - b) > 1e-3 for a, b in zip(body.ViewObject.ShapeColor[:3], color)):
                    body.ViewObject.ShapeColor = color
    else:
        # Single-Body projects have no part metadata: show each native result.
        from .bodies import bodies
        for body in bodies(doc):
            if not getattr(body, "KurtShapeInternal", False) and body.Tip and not body.Shape.isNull() and body.Shape.Solids:
                body.ViewObject.Visibility = True
                body.Tip.ViewObject.Visibility = True
    hide_internal(doc)


def hide_internal(doc):
    if App.GuiUp:
        for obj in doc.Objects:
            # Path curves (create_helix) are inputs the user sees, like sketches.
            neutral_result = (obj.TypeId.startswith("Part::") and bool(getattr(obj, "KurtShapeStudioOperation", ""))
                              and not getattr(obj, "KurtShapeCurve", False))
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


def _auto_scope_operations(doc):
    for index, obj in enumerate(order(doc)[:_cutoff(doc)]):
        request_text = getattr(obj, "KurtShapeStudioOperation", "")
        if not request_text:
            continue
        request = json.loads(request_text)
        operation = request.get("operation", "remove" if request["op"] == "pocket" else "new")
        if operation != "new" and request.get("merge_scope", "auto") == "auto" and "KurtShapeMergePartIds" in obj.PropertiesList:
            yield index, obj, operation


def refresh_validation(doc):
    """Populate exact auto-scope diagnostics at an explicit rebuild boundary."""
    scope_errors = []
    if enabled(doc):
        for index, obj, operation in _auto_scope_operations(doc):
            tools = ([obj.KurtShapeTool] if "KurtShapeTool" in obj.PropertiesList else
                     [doc.getObject(name) for name in getattr(obj, "KurtShapePatternToolParts", []) if doc.getObject(name)])
            if not tools or any(tool.Shape.isNull() for tool in tools):
                continue
            desired = _scope_parts(doc, operation, tools, index)
            # Included pattern sources are tools of their operation, never targets.
            sources = set(getattr(obj, "KurtShapePatternSourceParts", []))
            desired = [key for key in desired if key not in sources]
            recorded = list(obj.KurtShapeMergePartIds)
            if set(desired) != set(recorded):
                scope_errors.append({"feature": obj.Name, "code": "auto_merge_scope_changed",
                    "message": "Auto merge scope changed; run a managed rebuild, or reapply the operation if its native consumers prevent part migration",
                    "recorded_parts": recorded, "intended_parts": desired})
    _AUTO_SCOPE_CACHE[doc.Name] = scope_errors
    return list(scope_errors)


def validation_errors(doc):
    """Read cached exact diagnostics and cheap native history inputs only."""
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
    if doc.Name in _AUTO_SCOPE_CACHE:
        errors.extend(_AUTO_SCOPE_CACHE[doc.Name])
    else:
        errors.extend({"feature": obj.Name, "code": "auto_merge_scope_pending",
                       "message": "Auto merge scope needs a native recompute before it can be accepted"}
                      for index, obj, operation in _auto_scope_operations(doc))
    return errors


def _scope_parts_full(doc, operation, tools, before):
    """Original exact traversal, retained as the uncached membership oracle."""
    index = document_index.get(doc)
    if index is not None:
        index.counts["scope_membership_full"] = index.counts.get("scope_membership_full", 0) + 1
    desired = []
    for key, (body, tip) in _state(doc, before).items():
        shape = tip.Shape.copy()
        shape.Placement = body.Placement * shape.Placement
        if any(_pair_matches(doc, tip, tool, operation, first=shape, dependencies=(body,),
                             parameters=("history", before)) for tool in tools):
            desired.append(key)
    return desired


def _scope_parts(doc, operation, tools, before):
    """Memoize complete membership only while every native domain is stable."""
    index = document_index.get(doc)
    if (index is None or type(before) is not int or not isinstance(tools, (list, tuple))
            or not isinstance(operation, str) or operation not in {"add", "remove", "intersect"}):
        return _scope_parts_full(doc, operation, tools, before)
    domains = tuple(sorted(document_index.DOMAINS))
    token = index.token(*domains)
    # A foreign tool can change without notifying this document's observer.
    # Detached/unknown objects keep the original traversal and error behavior.
    try:
        if any(tool.Document != doc or doc.getObject(tool.Name) != tool for tool in tools):
            return _scope_parts_full(doc, operation, tools, before)
        identities = tuple((tool.Name, tool.ID) for tool in tools)
    except (AttributeError, RuntimeError):
        return _scope_parts_full(doc, operation, tools, before)

    def stable():
        return document_index.get(doc) is index and index.token(*domains) == token

    def retry_full():
        # A reentrant native read can also populate old _state/order entries.
        # Discard those before retrying and leave this uncertain read uncached.
        def discard():
            index.invalidate(structure=True)
            current = document_index.get(doc)
            if current is not None and current is not index:
                current.invalidate(structure=True)
            scalars = geometry.provider(doc)
            if scalars is not None:
                scalars.drop_document(doc)
        discard()
        current = document_index.get(doc)
        retry_token = current.token(*domains) if current is not None else None
        try:
            value = _scope_parts_full(doc, operation, tools, before)
            if (document_index.get(doc) is not current or current is not None
                    and current.token(*domains) != retry_token):
                raise _error("scope_document_changed", "Native document changed during scope resolution; retry")
            return value
        finally:
            discard()

    if not stable():
        return retry_full()
    local = document_index.local_dependencies(index)
    if not stable():
        return retry_full()
    if not local:
        return _scope_parts_full(doc, operation, tools, before)
    key = (token, operation, before, identities)
    entries = index.derived.get("scope_membership")
    if entries is not None and key in entries:
        value = entries[key]
        if not stable():
            return retry_full()
        entries.move_to_end(key)
        index.counts["scope_membership_hits"] = index.counts.get("scope_membership_hits", 0) + 1
        return list(value)
    try:
        value = _scope_parts_full(doc, operation, tools, before)
    except Exception:
        if not stable():
            return retry_full()
        raise
    if not stable():
        return retry_full()
    entries = index.derived.setdefault("scope_membership", OrderedDict())
    entries[key] = tuple(value)
    while len(entries) > _SCOPE_MEMBERSHIP_LIMIT:
        entries.popitem(last=False)
    return list(value)


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
        desired = _scope_parts(doc, operation, [tool], index)
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
        # New inputs and results follow the operation's accepted native Refine.
        refine = bool(getattr(representative, "Refine", True))
        snapshots = []
        for key in desired:
            body, tip = available[key]
            snapshot = old_inputs.get(key)
            if not snapshot:
                snapshot = _snapshot(doc, body, tip, representative.Name + "AutoInput", refine)
                _prop(snapshot, "App::PropertyString", "KurtShapeOperationOwner", representative.Name)
            elif "KurtShapeInputBinder" in snapshot.PropertiesList:
                _set_body_input(snapshot, tip)
                snapshot.KurtShapeInputBinder.Support = [(tip, [""])]
            elif snapshot.BaseFeature != tip:
                _set_body_input(snapshot, tip)
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
                            "subtract" if operation == "remove" else "intersect", refine)
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


def _inputs(doc, ids, prefix, refine=None):
    if not isinstance(ids, list) or not ids or len(set(ids)) != len(ids):
        raise _error("invalid_argument", "Choose a nonempty list of distinct current part IDs")
    available = _state(doc, _cutoff(doc))
    result = []
    for key in ids:
        body = current_part(doc, key)
        entry = available.get(part_id(body))
        if not entry:
            raise _error("missing_part", "The selected part has no solid at the rollback bar", part=key,
                         current_parts=part_choices([entry[0] for entry in available.values()], key))
        snap = _snapshot(doc, body, entry[1], prefix + "Input", refine)
        result.append((part_id(body), snap))
    doc.recompute()
    return result


def _set_refine(snapshots, booleans, refine):
    """Native Refine of a result's Booleans and of its input snapshot binders.

    A snapshot's SubShapeBinder refines the input part again, so an unrefined
    result needs both: refining merges per-turn faces of helical cuts into
    multi-turn faces that the next Boolean misses or turns inside out.
    """
    for _, snapshot in snapshots:
        binder = getattr(snapshot, "KurtShapeGeometryBinder", None)
        if binder is not None and "Refine" in binder.PropertiesList and binder.Refine != refine:
            binder.Refine = refine
    for boolean in booleans:
        if boolean.Refine != refine:
            boolean.Refine = refine


def _evaluate_boolean(doc, boolean):
    # Exact first. Native automatic fuzz scales with the combined bounds, which
    # through-all tools inflate (a 0.5 m tool fuzzes ~6e-5 mm); near-tangent
    # sections then carried ~3e-4 mm edge tolerances and later fillets came
    # out invalid. Keep the native automatic value only where exact fails.
    if "FuzzyTolerance" in boolean.PropertiesList:
        boolean.FuzzyTolerance = 0.0
    doc.recompute()
    shape = boolean.Shape
    if "FuzzyTolerance" in boolean.PropertiesList and (
            shape.isNull() or len(shape.Solids) != 1 or _native_failed(boolean)):
        boolean.FuzzyTolerance = -1.0
        doc.recompute()


def _native_boolean(doc, source, tools, name, key, label, kind, refine=True):
    result = _output(doc, source, name + "Part", key, label)
    doc.recompute()
    tip = result.Tip
    # Boolean.Group claims its tool Bodies in a GeoFeatureGroup. Every Boolean
    # therefore owns private native wrappers around a shared tool's native Tip.
    private_tools = [_boolean_tool(doc, result, tool, name + "BooleanTool") for tool in tools]
    boolean = result.newObject("PartDesign::Boolean", name)
    boolean.BaseFeature = tip
    boolean.Type = {"union": 0, "subtract": 1, "intersect": 2}[kind]
    boolean.Group = private_tools
    boolean.Refine = refine
    _evaluate_boolean(doc, boolean)
    return result, boolean


def _boolean_tool(doc, result, tool, name):
    """Provide world tool geometry in the native Boolean's Body-local frame."""
    binder = result.newObject("PartDesign::ShapeBinder", name + "Frame")
    binder.Support = [(tool.Tip, [""])]
    binder.TraceSupport = True
    _prop(binder, "App::PropertyBool", "KurtShapeInternal", True)
    private = doc.addObject("PartDesign::Body", name)
    _set_boolean_body_input(private, tool.Tip)
    private.setExpression("Placement", binder.Name + ".Placement")
    _prop(private, "App::PropertyBool", "KurtShapeInternal", True)
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


def _sketch_normal_direction(doc, tool, source, name):
    """Extrude along the sketch's own +Z, never a normal inferred from its edges.

    Native Normal mode honours only a Part2DObject base. For the world
    ShapeBinder it fits a plane to the edges (BRepLib_FindSurface), whose
    sign follows the edge winding, so a clockwise profile ran backwards.
    A unit line placed by the world source (the top-level binder carries the
    sketch's global placement) keeps the direction native and live. The
    binder's generated name also avoids sketch IDs such as "S" that the
    expression parser reads as units.
    """
    line = doc.addObject("Part::Line", name + "Direction")
    line.X1 = line.Y1 = line.Z1 = line.X2 = line.Y2 = 0
    line.Z2 = 1
    line.setExpression("Placement", source.Name + ".Placement")
    _prop(line, "App::PropertyBool", "KurtShapeInternal", True)
    if App.GuiUp:
        line.ViewObject.Visibility = False
    tool.DirMode = "Edge"
    tool.DirLink = (line, ["Edge1"])


def _carrier_binder(carrier, source, elements, name, operation=""):
    binder = carrier.newObject("PartDesign::ShapeBinder", name)
    binder.Support = [(source, elements)]
    binder.TraceSupport = True
    _prop(binder, "App::PropertyBool", "KurtShapeInternal", True)
    if operation:
        _prop(binder, "App::PropertyString", "KurtShapeOperationOwner", operation)
    return binder


def _migrate_up_to_face_scopes(doc):
    """Keep native Pad inputs in their carrier; binder Support spans source Bodies."""
    from . import selectors
    changed = False
    for tool in list(doc.Objects):
        carrier = _body_owner(tool)
        if tool.TypeId != "PartDesign::Pad" or tool.Type != "UpToFace" or not carrier or not getattr(carrier, "KurtShapeInternal", False):
            continue
        operation = getattr(tool, "KurtShapeOperationOwner", "") or tool.Name
        profile = tool.Profile[0] if tool.Profile else None
        if profile and _body_owner(profile) != carrier:
            if profile.TypeId == "PartDesign::ShapeBinder" and getattr(profile, "KurtShapeInternal", False):
                parent = profile.getParentGeoFeatureGroup()
                if parent:
                    parent.removeObject(profile)
                carrier.addObject(profile)
            else:
                profile = _carrier_binder(carrier, profile, [""], tool.Name + "Profile", operation)
                tool.Profile = profile
            changed = True
        stop, elements = tool.UpToFace if tool.UpToFace else (None, [])
        if stop and _body_owner(stop) != carrier:
            stop = _carrier_binder(carrier, stop, list(elements), tool.Name + "Stop", operation)
            tool.UpToFace = (stop, ["Face1"])
            selectors.move_binding(tool, stop, "up_to_face", "Support", "linksublist")
            changed = True
    return changed


def _tool(controller, doc, req, name):
    op = req["op"]
    if op in {"pad", "pocket"} and "face" in req:
        if "profile" in req:
            raise _error("invalid_argument", "Choose one face or one sketch profile")
        from .modeling_geometry import make_face_tool
        return make_face_tool(controller, doc, req, name)
    if op in {"pad", "pocket", "revolve", "sweep"}:
        profile = controller._profile(doc, req.get("profile"))
        if not profile.Shape.Wires:
            raise _error("open_profile", "Profile must contain closed geometry")
        if op in {"pad", "pocket"} and not any(wire.isClosed() for wire in profile.Shape.Wires):
            from .extrusion_edit import open_profile_error
            raise open_profile_error(profile)
    if op in {"pad", "pocket"}:
        end_type = req.get("end_type", "blind")
        if end_type not in extrusion_edit.END_TYPES:
            raise _error("invalid_argument", "end_type must be blind, through_all or up_to_face")
        if end_type == "up_to_face" or "up_to_face" in req:
            from . import selectors, reference_tools
            reference = selectors.native_reference(doc, req.get("up_to_face"), entity_type="face")
            target = doc.getObject(reference["feature"])
            aux = doc.addObject("PartDesign::Body", name + "Carrier")
            _prop(aux, "App::PropertyBool", "KurtShapeInternal", True)
            source = _carrier_binder(aux, profile, [""], name + "Profile")
            stop = _carrier_binder(aux, target, [reference["subelement"]], name + "Stop")
            if reference_tools.is_selector(req["up_to_face"]):
                selectors.bind(stop, "up_to_face", reference_tools.selector_value(req["up_to_face"]), native_property="Support", mode="linksublist")
            doc.recompute()
            tool = aux.newObject("PartDesign::Pad", name)
            tool.Profile = source
            tool.Type = "UpToFace"
            tool.UpToFace = (stop, ["Face1"])
            tool.Reversed = _bool(req, "reversed", False)
            _prop(tool, "App::PropertyBool", "KurtShapeInternal", True)
            doc.recompute()
            if tool.Shape.isNull() or _native_failed(tool):
                raise _error("build_failed", "The up-to-face tool did not produce valid geometry", status=tool.getStatusString())
            return tool
        source = _world_profile(doc, profile, name + "Profile")
        tool = doc.addObject("Part::Extrusion", name)
        tool.Base = source
        _sketch_normal_direction(doc, tool, source, name)
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
        source = _world_profile(doc, profile, name + "Profile")
        tool = doc.addObject("Part::Revolution", name)
        tool.Source = source
        from .modeling_geometry import bind_revolve_axis, is_reference
        if is_reference(req.get("axis")):
            bind_revolve_axis(doc, tool, req["axis"])
        else:
            tool.Base, tool.Axis = _axis(req)
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
        if App.GuiUp and getattr(path, "KurtShapeCurve", False):
            # Consumed like a profile sketch.
            path.ViewObject.Visibility = False
        source = _world_profile(doc, profile, name + "Profile")
        tool = doc.addObject("Part::Sweep", name)
        tool.Sections = [source]
        tool.Spine = (spine, [])
        tool.Solid = True
        tool.Frenet = _bool(req, "frenet", False)
    elif op == "loft":
        sections = req.get("sections")
        if not isinstance(sections, list) or len(sections) < 2:
            raise _error("invalid_argument", "Loft needs at least two sketch sections")
        profiles = [controller._profile(doc, item) for item in sections]
        sources = [_world_profile(doc, profile, name + "Section") for profile in profiles]
        tool = doc.addObject("Part::Loft", name)
        tool.Sections = sources
        tool.Solid = True
        tool.Ruled, tool.Closed = _bool(req, "ruled"), _bool(req, "closed")
    else:
        raise _error("unsupported_operation", "Unsupported studio tool")
    _prop(tool, "App::PropertyBool", "KurtShapeInternal", True)
    doc.recompute()
    if tool.Shape.isNull() or not tool.Shape.Solids or _native_failed(tool):
        if op in {"pad", "pocket"}:
            from .extrusion_edit import open_profile_error
            gap = open_profile_error(profile)
            if gap is not None:
                raise gap
        raise _error("build_failed", "The native tool did not produce valid solid geometry", status=tool.getStatusString())
    return tool


def _negligible(before, tool):
    """Largest volume change that counts as "nothing" for one part.

    OCCT's volume of curved (BSpline) solids carries noise of about 1e-7 of
    the part's volume: a helical cut that OCCT silently missed still "removed"
    0.005 mm3 of a 9486 mm3 drill. Pocket's 1e-7 mm3 stays the floor. Taking
    the smaller of the part and tool scales keeps small real cuts on large
    parts (a pin hole in a block) above the limit.
    """
    return max(1e-7, min(1e-6 * abs(before), 1e-5 * abs(tool)))


def _union_box(boxes):
    low = [min(box["min"][axis] for box in boxes) for axis in range(3)]
    high = [max(box["max"][axis] for box in boxes) for axis in range(3)]
    return {"min": low, "max": high, "size": [b - a for a, b in zip(low, high)]}


def _outside(inner, outer):
    """Largest distance the inner box sticks out of the outer box (0 if inside)."""
    return max(max(outer["min"][axis] - inner["min"][axis], inner["max"][axis] - outer["max"][axis], 0.0)
               for axis in range(3))


def _measure(facts, obj, shape, field, own=True):
    """A volume or tight box; through the GeometryCache when ``shape`` is the object's own (3.2 F1 §5.5)."""
    if facts is not None and obj is not None and own:
        return facts.facts(obj, (field,))[field]
    return geometry.scalar(shape, "volume") if field == "volume" else geometry.tight_bounding_box(shape)


def _result_pair(output):
    """``(body, tip, shape, own)`` for a Body (its Tip) or an explicit ``(body, tip)`` pair at a history position.

    ``own`` is True when ``shape`` is the Body's current shape (cacheable by the Body's identity).
    """
    if isinstance(output, tuple):
        body, tip = output
        if body is None or tip is None:
            return body, tip, None, False
        if body.Tip is not None and body.Tip.Name == tip.Name:
            return body, tip, body.Shape, True
        shape = tip.Shape.copy()
        shape.Placement = body.Placement.multiply(shape.Placement)
        return body, tip, shape, False
    return output, output.Tip, output.Shape, True


def _check_result(doc, name, operation, tool_body, snapshots, outputs, kernel=True, recompute=True, facts=None):
    """Post-conditions of one Add/Remove/Intersect result; returns its report.

    Native success and one solid are checked first, then (with `kernel`)
    BRepCheck; volumes must be possible for the Boolean kind, and (with
    `kernel`) tight result bounds must stay inside what the Boolean can reach
    and an Add must add material.
    A failed OCCT Boolean can pass BRepCheck: a refined helical cut that
    removed its whole tool volume (cutting a solid inside out) did. Every
    rejection names the operation as `feature` and the affected `part`.
    """
    began = time.perf_counter()
    if recompute:
        doc.recompute()
    cache = facts
    if tool_body is None or tool_body.Shape.isNull():
        raise _error("build_failed", f"{name} has no tool solid to check", feature=name)
    tool_volume = _measure(cache, tool_body, tool_body.Shape, "volume")
    if operation == "add":
        rows = [(snapshots[0][0], [source for _, source in snapshots], outputs[0])]
    else:
        rows = [(key, [source], output) for (key, source), output in zip(snapshots, outputs)]
    facts = []
    for key, sources, output in rows:
        body, tip, shape, own = _result_pair(output)
        if body is None or tip is None or shape is None:
            raise _error("build_failed", f"{name} lost a recorded output for part {key}", feature=name, part=key)
        if any(source is None or source.Shape.isNull() for source in sources):
            raise _error("build_failed", f"{name} lost a recorded input snapshot for part {key}", feature=name, part=key)
        if shape.isNull() or len(shape.Solids) != 1 or _native_failed(body) or tip and _native_failed(tip):
            raise _error("build_failed", f"{name} did not produce one valid solid for part {key}",
                         feature=name, part=key, body=body.Name, status=tip.getStatusString() if tip else body.getStatusString())
        facts.append((key, sources, (body, shape, own), [_measure(cache, source, source.Shape, "volume") for source in sources],
                      _measure(cache, body, shape, "volume", own)))
    if kernel:
        for key, sources, (body, shape, own), before, after in facts:
            check = geometry.check_shape(shape.copy())
            if not check["valid"]:
                raise _error("invalid_geometry", f"{name} produced an invalid solid for part {key} (BRepCheck)",
                             feature=name, part=key, check="brepcheck", issues=check["issues"])
    if tool_volume <= 1e-7:
        raise _error("invalid_geometry", f"The {name} tool solid has no positive volume (empty or inside out)",
                     feature=name, check="tool", tool_volume_mm3=tool_volume)
    for key, sources, (body, shape, own), before, after in facts:
        slack = max(1e-7, 1e-6 * (sum(abs(value) for value in before) + abs(tool_volume)))
        if operation == "remove":
            low, high = sum(before) - tool_volume, sum(before)
        elif operation == "intersect":
            low, high = 0.0, min(sum(before), tool_volume)
        else:
            low, high = max(max(before), tool_volume), sum(before) + tool_volume
        if not low - slack <= after <= high + slack:
            raise _error("invalid_geometry", f"{name} left part {key} with {after:.6g} mm3, outside the "
                         f"{low:.6g}..{high:.6g} mm3 a {operation} with a {tool_volume:.6g} mm3 tool can give",
                         feature=name, part=key, check="volume", volume_before_mm3=sum(before),
                         volume_after_mm3=after, tool_volume_mm3=tool_volume)
    if kernel:
        tool_box = _measure(cache, tool_body, tool_body.Shape, "bbox") if operation != "remove" else None
        for key, sources, (body, shape, own), before, after in facts:
            boxes = [_measure(cache, source, source.Shape, "bbox") for source in sources]
            reach = _union_box(boxes + [tool_box]) if operation == "add" else boxes[0]
            box = _measure(cache, body, shape, "bbox", own)
            outside = _outside(box, reach)
            if operation == "intersect":
                outside = max(outside, _outside(box, tool_box))
            if outside > max(1e-3, 1e-6 * math.dist(reach["min"], reach["max"])):
                raise _error("invalid_geometry", f"{name} result for part {key} reaches {outside:.6g} mm beyond "
                             f"what a {operation} can give (failed Boolean)", feature=name, part=key, check="bounds",
                             outside_mm=outside, bbox_mm=box, allowed_bbox_mm=reach)
    parts = [{"part": key, "body": body.Name, "volume_before_mm3": sum(before), "volume_after_mm3": after,
              "volume_delta_mm3": after - sum(before), **({"merged_parts": [row[0] for row in snapshots]}
                                                         if operation == "add" else {})}
             for key, sources, (body, shape, own), before, after in facts]
    if operation == "remove" and not any(sum(before) - after > _negligible(sum(before), tool_volume)
                                         for key, sources, (body, shape, own), before, after in facts):
        raise _error("empty_cut", f"{name} removed no material from the selected scope", feature=name, parts=parts,
                     tool_volume_mm3=tool_volume)
    # The live GUI preview shows a reversed Add's tool on the unchanged part;
    # acceptance rejects it.
    if operation == "add" and len(snapshots) == 1 and kernel:
        key, sources, (body, shape, own), before, after = facts[0]
        if after - before[0] <= _negligible(before[0], tool_volume):
            raise _error("empty_add", f"{name} added no material to part {key}", feature=name, parts=parts,
                         tool_volume_mm3=tool_volume)
    return {"feature": name, "operation": operation, "tool_volume_mm3": tool_volume,
            "volume_delta_mm3": sum(row["volume_delta_mm3"] for row in parts), "parts": parts,
            "geometry_check": "valid" if kernel else "not_checked", "check_ms": (time.perf_counter() - began) * 1000}


def _checked_result(doc, req, name, operation, tool_body, snapshots, outputs, booleans, refine):
    """Verify a result; a refined result that fails is retried once unrefined."""
    # "live": the GUI's per-edit preview, without BRepCheck, bounds or empty Add.
    kernel = req.get("_result_checks") != "live"
    try:
        report = _check_result(doc, name, operation, tool_body, snapshots, outputs, kernel)
        report["refine"] = {"requested": refine, "applied": refine, "retried_unrefined": False}
        return report
    except Exception as exc:
        code = getattr(exc, "code", None)
        if not refine or code not in {"build_failed", "invalid_geometry", "empty_cut", "empty_add"}:
            raise
        refined = {"code": code, "message": str(exc), **{key: value for key, value in exc.details.items()
                                                          if key in {"check", "part", "issues"}}}
    _set_refine(snapshots, booleans, False)
    for boolean in booleans:
        _evaluate_boolean(doc, boolean)
    try:
        report = _check_result(doc, name, operation, tool_body, snapshots, outputs, kernel)
    except Exception as exc:
        if hasattr(exc, "details"):
            exc.details["refine"] = {"requested": True, "retried_unrefined": True, "refined_failure": refined,
                                     "hint": "The unrefined retry failed too. A refined earlier result in this part "
                                             "(for example a previous helical cut) can cause this; rebuild it with "
                                             "refine:false"}
        raise
    report["refine"] = {"requested": True, "applied": False, "retried_unrefined": True, "refined_failure": refined}
    return report


def operation_inputs(doc, rep):
    """``(operation, tool_body, snapshots, outputs, booleans)`` of a recorded result operation.

    snapshots are ``(part id, snapshot Body)`` pairs, outputs ``(output Body, recorded tip)`` pairs
    and booleans the PartDesign::Boolean tips, as the operation left them (F1 D2).
    """
    request = json.loads(getattr(rep, "KurtShapeStudioOperation", "") or "{}")
    operation = request.get("operation", "remove" if request.get("op") == "pocket" else "new")
    tool_body = getattr(rep, "KurtShapeNeutralToolBody", None)
    snapshots = list(zip(getattr(rep, "KurtShapeInputPartIds", []), getattr(rep, "KurtShapeInputSnapshots", [])))
    names, tips = list(getattr(rep, "KurtShapeOutputParts", [])), list(getattr(rep, "KurtShapeOutputTips", []))
    outputs = [(doc.getObject(body), doc.getObject(tips[index]) if index < len(tips) else None)
               for index, body in enumerate(names)]
    booleans = [tip for _, tip in outputs if tip is not None and tip.TypeId == "PartDesign::Boolean"]
    return operation, tool_body, snapshots, outputs, booleans


def refine_state(rep):
    """``{requested, applied}``: the recorded refine request and whether every Boolean tip is refined now."""
    request = json.loads(getattr(rep, "KurtShapeStudioOperation", "") or "{}")
    requested = request.get("refine", True)
    booleans = operation_inputs(rep.Document, rep)[4]
    applied = all(bool(getattr(boolean, "Refine", False)) for boolean in booleans) if booleans else bool(requested)
    return {"requested": bool(requested) if isinstance(requested, bool) else True, "applied": applied}


def check_operation(doc, rep, kernel=True, facts=None):
    """Run the 3.1 post-conditions of a recorded result operation at its own history position.

    No recompute: the recorded tips, tool Body and snapshots are read as they are, so a
    later feature (a fillet moving the Body Tip) never enters the check. Adds the refine state.
    """
    operation, tool_body, snapshots, outputs, _ = operation_inputs(doc, rep)
    report = _check_result(doc, rep.Name, operation, tool_body, snapshots, outputs, kernel, recompute=False, facts=facts)
    state = refine_state(rep)
    report["refine"] = {"requested": state["requested"], "applied": state["applied"], "retried_unrefined": False}
    return report


def retry_unrefined(controller, doc, rep):
    """The creation-time unrefined retry for a history failure (F1 D6), inside the request's transaction.

    Unrefines the snapshots and Boolean tips, evaluates the Booleans exactly and then with native
    automatic fuzz where exact fails, and runs one managed recompute; the caller re-gates and re-keys.
    """
    _, _, snapshots, _, booleans = operation_inputs(doc, rep)
    _set_refine(snapshots, booleans, False)
    for boolean in booleans:
        _evaluate_boolean(doc, boolean)
    controller._recompute(doc)


def _result_operation(controller, doc, req, name):
    operation = req.get("operation", "remove" if req["op"] == "pocket" else "new")
    if operation not in RESULT_OPERATIONS:
        raise _error("invalid_argument", "Operation must be new, add, remove or intersect")
    refine = _bool(req, "refine", True)
    tool = _tool(controller, doc, req, name if operation == "new" else name + "Tool")
    tool_body = _output(doc, tool, name + "ToolBody")
    _prop(tool_body, "App::PropertyBool", "KurtShapeInternal", True)
    doc.recompute()
    if operation == "new":
        _prop(tool_body, "App::PropertyBool", "KurtShapeInternal", False)
        profile = doc.getObject(req.get("profile", "") or (req.get("sections", [""])[0] if req.get("sections") else ""))
        source_owner = _body_owner(profile) if profile else None
        if (source_owner and part_id(source_owner) not in _state(doc, _cutoff(doc))
                and part_id(source_owner) not in held_part_ids(doc)):
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
            if _pair_matches(doc, body, tool, operation, first=shape):
                chosen.append(part_id(body))
    elif isinstance(scope, list) and scope:
        chosen = [part_id(current_part(doc, item)) for item in scope]
        if len(set(chosen)) != len(chosen):
            raise _error("invalid_argument", "Merge scope must contain distinct part IDs")
    else:
        raise _error("invalid_argument", "Merge scope must be auto or a nonempty part list")
    if not chosen:
        # B3 (slice A/B U9): an auto scope the tool touches nowhere; say which direction to try.
        tool_volume = tool_body.Shape.Volume if not tool_body.Shape.isNull() else 0.0
        raise _error("empty_merge_scope", "The result does not touch a part in the selected scope",
                     tool_volume_mm3=tool_volume,
                     **direction_hint(req, "touches no part"))
    snapshots = _inputs(doc, chosen, name, refine)
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
                                      name, snapshots[0][0], getattr(first, "KurtShapePartName", first.Label), "union",
                                      refine)
        outputs.append(result)
        reps.append(rep)
    else:
        for index, (key, source) in enumerate(snapshots):
            original = current_part(doc, key)
            result, rep = _native_boolean(doc, source, [tool_body], name if index == 0 else name + "Result", key,
                                          getattr(original, "KurtShapePartName", original.Label),
                                          "subtract" if operation == "remove" else "intersect", refine)
            outputs.append(result)
            reps.append(rep)
    try:
        report = _checked_result(doc, req, name, operation, tool_body, snapshots, outputs, reps, refine)
    except Exception as exc:
        # B3 (slice A/B U9): an empty Remove or Add names the direction to try beside its tool volume.
        outcome = {"empty_cut": "removed no material", "empty_add": "added no material"}.get(getattr(exc, "code", None))
        if outcome and hasattr(exc, "details"):
            for key, value in direction_hint(req, outcome).items():
                exc.details.setdefault(key, value)
        raise
    controller._reports["result_report"] = report
    _prop(reps[0], "App::PropertyLinkGlobal", "KurtShapeTool", tool)
    _prop(reps[0], "App::PropertyLinkGlobal", "KurtShapeNeutralToolBody", tool_body)
    if through and tool.TypeId == "Part::Extrusion":
        _prop(reps[0], "App::PropertyLinkGlobal", "KurtShapeScopeBounds", bounds)
    _prop(reps[0], "App::PropertyStringList", "KurtShapeMergePartIds", chosen)
    recorded = _record(doc, reps[0], req, outputs, chosen, snapshots)
    checks = getattr(controller, "result_checks", None)
    if checks is not None and req.get("_result_checks") != "live":
        # Seed the history validator (contract 3.2 F1 D9): the post-dispatch validation reuses this
        # verdict through its creation key instead of running a second BRepCheck.
        checks.remember(doc, reps[0].Name, report)
    return recorded


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
        if isinstance(mirror, (dict, str)):
            from .modeling_geometry import bind_mirror_plane
            bind_mirror_plane(doc, shape, mirror)
        else:
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
    return App.Vector(*geometry.scalar(face, "center_of_mass")), face.normalAt(0, 0)


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
                    _prop(obj, "App::PropertyString", "KurtShapePartName", name)
            _name_part(doc, body, name)
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
        if kind not in BOOLEAN_KINDS:
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
        if copy:
            output.Label = req.get("name", getattr(original, "KurtShapePartName", original.Label) + " copy")
        elif "name" in req:
            _prop(output, "App::PropertyString", "KurtShapePartName", req["name"])
        _validate(doc, [output])
        return _record(doc, representative, req, [output], [] if copy else [part_id(original)], snapshots)
    if op in {"linear_pattern_parts", "circular_pattern_parts", "mirror_parts"}:
        operation = req.get("operation", "new")
        if operation not in RESULT_OPERATIONS:
            raise _error("invalid_argument", "Operation must be new, add, remove or intersect")
        # Feature-pattern semantics: the source parts act together with their
        # copies, as consumed tools (boolean_parts tools), never as targets.
        include_source = _bool(req, "include_source", False)
        if include_source and operation not in {"add", "remove"}:
            # Intersect against several patterned tools is ambiguous (each
            # instance in turn, or the union of instances) and the native
            # multi-tool Common splits its result; ask for an explicit union.
            raise _error("invalid_argument", "include_source requires operation add or remove; for intersect, "
                         "fuse the tools with boolean_parts first")
        snapshots = _inputs(doc, req.get("parts"), name)
        source_ids = [key for key, _ in snapshots]
        if include_source and isinstance(req.get("merge_scope"), list):
            overlap = [item for item in req["merge_scope"]
                       if isinstance(item, str) and part_id(current_part(doc, item)) in source_ids]
            if overlap:
                raise _error("invalid_argument", "merge_scope must not contain a pattern source part when include_source is true",
                             parts=overlap)
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
            if "plane" in req:
                if "origin" in req or "normal" in req:
                    raise _error("invalid_argument", "Choose one mirror plane or an origin and normal")
                mirror = req["plane"]
            else:
                mirror = (_vector(req.get("origin"), "origin", [0, 0, 0]),
                          _vector(req.get("normal"), "normal", [1, 0, 0], True))
            placements = [App.Placement()]
        outputs, reps = [], []
        for key, source in snapshots:
            for placement in placements:
                output, rep = _copy_result(doc, source, placement, name if not reps else name + "Instance", mirror=mirror)
                source_part = current_part(doc, key)
                output.Label = getattr(source_part, "KurtShapePartName", source_part.Label) + " pattern"
                outputs.append(output)
                reps.append(rep)
        _validate(doc, outputs)
        if operation != "new":
            copies = outputs
            for body in copies:
                _prop(body, "App::PropertyBool", "KurtShapeInternal", True)
                # Consumed copies are not outputs; _record's closure does not
                # reach a Body from its features, so tag them for deletion.
                _prop(body, "App::PropertyString", "KurtShapeOperationOwner", reps[0].Name)
            scope = req.get("merge_scope", "auto")
            candidates = current_parts(doc) if scope == "auto" else [current_part(doc, key) for key in scope] if isinstance(scope, list) and scope else []
            if not candidates:
                raise _error("empty_merge_scope", "Pattern merge scope must be auto or a nonempty part list")
            # Source snapshots are this history position's source geometry.
            source_tools = [source for key, source in snapshots] if include_source else []
            tools_pool = copies + source_tools
            if include_source:
                candidates = [body for body in candidates if part_id(body) not in source_ids]
                if not candidates:
                    raise _error("empty_merge_scope", "No part other than the pattern sources is in the merge scope")
            relevant = {}
            for body in candidates:
                matching = [copy for copy in tools_pool if _pair_matches(doc, body, copy, operation)]
                if matching:
                    relevant[part_id(body)] = matching
            if not relevant:
                raise _error("empty_merge_scope", "Pattern copies do not touch the selected scope")
            if include_source and operation == "add":
                # Add would otherwise discard an authored source solid or copy.
                touched = {tool.Name for tools in relevant.values() for tool in tools}
                loose = [key for key, source in zip(source_ids, source_tools) if source.Name not in touched]
                if loose:
                    raise _error("empty_merge_scope", "An included source part does not touch the merge scope", parts=loose)
                loose_copies = [copy.Label for copy in copies if copy.Name not in touched]
                if loose_copies:
                    raise _error("empty_merge_scope", "A pattern copy does not touch the merge scope", copies=loose_copies)
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
            _prop(reps[0], "App::PropertyStringList", "KurtShapePatternToolParts", [copy.Name for copy in tools_pool])
            consumed = list(relevant)
            if include_source:
                _prop(reps[0], "App::PropertyStringList", "KurtShapePatternSourceParts", source_ids)
                consumed += source_ids
            return _record(doc, reps[0], req, outputs, consumed, snapshots)
        return _record(doc, reps[0], req, outputs, snapshots=snapshots)
    raise _error("unsupported_operation", "Unsupported studio operation")
