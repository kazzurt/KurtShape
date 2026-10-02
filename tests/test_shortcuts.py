"""Shortcut behavior: context conflicts, native interception, and input safety."""
import os
from pathlib import Path
import sys
import unittest
import json
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kurtshape.shortcuts import ShortcutRouter, load_registry, normalize_key


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.messages = []
        self.commands = []
        self.context = "part_studio"
        self.router = ShortcutRouter(None, {}, lambda: self.context, self.messages.append,
                                     native_runner=self.commands.append)

    def test_user_override_conflicts_reject_and_perpendicular_keeps_shift_l(self):
        with tempfile.TemporaryDirectory(prefix="shortcut-override-") as folder:
            path = Path(folder) / "shortcuts.user.json"
            path.write_text(json.dumps({"schema_version": 1, "bindings": {"sketch.pierce": "Ctrl+Alt+G"}}))
            registry = load_registry(user_path=path)
            entries = registry["shortcuts"]
            pierce = next(entry for entry in entries if entry["id"] == "sketch.pierce")
            self.assertEqual(pierce["key"], "Ctrl+Alt+G")
            self.assertTrue(pierce["overridden"])
            perpendicular = next(entry for entry in entries if entry["id"] == "sketch.perpendicular")
            self.assertEqual(perpendicular["key"], "Shift+L")
            path.write_text(json.dumps({"schema_version": 1, "bindings": {"sketch.pierce": "Shift+L"}}))
            with self.assertRaises(ValueError):
                load_registry(user_path=path)

    def test_shift_s_retains_all_three_context_meanings(self):
        self.assertEqual(self.router.resolve("Shift+S", "part_studio")["id"], "sketch.start")
        self.assertEqual(self.router.resolve("Shift+S", "sketch")["id"], "sketch.point")
        self.assertEqual(self.router.resolve("Shift+S", "assembly")["id"], "assembly.snap")

    def test_fillet_dispatches_to_correct_native_tool(self):
        self.router.dispatch("Shift+F", "part_studio")
        self.router.dispatch("Shift+F", "sketch")
        self.assertEqual(self.commands, ["PartDesign_Fillet", "Sketcher_CreateFillet"])

    def test_construction_repeated_shortcut_toggles_native_flag(self):
        self.router.dispatch("Q", "sketch")
        self.router.dispatch("Q", "sketch")
        self.assertEqual(self.commands, ["Sketcher_ToggleConstruction"] * 2)

    def test_repeating_circle_exits_tool(self):
        self.router.dispatch("C", "sketch")
        self.router.dispatch("C", "sketch")
        self.assertEqual(self.commands, ["Sketcher_CreateCircle", "Sketcher_StopOperation"])

    def test_context_switch_does_not_cancel_next_sketch_tool(self):
        self.router.dispatch("C", "sketch")
        self.router.dispatch("F", "part_studio")
        self.router.dispatch("C", "sketch")
        self.assertEqual(self.commands[-1], "Sketcher_CreateCircle")

    def test_callbacks_can_defer_to_native_key_handling(self):
        self.router.callbacks["general.cancel"] = lambda: False
        self.assertFalse(self.router.dispatch("Escape", "sketch"))

    def test_registered_unsupported_key_is_not_silent(self):
        self.assertTrue(self.router.dispatch("Shift+G", "sketch"))
        self.assertEqual(self.commands, [])
        self.assertIn("Pierce constraint", self.messages[0])
        self.assertIn("Shift+G", self.messages[0])
        self.assertIn("sketch", self.messages[0])

    def test_failed_callback_reports_action_and_retains_router(self):
        def failure():
            raise RuntimeError("rebuild failed")
        self.router.callbacks["feature.extrude"] = failure
        self.assertTrue(self.router.dispatch("Shift+E"))
        self.assertIn("Extrude: rebuild failed", self.messages)
        self.assertTrue(self.router.dispatch("F"))

    def test_local_file_extensions_do_not_override_other_contexts(self):
        self.assertEqual(self.router.resolve("Ctrl+S", "part_studio")["id"], "local.save")
        self.assertEqual(self.router.resolve("Ctrl+S", "drawing")["id"], "drawing.sheets")
        self.assertEqual(self.router.resolve("Ctrl+S", "feature_studio")["id"], "feature_studio.commit")

    def test_palette_has_one_meaning_per_key_in_current_context(self):
        actions = self.router.available_actions("sketch")
        keys = [normalize_key(e["key"]) for e in actions]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertIn("sketch.point", [e["id"] for e in actions])
        self.assertNotIn("sketch.start", [e["id"] for e in actions])
        self.assertNotIn("assembly.insert", [e["id"] for e in actions])

    def test_all_native_ids_exist_in_pinned_runtime_probe(self):
        import json
        probe = json.loads((ROOT / "validation" / "onshape-shortcuts-command-probe.json").read_text())
        commands = set(probe["workbenches"]["SketcherWorkbench"]["commands"])
        for entry in load_registry()["shortcuts"]:
            if entry.get("native_command"):
                self.assertIn(entry["native_command"], commands)


