"""Application-owned light Qt theme, including FreeCAD's native task widgets.

FreeCAD's generated stylesheet and OS-derived palette are independent. Painting
light input backgrounds without replacing the dark palette leaves white text.
KurtShape therefore owns both the QApplication palette and stylesheet. This
only changes this process; no Windows or FreeCAD preference is written.
"""
from __future__ import annotations

COLORS = {
    "workspace": "#f1f3f6", "surface": "#ffffff", "chrome": "#e9edf2",
    "alternate": "#f7f9fc", "ink": "#243447", "muted": "#526378",
    "placeholder": "#65758a", "disabled_ink": "#5b687b", "disabled": "#eef1f5",
    "border": "#bdc7d3", "hover": "#e7f0fa", "selection": "#d8e9fa",
    "selection_ink": "#153f68", "accent": "#1e65a7", "accent_pressed": "#154e83",
    "error": "#a02f34", "success": "#237147", "tooltip": "#243447",
}

STYLESHEET = """
QWidget { color: %(ink)s; font-family: 'Segoe UI'; font-size: 12px; }
QWidget:disabled { color: %(disabled_ink)s; }
QMainWindow, QDialog, QDockWidget, QToolBar, QStatusBar, QTabWidget::pane {
    color: %(ink)s; background-color: %(workspace)s;
}
QLabel { color: %(ink)s; background-color: transparent; }
QLabel:disabled { color: %(disabled_ink)s; }
QLabel#SectionTitle { color: %(muted)s; background: %(workspace)s; font-weight: 600; padding: 7px 9px; }
QToolBar { border: 0; border-bottom: 1px solid %(border)s; spacing: 2px; padding: 3px 5px; }
QToolBar::separator { width: 1px; background: %(border)s; margin: 5px 6px; }
QDockWidget { border: 0; }
QDockWidget::title { color: %(ink)s; background: %(chrome)s; padding: 7px 9px; border-bottom: 1px solid %(border)s; }
QPushButton, QToolButton {
    color: %(ink)s; background-color: %(surface)s; border: 1px solid %(border)s;
    border-radius: 2px; padding: 5px 9px;
}
QToolButton { background-color: transparent; border-color: transparent; padding: 4px 6px; }
QPushButton:hover, QToolButton:hover { color: %(ink)s; background: %(hover)s; border-color: #8eaed1; }
QPushButton:pressed, QToolButton:pressed, QToolButton:checked { color: %(selection_ink)s; background: %(selection)s; border-color: #729dca; }
QPushButton:focus, QToolButton:focus { border-color: %(accent)s; }
QPushButton:default, QPushButton#Confirm { color: white; background: %(accent)s; border-color: %(accent)s; font-weight: 600; }
QPushButton:default:hover, QPushButton#Confirm:hover { color: white; background: %(accent_pressed)s; }
QPushButton#Cancel { color: %(error)s; background: %(surface)s; }
QPushButton:disabled, QToolButton:disabled { color: %(disabled_ink)s; background: %(disabled)s; border-color: #d1d8e1; }
QPushButton#Confirm:disabled, QPushButton#Cancel:disabled, QPushButton:default:disabled { color: %(disabled_ink)s; background: %(disabled)s; border-color: #d1d8e1; }
QToolButton::menu-indicator { subcontrol-position: right bottom; }
QToolButton[popupMode="1"] { padding-right: 20px; }
QToolButton::menu-button { background: %(workspace)s; border: 1px solid %(border)s; border-radius: 2px; width: 14px; }
QToolButton::menu-button:hover { background: %(hover)s; border-color: #8eaed1; }
QToolButton::menu-button:disabled { background: %(disabled)s; border-color: #d1d8e1; }
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QAbstractSpinBox {
    color: %(ink)s; background: %(surface)s; border: 1px solid %(border)s;
    border-radius: 2px; padding: 4px 6px;
    selection-background-color: %(selection)s; selection-color: %(selection_ink)s;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QAbstractSpinBox:focus { border-color: %(accent)s; }
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled, QAbstractSpinBox:disabled {
    color: %(disabled_ink)s; background: %(disabled)s; border-color: #d1d8e1;
}
QAbstractSpinBox QLineEdit { color: %(ink)s; background: transparent; border: 0; padding: 0; }
QAbstractSpinBox:disabled QLineEdit { color: %(disabled_ink)s; background: transparent; }
QComboBox::drop-down { border-left: 1px solid %(border)s; width: 20px; }
QComboBox QAbstractItemView { color: %(ink)s; background: %(surface)s; border: 1px solid %(border)s; selection-background-color: %(selection)s; selection-color: %(selection_ink)s; }
QAbstractItemView, QTreeView, QTreeWidget, QListView, QListWidget, QTableView, QTableWidget {
    color: %(ink)s; background: %(surface)s; alternate-background-color: %(alternate)s;
    border: 0; selection-background-color: %(selection)s; selection-color: %(selection_ink)s;
}
QAbstractItemView::item { color: %(ink)s; }
QAbstractItemView::item:hover { color: %(ink)s; background: %(hover)s; }
QAbstractItemView::item:selected, QAbstractItemView::item:selected:!active { color: %(selection_ink)s; background: %(selection)s; }
QAbstractItemView::item:disabled { color: %(disabled_ink)s; }
QTreeWidget::item { padding: 4px 2px; }
QHeaderView::section { color: %(muted)s; background: %(chrome)s; border: 0; border-bottom: 1px solid %(border)s; padding: 5px 7px; }
QMenu, QMenuBar { color: %(ink)s; background: %(surface)s; border: 1px solid %(border)s; }
QMenu { padding: 4px 0; menu-scrollable: 1; }
QMenu::item { color: %(ink)s; background: transparent; padding: 6px 26px 6px 12px; }
QMenu::item:selected, QMenuBar::item:selected { color: %(selection_ink)s; background: %(selection)s; }
QMenu::item:disabled { color: %(disabled_ink)s; background: transparent; }
QMenu::separator { height: 1px; background: %(border)s; margin: 4px 9px; }
QToolTip { color: white; background: %(tooltip)s; border: 1px solid %(tooltip)s; padding: 5px 7px; }
QLabel#NotificationBox_label { color: %(ink)s; background: %(surface)s; border: 1px solid %(border)s; }
QGroupBox { color: %(ink)s; background: %(surface)s; border: 1px solid %(border)s; border-radius: 2px; margin-top: 9px; padding: 9px 5px 5px; }
QGroupBox::title { color: %(ink)s; background: %(surface)s; subcontrol-origin: margin; left: 7px; padding: 0 3px; }
QCheckBox, QRadioButton { color: %(ink)s; background: transparent; spacing: 5px; }
QCheckBox:disabled, QRadioButton:disabled { color: %(disabled_ink)s; }
QScrollArea, QScrollArea > QWidget > QWidget { color: %(ink)s; background: %(surface)s; border: 0; }
QDockWidget#Tasks { color: %(ink)s; }
QTabBar::tab { color: %(muted)s; background: %(chrome)s; border: 0; padding: 7px 15px; }
QTabBar::tab:selected { color: %(accent)s; background: %(surface)s; border-top: 2px solid %(accent)s; }
QTabBar::tab:disabled { color: %(disabled_ink)s; background: %(disabled)s; }
QStatusBar { color: %(muted)s; border-top: 1px solid %(border)s; }
QStatusBar::item { border: 0; }
QProgressBar { color: %(ink)s; background: %(surface)s; border: 1px solid %(border)s; text-align: center; }
QProgressBar::chunk { background: %(selection)s; }
""" % COLORS


