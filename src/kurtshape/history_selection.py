"""History selection, atomic deletion and temporary native plane highlighting."""
from __future__ import annotations
from contextlib import contextmanager

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui

from .bodies import owner
from .face_history_links import FACE_MODIFIER_ROLE as FACE_MODIFIER_ROLE, FaceHistoryLinks
from .theme import COLORS

ROLLED_BACK_ROLE = QtCore.Qt.UserRole + 2


class HistoryDelegate(QtGui.QStyledItemDelegate):
    """Render rolled-back rows while retaining Qt's ordinary selection fill."""
    def paint(self, painter, option, index):
        if not index.data(ROLLED_BACK_ROLE):
            super().paint(painter, option, index)
            return
        styled = QtGui.QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        text = styled.text
        styled.text = ""
        widget = styled.widget
        style = widget.style() if widget else QtGui.QApplication.style()
        style.drawControl(QtGui.QStyle.CE_ItemViewItem, styled, painter, widget)
        rect = style.subElementRect(QtGui.QStyle.SE_ItemViewItemText, styled, widget)
        painter.save()
        painter.setFont(styled.font)
        selected = bool(styled.state & QtGui.QStyle.State_Selected)
        foreground = index.data(QtCore.Qt.ForegroundRole)
        normal_color = (foreground.color() if isinstance(foreground, QtGui.QBrush)
                        and foreground.style() != QtCore.Qt.NoBrush else COLORS["ink"])
        color = (COLORS["disabled_ink"] if index.data(ROLLED_BACK_ROLE) else
                 COLORS["selection_ink"] if selected else normal_color)
        painter.setPen(QtGui.QColor(color))
        text = QtGui.QFontMetrics(styled.font).elidedText(text, styled.textElideMode, rect.width())
        painter.drawText(rect, styled.displayAlignment, text)
        painter.restore()


class PlaneHighlight:
    """Reveal selected native planes without changing their saved presentation."""
    def __init__(self, panel):
        self.panel = panel
        panel.features.setItemDelegate(HistoryDelegate(panel.features))
        self.saved = {}
        self.modified = {}
        self.targets = ()

    def model_token(self, doc):
        state = self.panel.core.observer.state(doc)
        return (self.panel.core._meta(doc).Revision, doc.UndoCount, doc.RedoCount,
                state["version_clock"], state["generation"], state["intent_dirty"])

    @staticmethod
    def gui_document(name):
        try:
            return Gui.getDocument(name)
        except (NameError, ReferenceError, RuntimeError):
            return None

    def restore_modified(self, doc, saved, before):
        # Temporary presentation writes introduce their own native dirty flag.
        # A flag already raised by another edit, or changed native intent,
        # must survive when the presentation is restored.
        # Native datum presentation can briefly report changed intent. Preserve
        # its dirty flag rather than defer a reset that could hide a real edit.
        state = self.panel.core.observer.state(doc)
        if before == saved["value"] and not state["intent_dirty"] and self.model_token(doc) == saved["token"]:
            gui_doc = self.gui_document(doc.Name)
            if gui_doc:
                gui_doc.Modified = saved["value"]

    def remember(self, obj, properties):
        if obj.Document.Name not in self.modified:
            self.modified[obj.Document.Name] = {"value": Gui.getDocument(obj.Document.Name).Modified,
                                                "token": self.model_token(obj.Document)}
        key = (obj.Document.Name, obj.Name)
        saved = self.saved.setdefault(key, {})
        view = obj.ViewObject
        for name in properties:
            if name in view.PropertiesList and name not in saved:
                value = getattr(view, name)
                saved[name] = tuple(value) if isinstance(value, (list, tuple)) else value

    def restore(self):
        before = {}
        for name in self.modified:
            gui_doc = self.gui_document(name)
            if gui_doc:
                before[name] = gui_doc.Modified
        for (document, name), properties in reversed(list(self.saved.items())):
            doc = App.listDocuments().get(document)
            obj = doc.getObject(name) if doc else None
            if obj:
                for prop, value in properties.items():
                    try:
                        setattr(obj.ViewObject, prop, value)
                    except (RuntimeError, AttributeError):
                        pass
        for name, saved in self.modified.items():
            doc = App.listDocuments().get(name)
            if doc and name in before:
                self.restore_modified(doc, saved, before[name])
        self.saved.clear()
        self.modified.clear()
        self.targets = ()

    def show(self, planes):
        targets = tuple((obj.Document.Name, obj.Name) for obj in planes)
        if targets == self.targets:
            return
        self.restore()
        self.targets = targets
        accent = QtGui.QColor(COLORS["accent"])
        color = (accent.redF(), accent.greenF(), accent.blueF())
        for obj in planes:
            body = owner(obj.Document, obj)
            if obj.TypeId == "App::Plane" and body:
                self.remember(body.Origin, ["Visibility"])
                body.Origin.ViewObject.Visibility = True
            properties = ["Visibility", "ShapeColor", "LineColor", "PlaneColor", "Transparency"]
            self.remember(obj, properties)
            view = obj.ViewObject
            view.Visibility = True
            for name in ("ShapeColor", "LineColor", "PlaneColor"):
                if name in view.PropertiesList:
                    setattr(view, name, color)
            if "Transparency" in view.PropertiesList:
                view.Transparency = min(70, view.Transparency)
        for name, saved in self.modified.items():
            self.restore_modified(App.getDocument(name), saved, saved["value"])

    def forget_document(self, name):
        self.saved = {key: value for key, value in self.saved.items() if key[0] != name}
        self.modified.pop(name, None)
        self.targets = tuple(key for key in self.targets if key[0] != name)


