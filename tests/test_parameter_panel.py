"""Parameters section widgets, commit state machine and layout persistence (offscreen Qt).

Contract 3.2 feature 3b. The widget layer is exercised through a FakeAdapter that
records calls, returns scripted outcomes and serves rows in the 3a shape
(``native_value``, ``native_unit``, ``expression_ref``). Backend translation
against a headless Controller is ParameterAdapterTranslationTests (added with the
parameters backend). Tests assert layout relations, never prototype pixel values,
and in-process tests never call ``App.saveParameter``: they use a dict store.
"""
import copy
import hashlib
import json
import math
import os
import re
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import FreeCAD  # noqa: F401 -- provides the bundled PySide compatibility imports.
from PySide import QtCore, QtGui
from PySide6 import QtTest
import shiboken6

import support
from kurtshape import parameter_panel as pp
from kurtshape import theme

# The name rule belongs to the backend (parameters.NAME_PATTERN, Contract 3.2 C28).
# The widget layer never owns it; the fake injects it the way the real adapter does.
NAME_PATTERN = r"^[a-z][A-Za-z0-9_]{0,63}$"
NATIVE_TYPES = {"length": "App::PropertyDistance", "angle": "App::PropertyAngle", "number": "App::PropertyFloat"}
NATIVE_UNITS = {"length": "mm", "angle": "deg", "number": ""}
WIRE_UNITS = {"length": "mm", "angle": "rad", "number": ""}
EDITING = pp.ControllerParameterAdapter.EDITING
PARAMETER_RULES = """
QWidget#KurtShapeParameterHeader { background: %(chrome)s; }
QToolButton#KurtShapeAddParameter { color: %(ink)s; font-size: 15px; font-weight: 600; min-width: 18px; min-height: 18px; padding: 0 5px; }
QToolButton#KurtShapeAddParameter:disabled { background: transparent; border-color: transparent; }
QLineEdit#KurtShapeParameterValue { background: transparent; border-color: transparent; padding: 1px 3px; min-height: 16px; }
QLineEdit#KurtShapeParameterValue:focus { background: %(surface)s; border-color: %(accent)s; }
QLineEdit#KurtShapeParameterValue[validation="pending"] { background: %(surface)s; border-color: %(warning)s; }
QLineEdit#KurtShapeParameterValue[validation="invalid"] { background: %(surface)s; border-color: %(error)s; }
QLineEdit#KurtShapeParameterValue[stale="true"] { color: %(disabled_ink)s; }
QLabel#KurtShapeParameterEmpty { color: %(muted)s; background: %(surface)s; }
QLabel#KurtShapeParameterError, QLabel#KurtShapeParameterState { background: %(surface)s; }
"""


def make_row(name, kind, native, expression=None, **extra):
    """A compact inspect row in the 3a shape (params_backend §6.1/§6.6)."""
    row = {"name": name, "type": kind, "unit": WIRE_UNITS.get(kind, ""),
           "value": math.radians(native) if kind == "angle" else native,
           "native_value": native, "native_unit": NATIVE_UNITS.get(kind, ""), "expression": expression,
           "expression_ref": "Params." + name, "native_type": NATIVE_TYPES.get(kind, "App::PropertyString"),
           "status": "valid", "error": None, "used_by_count": 0}
    row.update(extra)
    return row


def default_rows():
    return [make_row("chamfer_angle", "angle", 30.0), make_row("flute_count", "number", 2.0),
            make_row("shaft_diameter", "length", 10.0),
            make_row("shoulder_diameter", "length", 12.0, "shaft_diameter + 2 mm")]


UP_TO_DATE = {"id": "Params", "label": "Params", "state": ["Up-to-date"], "error": None}


class FakeAdapter(pp.ParameterAdapter):
    """Records writes, scripts failures and mimics Panel.operation's refresh on success.

    Like core (through Panel._operation's staged ``expected_revision``), a value
    edit carrying a revision other than the current one is refused with
    ``stale_revision`` before anything changes.
    """

    def __init__(self, rows=None):
        self.state = {"document_id": "doc-1", "revision": "rev-1", "managed": True,
                      "parameters": default_rows() if rows is None else rows,
                      "parameter_set": dict(UP_TO_DATE), "build_errors": []}
        self.available = True
        self.blocked = None
        self.rolled = False
        self.pattern = NAME_PATTERN
        self.calls = []
        self.notes = []
        self.shown = []
        self.failures = []
        self.usages = {}
        self.usage_reads = 0
        self.stored = {}
        self.formulas = {"shoulder_diameter": lambda values: values["shaft_diameter"] + 2}
        self.section = None
        self.revisions = 1

    # reads
    def key(self):
        if not self.available:
            return None
        state = copy.deepcopy(self.state)
        return state["document_id"], state["managed"], state["parameters"], self.set_state_from(state)

    def revision(self):
        return self.state["revision"]

    def blocker(self):
        if not self.available:
            return pp.NO_DOCUMENT
        if not self.state["managed"]:
            return pp.ControllerParameterAdapter.REFERENCE
        return self.blocked

    def name_pattern(self):
        return self.pattern

    def rolled_back(self):
        return self.rolled

    def usage(self, name):
        self.usage_reads += 1
        return copy.deepcopy(self.usages.get(name, {"used_by": [], "used_by_parameters": [], "affects": [], "parts": []}))

    def notify(self, message, severity=None):
        self.notes.append((message, severity))

    def show_use(self, feature, parameter):
        self.shown.append((feature, parameter))

    # writes
    def set_value(self, name, request, tokens):
        self.calls.append(("edit_parameter", {"name": name, **request.args()}, dict(tokens)))
        expected = tokens.get("_expected_revision")
        if expected is not None and expected != self.state["revision"]:
            return self.translate({"code": "stale_revision",
                                   "message": "The document changed since this request was prepared"})
        return self._write(lambda: self._edit(name, request.args()))

    def create(self, name, kind, request, tokens):
        self.calls.append(("create_parameter", {"name": name, "type": kind, **request.args()}, dict(tokens)))
        return self._write(lambda: self._create(name, kind, request.args()))

    def rename(self, name, new_name, tokens):
        self.calls.append(("rename_parameter", {"name": name, "new_name": new_name}, dict(tokens)))
        return self._write(lambda: self._rename(name, new_name))

    def delete(self, name, keep_values, tokens):
        self.calls.append(("delete_parameter", {"name": name, "freeze_consumers": keep_values}, dict(tokens)))
        return self._write(lambda: self._remove(name))

    def _write(self, change):
        if self.failures:
            return self.translate(self.failures.pop(0))  # Panel._operation: no refresh on failure
        change()
        self.bump()
        if self.section is not None:
            self.section.refresh()  # Panel._operation refreshes after a successful op
        return pp.Outcome(True)

    # backend model
    def bump(self):
        self.revisions += 1
        self.state["revision"] = f"rev-{self.revisions}"

    def find(self, name):
        return next(row for row in self.state["parameters"] if row["name"] == name)

    @staticmethod
    def native(kind, value):
        if isinstance(value, (int, float)):
            return float(value)
        quantity = FreeCAD.Units.Quantity(value)
        if kind == "length":
            return float(quantity.getValueAs("mm"))
        if kind == "angle":
            return float(quantity.getValueAs("deg"))
        return float(quantity.Value)

    def evaluate(self):
        values = {row["name"]: row["native_value"] for row in self.state["parameters"]}
        for row in self.state["parameters"]:
            formula = self.formulas.get(row["name"])
            if row.get("expression") and formula:
                row["native_value"] = values[row["name"]] = float(formula(values))

    def _edit(self, name, args):
        row = self.find(name)
        if args.get("expression") is not None:
            row["expression"] = args["expression"]
        else:
            if "expression" in args:
                row["expression"] = None
            if "value" in args:
                value = self.native(row["type"], args["value"])
                row["native_value"] = self.stored.get(name, lambda stored: stored)(value)
        self.evaluate()

    def _create(self, name, kind, args):
        value = self.native(kind, args["value"]) if "value" in args else 0.0
        self.state["parameters"].append(make_row(name, kind, value, args.get("expression")))
        self.state["parameters"].sort(key=lambda row: row["name"].lower())

    def _rename(self, name, new_name):
        row = self.find(name)
        row.update(name=new_name, expression_ref="Params." + new_name)
        self.state["parameters"].sort(key=lambda row: row["name"].lower())

    def _remove(self, name):
        self.state["parameters"] = [row for row in self.state["parameters"] if row["name"] != name]

    def external(self, name, native):
        """A bridge or native change made elsewhere (no Panel refresh yet)."""
        self.find(name)["native_value"] = float(native)
        self.evaluate()
        self.bump()

    def switch_document(self, document_id, rows):
        self.state.update(document_id=document_id, parameters=rows)
        self.bump()


class FakeMessageBox:
    """Stands in for QMessageBox: records the prompt and answers without a nested loop."""
    Warning = QtGui.QMessageBox.Warning
    AcceptRole = QtGui.QMessageBox.AcceptRole
    Cancel = QtGui.QMessageBox.Cancel
    instances = []
    choice = "cancel"
    during = None

    def __init__(self, parent=None):
        self.text = ""
        self.title = ""
        self.buttons = []
        self.clicked = None
        FakeMessageBox.instances.append(self)

    def setIcon(self, icon):
        self.icon = icon

    def setWindowTitle(self, title):
        self.title = title

    def setText(self, text):
        self.text = text

    def addButton(self, button, role=None):
        token = object()
        self.buttons.append((button, token))
        return token

    def setDefaultButton(self, button):
        self.default = button

    def exec(self):
        if FakeMessageBox.during is not None:
            FakeMessageBox.during()
        self.clicked = self.buttons[0][1] if FakeMessageBox.choice == "delete" else self.buttons[1][1]
        return 0

    def clickedButton(self):
        return self.clicked


USAGE_ROW = {"name": "shaft_diameter", "used_by_parameters": ["shoulder_diameter"],
             "used_by": [{"feature": "ShaftSk", "native_feature": "ShaftSk", "parameter": "Diameter",
                          "path": ".Constraints.Diameter", "expression": "Params.shaft_diameter"},
                         {"feature": "Tip", "native_feature": "Tip", "parameter": None, "path": ".Length",
                          "expression": "Params.shaft_diameter * 2"}],
             "affects": {"features": ["ShaftSk", "Shaft"], "parts": ["p1", "p2"]}}


class FakePanel:
    """Just enough Panel for ControllerParameterAdapter; no backend, no FreeCADGui."""

    def __init__(self):
        self.state = {"document_id": "doc-1", "revision": "r1", "managed": True, "parameters": default_rows(),
                      "parameter_set": dict(UP_TO_DATE), "build_errors": [],
                      "features": [{"id": "ShaftSk", "name": "Shaft sketch", "rolled_back": False},
                                   {"id": "Shaft", "name": "Shaft", "rolled_back": False},
                                   {"id": "Tip", "name": "Tip", "rolled_back": True}],
                      "studio": {"feature_order": ["ShaftSk", "Shaft", "Tip"], "rollback_index": 2,
                                 "parts": [{"id": "p1", "name": "Body"}, {"id": "p2", "name": "Shank"}]}}
        self.workspace_mode = "part_studio"
        self.doc = object()
        self.sketch = self.task = self.studio_dialog = None
        self.pending_sketch = self.selecting_support = self.native_task = False
        self.dispatched = []
        self.core = type("Core", (), {})()
        self.core.busy = False
        self.core.dispatch = self.dispatch
        self.message = QtGui.QLabel("Roll forward first")
        self.operations, self.notes, self.responses = [], [], []
        self.last_operation_error = None
        self.shown = None

    def document(self):
        return self.doc

    def active_sketch(self):
        return self.sketch

    def native_feature_task_active(self):
        return self.native_task

    def operation(self, op, **args):
        self.operations.append((op, args))
        response = self.responses.pop(0) if self.responses else None
        if response is None:
            return self.state
        if isinstance(response, dict):
            self.last_operation_error = response
        return None

    def notify(self, message, *args):
        self.notes.append((message,) + args)

    def show_parameter_use(self, feature, parameter):
        self.shown = (feature, parameter)

    def dispatch(self, request):
        self.dispatched.append(request)
        return {"ok": True, "result": {"document_id": "doc-1", "parameters": [USAGE_ROW]}}


class DictStore:
    def __init__(self, text=""):
        self.text = text
        self.writes = []

    def get(self):
        return self.text

    def set(self, text):
        self.text = text
        self.writes.append(text)


