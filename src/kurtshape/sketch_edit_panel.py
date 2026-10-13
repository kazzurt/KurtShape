"""Compact sketch support field and native support replacement during an edit."""
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui

from . import navigation
from .bodies import owner, origin_plane
from .presentation_icons import icon_for


class SketchPlaneEditor:
    def __init__(self, panel):
        self.panel = panel
        self.picking = False
        self.choosing = False
        self.document_name = self.sketch_name = None
        self.visibility = {}
        self.widget = QtGui.QWidget()
        self.widget.setObjectName("KurtShapeSketchPlane")
        layout = QtGui.QVBoxLayout(self.widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(QtGui.QLabel("Sketch plane"))
        row = QtGui.QHBoxLayout()
        self.field = QtGui.QPushButton()
        self.field.setObjectName("KurtShapeSketchPlaneValue")
        self.field.setAccessibleName("Sketch plane")
        self.field.clicked.connect(self.begin_pick)
        self.clear = QtGui.QToolButton()
        self.clear.setObjectName("KurtShapeSketchPlaneClear")
        self.clear.setIcon(icon_for("Cancel"))
        self.clear.setIconSize(QtCore.QSize(16, 16))
        self.clear.setAutoRaise(True)
        self.clear.setAccessibleName("Clear sketch plane")
        self.clear.setToolTip("Clear plane and select a replacement")
        self.clear.clicked.connect(self.begin_pick)
        row.addWidget(self.field, 1)
        row.addWidget(self.clear)
        layout.addLayout(row)

    def sketch(self):
        doc = App.listDocuments().get(self.document_name)
        return doc.getObject(self.sketch_name) if doc and self.sketch_name else None

    def label(self, sketch):
        labels = {"XY": "Top (XY)", "XZ": "Front (XZ)", "YZ": "Right (YZ)"}
        body = owner(sketch.Document, sketch)
        supports = []
        for obj, elements in sketch.AttachmentSupport:
            plane = next((key for key in labels if body and origin_plane(body, key) == obj), None)
            text = labels[plane] if plane else obj.Label
            elements = [element for element in elements if element]
            if elements:
                text += " · " + ", ".join(elements)
            supports.append(text)
        return ", ".join(supports) or "Unattached plane"

    def refresh(self, sketch=None):
        sketch = sketch or self.panel.active_sketch() or self.sketch()
        if self.picking or self.panel.pending_sketch:
            text = "Select a plane or planar face"
        else:
            text = self.label(sketch) if sketch else "Select a plane or planar face"
        self.field.setText(text)
        self.field.setToolTip(text)
        self.clear.setVisible(bool(sketch) and not self.picking)

    def begin_pick(self):
        p = self.panel
        sketch = p.active_sketch()
        if self.picking or not sketch:
            return
        p.sketch_references.stop()
        p.sketch_references.native_tool = None
        Gui.runCommand("Sketcher_StopOperation")
        p.router._last_native = None
        p.history_controller.planes.restore()
        self.document_name, self.sketch_name = sketch.Document.Name, sketch.Name
        # Keep the accepted native support intact until another valid support
        # is chosen. Reset native Sketcher only to release its selection gate;
        # the managed edit lease retains Finish/Cancel and its undo history.
        self.picking = True
        Gui.activeDocument().resetEdit()
        Gui.Selection.clearSelection()
        p.sketch_history.apply()
        body = owner(sketch.Document, sketch)
        if body:
            for obj in [body.Origin] + [origin_plane(body, key) for key in ("XY", "XZ", "YZ")]:
                if obj:
                    self.visibility[obj.Name] = obj.ViewObject.Visibility
                    obj.ViewObject.Visibility = True
        p.sync_edit_ui()
        p.notify("Select a plane or planar face · Escape keeps the current plane")

    def apply_visibility(self):
        if self.picking:
            sketch = self.sketch()
            if sketch:
                for name in self.visibility:
                    obj = sketch.Document.getObject(name)
                    if obj:
                        obj.ViewObject.Visibility = True

    def restore_visibility(self):
        sketch = self.sketch()
        if sketch:
            for name, visible in self.visibility.items():
                obj = sketch.Document.getObject(name)
                if obj:
                    obj.ViewObject.Visibility = visible
        self.visibility = {}

    def history_pick(self, key):
        if not self.picking:
            return False
        if key and key.startswith("plane:"):
            attachment = {"plane": key.split(":")[1]}
        else:
            sketch = self.sketch()
            obj = sketch.Document.getObject(key or "") if sketch else None
            attachment = {"support": {"feature": obj.Name}} if obj and obj.TypeId in {"App::Plane", "PartDesign::Plane"} else None
        if attachment:
            self.queue_choice(attachment)
        return True

    def selection_pick(self, document, name, element):
        if not self.picking:
            return False
        sketch = self.sketch()
        if not sketch or sketch.Document.Name != document:
            return True
        obj = sketch.Document.getObject(name)
        if obj and (obj.TypeId in {"App::Plane", "PartDesign::Plane"} or element.split(".")[-1].startswith("Face")):
            # Body selections can contain a feature-qualified FaceN path.
            for token in element.split(".")[:-1]:
                candidate = sketch.Document.getObject(token)
                if candidate:
                    obj = candidate
            if obj.TypeId == "PartDesign::Body":
                obj = obj.Tip
            support = {"feature": obj.Name}
            if element:
                support["subelement"] = element.split(".")[-1]
            self.queue_choice({"support": support})
        return True

    def queue_choice(self, attachment):
        if self.choosing:
            return
        self.choosing = True
        QtCore.QTimer.singleShot(0, lambda: self.choose(attachment))

    def choose(self, attachment):
        try:
            sketch = self.sketch()
            if not self.picking or not sketch:
                return
            if self.panel.operation("set_sketch_support", sketch=sketch.Name, **attachment):
                self.resume(orient=True)
        finally:
            self.choosing = False

    def resume(self, orient=False):
        sketch = self.sketch()
        if not sketch:
            self.close()
            return False
        p = self.panel
        self.restore_visibility()
        p.entering_sketch = True
        try:
            Gui.Selection.clearSelection()
            view = Gui.getDocument(sketch.Document.Name).activeView()
            camera = view.getCamera()
            navigation.allow_sketch_3d(sketch, view)
            Gui.getDocument(sketch.Document.Name).setEdit(sketch.Name)
            navigation.allow_sketch_3d(sketch, view, camera=camera)
            if orient:
                navigation.normal_to_sketch(sketch, view)
            self.picking = False
            p.sketch_history.apply()
        finally:
            p.entering_sketch = False
        p.sync_edit_ui()
        return True

    def close(self):
        self.restore_visibility()
        self.picking = self.choosing = False
        self.document_name = self.sketch_name = None
