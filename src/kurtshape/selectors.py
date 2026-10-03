"""Declarative native references evaluated at a feature's regeneration position.

The native document owns selectors and their resolved links. No geometry graph is
persisted here. Creator tracing uses the verified FreeCAD 1.1.4 unhashed H trailer
grammar; unsupported maps fail closed rather than guess another face.
"""
from __future__ import annotations
from collections import Counter
import json
import io
import math
import re
import time
import zipfile
import xml.etree.ElementTree as ET
import FreeCAD as App
import Part
from .bodies import owner, results as native_results


TOLERANCE = 1e-7
_TAG = re.compile(r";:H(-?[0-9a-f]+)(?::([0-9a-f]+))?,([FEV])$")
_ENTITY = {"face": ("Faces", "Face"), "edge": ("Edges", "Edge"), "vertex": ("Vertexes", "Vertex")}
_SCHEMA = {
    "created_by": {"kind", "feature", "entity_type", "cap"},
    "owned_by": {"kind", "part", "body", "entity_type"}, "all": {"kind", "entity_type"},
    "geometry": {"kind", "query", "geometry"}, "union": {"kind", "queries"},
    "intersection": {"kind", "queries"}, "subtraction": {"kind", "query", "subtract"},
    "adjacent": {"kind", "query", "entity_type", "adjacency"}, "tangent": {"kind", "query"},
    "parallel": {"kind", "query", "direction", "allow_antiparallel"}, "closest": {"kind", "query", "point"},
}
_evaluation_milliseconds = 0.0
_refresh_milliseconds = 0.0
_rebuild_metrics = {}


def _error(code, message, **details):
    from .core import OperationError
    return OperationError(code, message, **details)


def _json(obj, name):
    try:
        return json.loads(getattr(obj, name, "{}") or "{}")
    except (ValueError, TypeError) as exc:
        raise _error("invalid_selector_metadata", "Native selector metadata is invalid", feature=obj.Name) from exc


def _health(obj):
    values = _json(obj, "QueryHealth")
    return {value["input"]: {key: item for key, item in value.items() if key != "input"} for value in values} if isinstance(values, list) else values


def _write_health(obj, values):
    _property(obj, "QueryHealth", json.dumps([{"input": name, **value} for name, value in values.items()], sort_keys=True))


def _active(obj):
    from . import studio
    return studio.is_active(obj)


def _in_transaction(doc):
    # FreeCAD marks HasPendingTransaction only after the first document change.
    # Its active native transaction exists immediately after openTransaction.
    return bool(doc.HasPendingTransaction or App.getActiveTransaction())


def _property(obj, name, value, property_type="App::PropertyString"):
    if name not in obj.PropertiesList:
        obj.addProperty(property_type, name, "KurtShape references")
        obj.setEditorMode(name, 1)
    if getattr(obj, name) != value:
        setattr(obj, name, value)


def _vector(value, name):
    if not isinstance(value, (list, tuple)) or len(value) != 3 or any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) for n in value):
        raise _error("invalid_selector", name + " requires three finite millimeter coordinates")
    return App.Vector(*value)


def _split_operands(text):
    values, start, depth = [], 0, 0
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                raise _error("unsupported_selector_history", "Unbalanced native history expression")
        elif char in ",|" and depth == 0:
            # H trailers use commas before entity type, which are not separators.
            if char == "," and index + 2 == len(text) and text[index + 1] in "FEV":
                continue
            if char == "," and index + 2 < len(text) and text[index + 1] in "FEV" and text[index + 2] in ";,|":
                continue
            values.append(text[start:index]); start = index + 1
    if depth:
        raise _error("unsupported_selector_history", "Unbalanced native history expression")
    values.append(text[start:])
    return [value for value in values if value]


def _decode(name):
    """Return source tag, source name, operation marker, secondary sources.

    In 1.1.4 H trailers record the *operation suffix* length in hexadecimal.
    This differs from the older T-trailer format described in the author's wiki.
    """
    if "#" in name:
        raise _error("unsupported_selector_history", "Creator queries require a fresh native rebuild with UseHasher disabled")
    trailer = _TAG.search(name)
    if not trailer:
        if ";:H" in name or ";:T" in name:
            raise _error("unsupported_selector_history", "Unknown native element history trailer")
        return None
    tag = int(trailer.group(1), 16)
    suffix_length = int(trailer.group(2), 16) if trailer.group(2) else 0
    end = trailer.start() - suffix_length
    if end < 0:
        raise _error("unsupported_selector_history", "Native history suffix exceeds its name")
    prefix, suffix = name[:end], name[end:trailer.start()]
    marker, additional = "", []
    if suffix:
        match = re.match(r";:([MGUL]+)[0-9]*(?:\((.*)\))?(?:;[A-Z0-9_]+)?$", suffix)
        if match:
            marker = match.group(1)
            if match.group(2):
                additional = _split_operands(match.group(2))
        elif re.fullmatch(r";K-?[0-9]+", suffix):
            marker = "K"
        elif re.fullmatch(r"(?:;:H-?[0-9a-f]+(?::[0-9a-f]+)?,[FEV])+", suffix):
            # Native Link/Compound/Body wrappers retain the complete earlier
            # name; their suffix length covers earlier H trailers, not an op.
            prefix = name[:trailer.start()]
        elif re.fullmatch(r";[A-Z0-9_]+", suffix):
            marker = "primitive"
        else:
            raise _error("unsupported_selector_history", "Unknown native modeling history step", suffix=suffix)
    return tag, prefix, marker, additional