class QtFixture:
    """Plain mixin (not a TestCase): one shown host window per test, cleaned up after."""

    @classmethod
    def setUpClass(cls):
        cls.app = QtGui.QApplication.instance() or QtGui.QApplication([])

    def pump(self, times=4):
        for _ in range(times):
            self.app.processEvents()

    def wait(self, milliseconds):
        QtTest.QTest.qWait(milliseconds)

    def show_host(self, host):
        host.show()
        host.activateWindow()
        QtTest.QTest.qWaitForWindowActive(host, 3000)
        self.pump()

    def make_section(self, adapter=None, height=420, stylesheet=False):
        self.adapter = adapter or FakeAdapter()
        self.host = QtGui.QWidget()
        self.host.setObjectName("ParameterPanelTestHost")
        self.host.resize(300, height)
        if stylesheet:
            self.host.setStyleSheet(theme.STYLESHEET + PARAMETER_RULES % theme.COLORS)
        layout = QtGui.QVBoxLayout(self.host)
        layout.setContentsMargins(0, 0, 0, 0)
        self.section = pp.ParameterSection(self.adapter)
        self.adapter.section = self.section
        layout.addWidget(self.section, 1)
        self.other = QtGui.QLineEdit("elsewhere")
        self.other.setObjectName("OtherField")
        layout.addWidget(self.other)
        self.addCleanup(self.dispose)
        self.section.refresh()
        self.show_host(self.host)
        return self.section

    def destroy(self, widget):
        """Delete now, not later: the native child shares one QApplication, and a
        closed but live widget can stay Qt's last widget under the mouse, which
        changes cursor-event delivery for later classes (test_sketch_cursor)."""
        if shiboken6.isValid(widget):
            widget.close()
            widget.deleteLater()
        self.app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        self.pump()

    def dispose(self):
        FakeMessageBox.instances, FakeMessageBox.during, FakeMessageBox.choice = [], None, "cancel"
        if shiboken6.isValid(self.section):
            self.section.close()
        QtGui.QToolTip.hideText()
        self.destroy(self.host)

    def field(self, name):
        return self.section.rows[name].field

    def focus(self, widget, reason=QtCore.Qt.OtherFocusReason):
        widget.setFocus(reason)
        self.pump()
        self.assertTrue(widget.hasFocus(), "offscreen focus did not reach " + widget.objectName())

    def move_focus(self, widget, reason):
        """Focus moves synchronously; the event loop (and any scheduled commit) does not run."""
        widget.setFocus(reason)
        self.assertTrue(widget.hasFocus(), "offscreen focus did not reach " + widget.objectName())

    def edit(self, name, text):
        field = self.field(name)
        self.focus(field)
        field.selectAll()
        QtTest.QTest.keyClicks(field, text)
        self.assertTrue(field.edited)
        self.assertEqual(field.text(), text)
        return field

    def enter(self, field):
        QtTest.QTest.keyClick(field, QtCore.Qt.Key_Return)
        self.pump()

    def focus_out(self, field, reason):
        QtGui.QApplication.sendEvent(field, QtGui.QFocusEvent(QtCore.QEvent.FocusOut, reason))
        self.pump()

    def post_key(self, widget, key):
        """Queue a key press and release, as input typed ahead while the GUI is busy is queued."""
        for kind in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            QtCore.QCoreApplication.postEvent(widget, QtGui.QKeyEvent(kind, key, QtCore.Qt.NoModifier))

    def help_event(self, widget, point):
        """The ToolTip help event Qt sends on hover."""
        QtGui.QApplication.sendEvent(widget, QtGui.QHelpEvent(QtCore.QEvent.ToolTip, point, widget.mapToGlobal(point)))
        self.pump()

    def edits(self):
        return [call for call in self.adapter.calls if call[0] == "edit_parameter"]

    def notes(self):
        return [message for message, _ in self.adapter.notes]


