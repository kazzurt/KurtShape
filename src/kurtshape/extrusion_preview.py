"""Disposable native extrusion evaluation and a non-pickable viewport overlay.

Only the accepted controller operation changes the project. Preview evaluates
the same Pad/Pocket operation in a hidden, temporary native FCStd, then keeps
detached BRep shapes. No preview objects enter the authoritative document.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
import json
from pathlib import Path
import tempfile
import time

import FreeCAD as App
import Part

from .core import OperationError, measurements, number


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
    def __init__(self, controller, document, expected_revision):
        self.controller = controller
        self.document = document
        self.document_name = document.Name
        self.expected_revision = expected_revision
        self._temporary = None
        self._snapshot = None
        self._generation = None
        self._cache = OrderedDict()
        self.closed = False
        self.evaluations = 0

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

    def _proposal(self, proposal):
        if not isinstance(proposal, dict) or proposal.get("op") not in {"pad", "pocket"}:
            raise OperationError("unsupported_preview", "Preview requires an extrusion or remove operation")
        op = proposal["op"]
        # IDs belong to the final acceptance, not to an ephemeral proposal.
        permitted = self.controller.ARGS[op] - {"id", "source_feature_id", "source_feature_name"}
        if set(proposal) - permitted - {"op"}:
            raise OperationError("invalid_argument", "Unknown extrusion preview argument")
        normalized = dict(proposal)
        if not isinstance(normalized.get("profile"), str):
            raise OperationError("missing_reference", "Select a closed sketch profile")
        if "reversed" in normalized and not isinstance(normalized["reversed"], bool):
            raise OperationError("invalid_argument", "reversed must be boolean")
        if op == "pocket":
            if "through_all" in normalized and not isinstance(normalized["through_all"], bool):
                raise OperationError("invalid_argument", "through_all must be boolean")
            normalized["through_all"] = normalized.get("through_all", True)
        if op == "pad" or not normalized["through_all"]:
            normalized["length"] = number(normalized.get("length"), "Depth", True)
        else:
            # Depth is irrelevant for Through all. Strip invalid/stale text so
            # this mode evaluates exactly like the controller operation.
            normalized.pop("length", None)
        profile = self.controller._profile(self.document, normalized["profile"])
        body = self.controller._body(self.document, normalized, profile)
        normalized["body"] = body.Name
        return normalized

    def evaluate(self, proposal):
        began = time.perf_counter()
        normalized = dict(proposal) if isinstance(proposal, dict) else {}
        clone, clone_name = None, None
        active = App.activeDocument()
        gui_state = None
        try:
            self._guard()
            normalized = self._proposal(proposal)
            gui_state = _capture_gui(self.document)
            generation = self.controller.observer.state(self.document)["generation"]
            if self._snapshot is None or generation != self._generation:
                self._cache.clear()
                if self._temporary:
                    self._temporary.cleanup()
                self._temporary = tempfile.TemporaryDirectory(prefix="kurtshape-extrusion-preview-")
                self._snapshot = Path(self._temporary.name) / "extrusion-source.FCStd"
                self.document.saveCopy(str(self._snapshot))
                self._generation = generation
            key = json.dumps(normalized, sort_keys=True, allow_nan=False)
            if key in self._cache:
                cached = self._cache.pop(key)
                self._cache[key] = cached
                return replace(cached, cached=True, milliseconds=(time.perf_counter() - began) * 1000)

            names_before = set(App.listDocuments())
            try:
                clone = App.openDocument(str(self._snapshot), True, True)
            except Exception:
                # The native loader can leave a document alive after failure.
                for name in set(App.listDocuments()) - names_before:
                    App.closeDocument(name)
                raise
            clone_name = clone.Name
            body = clone.getObject(normalized["body"])
            previous = _world_shape(body)
            operation = dict(normalized, id="KurtShapePreviewExtrusion")
            index = 2
            while clone.getObject(operation["id"]):
                operation["id"] = "KurtShapePreviewExtrusion" + str(index)
                index += 1
            self.evaluations += 1
            # The same whitelisted native operation and validation used by
            # acceptance run here; the clone is never Controller.attach'ed.
            self.controller._model_operation(clone, operation)
            self.controller._recompute(clone)
            errors = self.controller._build_status(clone)
            if errors or self.controller._meta(clone).BuildStatus != "valid" or len(body.Shape.Solids) != 1:
                raise OperationError("build_failed", "Preview could not produce one valid solid", features=errors)
            shape = _world_shape(body)
            material = (previous.cut(shape) if normalized["op"] == "pocket" else
                        shape if previous.isNull() else shape.cut(previous))
            if material.isNull() or not material.isValid() or material.Volume <= 1e-7:
                raise OperationError("empty_preview", "The extrusion changes no solid material")
            result = ExtrusionResult(True, self.expected_revision, normalized, body.Name,
                                     shape, material, measurements(shape))
            self._cache[key] = result
            while len(self._cache) > 8:
                self._cache.popitem(last=False)
            return replace(result, milliseconds=(time.perf_counter() - began) * 1000)
        except Exception as exc:
            return ExtrusionResult(False, self.expected_revision, normalized,
                                   error={"code": getattr(exc, "code", "preview_failed"), "message": str(exc)},
                                   milliseconds=(time.perf_counter() - began) * 1000)
        finally:
            if clone_name:
                if clone_name in App.listDocuments():
                    App.closeDocument(clone_name)
                self.controller.evaluations.pop(clone_name, None)
                self.controller.observer.states.pop(clone_name, None)
            if active and self.controller._is_open(active):
                App.setActiveDocument(active.Name)
            if self.controller._is_open(self.document):
                _restore_gui(self.document, gui_state)

    def close(self):
        self.closed = True
        self._cache.clear()
        if self._temporary:
            self._temporary.cleanup()
            self._temporary = None
        self._snapshot = None


class CoinExtrusionOverlay:
    """Actual native BRep tessellation; no selectable document/ViewProvider."""
    def __init__(self):
        self.scene = self.node = None

    def show(self, result, view):
        from pivy import coin
        self.clear()
        if not result.valid:
            return
        vertices, triangles = result.material_shape.tessellate(0.15)
        if not triangles:
            raise OperationError("empty_preview", "The extrusion has no displayable faces")
        node = coin.SoSeparator()
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        node.addChild(pick)
        if result.proposal["op"] == "pocket":
            depth = coin.SoDepthBuffer()
            # The live solid stays visible. Draw removed material through it
            # without writing depth that could occlude other scene objects.
            # "write" collides with SoNode.write in the Pivy Python binding.
            depth.getField("test").setValue(False)
            depth.getField("write").setValue(False)
            depth.getField("function").setValue(coin.SoDepthBuffer.ALWAYS)
            node.addChild(depth)
        hints = coin.SoShapeHints()
        hints.vertexOrdering = coin.SoShapeHints.COUNTERCLOCKWISE
        hints.shapeType = coin.SoShapeHints.SOLID
        node.addChild(hints)
        material = coin.SoMaterial()
        color = (0.96, 0.48, 0.20) if result.proposal["op"] == "pocket" else (0.25, 0.72, 0.96)
        material.diffuseColor.setValue(*color)
        material.emissiveColor.setValue(*(channel * 0.25 for channel in color))
        material.transparency = 0.38
        node.addChild(material)
        coordinates = coin.SoCoordinate3()
        coordinates.point.setValues(0, len(vertices), [(v.x, v.y, v.z) for v in vertices])
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
        points, segments = [], []
        for edge in result.shape.Edges:
            samples = edge.discretize(Deflection=0.15)
            if len(samples) > 1:
                points.extend((p.x, p.y, p.z) for p in samples)
                segments.append(len(samples))
        line_coordinates = coin.SoCoordinate3()
        line_coordinates.point.setValues(0, len(points), points)
        lines.addChild(line_coordinates)
        line_set = coin.SoLineSet()
        line_set.numVertices.setValues(0, len(segments), segments)
        lines.addChild(line_set)
        node.addChild(lines)
        self.scene = view.getSceneGraph()
        self.node = node
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


class DebouncedExtrusionPreview:
    """UI adapter. begin, schedule, clear and close run on the GUI thread.

    A status callback receives ExtrusionResult (or None on clear). An optional
    allowed callback checks that the owning custom editor is still displayed.
    clear must be called on acceptance, cancellation, profile/task switches,
    and before entering a sketch/native feature editor. A cheap lifetime timer
    also clears automatically after document/view activation or closure.
    """
    def __init__(self, controller, parent=None, status=None, allowed=None, delay_ms=160):
        from PySide import QtCore
        self.controller = controller
        self.status = status
        self.allowed = allowed
        self.evaluator = None
        self.overlay = CoinExtrusionOverlay()
        self.pending = self.result = None
        self.closed = False
        self.timer = QtCore.QTimer(parent)
        self.timer.setSingleShot(True)
        self.timer.setInterval(delay_ms)
        self.timer.timeout.connect(self.flush)
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

    def schedule(self, proposal):
        if self.closed or self.evaluator is None:
            return
        self.pending = dict(proposal)
        if not self.check_lifetime():
            return
        if self.result is not None and self.result.valid:
            try:
                self.evaluator._guard()
                normalized = self.evaluator._proposal(self.pending)
                if (normalized == self.result.proposal and self.evaluator._generation ==
                        self.controller.observer.state(self.evaluator.document)["generation"]):
                    # QuantitySpinBox normalizes e.g. "7 mm" to "7.00 mm"
                    # on focus-out. Preserve the valid ghost and re-enable
                    # Confirm synchronously so its mouse release can click.
                    self.timer.stop()
                    if self.status:
                        self.status(self.result)
                    return
            except Exception:
                # Invalid input or stale source must still discard the old
                # result and be reported by the usual guarded evaluation.
                pass
        # A previous valid ghost must not represent newly invalid editor text.
        self.overlay.clear()
        self.result = None
        self.timer.start()

    def flush(self):
        import FreeCADGui as Gui
        self.timer.stop()
        if self.closed or self.evaluator is None or self.pending is None:
            return None
        if not self.check_lifetime():
            return None
        result = self.evaluator.evaluate(self.pending)
        self.result = result
        self.overlay.clear()
        if result.valid:
            try:
                self.overlay.show(result, Gui.getDocument(self.evaluator.document_name).activeView())
            except Exception as exc:
                result = replace(result, valid=False, error={"code": "preview_render_failed", "message": str(exc)})
                self.result = result
                self.overlay.clear()
        if self.status:
            self.status(result)
        return result

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
        self.overlay.clear()
        if self.evaluator:
            self.evaluator.close()
        self.evaluator = self.pending = self.result = None
        if self.status:
            self.status(None)

    def close(self, *args):
        if self.closed:
            return
        self.clear()
        self.closed = True
        self.lifetime_timer.stop()
