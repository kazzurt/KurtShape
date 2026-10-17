"""Native PartDesign Hole on a current part (Onshape Hole parity).

The hole is one native ``PartDesign::Hole`` appended to the part's current
Body, like a fillet. Hole centres are the non-construction full circles and
standalone points of a sketch (native ``BaseProfileType`` 3: points and
circles; arcs and lines are ignored). Holes drill against the sketch normal,
into the material, unless ``reversed``.

Depth convention: ``depth`` is the blind depth of the full-diameter portion,
measured along the drilling direction from the sketch plane to the start of
the drill point (native ``DrillForDepth`` false). An angled point adds a cone
of height ``(diameter / 2) / tan(point_angle / 2)`` beyond it. A counterbore or
countersink lies inside that depth, from the sketch plane. Native Hole clamps a
blind depth to its through-all length (about 2.02 x the part's bounding-box
diagonal); a deeper request is rejected with that maximum instead.

Profile scope. A sketch in the part's current Body is the native Profile, and
native Hole follows it fully (circles added later become holes). A sketch in
another Body (KurtShape's authoring Body) reaches the part through a native
in-Body bridge, because a PartDesign Profile outside its Body is out of link
scope (FreeCAD warns and ignores the Body placement), and a binder used as
Profile loses the drilling sign: native Hole takes a non-sketch profile's
direction from an unsigned plane fit, and finds no plane for points at all.
The bridge keeps the authored sketch frame exactly:

* ``<id>Source``: ``PartDesign::ShapeBinder`` of the whole sketch with
  ``TraceSupport``, so its Placement is the sketch frame in Body coordinates.
* ``<id>Centres``: ``PartDesign::ShapeBinder`` of only the bound centre
  elements, points first, then circles. Its ``Support`` is a native element
  reference into the sketch, which FreeCAD re-resolves through the sketch's
  element map (``g<geometry id>;SKT``) whenever the sketch renumbers its shape,
  so its compound is always Vertex1..P = the points, Edge1..C = the circles.
* ``<id>Profile``: an internal ``Sketcher::SketchObject`` attached
  ``ObjectXY`` to ``<id>Source``, holding one defining external geometry per
  centre from ``<id>Centres`` (``Vertex<k>``/``Edge<k>``, stable by the order
  above) and the bound geometry ids in ``KurtShapeHoleCentres``. Hole reads
  its normal from this sketch.

All helpers carry ``KurtShapeInternal``, ``KurtShapeHoleHelper`` and
``KurtShapeOperationOwner`` (the Hole), are deleted with their Hole (see
``private_helpers``), and cannot be used as profiles or deleted alone.

Associativity of the bridge: moving or resizing the bound circles and points,
moving the sketch plane, and edits that renumber the sketch shape (adding or
deleting other geometry, joining or closing polylines) keep every hole on its
centre. Centres added to the sketch later are not picked up (the hole keeps
the centres it was created with, as Onshape does). A bound centre that is
deleted, made construction or changed into another kind of geometry fails the
build visibly (``bridge_errors``), as does a native hole count that differs
from the bound centre count.
"""
import math

import FreeCAD as App

ARGS = {"id", "part", "sketch", "diameter", "depth", "end_type", "point_angle", "reversed",
        "counterbore", "countersink"}
CUT_ARGS = {"counterbore": {"diameter", "depth"}, "countersink": {"diameter", "angle"}}
# Native Hole BaseProfileType bits: 1 standalone points, 2 circles, 4 arcs.
PROFILE_POINTS_AND_CIRCLES = 3
MAX_HOLES = 256
DEFAULT_POINT_ANGLE = "118 deg"
DEFAULT_COUNTERSINK_ANGLE = "90 deg"
# Included angles outside this range give degenerate cones (a 1e-9 rad point
# is an extremely long spike; 180 deg is flat but is spelled "flat").
MIN_ANGLE, MAX_ANGLE = 1.0, 179.0
POSITION_TOLERANCE = 1e-6
CENTRES = "KurtShapeHoleCentres"


def _error(code, message, **details):
    from .core import OperationError
    return OperationError(code, message, **details)


def _prop(obj, kind, name, value):
    if name not in obj.PropertiesList:
        obj.addProperty(kind, name, "KurtShape")
    setattr(obj, name, value)