def _native_arrow_stylesheet():
    # FreeCAD's generated CSS uses theme-dependent qss: image tokens. Replacing
    # that CSS must also supply visible indicators, or dropdown arrows vanish.
    try:
        from pathlib import Path
        import FreeCAD as App
        images = Path(App.getResourceDir()) / "Gui" / "Stylesheets" / "images_dark-light"
        paths = {name: images / (name + "_arrow_darker.svg") for name in ("up", "down", "right")}
        if not all(path.is_file() for path in paths.values()):
            return ""
        return """
QComboBox::down-arrow { image: url("%(down)s"); width: 10px; height: 6px; }
QToolButton::menu-arrow { image: url("%(down)s"); width: 8px; height: 5px; }
QAbstractSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 17px; background: #ffffff; border-left: 1px solid #bdc7d3; }
QAbstractSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 17px; background: #ffffff; border-left: 1px solid #bdc7d3; border-top: 1px solid #bdc7d3; }
QAbstractSpinBox::up-button:disabled, QAbstractSpinBox::down-button:disabled { background: #eef1f5; }
QAbstractSpinBox::up-arrow { image: url("%(up)s"); width: 8px; height: 5px; }
QAbstractSpinBox::down-arrow { image: url("%(down)s"); width: 8px; height: 5px; }
QMenu::right-arrow { image: url("%(right)s"); width: 6px; height: 10px; }
""" % {name: path.as_posix() for name, path in paths.items()}
    except ImportError:
        return ""


