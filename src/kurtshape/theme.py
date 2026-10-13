"""Application-owned light Qt theme, including FreeCAD's native task widgets.

FreeCAD's generated stylesheet and OS-derived palette are independent. Painting
light input backgrounds without replacing the dark palette leaves white text.
KurtShape therefore owns both the QApplication palette and stylesheet. This
owns this local KurtShape profile's appearance, including native text and sketch
colors. No Windows setting or model ViewObject color is changed.
"""
from __future__ import annotations

COLORS = {
    "workspace": "#f5f6f7", "surface": "#ffffff", "viewport": "#ffffff", "chrome": "#f5f6f7",
    "chrome_subtle": "#fafafa", "alternate": "#fafafa", "ink": "#2d3338", "muted": "#59636c",
    "placeholder": "#65717c", "disabled_ink": "#646f78", "disabled": "#f1f3f5",
    "divider": "#d6dadf", "border": "#8a949e", "hover": "#edf2f6", "selection": "#e6f1fa",
    "active_field_fill": "#e6f1fa", "selection_ink": "#204f79", "accent": "#185fa5", "accent_pressed": "#124b83",
    "error": "#bd3039", "warning": "#8c6005", "success": "#247a43", "tooltip": "#353a40", "tooltip_border": "#242a30",
    "geometry_selected": "#ffc107",
}

# Native Sketcher evaluates each point/curve using solver geometry extensions.
# Keep that classification: a fixed curve in an otherwise free sketch is black.
SKETCH_STATE_COLORS = {
    "ConstrainedDimColor": "#000000", "NonDrivingConstrDimColor": "#000000",
    "ExprBasedConstrDimColor": "#000000", "DeactivatedConstrDimColor": "#000000",
    "EditedEdgeColor": "#0000ff", "EditedVertexColor": "#0000ff",
    "SketchEdgeColor": "#0000ff", "SketchVertexColor": "#0000ff",
    "FullyConstraintElementColor": "#000000", "FullyConstrainedColor": "#000000",
    "InvalidSketchColor": "#ff0000",
    "ConstructionColor": "#0000ff",
    "FullyConstraintConstructionElementColor": "#000000",
    "FullyConstraintConstructionPointColor": "#000000",
    "ExternalDefiningColor": "#000000",
    "ExternalColor": "#000000",
    "InternalAlignedGeoColor": "#0000ff",
    "FullyConstraintInternalAlignmentColor": "#000000",
}


def apply_sketch_color_preferences():
    """Use native per-geometry solver colors, including already-open editors."""
    import FreeCAD as App
    prefs = App.ParamGet("User parameter:BaseApp/Preferences/View")
    changed = []
    for name, color in SKETCH_STATE_COLORS.items():
        value = int(color[1:] + "ff", 16)
        if prefs.GetUnsigned(name, 0) != value:
            prefs.SetUnsigned(name, value)
            changed.append("View/" + name)
    return changed


def apply_view_theme(view):
    """Own this native viewer's background without writing user preferences."""
    viewer = view.getViewer()
    white = (1.0, 1.0, 1.0)
    viewer.setBackgroundColor(*white)
    viewer.setGradientBackgroundColor(white, white, white)
    view.redraw()