def _degrees(degrees, name, allow_flat=False):
    if not MIN_ANGLE <= degrees <= MAX_ANGLE:
        raise _error("invalid_argument", f"{name} must be between {MIN_ANGLE:g} and {MAX_ANGLE:g} deg"
                     + (' (0 or "flat" for a flat bottom)' if allow_flat else ""), **{name.replace(".", "_") + "_deg": degrees})
    return degrees


def _angle(value, name, allow_flat=False):
    """Included angle in degrees, or None for a flat bottom."""
    from .core import number
    if allow_flat and isinstance(value, str) and value.strip().lower() == "flat":
        return None
    radians = number(value, name, False, "rad")
    if allow_flat and radians == 0:
        return None
    return _degrees(math.degrees(radians), name, allow_flat)


def _cut(req, kind, diameter):
    spec = req.get(kind)
    if not isinstance(spec, dict):
        raise _error("invalid_argument", f"{kind} must be an object with {' and '.join(sorted(CUT_ARGS[kind]))}")
    unknown = sorted(set(spec) - CUT_ARGS[kind])
    if unknown:
        raise _error("unknown_argument", f"Unknown {kind} field(s): {', '.join(unknown)}", fields=unknown)
    from .core import number
    cut_diameter = number(spec.get("diameter"), f"{kind}.diameter", True)
    if kind == "counterbore":
        return cut_diameter, number(spec.get("depth"), "counterbore.depth", True)
    return cut_diameter, _angle(spec.get("angle", DEFAULT_COUNTERSINK_ANGLE), "countersink.angle")


def _countersink_height(diameter, cut_diameter, angle):
    return (cut_diameter - diameter) / 2 / math.tan(math.radians(angle) / 2)


def _check_settings(diameter, depth, point_angle, cut):
    """Plausibility of one hole's dimensions, before any native build."""
    if point_angle is not None:
        _degrees(point_angle, "point_angle", True)
    if cut is None:
        return
    kind, cut_diameter, value = cut
    if cut_diameter <= diameter + 1e-9:
        raise _error("invalid_argument", f"{kind}.diameter must be larger than the hole diameter",
                     diameter=diameter, **{kind + "_diameter": cut_diameter})
    if kind == "counterbore":
        if depth is not None and value >= depth - 1e-9:
            raise _error("invalid_argument", "counterbore.depth must be less than the hole depth",
                         depth=depth, counterbore_depth=value)
        return
    _degrees(value, "countersink.angle")
    height = _countersink_height(diameter, cut_diameter, value)
    if depth is not None and height >= depth - 1e-9:
        raise _error("invalid_argument", f"The countersink is {height:.6g} mm deep; it must be shallower than the hole depth",
                     depth=depth, countersink_height=height)


def _settings(hole):
    """Current KurtShape-relevant dimensions of a native Hole."""
    diameter = hole.Diameter.Value
    through = str(hole.DepthType) != "Dimension"
    depth = None if through else hole.Depth.Value
    point_angle = None if through or str(hole.DrillPoint) != "Angled" else hole.DrillPointAngle.Value
    kind = str(hole.HoleCutType).lower()
    cut = None
    if kind == "counterbore":
        cut = (kind, hole.HoleCutDiameter.Value, hole.HoleCutDepth.Value)
    elif kind == "countersink":
        cut = (kind, hole.HoleCutDiameter.Value, hole.HoleCutCountersinkAngle.Value)
    return diameter, depth, point_angle, cut


def _position(geometry):
    import Part
    if type(geometry) is Part.Circle:
        return App.Vector(geometry.Center)
    return App.Vector(geometry.X, geometry.Y, geometry.Z)


def hole_centres(sketch):
    """Native hole centres: non-construction full circles and standalone points."""
    import Part
    centres = []
    for index, geometry in enumerate(sketch.Geometry):
        if sketch.getConstruction(index):
            continue
        if type(geometry) is Part.Circle:
            centres.append(("circle", index, App.Vector(geometry.Center)))
        elif type(geometry) is Part.Point:
            centres.append(("point", index, App.Vector(geometry.X, geometry.Y, geometry.Z)))
    return centres


