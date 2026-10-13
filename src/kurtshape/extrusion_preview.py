"""Disposable native extrusion evaluation and a non-pickable viewport overlay.

Only the accepted controller operation changes the project. Preview evaluates
the same Pad/Pocket operation in a hidden, temporary native FCStd, then keeps
detached BRep shapes. No preview objects enter the authoritative document.
"""
from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import tempfile
import time

import FreeCAD as App
import Part

from .core import OperationError, number
from . import geometry
from .bodies import results as native_results

PREVIEW_OPS = {"pad", "pocket", "revolve", "sweep", "loft", "boolean_parts",
               "split_part", "transform_part", "linear_pattern_parts", "circular_pattern_parts",
               "mirror_parts", "fillet", "chamfer", "shell", "extrude_face", "create_plane", "move_face"}


def _aggregate_shape(document):
    shapes = [_world_shape(obj) for obj in native_results(document)
              if hasattr(obj, "Shape") and not obj.Shape.isNull() and obj.Shape.Solids]
    return Part.makeCompound(shapes) if shapes else Part.Shape()


def _removal(proposal):
    if proposal.get("op") in {"fillet", "chamfer", "shell"} or proposal.get("op") == "boolean_parts" and proposal.get("kind") in {"subtract", "intersect"}:
        return True
    return proposal.get("operation", "remove" if proposal.get("op") == "pocket" else "add") in {"remove", "intersect"} or proposal.get("op") in {"shell"}


@dataclass(frozen=True)
class ExtrusionResult:
    valid: bool
    base_revision: str
    proposal: dict
    body_id: str | None = None
    shape: object = None
    material_shape: object = None
    measurements: dict | None = None
    error: dict | None = None
    cached: bool = False
    milliseconds: float = 0
    provisional: bool = False
    mesh: dict | None = None
    mesh_key: str | None = None
    transform: dict | None = None
    phase_milliseconds: dict | None = None


@contextmanager
def _preview_phase(phases, name):
    began = time.perf_counter()
    try:
        yield
    finally:
        phases[name] = phases.get(name, 0.0) + (time.perf_counter() - began) * 1000


@dataclass(frozen=True)
class ImmutablePreviewSnapshot:
    """Private borrowed file; its owner retains it until evaluation closes."""
    path: Path
    document: object
    revision: str
    generation: int
    file_identity: tuple

    @staticmethod
    def _identity(path):
        info = path.stat()
        if not path.is_file():
            raise OperationError("invalid_preview_snapshot", "Preview snapshot is not a native file")
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns

    @classmethod
    def bind(cls, controller, document, path):
        path = Path(path).resolve(strict=True)
        return cls(path, document, controller._meta(document).Revision,
                   controller.observer.state(document)["generation"], cls._identity(path))

    def validate(self, controller, document, revision):
        if (document is not self.document or revision != self.revision
                or controller.observer.state(document)["generation"] != self.generation):
            raise OperationError("stale_preview_snapshot", "The preview snapshot no longer matches its source")
        try:
            identity = self._identity(self.path)
        except OSError as exc:
            raise OperationError("invalid_preview_snapshot", "The preview snapshot is unavailable") from exc
        if identity != self.file_identity:
            raise OperationError("invalid_preview_snapshot", "The preview snapshot was changed")


def _normalize_preview_source(controller, document):
    """Restore persisted native map markers identically in source and clones.

    Native FCStd loading can omit Body/Plane marker strings while retaining
    their complete maps. Keep this narrowly scoped normalization shared with
    worker attachment; marker changes are never excluded from its comparison.
    """
    if not document.UseHasher:
        controller._restore_native_map_versions(document)


def _load_preview_clone(path, borrowed=False):
    if not borrowed:
        return App.openDocument(str(path), True, True)
    # openDocument deduplicates an already-open filename. The worker source
    # owns this same archive, so explicitly load it into a fresh native object
    # instead of reopening (and then accidentally editing/closing) the source.
    clone = App.newDocument("KurtShapePreviewClone", hidden=True, temp=True)
    clone.load(str(path))
    return clone


def render_mesh(material, outline):
    """Serialize display geometry; called in the exact worker for GUI use."""
    vertices, triangles = material.tessellate(0.15)
    if not triangles:
        raise OperationError("empty_preview", "The extrusion has no displayable faces")
    if len(vertices) > 500000 or len(triangles) > 1000000:
        raise OperationError("preview_too_large", "Preview exceeds the interactive display limit")
    points, segments = [], []
    for edge in outline.Edges:
        samples = edge.discretize(Deflection=0.15)
        if len(samples) > 1:
            points.extend((p.x, p.y, p.z) for p in samples)
            segments.append(len(samples))
    return {"vertices": [(v.x, v.y, v.z) for v in vertices], "triangles": triangles,
            "lines": points, "segments": segments}