class HistorySelection:
    """Use Qt's range/toggle selection and retain it across tree reconstruction."""
    def __init__(self, panel):
        self.panel = panel
        self.document_name = None
        self.snapshot = ([], None)
        self.planes = PlaneHighlight(panel)
        self.face_links = FaceHistoryLinks(panel)
        self.closed = False
        App.addDocumentObserver(self)
        panel.destroyed.connect(self.close)

    def selected_ids(self):
        return [item.data(0, QtCore.Qt.UserRole) for item in self.panel.features.selectedItems()]

    def feature_ids(self):
        valid = {feature["id"] for feature in (self.panel.state or {}).get("features", [])}
        return [key for key in self.selected_ids() if key in valid]

    def before_refresh(self, doc):
        self.face_links.clear()
        if not doc or doc.Name != self.document_name:
            self.planes.restore()
            self.document_name = doc.Name if doc else None
            self.snapshot = ([], None)
        else:
            item = self.panel.features.currentItem()
            current = item.data(0, QtCore.Qt.UserRole) if item else None
            self.snapshot = (self.selected_ids(), current)
        return self.snapshot

    def restore_selection(self):
        tree = self.panel.features
        keys, current = self.snapshot
        for key in keys:
            item = self.panel.items.get(key)
            if item:
                item.setSelected(True)
        item = self.panel.items.get(current)
        if item:
            tree.setCurrentItem(item, 0, QtCore.QItemSelectionModel.NoUpdate)
        self.highlight_planes()
        self.face_links.schedule()

    def resolve(self, key):
        doc = self.panel.document()
        if not doc:
            return None
        if key == "origin":
            body = self.panel.active_body()
            return body.Origin if body else None
        if key and key.startswith("plane:"):
            return self.panel.plane(doc, key.split(":")[1])
        return doc.getObject(key or "")

    def highlight_planes(self):
        if self.panel.pending_sketch or getattr(getattr(self.panel, "sketch_plane_editor", None), "picking", False):
            return
        planes = []
        for key in self.selected_ids():
            obj = self.resolve(key)
            if obj and obj.TypeId in {"App::Plane", "PartDesign::Plane"}:
                planes.append(obj)
            elif key == "origin" and obj:
                planes.extend(plane for plane in obj.OriginFeatures if plane.TypeId == "App::Plane")
        self.planes.show(list(dict.fromkeys(planes)))

    @contextmanager
    def suspend_planes(self):
        highlighted = bool(self.planes.saved)
        self.planes.restore()
        try:
            yield
        finally:
            if highlighted:
                self.highlight_planes()

    def sync_native_selection(self):
        Gui.Selection.clearSelection()
        for key in self.selected_ids():
            obj = self.resolve(key)
            if obj:
                Gui.Selection.addSelection(obj)

    def delete(self):
        panel = self.panel
        keys = self.feature_ids()
        if not keys:
            panel.notify("Select one or more features to delete.")
            return None
        if any(panel.feature_held(key) for key in keys):
            panel.notify("Roll forward through this feature before editing it.")
            return None
        doc = panel.document()
        tokens = {"_expected_revision": panel.state["revision"], "_document_id": panel.state["document_id"]}
        try:
            plan = panel.core.delete_features_plan(doc, keys)
        except Exception as exc:
            panel.notify(str(exc), "error")
            return None
        cascade = bool(plan["dependents"])
        if cascade:
            names = [doc.getObject(key).Label for key in plan["dependents"]]
            prompt = "These dependent features will also be deleted:\n\n" + "\n".join(names)
            answer = QtGui.QMessageBox.question(panel, "Delete dependent features?", prompt,
                                                QtGui.QMessageBox.Yes | QtGui.QMessageBox.No, QtGui.QMessageBox.No)
            if answer != QtGui.QMessageBox.Yes:
                return None
        return panel.operation("delete_features", features=keys, cascade=cascade, **tokens)

    def slotActivateDocument(self, doc):
        if doc.Name != self.document_name:
            self.planes.restore()
            self.face_links.clear()

    def slotDeletedDocument(self, doc):
        self.face_links.clear()
        self.face_links.resolver.clear()
        self.planes.forget_document(doc.Name)
        if doc.Name == self.document_name:
            self.document_name = None
            self.snapshot = ([], None)

    def close(self, *_):
        if not self.closed:
            self.face_links.close()
            self.planes.restore()
            App.removeDocumentObserver(self)
            self.closed = True