def _part_id(doc, obj):
    try:
        from . import studio
        return studio.part_id(obj)
    except (ImportError, AttributeError):
        body = owner(doc, obj)
        return getattr(body or obj, "KurtShapePartId", (body or obj).Name)


def _world_shape(obj):
    if obj.TypeId == "App::Link":
        from .assembly import global_shape
        return global_shape(obj)
    shape = obj.Shape.copy()
    shape.Placement = obj.getGlobalPlacement() * obj.Placement.inverse() * shape.Placement
    return shape


def _maker_input_shape(maker, source):
    # Native Part makers consume source.Shape in their own coordinate frame;
    # they do not include a source sketch's containing Body placement.
    shape = source.Shape.copy()
    shape.Placement = maker.getGlobalPlacement() * shape.Placement
    return shape


def _generated_creator(obj):
    """Creation identity at native whole-part instance generator boundaries."""
    compound = obj.TypeId == "Part::Compound" and bool(obj.Links) and all(link.TypeId == "App::Link" for link in obj.Links)
    if not compound and obj.TypeId != "Part::Mirroring":
        return set()
    operation = obj.Document.getObject(getattr(obj, "KurtShapeOperationOwner", "")) or obj
    request = json.loads(getattr(operation, "KurtShapeStudioOperation", "") or "{}")
    generated = request.get("op") in {"linear_pattern_parts", "circular_pattern_parts", "mirror_parts"}
    generated |= request.get("op") == "transform_part" and request.get("copy", False) is True
    return {operation.Name} if generated else set()


def _results(doc, before=None):
    try:
        from . import studio
        values = studio.results(doc, before=before)
        if values is not None:
            return values
    except (ImportError, AttributeError):
        pass
    objects = native_results(doc)
    if before is None:
        return [getattr(obj, "Tip", None) or obj for obj in objects]
    before = doc.getObject(before) if isinstance(before, str) else before
    boundary = doc.Objects.index(before) if before in doc.Objects else len(doc.Objects)
    answer = []
    for obj in objects:
        candidates = [item for item in getattr(obj, "Group", [obj])
                      if doc.Objects.index(item) < boundary and hasattr(item, "Shape")
                      and not item.Shape.isNull() and item.Shape.Solids]
        if candidates:
            answer.append(candidates[-1])
    return answer