def _element(sketch, kind, index):
    """Indexed sketch-Shape element of geometry ``index`` (Edge for circles, Vertex for points).

    The sketch element map is keyed by the persistent geometry id, which
    differs from the list index once any geometry has been deleted.
    """
    import Part
    geometry_id = sketch.getGeometryId(index)
    mapped = f"g{geometry_id};SKT" if kind == "circle" else f"g{geometry_id}v1;SKT"
    element = sketch.Shape.ElementMap.get(mapped, "")
    if element.startswith("Edge" if kind == "circle" else "Vertex"):
        return element
    # Fallback: match the element geometrically in sketch coordinates.
    local = sketch.Shape.copy()
    local.Placement = App.Placement()
    geometry = sketch.Geometry[index]
    if kind == "circle":
        for number, edge in enumerate(local.Edges, 1):
            curve = edge.Curve
            if (type(curve) is Part.Circle and edge.isClosed() and abs(curve.Radius - geometry.Radius) < 1e-7
                    and (curve.Center - geometry.Center).Length < 1e-7):
                return f"Edge{number}"
    else:
        point = _position(geometry)
        on_edges = {tuple(round(c, 9) for c in vertex.Point) for edge in local.Edges for vertex in edge.Vertexes}
        for number, vertex in enumerate(local.Vertexes, 1):
            if (vertex.Point - point).Length < 1e-7 and tuple(round(c, 9) for c in vertex.Point) not in on_edges:
                return f"Vertex{number}"
    raise _error("missing_reference", "A hole centre is not part of the sketch shape; recompute the sketch",
                 sketch=sketch.Name, geometry=index)


def _unique(doc, name):
    if doc.getObject(name) is None:
        return name
    number = 1
    while doc.getObject(f"{name}{number:03d}") is not None:
        number += 1
    return f"{name}{number:03d}"


def _internal(obj, owner_name):
    _prop(obj, "App::PropertyBool", "KurtShapeInternal", True)
    _prop(obj, "App::PropertyString", "KurtShapeOperationOwner", owner_name)
    _prop(obj, "App::PropertyBool", "KurtShapeHoleHelper", True)
    if App.GuiUp and getattr(obj, "ViewObject", None) is not None:
        obj.ViewObject.Visibility = False


def _failed(obj):
    return obj.Shape.isNull() or bool({"Invalid", "Error"} & set(obj.State))


def _bridge_profile(doc, body, sketch, centres, name):
    """In-Body frame and centre binders plus an internal sketch in the authored sketch frame."""
    # Points first: the centre binder's compound is then Vertex1..P = points, Edge1..C = circles.
    ordered = [centre for centre in centres if centre[0] == "point"] + [centre for centre in centres if centre[0] == "circle"]
    elements = [_element(sketch, kind, index) for kind, index, _ in ordered]
    frame = body.newObject("PartDesign::ShapeBinder", _unique(doc, name + "Source"))
    _internal(frame, name)
    frame.Support = [(sketch, [""])]
    frame.TraceSupport = True
    bound = body.newObject("PartDesign::ShapeBinder", _unique(doc, name + "Centres"))
    _internal(bound, name)
    bound.Support = [(sketch, elements)]
    bound.TraceSupport = True
    profile = body.newObject("Sketcher::SketchObject", _unique(doc, name + "Profile"))
    _internal(profile, name)
    profile.AttachmentSupport = [(frame, [""])]
    profile.MapMode = "ObjectXY"
    doc.recompute()
    for binder in (frame, bound):
        if _failed(binder):
            raise _error("build_failed", "The hole sketch could not be bound into the part's Body",
                         feature=binder.Name, status=binder.getStatusString())
    points = sum(1 for kind, _, _ in ordered if kind == "point")
    for k, (kind, _, _) in enumerate(ordered):
        profile.addExternal(bound.Name, f"Vertex{k + 1}" if kind == "point" else f"Edge{k + 1 - points}", True, False)
    _prop(profile, "App::PropertyStringList", CENTRES,
          [f"{kind}:{sketch.getGeometryId(index)}" for kind, index, _ in ordered])
    profile.setEditorMode(CENTRES, 1)
    doc.recompute()
    if {"Invalid", "Error"} & set(profile.State):
        raise _error("build_failed", "The hole centres could not be referenced in the part's Body",
                     feature=profile.Name, status=profile.getStatusString())
    errors = _centre_errors(profile)
    if errors:
        raise _error("missing_reference", errors[0]["message"], feature=profile.Name, centres=errors)
    return profile


def _record(profile):
    entries = []
    for entry in getattr(profile, CENTRES, []):
        kind, _, number = entry.partition(":")
        entries.append((kind, int(number)))
    return entries


