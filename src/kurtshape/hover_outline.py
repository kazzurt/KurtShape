"""Transient face-boundary hover; native clicks still select filled faces.

The native unified-selection node can disable its own hover rendering while
leaving clicks enabled. We do this only over faces, publish the same native
preselection reference for shortcuts/tasks, and draw an unpickable line set.
No document properties, view-provider colors or model geometry are changed.
"""
from __future__ import annotations

import re
from collections import OrderedDict

import FreeCAD as App

_controller = None
_FACE = re.compile(r"(?:^|\.)Face[1-9][0-9]*$")


def is_face_reference(element):
    return bool(_FACE.search(element or ""))


def boundary_polylines(shape):
    """Return every wire boundary, including holes, with bounded tessellation."""
    scale = max(shape.BoundBox.DiagonalLength, 1.0)
    deflection = max(scale * 0.0005, 0.01)
    result = []
    for edge in shape.Edges:
        points = edge.discretize(Deflection=deflection)
        if len(points) >= 2:
            result.append([tuple(point) for point in points])
    return result


def _selection_nodes(scene):
    from pivy import coin
    action = coin.SoSearchAction()
    action.setType(coin.SoType.fromName("SoFCUnifiedSelection"))
    action.setInterest(coin.SoSearchAction.ALL)
    action.apply(scene)
    return [path.getTail() for path in action.getPaths()]


class FaceHoverOutline:
    def __init__(self):
        self.scene = None
        self.node = None
        self.key = None
        self.native_modes = []
        self.boundaries = OrderedDict()
        self.cached_points = 0
        self.boundary_builds = self.pick_count = 0

    def invalidate(self, document=None):
        for key in list(self.boundaries):
            if document is None or key[0] == document:
                self.cached_points -= self.boundaries.pop(key)[-1]
        if self.key and (document is None or self.key[0] == document):
            self.clear()

    def _boundary(self, document, obj, element):
        key = (document.Name, obj.Name, element)
        placement = tuple(obj.getGlobalPlacement().Matrix.A)
        cached = self.boundaries.pop(key, None)
        if cached is not None:
            self.cached_points -= cached[-1]
            if cached[:3] == (document, obj, placement):
                self.boundaries[key] = cached
                self.cached_points += cached[-1]
                return cached[3]
        shape = obj.getSubObject(element)
        if shape is None or not hasattr(shape, "Edges") or shape.isNull():
            return []
        shape = shape.copy()
        shape.Placement = obj.getGlobalPlacement() * obj.Placement.inverse() * shape.Placement
        polylines = boundary_polylines(shape)
        self.boundary_builds += 1
        count = sum(len(line) for line in polylines)
        # Bound both entry count and geometry payload. Huge individual faces
        # are still displayed, but do not displace the bounded hover cache.
        if count <= 100000:
            self.boundaries[key] = (document, obj, placement, polylines, count)
            self.cached_points += count
            while len(self.boundaries) > 32 or self.cached_points > 100000:
                self.cached_points -= self.boundaries.popitem(last=False)[1][-1]
        return polylines

    def _restore_modes(self):
        for node, previous in self.native_modes:
            node.preselectionMode.setValue(previous)
        self.native_modes = []

    def clear(self):
        # A document may close between the Qt leave event and cleanup.
        try:
            if self.key is not None:
                import FreeCADGui as Gui
                preselection = Gui.Selection.getPreselection()
                if (preselection and (preselection.DocumentName, preselection.ObjectName,
                                      next(iter(preselection.SubElementNames), '')) == self.key):
                    Gui.Selection.clearPreselection()
            self._restore_modes()
            if self.scene is not None and self.node is not None:
                if self.scene.findChild(self.node) >= 0:
                    self.scene.removeChild(self.node)
        except (RuntimeError, ReferenceError):
            self.native_modes = []
        self.scene = self.node = self.key = None

    def show(self, view, document, obj, element):
        key = (document.Name, obj.Name, element)
        scene = view.getSceneGraph()
        if key == self.key and scene == self.scene:
            return
        self.clear()
        polylines = self._boundary(document, obj, element)
        if not polylines:
            return
        from pivy import coin
        import FreeCADGui as Gui
        # The coalesced pick runs after native mouse handling. Clear any filled
        # native hover while its renderer is still enabled, then republish the
        # same reference below with only our boundary renderer active.
        Gui.Selection.clearPreselection()
        self.scene = scene
        for node in _selection_nodes(self.scene):
            self.native_modes.append((node, node.preselectionMode.getValue()))
            node.preselectionMode.setValue(2)  # SoFCUnifiedSelection::OFF
        if not self.native_modes:
            self.clear()
            return
        overlay = coin.SoSeparator()
        overlay.setName("KurtShapeFaceHoverOutline")
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        overlay.addChild(pick)
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        overlay.addChild(light)
        material = coin.SoMaterial()
        material.diffuseColor = (0.16, 0.42, 0.88)
        overlay.addChild(material)
        style = coin.SoDrawStyle()
        style.lineWidth = 2.5
        overlay.addChild(style)
        # Respect depth; a hovered front boundary must not reveal hidden edges.
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, [point for line in polylines for point in line])
        overlay.addChild(coords)
        lines = coin.SoLineSet()
        lines.numVertices.setValues(0, [len(line) for line in polylines])
        overlay.addChild(lines)
        self.scene.addChild(overlay)
        self.node = overlay
        self.key = key

    def update(self, view, position):
        import FreeCADGui as Gui
        self.pick_count += 1
        hit = view.getObjectInfo(position)
        if not hit or not is_face_reference(hit.get("Component", "")):
            self.clear()
            return
        document = App.getDocument(hit["Document"])
        obj = document.getObject(hit["Object"])
        element = hit["Component"]
        # Keep native gates authoritative. Publishing normal preselection with
        # its hover renderer disabled preserves N/Y and tool selection hooks.
        self.show(view, document, obj, element)
        if self.node is not None:
            # type 0 is a normal preselection notification: unlike the default
            # internal/script type 1, it honours the disabled native renderer.
            Gui.Selection.setPreselection(obj, element, hit["x"], hit["y"], hit["z"], 0)
            preselection = Gui.Selection.getPreselection()
            if not preselection or preselection.ObjectName != obj.Name:
                self.clear()


