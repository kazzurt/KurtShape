"""Declarative native references evaluated at a feature's regeneration position.

The native document owns selectors and their resolved links. No geometry graph is
persisted here. Creator tracing uses the verified FreeCAD 1.1.4 unhashed H trailer
grammar; unsupported maps fail closed rather than guess another face.
"""
from __future__ import annotations
from collections import Counter, OrderedDict
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
from . import document_index, geometry


TOLERANCE = 1e-7
_TAG = re.compile(r";:H(-?[0-9a-f]+)(?::([0-9a-f]+))?,([FEV])$")
_ENTITY = {"face": ("Faces", "Face"), "edge": ("Edges", "Edge"), "vertex": ("Vertexes", "Vertex")}
_SCHEMA = {
    "created_by": {"kind", "feature", "entity_type", "cap"},
    "owned_by": {"kind", "part", "body", "entity_type"}, "all": {"kind", "entity_type"},
    "geometry": {"kind", "query", "geometry", "radius", "major_radius", "minor_radius", "tolerance"},
    "union": {"kind", "queries"},
    "intersection": {"kind", "queries"}, "subtraction": {"kind", "query", "subtract"},
    "adjacent": {"kind", "query", "entity_type", "adjacency"}, "tangent": {"kind", "query"},
    "parallel": {"kind", "query", "direction", "allow_antiparallel"}, "closest": {"kind", "query", "point"},
}
# Geometry-filter parameters: selector key -> geometry carrying it -> native
# primitive attribute. Cone radius is OCCT's reference radius (at its location).
_PARAMETERS = {
    "radius": {"circle": "Radius", "cylinder": "Radius", "sphere": "Radius", "cone": "Radius"},
    "major_radius": {"torus": "MajorRadius", "ellipse": "MajorRadius"},
    "minor_radius": {"torus": "MinorRadius", "ellipse": "MinorRadius"},
}
PARAMETER_TOLERANCE = 1e-6
# A face summary point must clear the face boundary, so a closest selector at
# it cannot tie with an adjacent face or edge.
_POINT_CLEARANCE = 1e-6
_evaluation_milliseconds = 0.0
_refresh_milliseconds = 0.0
_rebuild_metrics = {}
_native_pending = set()
_CONTEXT_LIMIT = 16


def _shape_frame(shape):
    placement = shape.Placement
    return tuple(placement.Base) + tuple(placement.Rotation.Q)


def _memo(doc, kind, objects, parameters, compute):
    cache = geometry.provider(doc)
    return cache.memo(kind, objects, parameters, compute) if cache is not None else compute()


def _row_scalar(row, field):
    shape, obj = row["_shape"], row["_object"]
    key = (row["entity_type"], row["subelement"], field, _shape_frame(shape))
    def compute():
        if field in _PARAMETERS:
            attribute = _PARAMETERS[field].get(_geometry(row))
            if attribute is None:
                return None
            primitive = shape.Surface if row["entity_type"] == "face" else shape.Curve
            return float(getattr(primitive, attribute))
        if field == "point":
            return tuple(_element_point(row))
        value = geometry.scalar(shape, field)
        return tuple(value) if field == "center_of_mass" else value
    return _memo(obj.Document, "selector_scalar", (obj,), key, compute)


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
    if name in obj.PropertiesList and obj.getTypeIdOfProperty(name) != property_type:
        prior = getattr(obj, name)
        editor_mode = obj.getEditorMode(name)
        obj.removeProperty(name)
        obj.addProperty(property_type, name, "KurtShape references")
        setattr(obj, name, prior)
        obj.setEditorMode(name, editor_mode)
    if name not in obj.PropertiesList:
        obj.addProperty(property_type, name, "KurtShape references")
        obj.setEditorMode(name, 1)
    if getattr(obj, name) != value:
        setattr(obj, name, value)


def migrate_link_scopes(doc):
    """Selector sources can be native features in any Body in this document."""
    for obj in doc.Objects:
        if "QuerySources" in obj.PropertiesList and obj.getTypeIdOfProperty("QuerySources") != "App::PropertyLinkListGlobal":
            _property(obj, "QuerySources", list(obj.QuerySources), "App::PropertyLinkListGlobal")


def _finite(number):
    """math.isfinite, treating JSON integers too large for a float as not finite."""
    try:
        return math.isfinite(number)
    except OverflowError:
        return False