class _Context:
    def __init__(self, doc, before=None):
        self.doc, self.before = doc, before
        self.objects = {obj.ID: obj for obj in doc.Objects}
        self.positions = {obj.Name: index for index, obj in enumerate(doc.Objects)}
        self.map_owners = {}
        for obj in doc.Objects:
            if hasattr(obj, "Shape") and obj.TypeId != "PartDesign::Body":
                for name in obj.Shape.ElementMap:
                    self.map_owners.setdefault(name, []).append(obj)
        self.lineages, self.multiplicities, self.dependencies = {}, {}, {}
        self.rows = []
        results = list(_results(doc, before))
        boundary = self.positions.get(before.Name if hasattr(before, "Name") else before, len(doc.Objects))
        from . import studio
        sequence = studio.order(doc)
        before_obj = doc.getObject(before) if isinstance(before, str) else before
        operation = getattr(before_obj, "KurtShapeOperationOwner", "") if before_obj else ""
        boundary_obj = doc.getObject(operation) if operation else before_obj
        if studio.enabled(doc) and boundary_obj in sequence:
            allowed_sketches = {candidate.Name for candidate in sequence[:sequence.index(boundary_obj)]}
        else:
            allowed_sketches = None
        results.extend(obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"
                       and (obj.Name in allowed_sketches if allowed_sketches is not None else self.positions[obj.Name] < boundary) and _active(obj))
        for result in results:
            obj = result.Tip if result.TypeId == "PartDesign::Body" and result.Tip else result
            if not hasattr(obj, "Shape") or obj.Shape.isNull():
                continue
            shape = _world_shape(obj)
            for kind, (collection, prefix) in _ENTITY.items():
                for i, subshape in enumerate(getattr(shape, collection)):
                    self.rows.append({"feature": obj.Name, "subelement": prefix + str(i + 1),
                                      "entity_type": kind, "part": obj.Name if obj.TypeId == "Sketcher::SketchObject" else _part_id(doc, result),
                                      "_object": obj, "_shape": subshape})

    def _source_keys(self, name):
        decoded = _decode(name)
        if not decoded:
            return []
        tag, prefix, marker, additional = decoded
        keys = [(abs(tag), prefix)]
        for value in additional:
            branch = _decode(value)
            if branch:
                keys.append((abs(branch[0]), branch[1]))
        return keys

    def multiplicity(self, obj, key, entity_type):
        cache_key = (obj.Name, entity_type)
        if cache_key not in self.multiplicities:
            counts = Counter()
            collection, prefix = _ENTITY[entity_type]
            for i in range(len(getattr(obj.Shape, collection))):
                name = obj.Shape.getElementMappedName(prefix + str(i + 1))
                for source in set(self._source_keys(name)):
                    counts[source] += 1
            self.multiplicities[cache_key] = counts
        return self.multiplicities[cache_key][key]

    def lineage(self, obj, name, entity_type, seen=None):
        key = (obj.Name, name, entity_type)
        if key in self.lineages:
            return self.lineages[key]
        seen = set() if seen is None else set(seen)
        if key in seen:
            raise _error("unsupported_selector_history", "Cyclic native element history")
        seen.add(key)
        if obj.Name not in self.dependencies:
            self.dependencies[obj.Name] = {candidate.Name for candidate in obj.OutListRecursive}
        inherited = [candidate for candidate in self.map_owners.get(name, [])
                     if candidate.Name in self.dependencies[obj.Name] and self.positions[candidate.Name] < self.positions[obj.Name]]
        if inherited:
            candidate = min(inherited, key=lambda value: self.positions[value.Name])
            value = set(self.lineage(candidate, name, entity_type, seen))
            value.update(_generated_creator(obj))
            self.lineages[key] = value
            return value
        decoded = _decode(name)
        if not decoded:
            value = {obj.Name}
        else:
            tag, prefix, marker, additional = decoded
            source = self.objects.get(abs(tag))
            if source is None:
                raise _error("unsupported_selector_history", "Native history points to an unavailable source", tag=tag)
            # Intermediate maker steps may keep their original sketch's tag.
            # They belong to the current object until a real earlier object's
            # mapped-name boundary is reached; a tag alone is not that boundary.
            if source != obj and _decode(prefix) is not None and prefix not in source.Shape.ElementMap:
                value = set(self.lineage(obj, prefix, entity_type, seen))
            else:
                value = set(self.lineage(source, prefix, entity_type, seen))
            for branch_name in additional:
                branch = _decode(branch_name)
                if branch is None:
                    raise _error("unsupported_selector_history", "Native merged history has an untagged source")
                other = self.objects.get(abs(branch[0]))
                if other is None:
                    raise _error("unsupported_selector_history", "Native merged history source is unavailable")
                value.update(self.lineage(obj, branch_name, entity_type, seen))
            generated = "G" in marker or marker in {"primitive", "L"}
            split = marker == "M" and self.multiplicity(obj, (abs(tag), prefix), entity_type) > 1
            merged = marker == "M" and bool(additional)
            # Wire/sketch topology is added to solid context by its solid maker,
            # even where OCCT retained an unmodified profile cap edge.
            sketch_source = source.TypeId == "Sketcher::SketchObject" and obj.TypeId != "Sketcher::SketchObject"
            if generated or split or merged or sketch_source:
                value.add(obj.Name)
        value.update(_generated_creator(obj))
        self.lineages[key] = value
        return value

    def creators(self, row):
        obj = row["_object"]
        name = obj.Shape.getElementMappedName(row["subelement"])
        if not name:
            if obj.TypeId in {"Part::Box", "Part::Cylinder", "Part::Sphere", "Part::Cone", "Part::Torus", "Sketcher::SketchObject"}:
                return {obj.Name}
            raise _error("unsupported_selector_history", "This native result has no creator element map", feature=obj.Name)
        version = tuple(App.Version()[:3])
        if version != ("1", "1", "4"):
            raise _error("unsupported_selector_history", "Creator history grammar is verified only for FreeCAD 1.1.4")
        mapped_values = set(obj.Shape.ElementMap.values())
        face_count = len(obj.Shape.Faces)
        if any(n.startswith("Face") and int(n[4:]) > face_count for n in mapped_values):
            raise _error("unsupported_selector_history", "Native refinement history does not match current topology", feature=obj.Name)
        creators = set(self.lineage(obj, name, row["entity_type"]))
        if obj.TypeId != "Sketcher::SketchObject":
            creators = {name for name in creators if self.doc.getObject(name).TypeId != "Sketcher::SketchObject"}
        for name in tuple(creators):
            source = self.doc.getObject(name)
            operation = getattr(source, "KurtShapeOperationOwner", "") if source else ""
            if operation:
                creators.add(operation)
        return creators


def _identity(row):
    return row["feature"], row["subelement"]


def _geometry(row):
    shape, kind = row["_shape"], row["entity_type"]
    if kind == "vertex":
        return "point"
    primitive = shape.Surface if kind == "face" else shape.Curve
    return {"Plane": "plane", "Cylinder": "cylinder", "Cone": "cone", "Sphere": "sphere",
            "Toroid": "torus", "Line": "line", "LineSegment": "line", "Circle": "circle",
            "Ellipse": "ellipse", "BSplineCurve": "spline", "BSplineSurface": "spline"}.get(type(primitive).__name__, type(primitive).__name__.lower())


def _profile_plane(shape):
    try:
        faces = Part.makeFace(shape.Wires, "Part::FaceMakerBullseye").Faces
    except Exception as exc:
        raise _error("unsupported_selector", "Cap queries require a planar native profile") from exc
    if not faces or any(not isinstance(face.Surface, Part.Plane) for face in faces):
        raise _error("unsupported_selector", "Cap queries require a planar native profile")
    point, normal = faces[0].CenterOfMass, faces[0].normalAt(0, 0)
    if any(abs(abs(face.normalAt(0, 0).dot(normal)) - 1) > TOLERANCE
           or abs(normal.dot(face.CenterOfMass - point)) > TOLERANCE for face in faces):
        raise _error("unsupported_selector", "Native profile faces must share a plane")
    return point, normal


