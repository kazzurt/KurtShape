"""Read-only last-modifier attribution for a selected bounded native face.

This is deliberately separate from ``created_by``.  The operation adapters use
the native, recorded predecessor solids, not face proximity.  A face passes an
operation only when its entire bounded surface *and* boundary curves are
equivalent.  This also handles native Hole/refinement maps whose history grammar
is unavailable.  No document property, hasher, transaction or recompute is used.
"""
from __future__ import annotations

from collections import OrderedDict
import copy
import json
import re

import Part

from . import document_index, selectors, studio


LINEAR_TOLERANCE_MM = 1e-7
RELATIVE_MEASURE_TOLERANCE = 1e-10
_FACE = re.compile(r"Face[1-9][0-9]*$")
_STUDIO = {"pad", "pocket", "revolve", "sweep", "loft", "boolean_parts",
           "split_part", "transform_part", "linear_pattern_parts",
           "circular_pattern_parts", "mirror_parts"}
_NATIVE = {"PartDesign::Pad", "PartDesign::Pocket", "PartDesign::Hole",
           "PartDesign::Fillet", "PartDesign::Chamfer", "PartDesign::Thickness",
           "PartDesign::AdditiveLoft", "PartDesign::SubtractiveLoft",
           "PartDesign::Revolution", "PartDesign::Groove",
           "PartDesign::AdditivePipe", "PartDesign::SubtractivePipe",
           "PartDesign::Feature", "PartDesign::FeatureBase"}


def _answer(status, reason, feature=None, **details):
    return {"status": status, "feature": feature, "reason": reason, **details}


def _world(obj):
    return selectors.world_shape(selectors.result_source(obj))


def _measure_close(first, second, dimension):
    absolute = LINEAR_TOLERANCE_MM ** dimension
    return abs(first - second) <= max(absolute, RELATIVE_MEASURE_TOLERANCE * max(abs(first), abs(second)))


def _equivalent(first, second):
    """True/False, or None when the kernel cannot prove full face equivalence.

    Area and bounds only reject candidates.  Acceptance requires a full native
    face intersection covering both faces, plus the complete boundary-curve
    intersection covering both boundaries, and agreeing physical normals.
    """
    if first.isEqual(second):
        return True
    if not _measure_close(first.Area, second.Area, 2):
        return False
    a, b = first.BoundBox, second.BoundBox
    if any(abs(getattr(a, field) - getattr(b, field)) > LINEAR_TOLERANCE_MM
           for field in ("XMin", "YMin", "ZMin", "XMax", "YMax", "ZMax")):
        return False
    try:
        overlap = first.common(second)
        if not _measure_close(overlap.Area, first.Area, 2) or not _measure_close(overlap.Area, second.Area, 2):
            return False
        # Periodic seams are parameterization, not an outer boundary or hole.
        # Their position may change while the complete bounded face is equal.
        first_edges = [edge for edge in first.Edges if not edge.isSeam(first)]
        second_edges = [edge for edge in second.Edges if not edge.isSeam(second)]
        if bool(first_edges) != bool(second_edges):
            return False
        if first_edges:
            first_boundary = Part.makeCompound(first_edges)
            second_boundary = Part.makeCompound(second_edges)
            boundary = first_boundary.common(second_boundary)
            if not _measure_close(boundary.Length, first_boundary.Length, 1) or not _measure_close(boundary.Length, second_boundary.Length, 1):
                return False
        u0, u1, v0, v1 = first.ParameterRange
        u, v = (u0 + u1) / 2, (v0 + v1) / 2
        point = first.valueAt(u, v)
        other_u, other_v = second.Surface.parameter(point)
        normal, other = first.normalAt(u, v), second.normalAt(other_u, other_v)
        return normal.dot(other) > 1 - 1e-10
    except (RuntimeError, ValueError, TypeError, AttributeError, Part.OCCError):
        return None