def _vector(value, name):
    if not isinstance(value, (list, tuple)) or len(value) != 3 or any(isinstance(n, bool) or not isinstance(n, (int, float)) or not _finite(n) for n in value):
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
    def __init__(self, doc, before=None, *, eager=False, cache=True):
        self.doc, self.before = doc, before
        self.index = index = document_index.get(doc) if cache else None
        topology = index.derived.get("selector_topology") if index is not None else None
        if topology is None:
            objects = index.objects() if index is not None else doc.Objects
            topology = {"objects": {obj.ID: obj for obj in objects},
                        "positions": {obj.Name: position for position, obj in enumerate(objects)},
                        "map_owners": None}
            if index is not None:
                index.derived["selector_topology"] = topology
        self._topology = topology
        self.objects, self.positions = topology["objects"], topology["positions"]
        self.lineages, self.multiplicities, self.dependencies = {}, {}, {}
        self._results = self._rows = None
        self._literal_rows = {}
        self._world_shapes = {}
        self.full_preparation = False
        self._count("selector_contexts")
        if eager:
            self.prepare_full()

    def _count(self, name, amount=1):
        if self.index is not None:
            self.index.counts[name] = self.index.counts.get(name, 0) + amount

    @property
    def map_owners(self):
        owners = self._topology["map_owners"]
        if owners is None:
            owners = {}
            entries = 0
            for obj in self.objects.values():
                if hasattr(obj, "Shape") and obj.TypeId != "PartDesign::Body":
                    for name in obj.Shape.ElementMap:
                        owners.setdefault(name, []).append(obj)
                        entries += 1
            self._topology["map_owners"] = owners
            self._count("selector_map_owner_builds")
            self._count("selector_map_entries", entries)
        return owners

    @property
    def results(self):
        if self._results is None:
            self._results = self._prepare_results()
            self._count("selector_membership_builds")
        return self._results

    def _prepare_results(self):
        """Keep native result order and part identity without enumerating entities."""
        doc, before = self.doc, self.before
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
        prepared = []
        for result in results:
            obj = result.Tip if result.TypeId == "PartDesign::Body" and result.Tip else result
            if not hasattr(obj, "Shape") or obj.Shape.isNull():
                continue
            prepared.append((obj, obj.Name if obj.TypeId == "Sketcher::SketchObject" else _part_id(doc, result)))
        return prepared

    @property
    def rows(self):
        if self._rows is None:
            self._rows = self._build_rows_full()
            self._count("selector_row_builds")
            self._count("selector_rows", len(self._rows))
        return self._rows

    def _build_rows_full(self):
        """The complete native entity enumeration remains the comparison path."""
        rows = []
        for obj, part in self.results:
            shape = self.world_shape(obj)
            for kind, (collection, prefix) in _ENTITY.items():
                for i, subshape in enumerate(getattr(shape, collection)):
                    rows.append({"feature": obj.Name, "subelement": prefix + str(i + 1),
                                 "entity_type": kind, "part": part, "_object": obj, "_shape": subshape})
        return rows

    def world_shape(self, obj):
        # Literal seeds and later adjacency/tangent enumeration must share the
        # same copied native topology for OCCT isSame comparisons.
        if obj.Name not in self._world_shapes:
            self._world_shapes[obj.Name] = _world_shape(obj)
        return self._world_shapes[obj.Name]

    def prepare_full(self):
        """Force the former eager preparation for comparison and fallback."""
        self.rows
        self.map_owners
        self.full_preparation = True
        return self

    def prior_part(self, part):
        # The historical Body rule selects the first matching full row. Empty
        # compounds have no rows, so they cannot become a new literal target.
        for obj, identifier in self.results:
            if identifier == part and any(getattr(obj.Shape, collection) for collection, _ in _ENTITY.values()):
                return obj
        return None

    def literal_rows(self, obj, element, entity_type):
        if self._rows is not None:
            available = [row for row in self._rows if row["feature"] == obj.Name and row["subelement"] == element]
            if available:
                return available
        key = obj.Name, element
        if key not in self._literal_rows:
            # Preserve the full path's current-result part identity (notably
            # sketches) and its fallback for explicit historical features.
            parts = [part for source, part in self.results if source == obj]
            try:
                shape = self.world_shape(obj).getElement(element)
            except Exception:
                return []
            self._literal_rows[key] = [{"feature": obj.Name, "subelement": element,
                "entity_type": entity_type, "part": part, "_object": obj, "_shape": shape}
                for part in parts or [_part_id(self.doc, obj)]]
            self._count("selector_literal_reads")
        return self._literal_rows[key]

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
    if kind == "edge" and shape.Degenerated:
        # Sphere poles and similar collapsed edges have no native 3D curve.
        return "degenerate"
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
    point, normal = App.Vector(*geometry.scalar(faces[0], "center_of_mass")), faces[0].normalAt(0, 0)
    if any(abs(abs(face.normalAt(0, 0).dot(normal)) - 1) > TOLERANCE
           or abs(normal.dot(App.Vector(*geometry.scalar(face, "center_of_mass")) - point)) > TOLERANCE for face in faces):
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
        return _on_cap_shapes(context, rows, start_shape, end_shape, cap, (obj, profile),
                              ("revolve", angle, first_angle, tuple(origin), tuple(axis)))
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
                and abs(normal.dot(App.Vector(*_row_scalar(row, "center_of_mass")) - point)) < TOLERANCE)
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