STYLESHEET = """
QWidget { color: %(ink)s; font-family: 'Segoe UI'; font-size: 13px; }
QWidget:disabled { color: %(disabled_ink)s; }
QMainWindow, QDialog, QDockWidget, QToolBar, QStatusBar, QTabWidget::pane {
    color: %(ink)s; background-color: %(workspace)s;
}
QLabel { color: %(ink)s; background-color: transparent; }
QLabel:disabled { color: %(disabled_ink)s; }
QLabel#KurtShapeBrand { font-size: 16px; font-weight: 600; padding: 0 6px; }
QLabel#KurtShapeDocumentIdentity { font-size: 14px; font-weight: 600; padding: 0 6px; }
QLabel#KurtShapeStatusMessage, QLabel#KurtShapeDocumentStatus { color: %(muted)s; }
QLabel[severity="error"], QLabel#KurtShapeStatusMessage[severity="error"], QLabel#KurtShapeDocumentStatus[severity="error"] { color: %(error)s; }
QLabel[severity="warning"], QLabel#KurtShapeStatusMessage[severity="warning"], QLabel#KurtShapeDocumentStatus[severity="warning"] { color: %(warning)s; }
QLabel[severity="success"], QLabel#KurtShapeStatusMessage[severity="success"], QLabel#KurtShapeDocumentStatus[severity="success"] { color: %(success)s; }
QLabel#SectionTitle { color: %(muted)s; background: %(chrome)s; font-weight: 600; padding: 5px 8px; }
QToolBar { background: %(chrome)s; border: 0; border-bottom: 1px solid %(divider)s; spacing: 0; padding: 0 4px; }
QToolBar::separator { width: 1px; background: %(divider)s; margin: 5px 4px; }
QToolBar QToolButton { min-width: 22px; min-height: 22px; padding: 4px; }
QToolBar QToolButton:disabled { background: transparent; border-color: transparent; }
QDockWidget { border: 0; }
QDockWidget::title { color: %(ink)s; background: %(chrome)s; padding: 5px 8px; border-bottom: 1px solid %(divider)s; }
QPushButton, QToolButton {
    color: %(ink)s; background-color: %(surface)s; border: 1px solid %(border)s;
    border-radius: 2px; padding: 4px 8px; min-height: 20px;
}
QToolButton { background-color: transparent; border-color: transparent; padding: 4px 6px; }
QPushButton:hover, QToolButton:hover { color: %(ink)s; background: %(hover)s; border-color: %(border)s; }
QPushButton:pressed, QPushButton:checked, QToolButton:pressed, QToolButton:checked { color: %(selection_ink)s; background: %(selection)s; border-color: %(accent)s; }
QPushButton:focus, QToolButton:focus { border-color: %(accent)s; }
QPushButton:default, QPushButton#Confirm { color: white; background: %(accent)s; border-color: %(accent)s; font-weight: 600; }
QPushButton:default:hover, QPushButton#Confirm:hover { color: white; background: %(accent_pressed)s; }
QPushButton#Cancel { color: %(ink)s; background: %(surface)s; }
QPushButton:disabled, QToolButton:disabled { color: %(disabled_ink)s; background: %(disabled)s; border-color: %(divider)s; }
QPushButton#Confirm:disabled, QPushButton#Cancel:disabled, QPushButton:default:disabled { color: %(disabled_ink)s; background: %(disabled)s; border-color: %(divider)s; }
QToolButton::menu-indicator { subcontrol-position: right bottom; }
QToolButton[popupMode="1"] { padding-right: 20px; }
QToolButton::menu-button { background: %(workspace)s; border: 1px solid %(border)s; border-radius: 2px; width: 14px; }
QToolButton::menu-button:hover { background: %(hover)s; border-color: %(border)s; }
QToolButton::menu-button:disabled { background: %(disabled)s; border-color: %(divider)s; }
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QAbstractSpinBox {
    color: %(ink)s; background: %(surface)s; border: 1px solid %(border)s;
    border-radius: 2px; padding: 4px 6px; min-height: 18px;
    selection-background-color: %(selection)s; selection-color: %(selection_ink)s;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QAbstractSpinBox:focus { border-color: %(accent)s; }
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled, QAbstractSpinBox:disabled {
    color: %(disabled_ink)s; background: %(disabled)s; border-color: %(divider)s;
}
QAbstractSpinBox QLineEdit { color: %(ink)s; background: transparent; border: 0; padding: 0; min-height: 0; }
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
QTreeWidget::item { padding: 3px 2px; }
QHeaderView::section { color: %(muted)s; background: %(chrome)s; border: 0; border-bottom: 1px solid %(divider)s; padding: 4px 7px; }
QMenu, QMenuBar { color: %(ink)s; background: %(surface)s; border: 1px solid %(border)s; }
QMenu { padding: 4px 0; menu-scrollable: 1; }
QMenu::item { color: %(ink)s; background: transparent; padding: 6px 26px 6px 12px; }
QMenu::item:selected, QMenuBar::item:selected { color: %(selection_ink)s; background: %(selection)s; }
QMenu::item:disabled { color: %(disabled_ink)s; background: transparent; }
QMenu::separator { height: 1px; background: %(border)s; margin: 4px 9px; }
QToolTip, QLabel#KurtShapeToolbarLabel { color: white; background: %(tooltip)s; border: 1px solid %(tooltip_border)s; border-radius: 2px; padding: 5px 8px; }
QLabel#NotificationBox_label { color: %(ink)s; background: %(surface)s; border: 1px solid %(border)s; }
QGroupBox { color: %(ink)s; background: %(surface)s; border: 1px solid %(border)s; border-radius: 2px; margin-top: 9px; padding: 9px 5px 5px; }
QGroupBox::title { color: %(ink)s; background: %(surface)s; subcontrol-origin: margin; left: 7px; padding: 0 3px; }
QCheckBox, QRadioButton { color: %(ink)s; background: transparent; spacing: 5px; }
QCheckBox:disabled, QRadioButton:disabled { color: %(disabled_ink)s; }
QScrollArea, QScrollArea > QWidget > QWidget { color: %(ink)s; background: %(surface)s; border: 0; }
QDockWidget#Tasks { color: %(ink)s; }
QTabBar::tab { color: %(muted)s; background: %(chrome)s; border: 0; padding: 5px 12px; }
QTabBar::tab:selected { color: %(accent)s; background: %(surface)s; border-bottom: 2px solid %(accent)s; }
QTabBar::tab:disabled { color: %(disabled_ink)s; background: %(disabled)s; }
QStatusBar { color: %(muted)s; border-top: 1px solid %(divider)s; }
QStatusBar::item { border: 0; }
QProgressBar { color: %(ink)s; background: %(surface)s; border: 1px solid %(border)s; text-align: center; }
QProgressBar::chunk { background: %(selection)s; }
QWidget#KurtShapeFeatureHeader { background: %(chrome)s; border-bottom: 1px solid %(divider)s; }
QLabel#KurtShapeFeatureTitle { color: %(ink)s; font-size: 14px; font-weight: 600; }
QToolButton#KurtShapeFeatureConfirm, QToolButton#KurtShapeFeatureCancel {
    background: transparent; border: 1px solid transparent; padding: 2px; min-width: 22px; min-height: 22px;
}
QToolButton#KurtShapeFeatureConfirm:hover, QToolButton#KurtShapeFeatureCancel:hover { background: %(hover)s; border-color: %(border)s; }
QToolButton#KurtShapeFeatureConfirm:focus, QToolButton#KurtShapeFeatureCancel:focus { border-color: %(accent)s; }
QToolButton#KurtShapeFeatureConfirm:disabled, QToolButton#KurtShapeFeatureCancel:disabled { color: %(disabled_ink)s; background: transparent; border-color: transparent; }
QWidget#KurtShapeReferencePicker { background: %(surface)s; border: 1px solid %(border)s; border-radius: 2px; }
QWidget#KurtShapeReferencePicker[activePicking="true"], QWidget#KurtShapeReferencePicker[pickingState="active"] {
    background: %(active_field_fill)s; border-color: %(accent)s;
}
QWidget#KurtShapeReferencePicker[pickingState="invalid"] { border-color: %(error)s; }
QWidget#KurtShapeReferencePicker[pickingState="disabled"] { background: %(disabled)s; border-color: %(divider)s; }
QPushButton#KurtShapeReferencePick { text-align: left; background: transparent; border-color: transparent; }
QPushButton#KurtShapeReferencePick:checked { color: %(selection_ink)s; background: %(active_field_fill)s; border-color: %(accent)s; }
QPushButton#KurtShapeReferencePick:focus { border-color: %(accent)s; }
QPushButton#KurtShapeReferencePick:disabled { color: %(disabled_ink)s; background: %(disabled)s; border-color: transparent; }
QToolButton#KurtShapeReferenceRemove, QToolButton#KurtShapeReferenceRowRemove, QToolButton#KurtShapeReferenceMenu { min-height: 14px; min-width: 14px; padding: 2px; }
QToolButton#KurtShapeReferenceMenu::menu-indicator { image: none; width: 0; height: 0; }
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
QAbstractSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 17px; background: %(surface)s; border-left: 1px solid %(border)s; }
QAbstractSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 17px; background: %(surface)s; border-left: 1px solid %(border)s; border-top: 1px solid %(border)s; }
QAbstractSpinBox::up-button:disabled, QAbstractSpinBox::down-button:disabled { background: %(disabled)s; }
QAbstractSpinBox::up-arrow { image: url("%(up)s"); width: 8px; height: 5px; }
QAbstractSpinBox::down-arrow { image: url("%(down)s"); width: 8px; height: 5px; }
QMenu::right-arrow { image: url("%(right)s"); width: 6px; height: 10px; }
""" % {**COLORS, **{name: path.as_posix() for name, path in paths.items()}}
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
        prefs = App.ParamGet("User parameter:BaseApp/Preferences/MainWindow")
        return {key: prefs.GetString(key) for key in ("Theme", "StyleSheet", "OverlayActiveStyleSheet")}
    except ImportError:
        return {}