class FaceProvenance:
    """Resolve exact face picks without changing native selection or the model."""
    def __init__(self, core):
        self.core = core
        self._cache = OrderedDict()
        self._contexts = OrderedDict()

    def clear(self):
        self._cache.clear()
        self._contexts.clear()

    def _token(self, doc):
        index = document_index.get(doc)
        if index is None:
            return None
        return (id(doc), doc.Name, index.token("structure", "history", "topology", "placement"),
                doc.UndoCount, doc.RedoCount)

    def resolve(self, doc, object_name, subelement):
        """Return resolved/unavailable/ambiguous; unsupported evidence never guesses."""
        if not isinstance(subelement, str) or not _FACE.fullmatch(subelement):
            return _answer("unavailable", "Select one exact face")
        try:
            obj = doc.getObject(object_name)
            if obj is None or not hasattr(obj, "Shape"):
                return _answer("unavailable", "Selected object is no longer available")
            if obj.TypeId == "App::Link" or getattr(obj, "KurtShapeEmbeddedSource", False):
                return _answer("unavailable", "Assembly snapshots do not contain source feature history")
            if not studio.is_active(obj):
                return _answer("unavailable", "Selected result is outside the evaluated history")
            meta = doc.getObject("KurtShapeProject")
            if meta is not None and (getattr(meta, "BuildStatus", "valid") != "valid" or getattr(meta, "RebuildReason", "")):
                return _answer("unavailable", "Model does not have a current valid evaluated build")
            token = self._token(doc)
            key = (token, obj.Name, subelement)
            if token is not None and key in self._cache:
                self._cache.move_to_end(key)
                return copy.deepcopy(self._cache[key])
            context = self._contexts.get(token) if token is not None else None
            if context is None:
                context = _Context(doc)
                if token is not None:
                    self._contexts[token] = context
                    while len(self._contexts) > 2:
                        self._contexts.popitem(last=False)
            if context.not_ready:
                return _answer("unavailable", "Native history contains unevaluated or failed features", features=context.not_ready)
            source = selectors.result_source(obj)
            shape = context.shape(source)
            index = int(subelement[4:]) - 1
            if index >= len(shape.Faces):
                return _answer("unavailable", "Selected face is no longer available")
            answer = context.trace(source, index)
            answer = {**answer, "object": obj.Name, "subelement": subelement,
                      "tolerance_mm": LINEAR_TOLERANCE_MM}
            if token != self._token(doc):
                return _answer("unavailable", "Model changed while resolving the selected face")
            if token is not None:
                self._cache[key] = copy.deepcopy(answer)
                while len(self._cache) > 512:
                    self._cache.popitem(last=False)
            return answer
        except (RuntimeError, ValueError, TypeError, AttributeError, KeyError, IndexError, ReferenceError, Part.OCCError) as exc:
            return _answer("unavailable", "Native face history could not be read", detail=str(exc))


