"""A modeless feature editor that leaves the CAD viewport available for picking."""
from PySide import QtCore, QtGui


def _refresh_property(widget, name, value):
    """Refresh semantic QSS states without installing local colors."""
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def _icon_button(parent, name, text, standard_icon):
    button = QtGui.QToolButton(parent)
    button.setObjectName(name)
    button.setText(text)
    button.setAccessibleName(text)
    button.setToolTip(text)
    button.setIcon(parent.style().standardIcon(standard_icon))
    button.setIconSize(QtCore.QSize(16, 16))
    button.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
    button.setAutoRaise(True)
    button.setFixedSize(28, 28)
    return button


class FeaturePanel(QtGui.QDockWidget):
    accepted = QtCore.Signal()
    rejected = QtCore.Signal()

    def __init__(self, title, parent):
        super().__init__(title, parent)
        self.setFeatures(QtGui.QDockWidget.DockWidgetClosable
                         | QtGui.QDockWidget.DockWidgetMovable
                         | QtGui.QDockWidget.DockWidgetFloatable)
        self.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)
        self.setWindowModality(QtCore.Qt.NonModal)
        self.setMinimumWidth(280)
        self.setMaximumWidth(440)
        self.setSizePolicy(QtGui.QSizePolicy.Preferred, QtGui.QSizePolicy.Preferred)
        self.finished = False
        self._reject_emitted = False
        self._accepting = False
        self._accept_enabled = False

        self.header = QtGui.QWidget(self)
        self.header.setObjectName("KurtShapeFeatureHeader")
        self.header.setAccessibleName(title + " editor")
        header_layout = QtGui.QHBoxLayout(self.header)
        header_layout.setContentsMargins(8, 4, 4, 4)
        header_layout.setSpacing(4)
        self.title_label = QtGui.QLabel(title, self.header)
        self.title = self.title_label
        self.title_label.setObjectName("KurtShapeFeatureTitle")
        self.title_label.setSizePolicy(QtGui.QSizePolicy.Ignored, QtGui.QSizePolicy.Preferred)
        self.title_label.setToolTip(title)
        header_layout.addWidget(self.title_label, 1)
        self.confirm_button = _icon_button(self.header, "KurtShapeFeatureConfirm", "Confirm " + title,
                                           QtGui.QStyle.SP_DialogApplyButton)
        self.cancel_button = _icon_button(self.header, "KurtShapeFeatureCancel", "Cancel " + title,
                                          QtGui.QStyle.SP_DialogCancelButton)
        self.confirm = self.confirm_button
        self.cancel = self.cancel_button
        self.confirm_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        header_layout.addWidget(self.confirm_button)
        header_layout.addWidget(self.cancel_button)
        self.setTitleBarWidget(self.header)
        self.windowTitleChanged.connect(self._title_changed)

        self.content = QtGui.QWidget()
        self.content.setObjectName("KurtShapeFeatureContent")
        self.scroll = QtGui.QScrollArea(self)
        self.scroll.setObjectName("KurtShapeFeatureScroll")
        self.scroll.setFrameShape(QtGui.QFrame.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.content)
        self.verdict = QtGui.QLabel()
        self.verdict.setObjectName("KurtShapeFeatureVerdict")
        self.verdict.setWordWrap(True)
        self.verdict.setMargin(8)
        self.verdict.hide()
        body = QtGui.QWidget()
        body.setObjectName("KurtShapeFeatureBody")
        body_layout = QtGui.QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        body_layout.addWidget(self.scroll, 1)
        body_layout.addWidget(self.verdict)
        self.setWidget(body)
        self.set_accept_enabled(False)

    def _title_changed(self, title):
        self.title_label.setText(title)
        self.title_label.setToolTip(title)
        self.header.setAccessibleName(title + " editor")
        self.confirm_button.setAccessibleName("Confirm " + title)
        self.confirm_button.setToolTip("Confirm " + title)
        self.cancel_button.setAccessibleName("Cancel " + title)
        self.cancel_button.setToolTip("Cancel " + title)

    def set_accept_enabled(self, enabled):
        """Gate the header and keyboard callback on the current preview verdict."""
        self._accept_enabled = bool(enabled)
        self.confirm_button.setEnabled(self._accept_enabled and not self.finished and not self._reject_emitted)

    def set_status(self, text, severity=""):
        self.verdict.setText(text)
        self.verdict.setToolTip(text)
        _refresh_property(self.verdict, "severity", severity)
        self.verdict.setVisible(bool(text))

    def reset_lifecycle(self):
        """Rearm an unfinished editor reused for a new task by its owner."""
        if not self.finished:
            self._reject_emitted = False
            self._accepting = False
            self.set_accept_enabled(self._accept_enabled)

    def show_compact(self):
        """Float beside the native MDI canvas after the owner adds this dock."""
        self.reset_lifecycle()
        parent = self.parentWidget()
        area = parent.findChild(QtGui.QMdiArea) if parent is not None else None
        canvas = area.viewport() if area is not None else parent
        point = canvas.mapToGlobal(QtCore.QPoint(12, 12)) if canvas is not None else None
        screen = QtGui.QApplication.screenAt(point) if point is not None else None
        screen = screen or (parent.screen() if parent is not None else QtGui.QApplication.primaryScreen())
        if screen is None:
            self.show()
            return
        available = screen.availableGeometry()
        self.ensurePolished()
        if self.content.layout() is not None:
            self.content.layout().activate()
        content_height = self.content.sizeHint().height()
        height_limit = max(120, available.height() - 24)
        if canvas is not None and canvas.height() > 160:
            height_limit = min(height_limit, canvas.height() - 24)
        width = min(320, available.width())
        status_height = self.verdict.heightForWidth(width) if not self.verdict.isHidden() else 0
        height = min(height_limit, max(getattr(self, "compact_minimum_height", 180), content_height + self.header.sizeHint().height() + max(0, status_height) + 8))
        point = point or available.topLeft() + QtCore.QPoint(12, 12)
        self.setFloating(True)
        self.resize(width, height)
        # Use the actual minimum/layout result when clamping, not the requested
        # size: long native form labels may establish a larger minimum width.
        x = max(available.left(), min(point.x(), available.right() - self.width() + 1))
        y = max(available.top(), min(point.y(), available.bottom() - self.height() + 1))
        self.move(x, y)
        self.show()
        self.raise_()

    def accept(self):
        if self.finished or self._reject_emitted or self._accepting or not self._accept_enabled:
            return
        # A rejected operation can retain this editor for correction and retry;
        # only the owner marks an accepted transaction as finished.
        self._accepting = True
        try:
            self.accepted.emit()
        finally:
            self._accepting = False

    def reject(self):
        if not self.finished and not self._reject_emitted:
            self._reject_emitted = True
            self.confirm_button.setEnabled(False)
            self.rejected.emit()

    def closeEvent(self, event):
        self.reject()
        if not self.finished and not self._reject_emitted:
            event.ignore()  # The owner retained the task after failed cancellation.
        else:
            event.accept()


