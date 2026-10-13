"""Qt cursor stack ownership and appearance reuse, without a native viewer."""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import FreeCAD  # noqa: F401 -- provides bundled PySide compatibility imports.
from PySide import QtCore, QtGui

from kurtshape.sketch_cursor import SketchCursor


class QOpenGLWidget(QtGui.QWidget):
    """Cursor behavior is QWidget behavior; avoid an offscreen OpenGL context."""


class CursorRelay(QtCore.QObject):
    def __init__(self, helper):
        super().__init__()
        self.helper = helper

    def eventFilter(self, watched, event):
        return self.helper.event(watched, event)


class SketchCursorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtGui.QApplication.instance() or QtGui.QApplication([])

    def setUp(self):
        self.assertIsNone(self.app.overrideCursor())
        self.window = QtGui.QWidget()
        layout = QtGui.QVBoxLayout(self.window)
        self.viewer = QtGui.QWidget()
        viewer_layout = QtGui.QVBoxLayout(self.viewer)
        self.viewport = QOpenGLWidget()
        viewer_layout.addWidget(self.viewport)
        self.outside = QtGui.QPushButton("Outside the viewport")
        layout.addWidget(self.viewer)
        layout.addWidget(self.outside)
        self.window.show()
        self.window.activateWindow()
        self.app.processEvents()
        self.panel = SimpleNamespace(main=self.window, active_sketch=lambda: object())
        self.helper = SketchCursor(self.panel)
        self.relay = CursorRelay(self.helper)
        self.app.installEventFilter(self.relay)
        self.pointer = patch.object(QtGui.QApplication, "widgetAt", return_value=self.viewport)
        self.pointer.start()

    def tearDown(self):
        self.app.removeEventFilter(self.relay)
        self.helper.close()
        # Tests that deliberately exercise foreign stack entries clean them
        # up first, then let the helper restore its own entry.
        while self.app.overrideCursor() is not None:
            self.app.restoreOverrideCursor()
        self.helper._cleanup()
        self.pointer.stop()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    @staticmethod
    def cursor(color="red", hotspot=(2, 3), ratio=1):
        pixmap = QtGui.QPixmap(24, 24)
        pixmap.fill(QtGui.QColor(color))
        pixmap.setDevicePixelRatio(ratio)
        return QtGui.QCursor(pixmap, *hotspot)

    def start(self):
        self.viewport.setCursor(self.cursor())
        self.helper.sync("Sketcher_CreatePolyline")
        self.assertTrue(self.helper.counters["owned"])

    def test_identical_native_images_reuse_one_override_and_keep_widget_cursor(self):
        self.start()
        identity = self.app.overrideCursor().pixmap().cacheKey()
        native_keys = set()
        for _ in range(200):
            native = self.cursor()
            native_keys.add(native.pixmap().cacheKey())
            self.viewport.setCursor(native)
            self.assertEqual(self.viewport.cursor().pixmap().cacheKey(), native.pixmap().cacheKey())
            self.assertEqual(self.app.overrideCursor().pixmap().cacheKey(), identity)
        self.assertEqual(len(native_keys), 200)
        self.assertEqual(self.helper.counters["pushes"], 1)
        self.assertEqual(self.helper.counters["changes"], 0)
        self.assertEqual(self.helper.counters["cache_size"], 1)

    def test_native_icon_hotspot_and_dpr_changes_preserve_exact_appearance(self):
        self.start()
        first = self.app.overrideCursor().pixmap().cacheKey()
        for color, hotspot, ratio in (("blue", (2, 3), 1), ("blue", (7, 9), 1), ("blue", (7, 9), 2)):
            native = self.cursor(color, hotspot, ratio)
            self.viewport.setCursor(native)
            shown = self.app.overrideCursor()
            self.assertEqual(shown.pixmap().toImage(), native.pixmap().toImage())
            self.assertEqual(shown.hotSpot(), native.hotSpot())
            self.assertEqual(shown.pixmap().devicePixelRatioF(), ratio)
        self.viewport.setCursor(self.cursor())
        self.assertEqual(self.app.overrideCursor().pixmap().cacheKey(), first)
        self.assertEqual(self.helper.counters["changes"], 4)

    def test_inherited_viewer_cursor_changes_update_before_next_mouse_move(self):
        self.assertFalse(self.viewport.testAttribute(QtCore.Qt.WA_SetCursor))
        self.viewer.setCursor(self.cursor())
        self.helper.sync("Sketcher_CreatePolyline")
        before = self.helper.counters["cursor_events"]
        for color, hotspot, ratio in (("blue", (7, 9), 2), ("red", (2, 3), 1)):
            native = self.cursor(color, hotspot, ratio)
            # This sends CursorChange only to the viewer ancestor. Assert
            # immediately: no move, idle tick or event-loop pump can fix lag.
            self.viewer.setCursor(native)
            shown = self.app.overrideCursor()
            self.assertIsNotNone(shown)
            self.assertEqual(shown.pixmap().toImage(), native.pixmap().toImage())
            self.assertEqual(shown.hotSpot(), native.hotSpot())
            self.assertEqual(shown.pixmap().devicePixelRatioF(), ratio)
            self.assertFalse(self.viewport.testAttribute(QtCore.Qt.WA_SetCursor))
            self.assertEqual(self.viewport.cursor().pixmap().cacheKey(), native.pixmap().cacheKey())
        self.assertEqual(self.helper.counters["cursor_events"] - before, 2)
        self.assertEqual(self.helper.counters["changes"], 2)

    def test_ancestor_updates_honor_explicit_child_cursor_and_ignore_siblings(self):
        self.start()
        original = self.app.overrideCursor().pixmap().cacheKey()
        self.viewer.setCursor(self.cursor("blue"))
        self.assertEqual(self.app.overrideCursor().pixmap().cacheKey(), original)
        events = self.helper.counters["cursor_events"]
        self.outside.setCursor(self.cursor("green"))
        self.assertEqual(self.helper.counters["cursor_events"], events)
        self.assertEqual(self.app.overrideCursor().pixmap().cacheKey(), original)
        self.viewport.unsetCursor()
        self.assertEqual(self.app.overrideCursor().pixmap().toImage(), self.viewer.cursor().pixmap().toImage())

    def test_cursor_cache_remains_bounded(self):
        self.start()
        for index in range(100):
            self.viewport.setCursor(self.cursor(QtGui.QColor(index, 21, 49)))
        self.assertEqual(self.helper.counters["cache_size"], self.helper.CACHE_LIMIT)

    def test_preexisting_override_is_never_covered_or_removed(self):
        self.app.setOverrideCursor(QtCore.Qt.WaitCursor)
        self.viewport.setCursor(self.cursor())
        self.helper.sync("Sketcher_CreateCircle")
        self.assertFalse(self.helper.counters["owned"])
        self.helper.close()
        self.assertEqual(self.app.overrideCursor().shape(), QtCore.Qt.WaitCursor)
        self.app.restoreOverrideCursor()

    def test_foreign_override_above_ours_is_preserved_until_owned_entry_resurfaces(self):
        self.start()
        # Even the exact widget cursor is foreign: our cached cursor owns an
        # independent pixmap identity, so equal pixels cannot confuse cleanup.
        foreign = self.viewport.cursor()
        self.app.setOverrideCursor(foreign)
        self.helper.close()
        self.assertTrue(self.helper.counters["deferred_release"])
        self.assertEqual(self.app.overrideCursor().pixmap().cacheKey(), foreign.pixmap().cacheKey())
        self.app.restoreOverrideCursor()
        self.helper._cleanup()
        self.assertIsNone(self.app.overrideCursor())
        self.assertFalse(self.helper.counters["owned"])

    def test_foreign_wait_during_drawing_is_not_changed_by_new_native_icon(self):
        self.start()
        self.app.setOverrideCursor(QtCore.Qt.WaitCursor)
        self.viewport.setCursor(self.cursor("blue"))
        self.assertEqual(self.app.overrideCursor().shape(), QtCore.Qt.WaitCursor)
        self.app.restoreOverrideCursor()
        self.helper.sync("Sketcher_CreatePolyline")
        self.assertEqual(self.app.overrideCursor().pixmap().toImage(), self.viewport.cursor().pixmap().toImage())

    def test_leave_command_end_edit_exit_and_deactivation_restore(self):
        for reason in ("leave", "end", "edit", "deactivate"):
            with self.subTest(reason=reason):
                self.panel.active_sketch = lambda: object()
                self.start()
                if reason == "leave":
                    self.helper.event(self.viewport, QtCore.QEvent(QtCore.QEvent.Leave))
                elif reason == "end":
                    self.helper.sync(None)
                elif reason == "edit":
                    self.panel.active_sketch = lambda: None
                    self.helper.sync("Sketcher_CreatePolyline")
                else:
                    self.helper.event(self.window, QtCore.QEvent(QtCore.QEvent.WindowDeactivate))
                self.assertIsNone(self.app.overrideCursor())

    def test_escape_and_plain_right_click_release_but_preserve_navigation_chords(self):
        self.start()
        pos = QtCore.QPointF(5, 5)
        for modifiers, buttons in ((QtCore.Qt.ControlModifier, QtCore.Qt.RightButton),
                                   (QtCore.Qt.NoModifier, QtCore.Qt.RightButton | QtCore.Qt.LeftButton)):
            event = QtGui.QMouseEvent(QtCore.QEvent.MouseButtonPress, pos, pos,
                                     QtCore.Qt.RightButton, buttons, modifiers)
            self.assertFalse(self.helper.event(self.viewport, event))
            self.assertIsNotNone(self.app.overrideCursor())
        event = QtGui.QMouseEvent(QtCore.QEvent.MouseButtonPress, pos, pos,
                                 QtCore.Qt.RightButton, QtCore.Qt.RightButton, QtCore.Qt.NoModifier)
        self.assertFalse(self.helper.event(self.viewport, event))
        self.assertIsNone(self.app.overrideCursor())
        self.start()
        event = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Escape, QtCore.Qt.NoModifier)
        self.assertFalse(self.helper.event(self.viewport, event))
        self.assertIsNone(self.app.overrideCursor())

    def test_nonviewport_click_and_modal_window_release(self):
        self.start()
        pos = QtCore.QPointF(5, 5)
        event = QtGui.QMouseEvent(QtCore.QEvent.MouseButtonPress, pos, pos,
                                 QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier)
        self.assertFalse(self.helper.event(self.outside, event))
        self.assertIsNone(self.app.overrideCursor())
        self.start()
        dialog = QtGui.QDialog(self.window)
        dialog.setModal(True)
        dialog.show()
        self.app.processEvents()
        self.helper.sync("Sketcher_CreatePolyline")
        self.assertIsNone(self.app.overrideCursor())
        dialog.close()

    def test_stock_cursor_releases_and_does_not_change_widget_cursor(self):
        self.start()
        self.viewport.setCursor(QtCore.Qt.CrossCursor)
        self.assertIsNone(self.app.overrideCursor())
        self.assertEqual(self.viewport.cursor().shape(), QtCore.Qt.CrossCursor)


if __name__ == "__main__":
    unittest.main(verbosity=2)