try:
    import FreeCAD  # Provides the bundled PySide compatibility module.
    from PySide import QtCore, QtGui
    from PySide6 import QtTest
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False


@unittest.skipUnless(QT_AVAILABLE, "Bundled Qt required for physical event routing checks")
class QtRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QtGui.QApplication.instance() or QtGui.QApplication([])

    def setUp(self):
        self.commands, self.messages, self.undo_calls = [], [], []
        self.window = QtGui.QWidget()
        layout = QtGui.QVBoxLayout(self.window)
        self.input = QtGui.QLineEdit()
        self.spin = QtGui.QDoubleSpinBox()
        self.viewport = QtGui.QPushButton("viewport focus target")
        layout.addWidget(self.input)
        layout.addWidget(self.spin)
        layout.addWidget(self.viewport)
        self.window.show()
        self.window.activateWindow()
        self.router = ShortcutRouter(self.app, {"general.undo": lambda: self.undo_calls.append("model")},
                                     lambda: "sketch", self.messages.append, native_runner=self.commands.append)
        self.router.install()
        self.app.processEvents()

    def tearDown(self):
        self.router.uninstall()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def focus(self, widget):
        widget.setFocus()
        self.app.processEvents()

    def test_native_shortcut_collision_is_overridden_once(self):
        native_hits = []
        shortcut = QtGui.QShortcut(QtGui.QKeySequence("C"), self.window)
        shortcut.activated.connect(lambda: native_hits.append("native wrong command"))
        self.focus(self.viewport)
        QtTest.QTest.keyClick(self.viewport, QtCore.Qt.Key_C)
        self.app.processEvents()
        self.assertEqual(self.commands, ["Sketcher_CreateCircle"])
        self.assertEqual(native_hits, [])

    def test_typing_letters_spaces_and_model_keys_does_not_model(self):
        self.focus(self.input)
        QtTest.QTest.keyClicks(self.input, "Circle sketch 42")
        QtTest.QTest.keyClick(self.input, QtCore.Qt.Key_S, QtCore.Qt.ShiftModifier)
        self.assertEqual(self.commands, [])
        self.assertEqual(self.input.text().lower(), "circle sketch 42s")

    def test_text_undo_is_not_model_undo(self):
        self.focus(self.input)
        QtTest.QTest.keyClicks(self.input, "123")
        QtTest.QTest.keyClick(self.input, QtCore.Qt.Key_Z, QtCore.Qt.ControlModifier)
        self.assertEqual(self.undo_calls, [])
        self.assertEqual(self.input.text(), "")
        self.focus(self.viewport)
        QtTest.QTest.keyClick(self.viewport, QtCore.Qt.Key_Z, QtCore.Qt.ControlModifier)
        self.assertEqual(self.undo_calls, ["model"])

    def test_shifted_digit_maps_to_standard_view(self):
        self.focus(self.viewport)
        event = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Exclam,
                               QtCore.Qt.ShiftModifier, "!")
        self.app.sendEvent(self.viewport, event)
        self.assertEqual(self.commands, ["Std_ViewFront"])

    def test_dimension_dialog_keeps_return(self):
        accepted = []
        dialog = QtGui.QDialog(self.window)
        layout = QtGui.QVBoxLayout(dialog)
        field = QtGui.QLineEdit()
        field.returnPressed.connect(lambda: accepted.append("dimension"))
        layout.addWidget(field)
        dialog.show()
        dialog.activateWindow()
        field.setFocus()
        self.app.processEvents()
        self.router.callbacks["general.accept"] = lambda: self.commands.append("wrong finish sketch")
        QtTest.QTest.keyClick(field, QtCore.Qt.Key_Return)
        self.assertEqual(accepted, ["dimension"])
        self.assertEqual(self.commands, [])
        dialog.close()
        dialog.deleteLater()

    def test_palette_owns_arrow_and_escape_without_model_commands(self):
        cancel_calls = []
        self.router.callbacks["general.cancel"] = lambda: cancel_calls.append("wrong cancel")
        self.router.callbacks["view.rotate_down_15"] = lambda: self.commands.append("wrong rotate")
        self.focus(self.viewport)
        observed = []
        def inspect_palette():
            popup = self.app.activePopupWidget()
            observed.append(popup is not None)
            if popup is not None:
                QtTest.QTest.keyClick(popup, QtCore.Qt.Key_Down)
                QtTest.QTest.keyClick(popup, QtCore.Qt.Key_Escape)
        QtCore.QTimer.singleShot(0, inspect_palette)
        self.router.show_palette(self.window)
        self.assertEqual(observed, [True])
        self.assertEqual(cancel_calls, [])
        self.assertEqual(self.commands, [])

    def test_help_typing_and_toggle_do_not_trigger_sketch_tools(self):
        self.focus(self.viewport)
        self.router.show_help(self.window)
        dialog = self.router._dialogs["help"]
        dialog.activateWindow()
        field = dialog.findChild(QtGui.QLineEdit)
        field.setFocus()
        self.app.processEvents()
        QtTest.QTest.keyClicks(field, "circle")
        self.assertEqual(field.text(), "circle")
        self.assertEqual(self.commands, [])
        QtTest.QTest.keyClick(field, QtCore.Qt.Key_Slash, QtCore.Qt.ShiftModifier)
        self.assertFalse(dialog.isVisible())

    def test_right_click_cancellation_allows_same_tool_to_restart(self):
        self.focus(self.viewport)
        QtTest.QTest.keyClick(self.viewport, QtCore.Qt.Key_C)
        QtTest.QTest.mouseClick(self.viewport, QtCore.Qt.RightButton)
        QtTest.QTest.keyClick(self.viewport, QtCore.Qt.Key_C)
        self.assertEqual(self.commands, ["Sketcher_CreateCircle"] * 2)

    def test_file_shortcuts_in_fields_use_application_callbacks_once(self):
        calls, native_calls = [], []
        for name in ("save", "new", "open"):
            self.router.callbacks["local." + name] = lambda name=name: calls.append(name)
        shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+S"), self.window)
        shortcut.activated.connect(lambda: native_calls.append("unsafe native save"))
        for field in (self.input, self.spin):
            self.focus(field)
            for key in (QtCore.Qt.Key_S, QtCore.Qt.Key_N, QtCore.Qt.Key_O):
                QtTest.QTest.keyClick(field, key, QtCore.Qt.ControlModifier)
        self.assertEqual(calls, ["save", "new", "open"] * 2)
        self.assertEqual(native_calls, [])

    def test_modal_field_owns_file_shortcuts(self):
        app_calls, modal_calls = [], []
        self.router.callbacks["local.save"] = lambda: app_calls.append("wrong save")
        dialog = QtGui.QDialog(self.window)
        dialog.setModal(True)
        field = QtGui.QLineEdit(dialog)
        shortcut = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+S"), dialog)
        shortcut.activated.connect(lambda: modal_calls.append("dialog save"))
        dialog.show()
        dialog.activateWindow()
        field.setFocus()
        self.app.processEvents()
        QtTest.QTest.keyClick(field, QtCore.Qt.Key_S, QtCore.Qt.ControlModifier)
        self.assertEqual(app_calls, [])
        self.assertEqual(modal_calls, ["dialog save"])
        dialog.close()
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
