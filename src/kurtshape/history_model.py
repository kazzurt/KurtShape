"""Reconcile native Qt tree rows by identity, retaining selection and scroll."""
from PySide import QtCore, QtGui


class HistoryModel:
    def __init__(self, tree):
        self.tree = tree
        self.document = None
        self.items = {}
        self.created = 0

    def reconcile(self, document, rows):
        if self.document != document:
            self.tree.clear()
            self.items.clear()
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
                if icon is not None and item.icon(0).cacheKey() != icon.cacheKey():
                    item.setIcon(0, icon)
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
            parent = item.parent()
            position = parent.indexOfChild(item) if parent else self.tree.indexOfTopLevelItem(item)
            if position >= 0:
                (parent.takeChild(position) if parent else self.tree.takeTopLevelItem(position))
        self.tree.verticalScrollBar().setValue(scroll)
        return self.items