class ParameterPanelTests(QtFixture, unittest.TestCase):
    # -- presentation ------------------------------------------------------

    def test_rows_show_name_value_and_unit_for_each_kind(self):
        section = self.make_section()
        self.assertEqual(section.order, ["chamfer_angle", "flute_count", "shaft_diameter", "shoulder_diameter"])
        self.assertEqual(section.title.text(), "Parameters (4)")
        self.assertTrue(section.tree.isVisible())
        self.assertFalse(section.empty.isVisible())
        expected = {"shaft_diameter": ("10", "mm"), "chamfer_angle": ("30", "°"), "flute_count": ("2", "")}
        for name, (value, unit) in expected.items():
            entry = section.rows[name]
            self.assertEqual(entry.item.text(0), name)
            self.assertEqual(entry.field.text(), value, name)
            self.assertEqual(entry.item.text(2), unit, name)
            self.assertEqual(entry.field.accessibleName(), name + " value")
            self.assertEqual(entry.field.objectName(), "KurtShapeParameterValue")
        self.assertIsNone(section.rows["shaft_diameter"].field.formula_action)
        self.assertEqual(section.tree.objectName(), "KurtShapeParameters")
        self.assertEqual(section.tree.columnCount(), 3)
        self.assertTrue(section.tree.isHeaderHidden())
        self.assertEqual(section.created, 4)

    def test_formula_row_shows_value_unfocused_and_formula_focused(self):
        self.make_section()
        field = self.field("shoulder_diameter")
        self.assertEqual(field.text(), "12")
        self.assertIsNotNone(field.formula_action)
        self.assertEqual(field.formula_action.toolTip(), pp.FORMULA_NOTE)
        self.focus(field)
        self.assertEqual(field.text(), "=shaft_diameter + 2 mm")
        self.assertEqual(field.selectedText(), "=shaft_diameter + 2 mm")
        self.focus(self.other, QtCore.Qt.MouseFocusReason)
        self.assertEqual(field.text(), "12")
        self.assertEqual(self.adapter.calls, [])

    def test_unsupported_row_is_read_only_with_native_type_tooltip(self):
        rows = default_rows() + [make_row("zlabel", "string", 0.0, native_type="App::PropertyString", native_unit="")]
        section = self.make_section(FakeAdapter(rows))
        field = self.field("zlabel")
        self.assertTrue(field.isReadOnly())
        self.assertFalse(self.field("shaft_diameter").isReadOnly())
        self.assertIn("Unsupported native type App::PropertyString", section.tooltip("zlabel"))

    def test_value_column_width_follows_the_widest_value_within_bounds(self):
        section = self.make_section()
        header = section.tree.header()
        narrow = header.sectionSize(1)
        self.assertGreaterEqual(narrow, pp.VALUE_MIN_WIDTH)
        self.assertEqual(header.sectionSize(2), pp.UNIT_WIDTH)
        self.adapter.external("shaft_diameter", 123456.125)
        section.refresh()
        self.pump()
        wide = header.sectionSize(1)
        self.assertGreater(wide, narrow)
        self.assertLessEqual(wide, max(pp.VALUE_MIN_WIDTH, int(section.tree.viewport().width() * pp.VALUE_MAX_FRACTION)))
        # A value wider than its share is clipped to 45 % of the viewport.
        self.adapter.external("shaft_diameter", 1.2345678901234567e40)
        section.refresh()
        self.pump()
        ceiling = int(section.tree.viewport().width() * pp.VALUE_MAX_FRACTION)
        text = self.field("shaft_diameter").display_text
        self.assertGreater(section.tree.fontMetrics().horizontalAdvance(text) + pp.VALUE_PADDING, ceiling, text)
        self.assertGreater(ceiling, pp.VALUE_MIN_WIDTH)
        self.assertEqual(header.sectionSize(1), ceiling)

    # -- commit boundaries -------------------------------------------------

    def test_typing_never_dispatches_and_enter_commits_once(self):
        self.make_section()
        field = self.edit("shaft_diameter", "12")
        self.pump()
        self.assertEqual(self.adapter.calls, [])
        QtTest.QTest.keyClick(field, QtCore.Qt.Key_Return)
        self.assertEqual(self.adapter.calls, [], "the commit is decided now and dispatched from the event loop")
        self.pump()
        self.assertEqual(self.edits(), [("edit_parameter", {"name": "shaft_diameter", "value": "12.0 mm"},
                                         {"_document_id": "doc-1", "_expected_revision": "rev-1"})])
        self.assertFalse(field.edited)
        self.assertEqual(field.text(), "12")
        self.assertEqual(self.field("shoulder_diameter").text(), "14")
        # A focus move after the commit ran sends nothing more (input queued before it runs:
        # test_return_then_queued_focus_move_commits_once).
        self.focus(self.other, QtCore.Qt.MouseFocusReason)
        self.enter(field)
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertEqual(field.text(), "12")

    def test_programmatic_text_swap_is_not_an_edit(self):
        self.make_section()
        field = self.field("shoulder_diameter")
        self.focus(field)
        self.assertEqual(field.text(), "=shaft_diameter + 2 mm")
        self.assertFalse(field.edited)
        self.focus(self.other, QtCore.Qt.MouseFocusReason)
        self.assertEqual(self.adapter.calls, [])
        self.assertFalse(field.edited)
        self.assertEqual(field.text(), "12")

    def test_mouse_and_tab_focus_out_commit_once(self):
        self.make_section()
        field = self.edit("flute_count", "3")
        self.focus(self.other, QtCore.Qt.MouseFocusReason)
        self.assertEqual([call[1] for call in self.edits()], [{"name": "flute_count", "value": 3.0}])
        self.assertEqual(field.text(), "3")
        self.edit("flute_count", "4")
        self.focus(self.other, QtCore.Qt.TabFocusReason)
        self.assertEqual([call[1]["value"] for call in self.edits()], [3.0, 4.0])
        for reason, value in ((QtCore.Qt.BacktabFocusReason, "5"), (QtCore.Qt.ShortcutFocusReason, "6")):
            self.edit("flute_count", value)
            self.focus(self.other, reason)
        self.assertEqual([call[1]["value"] for call in self.edits()], [3.0, 4.0, 5.0, 6.0])
        # Down moves to the next field with TabFocusReason, which commits too.
        shaft = self.edit("shaft_diameter", "11")
        QtTest.QTest.keyClick(shaft, QtCore.Qt.Key_Down)
        self.pump()
        self.assertTrue(self.field("shoulder_diameter").hasFocus())
        self.assertEqual(self.edits()[-1][1], {"name": "shaft_diameter", "value": "11.0 mm"})
        self.assertEqual(len(self.edits()), 5)

    def test_window_popup_menubar_and_other_focus_out_keep_edit_pending(self):
        self.make_section()
        field = self.edit("shaft_diameter", "13")
        for reason in (QtCore.Qt.ActiveWindowFocusReason, QtCore.Qt.PopupFocusReason,
                       QtCore.Qt.MenuBarFocusReason, QtCore.Qt.OtherFocusReason):
            self.focus_out(field, reason)
            self.assertEqual(self.adapter.calls, [], reason)
            self.assertEqual(field.property("validation"), "pending")
            self.assertEqual(field.text(), "13")
            self.assertTrue(field.edited)
        self.assertIn(pp.PENDING_NOTE, self.section.tooltip("shaft_diameter", field))
        self.focus(self.other, QtCore.Qt.OtherFocusReason)
        self.assertEqual(self.adapter.calls, [])
        self.focus(field)
        self.assertEqual(field.text(), "13", "focus-in keeps an edited field's text")
        self.enter(field)
        self.assertEqual(len(self.edits()), 1)
        self.assertEqual(field.property("validation"), "")

    def test_enter_retries_after_transient_rejection(self):
        self.make_section()
        self.adapter.failures.append({"code": "stale_revision", "message": "The document changed"})
        field = self.edit("shaft_diameter", "12")
        self.enter(field)
        self.assertEqual(len(self.edits()), 1)
        self.assertTrue(field.rejected.transient)
        self.assertEqual(field.text(), "12")
        self.assertTrue(field.edited)
        self.assertEqual(field.property("validation"), "invalid")
        self.enter(field)
        self.assertEqual(len(self.edits()), 2)
        self.assertFalse(field.edited)
        self.assertEqual(self.adapter.find("shaft_diameter")["native_value"], 12.0)

    def test_focus_out_skips_nontransient_rejection_but_enter_retries(self):
        self.make_section()
        self.adapter.failures.append({"code": "invalid_argument", "message": "Value out of range"})
        field = self.edit("shaft_diameter", "-5")
        self.enter(field)
        self.assertEqual(len(self.edits()), 1)
        self.assertFalse(field.rejected.transient)
        self.focus(self.other, QtCore.Qt.MouseFocusReason)
        self.assertEqual(len(self.edits()), 1, "focus-out never resubmits a known failure")
        self.assertEqual(field.text(), "-5")
        self.focus(field)
        self.enter(field)
        self.assertEqual(len(self.edits()), 2)
        self.assertEqual(self.adapter.find("shaft_diameter")["native_value"], -5.0)

    def test_rejection_keeps_text_marks_invalid_and_reports_kept_value(self):
        section = self.make_section()
        field = self.edit("shaft_diameter", "12")
        self.enter(field)
        self.adapter.failures.append({"code": "build_failed", "message": "Change not applied: the cut is empty",
                                      "feature": "Shoulder", "validation": "history"})
        self.edit("shaft_diameter", "-5")
        self.enter(field)
        self.assertEqual(len(self.edits()), 2)
        self.assertEqual(field.text(), "-5")
        self.assertEqual(field.property("validation"), "invalid")
        self.assertTrue(section.error.isVisible())
        self.assertEqual(section.error.property("severity"), "error")
        self.assertIn("kept 12 mm", section.error.text())
        self.assertIn("Shoulder", section.error.text())
        self.assertTrue(field.hasFocus(), "an Enter failure keeps focus")
        self.assertEqual(field.selectedText(), "-5")
        tooltip = section.tooltip("shaft_diameter", field)
        self.assertIn("Not applied: Change not applied: the cut is empty", tooltip)
        self.assertIn("Esc restores 12 mm", tooltip)
        self.assertEqual(self.adapter.find("shaft_diameter")["native_value"], 12.0)
        self.assertEqual(section.error.toolTip(), section.error.text())

    def test_escape_restores_accepted_value_without_dispatch(self):
        section = self.make_section()
        field = self.edit("shaft_diameter", "99")
        QtTest.QTest.keyClick(field, QtCore.Qt.Key_Escape)
        self.pump()
        self.assertEqual(field.text(), "10")
        self.assertFalse(field.edited)
        self.assertTrue(field.hasFocus())
        self.adapter.failures.append({"code": "unit_mismatch", "message": "Expected a length"})
        self.edit("shaft_diameter", "30 deg")
        self.enter(field)
        self.assertTrue(section.error.isVisible())
        QtTest.QTest.keyClick(field, QtCore.Qt.Key_Escape)
        self.pump()
        self.assertEqual(field.text(), "10")
        self.assertIsNone(field.rejected)
        self.assertEqual(field.property("validation"), "")
        self.assertFalse(section.error.isVisible())
        self.assertEqual(len(self.edits()), 1)
        # The general.cancel wrapper: only an edited or rejected focused field is reverted.
        self.assertFalse(section.cancel_edit())
        self.edit("shaft_diameter", "77")
        self.assertTrue(section.cancel_edit())
        self.assertEqual(field.text(), "10")
        self.focus(self.other)
        self.assertFalse(section.cancel_edit())
        self.assertEqual(len(self.edits()), 1)

    def test_equals_prefix_sends_expression(self):
        self.make_section()
        field = self.edit("flute_count", "=shaft_diameter / 5")
        self.enter(field)
        self.assertEqual([call[1] for call in self.edits()],
                         [{"name": "flute_count", "expression": "shaft_diameter / 5"}])

    def test_literal_on_formula_row_clears_formula_in_one_request(self):
        self.make_section()
        field = self.edit("shoulder_diameter", "15")
        self.enter(field)
        self.assertEqual([call[1] for call in self.edits()],
                         [{"name": "shoulder_diameter", "value": "15.0 mm", "expression": None}])
        self.assertIsNone(field.formula_action)
        self.assertEqual(field.text(), "15")

    def test_freezing_formula_with_its_current_value_commits(self):
        self.make_section()
        field = self.field("shoulder_diameter")
        self.assertEqual(field.text(), "12")
        self.edit("shoulder_diameter", "12")
        self.enter(field)
        self.assertEqual([call[1] for call in self.edits()],
                         [{"name": "shoulder_diameter", "value": "12.0 mm", "expression": None}])
        self.assertIsNone(field.formula_action)

    def test_unchanged_literal_is_not_sent(self):
        self.make_section()
        field = self.edit("shaft_diameter", "10.0")
        self.enter(field)
        self.edit("shaft_diameter", "10")
        self.enter(field)
        self.assertEqual(self.adapter.calls, [])
        self.assertFalse(field.edited)

    def test_local_errors_stay_inline_without_dispatch(self):
        section = self.make_section()
        field = self.edit("shaft_diameter", "abc")
        self.enter(field)
        self.assertEqual(self.adapter.calls, [])
        self.assertEqual(field.property("validation"), "invalid")
        self.assertIn(pp.NOT_A_NUMBER, section.error.text())
        self.edit("shaft_diameter", "=")
        self.enter(field)
        self.assertIn("Enter a formula after =", section.error.text())
        self.assertEqual(self.adapter.calls, [])

    # -- external changes and refresh ---------------------------------------

    def test_external_change_updates_clean_focused_field(self):
        section = self.make_section()
        field = self.field("shaft_diameter")
        self.focus(field)
        self.assertEqual(field.text(), "10")
        self.adapter.external("shaft_diameter", 16)
        section.refresh()
        self.assertEqual(field.text(), "16")
        self.assertEqual(self.field("shoulder_diameter").text(), "18")
        self.assertFalse(field.edited)
        self.assertEqual(self.adapter.calls, [])

    def test_external_change_conflicts_edited_field_and_only_enter_overwrites(self):
        section = self.make_section()
        field = self.edit("shaft_diameter", "13")
        self.adapter.external("shaft_diameter", 15)
        section.refresh()
        self.assertEqual(field.text(), "13")
        self.assertTrue(field.conflict)
        self.assertEqual(section.error.property("severity"), "warning")
        self.assertIn("shaft_diameter changed elsewhere to 15 mm", section.error.text())
        self.assertIn("Enter applies 13 mm, Esc takes 15 mm", section.error.text())
        self.assertIn("changed elsewhere", section.tooltip("shaft_diameter", field))
        self.focus(self.other, QtCore.Qt.MouseFocusReason)
        self.assertEqual(self.adapter.calls, [])
        self.assertEqual(field.text(), "13")
        self.focus(field)
        self.enter(field)
        self.assertEqual([call[1] for call in self.edits()], [{"name": "shaft_diameter", "value": "13.0 mm"}])
        self.assertEqual(self.adapter.find("shaft_diameter")["native_value"], 13.0)
        self.assertFalse(field.conflict)

    def test_same_rows_refresh_neither_reconciles_nor_allocates(self):
        section = self.make_section()
        created = section.created
        widgets = {name: (entry.item, entry.field) for name, entry in section.rows.items()}
        self.adapter.bump()  # a model edit that leaves every parameter unchanged
        with patch.object(section, "_reconcile", wraps=section._reconcile) as reconcile:
            for _ in range(5):
                section.refresh()
        self.assertEqual(reconcile.call_count, 0)
        self.assertEqual(section.created, created)
        self.assertEqual({name: (entry.item, entry.field) for name, entry in section.rows.items()}, widgets)
        self.adapter.external("flute_count", 3)
        section.refresh()
        self.assertEqual(section.created, created, "a changed value updates rows in place")
        self.assertIs(section.rows["flute_count"].field, widgets["flute_count"][1])
        self.assertEqual(self.field("flute_count").text(), "3")

    def test_set_unavailable_then_same_document_refresh_rebuilds_rows(self):
        section = self.make_section()
        created = section.created
        section.set_unavailable(pp.ControllerParameterAdapter.ASSEMBLY)
        self.assertEqual(section.rows, {})
        self.assertTrue(section.empty.isVisible())
        self.assertEqual(section.empty.text(), "Parameters are edited in part studios")
        self.assertFalse(section.add_button.isEnabled())
        self.assertIsNone(section.cache_key)
        section.refresh()  # same document, same revision
        self.assertEqual(section.order, ["chamfer_angle", "flute_count", "shaft_diameter", "shoulder_diameter"])
        self.assertEqual(section.created, created + 4)
        self.assertTrue(section.add_button.isEnabled())
        self.assertFalse(section.empty.isVisible())

    def test_document_switch_retires_edited_field_without_dispatch(self):
        section = self.make_section()
        shaft = self.edit("shaft_diameter", "12")
        flute = self.edit("flute_count", "3")  # moving focus here left shaft pending (Other reason)
        self.move_focus(self.other, QtCore.Qt.MouseFocusReason)  # schedules flute's commit
        self.assertEqual(len(section._pending), 1)
        self.adapter.switch_document("doc-2", [make_row("depth", "length", 4.0)])
        section.refresh()
        self.pump()
        self.assertEqual(self.adapter.calls, [])
        self.assertTrue(shaft.retired and flute.retired)
        self.assertIn("Unapplied edit to shaft_diameter discarded: project changed", self.notes())
        self.assertIn("Unapplied edit to flute_count discarded: project changed", self.notes())
        self.assertEqual(section.order, ["depth"])
        self.assertEqual(section.document_id, "doc-2")
        self.assertEqual(self.field("depth").text(), "4")

    def test_row_removed_by_undo_drops_scheduled_commit(self):
        section = self.make_section()
        field = self.edit("flute_count", "5")
        self.move_focus(self.other, QtCore.Qt.MouseFocusReason)
        self.assertEqual(len(section._pending), 1)
        self.adapter._remove("flute_count")
        self.adapter.bump()
        section.refresh()
        self.pump()
        self.assertEqual(self.adapter.calls, [])
        self.assertTrue(field.retired)
        self.assertNotIn("flute_count", section.rows)
        self.assertIn("Unapplied edit to flute_count discarded: renamed or deleted elsewhere", self.notes())

    def test_missing_parameter_rejection_refreshes_and_discards(self):
        section = self.make_section()
        field = self.edit("flute_count", "5")
        self.adapter._remove("flute_count")  # deleted elsewhere; the panel has not refreshed yet
        self.adapter.failures.append({"code": "missing_parameter", "message": "No parameter flute_count",
                                      "names": ["flute_count"], "available": []})
        self.enter(field)
        self.assertEqual(len(self.edits()), 1)
        self.assertTrue(field.retired)
        self.assertNotIn("flute_count", section.rows)
        self.assertIn("Unapplied edit to flute_count discarded: renamed or deleted elsewhere", self.notes())

    def test_dialog_rejected_when_document_changes(self):
        section = self.make_section()
        dialog = section.add_parameter()
        self.pump()
        self.assertTrue(dialog.isVisible())
        self.assertIs(section.dialog, dialog)
        self.adapter.switch_document("doc-2", default_rows())
        section.refresh()
        # Checked before the event loop runs: the closed dialog is then deleted.
        self.assertFalse(dialog.isVisible())
        self.assertEqual(dialog.result(), QtGui.QDialog.Rejected)
        self.assertIsNone(section.dialog)
        self.assertIn("Parameter dialog closed: project changed", self.notes())
        self.pump()
        rename = section.rename("flute_count")
        self.pump()
        self.assertTrue(rename.isVisible())
        self.assertEqual(rename.document_id, "doc-2")
        self.adapter._remove("flute_count")
        self.adapter.bump()
        section.refresh()
        self.assertFalse(rename.isVisible())
        self.assertIsNone(section.dialog)
        self.assertIn("Parameter dialog closed: renamed or deleted elsewhere", self.notes())
        self.pump()
        dialog = section.add_parameter()
        self.pump()
        section.clear()
        self.assertFalse(dialog.isVisible())
        self.assertIsNone(section.dialog)
        self.assertEqual(self.adapter.calls, [])

    def test_commit_carries_document_and_revision_tokens(self):
        self.make_section()
        self.adapter.state["revision"] = "rev-7"
        field = self.edit("shaft_diameter", "12")
        self.enter(field)
        self.assertEqual(self.edits()[0][2], {"_document_id": "doc-1", "_expected_revision": "rev-7"})
        # The revision is the one seen when the commit was decided, not when it runs.
        before = self.adapter.state["revision"]
        self.edit("shaft_diameter", "13")
        self.focus(self.other, QtCore.Qt.MouseFocusReason)
        self.assertEqual(len(self.edits()), 2)
        self.assertEqual(self.edits()[1][2]["_expected_revision"], before)
        field = self.edit("shaft_diameter", "14")
        decided = self.adapter.state["revision"]
        QtTest.QTest.keyClick(self.field("shaft_diameter"), QtCore.Qt.Key_Return)
        self.adapter.bump()  # a bridge mutation lands between the decision and the dispatch
        self.assertNotEqual(self.adapter.state["revision"], decided)
        self.pump()
        self.assertEqual(len(self.edits()), 3)
        self.assertEqual(self.edits()[2][2], {"_document_id": "doc-1", "_expected_revision": decided})
        # The backend refuses the stale request; it is transient, so Enter retries with the new revision.
        self.assertEqual((field.rejected.code, field.rejected.transient), ("stale_revision", True))
        self.assertEqual(field.property("validation"), "invalid")
        self.assertEqual(self.adapter.find("shaft_diameter")["native_value"], 13.0)
        current = self.adapter.state["revision"]
        self.enter(field)
        self.assertEqual(self.edits()[3][2], {"_document_id": "doc-1", "_expected_revision": current})
        self.assertEqual(self.adapter.find("shaft_diameter")["native_value"], 14.0)
        self.assertIsNone(field.rejected)

    def test_closing_drops_scheduled_commit(self):
        section = self.make_section()
        self.edit("flute_count", "5")
        self.move_focus(self.other, QtCore.Qt.MouseFocusReason)
        self.assertEqual(len(section._pending), 1)
        section.close()
        self.pump()
        self.assertEqual(self.adapter.calls, [])
        self.assertTrue(section.flush_pending())
        self.assertEqual(self.adapter.calls, [])
        section.refresh()
        self.assertEqual(self.adapter.calls, [])

    def test_close_rejects_the_open_dialog(self):
        section = self.make_section()
        dialog = section.add_parameter()
        self.pump()
        self.assertTrue(dialog.isVisible())
        section.close()
        self.assertFalse(dialog.isVisible())
        self.assertEqual(dialog.result(), QtGui.QDialog.Rejected)
        self.assertIsNone(section.dialog)
        self.assertEqual(self.adapter.calls, [])

    def test_deleted_section_drops_its_scheduled_commit(self):
        section = self.make_section()
        self.edit("flute_count", "5")
        self.move_focus(self.other, QtCore.Qt.MouseFocusReason)  # schedules the commit
        self.assertEqual(len(section._pending), 1)
        self.adapter.section = None
        errors = []
        with patch.object(sys, "excepthook", lambda *info: errors.append(info)):
            shiboken6.delete(section)
            self.assertFalse(shiboken6.isValid(section))
            self.app.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
            self.pump()
        self.assertEqual(self.adapter.calls, [], "the zero-delay commit is bound to the section")
        self.assertEqual(errors, [])

    # -- input queued before the deferred commit runs -------------------------
    # Qt delivers input that is already queued (typed ahead while a recompute or
    # an inspect kept the GUI busy) before the zero-delay commit. These tests
    # decide a commit and feed the next input before the event loop runs it; the
    # fake refuses a stale revision as core does.

    def test_return_then_queued_focus_move_commits_once(self):
        section = self.make_section()
        field = self.edit("shaft_diameter", "12")
        QtTest.QTest.keyClick(field, QtCore.Qt.Key_Return)  # decided; the dispatch waits for the loop
        self.move_focus(self.other, QtCore.Qt.MouseFocusReason)  # the click queued behind it
        self.assertEqual(len(section._pending), 1, "the click joins the decided commit")
        self.pump()
        self.assertEqual(self.edits(), [("edit_parameter", {"name": "shaft_diameter", "value": "12.0 mm"},
                                         {"_document_id": "doc-1", "_expected_revision": "rev-1"})])
        self.assertEqual(self.adapter.find("shaft_diameter")["native_value"], 12.0)
        self.assertFalse(field.edited)
        self.assertIsNone(field.rejected)
        self.assertEqual(field.property("validation"), "")
        self.assertFalse(section.error.isVisible())
        self.assertEqual(field.text(), "12")
        self.assertTrue(self.other.hasFocus())

    def test_second_return_queued_before_the_dispatch_commits_once(self):
        section = self.make_section()
        field = self.edit("flute_count", "5")
        self.post_key(field, QtCore.Qt.Key_Return)
        self.post_key(field, QtCore.Qt.Key_Return)
        self.pump()
        self.assertEqual([call[1] for call in self.edits()], [{"name": "flute_count", "value": 5.0}])
        self.assertEqual(self.adapter.find("flute_count")["native_value"], 5.0)
        self.assertIsNone(field.rejected)
        self.assertEqual(field.property("validation"), "")
        self.assertFalse(section.error.isVisible())
        self.assertTrue(field.hasFocus())
        # Return, then a click elsewhere already in the queue.
        self.edit("flute_count", "6")
        self.post_key(field, QtCore.Qt.Key_Return)
        QtCore.QTimer.singleShot(0, lambda: self.other.setFocus(QtCore.Qt.MouseFocusReason))
        self.pump()
        self.assertEqual([call[1]["value"] for call in self.edits()], [5.0, 6.0])
        self.assertIsNone(field.rejected)
        self.assertEqual(field.property("validation"), "")
        self.assertTrue(self.other.hasFocus())

    def test_escape_queued_before_the_dispatch_discards_the_edit(self):
        section = self.make_section()
        field = self.edit("shaft_diameter", "12")
        QtTest.QTest.keyClick(field, QtCore.Qt.Key_Return)
        QtTest.QTest.keyClick(field, QtCore.Qt.Key_Escape)
        self.assertEqual(section._pending, [])
        self.pump()
        self.assertEqual(self.adapter.calls, [])
        self.assertEqual(field.text(), "10")
        self.assertFalse(field.edited)
        self.assertTrue(field.hasFocus())
        # The same keys queued in the order the system delivers them.
        self.edit("shaft_diameter", "12")
        self.post_key(field, QtCore.Qt.Key_Return)
        self.post_key(field, QtCore.Qt.Key_Escape)
        self.pump()
        self.assertEqual(self.adapter.calls, [])
        self.assertEqual(field.text(), "10")
        self.assertEqual(self.adapter.find("shaft_diameter")["native_value"], 10.0)

    def test_typing_after_return_before_the_dispatch_is_kept(self):
        section = self.make_section()
        field = self.edit("shaft_diameter", "12")
        QtTest.QTest.keyClick(field, QtCore.Qt.Key_Return)
        QtTest.QTest.keyClicks(field, "5")
        self.pump()
        self.assertEqual(self.adapter.calls, [], "the decision for 12 no longer matches the field")
        self.assertEqual(field.text(), "125")
        self.assertTrue(field.edited)
        self.assertEqual(field.property("validation"), "")
        self.enter(field)
        self.assertEqual([call[1] for call in self.edits()], [{"name": "shaft_diameter", "value": "125.0 mm"}])
        self.assertEqual(field.text(), "125")
        # New text decided by a later click replaces the earlier decision.
        flute = self.edit("flute_count", "3")
        QtTest.QTest.keyClick(flute, QtCore.Qt.Key_Return)
        QtTest.QTest.keyClicks(flute, "4")
        self.move_focus(self.other, QtCore.Qt.MouseFocusReason)
        self.assertEqual([pending.text for pending in section._pending], ["34"])
        self.pump()
        self.assertEqual([call[1] for call in self.edits()][1:], [{"name": "flute_count", "value": 34.0}])
        self.assertIsNone(flute.rejected)

    def test_chained_entry_typed_ahead_commits_each_field_once(self):
        section = self.make_section()
        flute, shaft = self.field("flute_count"), self.field("shaft_diameter")

        def type_ahead(flute_text, shaft_text):
            # Click flute, type, Enter, click shaft, type, Tab: all before the loop runs.
            self.move_focus(flute, QtCore.Qt.MouseFocusReason)
            flute.selectAll()
            QtTest.QTest.keyClicks(flute, flute_text)
            QtTest.QTest.keyClick(flute, QtCore.Qt.Key_Return)
            self.move_focus(shaft, QtCore.Qt.MouseFocusReason)
            shaft.selectAll()
            QtTest.QTest.keyClicks(shaft, shaft_text)
            self.move_focus(self.other, QtCore.Qt.TabFocusReason)
            self.assertEqual([pending.text for pending in section._pending], [flute_text, shaft_text])

        type_ahead("5", "11")
        self.pump()
        # The second commit was decided before the first ran; the section's own edit is not a
        # change made elsewhere, so it follows that edit's revision.
        self.assertEqual(self.edits(), [
            ("edit_parameter", {"name": "flute_count", "value": 5.0}, {"_document_id": "doc-1", "_expected_revision": "rev-1"}),
            ("edit_parameter", {"name": "shaft_diameter", "value": "11.0 mm"},
             {"_document_id": "doc-1", "_expected_revision": "rev-2"})])
        for field, text in ((flute, "5"), (shaft, "11")):
            self.assertFalse(field.edited, field.name)
            self.assertIsNone(field.rejected, field.name)
            self.assertEqual(field.property("validation"), "", field.name)
            self.assertEqual(field.text(), text)
        self.assertFalse(section.error.isVisible())
        self.assertEqual(self.field("shoulder_diameter").text(), "13")
        # A change made elsewhere before the queued commits run is refused for both.
        type_ahead("6", "12")
        self.adapter.bump()
        self.pump()
        self.assertEqual(len(self.edits()), 4)
        for field in (flute, shaft):
            self.assertEqual((field.rejected.code, field.rejected.transient), ("stale_revision", True))
            self.assertEqual(field.property("validation"), "invalid")
        self.assertEqual(self.adapter.find("flute_count")["native_value"], 5.0)
        self.assertEqual(self.adapter.find("shaft_diameter")["native_value"], 11.0)
        self.assertTrue(self.other.hasFocus(), "a failed focus-out commit does not pull focus back")

    def test_blocker_that_appears_before_the_dispatch_rejects_without_sending(self):
        section = self.make_section()
        field = self.edit("shaft_diameter", "12")
        self.move_focus(self.other, QtCore.Qt.MouseFocusReason)  # decided; the same click opened a tool
        self.adapter.blocked = EDITING
        self.pump()
        self.assertEqual(self.adapter.calls, [])
        self.assertEqual((field.rejected.code, field.rejected.transient), ("blocked", True))
        self.assertEqual(field.property("validation"), "invalid")
        self.assertIn("shaft_diameter: " + EDITING + " · kept 10 mm", section.error.text())
        self.assertEqual(field.text(), "12")
        self.assertTrue(self.other.hasFocus(), "the tool keeps focus")
        # Once the tool is gone, Enter applies the kept edit.
        self.adapter.blocked = None
        section.set_editable()
        self.focus(field)
        self.enter(field)
        self.assertEqual([call[1] for call in self.edits()], [{"name": "shaft_diameter", "value": "12.0 mm"}])
        self.assertIsNone(field.rejected)

    def test_focus_out_failure_leaves_focus_where_the_user_moved_it(self):
        section = self.make_section()
        self.adapter.failures.append({"code": "invalid_argument", "message": "Value out of range"})
        field = self.edit("shaft_diameter", "-5")
        self.focus(self.other, QtCore.Qt.MouseFocusReason)
        self.assertEqual(len(self.edits()), 1)
        self.assertTrue(self.other.hasFocus())
        self.assertFalse(field.hasFocus())
        self.assertEqual(field.property("validation"), "invalid")
        self.assertEqual(field.text(), "-5")
        self.assertIn("shaft_diameter: Value out of range · kept 10 mm", section.error.text())

    def test_conflict_note_clears_when_the_value_returns_elsewhere(self):
        section = self.make_section()
        field = self.edit("shaft_diameter", "13")
        self.adapter.external("shaft_diameter", 15)
        section.refresh()
        self.assertTrue(field.conflict)
        self.assertIn("shaft_diameter changed elsewhere to 15 mm", section.error.text())
        self.adapter.external("shaft_diameter", 10)  # back to the value the edit started from
        section.refresh()
        self.assertFalse(field.conflict)
        self.assertFalse(section.error.isVisible())
        self.assertNotIn("changed elsewhere", section.tooltip("shaft_diameter", field))
        self.assertTrue(field.edited)
        self.assertEqual(field.text(), "13")
        # No conflict any more: the usual focus-out commit applies the edit.
        self.focus(self.other, QtCore.Qt.MouseFocusReason)
        self.assertEqual([call[1] for call in self.edits()], [{"name": "shaft_diameter", "value": "13.0 mm"}])
        self.assertEqual(self.adapter.find("shaft_diameter")["native_value"], 13.0)
        self.assertFalse(section.error.isVisible())

    def test_actions_apply_a_pending_edit_first_or_refuse(self):
        section = self.make_section()
        # Delete and Replace formula: the edit is dispatched before the action.
        self.edit("flute_count", "3")
        self.assertTrue(section.delete("chamfer_angle").ok)
        self.assertEqual([(op, args["name"]) for op, args, _ in self.adapter.calls],
                         [("edit_parameter", "flute_count"), ("delete_parameter", "chamfer_angle")])
        self.edit("flute_count", "4")
        self.assertTrue(section.replace_formula("shoulder_diameter").ok)
        self.assertEqual([(op, args) for op, args, _ in self.adapter.calls[2:]],
                         [("edit_parameter", {"name": "flute_count", "value": 4.0}),
                          ("edit_parameter", {"name": "shoulder_diameter", "value": "12.0 mm", "expression": None})])
        # Add and Rename: the edit is dispatched before the dialog opens.
        for value, open_dialog in ((5.0, section.add_parameter), (6.0, lambda: section.rename("flute_count"))):
            self.edit("flute_count", pp.format_number(value))
            count = len(self.adapter.calls)
            dialog = open_dialog()
            self.assertIsNotNone(dialog)
            self.assertEqual([(op, args) for op, args, _ in self.adapter.calls[count:]],
                             [("edit_parameter", {"name": "flute_count", "value": value})])
            dialog.reject()
            self.pump()
            self.show_host(self.host)  # offscreen Qt does not reactivate the host by itself
        # A conflict or a known rejection refuses every action and dispatches nothing.
        self.adapter.find("flute_count")["expression"] = "shaft_diameter / 5"  # a formula row to replace
        self.adapter.bump()
        section.refresh()
        self.assertTrue(self.field("flute_count").formula)
        calls = len(self.adapter.calls)
        field = self.edit("shaft_diameter", "13")
        self.adapter.external("shaft_diameter", 15)
        section.refresh()
        self.assertTrue(field.conflict)
        actions = (section.add_parameter, lambda: section.rename("flute_count"), lambda: section.delete("flute_count"),
                   lambda: section.replace_formula("flute_count"))
        for action in actions:
            self.assertIsNone(action())
        self.assertIsNone(section.dialog)
        self.assertEqual(len(self.adapter.calls), calls)
        self.assertIn("Apply or discard the edit to shaft_diameter first · Enter applies, Esc discards", self.notes())
        self.assertTrue(section.revert(field))
        self.adapter.failures.append({"code": "invalid_argument", "message": "Value out of range"})
        self.edit("shaft_diameter", "-1")
        self.enter(field)
        calls += 1
        self.assertEqual(len(self.adapter.calls), calls)
        for action in actions:
            self.assertIsNone(action())
        self.assertIsNone(section.dialog)
        self.assertEqual(len(self.adapter.calls), calls)

    def test_flush_pending_commits_synchronously_and_refuses_conflict_or_known_rejection(self):
        section = self.make_section()
        self.edit("shaft_diameter", "12")
        self.assertTrue(section.flush_pending())
        self.assertEqual([call[1] for call in self.edits()], [{"name": "shaft_diameter", "value": "12.0 mm"}])
        self.edit("flute_count", "3")
        self.move_focus(self.other, QtCore.Qt.MouseFocusReason)
        self.assertEqual(len(section._pending), 1)
        self.assertTrue(section.flush_pending())
        self.assertEqual(len(self.edits()), 2)
        self.assertEqual(section._pending, [])
        # A conflict refuses the action.
        field = self.edit("shaft_diameter", "13")
        self.adapter.external("shaft_diameter", 15)
        section.refresh()
        self.assertFalse(section.flush_pending())
        self.assertEqual(len(self.edits()), 2)
        refusal = "Apply or discard the edit to shaft_diameter first · Enter applies, Esc discards"
        self.assertIn(refusal, self.notes())
        self.assertIn(refusal, section.error.text())
        self.assertTrue(section.revert(field))
        # Text already rejected (not transient) refuses the action too.
        self.adapter.failures.append({"code": "invalid_argument", "message": "Value out of range"})
        self.edit("shaft_diameter", "-1")
        self.enter(field)
        self.assertEqual(len(self.edits()), 3)
        self.assertFalse(section.flush_pending())
        self.assertEqual(len(self.edits()), 3)
        self.assertTrue(section.revert(field))
        # A transient rejection is retried synchronously.
        self.adapter.failures.append({"code": "busy", "message": "Finish the active operation"})
        flute = self.edit("flute_count", "7")
        self.enter(flute)
        self.assertTrue(flute.rejected.transient)
        self.assertTrue(section.flush_pending())
        self.assertEqual(len(self.edits()), 5)
        self.assertEqual(self.adapter.find("flute_count")["native_value"], 7.0)
        # A read-only section cannot apply the edit, so the action is refused.
        self.edit("flute_count", "8")
        self.adapter.blocked = EDITING
        self.assertFalse(section.flush_pending())
        self.assertEqual(len(self.edits()), 5)

    def test_tab_order_follows_visual_rows_after_insert(self):
        section = self.make_section(FakeAdapter([make_row("b_len", "length", 2.0), make_row("c_len", "length", 3.0)]))
        created = section.created
        self.adapter.state["parameters"].insert(0, make_row("a_len", "length", 1.0))
        self.adapter.bump()
        section.refresh()
        self.assertEqual(section.created, created + 1, "a bridge-like create allocates exactly one row")
        self.assertEqual(section.order, ["a_len", "b_len", "c_len"])
        self.assertEqual([section.tree.topLevelItem(i).text(0) for i in range(3)], ["a_len", "b_len", "c_len"])
        self.focus(self.field("a_len"))
        QtTest.QTest.keyClick(self.field("a_len"), QtCore.Qt.Key_Tab)
        self.pump()
        self.assertTrue(self.field("b_len").hasFocus())
        QtTest.QTest.keyClick(self.field("b_len"), QtCore.Qt.Key_Tab)
        self.pump()
        self.assertTrue(self.field("c_len").hasFocus())
        self.assertEqual(self.adapter.calls, [])

    # -- states and actions ------------------------------------------------

    def test_read_only_blocks_commit_and_add_with_reason(self):
        section = self.make_section()
        self.adapter.blocked = EDITING
        section.set_editable()
        self.assertFalse(section.add_button.isEnabled())
        self.assertEqual(section.add_button.toolTip(), "Add parameter \u00b7 " + EDITING)
        self.assertTrue(all(entry.field.isReadOnly() for entry in section.rows.values()))
        QtTest.QTest.keyClicks(self.field("flute_count"), "9")
        self.assertEqual(self.field("flute_count").text(), "2", "a read-only field takes no typing")
        self.assertFalse(self.field("flute_count").edited)
        self.assertIsNone(section.add_parameter())
        self.assertIsNone(section.dialog)
        self.assertIn(EDITING, self.notes())
        center = section.add_button.rect().center()
        event = QtGui.QHelpEvent(QtCore.QEvent.ToolTip, center, section.add_button.mapToGlobal(center))
        QtGui.QApplication.sendEvent(section.add_button, event)
        self.pump()
        self.assertTrue(QtGui.QToolTip.isVisible())
        self.assertIn(EDITING, QtGui.QToolTip.text())
        QtGui.QToolTip.hideText()
        # An edit made before the section turned read-only keeps its text, and Enter is refused.
        self.adapter.blocked = None
        section.sync_editable()
        self.assertTrue(section.add_button.isEnabled())
        self.assertEqual(section.add_button.toolTip(), "Add parameter")
        field = self.edit("shaft_diameter", "12")
        self.adapter.blocked = EDITING
        section.set_editable()
        self.assertTrue(field.isReadOnly())
        self.assertEqual(field.text(), "12")
        self.enter(field)
        self.assertEqual(self.adapter.calls, [])
        self.assertIn(EDITING, section.error.text())
        # Actions flush first; an edit that cannot be applied refuses them with a note.
        self.assertFalse(section.flush_pending())
        self.assertIn("Apply or discard the edit to shaft_diameter first \u00b7 Enter applies, Esc discards", self.notes())
        self.assertEqual(field.text(), "12")
        # Enter works again once the section is editable.
        self.adapter.blocked = None
        section.sync_editable()
        self.assertFalse(field.isReadOnly())
        self.enter(field)
        self.assertEqual([call[1] for call in self.edits()], [{"name": "shaft_diameter", "value": "12.0 mm"}])
        # Escape still reverts an edited field while read-only.
        flute = self.edit("flute_count", "4")
        self.adapter.blocked = EDITING
        section.set_editable()
        QtTest.QTest.keyClick(flute, QtCore.Qt.Key_Escape)
        self.assertEqual(flute.text(), "2")
        self.assertFalse(flute.edited)
        self.assertEqual(len(self.adapter.calls), 1)

    def test_placeholders_for_no_document_unmanaged_and_assembly(self):
        section = self.make_section()
        self.adapter.available = False
        section.refresh()
        self.assertEqual(section.rows, {})
        self.assertTrue(section.empty.isVisible())
        self.assertEqual(section.empty.text(), "Open or create a part studio to add parameters")
        self.assertFalse(section.add_button.isEnabled())
        self.assertIn(pp.NO_DOCUMENT, section.add_button.toolTip())
        self.assertEqual(section.title.text(), "Parameters (0)")
        self.adapter.available = True
        self.adapter.state.update(managed=False, parameters=[])
        section.refresh()
        self.assertEqual(section.empty.text(), "Reference file · adopt a copy to edit parameters")
        self.assertFalse(section.add_button.isEnabled())
        self.adapter.state["parameters"] = default_rows()
        section.refresh()
        self.assertFalse(section.empty.isVisible())
        self.assertTrue(all(entry.field.isReadOnly() for entry in section.rows.values()))
        self.assertIn("Reference file", section.add_button.toolTip())
        section.set_unavailable("Parameters are edited in part studios")
        self.assertEqual(section.empty.text(), "Parameters are edited in part studios")
        self.assertFalse(section.add_button.isEnabled())
        section.set_editable()  # Panel.refresh/sync_edit_ui keep the unavailable reason
        self.assertIn("part studios", section.add_button.toolTip())
        self.adapter.state.update(managed=True, parameters=[])
        section.refresh()
        self.assertEqual(section.empty.text(), "No parameters · + adds one")
        self.assertTrue(section.add_button.isEnabled())
        section.clear()
        self.assertEqual(section.empty.text(), pp.NO_DOCUMENT)
        self.assertFalse(section.add_button.isEnabled())
        self.assertEqual(self.adapter.calls, [])

    def test_add_dialog_keeps_input_and_focuses_named_field(self):
        section = self.make_section()
        dialog = section.add_parameter()
        self.pump()
        self.assertEqual(dialog.objectName(), "KurtShapeParameterDialog")
        self.assertEqual(dialog.windowModality(), QtCore.Qt.WindowModal)
        self.assertEqual([dialog.type_choice.itemData(i) for i in range(dialog.type_choice.count())],
                         ["length", "angle", "number"])
        self.assertEqual(dialog.value_edit.text(), "10")
        dialog.type_choice.setCurrentIndex(1)
        self.assertEqual(dialog.value_edit.text(), "0")
        dialog.type_choice.setCurrentIndex(2)
        self.assertEqual(dialog.value_edit.text(), "1")
        dialog.type_choice.setCurrentIndex(0)
        self.assertEqual(dialog.value_edit.text(), "10")
        self.assertFalse(dialog.accept_button.isEnabled(), "an empty name cannot be added")
        # The local hint uses the injected backend pattern (lowercase first).
        dialog.name_edit.setText("Shaft")
        self.assertFalse(dialog.accept_button.isEnabled())
        self.assertIn("lowercase", dialog.message.text())
        # A unit symbol passes the format hint; the backend reason is shown in plain words.
        dialog.name_edit.setText("t")
        self.assertTrue(dialog.accept_button.isEnabled())
        self.adapter.failures.append({"code": "invalid_parameter_name", "message": "t is a unit",
                                      "name": "t", "reason": "expression_token"})
        dialog.accept_button.click()
        self.pump()
        self.assertTrue(dialog.isVisible())
        self.assertIn("is a unit or keyword in formulas", dialog.message.text())
        self.assertIs(dialog.focusWidget(), dialog.name_edit)
        self.assertEqual(dialog.name_edit.text(), "t")
        self.assertEqual(dialog.value_edit.text(), "10")
        # A value error focuses Value and keeps the input.
        dialog.name_edit.setText("thickness")
        dialog.value_edit.setText("30 deg")
        self.adapter.failures.append({"code": "unit_mismatch", "message": "Expected a length, got an angle",
                                      "expected_unit": "mm", "actual_unit": "Angle"})
        dialog.accept_button.click()
        self.pump()
        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog.message.text(), "Expected a length, got an angle")
        self.assertIs(dialog.focusWidget(), dialog.value_edit)
        self.assertEqual(dialog.value_edit.text(), "30 deg")
        # A local value error never dispatches.
        dialog.value_edit.setText("abc")
        dialog.accept_button.click()
        self.assertEqual(len(self.adapter.calls), 2)
        self.assertIn(pp.NOT_A_NUMBER, dialog.message.text())
        # Success: one create with the document captured at open; the new row gets focus.
        dialog.value_edit.setText("3")
        dialog.accept_button.click()
        self.assertFalse(dialog.isVisible())
        self.assertEqual(dialog.result(), QtGui.QDialog.Accepted)
        self.assertIsNone(section.dialog)
        self.pump()
        self.assertEqual(self.adapter.calls[-1], ("create_parameter", {"name": "thickness", "type": "length",
                                                                       "value": "3.0 mm"}, {"_document_id": "doc-1"}))
        self.assertEqual(section.current_name(), "thickness")
        # The deferred select gave the new field focus; offscreen Qt does not
        # reactivate the host when the window-modal dialog closes, so do it here.
        self.show_host(self.host)
        self.assertTrue(self.field("thickness").hasFocus())
        self.assertEqual(section.title.text(), "Parameters (5)")
        # Without an injected pattern the widget applies no rule of its own.
        self.adapter.pattern = None
        dialog = section.add_parameter()
        dialog.name_edit.setText("Shaft")
        self.assertTrue(dialog.accept_button.isEnabled())
        dialog.reject()

    def test_rename_dialog_from_f2_passes_document_token(self):
        section = self.make_section()
        section.select("flute_count")
        self.focus(section.tree)
        self.assertTrue(section.owns_focus())
        QtTest.QTest.keyClick(section.tree, QtCore.Qt.Key_F2)
        self.pump()
        dialog = section.dialog
        self.assertIsNotNone(dialog)
        self.assertEqual(dialog.mode, "rename")
        self.assertIsNone(dialog.value_edit)
        self.assertEqual(dialog.name_edit.text(), "flute_count")
        self.assertFalse(dialog.accept_button.isEnabled(), "the same name is not a rename")
        self.assertIsNotNone(dialog.findChild(QtGui.QLabel, "KurtShapeParameterRenameNote"))
        dialog.name_edit.setText("flutes")
        dialog.accept_button.click()
        self.assertFalse(dialog.isVisible())
        self.assertIsNone(section.dialog)
        self.pump()
        self.assertEqual(self.adapter.calls, [("rename_parameter", {"name": "flute_count", "new_name": "flutes"},
                                               {"_document_id": "doc-1"})])
        self.assertEqual(section.current_name(), "flutes")
        self.assertNotIn("Parameter dialog closed", " ".join(self.notes()))

    def test_tree_enter_focuses_the_current_value_field(self):
        section = self.make_section()
        section.select("shaft_diameter")
        self.focus(section.tree)
        QtTest.QTest.keyClick(section.tree, QtCore.Qt.Key_Return)
        self.pump()
        self.assertTrue(self.field("shaft_diameter").hasFocus())
        self.assertEqual(self.field("shaft_diameter").text(), "10")

    def test_delete_confirmation_lists_features_and_dependent_parameters_and_passes_tokens(self):
        section = self.make_section()
        self.adapter.state["revision"] = "rev-3"
        with patch.object(pp.QtGui, "QMessageBox", FakeMessageBox):
            outcome = section.delete("flute_count")
            self.assertTrue(outcome.ok)
            self.assertEqual(FakeMessageBox.instances, [], "an unused parameter is deleted without asking")
            self.assertEqual(self.adapter.calls[-1], ("delete_parameter", {"name": "flute_count", "freeze_consumers": False},
                                                      {"_document_id": "doc-1", "_expected_revision": "rev-3"}))
            self.adapter.usages["shaft_diameter"] = {
                "used_by": [{"feature": "ShaftSk", "parameter": "Diameter", "label": "Shaft sketch · Diameter", "held": False}],
                "used_by_parameters": ["shoulder_diameter"], "affects": ["Shaft sketch", "Shaft"], "parts": []}
            section.select("shaft_diameter")
            self.assertIsNone(section.delete_current())
            box = FakeMessageBox.instances[-1]
            self.assertIn("Shaft sketch · Diameter", box.text)
            self.assertIn("shoulder_diameter (formula)", box.text)
            self.assertEqual(box.buttons[0][0], "Delete and keep current values")
            self.assertEqual(len(self.adapter.calls), 1, "Cancel deletes nothing")
            FakeMessageBox.choice = "delete"
            revision = self.adapter.state["revision"]
            FakeMessageBox.during = self.adapter.bump  # a bridge change while the box is open
            outcome = section.delete("shaft_diameter")
            self.assertTrue(outcome.ok)
            self.assertEqual(self.adapter.calls[-1], ("delete_parameter", {"name": "shaft_diameter", "freeze_consumers": True},
                                                      {"_document_id": "doc-1", "_expected_revision": revision}))
            self.adapter.usages["shoulder_diameter"] = {
                "used_by": [{"feature": f"F{i}", "parameter": "Length", "label": f"Feature {i} · Length", "held": False}
                            for i in range(11)], "used_by_parameters": [], "affects": [], "parts": []}
            FakeMessageBox.choice = "cancel"
            FakeMessageBox.during = None
            section.delete("shoulder_diameter")
            self.assertIn("Feature 7 · Length", FakeMessageBox.instances[-1].text)
            self.assertNotIn("Feature 8 · Length", FakeMessageBox.instances[-1].text)
            self.assertIn("… and 3 more", FakeMessageBox.instances[-1].text)
        self.assertEqual(section.order, ["chamfer_angle", "shoulder_diameter"])

    def test_copy_reference_uses_backend_reference_verbatim(self):
        rows = default_rows()
        rows[2]["expression_ref"] = "Params001.shaft_diameter"
        section = self.make_section(FakeAdapter(rows))
        clipboard = QtGui.QApplication.clipboard()
        previous = clipboard.text()
        self.addCleanup(clipboard.setText, previous)
        section.select("shaft_diameter")
        self.assertTrue(section.copy_reference())
        self.assertEqual(clipboard.text(), "Params001.shaft_diameter")
        self.assertIn("Copied Params001.shaft_diameter · paste into a feature's Formula field", self.notes())
        self.assertIn("Use in feature formulas as Params001.shaft_diameter", section.tooltip("shaft_diameter"))
        clipboard.setText("")
        menu = section.build_context_menu(section.tree.visualItemRect(section.rows["flute_count"].item).center())
        next(action for action in menu.actions() if action.text() == "Copy reference").trigger()
        self.assertEqual(clipboard.text(), "Params.flute_count")
        menu.deleteLater()
        self.assertTrue(section.paste())
        self.assertIn("Paste into a parameter value field", self.notes())
        self.assertEqual(self.adapter.calls, [])

    def test_context_menu_used_by_and_actions(self):
        section = self.make_section()
        self.adapter.usages["shaft_diameter"] = {
            "used_by": [{"feature": "ShaftSk", "parameter": "Diameter", "label": "Shaft sketch · Diameter", "held": False}],
            "used_by_parameters": ["shoulder_diameter"], "affects": ["Shaft sketch", "Shaft"], "parts": []}
        point = section.tree.visualItemRect(section.rows["shaft_diameter"].item).center()
        menu = section.build_context_menu(point)
        texts = [action.text() for action in menu.actions() if not action.isSeparator()]
        self.assertEqual(texts, ["Copy reference", "Used by", "Rename…", "Delete…"])
        used = next(action for action in menu.actions() if action.text() == "Used by").menu()
        entries = used.actions()
        self.assertEqual([action.text() for action in entries], ["Shaft sketch · Diameter", "shoulder_diameter (formula)"])
        entries[0].trigger()
        self.assertEqual(self.adapter.shown, [("ShaftSk", "Diameter")])
        entries[1].trigger()
        self.assertEqual(section.current_name(), "shoulder_diameter")
        menu.deleteLater()
        menu = section.build_context_menu(section.tree.visualItemRect(section.rows["flute_count"].item).center())
        used = next(action for action in menu.actions() if action.text() == "Used by").menu()
        self.assertEqual([(action.text(), action.isEnabled()) for action in used.actions()], [("Not used yet", False)])
        menu.deleteLater()
        menu = section.build_context_menu(section.tree.visualItemRect(section.rows["shoulder_diameter"].item).center())
        next(action for action in menu.actions() if action.text() == "Replace formula with value").trigger()
        self.assertEqual([call[1] for call in self.edits()],
                         [{"name": "shoulder_diameter", "value": "12.0 mm", "expression": None}])
        menu.deleteLater()
        empty = QtCore.QPoint(4, section.tree.viewport().height() - 3)
        self.assertIsNone(section.tree.itemAt(empty))
        menu = section.build_context_menu(empty)
        self.assertEqual([action.text() for action in menu.actions()], ["Add parameter…"])
        menu.deleteLater()
        tooltip = section.tooltip("shaft_diameter")
        self.assertIn("Used by: Shaft sketch · Diameter", tooltip)
        self.assertIn("Used by parameters: shoulder_diameter", tooltip)
        self.assertIn("Affects: Shaft sketch, Shaft (2 features)", tooltip)
        self.assertIn("Used by: nothing yet", section.tooltip("flute_count"))

    def test_context_menu_applies_pending_edit_before_it_shows(self):
        section = self.make_section()
        self.edit("flute_count", "3")
        seen = []

        def close_menu():
            popup = QtGui.QApplication.activePopupWidget()
            seen.append((popup is not None, len(self.adapter.calls)))
            if popup is not None:
                popup.close()

        QtCore.QTimer.singleShot(200, close_menu)
        section._context_menu(section.tree.visualItemRect(section.rows["shaft_diameter"].item).center())
        self.pump()
        self.assertEqual(seen, [(True, 1)], "exactly one dispatch, completed before the menu showed")
        self.assertEqual(len(self.adapter.calls), 1)

    def test_stale_formula_rows_and_banner_when_parameter_set_not_evaluated(self):
        section = self.make_section()
        self.assertFalse(section.banner.isVisible())
        message = "Quantity::operator +(): Unit mismatch in plus operation\nin expression: shaft_diameter + 2 mm"
        self.adapter.state["parameter_set"] = {"id": "Params", "label": "Params", "state": ["Touched", "Invalid"],
                                               "error": {"name": "shoulder_diameter", "message": message}}
        section.refresh()
        self.assertTrue(section.banner.isVisible())
        self.assertEqual(section.banner.objectName(), "KurtShapeParameterState")
        self.assertEqual(section.banner.text(), "Parameters not fully evaluated · shoulder_diameter: "
                         "Quantity::operator +(): Unit mismatch in plus operation · Rebuild to re-evaluate")
        shoulder = section.rows["shoulder_diameter"]
        self.assertEqual(shoulder.field.property("stale"), "true")
        self.assertEqual(self.field("shaft_diameter").property("stale"), "false")
        self.assertEqual(shoulder.item.text(0), "shoulder_diameter  !")
        self.assertEqual(shoulder.item.foreground(0).color().name(), theme.COLORS["error"])
        self.assertIn(pp.STALE_NOTE, section.tooltip("shoulder_diameter"))
        self.assertNotIn(pp.STALE_NOTE, section.tooltip("shaft_diameter"))
        self.adapter.state["parameter_set"] = dict(UP_TO_DATE, state=["Touched"])
        section.refresh()
        self.assertEqual(section.banner.text(), "Parameters changed outside KurtShape · Rebuild to re-evaluate")
        self.assertEqual(shoulder.item.text(0), "shoulder_diameter")
        # Fallback: the container's build error, when inspect has no parameter_set.
        self.adapter.state["parameter_set"] = None
        self.adapter.state["build_errors"] = [{"feature": "Params", "message": message
                                               + "\nin property binding 'Drill#Params.shoulder_diameter'"}]
        section.refresh()
        self.assertTrue(section.banner.isVisible())
        self.assertIn("shoulder_diameter: Quantity::operator +(): Unit mismatch", section.banner.text())
        self.assertEqual(shoulder.field.property("stale"), "true")
        self.assertEqual(shoulder.item.text(0), "shoulder_diameter  !")
        self.adapter.state["build_errors"] = []
        section.refresh()
        self.assertFalse(section.banner.isVisible())
        self.assertEqual(shoulder.field.property("stale"), "false")
        self.assertEqual(self.adapter.calls, [])

    def test_only_touched_invalid_or_error_mark_the_set_out_of_date(self):
        # Other native flags (Expanded is a tree-view flag) leave the set up to date.
        section = self.make_section()
        shoulder = self.field("shoulder_diameter")
        for flags in (["Up-to-date"], ["Up-to-date", "Expanded"], ["Expanded"], []):
            self.adapter.state["parameter_set"] = dict(UP_TO_DATE, state=flags)
            section.refresh()
            self.assertFalse(section.banner.isVisible(), flags)
            self.assertEqual(shoulder.property("stale"), "false", flags)
            self.assertNotIn(pp.STALE_NOTE, section.tooltip("shoulder_diameter"), flags)
        for flags, words in ((["Touched", "Expanded"], "changed outside KurtShape"),
                             (["Up-to-date", "Error"], "not fully evaluated"), (["Invalid"], "not fully evaluated")):
            self.adapter.state["parameter_set"] = dict(UP_TO_DATE, state=flags)
            section.refresh()
            self.assertTrue(section.banner.isVisible(), flags)
            self.assertIn(words, section.banner.text(), flags)
            self.assertEqual(shoulder.property("stale"), "true", flags)

    def test_hover_tooltips_read_usage_only_on_the_tooltip_event(self):
        section = self.make_section()
        self.assertEqual(self.adapter.usage_reads, 0, "refresh never reads usage")
        rect = section.tree.visualItemRect(section.rows["shaft_diameter"].item)
        self.help_event(section.tree.viewport(), QtCore.QPoint(rect.left() + 4, rect.center().y()))
        self.assertEqual(self.adapter.usage_reads, 1)
        self.assertTrue(QtGui.QToolTip.isVisible())
        self.assertIn("shaft_diameter · Length (mm)", QtGui.QToolTip.text())
        self.assertIn("Use in feature formulas as Params.shaft_diameter", QtGui.QToolTip.text())
        flute = self.field("flute_count")
        self.help_event(flute, flute.rect().center())
        self.assertEqual(self.adapter.usage_reads, 2)
        self.assertIn("Use in feature formulas as Params.flute_count", flute.toolTip())
        self.assertIn("Use in feature formulas as Params.flute_count", QtGui.QToolTip.text())
        empty = QtCore.QPoint(4, section.tree.viewport().height() - 3)
        self.assertIsNone(section.tree.itemAt(empty))
        self.help_event(section.tree.viewport(), empty)
        self.assertEqual(self.adapter.usage_reads, 2, "empty space reads nothing")
        self.assertEqual(self.adapter.calls, [])

    def test_focusing_a_value_field_makes_its_row_current(self):
        section = self.make_section()
        section.select("chamfer_angle")
        self.focus(self.field("flute_count"), QtCore.Qt.MouseFocusReason)
        self.assertEqual(section.current_name(), "flute_count")
        QtTest.QTest.keyClick(self.field("flute_count"), QtCore.Qt.Key_Down)
        self.pump()
        self.assertTrue(self.field("shaft_diameter").hasFocus())
        self.assertEqual(section.current_name(), "shaft_diameter")
        self.assertEqual(self.adapter.calls, [])

    def test_clamped_value_is_reported(self):
        section = self.make_section()
        self.adapter.stored["shaft_diameter"] = lambda value: max(value, 0.0)
        field = self.edit("shaft_diameter", "-5")
        self.enter(field)
        self.assertEqual(len(self.edits()), 1)
        warning = "shaft_diameter stored as 0 mm (requested -5 mm)"
        self.assertEqual(section.error.text(), warning)
        self.assertEqual(section.error.property("severity"), "warning")
        self.assertIn((warning, "warning"), self.adapter.notes)
        self.assertEqual(field.text(), "0")

    def test_rollback_note_counts_held_uses(self):
        self.make_section()
        self.adapter.rolled = True
        self.adapter.usages["shaft_diameter"] = {"used_by": [
            {"feature": "ShaftSk", "parameter": "Diameter", "label": "Shaft sketch · Diameter", "held": False},
            {"feature": "Tip", "parameter": "Length", "label": "Tip · Length", "held": True},
            {"feature": "Hole", "parameter": "Diameter", "label": "Hole · Diameter", "held": True}],
            "used_by_parameters": [], "affects": [], "parts": []}
        self.enter(self.edit("shaft_diameter", "12"))
        self.assertIn("Parameter update complete · 2 uses after the rollback bar are checked when you roll forward",
                      self.notes())
        self.adapter.rolled = False
        reads = self.adapter.usage_reads
        self.enter(self.edit("shaft_diameter", "13"))
        self.assertEqual(self.adapter.usage_reads, reads, "usage is read only when the studio is rolled back")

    def test_translation_table_maps_codes_to_fields_and_transience(self):
        translate = pp.ParameterAdapter.translate
        for code in ("stale_revision", "busy", "sketch_edit_active", "managed_sketch_mismatch", "document_changed", "not_applied"):
            outcome = translate({"code": code, "message": "m"})
            self.assertEqual((outcome.ok, outcome.field, outcome.transient), (False, None, True), code)
        for code in ("invalid_argument", "unit_mismatch", "invalid_expression", "expression_cycle", "expression_driven",
                     "unsupported_parameter", "build_failed", "empty_cut", "empty_add", "invalid_geometry", "something_new"):
            outcome = translate({"code": code, "message": "m"})
            self.assertEqual((outcome.field, outcome.transient), ("value", False), code)
        duplicate = translate({"code": "duplicate_parameter", "message": "m", "name": "Shaft", "existing": "shaft"})
        self.assertEqual((duplicate.field, duplicate.message), ("name", "A parameter named shaft already exists."))
        reasons = {"format": "lowercase", "reserved": "t is reserved", "reserved_attribute": "built-in property",
                   "constant": "formula constant", "function": "formula function", "unit": "unit or keyword",
                   "expression_token": "unit or keyword"}
        for reason, words in reasons.items():
            outcome = translate({"code": "invalid_parameter_name", "message": "raw", "name": "t", "reason": reason})
            self.assertEqual(outcome.field, "name")
            self.assertIn(words, outcome.message, reason)
        self.assertEqual(translate({"code": "invalid_parameter_name", "message": "raw", "name": "t",
                                    "reason": "later_reason"}).message, "raw")
        failed = translate({"code": "empty_add", "message": "Change not applied: nothing added", "feature": "Cap"})
        self.assertIn("Cap", failed.message)
        self.assertEqual(failed.details, {"feature": "Cap"})
        missing = translate({"code": "missing_parameter", "message": "m", "names": ["x"]})
        self.assertEqual((missing.field, missing.transient, missing.refresh), (None, False, True))
        for code in ("parameter_in_use", "rename_failed"):
            self.assertEqual(translate({"code": code, "message": "m"}).field, None)

    def test_format_number_cases(self):
        cases = {12: "12", 12.7: "12.7", 0.125: "0.125", 1 / 3: "0.333333", 1e-7: "1e-07", -0.0: "0",
                 100000.0: "100000", -2.5: "-2.5", 30.0000000001: "30", None: "?"}
        for value, text in cases.items():
            self.assertEqual(pp.format_number(value), text, value)

    def test_normalize_value_cases(self):
        angle = pp.normalize_value("angle", "30")
        self.assertEqual((angle.args(), angle.expected_native), ({"value": "30.0 deg"}, 30.0))
        inches = pp.normalize_value("length", "1/2 in")
        self.assertEqual(inches.args(), {"value": "1/2 in"})
        self.assertAlmostEqual(inches.expected_native, 12.7)
        self.assertEqual(pp.normalize_value("length", "12").args(), {"value": "12.0 mm"})
        self.assertEqual(pp.normalize_value("length", "12,5").args(), {"value": "12.5 mm"})
        self.assertEqual(pp.normalize_value("length", "-0").args(), {"value": "0.0 mm"})
        self.assertEqual(pp.normalize_value("number", "2").args(), {"value": 2.0})
        self.assertEqual(pp.normalize_value("angle", "45 deg").expected_native, 45.0)
        mismatch = pp.normalize_value("length", "30 deg")
        self.assertEqual((mismatch.args(), mismatch.expected_native), ({"value": "30 deg"}, None))
        formula = pp.normalize_value("length", " =a+1 ")
        self.assertEqual((formula.args(), formula.expected_native), ({"expression": "a+1"}, None))
        self.assertEqual(pp.normalize_value("length", "15", formula_row=True).args(),
                         {"value": "15.0 mm", "expression": None})
        self.assertEqual(pp.normalize_value("length", "=b * 2", formula_row=True).args(), {"expression": "b * 2"})
        for text, words in (("", "Enter a value"), ("=", "Enter a formula after ="), ("abc", "="),
                            ("10 mm + 2 mm", "Not a number"), ("1e999", "finite")):
            error = pp.normalize_value("length", text)
            self.assertIsInstance(error, pp.LocalError, text)
            self.assertIn(words, error.message, text)

    def test_controller_adapter_routes_through_panel_without_backend(self):
        panel = FakePanel()
        adapter = pp.ControllerParameterAdapter(panel)
        self.assertEqual(adapter.key(), ("doc-1", True, panel.state["parameters"], panel.state["parameter_set"]))
        self.assertEqual(adapter.revision(), "r1")
        self.assertIsNone(adapter.blocker())
        self.assertTrue(adapter.rolled_back())
        for attribute, value in (("sketch", object()), ("task", "pad"), ("pending_sketch", True),
                                 ("studio_dialog", object()), ("selecting_support", True), ("native_task", True)):
            original = getattr(panel, attribute)
            setattr(panel, attribute, value)
            self.assertEqual(adapter.blocker(), EDITING, attribute)
            setattr(panel, attribute, original)
        panel.core.busy = True
        self.assertEqual(adapter.blocker(), EDITING)
        panel.core.busy = False
        panel.state["active_sketch_edit"] = "ShaftSk"
        self.assertEqual(adapter.blocker(), EDITING)
        del panel.state["active_sketch_edit"]
        panel.state["managed"] = False
        self.assertEqual(adapter.blocker(), pp.ControllerParameterAdapter.REFERENCE)
        panel.state["managed"] = True
        panel.workspace_mode = "assembly"
        self.assertIsNone(adapter.key())
        self.assertEqual(adapter.blocker(), pp.ControllerParameterAdapter.ASSEMBLY)
        panel.workspace_mode = "part_studio"
        panel.doc = None
        self.assertIsNone(adapter.key())
        self.assertEqual(adapter.blocker(), pp.NO_DOCUMENT)
        panel.doc = object()
        # Without the backend module the adapter injects no name rule (and the dialog applies none).
        import kurtshape
        loaded = kurtshape.__dict__.pop("parameters", None)
        try:
            with patch.dict(sys.modules, {"kurtshape.parameters": None}):
                self.assertIsNone(adapter.name_pattern())
        finally:
            if loaded is not None:
                kurtshape.parameters = loaded
        # NAME_PATTERN and the usage helper come from the backend module, injected here.
        helper_calls = []
        backend = type(sys)("kurtshape.parameters")
        backend.NAME_PATTERN = re.compile(NAME_PATTERN)
        # U5's helper is usage_rows(doc, names) -> {name: list_parameters row}.
        backend.usage_rows = lambda doc, names: helper_calls.append(names) or {names[0]: USAGE_ROW}
        with patch.dict(sys.modules, {"kurtshape.parameters": backend}), \
                patch.object(kurtshape, "parameters", backend, create=True):
            self.assertEqual(adapter.name_pattern(), NAME_PATTERN)
            usage = adapter.usage("shaft_diameter")
            self.assertEqual(adapter.usage("shaft_diameter"), usage)
            self.assertEqual(helper_calls, [["shaft_diameter"]], "usage is cached per document and revision")
            panel.state["revision"] = "r2"
            adapter.usage("shaft_diameter")
            self.assertEqual(len(helper_calls), 2)
            del backend.usage_rows
            backend.NAME_PATTERN = NAME_PATTERN
            self.assertEqual(adapter.name_pattern(), NAME_PATTERN)
            panel.state["revision"] = "r3"
            self.assertEqual(adapter.usage("shaft_diameter"), usage)
            self.assertEqual(panel.dispatched, [{"op": "list_parameters", "document_id": "doc-1", "names": ["shaft_diameter"]}])
        self.assertEqual(usage["used_by"], [
            {"feature": "ShaftSk", "parameter": "Diameter", "label": "Shaft sketch · Diameter", "held": False},
            {"feature": "Tip", "parameter": None, "label": "Tip · Length", "held": True}])
        self.assertEqual(usage["used_by_parameters"], ["shoulder_diameter"])
        self.assertEqual(usage["affects"], ["Shaft sketch", "Shaft"])
        self.assertEqual(usage["parts"], ["Body", "Shank"])
        # Writes go through Panel.operation with the staged tokens; failures are translated.
        tokens = {"_document_id": "doc-1", "_expected_revision": "r3"}
        self.assertTrue(adapter.set_value("shaft_diameter", pp.normalize_value("length", "12"), tokens).ok)
        self.assertEqual(panel.operations[-1], ("edit_parameter", {"name": "shaft_diameter", "value": "12.0 mm", **tokens}))
        panel.responses.append({"code": "duplicate_parameter", "message": "dup", "name": "Shaft", "existing": "shaft"})
        outcome = adapter.create("Shaft", "length", pp.normalize_value("length", "3"), {"_document_id": "doc-1"})
        self.assertEqual((outcome.ok, outcome.field, outcome.message), (False, "name", "A parameter named shaft already exists."))
        self.assertEqual(panel.operations[-1], ("create_parameter", {"name": "Shaft", "type": "length", "value": "3.0 mm",
                                                                     "_document_id": "doc-1"}))
        panel.responses.append("early return")
        outcome = adapter.rename("flute_count", "flutes", {"_document_id": "doc-1"})
        self.assertEqual((outcome.code, outcome.transient, outcome.message), ("not_applied", True, "Roll forward first"))
        self.assertEqual(panel.operations[-1], ("rename_parameter", {"name": "flute_count", "new_name": "flutes",
                                                                     "_document_id": "doc-1"}))
        self.assertTrue(adapter.delete("flute_count", 1, tokens).ok)
        self.assertEqual(panel.operations[-1], ("delete_parameter", {"name": "flute_count", "freeze_consumers": True, **tokens}))
        adapter.notify("bad", "error")
        adapter.notify("careful", "warning")
        adapter.show_use("ShaftSk", "Diameter")
        self.assertEqual(panel.notes, [("bad", "error"), ("careful",)])
        self.assertEqual(panel.shown, ("ShaftSk", "Diameter"))

    def test_section_images_with_fonts_are_saved_to_private_evidence(self):
        fonts = support.offscreen_qt_fonts(self)
        # The formula marker is painted once and cached; repaint it with the loaded fonts.
        patcher = patch.object(pp, "_FORMULA_ICON", None)
        patcher.start()
        self.addCleanup(patcher.stop)
        section = self.make_section(height=360, stylesheet=True)
        self.adapter.failures.append({"code": "build_failed", "message": "Change not applied: the cut is empty",
                                      "feature": "Shoulder"})
        self.enter(self.edit("shaft_diameter", "-5"))
        self.pump()
        image = section.grab()
        self.assertFalse(image.isNull())
        self.assertGreater(image.width(), 0)
        if not fonts:
            return  # only the image evidence needs real glyphs
        folder = support.evidence_dir("parameter-panel")
        self.assertTrue(image.save(str(folder / "parameters-section-error.png")))
        section.revert(self.field("shaft_diameter"))
        section.clear()
        self.pump()
        self.assertTrue(section.grab().save(str(folder / "parameters-section-no-document.png")))


