"""Sweep tool: native AdditivePipe with Onshape-style options.

The sweep is a ``PartDesign::AdditivePipe`` inside a private carrier Body, fed
by ShapeBinders of the profile (a sketch or one face) and of the path (a sketch
or picked edges). Everything stays native and associative:

* ``extend_full_path`` off: the path is trimmed so the sweep starts where the
  profile sits on it. The trimmed wire is a plain ``Part::Feature`` helper that
  KurtShape refreshes before every managed recompute (``refresh``), so edits to
  the path or profile sketches propagate without any scripted object.
* ``profile_control``: ``none`` (profile stays normal to the path, FreeCAD's
  Standard/corrected-Frenet mode), ``keep_orientation`` (Fixed trihedron, the
  profile keeps its original orientation), ``lock_faces`` (profile stays aligned
  to a planar face: Binormal mode with the face normal) and ``lock_direction``
  (Binormal mode with the direction of a straight edge or a planar face normal).
* ``twist``: ``turns`` full rotations of the profile along the path, through a
  generated auxiliary spine (also a refreshed helper) in Auxiliary mode.
"""
from __future__ import annotations

import json
import math

import FreeCAD as App
import Part

CONTROLS = ("none", "keep_orientation", "lock_faces", "lock_direction")
SPEC = "KurtShapeSweepSpec"
_TOLERANCE = 1e-6


def _error(code, message, **details):
    from .core import OperationError
    return OperationError(code, message, **details)


def _number(value, name, positive=False, unit="mm"):
    from .core import number
    return number(value, name, positive, unit)


def _bool(req, name, default=False):
    value = req.get(name, default)
    if not isinstance(value, bool):
        raise _error("invalid_argument", name + " must be boolean")
    return value


# ---------------------------------------------------------------- references

def _references(doc, spec, entity_type):
    """Normalize one reference or a list of references to native (feature, subelement) pairs."""
    from . import selectors
    items = spec if isinstance(spec, list) else [spec]
    if not items:
        raise _error("missing_reference", "Select at least one " + entity_type)
    resolved = []
    for item in items:
        if not isinstance(item, dict):
            raise _error("invalid_argument", entity_type + " references must be objects")
        ref = selectors.native_reference(doc, item, entity_type=entity_type)
        resolved.append((ref["feature"], ref["subelement"]))
    return resolved


def _support(doc, pairs):
    grouped = {}
    for feature, subelement in pairs:
        grouped.setdefault(feature, [])
        if subelement not in grouped[feature]:
            grouped[feature].append(subelement)
    return [(doc.getObject(feature), elements) for feature, elements in grouped.items()]


def _global_shape(obj, subelement=""):
    shape = Part.getShape(obj, subelement, needSubElement=bool(subelement))
    if shape is None or shape.isNull():
        raise _error("missing_reference", "Referenced geometry has no shape", feature=obj.Name, subelement=subelement)
    return shape


def _direction_from(doc, reference):
    """A straight edge gives its direction, a planar face its normal."""
    from . import selectors
    if isinstance(reference, dict) and reference.get("direction"):
        value = reference["direction"]
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            raise _error("invalid_argument", "direction requires three coordinates")
        vector = App.Vector(*[_number(x, "direction") for x in value])
        if vector.Length < 1e-10:
            raise _error("invalid_argument", "direction must be a nonzero vector")
        return vector.normalize()
    for entity_type in ("edge", "face"):
        try:
            ref = selectors.native_reference(doc, reference, entity_type=entity_type)
        except Exception:
            continue
        shape = _global_shape(doc.getObject(ref["feature"]), ref["subelement"])
        if entity_type == "edge":
            if not isinstance(shape.Curve, Part.Line) and shape.Curve.__class__.__name__ not in {"Line", "LineSegment"}:
                raise _error("invalid_argument", "Lock direction needs a straight edge or a planar face")
            vector = shape.Vertexes[-1].Point - shape.Vertexes[0].Point
        else:
            if not isinstance(shape.Surface, Part.Plane):
                raise _error("invalid_argument", "Lock direction needs a straight edge or a planar face")
            vector = shape.normalAt(0, 0)
        if vector.Length < 1e-10:
            raise _error("invalid_argument", "Lock direction reference is degenerate")
        return vector.normalize()
    raise _error("missing_reference", "Lock direction reference resolves to no straight edge or planar face")


