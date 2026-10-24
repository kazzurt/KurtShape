"""Assembly UX item 2: selected occurrence geometry maps to instance rows."""
from pathlib import Path
import sys
import unittest

import support  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App  # noqa: F401 — installs the bundled PySide compatibility module.
from kurtshape.assembly_instance_links import AssemblyInstanceLinks, instance_owners, newest_owner

IDS = ["Left", "Right", "Bolt001", "Bolt002"]


class AssemblyInstanceLinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide import QtGui
        cls.app = QtGui.QApplication.instance() or QtGui.QApplication([])

    def test_link_picks_map_to_their_instance_in_selection_order(self):
        selection = [("Right", ("Face6",)), ("Left", ("Edge2", "Vertex1")), ("Right", ("Face1",))]
        self.assertEqual(instance_owners(selection, IDS), ["Right", "Left"])

    def test_assembly_paths_whole_objects_and_strangers(self):
        selection = [("Assembly", ("Bolt002.Face3",)), ("Bolt001", ()), ("Joint", ()),
                     ("Assembly", ("Unknown.Face1", "")), ("Body", ("Face1",))]
        self.assertEqual(instance_owners(selection, IDS, {"Assembly"}), ["Bolt002", "Bolt001"])
        self.assertEqual(instance_owners([], IDS), [])
        self.assertEqual(instance_owners([("Assembly", ("Left.Face1",))], IDS), [])

    def test_newest_owner_follows_the_latest_addition(self):
        previous = (("Left", ("Face1",)),)
        current = (("Left", ("Face1",)), ("Right", ("Face2",)))
        self.assertEqual(newest_owner(previous, ["Left", "Right"], current, IDS), "Right")
        # A removal adds nothing: the last remaining owner stays the target.
        self.assertEqual(newest_owner(current, ["Left"], previous, IDS), "Left")
        self.assertIsNone(newest_owner(current, [], (), IDS))
        # A further face on an already highlighted instance makes it the target again.
        again = current + (("Left", ("Face3",)),)
        self.assertEqual(newest_owner(current, ["Left", "Right"], again, IDS), "Left")

    def tree(self):
        from PySide import QtCore, QtGui
        tree = QtGui.QTreeWidget()
        tree.setSelectionMode(QtGui.QAbstractItemView.ExtendedSelection)
        items = {}
        group = QtGui.QTreeWidgetItem(tree, ["Instances"])
        folder = QtGui.QTreeWidgetItem(group, ["Fasteners"])
        for name, parent in (("Left", group), ("Right", group), ("Bolt001", folder), ("Bolt002", folder)):
            items[name] = QtGui.QTreeWidgetItem(parent, [name])
            items[name].setData(0, QtCore.Qt.UserRole, name)
        signals = []
        tree.itemSelectionChanged.connect(lambda: signals.append(True))
        return tree, items, folder, signals

    def test_select_rows_blocks_signals_and_expands_folders(self):
        from PySide import QtCore
        tree, items, folder, signals = self.tree()
        self.assertFalse(folder.isExpanded())
        AssemblyInstanceLinks._select(tree, items, ["Left", "Bolt002"], "Bolt002")
        self.assertEqual(sorted(i.data(0, QtCore.Qt.UserRole) for i in tree.selectedItems()), ["Bolt002", "Left"])
        self.assertIs(tree.currentItem(), items["Bolt002"])
        self.assertTrue(folder.isExpanded() and folder.parent().isExpanded())
        self.assertEqual(signals, [], "row highlighting must not emit selection commands")
        AssemblyInstanceLinks._select(tree, items, ["Right", "Missing"], None)
        self.assertEqual([i.data(0, QtCore.Qt.UserRole) for i in tree.selectedItems()], ["Right"])
        AssemblyInstanceLinks._select(tree, items, [], None)
        self.assertEqual(tree.selectedItems(), [])
        self.assertIsNone(tree.currentItem())
        self.assertEqual(signals, [])


if __name__ == "__main__":
    unittest.main()