class _Context:
    def __init__(self, doc):
        self.doc = doc
        self.sequence = studio.order(doc)
        self.positions = {obj.Name: i for i, obj in enumerate(self.sequence)}
        self.not_ready = [obj.Name for obj in self.sequence if studio.is_active(obj)
                          and set(obj.State) & {"Touched", "Invalid", "Error"}]
        self.shapes = {}
        self.resolved = {}
        self.predecessors = {}

    def shape(self, obj):
        if obj.Name not in self.shapes:
            self.shapes[obj.Name] = _world(obj)
        return self.shapes[obj.Name]

    def operation(self, obj):
        owner = getattr(obj, "KurtShapeOperationOwner", "")
        return self.doc.getObject(owner) if owner else obj

    def inputs(self, obj, operation, request):
        """Exact recorded operands at the operation's own history position."""
        if operation.Name in self.predecessors:
            return self.predecessors[operation.Name]
        position = self.positions[operation.Name]
        if request:
            ids = set(getattr(operation, "KurtShapeInputPartIds", []))
            if request["op"] == "boolean_parts" and request.get("kind", "union") == "subtract":
                ids &= set(request["targets"])
            prior = studio.results(self.doc, before=operation)
            if prior is None:
                return None
            values = [candidate for candidate in prior if studio.part_id(candidate) in ids]
            if ids and len({studio.part_id(value) for value in values}) != len(ids):
                return None
        else:
            # Native PartDesign features consume only their own preceding Body
            # solid.  Do not treat a hole's private cutter/profile as a source.
            from .bodies import owner
            body = owner(self.doc, obj)
            base = getattr(obj, "Base", None)
            base = base[0] if isinstance(base, (list, tuple)) and base else None
            base = base or getattr(obj, "BaseFeature", None)
            if base is not None and hasattr(base, "Shape") and not base.Shape.isNull() and base.Shape.Solids:
                values = [base]
            else:
                values = [candidate for candidate in self.sequence[:position]
                          if owner(self.doc, candidate) == body and hasattr(candidate, "Shape")
                          and not candidate.Shape.isNull() and candidate.Shape.Solids]
                values = values[-1:]
        self.predecessors[operation.Name] = values
        return values

    def trace(self, obj, face_index, seen=()):
        key = obj.Name, face_index
        if key in self.resolved:
            return self.resolved[key]
        if key in seen:
            return _answer("unavailable", "Native predecessor history is cyclic")
        operation = self.operation(obj)
        if operation is None or operation.Name not in self.positions:
            return _answer("unavailable", "Result has no visible modeling operation")
        text = getattr(operation, "KurtShapeStudioOperation", "")
        request = json.loads(text) if text else {}
        if (request and request.get("op") not in _STUDIO) or (not request and operation.TypeId not in _NATIVE):
            return _answer("unavailable", "This modeling operation has no verified face-history adapter")
        # Generated copies are deliberate new occurrences even if a symmetric
        # transformation leaves an individual bounded face coincident.
        generator = request.get("op") in {"transform_part", "linear_pattern_parts", "circular_pattern_parts", "mirror_parts"}
        if request.get("op") == "transform_part" and not request.get("copy", False):
            placement = studio._transform(request)
            if placement.Base.Length <= LINEAR_TOLERANCE_MM and abs(placement.Rotation.Angle) <= 1e-12:
                generator = False
        if generator and request.get("operation", "new") == "new":
            answer = _answer("resolved", "Face belongs to this transform or generated copy", operation.Name)
            self.resolved[key] = answer
            return answer
        prior = self.inputs(obj, operation, request)
        if prior is None:
            return _answer("unavailable", "Recorded predecessor solids are unavailable")
        face = self.shape(obj).Faces[face_index]
        matches, uncertain = [], False
        for candidate in prior:
            candidate = selectors.result_source(candidate)
            for index, previous in enumerate(self.shape(candidate).Faces):
                same = _equivalent(face, previous)
                if same is True:
                    matches.append((candidate, index))
                elif same is None:
                    uncertain = True
        if uncertain:
            return _answer("unavailable", "Kernel could not prove complete predecessor-face equivalence")
        if not matches:
            imported = operation.TypeId in {"PartDesign::Feature", "PartDesign::FeatureBase"}
            if imported and prior:
                return _answer("unavailable", "Unrecorded native feature cannot prove how it changed its input")
            answer = _answer("resolved", "Earlier history unavailable" if imported else "Operation changed or created this bounded face",
                             operation.Name, earlier_history_unavailable=imported)
        else:
            inherited = [self.trace(candidate, index, seen + (key,)) for candidate, index in matches]
            unknown = [item for item in inherited if item["status"] != "resolved"]
            features = sorted({item["feature"] for item in inherited if item["status"] == "resolved"})
            if unknown:
                answer = _answer("unavailable", "An unchanged predecessor has unavailable history", candidates=features)
            elif len(features) != 1:
                answer = _answer("ambiguous", "Coincident predecessor faces have different modifiers", candidates=features)
            else:
                answer = {**inherited[0], "reason": "Unchanged through later operations; " + inherited[0]["reason"],
                          "passed_through": [operation.Name] + inherited[0].get("passed_through", [])}
        self.resolved[key] = answer
        return answer
