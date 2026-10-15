"""A draggable build boundary drawn between the actual feature-history rows."""
from __future__ import annotations

from PySide import QtCore, QtGui

from .theme import COLORS


class RollbackMarker(QtGui.QWidget):
    """Keep the build boundary in the tree, with no separate numeric slider.

    The small slider-compatible surface preserves the existing keyboard route.
    Only a deliberate drag of the marker itself moves the boundary: the pointer
    must travel past the platform drag distance, and only that drag's release
    commits a rebuild. Clicks, row presses, tiny moves and scrolling never roll
    history back; Escape cancels a drag.
    """
    sliderPressed = QtCore.Signal()
    sliderReleased = QtCore.Signal()
    valueChanged = QtCore.Signal(int)

    def __init__(self, tree):
        super().__init__(tree.viewport())
        self.tree = tree
        self._value = self._maximum = 0
        self.order, self.items, self.labels = [], {}, {}
        self.available = False
        self.dragging = False
        self.pressing = False
        self.press_y = 0
        self.drag_start = 0
        self.drag_y = 0
        self.setObjectName("KurtShapeRollbackBar")
        self.setAccessibleName("Feature history rollback boundary")
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setCursor(QtCore.Qt.SizeVerCursor)
        self.setFixedHeight(10)
        self.setToolTip("Drag this line between features to roll history back or forward. "
                        "When it has focus, Up / Down moves one feature and Escape cancels a drag.")
        tree.viewport().setMouseTracking(True)
        tree.viewport().installEventFilter(self)
        tree.verticalScrollBar().valueChanged.connect(self.reposition)
        tree.itemExpanded.connect(self.reposition)
        tree.itemCollapsed.connect(self.reposition)
        tree.model().layoutChanged.connect(self.reposition)
        self.scroll_timer = QtCore.QTimer(self)
        self.scroll_timer.setInterval(60)
        self.scroll_timer.timeout.connect(self.autoscroll)
        self.hide()

    def setRange(self, minimum, maximum):
        self._maximum = max(0, int(maximum))

    def maximum(self):
        return self._maximum

    def value(self):
        return self._value

    def setValue(self, index):
        index = max(0, min(self._maximum, int(index)))
        changed = index != self._value
        self._value = index
        if changed:
            self.valueChanged.emit(index)
        self.reposition()

    def bind_history(self, order, items, labels, index, available=True):
        self.order = list(order)
        self.items = {name: items[name] for name in order if name in items}
        self.labels = dict(labels)
        self.available = bool(available)
        self.setRange(0, len(order))
        self.setValue(index)
        self.setAccessibleDescription(self.description())
        QtCore.QTimer.singleShot(0, self.reposition)

    def description(self, index=None):
        index = max(0, min(len(self.order), self._value if index is None else index))
        before = self.labels.get(self.order[index - 1], self.order[index - 1]) if index else None
        after = self.labels.get(self.order[index], self.order[index]) if index < len(self.order) else None
        if before and after:
            return "After " + before + " · before " + after
        if after:
            return "Before " + after
        if before:
            return "End of history · after " + before
        return "End of history"

    def gap_positions(self):
        """Map visible boundaries to native ordered-history positions."""
        positions = []
        for index, name in enumerate(self.order):
            item = self.items.get(name)
            if item is None or item.isHidden():
                continue
            rect = self.tree.visualItemRect(item)
            if rect.isEmpty():
                continue
            positions.append((index, rect.top()))
            positions.append((index + 1, rect.bottom() + 1))
        if not self.order:
            item = self.tree.topLevelItem(0)
            bottom = 11
            while item is not None:
                rect = self.tree.visualItemRect(item)
                if not item.isHidden() and not rect.isEmpty():
                    bottom = max(bottom, rect.bottom())
                item = self.tree.itemBelow(item)
            positions.append((0, bottom + 1))
        return positions

    def gap_point(self, index):
        """Return a viewport coordinate for a specific boundary (also for tests)."""
        choices = [y for value, y in self.gap_positions() if value == index]
        if not choices:
            return None
        y = choices[-1] if index == len(self.order) else choices[0]
        return QtCore.QPoint(max(24, self.tree.viewport().width() // 2), y)

    def nearest_gap(self, y, tolerance=None):
        choices = self.gap_positions()
        if not choices:
            return None
        index, gap_y = min(choices, key=lambda pair: abs(pair[1] - y))
        return index if tolerance is None or abs(gap_y - y) <= tolerance else None

    def reposition(self, *args):
        if not self.available:
            self.hide()
            return
        try:
            point = self.gap_point(self._value)
            viewport = self.tree.viewport()
            visible = point is not None and 0 <= point.y() < viewport.height()
            self.setVisible(visible)
            if visible:
                geometry = QtCore.QRect(0, max(0, point.y() - 5), viewport.width(), 10)
                if self.geometry() != geometry:
                    self.setGeometry(geometry)
                self.raise_()
        except RuntimeError:
            # Tree reconstruction retires its items before bind_history.
            self.hide()

    def reveal(self):
        name = (self.order[min(self._value, len(self.order) - 1)] if self.order else None)
        item = self.items.get(name)
        if item is not None and not item.isHidden():
            self.tree.scrollToItem(item, QtGui.QAbstractItemView.PositionAtCenter)
        self.reposition()

    def begin(self, y):
        """Arm a drag on the marker; nothing moves until the drag threshold."""
        if not self.available or not self.isEnabled():
            return False
        self.drag_start = self._value
        self.pressing = True
        self.dragging = False
        self.press_y = self.drag_y = y
        self.setFocus(QtCore.Qt.MouseFocusReason)
        return True

    def move(self, y):
        if self.pressing and not self.dragging:
            if abs(y - self.press_y) < QtGui.QApplication.startDragDistance():
                return
            self.dragging = True
            self.sliderPressed.emit()
            self.scroll_timer.start()
        if self.dragging:
            self.drag(y)

    def drag(self, y):
        self.drag_y = y
        index = self.nearest_gap(y)
        if index is not None:
            self.setValue(index)

    def finish(self, y):
        """Commit only a real drag; a click or tiny movement changes nothing."""
        dragged = self.dragging
        self.pressing = False
        if dragged:
            self.drag(y)
            self.release()
        return dragged

    def cancel_drag(self):
        if not (self.pressing or self.dragging):
            return False
        self.pressing = self.dragging = False
        self.scroll_timer.stop()
        self.setValue(self.drag_start)
        return True

    def release(self):
        self.dragging = False
        self.pressing = False
        self.scroll_timer.stop()
        # The controller rebuilds the tree. Let the originating mouse event end
        # before a refresh removes the current native tree items.
        QtCore.QTimer.singleShot(0, self.sliderReleased.emit)

    def autoscroll(self):
        height = self.tree.viewport().height()
        delta = -1 if self.drag_y < 16 else 1 if self.drag_y > height - 16 else 0
        if delta:
            scroll = self.tree.verticalScrollBar()
            scroll.setValue(scroll.value() + delta * max(1, scroll.singleStep()))
            self.drag(self.drag_y)

    def eventFilter(self, watched, event):
        if watched is not self.tree.viewport():
            return False
        kind = event.type()
        if kind in {QtCore.QEvent.Resize, QtCore.QEvent.Show, QtCore.QEvent.LayoutRequest}:
            QtCore.QTimer.singleShot(0, self.reposition)
        # Row presses, double-clicks, gaps and wheel scrolling belong to the
        # tree. Only the marker widget itself starts a rollback drag.
        return False

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.begin(self.mapToParent(event.pos()).y())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.pressing or self.dragging:
            self.move(self.mapToParent(event.pos()).y())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton and (self.pressing or self.dragging):
            self.finish(self.mapToParent(event.pos()).y())
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape and self.cancel_drag():
            event.accept()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        color = QtGui.QColor(COLORS["accent"] if self.isEnabled() else COLORS["disabled_ink"])
        painter.setPen(QtGui.QPen(color, 2))
        painter.drawLine(19, 5, max(20, self.width() - 5), 5)
        painter.setBrush(color)
        painter.drawRoundedRect(QtCore.QRectF(5, 1, 13, 8), 2, 2)
        painter.setPen(QtGui.QPen(QtGui.QColor(COLORS["surface"]), 1))
        for x in (9, 13):
            painter.drawLine(x, 3, x, 7)