def _cap_rows(context, rows, feature, cap):
    obj = context.doc.getObject(feature)
    if obj is None:
        return []
    supported = {"PartDesign::Pad", "PartDesign::Pocket", "Part::Extrusion", "Part::Revolution", "PartDesign::Revolution",
                 "Part::Sweep", "PartDesign::AdditivePipe", "Part::Loft", "PartDesign::AdditiveLoft"}
    if obj.TypeId not in supported and getattr(obj, "KurtShapeStudioOperation", ""):
        tools = [candidate for candidate in context.doc.Objects
                 if candidate.TypeId in supported and getattr(candidate, "KurtShapeOperationOwner", "") == feature]
        if len(tools) == 1:
            obj = tools[0]
    if obj.TypeId not in supported:
        raise _error("unsupported_selector", "Cap queries require a native extrusion, revolve, sweep or loft")
    if obj.TypeId in {"Part::Loft", "PartDesign::AdditiveLoft"}:
        profiles = list(obj.Sections)
        if obj.TypeId == "PartDesign::AdditiveLoft":
            profiles.insert(0, obj.Profile[0] if isinstance(obj.Profile, tuple) else obj.Profile)
        if getattr(obj, "Closed", False):
            return rows if cap == "side" else []
        if len(profiles) < 2:
            raise _error("unsupported_selector", "Native loft profile endpoints are unavailable")
        planes = [_profile_plane(_maker_input_shape(obj, profiles[0])),
                  _profile_plane(_maker_input_shape(obj, profiles[-1]))]
        return _on_cap_planes(rows, planes, cap)
    profile = (getattr(obj, "Profile", None) or getattr(obj, "Source", None)
               or (obj.Sections[0] if hasattr(obj, "Sections") and obj.Sections else None)
               or getattr(obj, "Base", None))
    profile = profile[0] if isinstance(profile, (tuple, list)) else profile
    if profile is None or not hasattr(profile, "Shape"):
        raise _error("unsupported_selector", "Native extrusion profile is unavailable")
    placement = obj.getGlobalPlacement() * profile.Shape.Placement
    start, normal = _profile_plane(_maker_input_shape(obj, profile))
    if obj.TypeId in {"PartDesign::Pad", "PartDesign::Pocket"}:
        normal = placement.Rotation.multVec(App.Vector(0, 0, 1))
    if obj.TypeId in {"Part::Revolution", "PartDesign::Revolution"}:
        if obj.TypeId != "Part::Revolution":
            raise _error("unsupported_selector", "Native PartDesign revolution axis attachment is not yet supported")
        angle = float(getattr(obj.Angle, "Value", obj.Angle))
        if abs(angle) >= 360 - TOLERANCE:
            return rows if cap == "side" else []
        axis = obj.getGlobalPlacement().Rotation.multVec(obj.Axis)
        origin = obj.getGlobalPlacement().multVec(obj.Base)
        first_angle = -angle / 2 if getattr(obj, "Symmetric", False) else 0
        first_rotation = App.Rotation(axis, first_angle)
        source_face = Part.makeFace(_maker_input_shape(obj, profile).Wires, "Part::FaceMakerBullseye")
        start_shape, end_shape = source_face.copy(), source_face.copy()
        end_rotation = App.Rotation(axis, first_angle + angle)
        start_shape.transformShape(App.Placement(origin - first_rotation.multVec(origin), first_rotation).toMatrix())
        end_shape.transformShape(App.Placement(origin - end_rotation.multVec(origin), end_rotation).toMatrix())
        return _on_cap_shapes(rows, start_shape, end_shape, cap)
    if obj.TypeId in {"Part::Sweep", "PartDesign::AdditivePipe"}:
        spine = obj.Spine[0]
        paths = obj.Spine[1]
        spine_shape = _maker_input_shape(obj, spine)
        if paths:
            path_shape = Part.Wire([spine_shape.getElement(name) for name in paths])
        elif len(spine_shape.Wires) == 1:
            path_shape = spine_shape.Wires[0]
        else:
            path_shape = Part.Wire(spine_shape.Edges)
        if path_shape.isClosed():
            return rows if cap == "side" else []
        edges = path_shape.OrderedEdges
        if not edges:
            raise _error("unsupported_selector", "Native sweep path endpoints are unavailable")
        first, last = edges[0], edges[-1]
        first_parameter = first.LastParameter if first.Orientation == "Reversed" else first.FirstParameter
        last_parameter = last.FirstParameter if last.Orientation == "Reversed" else last.LastParameter
        first_point, end = first.valueAt(first_parameter), last.valueAt(last_parameter)
        first_normal, end_normal = first.tangentAt(first_parameter), last.tangentAt(last_parameter)
        if abs(abs(first_normal.dot(normal)) - 1) > TOLERANCE or abs(normal.dot(first_point - start)) > TOLERANCE:
            raise _error("unsupported_selector", "Sweep cap queries require a profile normal to the start of its path")
        return _on_cap_planes(rows, [(start, normal), (end, end_normal)], cap)
    length = float(obj.Length.Value) if hasattr(obj, "Length") else float(obj.LengthFwd.Value)
    if getattr(obj, "Reversed", False):
        length = -length
    if obj.TypeId == "PartDesign::Pocket":
        length = -length
    if hasattr(obj, "Type") and str(obj.Type) not in {"Length", "0"}:
        raise _error("unsupported_selector", "Cap queries require a finite blind extrusion")
    direction = obj.getGlobalPlacement().Rotation.multVec(obj.Dir) if obj.TypeId == "Part::Extrusion" else normal
    direction = App.Vector(direction)
    if direction.Length < TOLERANCE:
        raise _error("unsupported_selector", "Native extrusion direction is unavailable")
    direction.normalize()
    if obj.TypeId == "Part::Extrusion":
        start = start - direction * float(obj.LengthRev.Value)
        length += float(obj.LengthRev.Value)
    end = start + direction * length
    return _on_cap_planes(rows, [(start, normal), (end, normal)], cap)


def _on_cap_planes(rows, planes, cap):
    start, start_normal = planes[0]
    end, end_normal = planes[1]
    answer = []
    for row in rows:
        on_start = _lies_on_plane(row, start, start_normal)
        on_end = _lies_on_plane(row, end, end_normal)
        if cap == "start" and on_start or cap == "end" and on_end or cap == "side" and not on_start and not on_end:
            answer.append(row)
    return answer