def _face_normal(doc, pairs):
    normal = None
    for feature, subelement in pairs:
        face = _global_shape(doc.getObject(feature), subelement)
        if not isinstance(face.Surface, Part.Plane):
            raise _error("unsupported_reference", "Lock profile faces supports planar faces in this version", feature=feature, subelement=subelement)
        candidate = face.normalAt(0, 0).normalize()
        if normal is not None and abs(abs(candidate.dot(normal)) - 1) > 1e-6:
            raise _error("invalid_argument", "Locked faces must be parallel")
        normal = normal or candidate
    return normal


# ---------------------------------------------------------------- geometry

def chain(shape):
    """The connected path wire of a shape, or an error naming why it is not one."""
    edges = [edge for edge in shape.Edges if edge.Length > _TOLERANCE]
    if not edges:
        raise _error("missing_reference", "Sweep path has no edges")
    try:
        ordered = Part.__sortEdges__(edges)
        wire = Part.Wire(ordered)
    except Exception as exc:
        raise _error("invalid_argument", "Sweep path must be one connected chain of edges") from exc
    if len(wire.Edges) != len(edges):
        raise _error("invalid_argument", "Sweep path must be one connected chain of edges")
    return wire


def profile_anchor(profile_shape):
    faces = profile_shape.Faces
    if faces:
        return Part.makeCompound(faces).CenterOfMass
    return profile_shape.CenterOfMass


def trim_wire(path_shape, profile_shape):
    """The part of the path from the profile's position to the path end.

    Starts the sweep at the profile instead of carrying the profile back to the
    beginning of the path. A profile at the first vertex keeps the full path; a
    profile at the last vertex runs the path backwards in full.
    """
    wire = chain(path_shape)
    anchor = Part.Vertex(profile_anchor(profile_shape))
    start, end = wire.Vertexes[0].Point, wire.Vertexes[-1].Point
    if wire.isClosed() or (anchor.Point - start).Length <= _TOLERANCE * max(1.0, wire.Length):
        return wire
    if (anchor.Point - end).Length <= _TOLERANCE * max(1.0, wire.Length):
        return _reversed(wire)
    distance, points, info = wire.distToShape(anchor)
    kind, index, parameter = info[0][0], info[0][1], info[0][2]
    edges = list(wire.Edges)
    if kind == "Vertex":
        vertex = wire.Vertexes[index].Point
        keep = next((i for i, edge in enumerate(edges) if (edge.Vertexes[0].Point - vertex).Length <= _TOLERANCE), None)
        if keep is None:
            keep = next((i + 1 for i, edge in enumerate(edges) if (edge.Vertexes[-1].Point - vertex).Length <= _TOLERANCE), len(edges))
        remaining = edges[keep:]
        return Part.Wire(remaining) if remaining else _reversed(wire)
    edge = edges[index]
    first, last = edge.FirstParameter, edge.LastParameter
    if abs(parameter - first) <= 1e-9 * max(1.0, abs(last - first)):
        pieces = []
    elif abs(parameter - last) <= 1e-9 * max(1.0, abs(last - first)):
        pieces = None
    else:
        candidates = _split_edge(edge, parameter)
        downstream_point = edges[index + 1].Vertexes[0].Point if index + 1 < len(edges) else end
        def gap(piece):
            return min((piece.Vertexes[0].Point - downstream_point).Length, (piece.Vertexes[-1].Point - downstream_point).Length)
        # Keep the piece that continues toward the rest of the path.
        pieces = [min(candidates, key=gap)]
    if pieces is None:
        remaining = edges[index + 1:]
    else:
        remaining = pieces + edges[index + 1:]
    if not remaining:
        return _reversed(wire)
    return Part.Wire(Part.__sortEdges__(remaining))