def _authored(profile):
    """(centre binder, authored sketch) of a bridged profile, or (None, None)."""
    sources = [source for source, _ in profile.ExternalGeometry]
    binder = sources[0] if sources and all(source == sources[0] for source in sources) else None
    support = getattr(binder, "Support", None) or []
    sketch = support[0][0] if len(support) == 1 else None
    if sketch is None or sketch.TypeId != "Sketcher::SketchObject":
        return binder, None
    return binder, sketch


def _centre_errors(profile, positions=True):
    """Bound centres that no longer exist in the authored sketch or sit elsewhere.

    Cheap reads only (geometry ids, types, coordinates); no kernel checks. The
    profile frame is the authored sketch frame, so the external centres must
    equal the authored centres in local coordinates.
    """
    import Part
    owner_name = getattr(profile, "KurtShapeOperationOwner", "")
    binder, sketch = _authored(profile)
    if sketch is None:
        return [{"feature": owner_name, "input": "HoleCentres", "code": "missing_reference", "reference_health": "missing",
                 "message": "The hole's authored sketch is missing; recreate the hole"}]
    externals = profile.ExternalGeo[2:]
    entries = _record(profile)
    errors = []
    if not entries:
        # Holes from the first bridge (no KurtShapeHoleCentres) reference the
        # whole-sketch binder by position: each external must still be an authored centre.
        if not positions:
            return []
        authored = [(kind, position) for kind, _, position in hole_centres(sketch)]
        kinds = {Part.Circle: "circle", Part.Point: "point"}
        for k, geometry in enumerate(externals):
            kind = kinds.get(type(geometry))
            if kind is None or not any(kind == other and (_position(geometry) - position).Length <= POSITION_TOLERANCE
                                       for other, position in authored):
                errors.append({"feature": owner_name, "input": f"HoleCentre{k + 1}", "code": "missing_reference",
                               "reference_health": "missing",
                               "message": f"Hole centre {k + 1} no longer matches a circle or point of sketch {sketch.Name}; "
                                          "recreate the hole"})
        return errors
    ids = {sketch.getGeometryId(index): index for index in range(sketch.GeometryCount)}
    geometries = sketch.Geometry
    wanted = {"circle": Part.Circle, "point": Part.Point}
    for k, (kind, geometry_id) in enumerate(entries):
        index = ids.get(geometry_id)
        label = f"{kind} g{geometry_id} of sketch {sketch.Name}"
        if index is None or type(geometries[index]) is not wanted.get(kind) or sketch.getConstruction(index):
            state = ("was deleted" if index is None else "is now construction geometry" if sketch.getConstruction(index)
                     else "is no longer a " + kind)
            errors.append({"feature": owner_name, "input": f"HoleCentre{k + 1}", "code": "missing_reference",
                           "reference_health": "missing", "geometry_id": geometry_id,
                           "message": f"Hole centre {k + 1} ({label}) {state}; edit the sketch or recreate the hole"})
            continue
        if not positions:
            continue
        if k >= len(externals) or type(externals[k]) is not wanted[kind]:
            errors.append({"feature": owner_name, "input": f"HoleCentre{k + 1}", "code": "missing_reference",
                           "reference_health": "missing", "geometry_id": geometry_id,
                           "message": f"Hole centre {k + 1} ({label}) is not referenced by the hole's profile; recreate the hole"})
            continue
        offset = (_position(externals[k]) - _position(geometries[index])).Length
        if offset > POSITION_TOLERANCE:
            errors.append({"feature": owner_name, "input": f"HoleCentre{k + 1}", "code": "missing_reference",
                           "reference_health": "missing", "geometry_id": geometry_id, "offset_mm": offset,
                           "message": f"Hole centre {k + 1} sits {offset:.6g} mm away from {label}; rebuild or recreate the hole"})
    if positions and len(externals) != len(entries):
        errors.append({"feature": owner_name, "input": "HoleCentres", "code": "missing_reference",
                       "reference_health": "missing",
                       "message": f"The hole profile has {len(externals)} centres for {len(entries)} bound sketch centres; recreate the hole"})
    return errors


def _tool_count(hole):
    tools = hole.AddSubShape
    return len(tools.Solids) if not tools.isNull() else 0


def _expected_count(hole):
    profile = hole.Profile[0] if hole.Profile else None
    if profile is None:
        return None
    if getattr(profile, "KurtShapeHoleHelper", False):
        return len(_record(profile)) or len(profile.ExternalGeo) - 2
    return len(hole_centres(profile))


