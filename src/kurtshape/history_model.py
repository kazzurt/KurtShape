"""Reconcile native Qt tree rows by identity, retaining selection and scroll."""
from PySide import QtCore, QtGui

from .presentation_icons import icon_signature


class HistoryModel:
    def __init__(self, tree):
        self.tree = tree
        self.document = None
        self.items = {}
        self.created = 0
        # Every item.setIcon this model performs. FreeCAD hands back a new
        # QIcon per ViewObject.Icon read, so an unchanged icon is recognised by
        # its pixel signature and is not set again.
        self.icon_sets = 0
        self.icon_signatures = {}

    def reconcile(self, document, rows):
        if self.document != document:
            self.tree.clear()
            self.items.clear()
            self.icon_signatures.clear()
            self.document = document
        wanted = set()
        scroll = self.tree.verticalScrollBar().value()

        def update(parent, records):
            for position, row in enumerate(records):
                key = row["key"]
                wanted.add(key)
                item = self.items.get(key)
                if item is None:
                    item = QtGui.QTreeWidgetItem()
                    self.items[key] = item
                    self.created += 1
                old_parent = item.parent()
                old_position = old_parent.indexOfChild(item) if old_parent else self.tree.indexOfTopLevelItem(item)
                if old_parent is not parent or old_position != position:
                    selected, expanded = item.isSelected(), item.isExpanded()
                    current = self.tree.currentItem() is item
                    if old_position >= 0:
                        (old_parent.takeChild(old_position) if old_parent else self.tree.takeTopLevelItem(old_position))
                    (parent.insertChild(position, item) if parent else self.tree.insertTopLevelItem(position, item))
                    item.setExpanded(expanded)
                    if current:
                        self.tree.setCurrentItem(item, 0, QtCore.QItemSelectionModel.NoUpdate)
                    item.setSelected(selected)
                if item.text(0) != row["text"]:
                    item.setText(0, row["text"])
                for role, value in row.get("data", {}).items():
                    if item.data(0, role) != value:
                        item.setData(0, role, value)
                tooltip = row.get("tooltip", "")
                if item.toolTip(0) != tooltip:
                    item.setToolTip(0, tooltip)
                icon = row.get("icon")
                if icon is not None:
                    shown = item.icon(0).cacheKey()
                    if shown != icon.cacheKey():
                        # Recorded as (cacheKey set, signature): an icon replaced
                        # outside this model no longer matches and is set again.
                        recorded = self.icon_signatures.get(key)
                        signature = icon_signature(icon)
                        if recorded is None or recorded[0] != shown or recorded[1] != signature:
                            item.setIcon(0, icon)
                            self.icon_sets += 1
                            self.icon_signatures[key] = (icon.cacheKey(), signature)
                brush = QtGui.QBrush(QtGui.QColor(row["color"])) if row.get("color") else QtGui.QBrush()
                if item.foreground(0) != brush:
                    item.setForeground(0, brush)
                font = item.font(0)
                italic, bold = row.get("italic", False), row.get("bold", False)
                if font.italic() != italic or font.bold() != bold:
                    font.setItalic(italic)
                    font.setBold(bold)
                    item.setFont(0, font)
                if "checked" in row:
                    item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                    check = QtCore.Qt.Checked if row["checked"] else QtCore.Qt.Unchecked
                    if item.checkState(0) != check:
                        item.setCheckState(0, check)
                if row.get("expand_new") and key not in self._previous_keys:
                    item.setExpanded(True)
                update(item, row.get("children", []))

        self._previous_keys = set(self.items)
        update(None, rows)
        def depth(key):
            result, parent = 0, self.items[key].parent()
            while parent is not None:
                result += 1
                parent = parent.parent()
            return result

        # Qt owns each subtree. Detach descendants first so dropping an old
        # parent cannot invalidate a child wrapper still awaiting removal.
        for key in sorted(set(self.items) - wanted, key=depth, reverse=True):
            item = self.items.pop(key)
            self.icon_signatures.pop(key, None)
            parent = item.parent()
            position = parent.indexOfChild(item) if parent else self.tree.indexOfTopLevelItem(item)
            if position >= 0:
                (parent.takeChild(position) if parent else self.tree.takeTopLevelItem(position))
        self.tree.verticalScrollBar().setValue(scroll)
        return self.items
