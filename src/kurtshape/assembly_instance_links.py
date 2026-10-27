"""Selected occurrence geometry highlights its instance rows (assembly UX item 2).

The assembly sibling of ``face_history_links``: a face, edge or vertex picked
on an occurrence (an ``App::Link``) selects that instance's row in both the
features tree's Instances group and the Instances list. Tree updates block
signals, so highlighting a row never replaces the native sub-element selection
with the whole occurrence. The row of the most recently selected instance is
scrolled to the vertical centre; folders holding a highlighted row expand.
"""
from __future__ import annotations

from PySide import QtCore, QtGui


def instance_owners(selection, instance_ids, assembly_names=()):
    """Instance ids owning the selected entries, in selection order, without repeats.

    ``selection`` is ``[(object_name, (subelement, ...)), ...]`` as
    ``Gui.Selection.getSelectionEx`` reports it. A pick on an occurrence names
    the link itself; a pick resolved from the assembly names the link as the
    first component of the sub-element path (``"Left.Face6"``).
    """
    instance_ids = set(instance_ids)
    owners = []
    for name, subelements in selection:
        if name in instance_ids:
            owners.append(name)
        elif name in assembly_names:
            for sub in subelements or ():
                head = sub.split(".", 1)[0]
                if head in instance_ids:
                    owners.append(head)
    return list(dict.fromkeys(owners))


def newest_owner(previous, current, selection, instance_ids, assembly_names=()):
    """The owner of the latest newly selected entry, else the last owner."""
    added = [entry for entry in selection if entry not in previous]
    owners = instance_owners(added, instance_ids, assembly_names)
    if owners:
        return owners[-1]
    return current[-1] if current else None


class AssemblyInstanceLinks:
    def __init__(self, panel):
        self.panel = panel
        self.closed = False
        self.last_selection = ()
        self.owners = ()
        self.timer = QtCore.QTimer(panel)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.sync)

    def allowed(self):
        p = self.panel
        return bool(not self.closed and p.state and p.workspace_mode == "assembly" and not p.core.busy
                    and not p.pending_sketch and not p.selecting_support and not p.studio_selection_callback
                    and not p.active_sketch() and not p.native_feature_task_active()
                    and not p.section_view.picking)

    def schedule(self):
        if not self.closed:
            self.timer.start(0)

    def _instance_ids(self):
        assembly = self.panel.assembly_state() or {}
        return [entry["id"] for entry in assembly.get("instances", [])]

    def _selection(self, doc):
        import FreeCADGui as Gui
        return tuple((entry.ObjectName, tuple(entry.SubElementNames)) for entry in Gui.Selection.getSelectionEx(doc.Name))

    def sync(self):
        if not self.allowed():
            self.last_selection = ()
            return
        doc = self.panel.document()
        if doc is None:
            return
        selection = self._selection(doc)
        ids = self._instance_ids()
        assemblies = {obj.Name for obj in doc.Objects if obj.TypeId == "Assembly::AssemblyObject"}
        owners = instance_owners(selection, ids, assemblies)
        target = newest_owner(self.last_selection, owners, selection, ids, assemblies)
        self.last_selection, self.owners = selection, tuple(owners)
        # Whole-object picks of other rows (a joint clicked in the tree) stay selected.
        items = getattr(self.panel, "items", {})
        others = [name for name, subs in selection if not subs and name in items and name not in owners]
        self._select(self.panel.features, items, owners + others, target)
        self._select(self.panel.parts, self.panel.part_model.items, owners, target)

    @staticmethod
    def _select(tree, items, names, target):
        names = [name for name in names if name in items]
        selected = {item.data(0, QtCore.Qt.UserRole) for item in tree.selectedItems()}
        before = tree.blockSignals(True)
        try:
            if selected != set(names):
                tree.clearSelection()
                for name in names:
                    items[name].setSelected(True)
            if target in names:
                item = items[target]
                ancestor = item.parent()
                while ancestor is not None:
                    ancestor.setExpanded(True)
                    ancestor = ancestor.parent()
                tree.setCurrentItem(item, 0, QtCore.QItemSelectionModel.NoUpdate)
                if not item.isHidden():
                    tree.scrollToItem(item, QtGui.QAbstractItemView.PositionAtCenter)
            elif not names:
                tree.setCurrentItem(None)
        finally:
            tree.blockSignals(before)

    def close(self):
        self.timer.stop()
        self.closed = True