def _lies_on_plane(row, point, normal):
    shape = row["_shape"]
    if row["entity_type"] == "face":
        return (isinstance(shape.Surface, Part.Plane)
                and abs(abs(shape.normalAt(0, 0).dot(normal)) - 1) < TOLERANCE
                and abs(normal.dot(shape.CenterOfMass - point)) < TOLERANCE)
    if row["entity_type"] == "edge":
        curve = shape.Curve
        if isinstance(curve, (Part.Circle, Part.Ellipse)):
            return (abs(abs(curve.Axis.dot(normal)) - 1) < TOLERANCE
                    and abs(normal.dot(curve.Center - point)) < TOLERANCE)
        if hasattr(curve, "getPoles"):
            return all(abs(normal.dot(value - point)) < TOLERANCE for value in curve.getPoles())
        if _geometry(row) != "line":
            raise _error("unsupported_selector", "Cap plane membership for this native curve is unsupported")
    vertices = shape.Vertexes
    return bool(vertices) and all(abs(normal.dot(vertex.Point - point)) < TOLERANCE for vertex in vertices)


def _on_cap_shapes(rows, start, end, cap):
    def touches(row, shape):
        entity = row["_shape"]
        if row["entity_type"] == "vertex":
            return entity.distToShape(shape)[0] < TOLERANCE
        common = entity.common(shape)
        return common.Area > TOLERANCE if row["entity_type"] == "face" else common.Length > TOLERANCE
    answer = []
    for row in rows:
        on_start, on_end = touches(row, start), touches(row, end)
        if cap == "start" and on_start or cap == "end" and on_end or cap == "side" and not on_start and not on_end:
            answer.append(row)
    return answer


