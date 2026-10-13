"""Small shaded command labels anchored below toolbar symbols.

This is presentation only: the popup takes no focus and installs no selection or
command callbacks. Native tooltips remain available for unregistered controls.
"""
from __future__ import annotations

from PySide import QtCore, QtGui
from shiboken6 import isValid


class ToolbarLabels(QtCore.QObject):
    """Own one delayed, screen-bounded tooltip for a window's toolbar buttons."""

    def __init__(self, main, delay_ms=350):
        super().__init__(main)
        self.main = main
        self._buttons = {}
        self._toolbars = {}
        self._pending_scans = set()
        self._pending = None
        self._showing = None
        self._closed = False
        self.popup = QtGui.QLabel(main, QtCore.Qt.ToolTip | QtCore.Qt.FramelessWindowHint)
        self.popup.setObjectName("KurtShapeToolbarLabel")
        self.popup.setTextFormat(QtCore.Qt.PlainText)
        self.popup.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
        self.popup.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.popup.setFocusPolicy(QtCore.Qt.NoFocus)
        self.popup.hide()
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(max(0, int(delay_ms)))
        self.timer.timeout.connect(self._show_pending)
        self._app = QtGui.QApplication.instance()
        self._app.installEventFilter(self)
        main.destroyed.connect(self.close)

    def register(self, button, label, shortcut=""):
        """Keep action names intact; suppress only this button's native tooltip."""
        if self._closed or button is None or not isValid(button):
            return
        label = str(label).replace("&&", "\0").replace("&", "").replace("\0", "&").strip()
        if not label:
            return
        key = id(button)
        if key not in self._buttons:
            # Keeping the wrapper alive avoids losing QAction-generated toolbar
            # children to Python GC; destruction removes it and isValid guards
            # the C++ lifetime. No widget is captured by the signal callback.
            button.destroyed.connect(lambda *_args, token=key: self._forget_button(token))
        self._buttons[key] = (button, label, str(shortcut).strip())
        if not button.accessibleName():
            button.setAccessibleName(label)

    def watch_toolbar(self, bar):
        """Register existing and future QToolButtons, including Qt overflow."""
        if self._closed or bar is None or not isValid(bar):
            return
        key = id(bar)
        if key not in self._toolbars:
            self._toolbars[key] = bar
            bar.destroyed.connect(lambda *_args, token=key: self._toolbars.pop(token, None))
        self._scan_toolbar(bar)

    def _scan_toolbar(self, bar):
        if self._closed or not isValid(bar):
            return
        for button in bar.findChildren(QtGui.QToolButton):
            action = button.defaultAction()
            if action is not None:
                label = action.text()
                shortcut = action.shortcut().toString(QtGui.QKeySequence.NativeText)
                if not shortcut:
                    shortcut = self._buttons.get(id(button), (None, "", ""))[2]
            else:
                label = button.accessibleName() or button.text()
                shortcut = ""
            if not label and button.objectName() == "qt_toolbar_ext_button":
                label = "More tools"
            if not label:
                label = button.toolTip().split("\n", 1)[0]
            self.register(button, label, shortcut)

    def _defer_scan(self, key):
        if key in self._pending_scans:
            return
        self._pending_scans.add(key)

        def scan_when_ready():
            self._pending_scans.discard(key)
            bar = self._toolbars.get(key)
            if bar is not None:
                self._scan_toolbar(bar)

        QtCore.QTimer.singleShot(0, scan_when_ready)

    def _forget_button(self, key):
        self._buttons.pop(key, None)
        if key in (self._pending, self._showing):
            self.hide()

    def _request(self, key):
        if self._showing == key and isValid(self.popup) and self.popup.isVisible():
            return
        self.hide()
        self._pending = key
        self.timer.start()

    def _show_pending(self):
        key = self._pending
        self._pending = None
        record = self._buttons.get(key)
        if self._closed or record is None or not isValid(self.popup):
            return
        button, label, shortcut = record
        if not isValid(button) or not button.isVisible() or not isValid(self.main) or not self.main.isVisible():
            return
        # Popups and modal dialogs own their current interaction. A command
        # label must never cover their content or imply a toolbar is available.
        if self._app.activePopupWidget() is not None or self._app.activeModalWidget() is not None:
            return
        text = label + ("  (" + shortcut + ")" if shortcut else "")
        action = button.defaultAction()
        detail = action.property("kurtshapeHelp") if action is not None else None
        if detail:
            text += "\n" + str(detail)
        screen = button.screen() or self.main.screen() or self._app.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry().adjusted(4, 4, -4, -4)
        self.popup.setMinimumWidth(0)
        self.popup.setMaximumWidth(16777215)
        self.popup.setWordWrap(False)
        self.popup.setText(text)
        self.popup.adjustSize()
        # The usual command label is one short line. Bound unusual translated
        # names to the screen rather than letting a popup escape its monitor.
        if self.popup.width() > available.width():
            self.popup.setWordWrap(True)
            self.popup.setFixedWidth(max(1, available.width()))
            self.popup.adjustSize()
        anchor = button.mapToGlobal(QtCore.QPoint(0, button.height()))
        x = anchor.x() + (button.width() - self.popup.width()) // 2
        x = max(available.left(), min(x, available.right() - self.popup.width() + 1))
        y = anchor.y() + 5
        if y + self.popup.height() - 1 > available.bottom():
            # Only a toolbar next to the monitor's bottom edge falls back above.
            y = button.mapToGlobal(QtCore.QPoint(0, 0)).y() - self.popup.height() - 5
        y = max(available.top(), min(y, available.bottom() - self.popup.height() + 1))
        QtGui.QToolTip.hideText()
        self.popup.move(x, y)
        self._showing = key
        self.popup.show()

    def hide(self):
        """Also call when the active document changes without a focus event."""
        self._pending = None
        self._showing = None
        if isValid(self.timer):
            self.timer.stop()
        if isValid(self.popup):
            self.popup.hide()

    def close(self, *_args):
        """Remove the application filter on shell teardown/reload."""
        if self._closed:
            return
        self._closed = True
        self.hide()
        if isValid(self._app) and isValid(self):
            self._app.removeEventFilter(self)
        if isValid(self.popup):
            self.popup.deleteLater()
        self._buttons.clear()
        self._toolbars.clear()
        self._pending_scans.clear()

    def eventFilter(self, watched, event):
        if self._closed:
            return False
        kind = event.type()
        key = id(watched)
        if key in self._toolbars and kind in (QtCore.QEvent.ChildAdded, QtCore.QEvent.ActionAdded, QtCore.QEvent.ActionChanged):
            self._defer_scan(key)
        if key in self._buttons:
            if kind == QtCore.QEvent.ToolTip:
                # Cursor-positioned native tooltips would duplicate this label.
                event.accept()
                return True
            if kind in (QtCore.QEvent.Enter, QtCore.QEvent.FocusIn):
                # A mouse press can also grant focus. It should dismiss the
                # popup until the next deliberate hover/focus transition.
                if kind != QtCore.QEvent.FocusIn or self._app.mouseButtons() == QtCore.Qt.NoButton:
                    self._request(key)
            elif kind in (QtCore.QEvent.Leave, QtCore.QEvent.FocusOut, QtCore.QEvent.Hide):
                if key in (self._pending, self._showing):
                    self.hide()
            elif kind == QtCore.QEvent.ActionChanged and isinstance(watched, QtGui.QToolButton):
                action = watched.defaultAction()
                if action is not None:
                    shortcut = action.shortcut().toString(QtGui.QKeySequence.NativeText) or self._buttons.get(key, (None, "", ""))[2]
                    self.register(watched, action.text(), shortcut)
        if kind in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.KeyPress, QtCore.QEvent.WindowDeactivate,
                    QtCore.QEvent.ApplicationDeactivate, QtCore.QEvent.Close):
            self.hide()
        elif kind == QtCore.QEvent.Show and isinstance(watched, (QtGui.QMenu, QtGui.QDialog)):
            self.hide()
        elif watched is self.main and kind in (QtCore.QEvent.Hide, QtCore.QEvent.Move, QtCore.QEvent.Resize):
            self.hide()
        return False