def install_hover_outline():
    global _controller
    if _controller is not None:
        return _controller
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui

    class HoverEvents(QtCore.QObject):
        def __init__(self):
            super().__init__(Gui.getMainWindow())
            self.outline = FaceHoverOutline()
            self.pending = None
            self.timer = QtCore.QTimer(self)
            self.timer.setSingleShot(True)
            self.timer.setInterval(16)
            self.timer.timeout.connect(self.flush)

        def clear(self):
            self.timer.stop()
            self.pending = None
            self.outline.clear()

        def flush(self):
            self.timer.stop()
            pending, self.pending = self.pending, None
            if pending is None:
                return
            watched, document_name, point = pending
            from shiboken6 import isValid
            if not isValid(watched) or not watched.isVisible():
                self.clear()
                return
            doc = Gui.activeDocument()
            source = App.activeDocument()
            if not doc or not source or source.Name != document_name or doc.getInEdit():
                self.clear()
                return
            view = doc.activeView()
            ratio = watched.devicePixelRatioF()
            native = (round(point.x() * ratio), view.getSize()[1] - 1 - round(point.y() * ratio))
            try:
                self.outline.update(view, native)
            except (RuntimeError, ReferenceError, AttributeError, TypeError, ValueError):
                self.clear()

        def slotRecomputedDocument(self, doc):
            self.outline.invalidate(doc.Name)

        slotUndoDocument = slotRedoDocument = slotAbortTransaction = slotRecomputedDocument

        def slotChangedObject(self, obj, prop):
            if prop in {"Shape", "Placement", "LinkPlacement", "LinkedObject", "Tip", "Group"}:
                self.outline.invalidate(obj.Document.Name)

        def slotDeletedDocument(self, doc):
            self.clear()
            self.slotRecomputedDocument(doc)

        def slotActivateDocument(self, doc):
            self.clear()

        def slotDeletedObject(self, obj):
            self.outline.invalidate(obj.Document.Name)

        def eventFilter(self, watched, event):
            if not isinstance(watched, QtGui.QWidget) or watched.metaObject().className() != "QOpenGLWidget":
                return False
            parent = watched.parentWidget()
            if not parent or parent.metaObject().className() != "Gui::View3DInventorViewer":
                return False
            if event.type() in (QtCore.QEvent.Leave, QtCore.QEvent.Hide, QtCore.QEvent.Close, QtCore.QEvent.Wheel):
                self.clear()
            elif event.type() == QtCore.QEvent.MouseMove and event.buttons() == QtCore.Qt.NoButton:
                doc = Gui.activeDocument()
                if doc:
                    # Sketcher owns native geometry highlighting; its model
                    # edge adapter supplies a separate edge-only highlight.
                    if doc.getInEdit():
                        self.clear()
                        return False
                    point = event.position() if hasattr(event, "position") else event.pos()
                    self.pending = (watched, App.activeDocument().Name, QtCore.QPointF(point))
                    if not self.timer.isActive():
                        self.timer.start()
            elif event.type() == QtCore.QEvent.MouseButtonPress:
                if event.button() == QtCore.Qt.LeftButton:
                    self.flush()
                else:
                    self.clear()
            return False

    _controller = HoverEvents()
    QtGui.QApplication.instance().installEventFilter(_controller)
    App.addDocumentObserver(_controller)
    return _controller