def _evaluate(context, selector, depth=0):
    if depth > 24 or not isinstance(selector, dict):
        raise _error("invalid_selector", "Selector must be a bounded declarative object")
    if "selector" in selector and set(selector) == {"selector"}:
        return _evaluate(context, selector["selector"], depth + 1)
    kind = selector.get("kind")
    allowed = {"feature", "subelement"} if kind is None and "feature" in selector else _SCHEMA.get(kind)
    if allowed is None or set(selector) - allowed:
        raise _error("invalid_selector", "Unknown selector kind or fields", kind=kind, fields=sorted(set(selector) - (allowed or set())))
    if kind is None and "feature" in selector:
        obj = context.doc.getObject(selector["feature"])
        if obj is None:
            return []
        if obj.TypeId == "PartDesign::Body" and context.before is not None:
            prior = [row["_object"] for row in context.rows if row["part"] == _part_id(context.doc, obj)]
            if not prior:
                return []
            obj = prior[0]
        else:
            obj = obj.Tip if obj.TypeId == "PartDesign::Body" and obj.Tip else obj
        element = selector.get("subelement", "")
        match = re.fullmatch(r"(Face|Edge|Vertex)([1-9][0-9]*)", str(element))
        if not match or not hasattr(obj, "Shape"):
            raise _error("invalid_reference", "Native reference requires FaceN, EdgeN or VertexN")
        available = [row for row in context.rows if row["feature"] == obj.Name and row["subelement"] == element]
        if available:
            return available
        try:
            shape = _world_shape(obj).getElement(element)
        except Exception:
            return []
        return [{"feature": obj.Name, "subelement": element, "entity_type": {"Face": "face", "Edge": "edge", "Vertex": "vertex"}[match.group(1)],
                 "part": _part_id(context.doc, obj), "_object": obj, "_shape": shape}]
    entity_type = str(selector.get("entity_type", "face")).lower()
    if entity_type not in _ENTITY:
        raise _error("invalid_selector", "entity_type must be face, edge or vertex")
    if kind in {"created_by", "owned_by", "all"}:
        rows = [row for row in context.rows if row["entity_type"] == entity_type]
        if kind == "created_by":
            feature = selector.get("feature")
            if not isinstance(feature, str):
                raise _error("invalid_selector", "created_by requires a native feature ID")
            target = context.doc.getObject(feature)
            if target is None:
                return []
            from . import studio
            if not _active(target):
                return []
            if context.before is not None and studio.enabled(context.doc):
                sequence = studio.order(context.doc)
                target_order = context.doc.getObject(getattr(target, "KurtShapeOperationOwner", "")) or target
                before_obj = context.doc.getObject(context.before) if isinstance(context.before, str) else context.before
                before_order = context.doc.getObject(getattr(before_obj, "KurtShapeOperationOwner", "")) or before_obj
                if target_order in sequence and before_order in sequence and sequence.index(target_order) >= sequence.index(before_order):
                    return []
            related = {target.Name} | {candidate.Name for candidate in context.doc.Objects
                                      if getattr(candidate, "KurtShapeOperationOwner", "") == feature}
            rows = [row for row in rows if row["_object"].Name in related
                    or any(candidate.Name in related for candidate in row["_object"].OutListRecursive)]
            rows = [row for row in rows if feature in context.creators(row)]
            if "cap" in selector:
                if selector["cap"] not in {"start", "end", "side"}:
                    raise _error("invalid_selector", "cap must be start, end or side")
                rows = _cap_rows(context, rows, feature, selector["cap"])
        elif kind == "owned_by":
            part = selector.get("part", selector.get("body"))
            if not isinstance(part, str):
                raise _error("invalid_selector", "owned_by requires a native part ID")
            selected = context.doc.getObject(part)
            identifiers = {part, _part_id(context.doc, selected)} if selected else {part}
            rows = [row for row in rows if row["part"] in identifiers]
        return rows
    if kind in {"union", "intersection"}:
        queries = selector.get("queries")
        if not isinstance(queries, list) or not queries or len(queries) > 64:
            raise _error("invalid_selector", "Set queries require 1–64 queries")
        sets = [_evaluate(context, query, depth + 1) for query in queries]
        if kind == "union":
            unique = {_identity(row): row for values in sets for row in values}
            return list(unique.values())
        keys = set.intersection(*[{_identity(row) for row in values} for values in sets])
        return [row for row in sets[0] if _identity(row) in keys]
    query = selector.get("query")
    rows = _evaluate(context, query, depth + 1)
    if kind == "subtraction":
        excluded = {_identity(row) for row in _evaluate(context, selector.get("subtract"), depth + 1)}
        return [row for row in rows if _identity(row) not in excluded]
    if kind == "geometry":
        geometry = selector.get("geometry")
        if geometry not in {"plane", "cylinder", "cone", "sphere", "torus", "line", "circle", "ellipse", "spline", "point"}:
            raise _error("invalid_selector", "Unknown geometry filter")
        return [row for row in rows if _geometry(row) == geometry]
    if kind == "parallel":
        direction = _vector(selector.get("direction"), "direction")
        if direction.Length < TOLERANCE:
            raise _error("invalid_selector", "Parallel direction must be nonzero")
        direction.normalize()
        antiparallel = selector.get("allow_antiparallel", True)
        if not isinstance(antiparallel, bool):
            raise _error("invalid_selector", "allow_antiparallel must be boolean")
        answer = []
        for row in rows:
            if _geometry(row) == "plane":
                axis = row["_shape"].normalAt(0, 0)
            elif _geometry(row) == "line":
                axis = row["_shape"].tangentAt(row["_shape"].FirstParameter)
            else:
                continue
            dot = axis.dot(direction)
            if abs(abs(dot) - 1) < TOLERANCE and (antiparallel or dot > 0):
                answer.append(row)
        return answer
    if kind == "closest":
        point = Part.Vertex(_vector(selector.get("point"), "point"))
        distances = [(row["_shape"].distToShape(point)[0], row) for row in rows]
        if not distances:
            return []
        minimum = min(value for value, row in distances)
        return [row for value, row in distances if abs(value - minimum) < TOLERANCE]
    if kind == "adjacent":
        adjacency = selector.get("adjacency", "edge")
        if adjacency not in {"edge", "vertex"}:
            raise _error("invalid_selector", "adjacency must be edge or vertex")
        collection = "Edges" if adjacency == "edge" else "Vertexes"
        answer = []
        for candidate in context.rows:
            if candidate["entity_type"] != entity_type:
                continue
            for seed in rows:
                if candidate["feature"] != seed["feature"] or _identity(candidate) == _identity(seed):
                    continue
                if any(first.isSame(second) for first in getattr(candidate["_shape"], collection)
                       for second in getattr(seed["_shape"], collection)):
                    answer.append(candidate); break
        return answer
    if kind == "tangent":
        if any(row["entity_type"] != "edge" for row in rows):
            raise _error("invalid_selector", "Tangent chain seeds must be edges")
        answer = {_identity(row): row for row in rows}
        pending = list(rows)
        while pending:
            seed = pending.pop()
            edge = seed["_shape"]
            for candidate in context.rows:
                if candidate["entity_type"] != "edge" or candidate["feature"] != seed["feature"] or _identity(candidate) in answer:
                    continue
                other = candidate["_shape"]
                shared = [a for a in edge.Vertexes if any(a.isSame(b) for b in other.Vertexes)]
                if any(abs(abs(edge.tangentAt(edge.Curve.parameter(v.Point)).dot(other.tangentAt(other.Curve.parameter(v.Point)))) - 1) < TOLERANCE for v in shared):
                    answer[_identity(candidate)] = candidate; pending.append(candidate)
        return list(answer.values())
    raise _error("invalid_selector", "Unknown selector kind", kind=kind)


def _summary(row):
    shape = row["_shape"]
    result = {"geometry": _geometry(row), "center_mm": list(shape.CenterOfMass)}
    if row["entity_type"] == "face":
        result["area_mm2"] = shape.Area
        if result["geometry"] == "plane":
            result["normal"] = list(shape.normalAt(0, 0))
    elif row["entity_type"] == "edge":
        result["length_mm"] = shape.Length
    return result


def resolve(doc, selector, before=None):
    global _evaluation_milliseconds
    start = time.perf_counter()
    try:
        context = _Context(doc, before)
        values = _evaluate(context, selector)
        return [{**{key: value for key, value in row.items() if not key.startswith("_")}, "summary": _summary(row)}
                for row in sorted(values, key=_identity)]
    finally:
        _evaluation_milliseconds += (time.perf_counter() - start) * 1000


def native_reference(doc, spec, before=None, entity_type=None):
    values = resolve(doc, spec, before)
    if entity_type:
        values = [row for row in values if row["entity_type"] == entity_type]
    if not values:
        raise _error("missing_reference", "Reference selector resolves to no matching element")
    if len(values) != 1:
        raise _error("ambiguous_reference", "Reference selector resolves to several elements", matches=values)
    return {"feature": values[0]["feature"], "subelement": values[0]["subelement"]}


