"""Synchronize viewport selection with the corresponding history rows.

Tree updates block signals so highlighting a face's feature never replaces the
selected native face with a whole feature or interrupts an active picker.
"""
from __future__ import annotations

import FreeCADGui as Gui
from PySide import QtCore, QtGui

from . import document_index
from .face_provenance import FaceProvenance


FACE_MODIFIER_ROLE = QtCore.Qt.UserRole + 3


class FaceHistoryLinks:
    def __init__(self, panel):
        self.panel = panel
        self.resolver = FaceProvenance(panel.core)
        self.feature_ids = ()
        self.results = ()
        self.context = None
        self.last_faces = ()
        self.pending_reveal = False
        self.closed = False
        self.decorated = {}
        self.timer = QtCore.QTimer(panel)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._scheduled_sync)
        self.bar = QtGui.QWidget(panel)
        self.bar.setObjectName("KurtShapeFaceHistoryLink")
        layout = QtGui.QHBoxLayout(self.bar)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(4)
        self.reveal_button = QtGui.QPushButton("Reveal")
        self.reveal_button.setToolTip("Clear the feature filter and reveal the selected feature")
        self.reveal_button.clicked.connect(self.reveal)
        layout.addWidget(self.reveal_button)
        self.bar.hide()

    def allowed(self):
        p = self.panel
        return bool(not self.closed and p.state and p.state.get("managed", True)
                    and p.workspace_mode == "part_studio" and not p.core.busy
                    and not p.pending_sketch and not p.selecting_support
                    and not p.task and not p.studio_dialog and not p.studio_selection_callback
                    and not p.active_sketch() and not p.native_feature_task_active()
                    and not p.sketch_plane_editor.picking and not p.section_view.picking)

    def _context(self):
        doc = self.panel.document()
        if not doc or not self.allowed():
            return None
        index = document_index.get(doc)
        generation = index.token("structure", "history", "topology", "placement", "metadata") if index else None
        state = self.panel.core.observer.state(doc)
        return (doc.Name, id(doc), self.panel.state["document_id"], generation,
                state["generation"], state["version_clock"], doc.UndoCount, doc.RedoCount)

    def _faces(self):
        doc = self.panel.document()
        if not doc:
            return ()
        return tuple((entry.ObjectName, element)
                     for entry in Gui.Selection.getSelectionEx(doc.Name)
                     for element in entry.SubElementNames
                     if element.startswith("Face") and element[4:].isdigit())

    def schedule(self, reveal=False):
        if self.closed:
            return
        self.pending_reveal |= reveal
        self.timer.start(0)

    def _scheduled_sync(self):
        reveal, self.pending_reveal = self.pending_reveal, False
        self.sync(reveal=reveal)

    def poll(self):
        """Cheap invalidation check in the existing panel tick; no model reads."""
        context = self._context()
        if context != self.context:
            self.clear()
            self.context = context
            if context is not None:
                self.schedule()

    def _undecorate(self):
        items = getattr(self.panel, "items", {})
        for name, (item, tooltip, accessible) in self.decorated.items():
            # A reconciled/deleted Qt row can no longer be touched.
            if items.get(name) is item:
                item.setData(0, FACE_MODIFIER_ROLE, None)
                if item.toolTip(0).endswith("\nFeature of selected face"):
                    item.setToolTip(0, tooltip)
                item.setData(0, QtCore.Qt.AccessibleTextRole, accessible)
        self.decorated.clear()

    def clear(self):
        self.timer.stop()
        self.pending_reveal = False
        self._undecorate()
        self.feature_ids = ()
        self.results = ()
        self.last_faces = ()
        self.reveal_button.hide()
        self.bar.hide()

    def _select_rows(self, names, current=None):
        """Replace stale tree selection without emitting geometry commands."""
        tree = self.panel.features
        items = getattr(self.panel, "items", {})
        names = tuple(name for name in names if name in items)
        current = current if current in names else names[-1] if names else None
        selected = {item.data(0, QtCore.Qt.UserRole) for item in tree.selectedItems()}
        current_item = tree.currentItem()
        current_name = current_item.data(0, QtCore.Qt.UserRole) if current_item else None
        # Native whole-object selection can echo a tree click. Keeping an
        # identical Qt selection also preserves its Shift-range anchor.
        if selected == set(names) and current_name == current:
            return
        before = tree.blockSignals(True)
        try:
            tree.clearSelection()
            tree.setCurrentItem(None)
            for name in names:
                items[name].setSelected(True)
            if current:
                tree.setCurrentItem(items[current], 0, QtCore.QItemSelectionModel.NoUpdate)
        finally:
            tree.blockSignals(before)
        self.panel.history_controller.highlight_planes()

    def _selected_objects(self):
        """Keep a deliberate tree/whole-object pick when it has no faces."""
        doc = self.panel.document()
        items = getattr(self.panel, "items", {})
        names = []
        for entry in Gui.Selection.getSelectionEx(doc.Name):
            if entry.SubElementNames:
                continue
            if entry.ObjectName in items:
                names.append(entry.ObjectName)
                continue
            # Origin planes have synthetic row keys rather than object names.
            for name in self.panel.history_controller.selected_ids():
                obj = self.panel.history_controller.resolve(name)
                if obj and obj.Name == entry.ObjectName:
                    names.append(name)
        return tuple(dict.fromkeys(names))

    def sync(self, reveal=False):
        context = self._context()
        if context is None:
            self.clear()
            self.context = None
            return
        faces = self._faces()
        added = [face for face in faces if face not in self.last_faces]
        self._undecorate()
        self.context = context
        self.last_faces = faces
        if not faces:
            names = self._selected_objects()
            item = self.panel.features.currentItem()
            current = item.data(0, QtCore.Qt.UserRole) if item else None
            selected = {item.data(0, QtCore.Qt.UserRole) for item in self.panel.features.selectedItems()}
            self.clear()
            if names and selected == set(names):
                # A Ctrl toggle can leave the clicked current row unselected.
                # An echoed native selection must retain that Qt range anchor.
                return
            self._select_rows(names, current)
            return
        doc = self.panel.document()
        results = tuple(self.resolver.resolve(doc, name, element) for name, element in faces)
        # Resolve is read-only and synchronous today. Still reject obsolete
        # completions if an adapter ever processes native events internally.
        if self._context() != context or self._faces() != faces:
            self.clear()
            self.context = None
            self.schedule()
            return
        self.results = results
        items = getattr(self.panel, "items", {})
        self.feature_ids = tuple(dict.fromkeys(result["feature"] for result in results
                                  if result["status"] == "resolved" and result.get("feature") in items))
        for name in self.feature_ids:
            item = items[name]
            tooltip, accessible = item.toolTip(0), item.data(0, QtCore.Qt.AccessibleTextRole)
            self.decorated[name] = item, tooltip, accessible
            item.setData(0, FACE_MODIFIER_ROLE, True)
            item.setToolTip(0, tooltip + "\nFeature of selected face")
            item.setData(0, QtCore.Qt.AccessibleTextRole, item.text(0) + ", feature of selected face")
        target = next((result.get("feature") for face, result in reversed(tuple(zip(faces, results)))
                       if face in added and result["status"] == "resolved"), None)
        self._select_rows(self.feature_ids, target)
        self.update_filter()
        if reveal and added:
            self._show_row(target)

    def update_filter(self):
        items = getattr(self.panel, "items", {})
        filtered = any(items[name].isHidden() for name in self.feature_ids if name in items)
        self.reveal_button.setVisible(filtered)
        self.bar.setVisible(filtered)

    def _show_row(self, name):
        item = getattr(self.panel, "items", {}).get(name)
        if item is None or item.isHidden():
            return
        ancestor = item.parent()
        while ancestor is not None:
            ancestor.setExpanded(True)
            ancestor = ancestor.parent()
        self.panel.features.scrollToItem(item, QtGui.QAbstractItemView.EnsureVisible)

    def reveal(self):
        self.panel.filter.clear()
        for name in reversed(self.feature_ids):
            self._show_row(name)
            break

    def close(self):
        self.clear()
        self.resolver.clear()
        self.closed = True