def _split_edge(edge, parameter):
    """Both pieces of an edge at a parameter, in the edge's global frame.

    Edge.split drops the edge's placement, so build the pieces from the
    (already placed) curve instead.
    """
    try:
        pieces = [Part.Edge(edge.Curve, edge.FirstParameter, parameter),
                  Part.Edge(edge.Curve, parameter, edge.LastParameter)]
        if all(piece.Length > _TOLERANCE for piece in pieces):
            return pieces
    except Exception:
        pass
    split = edge.split([parameter])
    split.Placement = edge.Placement
    return list(split.Edges)


def _reversed(wire):
    edges = [edge.reversed() for edge in reversed(wire.Edges)]
    return Part.Wire(Part.__sortEdges__(edges))


def _frames(points):
    """Rotation-minimizing frames (double reflection) along sampled points."""
    tangents = []
    for i in range(len(points)):
        a = points[max(i - 1, 0)]
        b = points[min(i + 1, len(points) - 1)]
        tangent = b - a
        tangents.append(tangent.normalize() if tangent.Length > 1e-12 else (tangents[-1] if tangents else App.Vector(0, 0, 1)))
    t0 = tangents[0]
    seed = App.Vector(0, 0, 1) if abs(t0.z) < 0.9 else App.Vector(1, 0, 0)
    normal = t0.cross(seed).cross(t0).normalize()
    normals = [normal]
    for i in range(len(points) - 1):
        v1 = points[i + 1] - points[i]
        c1 = v1.dot(v1)
        if c1 < 1e-18:
            normals.append(normals[-1])
            continue
        rl = normals[-1] - v1 * (2 / c1 * v1.dot(normals[-1]))
        tl = tangents[i] - v1 * (2 / c1 * v1.dot(tangents[i]))
        v2 = tangents[i + 1] - tl
        c2 = v2.dot(v2)
        n = rl if c2 < 1e-18 else rl - v2 * (2 / c2 * v2.dot(rl))
        normals.append(n.normalize() if n.Length > 1e-12 else normals[-1])
    return tangents, normals


def twist_spine(path_shape, turns, radius):
    """An auxiliary spine winding ``turns`` times around the path."""
    wire = chain(path_shape)
    length = wire.Length
    samples = max(48, int(32 * abs(turns)) + 8)
    points = wire.discretize(Number=samples)
    tangents, normals = _frames(points)
    aux = []
    for i, point in enumerate(points):
        fraction = i / (len(points) - 1)
        angle = 2 * math.pi * turns * fraction
        binormal = tangents[i].cross(normals[i])
        aux.append(point + normals[i] * (radius * math.cos(angle)) + binormal * (radius * math.sin(angle)))
    curve = Part.BSplineCurve()
    curve.interpolate(aux)
    return Part.Wire([curve.toShape()])


def _profile_size(profile_shape):
    box = profile_shape.BoundBox
    return max(box.DiagonalLength, 1.0)


# ---------------------------------------------------------------- building