def _sources(doc, selector, before=None):
    names = set()
    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"feature", "part", "body"} and isinstance(item, str):
                    obj = doc.getObject(item)
                    if obj:
                        if obj.TypeId == "PartDesign::Body":
                            for prior in _results(doc, before):
                                if _part_id(doc, prior) == _part_id(doc, obj):
                                    names.add((prior.Tip if prior.TypeId == "PartDesign::Body" and prior.Tip else prior).Name)
                        else:
                            names.add(obj.Name)
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(selector)
    return [doc.getObject(name) for name in sorted(names)]


def _set_reference(feature, info, values):
    prop, mode = info["native_property"], info.get("mode", "linksub")
    references = [(feature.Document.getObject(row["feature"]), row["subelement"]) for row in values]
    if mode == "linksub":
        obj = references[0][0]
        if any(other != obj for other, name in references):
            raise _error("ambiguous_reference", "Native input cannot span multiple feature objects")
        setattr(feature, prop, (obj, [name for other, name in references]))
    elif mode == "linksublist":
        setattr(feature, prop, [(obj, [name]) for obj, name in references])
    elif mode == "linksub_index":
        current = getattr(feature, prop)
        obj, names = current[0], list(current[1])
        if references[0][0] != obj:
            if len(names) != 1:
                raise _error("ambiguous_reference", "Native multi-element Base cannot be changed to two feature objects")
            obj = references[0][0]
        index = info.get("index", 0)
        if index >= len(names):
            raise _error("invalid_selector_metadata", "Native element input slot no longer exists")
        names[index] = references[0][1]
        setattr(feature, prop, (obj, names))
    elif mode == "external":
        index = info["index"]
        obj, name = references[0]
        current = list(feature.ExternalGeometry)
        if not 0 <= index < len(current):
            raise _error("invalid_selector_metadata", "Native external geometry input no longer exists")
        if current[index] != (obj, (name,)) and current[index] != (obj, [name]):
            # The public property is read-only and delExternal drops constraints.
            # Edit only its native persistence link, retaining the exact sketch
            # buffer, external slots and projection/intersection mode metadata.
            buffer = io.BytesIO(bytes(feature.dumpContent()))
            with zipfile.ZipFile(buffer) as source:
                root = ET.fromstring(source.read("Persistence.xml"))
                links = root.findall(".//Property[@name='ExternalGeometry']/LinkSubList/Link")
                if len(links) != len(current):
                    raise _error("unsupported_selector_binding", "Native external-link persistence layout is unsupported")
                links[index].set("obj", obj.Name)
                links[index].set("sub", name)
                output = io.BytesIO()
                with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as destination:
                    for entry in source.infolist():
                        destination.writestr(entry, ET.tostring(root, encoding="utf-8", xml_declaration=True)
                                             if entry.filename == "Persistence.xml" else source.read(entry.filename))
            feature.restoreContent(output.getvalue())
            feature.touch()
    else:
        raise _error("invalid_selector_metadata", "Unknown native reference binding mode")


def _native_references(feature, info):
    """Read the actual native cache instead of trusting its JSON mirror."""
    mode = info.get("mode", "linksub")
    value = getattr(feature, info["native_property"])
    if mode == "external":
        index = info["index"]
        links = [value[index]] if 0 <= index < len(value) else []
    elif mode == "linksub_index":
        index = info.get("index", 0)
        links = [(value[0], [value[1][index]])] if value[0] is not None and 0 <= index < len(value[1]) else []
    elif mode in {"linksub", "linksublist"}:
        links = [value] if isinstance(value, tuple) and len(value) == 2 and hasattr(value[0], "Name") else list(value)
    else:
        raise _error("invalid_selector_metadata", "Unknown native reference binding mode")
    return [{"feature": obj.Name, "subelement": name} for obj, names in links if obj is not None for name in names]


def bind(feature, input_name, selector, native_property="AttachmentSupport", many=False, mode="linksub", index=None, **options):
    if not isinstance(input_name, str) or not input_name:
        raise _error("invalid_selector", "Reference input needs a name")
    if not _in_transaction(feature.Document):
        raise _error("selector_transaction_required", "Selector bindings must be authored inside the native mutation transaction")
    if mode == "external":
        native_property = "ExternalGeometry"
    inputs = _json(feature, "QueryInputs")
    info = {"selector": selector, "native_property": native_property, "many": bool(many), "mode": mode}
    if index is not None:
        info["index"] = index
    values = resolve(feature.Document, selector, before=feature)
    if not values:
        raise _error("missing_reference", "Reference selector resolves to no matching element")
    if not many and len(values) != 1:
        raise _error("ambiguous_reference", "Reference selector resolves to several elements", matches=values)
    for source in _sources(feature.Document, selector, before=feature):
        if source == feature or feature in source.OutListRecursive:
            raise _error("cyclic_reference", "Reference selector cannot target its consumer or a downstream feature")
    info["resolved"] = [{"feature": row["feature"], "subelement": row["subelement"]} for row in values]
    inputs[input_name] = info
    _set_reference(feature, info, values)
    _property(feature, "QueryInputs", json.dumps(inputs, sort_keys=True))
    sources = {obj.Name: obj for item in inputs.values() for obj in _sources(feature.Document, item["selector"], before=feature)}
    _property(feature, "QuerySources", list(sources.values()), "App::PropertyLinkList")
    health = _health(feature)
    health[input_name] = {"status": "healthy", "count": len(values)}
    _write_health(feature, health)
    _property(feature, "QueryResolutionLog", "[]")
    return values