def bridge_errors(profile):
    """Rebuild check of a Hole's bridged profile, for build status (no kernel checks).

    Reports bound centres that were deleted, made construction or changed kind,
    externals that no longer sit on their authored centre, and a native hole
    count that differs from the bound centre count. Position and count checks
    wait while any object of the bridge is still pending a recompute.
    """
    doc = profile.Document
    hole = doc.getObject(getattr(profile, "KurtShapeOperationOwner", ""))
    if hole is None or hole.TypeId != "PartDesign::Hole" or not hole.Profile or hole.Profile[0] != profile:
        return []
    binder, sketch = _authored(profile)
    frame = profile.AttachmentSupport[0][0] if profile.AttachmentSupport else None
    chain = [obj for obj in (sketch, frame, binder, profile, hole) if obj is not None]
    settled = not any("Touched" in obj.State for obj in chain)
    errors = _centre_errors(profile, positions=settled)
    if settled and not errors and not hole.Shape.isNull():
        expected, built = _expected_count(hole), _tool_count(hole)
        if expected is not None and built != expected:
            errors.append({"feature": hole.Name, "input": "HoleCentres", "code": "hole_count_changed",
                           "reference_health": "missing",
                           "message": f"The native hole builds {built} hole(s) for {expected} bound centre(s)"})
    return errors


def _tool_volume(diameter, depth, point_angle, cut):
    """Analytic volume of one blind hole tool (upper bound of what it removes)."""
    radius = diameter / 2
    volume = math.pi * radius * radius * depth
    if point_angle is not None:
        volume += math.pi * radius * radius * (radius / math.tan(math.radians(point_angle) / 2)) / 3
    if cut is not None:
        kind, cut_diameter, value = cut
        outer = cut_diameter / 2
        if kind == "counterbore":
            volume += math.pi * (outer * outer - radius * radius) * value
        else:
            height = (outer - radius) / math.tan(math.radians(value) / 2)
            volume += math.pi * height / 3 * (outer * outer + outer * radius + radius * radius) - math.pi * radius * radius * height
    return volume


def _clamped(hole, prop, wanted):
    """Reject a value native onChanged handlers rewrote (Depth is clamped to the through-all length)."""
    actual = getattr(hole, prop).Value
    if abs(actual - wanted) <= 1e-9 * max(1.0, abs(wanted)):
        return
    if prop == "Depth" and actual < wanted:
        raise _error("invalid_argument", f"depth {wanted:g} mm exceeds the native maximum hole depth of {actual:.6g} mm "
                     "for this part (FreeCAD's through-all length); use a smaller depth or end_type through_all",
                     depth=wanted, maximum_depth=actual)
    raise _error("invalid_argument", f"Native hole changed {prop} from {wanted:g} to {actual:.6g}",
                 feature=hole.Name, requested=wanted, native=actual)


