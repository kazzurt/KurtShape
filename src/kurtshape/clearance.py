"""Opt-in nominal BRep envelope checks; no CAD objects or machine model are created."""
import math

import FreeCAD as App
import Part

from . import assembly
from .bodies import results


def world_shape(obj):
    """Detached result in world coordinates, including nested native containers.

    Assembly links have their own source/occurrence placement contract. A
    legacy result's Shape already includes its own Placement, so add only the
    parent transform rather than applying that placement a second time.
    """
    if obj.TypeId == "App::Link":
        return assembly.global_shape(obj).copy(True, False)
    shape = obj.Shape.copy(True, False)
    if hasattr(obj, "getGlobalPlacement") and hasattr(obj, "Placement"):
        shape.Placement = obj.getGlobalPlacement() * obj.Placement.inverse() * shape.Placement
    return shape


def _error(message, **details):
    from .core import OperationError
    return OperationError("invalid_clearance", message, **details)


def _checked_shape(shape, context, *, solid=False, allow_empty=False):
    """BRepCheck every supplied solid and every nonempty kernel result."""
    from .core import OperationError
    empty = shape.isNull() or not shape.Vertexes
    if empty and allow_empty:
        return shape
    if empty or not shape.isValid() or (solid and not shape.Solids):
        raise OperationError("invalid_clearance_geometry", "Clearance requires valid BRep geometry", context=context)
    if any(not math.isfinite(item.Volume) or item.Volume <= 0 for item in shape.Solids):
        raise OperationError("invalid_clearance_geometry", "Clearance requires positive-volume solids", context=context)
    return shape


def _boolean(first, second, operation, context):
    from .core import OperationError
    try:
        result = getattr(first, operation)(second)
    except Exception as exc:
        raise OperationError("invalid_clearance_geometry", "Clearance Boolean failed", context=context, reason=str(exc))
    return _checked_shape(result, context, allow_empty=True)


