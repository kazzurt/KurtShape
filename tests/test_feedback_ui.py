"""Honest, detailed feedback and owned-dialog keys (slice A/B U7: plan A6, A7)."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kurtshape import feedback
from kurtshape.shortcuts import ShortcutRouter, load_registry


def router_for(registry_path):
    """A headless router (no Qt) holding the registry with the user bindings at ``registry_path``."""
    router = ShortcutRouter(None, {}, lambda: "part_studio", lambda message: None)
    router.registry = load_registry(user_path=registry_path)
    router.entries = router.registry["shortcuts"]
    return router


REMOVE_NOTHING = {"code": "empty_cut", "message": "Change not applied: the Remove removes no material",
                  "feature": "ExtrudeRemove", "validation": "history", "previous_status": "new",
                  "trigger": {"op": "pocket", "feature": "Profile"}}


class FeedbackUiTests(unittest.TestCase):
    # --- A6 / C-03, H-02: error composition -------------------------------------------------

    def test_error_status_names_message_feature_and_code(self):
        composed = feedback.compose_error(REMOVE_NOTHING, {"Profile": "Top profile"})
        self.assertEqual(composed["status"],
                         "Change not applied: the Remove removes no material · ExtrudeRemove · empty_cut")
        self.assertEqual(composed["feature"], "ExtrudeRemove")
        # A rolled-back new feature has no row: the trigger's feature is the next selection candidate.
        self.assertEqual(composed["candidates"], ["ExtrudeRemove", "Profile"])
        lines = composed["message"].splitlines()
        self.assertEqual(lines[0], composed["status"])
        self.assertIn("  while pocket on Top profile", lines)
        self.assertTrue(lines[-1].startswith("  details: "))
        details = dict(REMOVE_NOTHING)
        details.pop("message")
        self.assertEqual(json.loads(lines[-1][len("  details: "):]), details)
        self.assertEqual(composed["message"].count(REMOVE_NOTHING["message"]), 1, "each failure is logged once")

    def test_error_uses_history_names_and_lists_each_failing_feature(self):
        error = {"code": "build_failed", "message": "Change not applied: the unrefined retry could not rebuild native features",
                 "feature": "Cut", "features": [{"feature": "Fillet", "message": "BRep_API: command not done"}, "Cut"],
                 "hint": "Rebuild an earlier refined result with refine:false"}
        composed = feedback.compose_error(error, {"Cut": "Cut 1", "Fillet": "Edge fillet"}, prefix="Plate · ")
        self.assertEqual(composed["status"], "Plate · " + error["message"] + " · Cut 1 · build_failed")
        self.assertEqual(composed["candidates"], ["Cut", "Fillet"])
        self.assertIn("  Edge fillet: BRep_API: command not done", composed["message"].splitlines())
        self.assertIn("  hint: Rebuild an earlier refined result with refine:false", composed["message"].splitlines())

    def test_error_without_its_own_feature_names_the_rejected_request(self):
        error = {"code": "empty_merge_scope", "message": "The result does not touch a part in the selected scope"}
        request = {"id": "ExtrudeRemove", "profile": "Air", "operation": "remove", "document_id": "doc"}
        composed = feedback.compose_error(error, {"Air": "Air"}, request=request)
        self.assertEqual(composed["status"], error["message"] + " · ExtrudeRemove · empty_merge_scope")
        self.assertEqual(composed["candidates"], ["ExtrudeRemove", "Air"])
        # The error's own names come first; the request only adds what is missing.
        self.assertEqual(feedback.failing_features(REMOVE_NOTHING, {"id": "ExtrudeRemove", "profile": "Profile"}),
                         ["ExtrudeRemove", "Profile"])

    def test_error_without_a_feature_keeps_message_and_code(self):
        composed = feedback.compose_error({"code": "stale_revision", "message": "Document changed"})
        self.assertEqual(composed["status"], "Document changed · stale_revision")
        self.assertIsNone(composed["feature"])
        self.assertEqual(feedback.compose_error({"message": "boom"})["status"], "boom · operation_failed")

    # --- A6 / A-10: status wording per state ------------------------------------------------

    def state(self, status, features=(), **extra):
        rows = [{"id": "Body", "name": "Body", "type": "PartDesign::Body"}] + [
            {"id": name, "name": name + " name", "type": kind} for name, kind in features]
        return dict({"build_status": status, "features": rows, "measurements": None}, **extra)

    def test_status_wording_for_each_document_state(self):
        sketch = [("Sketch", "Sketcher::SketchObject")]
        solid = {"solid_count": 1, "volume_mm3": 4800.0}
        cases = [
            (self.state("sketch_only"), ("Empty part · mm", "")),
            (self.state("sketch_only", sketch), ("Sketches only · mm", "")),
            (self.state("needs_rebuild", sketch, active_sketch_edit="Sketch"), ("Editing sketch · mm", "")),
            (self.state("valid", sketch, active_sketch_edit="Sketch", measurements=solid), ("Editing sketch · mm", "")),
            (self.state("needs_rebuild", sketch), ("Rebuild required · pending model changes", "warning")),
            (self.state("needs_rebuild", sketch, rebuild_reason="engine_changed"),
             ("Rebuild required · geometry engine changed", "warning")),
            (self.state("valid", sketch, measurements=solid), ("1 solid(s) · 4,800.00 mm³", "")),
            (self.state("valid", sketch, measurements={"solid_count": 1}), ("1 solid(s)", "")),
            (self.state("valid", sketch, measurements=solid, geometry_check="valid"), ("1 solid(s) · 4,800.00 mm³ · checked", "")),
            (self.state("failed", [("Pad", "PartDesign::Pad")], build_errors=[{"feature": "Pad", "message": "Pad: Resulting shape is not a solid"}]),
             ("Build failed · Pad name: Pad: Resulting shape is not a solid", "error")),
            (self.state("failed", [("Pad", "PartDesign::Pad")], result_checks={"failed": [{"feature": "Pad", "code": "empty_add"}]}),
             ("Result check failed · Pad name · empty_add — see Messages", "error")),
            (self.state("failed", [("Pad", "PartDesign::Pad")], geometry_check="invalid",
                        build_errors=[{"feature": "Pad", "message": "Invalid solid"}]),
             ("Invalid geometry · Pad name — see Messages", "error")),
            (self.state("failed"), ("Build failed — see Messages", "error")),
        ]
        for state, expected in cases:
            with self.subTest(state=state):
                self.assertEqual(feedback.status_text(state), expected)
        # A failure outranks the sketch edit; checks pending still shows on the sketches-only line.
        failed_while_editing = self.state("failed", sketch, active_sketch_edit="Sketch",
                                          build_errors=[{"feature": "Sketch", "message": "Over-constrained"}])
        self.assertTrue(feedback.status_text(failed_while_editing)[0].startswith("Build failed · Sketch name"))
        pending = self.state("sketch_only", sketch, result_checks={"status": "pending"})
        self.assertEqual(feedback.status_text(pending)[0], "Sketches only · mm · checks pending")

    # --- A6 / A-05: hover labels show every key from the registry ---------------------------

    def test_hover_labels_show_single_keys_from_the_registry(self):
        entries = router_for(Path(support.TEST_TMP) / "no-user-shortcuts.json")
        cases = [("sketch", "Line", "Sketcher_CreatePolyline", "L"), ("sketch", "Rectangle", "Sketcher_CreateRectangle", "G"),
                 ("sketch", "Dimension", "Sketcher_Dimension", "D"), ("sketch", "Use", "Sketcher_Projection", "U"),
                 ("sketch", "Point", "Sketcher_CreatePoint", "Shift+S"), ("sketch", "Spline", "Sketcher_CreateBSpline", ""),
                 ("part_studio", "Sketch", "Sketcher_NewSketch", "Shift+S"), ("part_studio", "Fit", "Std_ViewFitAll", "F"),
                 # "Normal" carries the Std_ViewTop icon; its action is view.normal (N), not Top (Shift+5).
                 ("part_studio", "Normal", "Std_ViewTop", "N"), ("part_studio", "Show planes", "PartDesign_Plane", "P"),
                 ("part_studio", "Fillet", "PartDesign_Fillet", "Shift+F"), ("part_studio", "Rebuild", "Std_Refresh", ""),
                 ("assembly", "Insert", None, "I"), ("assembly", "Joints", None, "J"), ("assembly", "Fixed", None, "M"),
                 ("part_studio", "Save", None, "Ctrl+S")]
        for context, label, command, key in cases:
            with self.subTest(label=label, context=context):
                self.assertEqual(feedback.tool_shortcut(entries, context, label, command), key)
        # Shadowing: in a sketch Shift+S places a point, so Start sketch shows no key there.
        self.assertEqual(feedback.registry_shortcut(entries, "sketch", action="sketch.start"), "")
        self.assertEqual(feedback.registry_shortcut(entries, "part_studio", action="general.accept"), "Enter")
        self.assertEqual(feedback.registry_shortcut(entries, "part_studio", action="general.cancel"), "Escape")

    def test_hover_labels_follow_a_rebinding(self):
        with tempfile.TemporaryDirectory(prefix="feedback-shortcuts-", dir=support.TEST_TMP, ignore_cleanup_errors=True) as folder:
            path = Path(folder) / "shortcuts.user.json"
            path.write_text(json.dumps({"schema_version": 1, "bindings": {"sketch.line": "Shift+Alt+L", "view.fit": "Ctrl+Alt+F"}}))
            entries = router_for(path)
        self.assertEqual(feedback.tool_shortcut(entries, "sketch", "Line", "Sketcher_CreatePolyline"), "Alt+Shift+L")
        self.assertEqual(feedback.tool_shortcut(entries, "part_studio", "Fit", "Std_ViewFitAll"), "Ctrl+Alt+F")
        self.assertEqual(feedback.tool_shortcut(entries, "sketch", "Rectangle", "Sketcher_CreateRectangle"), "G")

    def test_toolbar_label_reads_a_callable_shortcut_when_shown(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import FreeCAD  # noqa: F401  # provides the bundled PySide compatibility module
        from PySide import QtGui
        from kurtshape.toolbar_labels import ToolbarLabels
        app = QtGui.QApplication.instance() or QtGui.QApplication([])
        main = QtGui.QMainWindow()
        labels = ToolbarLabels(main)
        try:
            button = QtGui.QToolButton(main)
            current = ["L"]
            labels.register(button, "Line", lambda: current[0])
            self.assertEqual(labels.text_for(button), "Line  (L)")
            current[0] = "Alt+Shift+L"
            self.assertEqual(labels.text_for(button), "Line  (Alt+Shift+L)")
            labels.register(button, "Spline", "")
            self.assertEqual(labels.text_for(button), "Spline")
        finally:
            labels.close()
            main.deleteLater()
            app.processEvents()

    # --- A6 / A-08: Messages dot counts warnings and errors that arrived while hidden --------

    def test_messages_dot_counts_only_warnings_and_errors_while_hidden(self):
        unread = feedback.UnreadMessages()
        unread.add("error")  # startup backlog: neither unread nor an alert
        unread.add("info")
        self.assertEqual((unread.count, unread.alerts, unread.button_text()), (0, 0, "Messages"))
        unread.end_startup()
        unread.add("info")
        unread.add("info")
        self.assertEqual((unread.count, unread.dot, unread.button_text()), (2, False, "Messages"))
        self.assertEqual(unread.tooltip(False), "Show messages · 2 unread")
        unread.add("warning", visible=True)  # read as it arrived
        self.assertFalse(unread.dot)
        unread.add("warning")
        unread.add("error")
        self.assertEqual((unread.count, unread.alerts, unread.button_text()), (4, 2, "Messages •"))
        self.assertEqual(unread.tooltip(False), "Show messages · 4 unread · 2 warnings or errors")
        self.assertEqual(unread.tooltip(True), "Hide messages")
        unread.seen()
        self.assertEqual((unread.count, unread.alerts, unread.button_text()), (0, 0, "Messages"))
        # A native line is counted on arrival and lights the dot once its report color says warning.
        self.assertTrue(unread.add("info"))
        unread.escalate("info")
        self.assertFalse(unread.dot)
        unread.escalate("warning")
        self.assertEqual((unread.count, unread.alerts), (1, 1))
        unread.seen()
        unread.escalate("error")  # nothing unread any more
        self.assertFalse(unread.dot)
        self.assertFalse(unread.add("error", visible=True))

    def test_native_report_severity_comes_from_the_report_colors(self):
        error, warning = "#bd3039", "#8c6005"
        self.assertEqual(feedback.native_severity({"#BD3039"}, error, warning), "error")
        self.assertEqual(feedback.native_severity({"#22262b", "#8c6005"}, error, warning), "warning")
        self.assertEqual(feedback.native_severity({"#22262b"}, error, warning), "info")
        self.assertEqual(feedback.native_severity((), error, warning), "info")

    # --- A7 / C-04: Enter and Shift+Enter in an owned dialog ---------------------------------

    def test_enter_and_shift_enter_confirm_an_owned_dialog_through_its_gate(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import FreeCAD  # noqa: F401  # provides the bundled PySide compatibility module
        from PySide import QtCore, QtGui
        from PySide6 import QtTest
        from kurtshape.feature_panel import FeaturePanel, ReferencePicker
        app = QtGui.QApplication.instance() or QtGui.QApplication([])
        main = QtGui.QMainWindow()
        main.setCentralWidget(QtGui.QWidget())
        panel = FeaturePanel("Fillet", main)
        layout = QtGui.QVBoxLayout(panel.content)
        line, spin, combo, check = QtGui.QLineEdit(), QtGui.QDoubleSpinBox(), QtGui.QComboBox(), QtGui.QCheckBox("Keep")
        combo.addItems(["New", "Add"])
        picker = ReferencePicker("Select edges")
        for widget in (line, spin, combo, check, picker):
            layout.addWidget(widget)
        main.addDockWidget(QtCore.Qt.RightDockWidgetArea, panel)
        accepted, repeated = [], []
        panel.accepted.connect(lambda: accepted.append(True))
        main.show()
        app.processEvents()

        def press(widget, shift=False):
            widget.setFocus()
            app.processEvents()
            QtTest.QTest.keyClick(widget, QtCore.Qt.Key_Return, QtCore.Qt.ShiftModifier if shift else QtCore.Qt.NoModifier)
            app.processEvents()

        try:
            press(line)
            self.assertEqual(accepted, [], "Enter must respect the Confirm gate")
            panel.set_accept_enabled(True)
            for widget in (line, spin, combo, check):
                with self.subTest(widget=type(widget).__name__):
                    before = len(accepted)
                    press(widget)
                    self.assertEqual(len(accepted), before + 1)
            press(spin, shift=True)  # no repeat: Shift+Enter confirms
            self.assertEqual(len(accepted), 5)
            panel.repeat = lambda: repeated.append(True)
            press(line, shift=True)
            self.assertEqual((len(accepted), len(repeated)), (5, 1))
            press(picker.pick)
            press(picker.items)
            self.assertEqual((len(accepted), len(repeated)), (5, 1), "a reference picker keeps Enter")
            # The one entry point the shell's filter also calls: False hands Return to an open list.
            self.assertTrue(panel.enter_pressed(line))
            self.assertEqual(len(accepted), 6)
            self.assertTrue(panel.enter_pressed(picker.items))  # taken, not confirmed
            self.assertEqual(len(accepted), 6)
            self.assertTrue(panel.enter_pressed(check, shift=True))
            self.assertEqual((len(accepted), len(repeated)), (6, 2))
            combo.showPopup()
            app.processEvents()
            self.assertTrue(combo.view().isVisible())
            self.assertFalse(panel.enter_pressed(combo.view()), "an open combo box list keeps Enter")
            self.assertFalse(panel.enter_pressed(combo))
            self.assertEqual((len(accepted), len(repeated)), (6, 2))
            combo.hidePopup()
            app.processEvents()
            panel.reject()
            press(line)
            self.assertEqual(len(accepted), 6, "a rejected editor never confirms")
        finally:
            main.close()
            main.deleteLater()
            app.processEvents()


if __name__ == "__main__":
    unittest.main()