def build(controller, doc, req, name, profile):
    """Create the carrier Body, binders, helpers and the AdditivePipe tool."""
    from . import selectors, reference_tools
    from .studio import _prop, _carrier_binder, _native_failed
    control = req.get("profile_control", "none")
    if control not in CONTROLS:
        raise _error("invalid_argument", "profile_control must be none, keep_orientation, lock_faces or lock_direction")
    extend = _bool(req, "extend_full_path", False)
    twist = _bool(req, "twist", False)
    frenet = _bool(req, "frenet", False)
    turns = _number(req.get("turns", 1), "turns", True, "mm") if twist else 0.0
    if twist and control != "none":
        raise _error("invalid_argument", "Twist cannot be combined with profile control")
    # The operation's representative owns the carrier and helpers, so deleting
    # the sweep removes them too (a Tool-suffixed name belongs to a merge).
    operation = req.get("operation", "new")
    representative = name[:-4] if operation != "new" and name.endswith("Tool") else name
    carrier = doc.addObject("PartDesign::Body", name + "Carrier")
    _prop(carrier, "App::PropertyBool", "KurtShapeInternal", True)
    _prop(carrier, "App::PropertyString", "KurtShapeOperationOwner", representative)
    # Profile: a closed sketch or one face.
    if profile is None:
        pairs = _references(doc, req.get("profile"), "face")
        if len(pairs) != 1:
            raise _error("invalid_argument", "Sweep one face or one sketch profile")
        target = doc.getObject(pairs[0][0])
        section = _carrier_binder(carrier, target, [pairs[0][1]], name + "Profile")
        if reference_tools.is_selector(req["profile"]):
            selectors.bind(section, "profile", reference_tools.selector_value(req["profile"]), native_property="Support", mode="linksublist")
    else:
        section = _carrier_binder(carrier, profile, [""], name + "Profile")
    # Path: a sketch/curve feature or picked edges.
    path_spec = req.get("path")
    if isinstance(path_spec, str):
        source = doc.getObject(path_spec)
        if not source or not hasattr(source, "Shape") or source.Shape.isNull() or not source.Shape.Edges:
            raise _error("missing_reference", "Sweep path must name a native curve feature")
        path_source = _carrier_binder(carrier, source, [""], name + "PathSource")
    else:
        pairs = _references(doc, path_spec, "edge")
        path_source = doc.addObject("PartDesign::ShapeBinder", name + "PathSource")
        carrier.addObject(path_source)
        path_source.Support = _support(doc, pairs)
        path_source.TraceSupport = True
        _prop(path_source, "App::PropertyBool", "KurtShapeInternal", True)
        if isinstance(path_spec, dict) and reference_tools.is_selector(path_spec):
            selectors.bind(path_source, "path", reference_tools.selector_value(path_spec), native_property="Support", mode="linksublist")
    doc.recompute()
    chain(path_source.Shape)
    spine = path_source
    trim = None
    if not extend:
        trim = doc.addObject("Part::Feature", name + "PathTrim")
        _prop(trim, "App::PropertyBool", "KurtShapeInternal", True)
        _prop(trim, "App::PropertyString", "KurtShapeOperationOwner", representative)
        trim.Shape = trim_wire(path_source.Shape, section.Shape)
        spine = _carrier_binder(carrier, trim, [""], name + "Path")
    aux = None
    if twist:
        aux = doc.addObject("Part::Feature", name + "TwistSpine")
        _prop(aux, "App::PropertyBool", "KurtShapeInternal", True)
        _prop(aux, "App::PropertyString", "KurtShapeOperationOwner", representative)
        aux.Shape = twist_spine((trim or path_source).Shape, turns, _profile_size(section.Shape))
        aux_binder = _carrier_binder(carrier, aux, [""], name + "Twist")
    doc.recompute()
    # AdditivePipe takes a whole sketch, but a binder needs an explicit
    # subelement: the face of a picked face, the wire of a single-loop sketch,
    # or a face built from a multi-loop sketch (outer wire plus holes).
    if section.Shape.Faces:
        profile_link = (section, ["Face1"])
    elif len(section.Shape.Wires) == 1:
        profile_link = (section, ["Wire1"])
    else:
        face = doc.addObject("Part::Face", name + "ProfileFace")
        face.Sources = [section]
        face.FaceMakerClass = "Part::FaceMakerBullseye"
        _prop(face, "App::PropertyBool", "KurtShapeInternal", True)
        _prop(face, "App::PropertyString", "KurtShapeOperationOwner", representative)
        doc.recompute()
        if face.Shape.isNull() or not face.Shape.Faces:
            raise _error("open_profile", "Sweep profile must be a closed sketch region or a face")
        profile_link = (_carrier_binder(carrier, face, [""], name + "ProfileFaces"), ["Face1"])
    tool = carrier.newObject("PartDesign::AdditivePipe", name)
    tool.Profile = profile_link
    tool.Spine = (spine, [])
    tool.Transition = "Transformed"
    binormal = None
    if twist:
        tool.Mode = "Auxiliary"
        tool.AuxiliarySpine = (aux_binder, [])
        tool.AuxiliaryCurvilinear = True
        tool.AuxiliarySpineTangent = False
    elif control == "keep_orientation":
        tool.Mode = "Fixed"
    elif control == "lock_faces":
        binormal = _face_normal(doc, _references(doc, req.get("lock_faces"), "face"))
    elif control == "lock_direction":
        if req.get("lock_direction") is None:
            raise _error("missing_reference", "Lock profile direction needs a straight edge or a planar face")
        binormal = _direction_from(doc, req["lock_direction"])
    else:
        tool.Mode = "Frenet" if frenet else "Standard"
    if binormal is not None:
        tool.Mode = "Binormal"
        tool.Binormal = binormal
    _prop(tool, "App::PropertyBool", "KurtShapeInternal", True)
    _prop(tool, "App::PropertyString", SPEC, json.dumps({
        "extend_full_path": extend, "profile_control": control, "twist": twist, "turns": turns}, sort_keys=True))
    _prop(tool, "App::PropertyLinkGlobal", "KurtShapeSweepPathSource", path_source)
    _prop(tool, "App::PropertyLinkGlobal", "KurtShapeSweepProfile", section)
    if trim is not None:
        _prop(tool, "App::PropertyLinkGlobal", "KurtShapeSweepTrim", trim)
    if aux is not None:
        _prop(tool, "App::PropertyLinkGlobal", "KurtShapeSweepTwist", aux)
    doc.recompute()
    if tool.Shape.isNull() or not tool.Shape.Solids or _native_failed(tool):
        raise _error("build_failed", "The sweep did not produce valid solid geometry", status=tool.getStatusString())
    return tool


