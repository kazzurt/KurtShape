"""Modeling preferences away from the viewport's working status bar."""
from PySide import QtCore, QtGui
from . import navigation


def _empty_native_overlay(widget, main):
    if not isinstance(widget, QtGui.QWidget) or widget.parentWidget() is not main:
        return False
    kind = widget.metaObject().className()
    if kind == "Gui::OverlayTabWidget":
        overlay = widget
    elif kind == "Gui::OverlayProxyWidget" and widget.objectName().endswith("Proxy"):
        # FreeCAD parents the reveal strip beside its tab widget, under main.
        overlay = main.findChild(QtGui.QTabWidget, widget.objectName()[:-5])
        if overlay is None or overlay.metaObject().className() != "Gui::OverlayTabWidget":
            return False
    else:
        return False
    return not overlay.findChildren(QtGui.QDockWidget)


def release_native_overlays(main):
    """Let FreeCAD release its restored dock ownership before we arrange Tasks."""
    overlays = [widget for widget in main.findChildren(QtGui.QTabWidget)
                if widget.metaObject().className() == "Gui::OverlayTabWidget"]
    # This native command toggles all overlays. Only invoke its disable branch:
    # a second invocation with no tabs would enable overlays on a clean profile.
    if any(widget.count() for widget in overlays):
        import FreeCADGui as Gui
        Gui.runCommand("Std_DockOverlayAll")
    for widget in main.findChildren(QtGui.QWidget):
        if _empty_native_overlay(widget, main):
            widget.hide()


class WorkspacePreferences(QtCore.QObject):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.dialog = None
        self.application = QtGui.QApplication.instance()
        self.application.installEventFilter(self)
        self.hide_navigation_indicator()
        self.hide_native_toolbars()
        self.hide_empty_native_overlays()

    def _empty_native_overlay(self, widget):
        # Old layouts can leave a native tab/splitter shell after Tasks was
        # moved into a regular dock. Its mostly blank rectangle still takes
        # pointer events. Never hide an overlay that owns actual task content.
        return _empty_native_overlay(widget, self.panel.main)

    def hide_empty_native_overlays(self):
        for widget in self.panel.main.findChildren(QtGui.QWidget):
            if self._empty_native_overlay(widget):
                widget.hide()

    def _native_toolbar(self, widget):
        if not isinstance(widget, QtGui.QToolBar) or widget.objectName().startswith("KurtShape"):
            return False
        # Floating native bars are windows of their own but remain owned by
        # the main window. Do not affect another window's toolbars.
        parent = widget.parent()
        while parent is not None:
            if parent is self.panel.main:
                return True
            parent = parent.parent()
        return False

    def hide_native_toolbars(self):
        for bar in self.panel.main.findChildren(QtGui.QToolBar):
            if self._native_toolbar(bar):
                bar.hide()

    def hide_navigation_indicator(self):
        indicator = self.panel.main.findChild(QtGui.QWidget, "NavigationIndicator")
        if indicator:
            indicator.hide()

    def eventFilter(self, watched, event):
        if event.type() in {QtCore.QEvent.Show, QtCore.QEvent.Polish}:
            if (isinstance(watched, QtGui.QWidget) and watched.objectName() == "NavigationIndicator"
                    or self._native_toolbar(watched) or self._empty_native_overlay(watched)):
                # Native workbench/task activation restores this chrome after
                # the synchronous hide pass, including blank overlay shells.
                watched.hide()
        return False

    def show(self):
        if self.dialog:
            self.dialog.raise_()
            self.dialog.activateWindow()
            return
        dialog = QtGui.QDialog(self.panel.main)
        dialog.setObjectName("KurtShapeSettings")
        dialog.setWindowTitle("Settings")
        dialog.setMinimumWidth(360)
        self.dialog = dialog
        layout = QtGui.QVBoxLayout(dialog)
        form = QtGui.QFormLayout()
        appearance = QtGui.QLabel("Light (Onshape)")
        appearance.setObjectName("KurtShapeAppearance")
        form.addRow("Appearance", appearance)
        choice = QtGui.QComboBox()
        choice.setObjectName("KurtShapeMouseNavigation")
        for name, style in navigation.NAVIGATION_STYLES:
            choice.addItem(name, style)
        choice.setCurrentIndex(choice.findData(navigation.selected_style()))
        form.addRow("Mouse navigation", choice)
        from . import selection_mode
        additive = QtGui.QCheckBox("Click adds to selection")
        additive.setObjectName("KurtShapeAdditiveSelection")
        additive.setToolTip("On: a click on a face, edge or vertex adds it and a second click removes it; "
                            "click empty space or press Space to clear. Off: a click replaces the selection.")
        additive.setChecked(selection_mode.enabled())
        form.addRow("Selection", additive)
        layout.addLayout(form)
        restore = QtGui.QPushButton("Restore light appearance")
        restore.setObjectName("KurtShapeRestoreLightAppearance")
        layout.addWidget(restore)

        def restore_appearance():
            from .theme import apply_theme, apply_view_theme
            import FreeCAD as App
            import FreeCADGui as Gui
            try:
                apply_theme(self.panel.main)
                for doc in App.listDocuments().values():
                    gui_document = Gui.getDocument(doc.Name)
                    view = gui_document.activeView() if gui_document else None
                    if view is not None and hasattr(view, "getViewer"):
                        apply_view_theme(view)
                App.saveParameter()
                self.panel.notify("Light appearance restored")
            except Exception as exc:
                self.panel.notify(str(exc), "error")

        restore.clicked.connect(restore_appearance)
        help_text = QtGui.QLabel()
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        def update_help(*args):
            help_text.setText("Middle drag rotates, Ctrl + middle drag pans, Shift + middle drag zooms, and double middle click fits the model."
                              if choice.currentData() == navigation.SOLIDWORKS_STYLE else
                              "Uses FreeCAD's " + choice.currentText() + " mouse controls. The choice applies to current and newly opened views.")
        choice.currentIndexChanged.connect(update_help)
        update_help()
        buttons = QtGui.QDialogButtonBox(QtGui.QDialogButtonBox.Save | QtGui.QDialogButtonBox.Cancel)
        layout.addWidget(buttons)

        def save():
            try:
                navigation.set_navigation_style(choice.currentData())
                selection_mode.set_enabled(additive.isChecked())
                self.hide_navigation_indicator()
                self.panel.notify("Mouse navigation saved")
                dialog.accept()
            except Exception as exc:
                self.panel.notify(str(exc), "error")

        buttons.accepted.connect(save)
        buttons.rejected.connect(dialog.reject)
        def finished(*args):
            self.dialog = None
            dialog.deleteLater()
        dialog.finished.connect(finished)
        dialog.open()

    def close(self):
        if self.dialog:
            self.dialog.reject()
        self.application.removeEventFilter(self)