def _on_cap_shapes(context, rows, start, end, cap, sources=(), parameters=()):
    def touches(row, shape, endpoint):
        entity = row["_shape"]
        if not geometry.bboxes_overlap(geometry.bounding_box(entity), geometry.bounding_box(shape), tolerance=TOLERANCE):
            return False
        key = (parameters, endpoint, row["entity_type"], row["subelement"], _shape_frame(entity), _shape_frame(shape))
        objects = (row["_object"], *sources)
        if row["entity_type"] == "vertex":
            return _memo(context.doc, "selector_cap_distance", objects, key,
                         lambda: geometry.distance(entity, shape)) < TOLERANCE
        field = "area" if row["entity_type"] == "face" else "length"
        return _memo(context.doc, "selector_cap_overlap", objects, key,
                     lambda: geometry.scalar(entity.common(shape), field)) > TOLERANCE
    answer = []
    for row in rows:
        on_start, on_end = touches(row, start, "start"), touches(row, end, "end")
        if cap == "start" and on_start or cap == "end" and on_end or cap == "side" and not on_start and not on_end:
            answer.append(row)
    return answer


def _literal_reference_full(context, selector):
    """Original row-based literal rules, independent of lazy membership reads."""
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
    return [{"feature": obj.Name, "subelement": element,
             "entity_type": {"Face": "face", "Edge": "edge", "Vertex": "vertex"}[match.group(1)],
             "part": _part_id(context.doc, obj), "_object": obj, "_shape": shape}]


def _measure(value, name, positive=False):
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or not _finite(value)
            or value < 0 or positive and value == 0):
        raise _error("invalid_selector", name + " requires a " + ("positive" if positive else "non-negative")
                     + " finite millimeter number")
    return float(value)


def _parameter_filters(selector, geometric_filter):
    """Validated {parameter: millimeters} and absolute tolerance of a geometry filter."""
    filters = {}
    for name, carriers in _PARAMETERS.items():
        if name not in selector:
            continue
        if geometric_filter not in carriers:
            hint = ("; " + geometric_filter + " uses major_radius/minor_radius"
                    if name == "radius" and geometric_filter in {"torus", "ellipse"} else "")
            raise _error("invalid_selector", name + " applies only to " + ", ".join(sorted(carriers)) + " geometry" + hint,
                         geometry=geometric_filter, field=name)
        filters[name] = _measure(selector[name], name, positive=True)
    if "tolerance" not in selector:
        return filters, PARAMETER_TOLERANCE
    if not filters:
        raise _error("invalid_selector", "tolerance requires a radius, major_radius or minor_radius filter", field="tolerance")
    return filters, _measure(selector["tolerance"], "tolerance")