def handle(core, doc, req):
    from .core import OperationError, number
    from .bodies import owner
    body_request = dict(req)
    if "part" in req:
        body_request["body"] = req["part"]
    body = core._body(doc, body_request)
    tip = body.Tip
    if tip is None or tip.Shape.isNull() or not tip.Shape.Solids:
        raise OperationError("missing_body", "Choose a current solid part")
    sketch = doc.getObject(req["sketch"]) if isinstance(req.get("sketch"), str) and req["sketch"] else None
    if sketch is None or sketch.TypeId != "Sketcher::SketchObject" or getattr(sketch, "KurtShapeInternal", False):
        raise OperationError("missing_reference", "sketch must name a native sketch with hole circles or points",
                             sketch=req.get("sketch"))
    if sketch.solve() != 0:
        raise OperationError("constraint_conflict", "Sketch solver reports conflicting constraints", sketch=sketch.Name)
    centres = hole_centres(sketch)
    if not centres:
        raise OperationError("empty_profile", "The sketch has no circles or points to place holes on; "
                             "construction geometry, arcs and lines are not hole centres", sketch=sketch.Name)
    if len(centres) > MAX_HOLES:
        raise OperationError("invalid_argument", f"One hole feature takes at most {MAX_HOLES} centres", count=len(centres))

    diameter = number(req.get("diameter"), "diameter", True)
    end_type = req.get("end_type", "blind")
    if end_type not in {"blind", "through_all"}:
        raise OperationError("invalid_argument", "end_type must be blind or through_all")
    through = end_type == "through_all"
    if through:
        extra = sorted(key for key in ("depth", "point_angle") if key in req)
        if extra:
            raise OperationError("invalid_argument", "A through-all hole takes no " + " or ".join(extra), fields=extra)
        depth, point_angle = None, None
    else:
        depth = number(req.get("depth"), "depth", True)
        point_angle = _angle(req.get("point_angle", DEFAULT_POINT_ANGLE), "point_angle", allow_flat=True)
    reversed_direction = req.get("reversed", False)
    if not isinstance(reversed_direction, bool):
        raise OperationError("invalid_argument", "reversed must be boolean")
    if "counterbore" in req and "countersink" in req:
        raise OperationError("invalid_argument", "Choose either a counterbore or a countersink")
    cut = None
    for kind in ("counterbore", "countersink"):
        if kind in req:
            cut = (kind,) + _cut(req, kind, diameter)
    _check_settings(diameter, depth, point_angle, cut)

    name = core._id(doc, req, "Hole") if "id" in req else _unique(doc, "Hole")
    if owner(doc, sketch) == body:
        profile = sketch
    else:
        profile = _bridge_profile(doc, body, sketch, centres, name)

    hole = body.newObject("PartDesign::Hole", name)
    hole.Profile = profile
    hole.BaseProfileType = PROFILE_POINTS_AND_CIRCLES
    hole.Threaded = False
    hole.ThreadType = "None"
    hole.Tapered = False
    hole.Diameter = diameter
    hole.HoleCutType = "None" if cut is None else cut[0].capitalize()
    if cut is not None:
        hole.HoleCutCustomValues = True
        hole.HoleCutDiameter = cut[1]
        if cut[0] == "counterbore":
            hole.HoleCutDepth = cut[2]
        else:
            hole.HoleCutCountersinkAngle = cut[2]
    hole.DepthType = "ThroughAll" if through else "Dimension"
    if not through:
        hole.Depth = depth
        _clamped(hole, "Depth", depth)
        hole.DrillForDepth = False
        hole.DrillPoint = "Flat" if point_angle is None else "Angled"
        if point_angle is not None:
            hole.DrillPointAngle = point_angle
    hole.Reversed = reversed_direction
    core._recompute(doc)
    _validate(hole, tip, diameter, depth, point_angle, cut, reversed_direction, len(centres))
    body.Tip = hole
    return hole.Name


def _intent(hole):
    """Native values that carry this hole's dimensions (cut values only for its cut type)."""
    diameter, depth, point_angle, cut = _settings(hole)
    values = {"Diameter": diameter, "Depth": depth, "DrillPointAngle": point_angle}
    if cut is not None:
        values["HoleCutDiameter"] = cut[1]
        values["HoleCutDepth" if cut[0] == "counterbore" else "HoleCutCountersinkAngle"] = cut[2]
    return {prop: value for prop, value in values.items() if value is not None}


def _keeps(hole, before, edited):
    """Native onChanged handlers rewrite dependent values (a counterbore grows with the diameter); reject that."""
    for prop, value in before.items():
        actual = getattr(hole, prop).Value
        if prop != edited and abs(actual - value) > 1e-9 * max(1.0, abs(value)):
            raise _error("invalid_argument", f"Native hole would change {prop} from {value:g} to {actual:.6g} for this "
                         f"{edited}; edit {prop} first or recreate the hole", feature=hole.Name, parameter=edited,
                         changed=prop, native=actual)


def _edited(core, doc, hole):
    """The hole operation's own checks after an edit, without kernel BRepCheck."""
    diameter, depth, point_angle, cut = _settings(hole)
    _check_settings(diameter, depth, point_angle, cut)
    core._recompute(doc)
    _validate(hole, hole.BaseFeature, diameter, depth, point_angle, cut, bool(hole.Reversed), _expected_count(hole))


def set_parameter(core, doc, hole, prop, value):
    """set_parameter on a Hole: ``value`` is native (degrees for angles)."""
    before = _intent(hole)
    setattr(hole, prop, value)
    _clamped(hole, prop, value)
    _keeps(hole, before, prop)
    _edited(core, doc, hole)


def set_expression(core, doc, hole, prop, expression):
    """set_expression on a Hole; ``expression`` None clears it."""
    from .core import OperationError
    before = _intent(hole)
    hole.setExpression(prop, expression)
    core._recompute(doc)
    if {"Invalid", "Error"} & set(hole.State):
        raise OperationError("invalid_expression", "Formula is invalid, has a missing reference, or has incompatible units",
                             status=hole.getStatusString())
    if expression is not None:
        _clamped(hole, prop, hole.evalExpression(expression).Value)
    _keeps(hole, before, prop)
    _edited(core, doc, hole)


