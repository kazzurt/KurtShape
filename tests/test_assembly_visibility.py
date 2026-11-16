"""Assembly visibility: selection scope and hidden occurrence row presentation."""
from types import SimpleNamespace
import unittest
import support  # noqa: F401
import FreeCAD  # noqa: F401 - bundled PySide compatibility module
from kurtshape.assembly_tree import instance_visibility, visibility_targets
from PySide import QtCore, QtGui
from kurtshape.presentation_icons import hidden_icon, icon_signature


class AssemblyVisibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtGui.QApplication.instance() or QtGui.QApplication([])

    @staticmethod
    def native_icon():
        image = QtGui.QImage(32, 32, QtGui.QImage.Format_ARGB32)
        image.fill(QtCore.Qt.transparent)
        image.setPixelColor(16, 16, QtGui.QColor(20, 80, 240, 255))
        image.setPixelColor(17, 16, QtGui.QColor(10, 20, 30, 128))
        return QtGui.QIcon(QtGui.QPixmap.fromImage(image))

    def test_hidden_icon_is_neutral_and_keeps_alpha_in_selected_and_active_states(self):
        native = self.native_icon()
        hidden = hidden_icon(native)
        self.assertNotEqual(icon_signature(hidden), icon_signature(native))
        for mode in (QtGui.QIcon.Normal, QtGui.QIcon.Selected, QtGui.QIcon.Active, QtGui.QIcon.Disabled):
            for state in (QtGui.QIcon.On, QtGui.QIcon.Off):
                image = hidden.pixmap(QtCore.QSize(32, 32), mode, state).toImage()
                pixel = image.pixelColor(16, 16)
                self.assertEqual(pixel.red(), pixel.green())
                self.assertEqual(pixel.green(), pixel.blue())
                self.assertGreater(pixel.red(), 100)
                self.assertLess(pixel.red(), 200)
                self.assertEqual(pixel.alpha(), 255)
                self.assertEqual(image.pixelColor(17, 16).alpha(), 128)
                self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        self.assertEqual(hidden.cacheKey(), hidden_icon(self.native_icon()).cacheKey())
    def test_no_selection_shows_all_occurrences(self):
        self.assertEqual(visibility_targets(["Left", "Right"], []), ["Left", "Right"])
        self.assertEqual(visibility_targets(["Left", "Right"], [], tree_selection=[]), ["Left", "Right"])

    def test_native_whole_parts_and_assembly_face_paths_show_only_owners(self):
        ids = ["Left", "Right", "Other"]
        self.assertEqual(visibility_targets(ids, [("Left", ())]), ["Left"])
        self.assertEqual(visibility_targets(ids, [("Assembly", ("Right.Face1", "Right.Edge2"))], {"Assembly"}), ["Right"])
        self.assertEqual(visibility_targets(ids, [("Left", ()), ("Right", ("Face2",))]), ["Left", "Right"])

    def test_non_part_selection_never_means_show_all(self):
        ids = ["Left", "Right"]
        for selection in [[("Joint", ())], [("Assembly", ())], [("EmbeddedSource", ())]]:
            self.assertEqual(visibility_targets(ids, selection, {"Assembly"}), [])
        for keys in [["assembly_folder:Frame"], ["assembly_group:instances"], ["Joint"]]:
            self.assertEqual(visibility_targets(ids, [], tree_selection=keys), [])

    def test_focused_tree_keyboard_selection_wins_over_old_native_selection(self):
        self.assertEqual(visibility_targets(["Left", "Right"], [("Left", ())], tree_selection=["Right"]), ["Right"])
        self.assertEqual(visibility_targets(["Left", "Right"], [], tree_selection=["Right", "Left", "Right"]), ["Right", "Left"])
        self.assertEqual(visibility_targets(["Left", "Right"], [("Left", ())], tree_selection=["Joint"]), [])

    def test_hidden_occurrence_is_muted_italic_and_retains_source_notice(self):
        obj = SimpleNamespace(ViewObject=SimpleNamespace(Visibility=False))
        row = instance_visibility({"text": "Left · outdated", "icon": self.native_icon(), "color": "#b7791f", "tooltip": "Left · grounded"}, obj)
        self.assertEqual(row["color"], "#b7791f")
        self.assertEqual(icon_signature(row["icon"]), icon_signature(hidden_icon(self.native_icon())))
        self.assertTrue(row["italic"])
        self.assertEqual(row["text"], "Left · outdated")
        self.assertIn("Hidden", row["tooltip"])
        obj.ViewObject.Visibility = True
        shown = instance_visibility({"text": "Left · outdated", "color": "#b7791f"}, obj)
        self.assertEqual(shown["color"], "#b7791f")
        self.assertFalse(shown.get("italic", False))


if __name__ == "__main__":
    unittest.main()