def _parameter_matches(actual, expected, tolerance):
    return actual is not None and abs(actual - expected) <= tolerance


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
        if context.full_preparation:
            return _literal_reference_full(context, selector)
        obj = context.doc.getObject(selector["feature"])
        if obj is None:
            return []
        if obj.TypeId == "PartDesign::Body" and context.before is not None:
            obj = context.prior_part(_part_id(context.doc, obj))
            if obj is None:
                return []
        else:
            obj = obj.Tip if obj.TypeId == "PartDesign::Body" and obj.Tip else obj
        element = selector.get("subelement", "")
        match = re.fullmatch(r"(Face|Edge|Vertex)([1-9][0-9]*)", str(element))
        if not match or not hasattr(obj, "Shape"):
            raise _error("invalid_reference", "Native reference requires FaceN, EdgeN or VertexN")
        return context.literal_rows(obj, element, {"Face": "face", "Edge": "edge", "Vertex": "vertex"}[match.group(1)])
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
        geometric_filter = selector.get("geometry")
        if geometric_filter not in {"plane", "cylinder", "cone", "sphere", "torus", "line", "circle", "ellipse", "spline", "point"}:
            raise _error("invalid_selector", "Unknown geometry filter")
        filters, tolerance = _parameter_filters(selector, geometric_filter)
        return [row for row in rows if _geometry(row) == geometric_filter
                and all(_parameter_matches(_row_scalar(row, name), value, tolerance) for name, value in filters.items())]
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
        coordinates = _vector(selector.get("point"), "point")
        point = Part.Vertex(coordinates)
        point_box = geometry.bounding_box(point)
        candidates = sorted(enumerate(rows), key=lambda item:
                            (geometry.bbox_distance(geometry.bounding_box(item[1]["_shape"]), point_box), item[0]))
        distances, minimum = [], math.inf
        for index, row in candidates:
            entity = row["_shape"]
            if geometry.bbox_distance(geometry.bounding_box(entity), point_box) > minimum + TOLERANCE:
                continue
            key = (row["entity_type"], row["subelement"], _shape_frame(entity), tuple(coordinates))
            value = _memo(context.doc, "selector_closest_distance", (row["_object"],), key,
                          lambda: geometry.distance(entity, point))
            distances.append((value, row))
            minimum = min(minimum, value)
        if not distances:
            return []
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


def _xyz(vector):
    return [vector.x, vector.y, vector.z]


def _unit(vector):
    vector = App.Vector(vector)
    if vector.Length > 0:
        vector.normalize()
    return _xyz(vector)


def _surface_parameters(surface, u, v, bounds):
    """Native projection parameters moved into the face's periodic range."""
    u0, u1, v0, v1 = bounds
    if surface.isUPeriodic() and not u0 <= u <= u1:
        u = u0 + (u - u0) % surface.UPeriod()
    if surface.isVPeriodic() and not v0 <= v <= v1:
        v = v0 + (v - v0) % surface.VPeriod()
    return u, v


def _face_point(face, center_of_mass):
    """A point on the face, clear of its boundary whenever one can be found.

    Order: parametric centre, a parameter grid nearest that centre, the
    projected centre of mass, small inward steps from edge midpoints, and
    finally the longest edge's midpoint (on the boundary, still on the face).
    """
    bounds = u0, u1, v0, v1 = face.ParameterRange
    du, dv = u1 - u0, v1 - v0
    surface = face.Surface
    edges = [edge for edge in face.Edges if not edge.Degenerated]
    boundary = []

    def interior(u, v):
        try:
            if not face.isPartOfDomain(u, v):
                return None
            point = face.valueAt(u, v)
            if edges:
                if not boundary:
                    boundary.append(Part.Compound(edges))
                if boundary[0].distToShape(Part.Vertex(point))[0] <= _POINT_CLEARANCE:
                    return None
            return point
        except Exception:
            # Native classification can fail on a degenerate parameter curve;
            # another candidate is tried.
            return None

    steps = 8
    grid = sorted((((i + .5) / steps, (j + .5) / steps) for i in range(steps) for j in range(steps)),
                  key=lambda item: ((item[0] - .5) ** 2 + (item[1] - .5) ** 2, item))
    for a, b in [(.5, .5)] + grid:
        point = interior(u0 + a * du, v0 + b * dv)
        if point is not None:
            return point
    seeds = [App.Vector(*center_of_mass)] + [edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2)
                                             for edge in sorted(edges, key=lambda edge: -edge.Length)]
    for index, seed in enumerate(seeds):
        try:
            u, v = _surface_parameters(surface, *surface.parameter(seed), bounds)
        except Exception:
            continue  # Native projection failed for this seed; try the next one.
        offsets = [(0.0, 0.0)] if index == 0 else [
            (scale * math.cos(angle), scale * math.sin(angle))
            for scale in (1e-2, 1e-3, 1e-4) for angle in (k * math.pi / 4 for k in range(8))]
        for a, b in offsets:
            point = interior(u + a * du, v + b * dv)
            if point is not None:
                return point
    if len(seeds) > 1:
        return seeds[1]
    return face.Vertexes[0].Point if face.Vertexes else App.Vector(*center_of_mass)


