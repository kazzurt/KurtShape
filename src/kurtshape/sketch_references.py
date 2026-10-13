"""Viewport picking and native sketch selections for associated model edges."""
from __future__ import annotations

import re
import math

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui

from . import sketch_tools
from .tool_session import ToolSession


class SketchReferences:
    def __init__(self, panel):
        self.panel = panel
        self.tools = ToolSession()
        self._changing_tool = self._syncing_context = False
        self._last_context = None
        self._native_presentation_suspended = False
        self.suppress_release = None
        self.dimension_refs = []
        self.dimension_cursor = None
        self.dimension_cursor_widgets = {}
        self.dimension_cursor_pending = False
        self.hover_source = None
        self.hover_scene = None
        self.hover_node = None
        self.hover_event = 0
        self.hover_pending = None
        self.hover_timer = QtCore.QTimer(panel)
        self.hover_timer.setSingleShot(True)
        self.hover_timer.setInterval(16)
        self.hover_timer.timeout.connect(self.flush_hover)
        self.cursor_refresh_timer = QtCore.QTimer(panel)
        self.cursor_refresh_timer.setSingleShot(True)
        self.cursor_refresh_timer.timeout.connect(self.refresh_dimension_cursor)
        self.cursor_refresh_pending = None
        self.dimension_selection_timer = QtCore.QTimer(panel)
        self.dimension_selection_timer.setSingleShot(True)
        self.dimension_selection_timer.timeout.connect(self.flush_dimension_selection)
        self.dimension_selection_pending = None
        self.mdi = panel.main.findChild(QtGui.QMdiArea)
        self._view_changed = lambda *args: self.sync_context()
        if self.mdi:
            self.mdi.subWindowActivated.connect(self._view_changed)

    def _tool_value(self, kind):
        return self.tools.state.value if self.tools.state.kind == kind else None

    native_tool = property(lambda self: self._tool_value("native"),
                           lambda self, value: self._assign_tool("native", value))
    picking = property(lambda self: self._tool_value("reference"),
                       lambda self, value: self._assign_tool("reference", value))
    dimension_picking = property(lambda self: self._tool_value("dimension"),
                                 lambda self, value: self._assign_tool("dimension", value))

    def _context_stamp(self):
        from shiboken6 import isValid
        try:
            sketch = self.panel.active_sketch()
            window = self.mdi.activeSubWindow() if self.mdi and isValid(self.mdi) else None
            if sketch is not None and window is not None and isValid(window):
                return sketch.Document, sketch, window
        except (AttributeError, ReferenceError, RuntimeError):
            pass
        return None

    @staticmethod
    def _same_context(first, second):
        try:
            return first == second
        except (ReferenceError, RuntimeError):
            return False

    def _callback_stamp(self):
        return self.tools.generation, self._context_stamp()

    def _callback_current(self, stamp):
        if stamp is None or self._changing_tool or not self.tools.current(stamp[0]) or stamp[1] is None:
            return False
        context = self._context_stamp()
        # Reading native edit/view context can deliver a newer tool transition.
        return (not self._changing_tool and self.tools.current(stamp[0])
                and (not self.tools.active or self._same_context(self.tools.state.owner, stamp[1]))
                and self._same_context(stamp[1], context))

    def _viewport_window(self, watched):
        """Return the active window only for a live descendant viewport."""
        from shiboken6 import isValid
        try:
            if self.mdi is None or not isValid(self.mdi) or not isValid(watched):
                return None
            window = self.mdi.activeSubWindow()
            if window is not None and isValid(window) and window.isAncestorOf(watched):
                return window
        except (AttributeError, ReferenceError, RuntimeError):
            pass
        return None

    def _hover_current(self, stamp, serial, watched=None):
        try:
            if (serial != self.hover_event or not self._callback_current(stamp)
                    or self.native_tool or App.ActiveDocument != stamp[1][0]):
                return False
            if watched is not None and (self._viewport_window(watched) != stamp[1][2] or not watched.isVisible()):
                return False
            return serial == self.hover_event and self.tools.current(stamp[0]) and not self._changing_tool
        except (AttributeError, ReferenceError, RuntimeError):
            return False

    def _cancel_deferred(self):
        previous, self._changing_tool = self._changing_tool, True
        try:
            self.tools.invalidate_callbacks()
            self.cursor_refresh_timer.stop()
            self.dimension_selection_timer.stop()
            self.cursor_refresh_pending = self.dimension_selection_pending = None
            self.dimension_cursor_pending = False
            self.clear_hover()
            self.restore_dimension_cursor()
        finally:
            self._changing_tool = previous

    def _sync_tool_presentation(self):
        command = self.native_command_for_context()
        snapping = getattr(self.panel, "sketch_snapping", None)
        cursor = getattr(self.panel, "sketch_cursor", None)
        if snapping is not None:
            snapping.sync_tool(command)
        if cursor is not None:
            cursor.sync(command)

    def _assign_tool(self, kind, value):
        if self.tools.closed:
            return
        if value is None:
            if not self.tools.clear(kind):
                return
        else:
            owner = self._context_stamp()
            if owner is None:
                raise RuntimeError("No active sketch view for tool activation")
            self.tools.select(kind, value, owner)
        self._native_presentation_suspended = False
        self._last_context = self._context_stamp()
        self._cancel_deferred()
        self.dimension_refs = []
        self.suppress_release = None
        self._sync_tool_presentation()

    def _owner_edit_open(self):
        if self.tools.state.owner is None:
            return False
        document, sketch, window = self.tools.state.owner
        try:
            if App.getDocument(document.Name) != document or document.getObject(sketch.Name) != sketch:
                return False
            gui = Gui.getDocument(document.Name)
            edited = gui.getInEdit() if gui else None
            if edited is not None and hasattr(edited, "Object"):
                edited = edited.Object
            return edited == sketch
        except (AttributeError, ReferenceError, RuntimeError):
            return False

    def sync_context(self):
        if self.tools.closed or self._syncing_context or self._changing_tool:
            return
        self._syncing_context = True
        try:
            context = self._context_stamp()
            if self._same_context(context, self._last_context):
                return
            self._last_context = context
            state = self.tools.state
            if self.tools.active and not self._owner_edit_open():
                self.end_tool()
                return
            self._cancel_deferred()
            self.suppress_release = None
            if self.tools.state is not state:
                return
            if state.kind == "native":
                if not self._same_context(state.owner, context):
                    self._native_presentation_suspended = True
                elif self._native_presentation_suspended:
                    document, sketch, window = state.owner
                    self.panel.sketch_snapping.begin(sketch, window.devicePixelRatioF())
                    self.panel.sketch_snapping.before_native(state.value)
                    self._native_presentation_suspended = False
            self._sync_tool_presentation()
            if self._same_context(state.owner, context):
                self.show_dimension_cursor()
        finally:
            self._syncing_context = False

    def native_command_for_context(self):
        state = self.tools.state
        if state.kind == "native" and self._same_context(state.owner, self._context_stamp()):
            return state.value
        return None

    def end_tool(self, stop_native=False):
        active = self.tools.active
        if stop_native:
            Gui.runCommand("Sketcher_StopOperation")
        self.tools.clear()
        self._native_presentation_suspended = False
        self._cancel_deferred()
        self.dimension_refs = []
        self.suppress_release = None
        self._sync_tool_presentation()
        return active

    def close(self):
        if self.tools.closed:
            return
        self._cancel_deferred()
        self.dimension_refs = []
        self.suppress_release = None
        self.tools.close()
        if self.mdi:
            try:
                self.mdi.subWindowActivated.disconnect(self._view_changed)
            except RuntimeError:
                pass

    def show_dimension_cursor(self, widget=None):
        """Mark both reference picking and native dimension placement."""
        if not self.dimension_picking and self.native_tool != "Sketcher_Dimension":
            return
        if self.dimension_cursor is None:
            pixmap = QtGui.QPixmap(32, 32)
            pixmap.fill(QtCore.Qt.transparent)
            painter = QtGui.QPainter(pixmap)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            # A precise crosshair hotspot plus extension lines and a double
            # arrow remain legible over both shaded faces and a white canvas.
            lines = [(1, 6, 11, 6), (6, 1, 6, 11),
                     (13, 17, 13, 29), (29, 17, 29, 29), (13, 23, 29, 23),
                     (13, 23, 17, 20), (13, 23, 17, 26),
                     (29, 23, 25, 20), (29, 23, 25, 26)]
            for color, width in (("white", 3.5), ("black", 1.3)):
                painter.setPen(QtGui.QPen(QtGui.QColor(color), width))
                for line in lines:
                    painter.drawLine(*line)
            painter.end()
            self.dimension_cursor = QtGui.QCursor(pixmap, 6, 6)
        if widget is None:
            mdi = self.panel.main.findChild(QtGui.QMdiArea)
            surface = mdi.activeSubWindow() if mdi else None
            widgets = [child for child in surface.findChildren(QtGui.QWidget)
                       if child.metaObject().className() == "QOpenGLWidget" and child.isVisible()] if surface else []
        else:
            widgets = [widget]
        for target in widgets:
            if target not in self.dimension_cursor_widgets:
                self.dimension_cursor_widgets[target] = (target.testAttribute(QtCore.Qt.WA_SetCursor), target.cursor())
            if target.cursor().pixmap().cacheKey() != self.dimension_cursor.pixmap().cacheKey():
                target.setCursor(self.dimension_cursor)

    def refresh_dimension_cursor(self):
        stamp, self.cursor_refresh_pending = self.cursor_refresh_pending, None
        self.dimension_cursor_pending = False
        if self._callback_current(stamp):
            self.show_dimension_cursor()

    def queue_dimension_cursor(self):
        if self._changing_tool or self.tools.closed:
            return
        self.cursor_refresh_pending = self._callback_stamp()
        self.dimension_cursor_pending = True
        if not self.cursor_refresh_timer.isActive():
            self.cursor_refresh_timer.start(0)

    def queue_dimension_selection(self, model_edge=False):
        if self._changing_tool or self.tools.closed:
            return
        stamp = self._callback_stamp()
        previous = self.dimension_selection_pending
        if previous is not None and previous[0] == stamp:
            model_edge = model_edge or previous[1]
        self.dimension_selection_pending = stamp, bool(model_edge)
        if not self.dimension_selection_timer.isActive():
            self.dimension_selection_timer.start(0)

    def flush_dimension_selection(self):
        pending, self.dimension_selection_pending = self.dimension_selection_pending, None
        if pending is not None and self._callback_current(pending[0]):
            self.dimension_selection(model_edge=pending[1])

    def restore_dimension_cursor(self):
        from shiboken6 import isValid
        for widget, (explicit, cursor) in self.dimension_cursor_widgets.items():
            if not isValid(widget):
                continue
            if explicit:
                widget.setCursor(cursor)
            else:
                widget.unsetCursor()
        self.dimension_cursor_widgets.clear()

    def cancel_hover(self):
        self.hover_event += 1
        self.hover_timer.stop()
        self.hover_pending = None

    def clear_hover(self):
        self.cancel_hover()
        scene, node = self.hover_scene, self.hover_node
        # Detach ownership before native scene work, which may reenter and
        # publish a replacement. Cleanup must touch only this former node.
        self.hover_source = self.hover_scene = self.hover_node = None
        self._remove_hover_node(scene, node)

    @staticmethod
    def _remove_hover_node(scene, node):
        try:
            if scene is not None and node is not None:
                if scene.findChild(node) >= 0:
                    scene.removeChild(node)
        except (RuntimeError, ReferenceError):
            pass

    def show_hover(self, source, stamp=None, serial=None):
        stamp = self._callback_stamp() if stamp is None else stamp
        serial = self.hover_event if serial is None else serial
        if not self._hover_current(stamp, serial):
            return
        if source == self.hover_source:
            return
        # clear_hover advances our serial once. Do not adopt any additional
        # advance caused by a newer event delivered during scene cleanup.
        serial += 1
        self.clear_hover()
        if not source or not self._hover_current(stamp, serial):
            return
        obj, edge = source
        from pivy import coin
        shape = obj.getSubObject(edge).copy()
        shape.Placement = obj.getGlobalPlacement() * obj.Placement.inverse() * shape.Placement
        points = shape.discretize(Deflection=max(shape.BoundBox.DiagonalLength * .0005, .01))
        node = coin.SoSeparator()
        node.setName("KurtShapeSketchSourceHighlight")
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        node.addChild(pick)
        # Sketcher's axes/geometry are drawn slightly above the support face.
        # Keep the picked-source highlight visible where an edge overlaps an
        # axis, without altering the model or native selection rendering.
        depth = coin.SoDepthBuffer()
        depth.getField("test").setValue(False)
        depth.getField("write").setValue(False)
        depth.getField("function").setValue(coin.SoDepthBuffer.ALWAYS)
        node.addChild(depth)
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        node.addChild(light)
        color = coin.SoBaseColor()
        color.rgb = (.16, .42, .88)
        node.addChild(color)
        style = coin.SoDrawStyle()
        style.lineWidth = 3
        node.addChild(style)
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, [tuple(point) for point in points])
        node.addChild(coords)
        lines = coin.SoLineSet()
        lines.numVertices.setValue(len(points))
        node.addChild(lines)
        if not self._hover_current(stamp, serial):
            return
        scene = Gui.activeDocument().activeView().getSceneGraph()
        if not self._hover_current(stamp, serial):
            return
        try:
            scene.addChild(node)
        except (RuntimeError, ReferenceError):
            self._remove_hover_node(scene, node)
            raise
        if not self._hover_current(stamp, serial):
            self._remove_hover_node(scene, node)
            return
        self.hover_scene = scene
        self.hover_node = node
        self.hover_source = source

    def stop(self):
        active = self.tools.state.kind in {"reference", "dimension"}
        if active:
            self.tools.clear()
        self._cancel_deferred()
        self.dimension_refs = []
        self.suppress_release = None
        self._sync_tool_presentation()
        return active

    def source(self, obj, element):
        """Resolve both direct EdgeN and Body's feature-qualified selections."""
        sketch = self.panel.active_sketch()
        if not obj or not sketch or obj.Document != sketch.Document or obj == sketch:
            return None
        parts = element.split(".")
        edge = parts[-1]
        if not re.fullmatch(r"Edge[1-9][0-9]*", edge):
            return None
        for name in reversed(parts[:-1]):
            candidate = obj.Document.getObject(name)
            if candidate:
                obj = candidate
                break
        if obj.TypeId == "PartDesign::Body":
            obj = obj.Tip
        if not obj or obj == sketch or getattr(obj, "KurtShapeInternal", False):
            return None
        if not self.panel.sketch_history.allows_source(obj):
            return None
        try:
            obj.Shape.getElement(edge)
        except (AttributeError, RuntimeError, ValueError):
            return None
        return obj, edge

    def selected_sources(self):
        result = []
        for selection in Gui.Selection.getSelectionEx():
            for element in selection.SubElementNames:
                source = (sketch_tools.external_source(selection.Object, element)
                          if selection.Object == self.panel.active_sketch()
                          else self.source(selection.Object, element))
                if source and source not in result:
                    result.append(source)
        return result

    def project(self, sources, defining=True, preserve=False):
        sketch = self.panel.active_sketch()
        if not sketch or not sources:
            return False
        self.clear_hover()
        retained = [(selection.Object, element) for selection in Gui.Selection.getSelectionEx()
                    if selection.Object == sketch for element in selection.SubElementNames] if preserve else []
        # Native mapped edge names track the exact picked source. A nearest-
        # edge query could silently choose a neighbor when this edge vanishes.
        references = [{"feature": obj.Name, "subelement": edge} for obj, edge in sources]
        if not self.panel.operation("project_geometry", sketch=sketch.Name, references=references,
                                    defining=defining):
            return False
        Gui.Selection.clearSelection()
        for obj, element in retained:
            Gui.Selection.addSelection(obj, element)
        for obj, edge in sources:
            element = sketch_tools.external_selection(sketch, obj, edge)
            if element:
                Gui.Selection.addSelection(sketch, element)
        return True

    def use(self):
        sketch = self.panel.active_sketch()
        if not sketch:
            self.panel.notify("Edit a sketch before using projected geometry.", "error")
            return False
        hovered = self.hover_source
        if self.stop():
            self.panel.notify("Sketch reference picking ended")
            return True
        sources = self.selected_sources()
        # A previous Use leaves its projected curve selected for constraints.
        # Hovering the next model edge then pressing U must use that new edge.
        selected_model = any(selection.Object != sketch and selection.SubElementNames
                             for selection in Gui.Selection.getSelectionEx())
        if hovered and not selected_model:
            source = self.source(*hovered)
            sources = [source] if source else []
        Gui.runCommand("Sketcher_StopOperation")
        self.native_tool = None
        if sources:
            projected = self.project(sources)
            if projected:
                label = ", ".join(obj.Label + " · " + edge for obj, edge in sources)
                self.panel.notify("Used " + label + " · linked to source geometry")
            return projected
        Gui.Selection.clearSelection()
        self.picking = (sketch.Document.Name, sketch.Name)
        self.panel.notify("Use · click model edges to project onto this sketch · U or Esc ends Use")
        return True

    def prepare_constraint(self):
        # Existing external selections already belong to the native sketch.
        sources = [self.source(selection.Object, element)
                   for selection in Gui.Selection.getSelectionEx()
                   for element in selection.SubElementNames]
        sources = list(dict.fromkeys(source for source in sources if source))
        if sources and self.native_tool:
            retained = [(selection.Object, element) for selection in Gui.Selection.getSelectionEx()
                        for element in selection.SubElementNames]
            Gui.runCommand("Sketcher_StopOperation")
            Gui.Selection.clearSelection()
            for obj, element in retained:
                Gui.Selection.addSelection(obj, element)
        return not sources or self.project(sources, defining=False, preserve=True)

    def start_dimension(self, command):
        if command != "Sketcher_Dimension" or any(s.SubElementNames for s in Gui.Selection.getSelectionEx()):
            return False
        self.stop()
        Gui.runCommand("Sketcher_StopOperation")
        sketch = self.panel.active_sketch()
        self.native_tool = None
        self.dimension_picking = (sketch.Document.Name, sketch.Name)
        self.show_dimension_cursor()
        self.panel.notify("Dimension · choose a sketch point and model edge, or a curve · click to place the dimension")
        return True

    def dimension_selection(self, model_edge=False):
        if not self.dimension_picking or not self.panel.active_sketch():
            return
        sketch = self.panel.active_sketch()
        for selection in Gui.Selection.getSelectionEx():
            if selection.Object == sketch:
                for element in selection.SubElementNames:
                    if element not in self.dimension_refs:
                        self.dimension_refs.append(element)
        refs = list(self.dimension_refs)
        if len(refs) < 2 and (model_edge or not refs or refs[0].startswith("Vertex")):
            self.panel.notify("Dimension · choose the other point or edge")
            return
        self.stop()
        Gui.Selection.clearSelection()
        for element in refs:
            Gui.Selection.addSelection(sketch, element)
        self.panel.native_command("Sketcher_Dimension")

    def before_native(self, command):
        self.stop()
        if command.startswith("Sketcher_Constrain") or command == "Sketcher_Dimension":
            if not self.prepare_constraint():
                return False
        selected = any(s.SubElementNames for s in Gui.Selection.getSelectionEx())
        immediate = ((command.startswith("Sketcher_Constrain") and selected)
                     or command.startswith("Sketcher_Toggle")
                     or command in {"Sketcher_SelectConstraints", "Sketcher_SelectOrigin"})
        self.native_tool = (command if command.startswith("Sketcher_")
                            and command != "Sketcher_StopOperation" and not immediate else None)
        return True

    def hit(self, watched, event=None, point=None):
        view = Gui.activeDocument().activeView()
        if point is None:
            point = event.position() if hasattr(event, "position") else event.pos()
        ratio = watched.devicePixelRatioF()
        native = (math.floor(point.x() * ratio + .5), view.getSize()[1] - 1 - math.floor(point.y() * ratio + .5))
        hits = view.getObjectsInfo(native, 7.5 * ratio) or []
        if not hits:
            hit = view.getObjectInfo(native)
            hits = [hit] if hit else []
        candidates = []
        towards_camera = view.getCameraOrientation().multVec(App.Vector(0, 0, 1))
        for hit in hits:
            doc = App.getDocument(hit.get("Document", ""))
            if doc:
                source = self.source(doc.getObject(hit.get("Object", "")), hit.get("Component", ""))
                if source:
                    depth = App.Vector(hit["x"], hit["y"], hit["z"]).dot(towards_camera)
                    candidates.append((source[0].TypeId == "Sketcher::SketchObject", -depth, source))
        # Sketcher's edit scene can expose a support profile through its solid.
        # Prefer the actual model boundary to that coincident historical sketch.
        # Pick-all traversal order can change when the sketch is reopened.
        # Among solid edges choose the front boundary in the current camera.
        return min(candidates, key=lambda candidate: candidate[:2])[2] if candidates else None

    def native_preselection(self, sketch, watched=None, point=None):
        preselection = Gui.Selection.getPreselection()
        native = bool(preselection and preselection.ObjectName == sketch.Name
                      and preselection.DocumentName == sketch.Document.Name
                      and any(element.startswith(("Edge", "ExternalEdge", "Vertex"))
                              for element in preselection.SubElementNames))
        if not native or watched is None or point is None:
            return native
        # Sketcher's selection gate can leave the previous point highlighted
        # after the pointer moves over a foreign edge. Honor it only under the
        # actual cursor, so it cannot swallow a model-edge click elsewhere.
        view = Gui.activeDocument().activeView()
        ratio = watched.devicePixelRatioF()
        x, y = point.x() * ratio, view.getSize()[1] - 1 - point.y() * ratio
        for picked in preselection.PickedPoints:
            pixel = view.getPointOnViewport(picked)
            if math.hypot(pixel[0] - x, pixel[1] - y) <= 10 * ratio:
                return True
        return False

    def queue_hover(self, watched, point, sketch):
        if self.tools.closed or self._changing_tool:
            return
        stamp = self._callback_stamp()
        if (stamp[1] is None or stamp[1][1] != sketch
                or not self._hover_current(stamp, self.hover_event, watched)):
            return
        # Replace the pending position without restarting its timer. Sustained
        # motion must not postpone highlighting until the pointer pauses.
        # It also supersedes native hit/tessellation already in progress.
        self.hover_event += 1
        self.hover_pending = (watched, QtCore.QPointF(point), stamp, self.hover_event)
        if not self.hover_timer.isActive():
            self.hover_timer.start()

    def flush_hover(self):
        self.hover_timer.stop()
        pending, self.hover_pending = self.hover_pending, None
        if pending is None:
            return
        watched, point, stamp, serial = pending
        try:
            if not self._hover_current(stamp, serial, watched):
                return
            if self.native_preselection(stamp[1][1], watched, point):
                if self._hover_current(stamp, serial, watched):
                    self.clear_hover()
                return
            if not self._hover_current(stamp, serial, watched):
                return
            source = self.hit(watched, point=point)
            if self._hover_current(stamp, serial, watched):
                self.show_hover(source, stamp=stamp, serial=serial)
        except (AttributeError, RuntimeError, ReferenceError, ValueError, TypeError):
            if self._hover_current(stamp, serial, watched):
                self.clear_hover()

    def select_source(self, source, preserve):
        # Merely selecting an edge must not change the sketch or its history.
        # Dimension/constraint activation converts it to reference geometry;
        # explicit U converts it to defining, associated sketch geometry.
        if not preserve:
            Gui.Selection.clearSelection()
        Gui.Selection.addSelection(*source)

    def event(self, watched, event):
        if self.tools.closed or self._changing_tool:
            return False
        kind = event.type()
        viewport = isinstance(watched, QtGui.QWidget) and watched.metaObject().className() == "QOpenGLWidget"
        # Foreign GL events must not sync context, alter the cursor, consume a
        # release or stop the active view's tool. Keyboard/dialog routing and
        # ancestor-window deactivation retain their existing paths.
        if viewport and kind != QtCore.QEvent.KeyPress and self._viewport_window(watched) is None:
            return False
        if kind == QtCore.QEvent.WindowDeactivate:
            # This event belongs to an ancestor window, not the GL viewport.
            self._cancel_deferred()
            return False
        if kind in {QtCore.QEvent.KeyPress, QtCore.QEvent.MouseMove, QtCore.QEvent.MouseButtonPress,
                    QtCore.QEvent.MouseButtonRelease, QtCore.QEvent.Wheel}:
            self.sync_context()
            if self.tools.active and not self._same_context(self.tools.state.owner, self._context_stamp()):
                return False
        if kind == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Escape:
            app = QtGui.QApplication.instance()
            focus = app.focusWidget()
            if app.activePopupWidget() or focus and isinstance(focus.window(), QtGui.QDialog):
                return False
            native_tool = self.native_tool
            self.native_tool = None
            if self.stop():
                self.panel.notify("Sketch reference picking ended")
                return True
            if native_tool and self.panel.active_sketch():
                # A continuous polyline can cancel only its pending segment
                # on Escape. End its handler so subsequent clicks select
                # geometry for dimensions/constraints instead of drawing.
                Gui.runCommand("Sketcher_StopOperation")
                self.panel.router._last_native = None
                return True
        if not viewport:
            return False
        if kind == QtCore.QEvent.CursorChange and (self.dimension_picking or self.native_tool == "Sketcher_Dimension"):
            # The native handler can replace the viewport cursor after its
            # activation returns. Reapply once after that event, never on paint.
            if not self.dimension_cursor_pending:
                self.queue_dimension_cursor()
            return False
        if kind in {QtCore.QEvent.Leave, QtCore.QEvent.Hide, QtCore.QEvent.Close,
                    QtCore.QEvent.Wheel, QtCore.QEvent.WindowDeactivate}:
            self.clear_hover()
            return False
        if kind == QtCore.QEvent.MouseButtonRelease and self.suppress_release == (watched, event.button()):
            self.suppress_release = None
            return True
        sketch = self.panel.active_sketch()
        if not sketch:
            self.clear_hover()
            return False
        if self.picking and self.picking != (sketch.Document.Name, sketch.Name):
            self.stop()
        if self.dimension_picking and self.dimension_picking != (sketch.Document.Name, sketch.Name):
            self.stop()
        if kind == QtCore.QEvent.MouseMove:
            if self.dimension_picking or self.native_tool == "Sketcher_Dimension":
                self.show_dimension_cursor(watched)
            if event.buttons() != QtCore.Qt.NoButton or self.native_tool:
                self.clear_hover()
            else:
                # Let Sketcher update its point/curve preselection first.
                point = event.position() if hasattr(event, "position") else event.pos()
                self.queue_hover(watched, point, sketch)
            return False
        if kind == QtCore.QEvent.MouseButtonPress:
            # Click targeting stays synchronous at its actual coordinates.
            self.cancel_hover()
        if kind == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.RightButton:
            if event.modifiers() != QtCore.Qt.NoModifier or event.buttons() != QtCore.Qt.RightButton:
                return False  # Modified clicks and button chords belong to navigation.
            native_tool = self.native_tool
            if native_tool:
                # Native continuous tools can only reset their pending geometry
                # on right-click. End the handler before resuming source picks,
                # matching Escape instead of leaving a live untracked tool.
                Gui.runCommand("Sketcher_StopOperation")
            self.native_tool = None
            reference_picking = self.stop()
            if native_tool or reference_picking:
                self.panel.router._last_native = None
                self.suppress_release = (watched, event.button())
                if reference_picking:
                    self.panel.notify("Sketch reference picking ended")
                return True
        if kind == QtCore.QEvent.MouseButtonRelease and self.dimension_picking:
            self.queue_dimension_selection()
            return False
        if kind != QtCore.QEvent.MouseButtonPress or event.button() != QtCore.Qt.LeftButton:
            return False
        # Native drawing tools continue to receive their clicks.
        if not self.picking and not self.dimension_picking and self.native_tool:
            return False
        if not self.picking:
            point = event.position() if hasattr(event, "position") else event.pos()
            if self.native_preselection(sketch, watched, point):
                return False
        source = self.hit(watched, event)
        if not source:
            self.clear_hover()
            if self.picking:
                self.suppress_release = (watched, event.button())
            return bool(self.picking)
        self.suppress_release = (watched, event.button())
        if not self.picking and not self.dimension_picking:
            self.select_source(source, bool(event.modifiers() & QtCore.Qt.ControlModifier))
            return True
        projected = self.project([source], defining=bool(self.picking),
                                 preserve=bool(self.dimension_picking or event.modifiers() & QtCore.Qt.ControlModifier))
        if projected and self.dimension_picking:
            self.queue_dimension_selection(model_edge=True)
        return True