class ProvisionalExtrusion:
    """Profile-only unit prisms. They are visual hints, never accepted solids."""
    def __init__(self, evaluator):
        self.evaluator = evaluator
        self.meshes = {}

    def evaluate(self, proposal):
        # Up-to and through-all need model-dependent exact evaluation. Their
        # UI stays responsive using the worker even without a provisional mesh.
        if (proposal.get("op") not in {"pad", "pocket"} or "length" not in proposal
                or proposal.get("end_type", "blind") != "blind"
                or proposal.get("op") == "pocket" and proposal.get("through_all", True)):
            return None
        doc = self.evaluator.document
        profile = doc.getObject(proposal["profile"])
        scoped = "operation" in proposal or "merge_scope" in proposal
        reversed_direction = proposal.get("reversed", proposal["op"] == "pocket" if scoped else False)
        sign = -1 if reversed_direction else 1
        if proposal["op"] == "pocket" and not scoped:
            sign *= -1
            # Legacy omitted direction retries the native cut on the other
            # side. Avoid guessing its material side in a provisional graphic.
            if "reversed" not in proposal:
                return None
        generation = self.evaluator.controller.observer.state(doc)["generation"]
        key = (profile.Name, generation, sign, _removal(proposal))
        if key not in self.meshes:
            shape = _world_shape(profile)
            wires = shape.Wires
            if not wires or any(not wire.isClosed() for wire in wires):
                return None
            face = Part.makeFace(wires, "Part::FaceMakerBullseye")
            direction = profile.getGlobalPlacement().Rotation.multVec(App.Vector(0, 0, sign))
            unit = face.extrude(direction)
            origin = profile.getGlobalPlacement().Base
            self.meshes[key] = (render_mesh(unit, unit), (origin.x, origin.y, origin.z),
                                (direction.x, direction.y, direction.z))
            # Depth changes reuse a mesh; limit changes of profile/placement.
            if len(self.meshes) > 8:
                del self.meshes[next(iter(self.meshes))]
        mesh, origin, direction = self.meshes[key]
        return ExtrusionResult(False, self.evaluator.expected_revision, proposal,
                               body_id=proposal.get("body"), provisional=True,
                               mesh=mesh, mesh_key=repr(key),
                               transform={"origin": origin, "direction": direction, "depth": proposal["length"]})


def _world_shape(body):
    shape = body.Shape.copy()
    # Body.Shape already includes its own Placement; an enclosing App::Part's
    # placement is applied by the native view provider rather than by Shape.
    shape.Placement = body.getGlobalPlacement() * body.Placement.inverse() * shape.Placement
    return shape


def _capture_gui(document):
    if not getattr(App, "GuiUp", False):
        return None
    import FreeCADGui as Gui
    view = Gui.getDocument(document.Name).activeView()
    selections = [(item.DocumentName, item.ObjectName, tuple(item.SubElementNames), tuple(item.PickedPoints))
                  for item in Gui.Selection.getSelectionEx()]
    return (view, view.getCamera(), Gui.getDocument(document.Name).Modified, selections)


def _restore_gui(document, state):
    if state is None:
        return
    import FreeCADGui as Gui
    view, camera, modified, selections = state
    if view.getCamera() != camera:
        view.setCamera(camera)
    Gui.getDocument(document.Name).Modified = modified
    # Native FCStd opening clears global selection even with hidden=True.
    # Restore the actual selected references and picked coordinates, rather
    # than relying on the custom history widget to infer selection afterward.
    current = [(item.DocumentName, item.ObjectName, tuple(item.SubElementNames), tuple(item.PickedPoints))
               for item in Gui.Selection.getSelectionEx()]
    if current != selections:
        Gui.Selection.clearSelection()
        for doc_name, object_name, elements, points in selections:
            obj = App.getDocument(doc_name).getObject(object_name)
            if elements:
                for index, element in enumerate(elements):
                    if index < len(points):
                        point = points[index]
                        Gui.Selection.addSelection(obj, element, point.x, point.y, point.z)
                    else:
                        Gui.Selection.addSelection(obj, element)
            else:
                Gui.Selection.addSelection(obj)