def _element_point(row):
    shape = row["_shape"]
    if row["entity_type"] == "edge":
        return _xyz(shape.valueAt((shape.FirstParameter + shape.LastParameter) / 2))
    if row["entity_type"] == "face":
        return _xyz(_face_point(shape, _row_scalar(row, "center_of_mass")))
    return _xyz(shape.Point)


def _detail(row, kind):
    """Usable geometry for resolve_selector output; never used by evaluation."""
    shape, result = row["_shape"], {"point_mm": list(_row_scalar(row, "point"))}
    if row["entity_type"] == "edge":
        if kind == "line":
            result["direction"] = _unit(shape.valueAt(shape.LastParameter) - shape.valueAt(shape.FirstParameter))
        elif kind in {"circle", "ellipse"}:
            curve = shape.Curve
            if kind == "circle":
                result["radius_mm"] = _row_scalar(row, "radius")
            else:
                result["major_radius_mm"] = _row_scalar(row, "major_radius")
                result["minor_radius_mm"] = _row_scalar(row, "minor_radius")
            result["geometric_center_mm"] = _xyz(curve.Center)
            result["axis"] = _unit(curve.Axis)
    elif row["entity_type"] == "face" and kind in {"cylinder", "cone", "sphere", "torus"}:
        surface = shape.Surface
        if kind == "torus":
            result["major_radius_mm"] = _row_scalar(row, "major_radius")
            result["minor_radius_mm"] = _row_scalar(row, "minor_radius")
        else:
            result["radius_mm"] = _row_scalar(row, "radius")
        if kind in {"sphere", "torus"}:
            result["geometric_center_mm"] = _xyz(surface.Center)
        else:
            result["axis_point_mm"] = _xyz(surface.Center)
        if kind != "sphere":
            result["axis"] = _unit(surface.Axis)
        if kind == "cone":
            result["apex_mm"] = _xyz(surface.Apex)
            result["semi_angle_rad"] = float(surface.SemiAngle)
    return result


def _summary(row, detail=False):
    shape = row["_shape"]
    result = {"geometry": _geometry(row), "center_mm": list(_row_scalar(row, "center_of_mass"))}
    if row["entity_type"] == "face":
        result["area_mm2"] = _row_scalar(row, "area")
        if result["geometry"] == "plane":
            result["normal"] = list(shape.normalAt(0, 0))
    elif row["entity_type"] == "edge":
        result["length_mm"] = _row_scalar(row, "length")
    if detail:
        result.update(_detail(row, result["geometry"]))
    return result


def _resolved(context, selector, detail=False):
    values = _evaluate(context, selector)
    return [{**{key: value for key, value in row.items() if not key.startswith("_")}, "summary": _summary(row, detail)}
            for row in sorted(values, key=_identity)]


def _resolve_full(doc, selector, before=None, detail=False):
    """Fresh complete preparation, retained as an explicit correctness oracle."""
    return _resolved(_Context(doc, before, eager=True, cache=False), selector, detail)


def resolve(doc, selector, before=None, detail=False):
    """Matched rows with a basic summary; ``detail`` adds resolve_selector geometry.

    Detail (points on elements, radii, axes) is computed only for that read
    output and ambiguity diagnostics, never while consumers rebind.
    """
    global _evaluation_milliseconds
    start = time.perf_counter()
    try:
        index = document_index.get(doc)
        if index is not None and not document_index.local_dependencies(index):
            # Foreign sources can change without advancing this document's
            # token. Use fresh full topology and dispose nested scalar caches.
            def discard_foreign():
                current = document_index.get(doc)
                if current is not None:
                    current.invalidate(structure=True)
                provider = geometry.provider(doc)
                if provider is not None:
                    provider.drop_document(doc)
            discard_foreign()
            try:
                return _resolve_full(doc, selector, before, detail)
            finally:
                discard_foreign()
        token = index.token(*sorted(document_index.DOMAINS)) if index is not None else None
        def changed():
            return index is not None and (document_index.get(doc) is not index
                or token != index.token(*sorted(document_index.DOMAINS)))
        try:
            if index is None:
                context = _Context(doc, before)
            else:
                contexts = index.derived.setdefault("selector_contexts", OrderedDict())
                boundary = before.Name if hasattr(before, "Name") else before
                if boundary not in contexts:
                    contexts[boundary] = _Context(doc, before)
                    while len(contexts) > _CONTEXT_LIMIT:
                        contexts.popitem(last=False)
                contexts.move_to_end(boundary)
                context = contexts[boundary]
            result = _resolved(context, selector, detail)
        except Exception:
            if not changed():
                raise
        else:
            if not changed():
                return result
        # Native reads can reenter document callbacks. Discard nested history
        # and geometry memos too: a builder can store an old shape's scalar
        # under an object's new version after that callback has invalidated it.
        def discard():
            current = document_index.get(doc)
            if current is not None:
                current.invalidate(structure=True)
            provider = geometry.provider(doc)
            if provider is not None:
                provider.drop_document(doc)
        discard()
        current = document_index.get(doc)
        fallback_token = current.token(*sorted(document_index.DOMAINS)) if current is not None else None
        try:
            result = _resolve_full(doc, selector, before, detail)
            if (document_index.get(doc) is not current or current is not None
                    and fallback_token != current.token(*sorted(document_index.DOMAINS))):
                raise _error("selector_document_changed", "Native document changed during selector resolution; retry")
            return result
        finally:
            discard()
    finally:
        _evaluation_milliseconds += (time.perf_counter() - start) * 1000