def apply_native_light_preferences():
    """Align native drawing/text colors with the white shell and canvas.

    A Qt palette cannot override Coin sketch colors or rich report text. Read
    the installed Light pack selectively; a whole pack would also overwrite
    model defaults, navigation, selection colors and unrelated workbenches.
    """
    import FreeCAD as App
    from pathlib import Path
    from xml.etree import ElementTree

    pack = Path(App.getResourceDir()) / "Gui/PreferencePacks/FreeCAD Light/FreeCAD Light.cfg"
    preferences = ElementTree.parse(pack).getroot().find(
        "./FCParamGroup[@Name='Root']/FCParamGroup[@Name='BaseApp']/FCParamGroup[@Name='Preferences']")
    view_names = {
        "AnnotationTextColor", "AxisLetterColor", "CbLabelColor", "ConstrainedDimColor",
        "ConstrainedIcoColor", "ConstructionColor", "CreateLineColor", "CursorCrosshairColor",
        "CursorTextColor", "DeactivatedConstrDimColor", "EditedEdgeColor", "EditedVertexColor",
        "ExprBasedConstrDimColor", "ExternalColor", "FullyConstrainedColor",
        "FullyConstraintConstructionElementColor", "FullyConstraintConstructionPointColor",
        "FullyConstraintElementColor", "FullyConstraintInternalAlignmentColor",
        "InternalAlignedGeoColor", "InvalidSketchColor", "NonDrivingConstrDimColor",
        "SketchEdgeColor", "SketchVertexColor",
    }
    changed = []
    groups = (
        ("View", view_names), ("Editor", None),
        ("Mod/Measure/Appearance", {"DefaultTextColor", "DefaultTextBackgroundColor"}),
        ("Mod/Sketcher/General", {"GridDivLineColor", "GridLineColor"}),
    )
    for path, names in groups:
        node = preferences
        for part in path.split("/"):
            node = node.find("FCParamGroup[@Name='" + part + "']")
        params = App.ParamGet("User parameter:BaseApp/Preferences/" + path)
        for entry in node.findall("FCUInt"):
            name, value = entry.get("Name"), int(entry.get("Value"))
            if names is None or name in names:
                if params.GetUnsigned(name, 0) != value:
                    params.SetUnsigned(name, value)
                    changed.append(path + "/" + name)
    changed.extend(apply_sketch_color_preferences())
    output = App.ParamGet("User parameter:BaseApp/Preferences/OutputWindow")
    for name, token in (("colorText", "ink"), ("colorLogging", "muted"),
                        ("colorError", "error"), ("colorWarning", "warning")):
        value = int(COLORS[token][1:] + "ff", 16)
        if output.GetUnsigned(name, 0) != value:
            output.SetUnsigned(name, value)
            changed.append("OutputWindow/" + name)
    native = App.ParamGet("User parameter:BaseApp/Preferences/MainWindow")
    if native.GetString("Theme") != "FreeCAD Light":
        native.SetString("Theme", "FreeCAD Light")
        changed.append("MainWindow/Theme")
    if changed:
        App.saveParameter()
    return changed