class SectionLayoutTests(QtFixture, unittest.TestCase):
    def make_panel(self, store, height=640):
        host = QtGui.QWidget()
        host.resize(260, height)
        layout = QtGui.QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        history = QtGui.QWidget()
        history_layout = QtGui.QVBoxLayout(history)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_layout.addWidget(QtGui.QLineEdit())
        history_layout.addWidget(QtGui.QLabel("Features (4)"))
        features = QtGui.QTreeWidget()
        features.setHeaderHidden(True)
        history_layout.addWidget(features, 1)
        history_layout.addWidget(QtGui.QLabel("End of history"))
        adapter = FakeAdapter()
        section = pp.ParameterSection(adapter)
        adapter.section = section
        section.refresh()
        parts = QtGui.QWidget()
        parts_layout = QtGui.QVBoxLayout(parts)
        parts_layout.setContentsMargins(0, 0, 0, 0)
        parts_layout.addWidget(QtGui.QLabel("Parts (1)"))
        parts_layout.addWidget(QtGui.QComboBox())
        parts_tree = QtGui.QTreeWidget()
        parts_tree.setMinimumHeight(58)
        parts_layout.addWidget(parts_tree, 1)
        splitter = QtGui.QSplitter(QtCore.Qt.Vertical)
        splitter.setObjectName("KurtShapeHistoryPartsSplit")
        splitter.setChildrenCollapsible(False)
        for widget in (history, section, parts):
            splitter.addWidget(widget)
        for index, stretch in enumerate((3, 1, 1)):
            splitter.setStretchFactor(index, stretch)
        sections = pp.SectionLayout(splitter, store)
        restored = sections.restore()
        layout.addWidget(splitter)
        self.host = host
        self.addCleanup(self.close_host, section)
        self.show_host(host)
        return splitter, sections, (history, section, parts), restored

    def close_host(self, section):
        section.close()
        self.destroy(self.host)

    def drag(self, splitter, index, dy):
        handle = splitter.handle(index)
        start = handle.rect().center()
        QtTest.QTest.mousePress(handle, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, start)
        QtTest.QTest.mouseMove(handle, start + QtCore.QPoint(0, dy))
        QtTest.QTest.mouseRelease(handle, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, start + QtCore.QPoint(0, dy))
        self.pump()

    def test_three_noncollapsible_sections_respect_size_hints(self):
        store = DictStore()
        splitter, sections, widgets, restored = self.make_panel(store)
        self.assertEqual(restored, list(pp.DEFAULT_SIZES))
        self.assertEqual(splitter.count(), 3)
        self.assertEqual([splitter.widget(i) for i in range(3)], list(widgets))
        self.assertEqual(splitter.orientation(), QtCore.Qt.Vertical)
        # isCollapsible() reports Qt's per-widget "Default" as truthy; the squeeze
        # below is what proves no section collapses.
        self.assertFalse(splitter.childrenCollapsible())
        section = widgets[1]
        rows = section.minimumSizeHint().height()
        self.assertGreaterEqual(rows, section.header.sizeHint().height() + 2 * section._row_height())
        section.adapter.state["parameter_set"] = {"id": "Params", "label": "Params", "state": ["Invalid"],
                                                  "error": {"name": "shoulder_diameter", "message": "Unit mismatch"}}
        section.refresh()
        self.assertFalse(section.banner.isHidden())
        banner = section.minimumSizeHint().height()
        self.assertGreater(banner, rows, "a visible state banner needs room")
        section._show_line("shaft_diameter: rejected · kept 12 mm")
        self.assertGreater(section.minimumSizeHint().height(), banner, "a visible error line needs room")
        total = sum(splitter.sizes())
        for squeezed in range(3):
            sizes = [total] * 3
            sizes[squeezed] = 1
            splitter.setSizes(sizes)
            self.pump()
            for index, widget in enumerate(widgets):
                self.assertGreaterEqual(splitter.sizes()[index], widget.minimumSizeHint().height(),
                                        (squeezed, index, splitter.sizes()))
        self.assertEqual(store.writes, [], "programmatic sizes never write")

    def test_drag_saves_only_after_debounce(self):
        store = DictStore()
        written_at = []
        store_set = store.set
        store.set = lambda text: (written_at.append(time.monotonic()), store_set(text))
        splitter, sections, widgets, restored = self.make_panel(store)
        self.assertEqual(pp.SAVE_DELAY_MS, 400)
        self.assertEqual(sections.timer.interval(), pp.SAVE_DELAY_MS)
        self.assertTrue(sections.timer.isSingleShot())
        splitter.setSizes([400, 150, 150])
        self.pump()
        before = splitter.sizes()
        self.drag(splitter, 2, 40)
        self.assertNotEqual(splitter.sizes(), before, "the QTest drag moved the handle")
        self.assertTrue(sections.timer.isActive())
        self.assertEqual(store.writes, [], "nothing is written while the debounce timer runs")
        last_move = time.monotonic()  # taken before the last drag starts the timer again
        self.drag(splitter, 2, -10)
        self.assertEqual(store.writes, [])
        deadline = time.monotonic() + 5
        while sections.timer.isActive() and time.monotonic() < deadline:
            self.wait(50)
        self.assertEqual(store.writes, [",".join(str(size) for size in splitter.sizes())])
        # Coarse Qt timers may fire up to 5 % early; never sooner than that after the last move.
        self.assertGreaterEqual(written_at[0] - last_move, 0.9 * pp.SAVE_DELAY_MS / 1000)
        sections.flush()
        self.assertEqual(len(store.writes), 1, "flush has nothing left to write")

    def test_flush_writes_remembered_sizes_without_touching_the_splitter(self):
        store = DictStore()
        splitter = QtGui.QSplitter(QtCore.Qt.Vertical)
        for _ in range(3):
            splitter.addWidget(QtGui.QWidget())
        sections = pp.SectionLayout(splitter, store)
        sections.flush()
        self.assertEqual(store.writes, [])
        splitter.resize(200, 500)
        splitter.setSizes([300, 100, 100])
        splitter.splitterMoved.emit(300, 1)
        remembered = ",".join(str(size) for size in splitter.sizes())
        self.assertTrue(sections.timer.isActive())
        shiboken6.delete(splitter)
        self.assertFalse(shiboken6.isValid(splitter))
        sections.flush()
        self.assertEqual(store.writes, [remembered])
        self.wait(pp.SAVE_DELAY_MS + 150)
        self.assertEqual(store.writes, [remembered], "the debounce timer finds nothing left to write")

    def test_restore_scales_saved_sizes_proportionally(self):
        stored = [375, 168, 113]
        splitter = QtGui.QSplitter(QtCore.Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        for _ in range(3):
            widget = QtGui.QWidget()
            widget.setMinimumHeight(20)
            splitter.addWidget(widget)
        for index, stretch in enumerate((3, 1, 1)):
            splitter.setStretchFactor(index, stretch)
        store = DictStore(",".join(map(str, stored)))
        self.assertEqual(pp.SectionLayout(splitter, store).restore(), stored)
        splitter.setFixedSize(220, 600)
        self.addCleanup(self.destroy, splitter)
        self.show_host(splitter)
        sizes = splitter.sizes()
        total = sum(sizes)
        self.assertLess(total, sum(stored))
        for size, saved in zip(sizes, stored):
            self.assertLessEqual(abs(size - saved * total / sum(stored)), 2, (sizes, stored))
        splitter.close()
        self.assertEqual(store.writes, [])

    def test_malformed_or_wrong_count_uses_defaults(self):
        splitter = QtGui.QSplitter(QtCore.Qt.Vertical)
        self.addCleanup(self.destroy, splitter)
        for _ in range(3):
            splitter.addWidget(QtGui.QWidget())
        for text in ("", "bogus,1", "1,2", "100,100,100,100", "0,100,100", "100,100,30000", "a,b,c", "1.5,2,3", None):
            store = DictStore(text)
            self.assertEqual(pp.SectionLayout(splitter, store).restore(), list(pp.DEFAULT_SIZES), text)
            self.assertEqual(store.writes, [])
        self.assertEqual(pp.SectionLayout(splitter, DictStore("300, 120,150")).restore(), [300, 120, 150])
        two = QtGui.QSplitter(QtCore.Qt.Vertical)
        self.addCleanup(self.destroy, two)
        two.addWidget(QtGui.QWidget())
        two.addWidget(QtGui.QWidget())
        self.assertIsNone(pp.SectionLayout(two, DictStore("bogus")).restore(), "defaults only fit three sections")

    def test_saved_sizes_survive_a_fresh_process(self):
        home = support.scratch(self, prefix="pp-") / "home"
        home.mkdir()
        shared = Path(os.environ["FREECAD_USER_HOME"]).resolve()
        self.assertFalse(home.resolve().is_relative_to(shared))

        def config_hashes(folder):
            return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in folder.rglob("*.cfg")}

        shared_before = config_hashes(shared)
        environment = dict(os.environ, FREECAD_USER_HOME=str(home), QT_QPA_PLATFORM="offscreen")
        source = str(ROOT / "src")

        def run(script):
            process = subprocess.run([sys.executable, "-B", "-c", script, source], capture_output=True, text=True,
                                     env=environment, timeout=180, cwd=str(home),
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            return json.loads(process.stdout.strip().splitlines()[-1])

        written = run(SUBPROCESS_PRELUDE + WRITER)
        self.assertEqual(written["writes"], 1)
        self.assertEqual(written["stored"], ",".join(map(str, written["sizes"])))
        self.assertTrue(Path(written["config"]).resolve().is_relative_to(home.resolve()), written["config"])
        read = run(SUBPROCESS_PRELUDE + READER)
        self.assertEqual(read["stored"], written["stored"])
        self.assertEqual(read["writes"], 0)
        for restored, saved in zip(read["restored"], written["sizes"]):
            self.assertLessEqual(abs(restored - saved), 2, (read, written))
        self.assertTrue(any(pp.LAYOUT_KEY in path.read_text(encoding="utf-8", errors="replace")
                            for path in home.rglob("*.cfg")))
        self.assertEqual(config_hashes(shared), shared_before, "the runner's shared profile is never written")


SUBPROCESS_PRELUDE = """
import json, sys, time
sys.path.insert(0, sys.argv[1])
import FreeCAD as App
from PySide import QtCore, QtGui
from kurtshape.parameter_panel import PreferenceStore, SectionLayout
app = QtGui.QApplication.instance() or QtGui.QApplication([])
splitter = QtGui.QSplitter(QtCore.Qt.Vertical)
splitter.setChildrenCollapsible(False)
for _ in range(3):
    widget = QtGui.QWidget()
    widget.setMinimumHeight(20)
    splitter.addWidget(widget)
splitter.setFixedSize(200, 604)
layout = SectionLayout(splitter, PreferenceStore())
layout.restore()
splitter.show()
for _ in range(5):
    app.processEvents()
"""

WRITER = """
splitter.setSizes([300, 150, 150])
app.processEvents()
splitter.splitterMoved.emit(300, 1)
deadline = time.monotonic() + 10
while layout.writes == 0 and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(0.02)
print(json.dumps({"sizes": splitter.sizes(), "writes": layout.writes, "stored": PreferenceStore().get(),
                  "config": App.getUserConfigDir()}))
"""

READER = """
print(json.dumps({"restored": splitter.sizes(), "writes": layout.writes, "stored": PreferenceStore().get(),
                  "config": App.getUserConfigDir()}))
"""



class ControllerPanel:
    """About fifteen lines of Panel over a headless Controller: operation() pops the tokens, inspects
    afresh, dispatches and keeps the error object, as Panel._operation does."""

    workspace_mode, task, studio_dialog, pending_sketch, selecting_support = "part_studio", None, None, False, False

    def __init__(self, core, state):
        self.core, self.state, self.last_operation_error, self.notes = core, state, None, []
        self.message = QtGui.QLabel()

    def document(self):
        return self.core.documents[self.state["document_id"]]

    def active_sketch(self):
        return None

    def native_feature_task_active(self):
        return False

    def notify(self, message, *args):
        self.notes.append(message)

    def operation(self, op, **args):
        self.last_operation_error = None
        expected, document = args.pop("_expected_revision", None), args.pop("_document_id", None)
        self.state = self.core.dispatch({"op": "inspect", "document_id": self.state["document_id"]})["result"]
        if document and document != self.state["document_id"]:
            self.last_operation_error = {"code": "document_changed", "message": "project changed"}
            return None
        response = self.core.dispatch({"op": op, "document_id": self.state["document_id"],
                                       "expected_revision": expected or self.state["revision"], **args})
        if not response["ok"]:
            self.last_operation_error = response["error"]
            return None
        self.state = response["result"]
        return self.state


class ParameterAdapterTranslationTests(unittest.TestCase):
    """ControllerParameterAdapter against the real parameters backend: GUI text in, wire requests out,
    error codes back to fields. Undo, rollback and inspect filtering belong to ParameterTests."""

    def setUp(self):
        import FreeCAD as App
        from kurtshape.core import Controller
        self.App = App
        self.initial = set(App.listDocuments())
        support.isolated_session(self, prefix="parameter-adapter-")
        self.core = Controller()
        self.addCleanup(self.close_all)
        state = self.core.dispatch({"op": "new", "name": "Adapter"})["result"]
        self.panel = ControllerPanel(self.core, state)
        self.adapter = pp.ControllerParameterAdapter(self.panel)

    def close_all(self):
        self.core.close()
        for name in set(self.App.listDocuments()) - self.initial:
            self.App.closeDocument(name)

    def row(self, name):
        return next(row for row in self.panel.state["parameters"] if row["name"] == name)

    def create(self, name, kind, text, **tokens):
        return self.adapter.create(name, kind, pp.normalize_value(kind, text), tokens)

    def test_gui_angle_text_is_degrees(self):
        self.assertTrue(self.create("tilt", "angle", "30").ok)
        row = self.row("tilt")
        self.assertAlmostEqual(row["native_value"], 30.0)
        self.assertAlmostEqual(row["value"], math.pi / 6)
        self.assertEqual(pp.unit_text(row), "°")

    def test_equals_sends_expression_and_literal_replaces_formula_in_one_request(self):
        self.assertTrue(self.create("shaft", "length", "10").ok)
        self.assertTrue(self.create("shoulder", "length", "=shaft + 2 mm").ok)
        self.assertEqual((self.row("shoulder")["expression"], self.row("shoulder")["native_value"]), ("shaft + 2 mm", 12.0))
        dispatched = []
        dispatch = self.core.dispatch
        with patch.object(self.core, "dispatch", side_effect=lambda request: (dispatched.append(request), dispatch(request))[1]):
            outcome = self.adapter.set_value("shoulder", pp.normalize_value("length", "14", formula_row=True), {})
        self.assertTrue(outcome.ok, outcome)
        edits = [request for request in dispatched if request["op"] == "edit_parameter"]
        self.assertEqual(len(edits), 1)
        self.assertEqual({key: edits[0][key] for key in ("value", "expression")}, {"value": "14.0 mm", "expression": None})
        self.assertEqual((self.row("shoulder")["expression"], self.row("shoulder")["native_value"]), (None, 14.0))

    def test_negative_length_is_stored_exactly_or_rejected(self):
        self.assertTrue(self.create("depth", "length", "8").ok)
        outcome = self.adapter.set_value("depth", pp.normalize_value("length", "-3"), {})
        if outcome.ok:
            self.assertEqual(self.row("depth")["native_value"], -3.0)
        else:
            self.assertEqual((outcome.field, self.row("depth")["native_value"]), ("value", 8.0))
        self.assertNotEqual(self.row("depth")["native_value"], 0.0, "never shown as 0")

    def test_angle_beyond_full_turn_is_rejected(self):
        self.assertTrue(self.create("tilt", "angle", "30").ok)
        outcome = self.adapter.set_value("tilt", pp.normalize_value("angle", "400"), {})
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.field, "value")
        self.assertEqual(self.row("tilt")["native_value"], 30.0)

    def test_unit_symbol_name_reports_plain_reason(self):
        outcome = self.create("t", "length", "2")
        self.assertFalse(outcome.ok)
        self.assertEqual((outcome.code, outcome.field), ("invalid_parameter_name", "name"))
        self.assertIn("unit", outcome.message)

    def test_error_codes_map_to_fields_and_transience(self):
        self.assertTrue(self.create("width", "length", "20").ok)
        stale = self.adapter.set_value("width", pp.normalize_value("length", "21"), {"_expected_revision": "not-current"})
        self.assertEqual((stale.code, stale.transient, stale.field), ("stale_revision", True, None))
        duplicate = self.create("width", "length", "5")
        self.assertEqual((duplicate.code, duplicate.field, duplicate.transient), ("duplicate_parameter", "name", False))
        wrong = self.adapter.set_value("width", pp.normalize_value("length", "30 deg"), {})
        self.assertEqual((wrong.code, wrong.field, wrong.transient), ("invalid_argument", "value", False))
        self.assertTrue(self.create("tilt", "angle", "30").ok)
        mismatch = self.adapter.set_value("width", pp.normalize_value("length", "=tilt"), {})
        self.assertEqual((mismatch.code, mismatch.field, mismatch.transient), ("unit_mismatch", "value", False))
        changed = self.adapter.set_value("width", pp.normalize_value("length", "22"), {"_document_id": "elsewhere"})
        self.assertEqual((changed.code, changed.transient), ("document_changed", True))
        self.assertEqual(self.row("width")["native_value"], 20.0)

    def test_usage_is_read_without_a_dispatch_and_set_state_from_inspect(self):
        self.assertTrue(self.create("width", "length", "20").ok)
        sketch = self.core.dispatch({"op": "sketch_rectangle", "document_id": self.panel.state["document_id"],
                                     "expected_revision": self.panel.state["revision"], "id": "Base", "width": 20,
                                     "height": 10})
        self.assertTrue(sketch["ok"], sketch)
        self.panel.state = sketch["result"]
        feature = next(row for row in self.panel.state["features"] if row["id"] == "Base")
        dimension = next(name for name, info in feature["parameters"].items() if info.get("value") == 20.0)
        bound = self.core.dispatch({"op": "set_expression", "document_id": self.panel.state["document_id"],
                                    "expected_revision": self.panel.state["revision"], "feature": "Base",
                                    "parameter": dimension, "expression": self.row("width")["expression_ref"]})
        self.assertTrue(bound["ok"], bound)
        self.panel.state = bound["result"]
        with patch.object(self.core, "dispatch", side_effect=AssertionError("usage must not dispatch")):
            usage = self.adapter.usage("width")
        self.assertEqual([(entry["feature"], entry["parameter"]) for entry in usage["used_by"]], [("Base", dimension)])
        key = self.adapter.key()
        self.assertEqual((key[0], key[1]), (self.panel.state["document_id"], True))
        self.assertIsNone(self.adapter.evaluation(key[3]), "an up-to-date set shows no banner")
        self.assertEqual(self.adapter.evaluation({"state": "needs_rebuild", "error": None})["kind"], "touched")
        self.assertEqual(self.adapter.evaluation({"state": "invalid", "error": {"name": "width", "message": "bad"}})["kind"],
                         "failed")


if __name__ == "__main__":
    unittest.main()