def _detailed_matches(doc, selector, before=None, entity_type=None):
    """Ambiguity diagnostics carry the resolve_selector geometry for refining picks."""
    values = resolve(doc, selector, before, detail=True)
    return [row for row in values if row["entity_type"] == entity_type] if entity_type else values


def native_reference(doc, spec, before=None, entity_type=None):
    values = resolve(doc, spec, before)
    if entity_type:
        values = [row for row in values if row["entity_type"] == entity_type]
    if not values:
        raise _error("missing_reference", "Reference selector resolves to no matching element")
    if len(values) != 1:
        raise _error("ambiguous_reference", "Reference selector resolves to several elements",
                     matches=_detailed_matches(doc, spec, before, entity_type))
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
        from .sketch_tools import external_links
        index = info["index"]
        obj, name = references[0]
        current = external_links(feature)
        if not 0 <= index < len(current):
            raise _error("invalid_selector_metadata", "Native external geometry input no longer exists")
        if current[index] != (obj, name):
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
            from .sketch_tools import restore_sketch_content
            restore_sketch_content(feature, output.getvalue())
            feature.touch()
    else:
        raise _error("invalid_selector_metadata", "Unknown native reference binding mode")


def _native_references(feature, info):
    """Read the actual native cache instead of trusting its JSON mirror."""
    mode = info.get("mode", "linksub")
    value = getattr(feature, info["native_property"])
    if mode == "external":
        from .sketch_tools import external_links
        value = external_links(feature)
        index = info["index"]
        links = [(value[index][0], [value[index][1]])] if 0 <= index < len(value) else []
    elif mode == "linksub_index":
        index = info.get("index", 0)
        links = [(value[0], [value[1][index]])] if value[0] is not None and 0 <= index < len(value[1]) else []
    elif mode in {"linksub", "linksublist"}:
        links = [value] if isinstance(value, tuple) and len(value) == 2 and (value[0] is None or hasattr(value[0], "Name")) else list(value)
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
        raise _error("ambiguous_reference", "Reference selector resolves to several elements",
                     matches=_detailed_matches(feature.Document, selector, before=feature))
    for source in _sources(feature.Document, selector, before=feature):
        if source == feature or feature in source.OutListRecursive:
            raise _error("cyclic_reference", "Reference selector cannot target its consumer or a downstream feature")
    info["resolved"] = [{"feature": row["feature"], "subelement": row["subelement"]} for row in values]
    inputs[input_name] = info
    _set_reference(feature, info, values)
    _property(feature, "QueryInputs", json.dumps(inputs, sort_keys=True))
    sources = {obj.Name: obj for item in inputs.values() for obj in _sources(feature.Document, item["selector"], before=feature)}
    _property(feature, "QuerySources", list(sources.values()), "App::PropertyLinkListGlobal")
    health = _health(feature)
    health[input_name] = {"status": "healthy", "count": len(values)}
    _write_health(feature, health)
    _property(feature, "QueryResolutionLog", "[]")
    return values


