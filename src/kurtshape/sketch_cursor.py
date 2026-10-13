"""Reuse native sketch cursor appearances without repeated Windows allocation.

Sketcher constructs a new, often identical QPixmap cursor on every pointer
move. A Qt application override keeps those widget cursors from repeatedly
creating native Windows cursors. The widget retains its original native
cursor; this adapter only displays a cached copy while drawing in the view.
"""
from __future__ import annotations

from collections import OrderedDict
import hashlib

from PySide import QtCore, QtGui


class SketchCursor:
    CACHE_LIMIT = 32

    def __init__(self, panel):
        self.panel = panel
        self.app = QtGui.QApplication.instance()
        self._command = None
        self._viewport = None
        self._owned = None
        self._appearance = None
        self._pending_release = False
        self._closed = False
        self._cache = OrderedDict()
        self._counts = dict(cursor_events=0, cache_hits=0, cache_misses=0,
                            pushes=0, changes=0, restores=0)
        # A native wait cursor can temporarily cover our stack entry. Even
        # after panel shutdown, remove ours only when it resurfaces.
        self._cleanup_timer = QtCore.QTimer(self.app)
        self._cleanup_timer.setInterval(100)
        self._cleanup_timer.timeout.connect(self._cleanup)

    @property
    def counters(self):
        return dict(self._counts, cache_size=len(self._cache),
                    owned=self._owned is not None,
                    deferred_release=self._pending_release)

    @property
    def stats(self):
        return self.counters

    def _count(self, name):
        self._counts[name] = min(self._counts[name] + 1, (1 << 63) - 1)

    @staticmethod
    def _identity(cursor):
        if cursor is None:
            return None
        pixmap = cursor.pixmap()
        hot = cursor.hotSpot()
        return (cursor.shape(), pixmap.cacheKey(), hot.x(), hot.y())

    @staticmethod
    def _key(cursor, pixmap):
        # RGBA8888 has four bytes per pixel and no row padding. Native cursor
        # pixmap cacheKeys change even when every displayed pixel is identical.
        image = pixmap.toImage().convertToFormat(QtGui.QImage.Format_RGBA8888)
        hot = cursor.hotSpot()
        return (cursor.shape(), image.width(), image.height(),
                pixmap.devicePixelRatioF(), hot.x(), hot.y(),
                hashlib.blake2b(image.constBits(), digest_size=16).digest())

    def _is_viewport(self, widget):
        if not isinstance(widget, QtGui.QWidget):
            return False
        try:
            if widget.metaObject().className() != "QOpenGLWidget":
                return False
            if widget.window() is not self.panel.main:
                return False
            mdi = self.panel.main.findChild(QtGui.QMdiArea)
            active = mdi.activeSubWindow() if mdi else None
            return mdi is None or active is not None and active.isAncestorOf(widget)
        except (RuntimeError, ReferenceError):
            return False

    def _allowed(self):
        return (not self._closed
                and (self._command or "").startswith("Sketcher_Create")
                and self.panel.main.isActiveWindow()
                and not self.app.activeModalWidget()
                and not self.app.activePopupWidget()
                and bool(self.panel.active_sketch()))

    def _changes_viewport_cursor(self, widget):
        if self._viewport is None or not isinstance(widget, QtGui.QWidget):
            return False
        try:
            return widget is self._viewport or widget.isAncestorOf(self._viewport)
        except (RuntimeError, ReferenceError):
            return False

    def _forget_owned(self):
        self._owned = self._appearance = None
        self._pending_release = False
        if self._cleanup_timer is not None:
            self._cleanup_timer.stop()
        if self._closed:
            self._cache.clear()

    def _release(self):
        if self._owned is None:
            return
        top = self.app.overrideCursor()
        if top is None:
            # Another owner already removed the entry. Never compensate by
            # popping a cursor which might belong to somebody else.
            self._forget_owned()
        elif self._identity(top) == self._owned:
            self.app.restoreOverrideCursor()
            self._count("restores")
            self._forget_owned()
        else:
            self._pending_release = True
            self._cleanup_timer.start()

    def _cleanup(self):
        if self._pending_release:
            self._release()
        if self._closed and self._owned is None:
            self._dispose_timer()

    def _dispose_timer(self):
        if self._cleanup_timer is not None:
            self._cleanup_timer.stop()
            self._cleanup_timer.timeout.disconnect(self._cleanup)
            self._cleanup_timer.deleteLater()
            self._cleanup_timer = None

    def _refresh(self):
        if not self._allowed() or self._viewport is None:
            self._release()
            return
        if self._pending_release:
            self._release()
            if self._owned is not None:
                return
        top = self.app.overrideCursor()
        if top is None and self._owned is not None:
            self._forget_owned()
        if top is not None and self._identity(top) != self._owned:
            # Do not cover a pre-existing wait/navigation/plugin cursor.
            self._release()
            return
        try:
            native = self._viewport.cursor()
        except (RuntimeError, ReferenceError):
            self._viewport = None
            self._release()
            return
        pixmap = native.pixmap()
        if pixmap.isNull():
            # Stock shapes have no pixmap allocation churn. More importantly,
            # a stock-shape override has no unique identity for safe ownership.
            self._release()
            return
        key = self._key(native, pixmap)
        if key in self._cache:
            cursor = self._cache.pop(key)
            self._count("cache_hits")
        else:
            # A distinct pixmap identity lets us recognize our stack entry,
            # even if somebody else pushes a copy of the native widget cursor.
            hot = native.hotSpot()
            cursor = QtGui.QCursor(pixmap.copy(), hot.x(), hot.y())
            self._count("cache_misses")
        self._cache[key] = cursor
        if len(self._cache) > self.CACHE_LIMIT:
            self._cache.popitem(last=False)
        if self._owned is None:
            self.app.setOverrideCursor(cursor)
            self._owned = self._identity(cursor)
            self._appearance = key
            self._count("pushes")
        elif key != self._appearance:
            self.app.changeOverrideCursor(cursor)
            self._owned = self._identity(cursor)
            self._appearance = key
            self._count("changes")

    def sync(self, command):
        """Call at command changes and the panel's ordinary idle tick."""
        if self._closed:
            self._cleanup()
            return
        if command != self._command:
            self._release()
        self._command = command
        if not self._allowed():
            self._viewport = None
            self._release()
            return
        # This also covers a command activated by a shortcut with the pointer
        # already over the view and recovery after a native modal wait cursor.
        widget = self.app.widgetAt(QtGui.QCursor.pos())
        self._viewport = widget if self._is_viewport(widget) else None
        self._refresh()

    def event(self, watched, event):
        """Observe application-filter events; never consume native input."""
        if self._closed:
            return False
        kind = event.type()
        plain_right = (kind == QtCore.QEvent.MouseButtonPress
                       and event.button() == QtCore.Qt.RightButton
                       and event.buttons() == QtCore.Qt.RightButton
                       and event.modifiers() == QtCore.Qt.NoModifier)
        if kind == QtCore.QEvent.KeyPress and event.key() == QtCore.Qt.Key_Escape:
            self._command = None
            self._viewport = None
            self._release()
        elif kind == QtCore.QEvent.MouseButtonPress and (
                plain_right or not self._is_viewport(watched)):
            if plain_right:
                self._command = None
            self._viewport = None
            self._release()
        elif kind in (QtCore.QEvent.WindowDeactivate, QtCore.QEvent.WindowBlocked,
                      QtCore.QEvent.ApplicationDeactivate):
            self._viewport = None
            self._release()
        elif watched is self._viewport and kind in (
                QtCore.QEvent.Leave, QtCore.QEvent.Hide, QtCore.QEvent.Close,
                QtCore.QEvent.Destroy):
            self._viewport = None
            self._release()
        elif kind in (QtCore.QEvent.Enter, QtCore.QEvent.MouseMove):
            if self._is_viewport(watched):
                self._viewport = watched
                self._refresh()
        elif kind == QtCore.QEvent.CursorChange and self._changes_viewport_cursor(watched):
            # FreeCAD sets the cursor on Gui::View3DInventorViewer. Its OpenGL
            # child inherits that cursor but receives no CursorChange itself.
            # Read the child's effective cursor immediately, including any
            # explicit child override, rather than waiting for the next move.
            self._count("cursor_events")
            self._refresh()
        return False

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._command = None
        self._viewport = None
        self._release()
        self._cache.clear()
        if self._owned is None:
            self._dispose_timer()
