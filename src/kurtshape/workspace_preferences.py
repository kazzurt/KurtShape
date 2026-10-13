"""Modeling preferences away from the viewport's working status bar."""
from PySide import QtCore, QtGui
from . import navigation


class WorkspacePreferences(QtCore.QObject):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self.dialog = None
        self.application = QtGui.QApplication.instance()
        self.application.installEventFilter(self)
        self.hide_navigation_indicator()

    def hide_navigation_indicator(self):
        indicator = self.panel.main.findChild(QtGui.QWidget, "NavigationIndicator")
        if indicator:
            indicator.hide()

    def eventFilter(self, watched, event):
        if event.type() in {QtCore.QEvent.Show, QtCore.QEvent.Polish} and isinstance(watched, QtGui.QWidget) and watched.objectName() == "NavigationIndicator":
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