class ExtrusionEvaluator:
    """One revision-bound feature task; call close when its editor is dismissed.

    evaluate accepts a Pad/Pocket proposal, without envelope UUID/revision/id.
    Its proposal is suitable for the usual controller operation on acceptance.
    The source is snapshotted once per task. Eight recently requested native
    results are cached, so toggling direction/end type back does not recompute.
    """
    def __init__(self, controller, document, expected_revision, *, snapshot_source=None):
        self.controller = controller
        self.document = document
        self.document_name = document.Name
        self.expected_revision = expected_revision
        if snapshot_source is not None and not isinstance(snapshot_source, ImmutablePreviewSnapshot):
            raise TypeError("snapshot_source must be an ImmutablePreviewSnapshot")
        self._temporary = None
        self._borrowed_snapshot = snapshot_source
        self._snapshot = snapshot_source.path if snapshot_source is not None else None
        self._generation = snapshot_source.generation if snapshot_source is not None else None
        self._cache = OrderedDict()
        self.closed = False
        self.evaluations = 0
        self.snapshot_captures = 0

    def _guard(self):
        core, doc = self.controller, self.document
        if self.closed:
            raise OperationError("preview_closed", "Start the extrusion tool again")
        if not core._is_open(doc):
            raise OperationError("unknown_document", "The extrusion's project was closed")
        if core.busy:
            raise OperationError("busy", "Wait for the current operation to finish")
        if not core.is_managed(doc):
            raise OperationError("unmanaged_document", "Adopt a copy before extruding")
        # saveCopy can emit native property notifications with unchanged
        # intent. Reconcile those through the controller, just as dispatch
        # does, before deciding whether an external edit invalidated the task.
        core.sync(doc)
        if core._meta(doc).Revision != self.expected_revision:
            raise OperationError("stale_revision", "The project changed; start the extrusion again")
        if core.identifier(doc) in core.sketch_edits or doc.HasPendingTransaction:
            raise OperationError("sketch_edit_active", "Finish editing the sketch before extruding")
        if getattr(App, "GuiUp", False) and core._native_edit_active():
            raise OperationError("sketch_edit_active", "Finish the current native editor before extruding")
        if self._borrowed_snapshot is not None:
            self._borrowed_snapshot.validate(core, doc, self.expected_revision)

    def _proposal(self, proposal, solve=True):
        if not isinstance(proposal, dict) or proposal.get("op") not in PREVIEW_OPS:
            raise OperationError("unsupported_preview", "This operation has no geometry preview")
        op = proposal["op"]
        # IDs belong to the final acceptance, not to an ephemeral proposal.
        permitted = self.controller.ARGS[op] - {"id", "source_feature_id", "source_feature_name"}
        if set(proposal) - permitted - {"op"}:
            raise OperationError("invalid_argument", "Unknown extrusion preview argument")
        normalized = dict(proposal)
        if op not in {"pad", "pocket"}:
            # Native/typed controller validation owns these operation schemas.
            # Normalize unit fields so focus-out retains equivalent intent.
            for key in ("length", "distance", "spacing", "radius", "size", "thickness"):
                if key in normalized:
                    normalized[key] = number(normalized[key], key.capitalize(), not (op == "move_face" and key == "distance"))
            if "offset" in normalized:
                normalized["offset"] = number(normalized["offset"], "Offset")
            if "angle" in normalized:
                normalized["angle"] = number(normalized["angle"], "Angle", True, "rad")
            if isinstance(normalized.get("rotation"), dict):
                normalized["rotation"] = dict(normalized["rotation"])
                normalized["rotation"]["angle"] = number(normalized["rotation"].get("angle", 0), "Rotation", unit="rad")
            return normalized
        if not isinstance(normalized.get("profile"), str):
            raise OperationError("missing_reference", "Select a closed sketch profile")
        if "reversed" in normalized and not isinstance(normalized["reversed"], bool):
            raise OperationError("invalid_argument", "reversed must be boolean")
        if op == "pocket":
            if "through_all" in normalized and not isinstance(normalized["through_all"], bool):
                raise OperationError("invalid_argument", "through_all must be boolean")
            normalized["through_all"] = normalized.get("through_all", True)
        if normalized.get("end_type") in {"up_to_face", "through_all"}:
            normalized.pop("length", None)
        elif op == "pad" or not normalized["through_all"]:
            normalized["length"] = number(normalized.get("length"), "Depth", True)
        else:
            # Depth is irrelevant for Through all. Strip invalid/stale text so
            # this mode evaluates exactly like the controller operation.
            normalized.pop("length", None)
        if solve:
            profile = self.controller._profile(self.document, normalized["profile"])
        else:
            # UI normalization must not solve a sketch per keystroke. The
            # exact worker and accepted native operation retain that check.
            profile = self.document.getObject(normalized["profile"])
            if profile is None or profile.TypeId != "Sketcher::SketchObject":
                raise OperationError("missing_reference", "Select a closed sketch profile")
        body = self.controller._body(self.document, normalized, profile)
        normalized["body"] = body.Name
        return normalized

    def evaluate(self, proposal):
        began = time.perf_counter()
        phases = {"snapshot": 0.0}
        normalized = dict(proposal) if isinstance(proposal, dict) else {}
        clone, clone_name = None, None
        active = App.activeDocument()
        gui_state = None
        previous_busy = None
        transaction_id = None
        try:
            with _preview_phase(phases, "guard"):
                self._guard()
            with _preview_phase(phases, "normalize"):
                normalized = self._proposal(proposal)
            # Native loading/recompute can pump Qt events with the hidden
            # clone temporarily active. Keep queued controller operations and
            # the panel's document watcher out of that disposable interval.
            previous_busy = self.controller.busy
            self.controller.busy = True
            gui_state = _capture_gui(self.document)
            generation = self.controller.observer.state(self.document)["generation"]
            if self._borrowed_snapshot is not None:
                self._borrowed_snapshot.validate(self.controller, self.document, self.expected_revision)
            elif self._snapshot is None or generation != self._generation:
                with _preview_phase(phases, "snapshot"):
                    self._cache.clear()
                    if self._temporary:
                        self._temporary.cleanup()
                    self._temporary = tempfile.TemporaryDirectory(prefix="kurtshape-extrusion-preview-")
                    self._snapshot = Path(self._temporary.name) / "extrusion-source.FCStd"
                    self.snapshot_captures += 1
                    self.document.saveCopy(str(self._snapshot))
                    self._generation = generation
            key = json.dumps(normalized, sort_keys=True, allow_nan=False)
            if key in self._cache:
                cached = self._cache.pop(key)
                self._cache[key] = cached
                return replace(cached, cached=True, milliseconds=(time.perf_counter() - began) * 1000,
                               phase_milliseconds=phases)

            names_before = set(App.listDocuments())
            try:
                with _preview_phase(phases, "load"):
                    clone = _load_preview_clone(self._snapshot, self._borrowed_snapshot is not None)
            except Exception:
                # The native loader can leave a document alive after failure.
                for name in set(App.listDocuments()) - names_before:
                    App.closeDocument(name)
                raise
            if clone.Name in names_before:
                raise OperationError("invalid_preview_clone", "Native preview loading reused an open document")
            clone_name = clone.Name
            with _preview_phase(phases, "clone_normalize"):
                _normalize_preview_source(self.controller, clone)
            if self._borrowed_snapshot is not None:
                self._borrowed_snapshot.validate(self.controller, self.document, self.expected_revision)
            App.setActiveDocument(clone_name)
            body = clone.getObject(normalized.get("body", ""))
            aggregate = "operation" in normalized or normalized["op"] not in {"pad", "pocket"}
            with _preview_phase(phases, "material"):
                previous = _aggregate_shape(clone) if aggregate else _world_shape(body)
            operation = dict(normalized, id="KurtShapePreviewExtrusion")
            index = 2
            while clone.getObject(operation["id"]):
                operation["id"] = "KurtShapePreviewExtrusion" + str(index)
                index += 1
            self.evaluations += 1
            # The same whitelisted native operation and validation used by
            # acceptance run here; the clone is never Controller.attach'ed.
            clone.openTransaction("Disposable feature preview")
            transaction_id = (App.getActiveTransaction() or (None, None))[1]
            with _preview_phase(phases, "model"):
                created = self.controller._model_operation(clone, operation)
            if isinstance(created, str):
                created = clone.getObject(created)
            from . import studio
            with _preview_phase(phases, "reconcile"):
                studio.reconcile(clone)
            with _preview_phase(phases, "recompute"):
                self.controller._recompute(clone)
            with _preview_phase(phases, "validation"):
                errors = self.controller._build_status(clone)
            acceptable_status = {"valid", "sketch_only"} if normalized["op"] == "create_plane" else {"valid"}
            if errors or self.controller._meta(clone).BuildStatus not in acceptable_status or not aggregate and len(body.Shape.Solids) != 1:
                raise OperationError("build_failed", "Preview could not produce valid current parts", features=errors)
            with _preview_phase(phases, "material"):
                shape = _aggregate_shape(clone) if aggregate else _world_shape(body)
            if normalized["op"] == "create_plane":
                material = Part.makePlane(50, 50, App.Vector(-25, -25, 0))
                material.Placement = created.getGlobalPlacement()
                if shape.isNull():
                    shape = material.copy()
            else:
                with _preview_phase(phases, "material"):
                    material = (previous.cut(shape) if _removal(normalized) else
                                shape if previous.isNull() else shape.cut(previous))
            if normalized["op"] != "create_plane" and (material.isNull() or geometry.scalar(material, "volume") <= 1e-7):
                # Split, fillet and a New part overlapping an existing part
                # can preserve the occupied volume while changing valid intent.
                # Show the resulting feature geometry in that case.
                if aggregate and created is not None and hasattr(created, "Shape") and not created.Shape.isNull():
                    material = _world_shape(created)
            if material.isNull() or normalized["op"] != "create_plane" and (not material.Solids or geometry.scalar(material, "volume") <= 1e-7):
                raise OperationError("empty_preview", "The extrusion changes no solid material")
            if self._borrowed_snapshot is not None:
                self._borrowed_snapshot.validate(self.controller, self.document, self.expected_revision)
            clone.commitTransaction()
            if transaction_id is not None and (App.getActiveTransaction() or (None, None))[1] == transaction_id:
                App.closeActiveTransaction()
            transaction_id = None
            result = ExtrusionResult(True, self.expected_revision, normalized, body.Name if body else None,
                                     shape, material, geometry.measurement_dict({"solid_count": len(shape.Solids),
                                                                               "volume": geometry.scalar(shape, "volume"),
                                                                                "bbox": geometry.bounding_box(shape)}),
                                     phase_milliseconds=phases)
            self._cache[key] = result
            while len(self._cache) > 8:
                self._cache.popitem(last=False)
            return replace(result, milliseconds=(time.perf_counter() - began) * 1000)
        except Exception as exc:
            return ExtrusionResult(False, self.expected_revision, normalized,
                                   error={"code": getattr(exc, "code", "preview_failed"), "message": str(exc),
                                          **getattr(exc, "details", {})},
                                   milliseconds=(time.perf_counter() - began) * 1000,
                                   phase_milliseconds=phases)
        finally:
            cleanup_began = time.perf_counter()
            try:
                if transaction_id is not None and (App.getActiveTransaction() or (None, None))[1] == transaction_id:
                    App.closeActiveTransaction(True)
                if clone_name:
                    if clone_name in App.listDocuments():
                        App.closeDocument(clone_name)
                    self.controller.geometry.drop_document(clone_name)
                    self.controller.observer.states.pop(clone_name, None)
                if active and self.controller._is_open(active):
                    App.setActiveDocument(active.Name)
                if self.controller._is_open(self.document):
                    _restore_gui(self.document, gui_state)
            finally:
                if previous_busy is not None:
                    self.controller.busy = previous_busy
                phases["cleanup"] = (time.perf_counter() - cleanup_began) * 1000
                for name, milliseconds in phases.items():
                    self.controller.timings.record("preview_phase_" + name, milliseconds)

    def close(self):
        self.closed = True
        self._cache.clear()
        if self._temporary:
            self._temporary.cleanup()
            self._temporary = None
        self._snapshot = None
        self._borrowed_snapshot = None