class _ReferenceDelegate(QtGui.QStyledItemDelegate):
    def paint(self, painter, option, index):
        # Keep QListWidgetItem.text() for callers and accessibility, but let the
        # row widget draw its elided label beside the explicit removal control.
        clean = QtGui.QStyleOptionViewItem(option)
        self.initStyleOption(clean, index)
        clean.text = ""
        style = clean.widget.style() if clean.widget is not None else QtGui.QApplication.style()
        style.drawControl(QtGui.QStyle.CE_ItemViewItem, clean, painter, clean.widget)


class _ReferenceLabel(QtGui.QLabel):
    def __init__(self, text, parent):
        super().__init__(text, parent)
        self.full_text = text
        self.setToolTip(text)
        self.setAccessibleName(text)
        self.setSizePolicy(QtGui.QSizePolicy.Ignored, QtGui.QSizePolicy.Preferred)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)

    def resizeEvent(self, event):
        self.setText(self.fontMetrics().elidedText(self.full_text, QtCore.Qt.ElideMiddle, self.width()))
        super().resizeEvent(event)


class ReferencePicker(QtGui.QWidget):
    """Visible selection field with explicit removal and an active picking state."""
    changed = QtCore.Signal()
    activated = QtCore.Signal()

    def __init__(self, prompt, multiple=True):
        super().__init__()
        self.setObjectName("KurtShapeReferencePicker")
        self.setAccessibleName(prompt)
        self.multiple = multiple
        self.prompt = prompt
        self.setSizePolicy(QtGui.QSizePolicy.Preferred, QtGui.QSizePolicy.Maximum)
        self.references = []
        self.native_inputs = []
        self.pick = QtGui.QPushButton(prompt)
        self.pick.setObjectName("KurtShapeReferencePick")
        self.pick.setAccessibleName(prompt)
        self.pick.setAutoDefault(False)
        self.pick.setDefault(False)
        self.pick.setCheckable(True)
        self.pick.setChecked(True)
        self.pick.setToolTip("Click this field, then select geometry in the viewport or feature history.")
        self.pick.clicked.connect(self.activated.emit)
        self.pick.toggled.connect(self._refresh_state)
        self.items = QtGui.QListWidget()
        self.items.setObjectName("KurtShapeReferenceItems")
        self.items.setAccessibleName(prompt + " references")
        self.items.setFrameShape(QtGui.QFrame.NoFrame)
        self.items.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.items.setItemDelegate(_ReferenceDelegate(self.items))
        self.items.setSelectionMode(QtGui.QAbstractItemView.ExtendedSelection)
        self.items.itemSelectionChanged.connect(self._refresh_state)
        self.items.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.items.customContextMenuRequested.connect(self._show_menu)
        self.remove = _icon_button(self, "KurtShapeReferenceRemove", "Remove selected references",
                                    QtGui.QStyle.SP_DialogCloseButton)
        self.remove.clicked.connect(self.remove_selected)
        self.menu_button = _icon_button(self, "KurtShapeReferenceMenu", "Reference options",
                                        QtGui.QStyle.SP_ArrowDown)
        self.menu = QtGui.QMenu(self)
        self.remove_action = self.menu.addAction("Remove selected")
        self.remove_action.triggered.connect(self.remove_selected)
        self.clear_action = self.menu.addAction("Clear all")
        self.clear_action.triggered.connect(self.clear_all)
        self.menu_button.setMenu(self.menu)
        self.menu_button.setPopupMode(QtGui.QToolButton.InstantPopup)
        layout = QtGui.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        heading = QtGui.QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(2)
        heading.addWidget(self.pick, 1)
        heading.addWidget(self.remove)
        heading.addWidget(self.menu_button)
        layout.addLayout(heading)
        layout.addWidget(self.items)
        self._refresh_state()

    def _refresh_state(self, *args):
        active = self.pick.isChecked() and self.isEnabled()
        state = "disabled" if not self.isEnabled() else "active" if active else "filled" if self.references else "empty"
        _refresh_property(self, "activePicking", active)
        _refresh_property(self, "pickingState", state)
        _refresh_property(self.pick, "activePicking", active)
        selected = bool(self.items.selectedItems())
        self.remove.setEnabled(selected)
        self.remove_action.setEnabled(selected)
        self.clear_action.setEnabled(bool(self.references))
        self.menu_button.setEnabled(bool(self.references))
        count = len(self.references)
        self.pick.setAccessibleName(self.prompt + ("; " + str(count) + " selected" if count else "; no references"))
        row_height = max(28, self.fontMetrics().height() + 8)
        for index in range(count):
            item = self.items.item(index)
            if item.sizeHint().height() != row_height:
                item.setSizeHint(QtCore.QSize(0, row_height))
        # A single reference occupies one row; multi-pickers grow to three rows,
        # then scroll. Empty pickers do not reserve an empty collection box.
        self.items.setFixedHeight(min(count, 3 if self.multiple else 1) * row_height + (2 if count else 0))
        self.items.setVisible(bool(count))
        self.updateGeometry()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QtCore.QEvent.EnabledChange, QtCore.QEvent.FontChange) and hasattr(self, "clear_action"):
            self._refresh_state()

    def _show_menu(self, position):
        self.menu.exec_(self.items.viewport().mapToGlobal(position))

    def add(self, reference, label, native_input=None):
        if reference in self.references:
            return
        if not self.multiple:
            self.references.clear()
            self.native_inputs.clear()
            self.items.clear()
        self.references.append(reference)
        self.native_inputs.append(native_input)
        item = QtGui.QListWidgetItem(label)
        item.setToolTip(label)
        item.setSizeHint(QtCore.QSize(0, max(28, self.fontMetrics().height() + 8)))
        self.items.addItem(item)
        row = QtGui.QWidget(self.items)
        row.setObjectName("KurtShapeReferenceRow")
        row_layout = QtGui.QHBoxLayout(row)
        row_layout.setContentsMargins(6, 0, 0, 0)
        row_layout.setSpacing(2)
        row_layout.addWidget(_ReferenceLabel(label, row), 1)
        remove = _icon_button(row, "KurtShapeReferenceRowRemove", "Remove " + label,
                              QtGui.QStyle.SP_DialogCloseButton)
        remove.clicked.connect(lambda checked=False, target=item: self._remove_rows([self.items.row(target)]))
        row_layout.addWidget(remove)
        self.items.setItemWidget(item, row)
        self._refresh_state()
        self.changed.emit()

    def remove_selected(self):
        self._remove_rows([self.items.row(item) for item in self.items.selectedItems()])

    def clear_all(self):
        self._remove_rows(range(len(self.references)))

    def _remove_rows(self, rows):
        rows = sorted({row for row in rows if 0 <= row < len(self.references)}, reverse=True)
        if not rows:
            return
        for row in rows:
            self.references.pop(row)
            native_input = self.native_inputs.pop(row)
            if native_input:
                import FreeCADGui as Gui
                obj, element = native_input
                try:
                    Gui.Selection.removeSelection(obj.Document.Name, obj.Name, element)
                except (ReferenceError, RuntimeError):
                    pass
            self.items.takeItem(row)
        self._refresh_state()
        self.changed.emit()

    def value(self):
        return list(self.references) if self.multiple else (self.references[0] if self.references else None)