def _refresh_feature_impl(feature, allow_reference_writes=True):
    inputs, health = _json(feature, "QueryInputs"), _health(feature)
    changed = False
    for name, info in inputs.items():
        try:
            values = resolve(feature.Document, info["selector"], before=feature)
            status = "missing" if not values else "ambiguous" if not info.get("many") and len(values) != 1 else "healthy"
            health[name] = {"status": status, "count": len(values)}
            if status != "healthy":
                continue
            resolved = [{"feature": row["feature"], "subelement": row["subelement"]} for row in values]
            actual = _native_references(feature, info)
            if resolved != info.get("resolved") or resolved != actual:
                if not allow_reference_writes:
                    health[name] = {"status": "missing", "count": len(values), "error": "Selector changed; run a managed rebuild to update its native input", "code": "pending_selector_resolution"}
                    continue
                _set_reference(feature, info, values)
                logs = json.loads(getattr(feature, "QueryResolutionLog", "[]"))
                logs.append({"input": name, "previous": actual, "resolved": resolved})
                _property(feature, "QueryResolutionLog", json.dumps(logs[-128:], sort_keys=True))
                info["resolved"] = resolved
                changed = True
        except Exception as exc:
            health[name] = {"status": "missing", "count": 0, "error": str(exc), "code": getattr(exc, "code", "selector_rebuild_failed")}
    _write_health(feature, health)
    if changed:
        _property(feature, "QueryInputs", json.dumps(inputs, sort_keys=True))
    return health


def _refresh_feature(feature, allow_reference_writes=True):
    global _refresh_milliseconds
    start = time.perf_counter()
    try:
        return _refresh_feature_impl(feature, allow_reference_writes)
    finally:
        _refresh_milliseconds += (time.perf_counter() - start) * 1000


def refresh(doc):
    if not _in_transaction(doc):
        raise _error("selector_transaction_required", "Selector references must refresh inside the native mutation transaction")
    for obj in doc.Objects:
        if "QueryInputs" in obj.PropertiesList and _active(obj):
            _refresh_feature(obj)
    return reference_errors(doc)


def recompute(doc):
    """Rebuild dependencies first and rebind each consumer in the same transaction."""
    start = time.perf_counter()
    evaluation_before = _evaluation_milliseconds
    refresh_before = _refresh_milliseconds
    native_ms = 0.0
    def native(objects=None):
        nonlocal native_ms
        begin = time.perf_counter()
        try:
            return doc.recompute(objects)
        finally:
            native_ms += (time.perf_counter() - begin) * 1000
    def metrics():
        _rebuild_metrics[doc.Name] = {"selector_evaluation_ms": _refresh_milliseconds - refresh_before,
                                    "query_resolution_ms": _evaluation_milliseconds - evaluation_before,
                                    "native_recompute_ms": native_ms,
                                    "selector_rebuild_ms": (time.perf_counter() - start) * 1000,
                                    "consumers": len(consumers)}
    consumers = [obj for obj in doc.Objects if "QueryInputs" in obj.PropertiesList and _active(obj)]
    if not consumers:
        result = native()
        metrics()
        return dict(_rebuild_metrics[doc.Name])
    if not _in_transaction(doc):
        # Undo/reopen restore native selector caches. No adapter writes outside
        # an accepted mutation; caller must create a rebuild transaction first.
        result = native()
        for obj in consumers:
            _refresh_feature(obj, allow_reference_writes=False)
        metrics()
        return dict(_rebuild_metrics[doc.Name])
    completed, visiting = set(), set()
    def rebuild(obj):
        if obj.Name in completed:
            return
        if obj.Name in visiting:
            raise _error("cyclic_reference", "Native reference dependencies contain a cycle")
        visiting.add(obj.Name)
        for dependency in obj.OutList:
            if dependency.Document == doc:
                rebuild(dependency)
        if "QueryInputs" in obj.PropertiesList and _active(obj):
            _refresh_feature(obj)
        native([obj])
        visiting.remove(obj.Name); completed.add(obj.Name)
    for obj in doc.Objects:
        rebuild(obj)
    metrics()
    return dict(_rebuild_metrics[doc.Name])


def rebuild_metrics(doc):
    """Derived timings from the last explicit rebuild, never a query evaluation."""
    return dict(_rebuild_metrics.get(doc.Name, {}))


def clear_cache(doc):
    """Release derived diagnostic state when the native document closes."""
    _rebuild_metrics.pop(doc.Name, None)


def reference_errors(doc):
    errors = []
    for obj in doc.Objects:
        if not _active(obj):
            continue
        for name, health in _health(obj).items():
            if health.get("status") != "healthy":
                errors.append({"feature": obj.Name, "input": name, "reference_health": health["status"],
                               "message": "Reference " + name + " is " + health["status"] + (": " + health["error"] if health.get("error") else "")})
    return errors


_native_refreshing = False


def native_recomputed(obj):
    """Observer boundary: refresh consumers without nesting native recomputation."""
    global _native_refreshing
    if _native_refreshing:
        return
    _native_refreshing = True
    try:
        if "QueryInputs" in obj.PropertiesList and _active(obj):
            # This consumer has already run. Diagnose an edited native cache;
            # rebinding now would require another kernel pass. Managed Rebuild
            # restores the authored selector inside its own transaction.
            _refresh_feature(obj, allow_reference_writes=False)
        for consumer in obj.Document.Objects:
            if consumer == obj or "QueryInputs" not in consumer.PropertiesList or not _active(consumer):
                continue
            if obj in consumer.OutListRecursive:
                _refresh_feature(consumer, allow_reference_writes=_in_transaction(obj.Document))
    finally:
        _native_refreshing = False