def _validate(hole, tip, diameter, depth, point_angle, cut, reversed_direction, expected=None):
    from .core import OperationError
    if {"Invalid", "Error"} & set(hole.State) or hole.Shape.isNull():
        raise OperationError("build_failed", "Native hole could not be built", feature=hole.Name,
                             status=hole.getStatusString())
    # Native onChanged handlers can rewrite dependent values; confirm intent.
    settings = [("Diameter", diameter)]
    if depth is not None:
        settings.append(("Depth", depth))
    if cut is not None:
        settings.append(("HoleCutDiameter", cut[1]))
        settings.append(("HoleCutDepth" if cut[0] == "counterbore" else "HoleCutCountersinkAngle", cut[2]))
    for prop, wanted in settings:
        if abs(getattr(hole, prop).Value - wanted) > 1e-9 * max(1.0, abs(wanted)):
            raise OperationError("build_failed", f"Native hole changed {prop} while building", feature=hole.Name)
    solids = len(hole.Shape.Solids)
    if solids != 1:
        raise OperationError("build_failed", f"The holes leave {solids} solids; a hole must keep the part one solid",
                             feature=hole.Name, solid_count=solids)
    count = _tool_count(hole)
    if expected is not None and count != expected:
        raise OperationError("build_failed", f"The native hole builds {count} hole(s) for {expected} centre(s)",
                             feature=hole.Name, hole_count=count, centre_count=expected)
    before, after = tip.Shape.Volume, hole.Shape.Volume
    if after >= before - 1e-7:
        raise OperationError("empty_cut", "The holes remove no material; check the sketch position or set reversed"
                             + ("=false" if reversed_direction else "=true"), feature=hole.Name)
    if depth is not None and count:
        limit = count * _tool_volume(diameter, depth, point_angle, cut) * (1 + 1e-6) + 1e-6 * abs(before)
        if before - after > limit:
            raise OperationError("invalid_geometry", f"The holes removed {before - after:.6g} mm3, more than "
                                 f"{count} hole tool(s) can ({limit:.6g} mm3); the kernel result is likely invalid",
                                 feature=hole.Name, removed_mm3=before - after, limit_mm3=limit)


def public_name(obj):
    """The user-facing feature for an object: a private profile helper reports its Hole."""
    owner_name = getattr(obj, "KurtShapeOperationOwner", "") if getattr(obj, "KurtShapeHoleHelper", False) else ""
    return owner_name if owner_name and obj.Document.getObject(owner_name) is not None else obj.Name


def reject_helper(obj, use):
    """A Hole's private helper is never a user profile or deletion target."""
    if obj is None or not getattr(obj, "KurtShapeHoleHelper", False):
        return
    owner_name = getattr(obj, "KurtShapeOperationOwner", "")
    if obj.Document.getObject(owner_name) is None:
        raise _error("orphan_helpers", f"{obj.Name} is a leftover helper of the removed hole {owner_name}. "
                     "Use Repair leftover helpers.", feature=obj.Name, owner=owner_name)
    code = "missing_reference" if use == "profile" else "unsupported_feature"
    raise _error(code, f"{obj.Name} is the private profile of hole {owner_name}; "
                 + ("use the authored sketch" if use == "profile" else "delete the hole instead"),
                 feature=obj.Name, hole=owner_name)


def private_helpers(doc, owners, removing=()):
    """Names of the private profile helpers owned by these Hole features.

    Used by feature deletion so the in-Body binders and internal sketch go with
    their Hole. A helper used by anything else rejects the deletion.
    """
    from .core import OperationError, METADATA
    from .bodies import owner
    owners = set(owners)
    helpers = {obj.Name: obj for obj in doc.Objects
               if getattr(obj, "KurtShapeHoleHelper", False) and getattr(obj, "KurtShapeOperationOwner", "") in owners}
    allowed = set(removing) | set(helpers) | owners | {METADATA}
    for obj in helpers.values():
        container = owner(doc, obj)
        for dependent in obj.InList:
            if dependent.Name not in allowed and dependent != container:
                raise OperationError("external_dependency", "A later feature depends on this hole's profile",
                                     feature=dependent.Name, hole=obj.KurtShapeOperationOwner)
    return set(helpers)