STYLESHEET += _native_arrow_stylesheet()


def light_palette():
    from PySide import QtGui
    palette = QtGui.QPalette()
    values = {
        "Window": "workspace", "WindowText": "ink", "Base": "surface", "AlternateBase": "alternate",
        "Text": "ink", "Button": "surface", "ButtonText": "ink", "Highlight": "selection",
        "HighlightedText": "selection_ink", "ToolTipBase": "tooltip", "ToolTipText": "surface",
        "PlaceholderText": "placeholder", "Link": "accent", "LinkVisited": "accent_pressed",
        "Light": "surface", "Midlight": "chrome", "Mid": "border", "Dark": "muted", "Shadow": "ink",
    }
    for group in (QtGui.QPalette.Active, QtGui.QPalette.Inactive, QtGui.QPalette.Disabled):
        for role, token in values.items():
            palette.setColor(group, getattr(QtGui.QPalette, role), QtGui.QColor(COLORS[token]))
        palette.setColor(group, QtGui.QPalette.BrightText, QtGui.QColor("#ffffff"))
    for role in (QtGui.QPalette.WindowText, QtGui.QPalette.Text, QtGui.QPalette.ButtonText, QtGui.QPalette.PlaceholderText):
        palette.setColor(QtGui.QPalette.Disabled, role, QtGui.QColor(COLORS["disabled_ink"]))
    for role in (QtGui.QPalette.Base, QtGui.QPalette.Button):
        palette.setColor(QtGui.QPalette.Disabled, role, QtGui.QColor(COLORS["disabled"]))
    return palette


def native_theme_preferences():
    """Read diagnostic preferences without changing the user's configuration."""
    try:
        import FreeCAD as App
        prefs = App.ParamGet("User parameter:BaseApp/Preferences/General")
        return {key: prefs.GetString(key) for key in ("Theme", "StyleSheet", "OverlayActiveStyleSheet")}
    except ImportError:
        return {}