def apply_theme(main):
    """Apply before constructing the shell; future native dialogs inherit it."""
    from PySide import QtCore, QtGui
    from shiboken6 import isValid
    app = QtGui.QApplication.instance()
    if app is None:
        raise RuntimeError("The light theme requires the native QApplication.")
    previous = {"native_preferences": native_theme_preferences(), "application_stylesheet_length": len(app.styleSheet()),
                "window_stylesheet_length": len(main.styleSheet()), "previous_window_text": app.palette().color(QtGui.QPalette.WindowText).name()}
    import FreeCAD as App
    native_output = App.ParamGet("User parameter:BaseApp/Preferences/OutputWindow")
    report_colors = {}
    for name, token in (("colorText", "ink"), ("colorLogging", "muted"),
                        ("colorError", "error"), ("colorWarning", "warning")):
        value = native_output.GetUnsigned(name, 0)
        if value:
            report_colors["#%06x" % (value >> 8)] = COLORS[token]
    previous["native_appearance_changes"] = apply_native_light_preferences()
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
    # Existing native report lines contain explicit rich-text foregrounds;
    # palette updates affect new lines but cannot recolor those old fragments.
    for report_widget in main.findChildren(QtGui.QTextEdit):
        if report_widget.metaObject().className() != "Gui::DockWnd::ReportOutput":
            continue
        document = report_widget.document()
        edits = []
        block = document.begin()
        while block.isValid():
            fragment_iterator = block.begin()
            while not fragment_iterator.atEnd():
                fragment = fragment_iterator.fragment()
                if fragment.isValid():
                    target = report_colors.get(fragment.charFormat().foreground().color().name())
                    if target is not None:
                        edits.append((fragment.position(), fragment.length(), target))
                fragment_iterator += 1
            block = block.next()
        cursor = QtGui.QTextCursor(document)
        for position, length, color in edits:
            cursor.setPosition(position)
            cursor.setPosition(position + length, QtGui.QTextCursor.KeepAnchor)
            format = QtGui.QTextCharFormat()
            format.setForeground(QtGui.QColor(color))
            cursor.mergeCharFormat(format)
        # Native ReportHighlighter stores severity outside the rich fragments.
        # Parameter changes update its colors but leave retained block formats
        # cached. Refresh those formats through Qt, preserving native severity.
        for highlighter in report_widget.findChildren(QtGui.QSyntaxHighlighter):
            highlighter.rehighlight()
    QtGui.QToolTip.setPalette(palette)

    old_filter = getattr(app, "_kurtshape_theme_filter", None)
    if old_filter is not None:
        app.removeEventFilter(old_filter)
        old_filter.deleteLater()

    pending_styles = set()

    def owned_palette_is_current():
        current = app.palette()
        roles = (QtGui.QPalette.Window, QtGui.QPalette.WindowText, QtGui.QPalette.Base,
                 QtGui.QPalette.Text, QtGui.QPalette.Button, QtGui.QPalette.ButtonText,
                 QtGui.QPalette.Highlight, QtGui.QPalette.HighlightedText)
        return all(current.color(group, role) == palette.color(group, role)
                   for group in (QtGui.QPalette.Active, QtGui.QPalette.Inactive, QtGui.QPalette.Disabled)
                   for role in roles)

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
        def __init__(self, parent):
            super().__init__(parent)
            self.pending = False
            self.restoring = False

        def restore_owned_theme(self):
            self.pending = False
            if self.restoring or not isValid(self) or not isValid(main) or getattr(app, "_kurtshape_theme_filter", None) is not self:
                return
            self.restoring = True
            try:
                if native_theme_preferences().get("Theme") != "FreeCAD Light":
                    apply_native_light_preferences()
                # FreeCAD's delayed MainWindow preference observer can replace
                # QApplication CSS after startup or native Preferences Apply.
                if app.styleSheet() != STYLESHEET:
                    app.setStyleSheet(STYLESHEET)
                if main.styleSheet():
                    main.setStyleSheet("")
                if not owned_palette_is_current():
                    app.setPalette(palette)
            finally:
                self.restoring = False

        def eventFilter(self, watched, event):
            if not isValid(main):
                return False
            if event.type() in (QtCore.QEvent.StyleChange, QtCore.QEvent.ApplicationPaletteChange):
                if not self.restoring and not self.pending and (app.styleSheet() != STYLESHEET
                        or main.styleSheet() or not owned_palette_is_current()):
                    self.pending = True
                    QtCore.QTimer.singleShot(0, self.restore_owned_theme)
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
