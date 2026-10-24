"""Assembly UX item 1: additive click selection (selection_mode).

The native click semantics are checked in the private GUI recipe
``additive-selection``; these cases pin the preference, the pick helpers and
the filter's rewrite/gating decisions with recorded Qt events.
"""
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import support  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
from kurtshape import selection_mode


def fake_panel(plane_picking=False, section_picking=False, **flags):
    values = dict(pending_sketch=False, selecting_support=False, studio_selection_callback=None)
    values.update(flags)
    return SimpleNamespace(sketch_plane_editor=SimpleNamespace(picking=plane_picking),
                           section_view=SimpleNamespace(picking=section_picking),
                           core=SimpleNamespace(busy=False), **values)


class SelectionModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide import QtGui
        cls.app = QtGui.QApplication.instance() or QtGui.QApplication([])

    def setUp(self):
        self.parameters = App.ParamGet(selection_mode.PREFERENCES)
        self.parameters.RemBool(selection_mode.KEY)
        self.addCleanup(self.parameters.RemBool, selection_mode.KEY)

    def test_preference_defaults_on_and_persists(self):
        self.assertTrue(selection_mode.enabled())
        selection_mode.set_enabled(False)
        self.assertFalse(selection_mode.enabled())
        self.assertFalse(self.parameters.GetBool(selection_mode.KEY, True))
        selection_mode.set_enabled(True)
        self.assertTrue(selection_mode.enabled())

    def test_pick_helpers(self):
        self.assertTrue(selection_mode.picks_geometry({"Object": "Box", "Component": "Face3"}))
        self.assertTrue(selection_mode.picks_geometry({"Object": "Assembly", "Component": "Left.Edge2"}))
        for hit in (None, {}, {"Object": "Box", "Component": ""}, {"Object": "", "Component": "Face1"}):
            self.assertFalse(selection_mode.picks_geometry(hit), hit)
        widget = SimpleNamespace(devicePixelRatioF=lambda: 2.0)
        view = SimpleNamespace(getSize=lambda: (800, 600))
        point = SimpleNamespace(x=lambda: 10, y=lambda: 20)
        self.assertEqual(selection_mode.native_position(widget, view, point), (20, 559))
        from PySide import QtGui
        self.assertFalse(selection_mode.is_viewer_surface(QtGui.QWidget()))
        self.assertFalse(selection_mode.is_viewer_surface(object()))

    def recorder(self):
        from PySide import QtGui

        class Recorder(QtGui.QWidget):
            def __init__(self):
                super().__init__()
                self.events = []

            def event(self, event):
                if event.type() in (event.Type.MouseButtonPress, event.Type.MouseButtonRelease,
                                    event.Type.MouseMove, event.Type.MouseButtonDblClick):
                    self.events.append((event.type(), event.modifiers()))
                    return True
                return super().event(event)
        return Recorder()

    def mouse(self, kind, modifiers=None, button=None, buttons=None):
        from PySide import QtCore, QtGui
        button = QtCore.Qt.LeftButton if button is None else button
        buttons = button if buttons is None else buttons
        return QtGui.QMouseEvent(kind, QtCore.QPointF(40, 30), QtCore.QPointF(40, 30), button, buttons,
                                 QtCore.Qt.NoModifier if modifiers is None else modifiers)

    def controller(self, panel=None):
        controller = selection_mode.install(None)
        from PySide import QtGui
        QtGui.QApplication.instance().removeEventFilter(controller)  # driven directly below
        controller.panel = panel or fake_panel()
        return controller

    def test_plain_click_on_geometry_is_resent_with_ctrl(self):
        from PySide import QtCore
        widget, controller = self.recorder(), self.controller()
        with patch.object(selection_mode, "is_viewer_surface", return_value=True), \
                patch.object(type(controller), "native_owned", return_value=False), \
                patch.object(type(controller), "hit", return_value={"Object": "Box", "Component": "Face6"}):
            self.assertTrue(controller.eventFilter(widget, self.mouse(QtCore.QEvent.MouseButtonPress)))
            self.assertTrue(controller.eventFilter(widget, self.mouse(QtCore.QEvent.MouseMove, buttons=QtCore.Qt.LeftButton,
                                                                      button=QtCore.Qt.NoButton)))
            self.assertTrue(controller.eventFilter(widget, self.mouse(QtCore.QEvent.MouseButtonRelease,
                                                                      buttons=QtCore.Qt.NoButton)))
        self.assertEqual([kind for kind, _ in widget.events],
                         [QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseMove, QtCore.QEvent.MouseButtonRelease])
        self.assertTrue(all(modifiers & QtCore.Qt.ControlModifier for _, modifiers in widget.events))
        self.assertIsNone(controller.rewriting)
        self.assertEqual(controller.rewritten, 1)

    def test_empty_space_modifiers_and_other_buttons_stay_native(self):
        from PySide import QtCore
        widget, controller = self.recorder(), self.controller()
        with patch.object(selection_mode, "is_viewer_surface", return_value=True), \
                patch.object(type(controller), "native_owned", return_value=False):
            with patch.object(type(controller), "hit", return_value=None):
                self.assertFalse(controller.eventFilter(widget, self.mouse(QtCore.QEvent.MouseButtonPress)))
                self.assertFalse(controller.eventFilter(widget, self.mouse(QtCore.QEvent.MouseButtonRelease,
                                                                           buttons=QtCore.Qt.NoButton)))
            with patch.object(type(controller), "hit", return_value={"Object": "Box", "Component": "Face6"}):
                for modifiers in (QtCore.Qt.ShiftModifier, QtCore.Qt.ControlModifier):
                    self.assertFalse(controller.eventFilter(widget, self.mouse(QtCore.QEvent.MouseButtonPress, modifiers)))
                self.assertFalse(controller.eventFilter(widget, self.mouse(QtCore.QEvent.MouseButtonPress,
                                                                           button=QtCore.Qt.RightButton)))
        self.assertEqual(widget.events, [])
        self.assertEqual(controller.rewritten, 0)

    def test_pickers_sketches_and_the_preference_keep_native_clicks(self):
        from PySide import QtCore
        cases = [fake_panel(pending_sketch=True), fake_panel(selecting_support=True),
                 fake_panel(studio_selection_callback=lambda *args: None),
                 fake_panel(plane_picking=True), fake_panel(section_picking=True)]
        for panel in cases:
            self.assertTrue(self.controller(panel).native_owned())
        busy = fake_panel()
        busy.core.busy = True
        self.assertTrue(self.controller(busy).native_owned())
        widget, controller = self.recorder(), self.controller()
        with patch.object(selection_mode, "is_viewer_surface", return_value=True), \
                patch.object(type(controller), "hit", return_value={"Object": "Box", "Component": "Face6"}):
            selection_mode.set_enabled(False)
            self.assertTrue(controller.native_owned())
            self.assertFalse(controller.eventFilter(widget, self.mouse(QtCore.QEvent.MouseButtonPress)))
        self.assertEqual(widget.events, [])

    def test_non_viewer_widgets_are_ignored(self):
        from PySide import QtCore
        widget, controller = self.recorder(), self.controller()
        with patch.object(type(controller), "native_owned", return_value=False), \
                patch.object(type(controller), "hit", return_value={"Object": "Box", "Component": "Face6"}):
            self.assertFalse(controller.eventFilter(widget, self.mouse(QtCore.QEvent.MouseButtonPress)))
        self.assertEqual(widget.events, [])


if __name__ == "__main__":
    unittest.main()