def apply_theme(main):
    """Apply before constructing the shell; future native dialogs inherit it."""
    from PySide import QtCore, QtGui
    from shiboken6 import isValid
    app = QtGui.QApplication.instance()
    if app is None:
        raise RuntimeError("The light theme requires the native QApplication.")
    previous = {"native_preferences": native_theme_preferences(), "application_stylesheet_length": len(app.styleSheet()),
                "window_stylesheet_length": len(main.styleSheet()), "previous_window_text": app.palette().color(QtGui.QPalette.WindowText).name()}
    app.setStyle("Fusion")
    palette = light_palette()
    notification_palette = QtGui.QPalette(palette)
    for group in (QtGui.QPalette.Active, QtGui.QPalette.Inactive, QtGui.QPalette.Disabled):
        notification_palette.setColor(group, QtGui.QPalette.ToolTipBase, QtGui.QColor(COLORS["surface"]))
        notification_palette.setColor(group, QtGui.QPalette.ToolTipText, QtGui.QColor(COLORS["ink"]))

    notification_style = "color: %(ink)s; background: %(surface)s; border: 1px solid %(border)s;" % COLORS
    floating_input_style = """
QAbstractSpinBox, QLineEdit { color: %(ink)s; background: %(surface)s;
    selection-background-color: %(selection)s; selection-color: %(selection_ink)s; }
QAbstractSpinBox QLineEdit { background: transparent; }
""" % COLORS

    def is_viewport_input(widget):
        if not isinstance(widget, (QtGui.QAbstractSpinBox, QtGui.QLineEdit)):
            return False
        parent = widget.parentWidget()
        while parent is not None:
            if parent.metaObject().className() == "Gui::View3DInventor":
                return True
            parent = parent.parentWidget()
        return False

    def set_widget_palette(widget):
        # FreeCAD draws parentless notifications using its separate tooltip
        # palette. Keep that panel consistent with its explicit QLabel colors.
        notification = (widget.objectName() == "NotificationBox_label"
                        or widget.metaObject().className() == "Gui::NotificationLabel")
        widget.setPalette(notification_palette if notification else palette)

    def set_widget_style(widget):
        notification = (widget.objectName() == "NotificationBox_label"
                        or widget.metaObject().className() == "Gui::NotificationLabel")
        # Native floating editors can install their own theme stylesheet,
        # which takes precedence over the application palette and CSS. Own
        # these two surfaces' colors locally, without changing native sizing.
        local_style = notification_style if notification else floating_input_style if is_viewport_input(widget) else None
        if local_style is not None and widget.styleSheet() != local_style:
            widget.setStyleSheet(local_style)

    app.setPalette(palette)
    main.setStyleSheet("")  # Remove the separate generated FreeCAD/dark window stylesheet.
    app.setStyleSheet(STYLESHEET)
    main.setPalette(palette)
    for widget in main.findChildren(QtGui.QWidget):
        set_widget_palette(widget)
        set_widget_style(widget)
    # A notification can already be visible before the app theme is applied;
    # parentless windows are absent from the main window's child traversal.
    for widget in app.topLevelWidgets():
        set_widget_palette(widget)
        set_widget_style(widget)
    QtGui.QToolTip.setPalette(palette)

    old_filter = getattr(app, "_kurtshape_theme_filter", None)
    if old_filter is not None:
        app.removeEventFilter(old_filter)
        old_filter.deleteLater()

    pending_styles = set()

    def defer_widget_style(widget):
        key = id(widget)
        if key in pending_styles:
            return
        pending_styles.add(key)
        def apply_when_ready():
            pending_styles.discard(key)
            if isValid(widget):
                set_widget_style(widget)
        # A stylesheet can rebuild native child controls. Let their current
        # constructor/Show/Polish handler finish before changing local CSS.
        QtCore.QTimer.singleShot(0, apply_when_ready)

    class NativePaletteFilter(QtCore.QObject):
        def eventFilter(self, watched, event):
            if event.type() in (QtCore.QEvent.Polish, QtCore.QEvent.Show) and isinstance(watched, QtGui.QWidget):
                # Native task widgets/popups may carry an explicit startup palette.
                set_widget_palette(watched)
                if isinstance(watched, (QtGui.QAbstractSpinBox, QtGui.QLineEdit)) or watched.objectName() == "NotificationBox_label" or watched.metaObject().className() == "Gui::NotificationLabel":
                    defer_widget_style(watched)
                if isinstance(watched, QtGui.QMenu):
                    # Qt may use full monitor height for scrolling menus. Keep
                    # every action above the Windows taskbar on this monitor.
                    screen = watched.screen() or main.screen()
                    watched.setMaximumHeight(max(1, screen.availableGeometry().height() - 8))
            return False

    app._kurtshape_theme_filter = NativePaletteFilter(app)
    app.installEventFilter(app._kurtshape_theme_filter)
    app._kurtshape_theme_diagnostics = previous
    main.setProperty("kurtshapeLightTheme", True)
    return previous