class CoinExtrusionOverlay:
    """Actual native BRep tessellation; no selectable document/ViewProvider."""
    def __init__(self):
        self.scene = self.node = None
        self.mesh_key = self.transform_node = None

    def _transform(self, result):
        from pivy import coin
        spec = result.transform
        if spec:
            self.transform_node.center.setValue(*spec["origin"])
            self.transform_node.scaleOrientation.setValue(coin.SbRotation(coin.SbVec3f(0, 0, 1), coin.SbVec3f(*spec["direction"])))
            self.transform_node.scaleFactor.setValue(1, 1, spec["depth"])

    def show(self, result, view):
        from pivy import coin
        if result.mesh_key and result.mesh_key == self.mesh_key and self.node is not None and self.scene == view.getSceneGraph():
            self._transform(result)
            view.redraw()
            return
        self.clear()
        if not result.valid and not result.provisional:
            return
        mesh = result.mesh if result.mesh is not None else render_mesh(result.material_shape, result.shape)
        vertices, triangles = mesh["vertices"], mesh["triangles"]
        node = coin.SoSeparator()
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        node.addChild(pick)
        if _removal(result.proposal):
            depth = coin.SoDepthBuffer()
            # The live solid stays visible. Draw removed material through it
            # without writing depth that could occlude other scene objects.
            # "write" collides with SoNode.write in the Pivy Python binding.
            depth.getField("test").setValue(False)
            depth.getField("write").setValue(False)
            depth.getField("function").setValue(coin.SoDepthBuffer.ALWAYS)
            node.addChild(depth)
        self.transform_node = coin.SoTransform()
        node.addChild(self.transform_node)
        self._transform(result)
        hints = coin.SoShapeHints()
        hints.vertexOrdering = coin.SoShapeHints.COUNTERCLOCKWISE
        hints.shapeType = coin.SoShapeHints.SOLID
        node.addChild(hints)
        material = coin.SoMaterial()
        color = (0.96, 0.48, 0.20) if _removal(result.proposal) else (0.25, 0.72, 0.96)
        material.diffuseColor.setValue(*color)
        material.emissiveColor.setValue(*(channel * 0.25 for channel in color))
        material.transparency = 0.72 if result.provisional else 0.38
        node.addChild(material)
        coordinates = coin.SoCoordinate3()
        coordinates.point.setValues(0, len(vertices), vertices)
        node.addChild(coordinates)
        faces = coin.SoIndexedFaceSet()
        indices = [value for triangle in triangles for value in (*triangle, -1)]
        faces.coordIndex.setValues(0, len(indices), indices)
        node.addChild(faces)
        # An outline of the resulting Body makes blind/through cuts readable
        # while preserving the original Body's visibility and selection.
        lines = coin.SoSeparator()
        line_material = coin.SoMaterial()
        line_material.diffuseColor.setValue(*color)
        line_material.emissiveColor.setValue(*color)
        lines.addChild(line_material)
        style = coin.SoDrawStyle()
        style.lineWidth = 2
        lines.addChild(style)
        points, segments = mesh["lines"], mesh["segments"]
        line_coordinates = coin.SoCoordinate3()
        line_coordinates.point.setValues(0, len(points), points)
        lines.addChild(line_coordinates)
        line_set = coin.SoLineSet()
        line_set.numVertices.setValues(0, len(segments), segments)
        lines.addChild(line_set)
        node.addChild(lines)
        self.scene = view.getSceneGraph()
        self.node = node
        self.mesh_key = result.mesh_key
        self.scene.addChild(node)
        view.redraw()

    def clear(self):
        if self.scene is not None and self.node is not None:
            try:
                if self.scene.findChild(self.node) >= 0:
                    self.scene.removeChild(self.node)
            except (RuntimeError, ReferenceError):
                pass  # The native view was already destroyed.
        self.scene = self.node = None
        self.mesh_key = self.transform_node = None