def _number(value, name, *, positive=False, nonnegative=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise _error(name + " must be a finite number")
    if positive and value <= 0 or nonnegative and value < 0:
        raise _error(name + (" must be positive" if positive else " must be nonnegative"))
    return float(value)


def _vector(value, name, *, direction=False):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise _error(name + " must have three numbers")
    vector = App.Vector(*[_number(item, name) for item in value])
    if direction:
        if vector.Length < 1e-12:
            raise _error(name + " must be nonzero")
        vector.normalize()
    return vector


def _keys(value, allowed, required=()):
    if not isinstance(value, dict):
        raise _error("Envelope, allowance and probe specifications must be objects")
    unknown, missing = set(value) - set(allowed), set(required) - set(value)
    if unknown or missing:
        raise _error("Invalid clearance specification fields", unknown=sorted(unknown), missing=sorted(missing))


def envelope(spec, objects, *, named=True):
    """Build a temporary world-space envelope, or copy a named current result."""
    kind = spec.get("kind") if isinstance(spec, dict) else None
    common = {"kind", "id"} if named else {"kind"}
    required = {"kind", "id"} if named else {"kind"}
    fields = {"component": {"component"}, "cylinder": {"origin_mm", "axis", "radius_mm", "length_mm"},
              "annulus": {"origin_mm", "axis", "inner_radius_mm", "outer_radius_mm", "length_mm"},
              "box": {"origin_mm", "size_mm", "rotation_xyzw"}}
    if kind not in fields:
        raise _error("Envelope kind must be component, cylinder, annulus or box")
    _keys(spec, common | fields[kind], required | (fields[kind] - {"rotation_xyzw"}))
    if named and (not isinstance(spec["id"], str) or not spec["id"].strip()):
        raise _error("Envelope id must be a nonempty string")
    if kind == "component":
        key = spec["component"]
        if not isinstance(key, str) or key not in objects:
            raise _error("Envelope component must identify a current solid result", component=key)
        return _checked_shape(world_shape(objects[key]), "component envelope " + key, solid=True)
    origin = _vector(spec["origin_mm"], "origin_mm")
    if kind == "box":
        size = _vector(spec["size_mm"], "size_mm")
        if min(size) <= 0:
            raise _error("Every size_mm dimension must be positive")
        q = spec.get("rotation_xyzw", [0, 0, 0, 1])
        if not isinstance(q, (list, tuple)) or len(q) != 4:
            raise _error("rotation_xyzw must have four numbers")
        q = [_number(value, "rotation_xyzw") for value in q]
        if abs(sum(value * value for value in q) - 1) > 1e-6:
            raise _error("rotation_xyzw must be a unit quaternion")
        shape = Part.makeBox(size.x, size.y, size.z)
        shape.Placement = App.Placement(origin, App.Rotation(*q))
        return _checked_shape(shape, "box envelope", solid=True)
    axis = _vector(spec["axis"], "axis", direction=True)
    length = _number(spec["length_mm"], "length_mm", positive=True)
    radius = _number(spec["radius_mm" if kind == "cylinder" else "outer_radius_mm"], "radius_mm", positive=True)
    shape = Part.makeCylinder(radius, length, origin, axis)
    if kind == "annulus":
        inner = _number(spec["inner_radius_mm"], "inner_radius_mm", positive=True)
        if inner >= radius:
            raise _error("inner_radius_mm must be smaller than outer_radius_mm")
        shape = _boolean(shape, Part.makeCylinder(inner, length, origin, axis), "cut", "annulus envelope")
    return _checked_shape(shape, "cylindrical envelope", solid=True)


def check(doc, request):
    """Evaluate explicit pairs, including bounded intentional thread envelopes."""
    candidates = {obj.Name: obj for obj in results(doc)
                  if hasattr(obj, "Shape") and not obj.Shape.isNull() and obj.Shape.Solids}
    chosen = request.get("components", list(candidates))
    if (not isinstance(chosen, list) or not chosen or any(not isinstance(key, str) or key not in candidates for key in chosen)
            or len(set(chosen)) != len(chosen)):
        raise _error("components must be distinct current solid result IDs")
    specs = request.get("envelopes", [])
    if not isinstance(specs, list) or len(specs) > 128:
        raise _error("envelopes must be a list of at most 128 specifications")
    if not specs and "axis_probe" not in request:
        raise _error("Supply envelopes or axis_probe")
    minimum = _number(request.get("minimum_clearance_mm", 0), "minimum_clearance_mm", nonnegative=True)
    targets = {key: _checked_shape(world_shape(candidates[key]), "component " + key, solid=True) for key in chosen}
    shapes, ids = {}, []
    for spec in specs:
        shape = envelope(spec, candidates)
        if spec["id"] in shapes:
            raise _error("Envelope IDs must be distinct")
        ids.append(spec["id"])
        shapes[spec["id"]] = shape
    allowances = request.get("allowed_overlaps", [])
    if not isinstance(allowances, list):
        raise _error("allowed_overlaps must be a list")
    permitted = {}
    for allowance in allowances:
        _keys(allowance, {"envelope", "component", "reason", "region", "max_volume_mm3"},
              {"envelope", "component", "reason", "region", "max_volume_mm3"})
        key = (allowance["envelope"], allowance["component"])
        if not all(isinstance(value, str) for value in key):
            raise _error("Overlap envelope and component must be string IDs")
        if key[0] not in shapes or key[1] not in chosen or key in permitted:
            raise _error("Each overlap allowance must name one distinct evaluated envelope/component pair")
        if allowance["reason"] != "thread_envelope":
            raise _error("Only an explicitly bounded thread_envelope overlap is supported")
        region = envelope(allowance["region"], candidates, named=False)
        limit = _number(allowance["max_volume_mm3"], "max_volume_mm3", positive=True)
        permitted[key] = (region, limit)
    rows = []
    for spec in specs:
        shape = shapes[spec["id"]]
        for key in chosen:
            if spec["kind"] == "component" and spec["component"] == key:
                continue
            target = targets[key]
            distance, points, _ = shape.distToShape(target)
            # distToShape may measure separated boundaries when one solid is
            # wholly inside another. Volume interference needs the Boolean.
            common = _boolean(shape, target, "common", spec["id"] + "/" + key) if shape.BoundBox.intersect(target.BoundBox) else None
            volume = max(0.0, common.Volume) if common is not None and not common.isNull() else 0.0
            if volume > 1e-7:
                distance = 0.0
            intended = False
            outside = None
            allowance = permitted.get((spec["id"], key))
            if volume > 1e-7 and allowance:
                region, limit = allowance
                remainder = _boolean(common, region, "cut", "thread allowance " + spec["id"] + "/" + key)
                outside = 0.0 if remainder.isNull() else max(0.0, remainder.Volume)
                intended = volume <= limit + 1e-7 and outside <= 1e-7
            status = ("intended_thread_overlap" if intended else "interference" if volume > 1e-7 else
                      "below_minimum" if distance + 1e-7 < minimum else "clear")
            rows.append({"envelope": spec["id"], "component": key, "component_label": candidates[key].Label,
                         "distance_mm": distance, "overlap_mm3": volume, "outside_allowed_region_mm3": outside,
                         "status": status, "closest_points_mm": [[list(a), list(b)] for a, b in points[:1]]})
    limits = []
    for identity in ids:
        pairs = [row for row in rows if row["envelope"] == identity]
        if pairs:
            limiting = min(pairs, key=lambda row: row["distance_mm"])
            limits.append({"envelope": identity, "component": limiting["component"],
                           "distance_mm": limiting["distance_mm"]})
    probe_report = None
    if "axis_probe" in request:
        probe = request["axis_probe"]
        _keys(probe, {"tip_mm", "axis", "radius_mm", "max_distance_mm"},
              {"tip_mm", "axis", "radius_mm", "max_distance_mm"})
        tip = _vector(probe["tip_mm"], "tip_mm")
        axis = _vector(probe["axis"], "axis", direction=True)
        radius = _number(probe["radius_mm"], "radius_mm", positive=True)
        reach = _number(probe["max_distance_mm"], "max_distance_mm", positive=True)
        sweep = _checked_shape(Part.makeCylinder(radius, reach, tip, axis), "axis probe", solid=True)
        to_local = App.Placement(tip, App.Rotation(App.Vector(0, 0, 1), axis)).inverse()
        stops = []
        for key in chosen:
            hit = _boolean(sweep, targets[key], "common", "axis probe/" + key)
            if hit.isNull() or not hit.Vertexes:
                continue
            hit.Placement = to_local * hit.Placement
            gap = max(0.0, hit.optimalBoundingBox().ZMin)
            stops.append({"component": key, "distance_mm": gap})
        stop = min(stops, key=lambda row: row["distance_mm"]) if stops else None
        probe_report = {"limiting_component": stop["component"] if stop else None,
                        "distance_mm": stop["distance_mm"] if stop else None, "tested_distance_mm": reach,
                        "status": ("below_minimum" if stop and stop["distance_mm"] + 1e-7 < minimum else
                                   "range_insufficient" if not stop and reach < minimum else "clear"), "stops": stops}
    if not rows and probe_report is None:
        raise _error("No clearance pair remains after skipping self-pairs")
    passed = all(row["status"] in {"clear", "intended_thread_overlap"} for row in rows)
    if probe_report:
        passed = passed and probe_report["status"] == "clear"
    return {"passed": passed, "minimum_clearance_mm": minimum, "pairs": rows, "limiting": limits,
            "axis_probe": probe_report, "scope": "Nominal supplied BRep envelopes only; no machine kinematics, loads, tolerance or unsupplied motion."}