def unbind(feature, input_name):
    """Stop an authored selector from overwriting a replaced native input."""
    if not _in_transaction(feature.Document):
        raise _error("selector_transaction_required", "Selector bindings must be removed inside the native mutation transaction")
    inputs = _json(feature, "QueryInputs")
    if input_name not in inputs:
        return False
    inputs.pop(input_name)
    if inputs:
        _property(feature, "QueryInputs", json.dumps(inputs, sort_keys=True))
        sources = {obj.Name: obj for info in inputs.values()
                   for obj in _sources(feature.Document, info["selector"], before=feature)}
        _property(feature, "QuerySources", list(sources.values()), "App::PropertyLinkListGlobal")
        health = _health(feature)
        health.pop(input_name, None)
        _write_health(feature, health)
        logs = json.loads(getattr(feature, "QueryResolutionLog", "[]"))
        _property(feature, "QueryResolutionLog", json.dumps([entry for entry in logs if entry.get("input") != input_name], sort_keys=True))
    else:
        for prop in ("QueryInputs", "QuerySources", "QueryHealth", "QueryResolutionLog"):
            if prop in feature.PropertiesList:
                feature.removeProperty(prop)
    return True


def move_binding(source, destination, input_name, native_property, mode):
    """Transfer an authored native input during scope migration, preserving history."""
    inputs = _json(source, "QueryInputs")
    binding = inputs.pop(input_name, None)
    if binding is None:
        return False
    moved = dict(binding, native_property=native_property, mode=mode)
    moved["resolved"] = _native_references(destination, moved)
    target_inputs = _json(destination, "QueryInputs")
    target_inputs[input_name] = moved
    _property(destination, "QueryInputs", json.dumps(target_inputs, sort_keys=True))
    sources = {obj.Name: obj for info in target_inputs.values()
               for obj in _sources(source.Document, info["selector"], before=source)}
    _property(destination, "QuerySources", list(sources.values()), "App::PropertyLinkListGlobal")
    health = _health(source)
    target_health = _health(destination)
    target_health[input_name] = health.pop(input_name, {"status": "healthy", "count": len(moved["resolved"])})
    _write_health(destination, target_health)
    logs = json.loads(getattr(source, "QueryResolutionLog", "[]"))
    _property(destination, "QueryResolutionLog", json.dumps([entry for entry in logs if entry.get("input") == input_name], sort_keys=True))
    if inputs:
        _property(source, "QueryInputs", json.dumps(inputs, sort_keys=True))
        remaining = {obj.Name: obj for info in inputs.values() for obj in _sources(source.Document, info["selector"], before=source)}
        _property(source, "QuerySources", list(remaining.values()), "App::PropertyLinkListGlobal")
        _write_health(source, health)
        _property(source, "QueryResolutionLog", json.dumps([entry for entry in logs if entry.get("input") != input_name], sort_keys=True))
    else:
        for prop in ("QueryInputs", "QuerySources", "QueryHealth", "QueryResolutionLog"):
            if prop in source.PropertiesList:
                source.removeProperty(prop)
    return True


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
    _native_pending.discard(doc.Name)


def reference_errors(doc):
    errors = []
    for obj in doc.Objects:
        if not _active(obj):
            continue
        for name, health in _health(obj).items():
            if health.get("status") != "healthy":
                errors.append({"feature": obj.Name, "input": name, "reference_health": health["status"],
                               "message": "Reference " + name + " is " + health["status"] + (": " + health["error"] if health.get("error") else "")})
        for name, info in _json(obj, "QueryInputs").items():
            try:
                divergent = _native_references(obj, info) != info.get("resolved")
            except (AttributeError, TypeError, ValueError, KeyError):
                divergent = True
            if divergent and not any(
                    entry["feature"] == obj.Name and entry["input"] == name for entry in errors):
                errors.append({"feature": obj.Name, "input": name, "reference_health": "missing",
                               "code": "pending_selector_resolution",
                               "message": "Selector native input changed; run a managed rebuild to update its native input"})
    return errors


def native_recomputed(obj):
    """Observer notification only; reconciliation belongs to Controller.sync."""
    _native_pending.add(obj.Document.Name)


def reconcile_native(doc):
    """Diagnose an already completed native recompute without rebinding inputs."""
    try:
        for obj in doc.Objects:
            if "QueryInputs" in obj.PropertiesList and _active(obj):
                _refresh_feature(obj, allow_reference_writes=False)
        return reference_errors(doc)
    finally:
        _native_pending.discard(doc.Name)