class DebouncedExtrusionPreview:
    """Immediate provisional display and latest-wins exact process evaluation.

    Every method runs on Qt's thread. The worker receives an immutable FCStd
    snapshot and JSON proposals, and returns only JSON display/measurement data.
    flush/current_result never wait: only a matching exact verdict can commit.
    """
    def __init__(self, controller, parent=None, status=None, allowed=None, delay_ms=160):
        from PySide import QtCore
        self.controller = controller
        self.status = status
        self.allowed = allowed
        self.evaluator = None
        self.overlay = CoinExtrusionOverlay()
        self.pending = self.result = None
        self.normalized = None
        self.provisional = self.worker = None
        self.snapshotting = None
        self.normalizing = 0
        self.sequence = 0
        self.source_generation = None
        self.source_key = None
        self.snapshot_captures = self.snapshot_reuses = 0
        self.ready_sequence = None
        self.submitted = None
        self.exact_cache = OrderedDict()
        self.closed = False
        self.evaluating = False
        self.delay_ms = delay_ms
        self.timer = QtCore.QTimer(parent)
        self.timer.setSingleShot(True)
        self.timer.setInterval(delay_ms)
        self.timer.timeout.connect(self._start_exact)
        self.poll_timer = QtCore.QTimer(parent)
        self.poll_timer.setInterval(20)
        self.poll_timer.timeout.connect(self._poll)
        self.lifetime_timer = QtCore.QTimer(parent)
        self.lifetime_timer.setInterval(200)
        self.lifetime_timer.timeout.connect(self.check_lifetime)
        self.lifetime_timer.start()
        if parent is not None:
            parent.destroyed.connect(self.close)

    def begin(self, document, expected_revision):
        self.clear()
        if not self.closed:
            self.evaluator = ExtrusionEvaluator(self.controller, document, expected_revision)
            self.provisional = ProvisionalExtrusion(self.evaluator)

    @staticmethod
    def _key(proposal):
        return json.dumps(proposal, sort_keys=True, allow_nan=False)

    def _failure(self, exc):
        return ExtrusionResult(False, self.evaluator.expected_revision if self.evaluator else "",
                               self.normalized or self.pending or {},
                               error={"code": getattr(exc, "code", "preview_failed"), "message": str(exc)})

    def _sync_generation(self):
        """Reject all accepted-state changes, including equal-revision serials."""
        evaluator = self.evaluator
        generation = self.controller.observer.state(evaluator.document)["generation"]
        key = self.controller.snapshot_key(evaluator.document)
        if self.evaluator is not evaluator:
            return False
        if self.source_generation is None:
            self.source_generation = generation
            self.source_key = key
        elif generation != self.source_generation or key != self.source_key:
            if self.worker:
                self.worker.close()
            self.worker = None
            self.poll_timer.stop()
            self.evaluating = False
            self.exact_cache.clear()
            self.provisional.meshes.clear()
            self.normalized = self.result = self.submitted = self.ready_sequence = None
            self.overlay.clear()
            self.sequence += 1
            self.source_generation = generation
            self.source_key = key
            return False
        return True

    def _display(self, result):
        import FreeCADGui as Gui
        began = time.perf_counter()
        if result is not None and (result.valid or result.provisional):
            try:
                self.overlay.show(result, Gui.getDocument(self.evaluator.document_name).activeView())
            except Exception as exc:
                result = self._failure(exc)
                self.overlay.clear()
        else:
            self.overlay.clear()
        self.controller.timings.record("preview_overlay", (time.perf_counter() - began) * 1000)
        self.result = result
        if self.status:
            self.status(result)
        return result

    def schedule(self, proposal):
        if self.closed or self.evaluator is None:
            return
        self.pending = dict(proposal)
        if self.snapshotting is not None:
            # saveCopy can pump Qt input. Keep only the latest fields and
            # normalize them after the native snapshot releases the document.
            self.sequence += 1
            self.normalized = self.result = None
            self.overlay.clear()
            if self.status:
                self.status(None)
            return
        if not self.check_lifetime():
            return
        evaluator = self.evaluator
        self.normalizing += 1
        try:
            evaluator._guard()
            if self.evaluator is not evaluator:
                return
            self._sync_generation()
            normalized = evaluator._proposal(self.pending, solve=False)
        except Exception as exc:
            if self.evaluator is not evaluator:
                return
            self.sequence += 1
            self.normalized = None
            self.timer.stop()
            self._display(self._failure(exc))
            return
        finally:
            self.normalizing -= 1
        if self.evaluator is not evaluator:
            return
        if normalized == self.normalized and (self.result is not None and (self.result.valid or self.result.provisional)
                                              or self.evaluating or self.timer.isActive()):
            if self.status:
                self.status(self.result)
            return
        self.sequence += 1
        self.normalized = normalized
        key = self._key(normalized)
        if key in self.exact_cache:
            self.timer.stop()
            result = self.exact_cache.pop(key)
            self.exact_cache[key] = result
            self._display(result)
            return
        began = time.perf_counter()
        try:
            provisional = self.provisional.evaluate(normalized)
        except Exception:
            # Some native profile types cannot make a cheap mesh. Exact
            # evaluation still owns acceptance and its actionable error.
            provisional = None
        self.controller.timings.record("preview_provisional", (time.perf_counter() - began) * 1000)
        self._display(provisional)
        # Always return to Qt before snapshotting; its first provisional frame
        # can paint before saveCopy's unavoidable native serialization cost.
        self.timer.start(self.delay_ms)

    def flush(self):
        result = self.current_result(self.pending)
        if result is None and self.normalized is not None and not self.closed:
            self.timer.start(0)
        return result

    def current_result(self, proposal=None):
        if self.normalizing or self.snapshotting is not None:
            return None
        if not self.check_lifetime() or self.result is None or not self.result.valid:
            return None
        evaluator = self.evaluator
        try:
            evaluator._guard()
            if self.evaluator is not evaluator or not self.check_lifetime():
                return None
            if not self._sync_generation():
                self.schedule(proposal or self.pending)
                return None
            normalized = evaluator._proposal(proposal or self.pending, solve=False)
            if self.evaluator is not evaluator or not self.check_lifetime():
                return None
            return self.result if normalized == self.result.proposal else None
        except Exception as exc:
            if self.evaluator is evaluator and not self.closed:
                self._display(self._failure(exc))
            return None

    def _start_exact(self):
        if self.snapshotting is not None:
            return
        if self.normalizing:
            # A native guard may pump Qt while schedule has newer raw fields
            # but has not yet published their normalized proposal/sequence.
            self.timer.start(self.delay_ms)
            return
        if not self.check_lifetime() or self.normalized is None:
            return
        self.ready_sequence = self.sequence
        if self.evaluating:
            return
        evaluator = self.evaluator
        if self.current_result(self.pending) is not None:
            return
        if self.evaluator is not evaluator:
            return
        try:
            evaluator._guard()
            if self.evaluator is not evaluator or not self.check_lifetime():
                return
            if not self._sync_generation():
                self.schedule(self.pending)
                return
            if self.worker is None:
                from .preview_worker import NativePreviewWorker
                executable = Path(App.getHomePath()) / "bin" / ("python.exe" if os.name == "nt" else "python")
                # Native FCStd extraction creates additional filenames. Keep
                # task roots shallow even when the current session path is long.
                parent = Path(__file__).resolve().parents[2] / "runtime"
                self.worker = NativePreviewWorker(executable, parent)
                worker = self.worker
                began = time.perf_counter()
                previous_busy = self.controller.busy
                self.controller.busy = True
                self.snapshotting = worker
                lease = None
                try:
                    key = self.controller.snapshot_key(evaluator.document)
                    try:
                        lease = self.controller.snapshots.try_acquire(key)
                    except OSError:
                        # Sharing is optional; durable recovery remains intact.
                        lease = None
                    if self.evaluator is evaluator and self.worker is worker:
                        if lease is not None:
                            if lease.key != key or self.controller.snapshot_key(evaluator.document) != key:
                                raise RuntimeError("Accepted preview state changed during snapshot acquisition")
                            worker.borrow_snapshot(lease)
                            lease = None  # Worker now pins it through confirmed exit.
                            self.snapshot_reuses += 1
                        else:
                            self.snapshot_captures += 1
                            evaluator.document.saveCopy(str(worker.snapshot))
                finally:
                    if lease is not None:
                        lease.release()
                    self.controller.busy = previous_busy
                    self.snapshotting = None
                    # saveCopy alone does not open another GUI document or
                    # reset its Modified flag. Never undo camera/selection
                    # input that Qt may deliver while native serialization runs.
                    if self.evaluator is not evaluator or self.worker is not worker or not self.controller._is_open(evaluator.document):
                        worker.close()
                    self.controller.timings.record("preview_snapshot_gui", (time.perf_counter() - began) * 1000)
                if self.evaluator is not evaluator or self.worker is not worker:
                    if self.evaluator is not None and self.pending is not None:
                        self.schedule(self.pending)
                    return
                if self.normalized is None:
                    self.schedule(self.pending)
                    return
                evaluator._guard()
                if self.evaluator is not evaluator or self.worker is not worker or not self.check_lifetime():
                    return
                if not self._sync_generation():
                    self.schedule(self.pending)
                    return
            self.submitted = (self.sequence, dict(self.normalized), self.source_generation)
            self.worker.submit(*self.submitted[:2])
            self.evaluator._generation = self.controller.observer.state(self.evaluator.document)["generation"]
            self.evaluating = True
            self.poll_timer.start()
        except Exception as exc:
            if self.evaluator is not evaluator:
                return
            self.evaluating = False
            if self.worker:
                self.worker.close()
                self.worker = None
            self._display(self._failure(exc))

    def _poll(self):
        if self.normalizing or self.snapshotting is not None:
            return
        if not self.check_lifetime() or self.worker is None:
            self.poll_timer.stop()
            return
        evaluator, worker = self.evaluator, self.worker
        began = time.perf_counter()
        try:
            evaluator._guard()
            if self.evaluator is not evaluator or self.worker is not worker or not self.check_lifetime():
                return
            if not self._sync_generation():
                self.schedule(self.pending)
                return
            response = worker.poll()
            if response is None:
                return
            self.poll_timer.stop()
            self.evaluating = False
            self.controller.timings.record("preview_ipc", (time.perf_counter() - began) * 1000)
            self.controller.timings.record("preview_worker_exact", response["milliseconds"])
            evaluator.evaluations += response["evaluation_delta"]
            evaluator._guard()
            if self.evaluator is not evaluator or self.worker is not worker or not self.check_lifetime():
                return
            if not self._sync_generation():
                self.schedule(self.pending)
                return
            sequence, proposal, generation = self.submitted
            if response["sequence"] != sequence:
                raise RuntimeError("Exact preview sequence changed")
            if generation != self.source_generation:
                raise RuntimeError("Exact preview geometry generation changed")
            phases = dict(response.get("phase_milliseconds") or {})
            for name, milliseconds in phases.items():
                self.controller.timings.record("preview_worker_phase_" + name, milliseconds)
            result = ExtrusionResult(response["valid"], self.evaluator.expected_revision, proposal,
                                     body_id=response.get("body_id"), measurements=response.get("measurements"),
                                     error=response.get("error"), cached=response.get("cached", False),
                                     milliseconds=response["milliseconds"], mesh=response.get("mesh"),
                                     mesh_key="exact:" + self._key(proposal), phase_milliseconds=phases)
            if result.valid:
                self.exact_cache[self._key(proposal)] = result
                while len(self.exact_cache) > 8:
                    self.exact_cache.popitem(last=False)
            if sequence == self.sequence and proposal == self.normalized:
                self._display(result)
            elif self.ready_sequence == self.sequence:
                self.timer.start(0)
        except Exception as exc:
            if self.evaluator is not evaluator or self.worker is not worker or self.closed:
                return
            self.poll_timer.stop()
            self.evaluating = False
            if self.worker:
                self.worker.close()
                self.worker = None
            self._display(self._failure(exc))

    def check_lifetime(self):
        if self.closed or self.evaluator is None:
            return False
        doc = self.evaluator.document
        if (not self.controller._is_open(doc) or App.activeDocument() != doc or
                self.allowed is not None and not self.allowed() or
                getattr(App, "GuiUp", False) and self.controller._native_edit_active()):
            self.clear()
            return False
        if self.controller._meta(doc).Revision != self.evaluator.expected_revision:
            self.clear()
            return False
        return True

    def clear(self):
        self.timer.stop()
        self.poll_timer.stop()
        self.overlay.clear()
        if self.worker and self.worker is not self.snapshotting:
            self.worker.close()
        self.worker = None
        self.evaluating = False
        if self.evaluator:
            self.evaluator.close()
        self.evaluator = self.pending = self.result = None
        self.normalized = self.provisional = self.submitted = self.ready_sequence = None
        self.source_generation = None
        self.source_key = None
        self.exact_cache.clear()
        self.sequence += 1
        if self.status:
            self.status(None)

    def close(self, *args):
        if self.closed:
            return
        self.clear()
        self.closed = True
        self.lifetime_timer.stop()