def _same_wire(a, b):
    if a is None or b is None or a.isNull() != b.isNull():
        return False
    if a.isNull():
        return True
    if abs(a.Length - b.Length) > 1e-7 or len(a.Edges) != len(b.Edges):
        return False
    return all((va.Point - vb.Point).Length <= 1e-7 for va, vb in zip(a.Vertexes, b.Vertexes))


def refresh(doc):
    """Recompute trim/twist helpers from their current sources; True when any changed."""
    changed = False
    for tool in doc.Objects:
        if tool.TypeId != "PartDesign::AdditivePipe" or SPEC not in tool.PropertiesList:
            continue
        try:
            spec = json.loads(getattr(tool, SPEC) or "{}")
            path_source = getattr(tool, "KurtShapeSweepPathSource", None)
            section = getattr(tool, "KurtShapeSweepProfile", None)
            if path_source is None or section is None or path_source.Shape.isNull() or section.Shape.isNull():
                continue
            spine_shape = path_source.Shape
            trim = getattr(tool, "KurtShapeSweepTrim", None)
            if trim is not None and not spec.get("extend_full_path", False):
                wire = trim_wire(path_source.Shape, section.Shape)
                if not _same_wire(trim.Shape, wire):
                    trim.Shape = wire
                    changed = True
                spine_shape = wire
            aux = getattr(tool, "KurtShapeSweepTwist", None)
            if aux is not None and spec.get("twist"):
                wire = twist_spine(spine_shape, float(spec.get("turns", 1)), _profile_size(section.Shape))
                if not _same_wire(aux.Shape, wire):
                    aux.Shape = wire
                    changed = True
        except Exception as exc:  # A broken source surfaces as the tool's own native error.
            App.Console.PrintLog("KurtShape sweep helper refresh skipped for %s: %s\n" % (tool.Name, exc))
    return changed
