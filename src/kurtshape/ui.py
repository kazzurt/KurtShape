"""Onshape-style desktop organization around one native FreeCAD document."""
from __future__ import annotations
from contextlib import nullcontext
import os
import json
import time
from pathlib import Path
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui
from .core import Controller, ROOT, METADATA, OperationError, number
from . import extrusion_edit
from .bridge import Bridge
from . import navigation
from . import geometry
from .shortcuts import ShortcutRouter
from .general_actions import GeneralActions
from .viewport_actions import callbacks as viewport_callbacks
from .theme import apply_theme, apply_view_theme, COLORS
from .feature_tools import available_catalog
from .quantity_field import QuantityField
from .extrusion_preview import DebouncedExtrusionPreview
from .workspace_preferences import WorkspacePreferences
from .sketch_tools import run_command as run_sketch_command
from .sketch_tools import show_unconsumed_sketch
from .sketch_references import SketchReferences
from .sketch_edit_panel import SketchPlaneEditor
from .sketch_history import HistoricalSketchView
from .sketch_colors import NativeSketchColors
from .sketch_regions import SketchRegionFill
from .sketch_snapping import SketchSnapping
from .sketch_cursor import SketchCursor
from .bodies import bodies, owner, origin_plane, results as native_results
from .feature_panel import FeaturePanel, ReferencePicker
from .presentation_icons import icon_for
from .toolbar_labels import ToolbarLabels
from .rollback_history import RollbackMarker
from .history_selection import HistorySelection, ROLLED_BACK_ROLE
from .history_model import HistoryModel
from .responsiveness import install_monitor


class DocumentLabel(QtGui.QLabel):
    """Keep the document identity readable without consuming the toolbar."""
    def __init__(self):
        super().__init__()
        self.full_text = ""
        self.setMinimumWidth(90)
        self.setSizePolicy(QtGui.QSizePolicy.Expanding, QtGui.QSizePolicy.Preferred)

    def setText(self, text):
        self.full_text = text
        self.setToolTip(text)
        self.update_text()

    def update_text(self):
        super().setText(self.fontMetrics().elidedText(self.full_text, QtCore.Qt.ElideRight, max(60, self.width() - 12)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_text()

class SearchField(QtGui.QLineEdit):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.setObjectName("KurtShapeToolSearch")
        self.setPlaceholderText("Search tools…  Alt+C")
        self.setAccessibleName("Search tools")
        self.setReadOnly(True)
        self.setFixedWidth(175)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.callback()
        else:
            super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in {QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter, QtCore.Qt.Key_Space}:
            self.callback()
        else:
            super().keyPressEvent(event)

def metadata_id(doc):
    return doc.getObject(METADATA).DocumentId

def native_plane(doc, plane, body=None):
    body = body or (bodies(doc)[0] if doc and len(bodies(doc)) == 1 else None)
    if body:
        return origin_plane(body, plane)

def hide_native_panels():
    main = Gui.getMainWindow()
    for dock in main.findChildren(QtGui.QDockWidget):
        if dock.objectName() in {"Combo View", "Tree view", "Property view", "Report view", "Python console"} or dock.windowTitle() in {"Model", "Combo View", "Property view", "Report view", "Python console"}:
            dock.hide()
        elif dock.windowTitle() == "Tasks":
            if main.dockWidgetArea(dock) != QtCore.Qt.RightDockWidgetArea:
                main.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
            if not Gui.Control.activeDialog():
                dock.hide()
    for bar in main.findChildren(QtGui.QToolBar):
        if not bar.objectName().startswith("KurtShape"):
            bar.hide()

class SelectionObserver:
    def __init__(self, panel):
        self.panel = panel

    def addSelection(self, document, object_name, subelement, *args):
        p = self.panel
        if p.core.busy:
            return
        if p.sketch_plane_editor.selection_pick(document, object_name, subelement):
            return
        if p.pending_sketch and not p.selecting_support:
            obj = App.getDocument(document).getObject(object_name)
            if obj and (obj.TypeId in {"App::Plane", "PartDesign::Plane"} or subelement.startswith("Face")):
                p.selecting_support = True
                QtCore.QTimer.singleShot(0, lambda: p.choose_support(document, object_name, subelement))
        QtCore.QTimer.singleShot(0, p.capture_feature_selection)

class Panel(QtGui.QDockWidget):
    MEASURE = False

    def __init__(self, controller):
        super().__init__("Feature history")
        self.setObjectName("KurtShapeHistory")
        self.setFeatures(QtGui.QDockWidget.NoDockWidgetFeatures)
        self.setMinimumWidth(235)
        self.setMaximumWidth(430)
        self.core, self.state = controller, None
        self._step_export_generation = 0
        self._step_export_job = None
        self._step_export_document = None
        self._step_export_preparing = False
        self._step_export_preparing_generation = None
        self._step_export_closed = False
        self.step_export_timer = QtCore.QTimer(self)
        self.step_export_timer.setInterval(30)
        self.step_export_timer.timeout.connect(self._poll_step_export)
        self._geometry_check_generation = 0
        self._geometry_check_job = None
        self._geometry_check_document = None
        self._geometry_check_preparing = False
        self._geometry_check_preparing_generation = None
        self._geometry_check_closed = False
        self.geometry_check_timer = QtCore.QTimer(self)
        self.geometry_check_timer.setInterval(30)
        self.geometry_check_timer.timeout.connect(self._poll_geometry_check)
        self.pending_sketch = self.selecting_support = self.refreshing = False
        self.plane_visibility, self.items = {}, {}
        self.task = self.task_profile = self.last_document = self.last_status = None
        self.task_edit = None
        self.finishing_sketch = False
        self.entering_sketch = False
        self.placement_document = self.task_document = None
        self.workspace_modes = {}
        self.workspace_documents = {}
        self.workspace_mode = "part_studio"
        self.rollback_selected = False
        self.studio_dialog = None
        self.studio_selection_callback = None
        self.studio_committing = False
        self.main = Gui.getMainWindow()
        self.sketch_references = SketchReferences(self)
        self.sketch_history = HistoricalSketchView(self)
        self.sketch_colors = NativeSketchColors(self)
        self.sketch_regions = SketchRegionFill(self)
        self.sketch_snapping = SketchSnapping()
        self.sketch_cursor = SketchCursor(self)
        self.main.menuBar().hide()
        self.main.statusBar().show()
        self.toolbar_labels = ToolbarLabels(self.main)
        self.make_history()
        self.make_editor()
        self.model_actions = []
        self.tool_menus = {}
        self.make_toolbars()
        self.make_messages()
        self.status_timer = QtCore.QTimer(self)
        self.status_timer.setSingleShot(True)
        self.status_timer.setInterval(4500)
        self.status_timer.timeout.connect(self.restore_status)
        self.workspace_preferences = WorkspacePreferences(self)
        self.extrusion_preview = DebouncedExtrusionPreview(
            self.core, self, status=self.preview_status,
            allowed=lambda: self.task in {"pad", "pocket"} and self.editor.isVisible())
        self.depth.lineEdit().textChanged.connect(self.schedule_preview)
        self.end_type.currentIndexChanged.connect(self.schedule_preview)
        self.reverse.toggled.connect(self.schedule_preview)
        self.formula.textChanged.connect(self.schedule_preview)
        self.edit_depth_touched = False
        self.depth.lineEdit().textEdited.connect(self.mark_depth_touched)
        self.depth.native.installEventFilter(self)
        self.result_operation.currentIndexChanged.connect(self.result_operation_changed)
        self.merge_scope.currentIndexChanged.connect(self.schedule_preview)
        self.merge_parts.itemChanged.connect(self.schedule_preview)
        self.observer = SelectionObserver(self)
        Gui.Selection.addObserver(self.observer)
        self.general_actions = GeneralActions(self)
        self.router = ShortcutRouter(QtGui.QApplication.instance(), self.shortcut_callbacks(), self.context,
                                     self.notify, native_runner=self.native_command,
                                     native_state=self.sketch_references.native_command_for_context)
        self.router.install()
        session_dir = Path(os.environ.get("KURTSHAPE_SESSION_DIR", str(ROOT / "runtime")))
        session_dir.mkdir(parents=True, exist_ok=True)
        self.bridge = Bridge(controller, session_dir)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(25)
        self.recovery_timer = QtCore.QTimer(self)
        self.recovery_timer.timeout.connect(self.checkpoint_projects)
        self.recovery_timer.start(1000)
        self.feedback_started = None
        self.feedback_kind = "ordinary"
        self.main.installEventFilter(self)
        QtGui.QApplication.instance().installEventFilter(self)
        self.responsiveness = install_monitor(self)
        self.feature_model = HistoryModel(self.features)
        self.part_model = HistoryModel(self.parts)

    def make_history(self):
        container = QtGui.QWidget()
        layout = QtGui.QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.filter = QtGui.QLineEdit()
        self.filter.setPlaceholderText("Filter features")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self.filter_features)
        history = QtGui.QWidget()
        history_layout = QtGui.QVBoxLayout(history)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_layout.setSpacing(0)
        history_layout.addWidget(self.filter)
        self.features_title = QtGui.QLabel("Features")
        self.features_title.setObjectName("SectionTitle")
        history_layout.addWidget(self.features_title)
        self.features = QtGui.QTreeWidget()
        self.features.setHeaderHidden(True)
        self.features.setSelectionMode(QtGui.QAbstractItemView.ExtendedSelection)
        self.history_controller = HistorySelection(self)
        self.features.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.features.customContextMenuRequested.connect(self.history_menu)
        self.features.itemSelectionChanged.connect(self.history_selection)
        self.features.itemClicked.connect(self.history_click)
        self.features.itemDoubleClicked.connect(self.history_double_click)
        history_layout.addWidget(self.features, 1)
        self.rollback_label = QtGui.QLabel("End of history")
        self.rollback_label.setMargin(5)
        self.rollback_label.setWordWrap(True)
        history_layout.addWidget(self.rollback_label)
        self.rollback_bar = RollbackMarker(self.features)
        self.rollback_bar.sliderPressed.connect(lambda: setattr(self, "rollback_selected", True))
        self.rollback_bar.valueChanged.connect(lambda index: self.rollback_label.setText(self.rollback_bar.description(index)))
        self.rollback_bar.sliderReleased.connect(self.commit_rollback)
        self.rollback_bar.installEventFilter(self)
        parts = QtGui.QWidget()
        parts_layout = QtGui.QVBoxLayout(parts)
        parts_layout.setContentsMargins(0, 0, 0, 0)
        parts_layout.setSpacing(0)
        self.parts_title = QtGui.QLabel("Parts (0)")
        self.parts_title.setObjectName("SectionTitle")
        parts_layout.addWidget(self.parts_title)
        self.body_choice = QtGui.QComboBox()
        self.body_choice.setToolTip("Part for new sketches and features")
        self.body_choice.currentIndexChanged.connect(self.change_body)
        parts_layout.addWidget(self.body_choice)
        self.parts = QtGui.QTreeWidget()
        self.parts.setHeaderHidden(True)
        self.parts.setMinimumHeight(58)
        self.parts.itemClicked.connect(self.part_selection)
        self.parts.itemChanged.connect(self.part_visibility_changed)
        self.parts.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.parts.customContextMenuRequested.connect(self.part_menu)
        parts_layout.addWidget(self.parts, 1)
        self.history_splitter = QtGui.QSplitter(QtCore.Qt.Vertical)
        self.history_splitter.setObjectName("KurtShapeHistoryPartsSplit")
        self.history_splitter.setChildrenCollapsible(False)
        self.history_splitter.addWidget(history)
        self.history_splitter.addWidget(parts)
        self.history_splitter.setStretchFactor(0, 3)
        self.history_splitter.setStretchFactor(1, 1)
        self.history_splitter.setSizes([500, 190])
        layout.addWidget(self.history_splitter, 1)
        self.status = QtGui.QLabel("Create or open a part studio")
        self.status.setWordWrap(True)
        self.status.setMargin(6)
        self.status.setObjectName("KurtShapeDocumentStatus")
        layout.addWidget(self.status)
        self.setWidget(container)

    def make_editor(self):
        self.editor = FeaturePanel("Feature settings", self.main)
        self.editor.setObjectName("KurtShapeEditor")
        widget = self.editor.content
        layout = QtGui.QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        self.editor_title = self.editor.title
        self.editor_help = QtGui.QLabel("")
        self.editor_help.setWordWrap(True)
        layout.addWidget(self.editor_help)
        self.sketch_plane_editor = SketchPlaneEditor(self)
        layout.addWidget(self.sketch_plane_editor.widget)
        self.form = QtGui.QFormLayout()
        self.form.setRowWrapPolicy(QtGui.QFormLayout.WrapLongRows)
        self.parameter = QtGui.QComboBox()
        self.parameter.currentIndexChanged.connect(self.parameter_value)
        self.value = QuantityField()
        self.value.setRange(-100000, 100000)
        self.value.setDecimals(4)
        self.value.setSuffix(" mm")
        self.depth = QuantityField()
        self.depth.setRange(0.01, 100000)
        self.depth.setValue(6)
        self.depth.setDecimals(3)
        self.depth.setSuffix(" mm")
        self.end_type = QtGui.QComboBox()
        self.end_type.addItems(["Blind", "Through all", "Up to face"])
        self.end_type.currentIndexChanged.connect(lambda: self.depth.setEnabled(self.end_type.currentIndex() == 0))
        self.reverse = QtGui.QCheckBox("Reverse direction")
        self.result_operation = QtGui.QComboBox()
        self.result_operation.setObjectName("KurtShapeResultOperation")
        for label, value in (("New", "new"), ("Add", "add"), ("Remove", "remove"), ("Intersect", "intersect")):
            self.result_operation.addItem(label, value)
        self.merge_scope = QtGui.QComboBox()
        self.merge_scope.setObjectName("KurtShapeMergeScope")
        self.merge_scope.addItem("Auto · touching parts", "auto")
        self.merge_scope.addItem("Selected parts", "explicit")
        self.merge_parts = QtGui.QListWidget()
        self.merge_parts.setObjectName("KurtShapeMergeParts")
        self.merge_parts.setMaximumHeight(115)
        self.end_face = QtGui.QPushButton("Use selected face")
        self.end_face.setObjectName("KurtShapeEndFace")
        self.end_face.clicked.connect(self.choose_end_face)
        self.up_to_face_reference = None
        self.formula = QtGui.QLineEdit()
        self.formula.setPlaceholderText("Example: Plate.Constraints.Width / 2")
        self.formula.installEventFilter(self)
        self.depth.lineEdit().installEventFilter(self)
        self.value.lineEdit().installEventFilter(self)
        for label, control in [("Dimension", self.parameter), ("Value", self.value),
                               ("Operation", self.result_operation), ("Merge scope", self.merge_scope),
                               ("Parts", self.merge_parts), ("End condition", self.end_type), ("End face", self.end_face),
                               ("Depth", self.depth), ("Formula", self.formula), ("", self.reverse)]:
            self.form.addRow(label, control)
        layout.addLayout(self.form)
        self.preview_hint = self.editor.verdict
        self.preview_hint.setObjectName("KurtShapeExtrusionPreviewHint")
        self.make_message_copyable(self.preview_hint)
        self.preview_hint.setWordWrap(True)
        self.apply = QtGui.QPushButton("Apply dimension")
        self.apply.clicked.connect(self.apply_parameter)
        layout.addWidget(self.apply)
        self.edit_extrusion_button = QtGui.QPushButton("Edit feature")
        self.edit_extrusion_button.setObjectName("KurtShapeEditExtrusion")
        self.edit_extrusion_button.setToolTip("Reopen this feature's settings with a preview")
        self.edit_extrusion_button.clicked.connect(lambda: self.edit_extrusion())
        layout.addWidget(self.edit_extrusion_button)
        self.clear_formula = QtGui.QPushButton("Clear formula")
        self.clear_formula.clicked.connect(lambda: self.operation("set_expression", feature=self.selected(), parameter=self.parameter.currentText(), expression=None))
        layout.addWidget(self.clear_formula)
        self.edit_button = QtGui.QPushButton("Edit sketch")
        self.edit_button.clicked.connect(self.edit_sketch)
        layout.addWidget(self.edit_button)
        self.normal_button = QtGui.QPushButton("Normal to sketch   N")
        self.normal_button.clicked.connect(self.normal)
        layout.addWidget(self.normal_button)
        self.iso_button = QtGui.QPushButton("Isometric view   Shift+7")
        self.iso_button.clicked.connect(self.isometric)
        layout.addWidget(self.iso_button)
        self.confirm = self.editor.confirm
        self.cancel = self.editor.cancel
        self.editor.accepted.connect(self.accept_task)
        self.editor.rejected.connect(self.reject_editor)
        self.register_editor_symbols(self.editor)
        self.main.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.editor)
        self.editor.hide()
        self.configure_editor(None)

    def reject_editor(self):
        if self.active_sketch() or self.sketch_plane_editor.picking:
            if not self.finish_sketch(cancel=True) and (self.active_sketch() or self.sketch_plane_editor.picking):
                self.editor.reset_lifecycle()
                self.editor.set_accept_enabled(True)
        elif self.task or self.pending_sketch:
            self.cancel_task()
        else:
            self.editor.hide()

    def register_editor_symbols(self, editor):
        editor.confirm.setIcon(icon_for("Finish"))
        editor.cancel.setIcon(icon_for("Cancel"))
        self.toolbar_labels.register(editor.confirm, "Confirm")
        self.toolbar_labels.register(editor.cancel, "Cancel")

    def register_reference_symbols(self, picker):
        for button in picker.findChildren(QtGui.QToolButton):
            self.toolbar_labels.register(button, button.accessibleName() or button.text())

    def tool_icon(self, icon, command=None, label=None):
        result = QtGui.QIcon()
        if command:
            try:
                info = Gui.Command.get(command).getInfo()
                if info.get("pixmap"):
                    result = Gui.getIcon(info["pixmap"])
            except Exception:
                pass
        if icon and result.isNull():
            result = QtGui.QIcon(icon) if str(icon).startswith(":/") else Gui.getIcon(icon)
        return icon_for(label or command or icon or "", command=command, native=result)

    def tool(self, bar, text, callback, tip="", icon=None, modeling=False, command=None):
        action = QtGui.QAction(self.tool_icon(icon, command, text), text, self)
        action.setObjectName("KurtShapeTool_" + text.replace(" ", "_"))
        action.setToolTip(tip or text)
        action.setStatusTip(tip or text)
        action.triggered.connect(lambda checked=False: callback())
        bar.addAction(action)
        if modeling:
            self.model_actions.append(action)
        if isinstance(bar, QtGui.QToolBar):
            button = bar.widgetForAction(action)
            button.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
            button.setAccessibleName(text)
            self.toolbar_labels.register(button, text, tip.split(" · ")[-1] if " · " in tip and "+" in tip.split(" · ")[-1] else "")
        return action

    def tool_menu(self, bar, label, tools, modeling=False):
        menu = QtGui.QMenu(label, self.main)
        for native in tools:
            action = QtGui.QAction(self.tool_icon(native.icon, native.command, native.label), native.label, menu)
            action.setData(native.command)
            action.setToolTip(native.tip)
            action.setStatusTip(native.tip)
            action.triggered.connect(lambda checked=False, tool=native: self.project_selected_geometry() if tool.key == "sk_projection" else self.primary_feature_tool(tool) if modeling else self.native_command(tool.command, tool.workbench))
            menu.addAction(action)
            if modeling:
                self.model_actions.append(action)
        action = menu.menuAction()
        action.setIcon(icon_for(label))
        bar.addAction(action)
        if isinstance(bar, QtGui.QToolBar):
            button = bar.widgetForAction(action)
            button.setAccessibleName(label + " tools")
            button.setToolTip(label + " tools")
            self.bind_tool_menu(button, menu)
        if modeling:
            self.model_actions.append(action)
        self.tool_menus[label] = menu
        return menu

    def bind_tool_menu(self, button, menu):
        # The default action already owns this menu. Calling setMenu with the
        # same menu action re-adds it and clears QToolButton's action binding.
        if button.defaultAction() != menu.menuAction():
            button.setDefaultAction(menu.menuAction())
        button.setPopupMode(QtGui.QToolButton.InstantPopup)
        if menu.menuAction().icon().isNull():
            menu.menuAction().setIcon(icon_for(menu.title()))
        button.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        button.setAccessibleName(menu.title())
        self.toolbar_labels.register(button, menu.title())
        menu.aboutToShow.connect(self.toolbar_labels.hide)

    def make_toolbars(self):
        self.catalog = available_catalog()
        self.catalog_model_commands = {tool.command for tool in self.catalog["all"] if tool.workbench != "SketcherWorkbench"}
        self.document_bar = QtGui.QToolBar("Document", self.main)
        self.document_bar.setObjectName("KurtShapeDocumentBar")
        self.document_bar.setMovable(False)
        self.document_bar.setIconSize(QtCore.QSize(20, 20))
        self.document_bar.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        logo = QtGui.QLabel("KurtShape")
        logo.setObjectName("KurtShapeBrand")
        self.document_bar.addWidget(logo)
        document_menu = QtGui.QMenu("Document", self.main)
        document_menu.menuAction().setIcon(icon_for("Document menu"))
        self.document_bar.addAction(document_menu.menuAction())
        self.bind_tool_menu(self.document_bar.widgetForAction(document_menu.menuAction()), document_menu)
        self.file_actions = []
        for name, callback, tip in [("New", self.new, "New part studio · Ctrl+N"),
                                    ("Open", self.open, "Open FCStd or import STEP / STP · Ctrl+O"),
                                    ("Export", self.export, "Export current solid · STEP / STL")]:
            self.file_actions.append(self.tool(document_menu, name, callback, tip))
        recent = QtGui.QMenu("Recent projects", self.main)
        recent.aboutToShow.connect(lambda: self.fill_recent(recent))
        document_menu.addMenu(recent)
        recovery_menu = QtGui.QMenu("Recovery", self.main)
        recovery_menu.aboutToShow.connect(lambda: self.fill_recovery(recovery_menu))
        document_menu.addMenu(recovery_menu)
        document_menu.addSeparator()
        self.tool(document_menu, "Adopt copy", self.adopt, "Create an editable copy of the inspected file")
        self.document_menu = document_menu
        self.document_name = DocumentLabel()
        self.document_name.setObjectName("KurtShapeDocumentIdentity")
        self.document_name.setText("New part studio")
        self.document_bar.addWidget(self.document_name)
        self.mode_choice = QtGui.QComboBox()
        self.mode_choice.setObjectName("KurtShapeWorkspaceMode")
        self.mode_choice.addItem("Part Studio", "part_studio")
        self.mode_choice.addItem("Assembly", "assembly")
        self.mode_choice.setToolTip("Return to an open Part Studio or Assembly; a new Part Studio opens if none is available")
        self.mode_choice.currentIndexChanged.connect(lambda: self.set_workspace_mode(self.mode_choice.currentData()))
        self.document_bar.addWidget(self.mode_choice)
        self.file_actions.append(self.tool(self.document_bar, "Save", self.save, "Save project · Ctrl+S"))
        help_menu = QtGui.QMenu("Help", self.main)
        self.tool(help_menu, "Shortcuts", lambda: self.router.show_help(self.main), "Keyboard shortcuts · Shift+/")
        self.tool(help_menu, "Example", lambda: self.operation("open", path=str(ROOT / "examples" / "acceptance-plate.FCStd")), "Open the development example")
        self.document_bar.addAction(help_menu.menuAction())
        self.bind_tool_menu(self.document_bar.widgetForAction(help_menu.menuAction()), help_menu)
        self.tool(self.document_bar, "Settings", lambda: self.workspace_preferences.show(), "Settings · mouse navigation")
        self.main.addToolBar(QtCore.Qt.TopToolBarArea, self.document_bar)
        self.main.addToolBarBreak(QtCore.Qt.TopToolBarArea)
        self.model_bar = QtGui.QToolBar("Part Studio", self.main)
        self.model_bar.setObjectName("KurtShapeModelBar")
        self.model_bar.setMovable(False)
        self.model_bar.setIconSize(QtCore.QSize(20, 20))
        self.model_bar.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        self.history_actions = []
        for name, op, tip in [("Undo", "undo", "Undo · Ctrl+Z"), ("Redo", "redo", "Redo · Ctrl+Y")]:
            self.history_actions.append(self.tool(self.model_bar, name, lambda kind=op: self.history_move(kind), tip))
        self.model_bar.addSeparator()
        self.tool(self.model_bar, "New part", self.new_part, "Start a separate solid part. New sketches and features belong to the selected part.", modeling=True)
        for name, callback, tip, icon in [
            ("Sketch", self.start_sketch, "Create sketch · Shift+S", "Sketcher_NewSketch"),
            ("Extrude", lambda: self.extrude(False), "Extrude sketch · Shift+E", "PartDesign_Pad"),
            ("Remove", lambda: self.extrude(True), "Remove material with a sketch", "PartDesign_Pocket")]:
            self.tool(self.model_bar, name, callback, tip, ":/icons/" + icon + ".svg", modeling=True, command=icon)
        self.model_bar.addSeparator()
        for native in self.catalog["primary"]:
            self.tool(self.model_bar, native.label, lambda tool=native: self.primary_feature_tool(tool),
                      native.tip, native.icon, modeling=True, command=native.command)
        for label, op, icon in (("Boolean parts", "boolean_parts", "PartDesign_Boolean"),
                                ("Split", "split_part", "Part_Slice"),
                                ("Transform", "transform_part", "Std_TransformManip")):
            self.tool(self.model_bar, label, lambda kind=op: self.studio_tool(kind),
                      label + " · edit parts in this studio", icon, modeling=True)
        self.model_bar.addSeparator()
        group_labels = {"Add material":"Build", "Remove material":"Cut", "Modify":"Modify", "Pattern":"Patterns", "Reference":"Reference", "Part tools":"Shape tools"}
        more = QtGui.QMenu("More", self.main)
        more.menuAction().setIcon(icon_for("More"))
        for category, tools in self.catalog["groups"]:
            self.tool_menu(more, group_labels[category], tools, modeling=True)
        self.model_bar.addAction(more.menuAction())
        self.bind_tool_menu(self.model_bar.widgetForAction(more.menuAction()), more)
        self.model_actions.append(more.menuAction())
        self.tool_menus["More"] = more
        self.model_bar.addSeparator()
        for name, callback, tip, icon in [("Rebuild", lambda: self.operation("rebuild"), "Rebuild the model", "Std_Refresh"), ("Check geometry", self.check_geometry, "Optional solid validity check · export checks automatically. Details appear in Messages.", "Part_CheckGeometry"), ("Fit", self.fit, "Fit · F", "Std_ViewFitAll"), ("Normal", self.normal, "Normal · N", "Std_ViewTop"), ("3D", self.isometric, "Isometric · Shift+7", "Std_ViewIsometric"), ("Show planes", self.toggle_planes, "Show / hide planes · P", "PartDesign_Plane")]:
            action = self.tool(self.model_bar, name, callback, tip, icon, modeling=name in {"Rebuild", "Check geometry"}, command=icon)
            if name == "Check geometry":
                action.setProperty("kurtshapeHelp", "Optional solid validity check.\nExport checks automatically.")
        self.model_bar.addWidget(SearchField(lambda: self.router.show_search(self.main)))
        self.main.addToolBar(QtCore.Qt.TopToolBarArea, self.model_bar)
        self.assembly_actions = []
        self.assembly_bar = QtGui.QToolBar("Assembly", self.main)
        self.assembly_bar.setObjectName("KurtShapeAssemblyBar")
        self.assembly_bar.setMovable(False)
        self.assembly_bar.setIconSize(QtCore.QSize(20, 20))
        self.assembly_bar.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        for action in self.history_actions:
            self.assembly_bar.addAction(action)
            self.toolbar_labels.register(self.assembly_bar.widgetForAction(action), action.text())
        self.assembly_bar.addSeparator()
        for label, callback, tip in [
            ("Create Assembly", self.create_assembly, "Create one assembly in this project"),
            ("Insert", self.insert_assembly_part, "Insert a part from FCStd or STEP / STP · I"),
            ("Ground", self.ground_assembly_instance, "Select an instance and make it the assembly reference"),
            ("Fixed", lambda: self.assembly_joint("fixed"), "Select two instance references; fasten with a fixed joint · M"),
            ("Revolute", lambda: self.assembly_joint("revolute"), "Select two axes; permit rotation around their joint axis"),
            ("Slider", lambda: self.assembly_joint("slider"), "Select two axes; permit translation along their joint axis"),
            ("Move", self.move_assembly_selection, "Select a revolute / slider joint to move its allowed coordinate, or an unjointed instance"),
            ("Edit", self.edit_assembly_selection, "Edit the selected joint or unjointed instance placement"),
            ("Solve", lambda: self.operation("solve_assembly"), "Recompute and solve the assembly")]:
            self.assembly_actions.append(self.tool(self.assembly_bar, label, callback, tip))
        self.assembly_bar.addSeparator()
        self.tool(self.assembly_bar, "Joints", self.toggle_assembly_joints, "Show or hide joints · J / H")
        self.tool(self.assembly_bar, "Fit", self.fit, "Fit · F", "Std_ViewFitAll", command="Std_ViewFitAll")
        self.tool(self.assembly_bar, "3D", self.isometric, "Isometric · Shift+7", "Std_ViewIsometric", command="Std_ViewIsometric")
        self.assembly_bar.addWidget(SearchField(lambda: self.router.show_search(self.main)))
        self.main.addToolBar(QtCore.Qt.TopToolBarArea, self.assembly_bar)
        self.assembly_bar.hide()
        self.sketch_bar = QtGui.QToolBar("Sketch", self.main)
        self.sketch_bar.setObjectName("KurtShapeSketchBar")
        self.sketch_bar.setMovable(False)
        self.sketch_bar.setIconSize(QtCore.QSize(20, 20))
        self.sketch_bar.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        for action in self.history_actions:
            self.sketch_bar.addAction(action)
            self.toolbar_labels.register(self.sketch_bar.widgetForAction(action), action.text())
        self.sketch_bar.addSeparator()
        for name, command, key in [("Line", "Sketcher_CreatePolyline", "L"), ("Rectangle", "Sketcher_CreateRectangle", "G"), ("Circle", "Sketcher_CreateCircle", "C"), ("Arc", "Sketcher_Create3PointArc", "A"), ("Spline", "Sketcher_CreateBSpline", ""), ("Point", "Sketcher_CreatePoint", "Shift+S"), ("Dimension", "Sketcher_Dimension", "D"), ("Trim", "Sketcher_Trimming", "M"), ("Construction", "Sketcher_ToggleConstruction", "Q")]:
            self.tool(self.sketch_bar, name, lambda c=command: self.native_command(c), name + (" · " + key if key else ""), ":/icons/" + command + ".svg", command=command)
        self.tool(self.sketch_bar, "Use", self.project_selected_geometry,
                  "Highlight or select an edge, then U · linked projection onto this sketch",
                  command="Sketcher_Projection")
        self.sketch_bar.addSeparator()
        for category, tools in self.catalog["sketch_groups"]:
            self.tool_menu(self.sketch_bar, category, tools)
        self.tool(self.sketch_bar, "Pierce", self.pierce, "Select a sketch point and crossing curve · Shift+G")
        self.sketch_bar.addSeparator()
        self.tool(self.sketch_bar, "Extrude", lambda: self.extrude(False), "Finish this sketch and extrude · Shift+E", "PartDesign_Pad")
        self.tool(self.sketch_bar, "Revolve", lambda: self.studio_from_sketch("revolve"), "Finish this sketch and revolve", "PartDesign_Revolution")
        self.sketch_bar.addSeparator()
        self.tool(self.sketch_bar, "Normal", self.normal, "Normal to sketch · N")
        self.tool(self.sketch_bar, "3D", self.isometric, "Sketch in 3D · Shift+7")
        finish = self.tool(self.sketch_bar, "Finish sketch", self.finish_sketch, "Commit changes", ":/icons/dialog-ok.svg")
        self.sketch_cancel_action = self.tool(self.sketch_bar, "Cancel sketch", lambda: self.finish_sketch(cancel=True), "Discard this edit session", ":/icons/dialog-cancel.svg")
        self.sketch_bar.addWidget(SearchField(lambda: self.router.show_search(self.main)))
        self.main.addToolBar(QtCore.Qt.TopToolBarArea, self.sketch_bar)
        self.sketch_bar.hide()
        for bar in (self.document_bar, self.model_bar, self.assembly_bar, self.sketch_bar):
            self.toolbar_labels.watch_toolbar(bar)
        self.message = QtGui.QLabel("Ready · Middle drag: orbit · Ctrl+middle: pan · Shift+middle: zoom")
        self.message.setObjectName("KurtShapeStatusMessage")
        self.make_message_copyable(self.message)
        self.main.statusBar().addPermanentWidget(self.message, 1)

    def make_message_copyable(self, label):
        label.setTextFormat(QtCore.Qt.PlainText)
        label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse | QtCore.Qt.TextSelectableByKeyboard)
        label.setFocusPolicy(QtCore.Qt.StrongFocus)
        label.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        label.customContextMenuRequested.connect(lambda position: self.show_message_menu(position, label))

    def show_message_menu(self, position, label=None):
        label = label or self.message
        menu = QtGui.QMenu(label)
        selected = menu.addAction("Copy selection")
        selected.setEnabled(bool(label.selectedText()))
        selected.triggered.connect(lambda: QtGui.QApplication.clipboard().setText(label.selectedText()))
        copy = menu.addAction("Copy message")
        copy.setEnabled(bool(label.text()))
        copy.triggered.connect(lambda: QtGui.QApplication.clipboard().setText(label.text()))
        menu.addSeparator()
        show = menu.addAction("Show messages")
        show.triggered.connect(lambda: self.messages_dock.show())
        menu.exec_(label.mapToGlobal(position))
        menu.deleteLater()

    def notify(self, message, *args):
        error = bool(args and args[0] == "error")
        self.status_timer.stop()
        self.message.setStyleSheet("color:" + COLORS["error"] if error else "")
        self.message.setText(str(message))
        self.message.setToolTip(str(message))
        if error and hasattr(self, "messages"):
            self.append_message(message)
        elif not error:
            self.status_timer.start()
        self.feedback_complete()

    def restore_status(self):
        """Prior command feedback gives way to the actual edit/document state."""
        generation = (self._geometry_check_generation, self._step_export_generation)
        if self._step_export_job is not None:
            text = "Exporting STEP… Escape to cancel"
        elif self._step_export_preparing_generation == self._step_export_generation:
            text = "Preparing STEP export…"
        elif self._geometry_check_job is not None:
            text = "Checking geometry… Escape to cancel"
        elif self._geometry_check_preparing_generation == self._geometry_check_generation:
            text = "Preparing geometry check…"
        elif self.studio_dialog:
            text = self.studio_dialog.windowTitle() + " · editing feature"
        elif self.active_sketch():
            text = "Editing sketch · mm"
        elif self.task in {"pad", "pocket"}:
            text = "Extrude · editing feature" if self.task == "pad" else "Remove material · editing feature"
        elif self.pending_sketch:
            text = "New sketch · select a plane or planar face"
        else:
            state = self.state or {}
            text = "Local document · mm · " + state.get("build_status", "ready").replace("_", " ")
        if generation != (self._geometry_check_generation, self._step_export_generation):
            return
        self.message.setStyleSheet("")
        self.message.setText(text)
        self.message.setToolTip(text)

    def task_feedback(self, text):
        self.status_timer.stop()
        self.message.setStyleSheet("")
        self.message.setText(text)
        self.message.setToolTip(text)

    def append_message(self, message, native=False):
        text = str(message) if native else str(message).strip()
        if not text:
            return
        if native:
            cursor = self.messages.textCursor()
            cursor.movePosition(QtGui.QTextCursor.End)
            existing = self.messages.toPlainText()
            if not self.last_message_native and existing and not existing.endswith("\n"):
                cursor.insertText("\n")
            cursor.insertText(text)
        else:
            self.messages.appendPlainText(text)
        self.last_message_native = native
        if text.strip() and not self.messages_dock.isVisible():
            self.unread_messages += 1
        self.update_messages_button()

    def update_messages_button(self, *args):
        visible = self.messages_dock.isVisible()
        if visible:
            self.unread_messages = 0
        self.messages_button.setChecked(visible)
        self.messages_button.setText("Messages" + (" •" if self.unread_messages else ""))
        self.messages_button.setToolTip("Hide messages" if visible else "Show messages" + (" · " + str(self.unread_messages) + " unread" if self.unread_messages else ""))

    def toggle_messages(self):
        self.messages_dock.setVisible(not self.messages_dock.isVisible())

    def copy_messages(self):
        text = self.messages.toPlainText()
        if text:
            QtGui.QApplication.clipboard().setText(text)

    def make_messages(self):
        self.messages_dock = QtGui.QDockWidget("Messages", self.main)
        self.messages_dock.setObjectName("KurtShapeMessages")
        container = QtGui.QWidget()
        layout = QtGui.QVBoxLayout(container)
        layout.setContentsMargins(8, 6, 8, 6)
        tools = QtGui.QHBoxLayout()
        hint = QtGui.QLabel("Select text and press Ctrl+C, or copy all messages.")
        tools.addWidget(hint, 1)
        self.copy_messages_button = QtGui.QToolButton()
        self.copy_messages_button.setObjectName("KurtShapeCopyMessagesButton")
        self.copy_messages_button.setText("Copy all")
        self.copy_messages_button.setToolTip("Copy all retained messages, including errors, to the clipboard")
        self.copy_messages_button.setEnabled(False)
        self.copy_messages_button.clicked.connect(self.copy_messages)
        tools.addWidget(self.copy_messages_button)
        layout.addLayout(tools)
        self.messages = QtGui.QPlainTextEdit()
        self.messages.setObjectName("KurtShapeMessagesText")
        self.messages.setReadOnly(True)
        self.messages.setMaximumBlockCount(200)
        self.messages.textChanged.connect(lambda: self.copy_messages_button.setEnabled(bool(self.messages.toPlainText())))
        layout.addWidget(self.messages)
        self.messages_dock.setWidget(container)
        self.main.addDockWidget(QtCore.Qt.BottomDockWidgetArea, self.messages_dock)
        self.messages_dock.hide()
        self.unread_messages = 0
        self.last_message_native = False
        self.messages_button = QtGui.QToolButton(self.main.statusBar())
        self.messages_button.setObjectName("KurtShapeMessagesButton")
        self.messages_button.setCheckable(True)
        self.messages_button.clicked.connect(self.toggle_messages)
        self.main.statusBar().addPermanentWidget(self.messages_button)
        self.messages_dock.visibilityChanged.connect(self.update_messages_button)
        self.update_messages_button()
        self.report_connections = []
        for dock in self.main.findChildren(QtGui.QDockWidget):
            if dock.objectName() == "Report view" or dock.windowTitle() == "Report view":
                for widget in dock.findChildren(QtGui.QTextEdit) + dock.findChildren(QtGui.QPlainTextEdit):
                    document = widget.document()
                    def changed(position, removed, added, d=document):
                        if added <= 0:
                            return
                        cursor = QtGui.QTextCursor(d)
                        cursor.setPosition(position)
                        cursor.setPosition(min(position + added, d.characterCount() - 1), QtGui.QTextCursor.KeepAnchor)
                        text = cursor.selectedText().replace("\u2029", "\n").replace("\u2028", "\n")
                        self.append_message(text, native=True)
                    document.contentsChange.connect(changed)
                    self.report_connections.append((document, changed))
                    # Include diagnostics emitted before the UI attached, once.
                    self.append_message(widget.toPlainText(), native=True)

    def context(self):
        if self.sketch_plane_editor.picking:
            return "sketch"
        if self.rollback_selected and not self.active_sketch() and self.workspace_mode == "part_studio":
            return ["rollback", "part_studio"]
        return "sketch" if self.active_sketch() else self.workspace_mode

    def set_workspace_mode(self, mode):
        mode = "assembly" if mode == "assembly" else "part_studio"
        if self.active_sketch() or self.native_feature_task_active():
            self.mode_choice.blockSignals(True)
            self.mode_choice.setCurrentIndex(self.mode_choice.findData(self.workspace_mode))
            self.mode_choice.blockSignals(False)
            self.notify("Finish or cancel the current edit before switching workspaces.")
            return False
        self.cancel_task()
        # Assembly copies are occurrence sources, not a destination for part
        # feature edits. Return to an independent Part Studio document instead.
        if self.state and ((mode == "part_studio" and self.assembly_state()) or (mode == "assembly" and not self.assembly_state())):
            candidates = [doc for doc in self.core.documents.values() if self.core._is_open(doc) and doc != self.document()
                          and self.core.is_managed(doc) and bool(any(obj.TypeId == "Assembly::AssemblyObject" for obj in doc.Objects)) == (mode == "assembly")]
            remembered = self.workspace_documents.get(mode)
            target = next((doc for doc in candidates if doc.Name == remembered), candidates[-1] if candidates else None)
            if target:
                self.workspace_modes[self.core.identifier(target)] = mode
                if self.general_actions._activate(target.Name):
                    return True
            elif mode == "part_studio":
                if self.operation("new", name="Untitled part"):
                    self.notify("Part Studio ready · your assembly stays open in its document tab")
                    return True
                return False
        self.workspace_mode = mode
        if self.state:
            self.workspace_modes[self.state["document_id"]] = mode
        self.mode_choice.blockSignals(True)
        self.mode_choice.setCurrentIndex(self.mode_choice.findData(mode))
        self.mode_choice.blockSignals(False)
        self.editor.hide()
        self.refresh()
        self.sync_edit_ui()
        if mode == "assembly" and not self.assembly_state():
            self.notify("Create Assembly, then insert parts from FCStd or STEP / STP files.")
        return True

    def assembly_state(self):
        return (self.state or {}).get("assembly") or {}

    def assembly_ready(self, require_assembly=True):
        if self.active_sketch() or self.native_feature_task_active():
            self.notify("Finish or cancel the current edit before an assembly command.")
            return False
        if not self.document() or not self.state:
            self.notify("Create or open a project first.", "error")
            return False
        if not self.state.get("managed", True):
            self.notify("Adopt a copy before editing this reference file.", "error")
            return False
        response = self.core.dispatch({"op": "inspect", "document_id": self.core.identifier(self.document()), "measure": self.MEASURE})
        if not response["ok"]:
            self.notify(response["error"]["message"], "error")
            return False
        self.state = response["result"]
        if require_assembly and not self.assembly_state():
            self.notify("Create Assembly before inserting parts or creating joints.", "error")
            return False
        return True

    def assembly_tokens(self):
        return {"_document_id": self.state["document_id"], "_expected_revision": self.state["revision"]}

    def create_assembly(self):
        if not self.assembly_ready(False):
            return None
        if self.assembly_state():
            self.set_workspace_mode("assembly")
            self.notify("This project already has its single-level assembly.")
            return None
        tokens = self.assembly_tokens()
        name, accepted = QtGui.QInputDialog.getText(self, "Create Assembly", "Assembly name", text="Assembly")
        if accepted and name.strip():
            # Preserve an existing modeled Part Studio as its own project.
            # The typed create operation still targets a named current document.
            if not self.document() or self.core.identifier(self.document()) != tokens["_document_id"]:
                self.notify("The source project is no longer active. Create Assembly again in the intended project.", "error")
                return None
            current = self.core.inspect(self.document(), measure=self.MEASURE)
            if current["document_id"] != tokens["_document_id"] or current["revision"] != tokens["_expected_revision"]:
                self.notify("The project changed while naming the assembly. Create Assembly again with the current project.", "error")
                return None
            modeled = any(obj.TypeId == "Sketcher::SketchObject" or (hasattr(obj, "Shape") and not obj.Shape.isNull() and bool(obj.Shape.Solids)) for obj in self.document().Objects)
            if modeled:
                if not self.operation("new", name=name.strip()):
                    return None
                tokens = self.assembly_tokens()
            result = self.operation("create_assembly", id=self.unique("Assembly"), name=name.strip(), **tokens)
            if result:
                self.set_workspace_mode("assembly")
            return result

    def insert_assembly_part(self, path=None, source_id=None):
        if not self.assembly_ready():
            return None
        tokens = self.assembly_tokens()
        if not path:
            path = QtGui.QFileDialog.getOpenFileName(self, "Insert part into assembly", self.core.settings.last_directory,
                "CAD parts (*.FCStd *.fcstd *.FCSTD *.step *.stp *.STEP *.STP);;FreeCAD project (*.FCStd *.fcstd *.FCSTD);;STEP (*.step *.stp *.STEP *.STP)")[0]
        if not path:
            return None
        response = self.core.dispatch({"op": "assembly_candidates", "path": str(path), "measure": self.MEASURE})
        if not response["ok"]:
            self.notify(response["error"]["message"], "error")
            return None
        candidates = response["result"].get("candidates", [])
        if not candidates:
            self.notify("This file has no solid part to insert. Choose an FCStd Body or a STEP file containing solids.", "error")
            return None
        if source_id is None:
            dialog = QtGui.QDialog(self.main)
            dialog.setObjectName("KurtShapeAssemblyInsertDialog")
            dialog.setWindowTitle("Insert part")
            layout = QtGui.QVBoxLayout(dialog)
            help_text = QtGui.QLabel("Choose the part to insert. Its geometry is stored in this assembly. Repeat Insert for another independent instance.")
            help_text.setWordWrap(True)
            layout.addWidget(help_text)
            layout.addWidget(QtGui.QLabel(Path(path).name))
            parts = QtGui.QListWidget()
            parts.setObjectName("KurtShapeAssemblyCandidates")
            for candidate in candidates:
                item = QtGui.QListWidgetItem(candidate.get("name", candidate["id"]) + " · " + candidate.get("type", "solid") + " · " + str(candidate.get("solid_count", 1)) + " solid(s)")
                item.setData(QtCore.Qt.UserRole, candidate["id"])
                parts.addItem(item)
            parts.setCurrentRow(0)
            layout.addWidget(parts)
            buttons = QtGui.QDialogButtonBox(QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel)
            buttons.button(QtGui.QDialogButtonBox.Ok).setText("Insert")
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            parts.itemDoubleClicked.connect(lambda *_: dialog.accept())
            layout.addWidget(buttons)
            dialog.resize(465, 275)
            if dialog.exec_() != QtGui.QDialog.Accepted:
                return None
            source_id = parts.currentItem().data(QtCore.Qt.UserRole)
        result = self.operation("insert_assembly_part", path=str(path), source_id=source_id, id=self.unique("Instance"), **tokens)
        if result:
            self.core.settings.remember(path)
            self.set_workspace_mode("assembly")
            self.fit()
            name = self.document().Name
            QtCore.QTimer.singleShot(0, lambda: self.frame_import(name))
        return result

    def assembly_references(self):
        """Resolve native root/link selection paths to visible occurrence IDs."""
        instance_ids = {entry["id"] for entry in self.assembly_state().get("instances", [])}
        references = []
        for selection in Gui.Selection.getSelectionEx():
            if selection.Object.Document != self.document():
                continue
            paths = list(selection.SubElementNames) or [""]
            for path in paths:
                segments = path.split(".")
                identifier = selection.Object.Name if selection.Object.Name in instance_ids else next((segment for segment in segments if segment in instance_ids), None)
                if identifier:
                    subelement = next((segment for segment in reversed(segments) if segment.startswith(("Face", "Edge", "Vertex"))), "")
                    reference = {"instance": identifier, "subelement": subelement}
                    if reference not in references:
                        references.append(reference)
        return references

    def assembly_selected_id(self):
        entries = self.assembly_state().get("instances", []) + self.assembly_state().get("joints", [])
        available = {entry["id"] for entry in entries}
        references = self.assembly_references()
        selected = Gui.Selection.getSelection()
        if len(selected) == 1 and selected[0].Name in available:
            return selected[0].Name
        if len(references) == 1:
            return references[0]["instance"]
        return self.selected() if self.selected() in available else None

    def ground_assembly_instance(self):
        if not self.assembly_ready():
            return None
        identifier = self.assembly_selected_id()
        if identifier not in {entry["id"] for entry in self.assembly_state().get("instances", [])}:
            self.notify("Select one instance in the viewport or instance history, then Ground.")
            return None
        return self.operation("ground_assembly_instance", instance=identifier)

    def assembly_joint(self, joint_type="fixed", joint_id=None):
        if not self.assembly_ready():
            return None
        assembly = self.assembly_state()
        instances = assembly.get("instances", [])
        if len(instances) < 2:
            self.notify("Insert at least two instances before connecting a joint.")
            return None
        tokens = self.assembly_tokens()
        joint = next((entry for entry in assembly.get("joints", []) if entry["id"] == joint_id), {})
        refs = self.assembly_references()
        if joint:
            refs = [joint.get("first") or {}, joint.get("second") or {}]
            joint_type = joint.get("joint_type", joint_type)
        dialog = QtGui.QDialog(self.main)
        dialog.setObjectName("KurtShapeAssemblyJointDialog")
        dialog.setWindowTitle("Edit joint" if joint else "Connect joint")
        layout = QtGui.QVBoxLayout(dialog)
        help_text = QtGui.QLabel("Ctrl-select a reference on each instance before opening this tool, or choose them below. Use EdgeN / FaceN / VertexN references; leave blank to use the instance origin. Revolute and slider align the reference axes. Ground one instance first. Move adjusts the allowed rotation or translation.")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        form = QtGui.QFormLayout()
        name = QtGui.QLineEdit(joint.get("name", joint_type.capitalize() + " joint"))
        name.setObjectName("KurtShapeAssemblyJointName")
        form.addRow("Name", name)
        kind = QtGui.QComboBox()
        kind.setObjectName("KurtShapeAssemblyJointType")
        for value, label in (("fixed", "Fixed"), ("revolute", "Revolute"), ("slider", "Slider")):
            kind.addItem(label, value)
        kind.setCurrentIndex(kind.findData(joint_type))
        form.addRow("Joint", kind)
        controls = []
        for index, label in enumerate(("First", "Second")):
            reference = refs[index] if len(refs) > index else {}
            choice = QtGui.QComboBox()
            choice.setObjectName("KurtShapeAssemblyJoint" + label + "Instance")
            for instance in instances:
                choice.addItem(instance["name"], instance["id"])
            choice.setCurrentIndex(max(0, choice.findData(reference.get("instance", instances[min(index, len(instances) - 1)]["id"]))))
            element = QtGui.QLineEdit(reference.get("subelement", ""))
            element.setObjectName("KurtShapeAssemblyJoint" + label + "Reference")
            element.setPlaceholderText("Instance origin, or Edge1 / Face1 / Vertex1")
            form.addRow(label + " instance", choice)
            form.addRow(label + " reference", element)
            controls.append((choice, element))
        layout.addLayout(form)
        buttons = QtGui.QDialogButtonBox(QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel)
        buttons.button(QtGui.QDialogButtonBox.Ok).setText("Apply joint" if joint else "Create joint")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.resize(485, 350)
        if dialog.exec_() != QtGui.QDialog.Accepted:
            return None
        references = [{"instance": choice.currentData(), "subelement": element.text().strip()} for choice, element in controls]
        args = {"joint_type": kind.currentData(), "first": references[0], "second": references[1], "name": name.text().strip()}
        if joint:
            args["joint"] = joint_id
        else:
            args["id"] = self.unique(kind.currentData().capitalize() + "Joint")
        result = self.operation("edit_assembly_joint" if joint else "create_assembly_joint", **args, **tokens)
        if result:
            self.select_feature(joint_id or args["id"])
        return result

    def move_assembly_selection(self):
        if not self.assembly_ready():
            return None
        identifier = self.assembly_selected_id()
        assembly = self.assembly_state()
        joint = next((entry for entry in assembly.get("joints", []) if entry["id"] == identifier), None)
        instance = next((entry for entry in assembly.get("instances", []) if entry["id"] == identifier), None)
        if not joint and not instance:
            self.notify("Select a revolute / slider joint to move its allowed coordinate, or select an unjointed instance.")
            return None
        tokens = self.assembly_tokens()
        if joint and joint.get("joint_type") == "fixed":
            self.notify("A fixed joint has no permitted motion. Select a revolute or slider joint.")
            return None
        dialog = QtGui.QDialog(self.main)
        dialog.setObjectName("KurtShapeAssemblyMoveDialog")
        dialog.setWindowTitle("Move " + (joint or instance)["name"])
        layout = QtGui.QVBoxLayout(dialog)
        form = QtGui.QFormLayout()
        fields = []
        if joint:
            unit = "deg" if joint.get("joint_type") == "revolute" else "mm"
            layout.addWidget(QtGui.QLabel("Set the joint's permitted " + ("rotation" if unit == "deg" else "translation") + "; its other constraints remain active."))
            value = QuantityField(unit)
            value.setObjectName("KurtShapeAssemblyMoveValue")
            value.setRange(-100000, 100000)
            value.setValue(joint.get("value") or 0)
            form.addRow("Angle" if unit == "deg" else "Distance", value)
            fields.append(value)
        else:
            layout.addWidget(QtGui.QLabel("Free placement applies to an ungrounded instance with no joints. Jointed parts move through their joint coordinate."))
            obj = self.document().getObject(identifier)
            values = list(obj.Placement.Base) + list(obj.Placement.Rotation.toEuler())
            for index, label in enumerate(("X", "Y", "Z", "Yaw", "Pitch", "Roll")):
                value = QuantityField("mm" if index < 3 else "deg")
                value.setObjectName("KurtShapeAssemblyMove" + label)
                value.setRange(-100000, 100000)
                value.setValue(values[index])
                form.addRow(label, value)
                fields.append(value)
        layout.addLayout(form)
        buttons = QtGui.QDialogButtonBox(QtGui.QDialogButtonBox.Ok | QtGui.QDialogButtonBox.Cancel)
        buttons.button(QtGui.QDialogButtonBox.Ok).setText("Move and solve")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec_() != QtGui.QDialog.Accepted:
            return None
        try:
            if joint:
                return self.operation("move_assembly_joint", joint=identifier, value=fields[0].value(), **tokens)
            values = [field.value() for field in fields]
            return self.operation("move_assembly_instance", instance=identifier, position_mm=values[:3], rotation_xyzw=list(App.Rotation(*values[3:]).Q), **tokens)
        except Exception as exc:
            self.notify(str(exc), "error")
            return None

    def edit_assembly_selection(self):
        if not self.assembly_ready():
            return None
        identifier = self.assembly_selected_id()
        joint = next((entry for entry in self.assembly_state().get("joints", []) if entry["id"] == identifier), None)
        return self.assembly_joint(joint.get("joint_type", "fixed"), identifier) if joint else self.move_assembly_selection()

    def toggle_assembly_joints(self):
        joints = [self.document().getObject(entry["id"]) for entry in self.assembly_state().get("joints", [])] if self.document() else []
        if not joints:
            self.notify("Create a joint first; Fixed, Revolute and Slider connect instance references.")
            return
        visible = not any(obj.ViewObject.Visibility for obj in joints if obj)
        for obj in joints:
            if obj:
                obj.ViewObject.Visibility = visible
        self.refresh()

    def document(self):
        return App.activeDocument()

    def active_body(self):
        doc = self.document()
        selected = doc.getObject(self.body_choice.currentData() or "") if doc else None
        candidates = self.sketch_owners()
        return selected if selected in candidates else candidates[0] if len(candidates) == 1 else None

    def sketch_owners(self):
        doc = self.document()
        if not doc:
            return []
        originals = [body for body in bodies(doc) if not getattr(body, "KurtShapeInternal", False)
                     and not getattr(body, "KurtShapeOutputGeneration", False)]
        studio = (self.state or {}).get("studio") or {}
        if not studio.get("enabled"):
            return originals
        current = [doc.getObject(entry["body"]) for entry in studio.get("parts", [])]
        empty_owners = [body for body in originals if body.Shape.isNull() or not body.Shape.Solids]
        return list(dict.fromkeys(body for body in current + empty_owners if body is not None))

    def plane(self, doc, plane):
        return native_plane(doc, plane, self.active_body())

    def change_body(self, *args):
        if not self.refreshing and self.state:
            body = self.active_body()
            if body and Gui.activeDocument():
                Gui.activeDocument().activeView().setActiveObject("pdbody", body)
            self.refresh()

    def maximize_document_view(self):
        if Gui.activeDocument():
            apply_view_theme(Gui.activeDocument().activeView())
        for area in self.main.findChildren(QtGui.QMdiArea):
            if area.activeSubWindow():
                area.activeSubWindow().showMaximized()

    def active_sketch(self):
        obj = Gui.activeDocument().getInEdit() if Gui.activeDocument() else None
        if obj and hasattr(obj, "Object"):
            obj = obj.Object
        return obj if obj and obj.TypeId == "Sketcher::SketchObject" else None

    def native_feature_task_active(self):
        return bool(Gui.Control.activeDialog()) and not bool(self.active_sketch())

    def tick(self):
        # Native preview evaluation may process Qt events while its hidden
        # document is active. Refresh only after it restores the live view.
        if self.core.busy or self._geometry_check_preparing or self._step_export_preparing:
            return
        geometry_document = self.document()
        if geometry_document is not self._step_export_document:
            self._step_export_document = geometry_document
            self._cancel_step_export()
        export_job = self._step_export_job
        if export_job and (not self._step_export_current(export_job)
                or self.core.snapshot_key(export_job["document"]) != export_job["bundle"]["snapshot_key"]):
            if self._step_export_job is export_job:
                self._cancel_step_export()
            else:
                self._retire_step_export(export_job)
        if geometry_document is not self._geometry_check_document:
            self._geometry_check_document = geometry_document
            self._cancel_geometry_check()
        geometry_job = self._geometry_check_job
        if geometry_job and not self._geometry_check_current(geometry_job):
            if self._geometry_check_job is geometry_job:
                self._cancel_geometry_check()
            else:
                self._retire_geometry_check(geometry_job)
        self.sketch_references.sync_context()
        native_command = self.sketch_references.native_command_for_context()
        self.sketch_snapping.sync_tool(native_command)
        self.sketch_cursor.sync(native_command)
        self.sketch_history.apply()
        self.sketch_colors.apply()
        self.sketch_regions.apply()
        self.sketch_plane_editor.apply_visibility()
        processed = False
        if not self.bridge.pending.empty():
            failures_before = self.core.last_failures.copy()
            processed = self.bridge.tick()
            if processed:
                for identifier, failure in self.core.last_failures.items():
                    request = failure.get("request", {})
                    if failure == failures_before.get(identifier) or not failure.get("rejected") or request.get("op") not in self.core.ASSEMBLY_OPS:
                        continue
                    request_id = request.get("request_id")
                    if not request_id or self.core.ledger.status(request_id)["status"] != "failed":
                        continue
                    document = self.core.documents.get(identifier)
                    label = document.Label + " · " if document and self.core._is_open(document) else ""
                    self.notify(label + failure.get("error", {}).get("message", "Assembly command failed"), "error")
        doc = self.document()
        if self.studio_dialog and (not doc or self.studio_dialog.source_document != doc.Name):
            self.studio_dialog.reject()
        elif self.studio_dialog and self.core._meta(doc).Revision != self.studio_dialog.base_revision:
            self.studio_dialog.reject()
            self.notify("Feature canceled because the project changed. Start the tool again to use the current model.")
        for identifier in list(self.core.sketch_edits):
            owner = self.core.documents.get(identifier)
            if owner and self.core._is_open(owner) and (doc is None or doc.Name != owner.Name) and not self.finishing_sketch:
                App.setActiveDocument(owner.Name)
                doc = owner
                self.notify("Finish or cancel the active sketch before switching documents.")
        if (self.task_document and (not doc or doc.Name != self.task_document)) or (self.placement_document and (not doc or doc.Name != self.placement_document)):
            self.cancel_task()
        if doc and any(self.core._is_open(d) and d.Name == doc.Name for d in self.core.documents.values()):
            if self.state is not None and not processed and not self.core.needs_refresh(doc) and self.last_document == doc.Name:
                if self.state.get("active_sketch_edit") and not self.active_sketch() and not self.finishing_sketch and not self.entering_sketch and not self.sketch_plane_editor.picking:
                    self.finish_sketch()
                return
            previous = (self.state or {}).get("revision")
            result = self.core.dispatch({"op": "inspect", "document_id": self.core.identifier(doc), "measure": self.MEASURE})
            if result["ok"]:
                self.state = result["result"]
                if previous != self.state["revision"] and self.feedback_started is not None:
                    self.feedback_kind = "model"
                if processed or previous != self.state["revision"] or self.last_document != doc.Name or self.last_status != self.state["build_status"]:
                    self.refresh()
                if self.last_document != doc.Name:
                    self.toolbar_labels.hide()
                    self.maximize_document_view()
                self.last_document, self.last_status = doc.Name, self.state["build_status"]
                self.core.observer.state(doc)["refresh"] = False
                if self.state.get("active_sketch_edit") and not self.active_sketch() and not self.finishing_sketch and not self.entering_sketch and not self.sketch_plane_editor.picking:
                    self.finish_sketch()
                self.sync_edit_ui()
        elif self.state is not None:
            self.toolbar_labels.hide()
            self.cancel_placement()
            self.state = None
            self.last_document = self.last_status = None
            self.features.clear()
            self.parts.clear()
            self.items.clear()
            self.feature_model.document = self.part_model.document = None
            self.feature_model.items.clear()
            self.part_model.items.clear()
            self.parameter.clear()
            self.status.setText("Create or open a part studio")
            self.document_name.setText("New part studio")
            self.editor.hide()
            self.sync_edit_ui()

    def operation(self, op, **args):
        with self.responsiveness.trace.command(op):
            return self._operation(op, **args)

    def _operation(self, op, **args):
        if op != "inspect":
            self._cancel_step_export()
        if op not in {"inspect", "check_geometry"}:
            self._cancel_geometry_check()
        if op in {"rename_feature", "delete_feature", "set_parameter", "set_expression", "edit_extrusion", "begin_sketch_edit",
                  "add_rectangle", "add_circle", "add_line"} and self.feature_held(args.get("feature") or args.get("sketch")):
            self.notify("Roll forward through this feature before editing it.")
            return None
        if self.studio_dialog and not self.studio_committing and op in self.core.MODEL_OPS | self.core.ASSEMBLY_OPS | self.core.CREATE_OPS | {"begin_sketch_edit", "undo", "redo", "adopt"}:
            self.studio_dialog.reject()
        staged_revision = args.pop("_expected_revision", None)
        staged_document = args.pop("_document_id", None)
        if getattr(self, "feedback_started", None) is not None:
            if op in {"save", "open", "import_step", "adopt", "recover", "export"}:
                self.feedback_kind = "disk"
            elif op in self.core.MODEL_OPS | self.core.ASSEMBLY_OPS | {"begin_sketch_edit", "finish_sketch_edit", "undo", "redo", "new"}:
                self.feedback_kind = "model"
        if op != "inspect" and self.native_feature_task_active():
            self.notify("Finish or cancel the current feature before another operation.")
            return None
        resume_preview = self.task in {"pad", "pocket"} and op in {"save", "export"}
        if op not in {"inspect", "check_geometry"}:
            editing = op == "edit_extrusion" and self.task_edit is not None
            if self.task in {"pad", "pocket"} and op != self.task and not resume_preview and not editing:
                self.cancel_task()
            else:
                self.extrusion_preview.clear()
        if op in self.core.CREATE_OPS:
            self.cancel_task()
        if op not in self.core.CREATE_OPS:
            doc = self.document()
            if not doc or not self.state:
                self.notify("Create or open a project first.", "error")
                return None
            response = self.core.dispatch({"op": "inspect", "document_id": self.core.identifier(doc), "measure": self.MEASURE})
            if not response["ok"]:
                self.notify(response["error"]["message"], "error")
                return None
            self.state = response["result"]
            if staged_document and staged_document != self.state["document_id"]:
                self.notify("Assembly command canceled because its source project is no longer active.", "error")
                return None
            args.update(document_id=self.state["document_id"], expected_revision=staged_revision or self.state["revision"])
            if op in self.core.MODEL_OPS - {"create_body", "rebuild", "delete_features", "edit_extrusion"} and "body" not in args:
                target = doc.getObject(args.get("feature") or args.get("profile") or args.get("sketch") or args.get("support", {}).get("feature") or "")
                body = owner(doc, target) or self.active_body()
                if body:
                    args["body"] = body.Name
        presentation = self.history_controller.suspend_planes() if op in {"save", "export"} else nullcontext()
        with presentation:
            response = self.core.dispatch({"op": op, **args, "measure": self.MEASURE})
        if not response["ok"]:
            if self.document() and self.state:
                self.state = self.core.inspect(self.document(), measure=self.MEASURE)
            if self.active_sketch() and self.core.identifier(self.document()) not in self.core.sketch_edits:
                Gui.activeDocument().resetEdit()
                self.sync_edit_ui()
            self.notify(response["error"]["message"], "error")
            if resume_preview:
                self.begin_preview()
            return None
        self.state = response["result"]
        if op in self.core.CREATE_OPS | {"adopt"}:
            document_owner = self.core.documents[self.state["document_id"]]
            App.setActiveDocument(document_owner.Name)
            Gui.ActiveDocument = Gui.getDocument(document_owner.Name)
            self.maximize_document_view()
        self.refresh()
        if op in self.core.CREATE_OPS | {"adopt"}:
            self.change_body()
        self.sync_edit_ui()
        if op == "create_body" and self.state.get("created_feature"):
            self.body_choice.setCurrentIndex(self.body_choice.findData(self.state["created_feature"]))
        navigation.apply_navigation()
        action_name = {"pad": "Extrude", "pocket": "Remove material", "create_body": "New part", "edit_extrusion": "Feature update"}.get(op, op.replace("_", " ").capitalize())
        self.notify(action_name + " complete")
        if op in {"open", "recover"} and self.state.get("rebuild_reason"):
            self.notify("Rebuild required · " + self.rebuild_reason_text(self.state))
        if op == "import_step":
            count = self.state["measurements"]["solid_count"] if self.state["measurements"] else 0
            self.notify(f"STEP imported · {count} solids · geometry only. Save as FCStd to keep your project.")
        if op in {"create_assembly", "insert_assembly_part", "ground_assembly_instance", "create_assembly_joint", "edit_assembly_joint", "move_assembly_joint", "move_assembly_instance", "delete_assembly_object", "solve_assembly"}:
            assembly = self.assembly_state()
            self.notify("Assembly " + str(assembly.get("solver_status", "updated")) + " · " + str(len(assembly.get("instances", []))) + " instances · " + str(len(assembly.get("joints", []))) + " joints")
        if op == "recover" and self.state.get("active_sketch_edit"):
            self.sketch_history.enter(self.document().getObject(self.state["active_sketch_edit"]))
            Gui.activeDocument().setEdit(self.state["active_sketch_edit"])
            self.sync_edit_ui()
        if resume_preview:
            self.begin_preview()
        return self.state

    @staticmethod
    def rebuild_reason_text(state):
        return {"engine_changed": "geometry engine changed",
                "saved_by_other_build": "saved by another application build",
                "engine_unrecorded": "geometry engine not recorded",
                "missing_shapes": "stored geometry is missing"}.get(state.get("rebuild_reason"), "pending model changes")

    def status_detail(self):
        status = self.state["build_status"]
        if status == "failed":
            return "Invalid geometry — see Messages" if self.state.get("geometry_check") == "invalid" else "Build failed"
        if status == "needs_rebuild":
            return "Rebuild required · " + self.rebuild_reason_text(self.state)
        measured = self.state.get("measurements")
        if not measured:
            return "Sketches only · mm"
        detail = str(measured["solid_count"]) + " solid(s)"
        if measured.get("volume_mm3") is not None:
            detail += f" · {measured['volume_mm3']:,.2f} mm³"
        if self.state.get("geometry_check") == "valid":
            detail += " · checked"
        return detail

    def check_geometry(self):
        self._cancel_step_export()
        if self._geometry_check_closed or self._geometry_check_preparing or self.core.busy:
            return None
        if self.native_feature_task_active():
            self.notify("Finish or cancel the current feature before checking geometry.")
            return None
        doc = self.document()
        if doc is None or not self.state:
            self.notify("Create or open a project first.", "error")
            return None
        generation = self._geometry_check_generation + 1
        self._cancel_geometry_check()
        if not self._geometry_check_context_current(generation, doc):
            return None
        self._geometry_check_document = doc
        self._geometry_check_preparing = True
        self._geometry_check_preparing_generation = generation
        self.task_feedback("Preparing geometry check…")
        bundle = None
        error = None
        try:
            with self.history_controller.suspend_planes():
                bundle = self.core.prepare_geometry_check(doc)
        except Exception as exc:
            error = exc
        finally:
            self._geometry_check_preparing = False
            self._geometry_check_preparing_generation = None
        if not self._geometry_check_context_current(generation, doc):
            if bundle is not None:
                bundle["worker"].close()
            self._restore_geometry_check_status(generation)
            return None
        if error is not None:
            self.notify(str(error), "error")
            return None
        if bundle is None:
            # Fully cached and unsupported capture contexts retain the
            # synchronous Controller contract and its native error reporting.
            return self._check_geometry_fallback(doc, generation)
        job = {"generation": generation, "document": doc, "bundle": bundle}
        self._geometry_check_job = job
        try:
            bundle["worker"].submit(bundle["sequence"], bundle["envelope"])
        except Exception as exc:
            current = self._geometry_check_current(job)
            self._retire_geometry_check(job)
            if current and self._geometry_check_context_current(generation, doc):
                self.notify(str(exc), "error")
            else:
                self._restore_geometry_check_status(generation)
            return None
        if not self._geometry_check_current(job):
            self._retire_geometry_check(job)
            self._restore_geometry_check_status(generation)
            return None
        self.task_feedback("Checking geometry… Escape to cancel")
        self.geometry_check_timer.start()
        return None

    def _check_geometry_fallback(self, doc, generation):
        # The generic operation wrapper publishes state and feedback itself.
        # Keep this read's publication behind the same ownership fence as a
        # child result, including a cached read that reenters native events.
        response = None
        error = None
        self.task_feedback("Checking geometry…")
        QtGui.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            request = {"op": "check_geometry", "document_id": self.core.identifier(doc), "measure": self.MEASURE}
            if self._geometry_check_context_current(generation, doc):
                response = self.core.dispatch(request)
        except Exception as exc:
            error = exc
        finally:
            QtGui.QApplication.restoreOverrideCursor()
        if not self._geometry_check_context_current(generation, doc):
            self._restore_geometry_check_status(generation)
            return None
        if error is not None or response is None or not response["ok"]:
            message = str(error) if error is not None else (response or {}).get("error", {}).get("message", "Geometry check could not complete")
            self.notify(message, "error")
            return None
        state = response["result"]
        self.state = state
        self.refresh()
        return self._present_geometry_check(state,
            is_current=lambda: self._geometry_check_context_current(generation, doc))

    def _restore_geometry_check_status(self, generation):
        if (not self._geometry_check_closed and generation == self._geometry_check_generation
                and self._geometry_check_job is None
                and self.message.text() in {"Preparing geometry check…", "Checking geometry…",
                                            "Checking geometry… Escape to cancel"}):
            self.restore_status()

    def _geometry_check_context_current(self, generation, doc):
        if self._geometry_check_closed or generation != self._geometry_check_generation:
            return False
        current = self.core._is_open(doc) and self.document() == doc
        # Native context getters may process events. Recheck ownership after
        # those reads, not just before entering them.
        return (current and not self._geometry_check_closed
                and generation == self._geometry_check_generation)

    def _geometry_check_current(self, job):
        return (self._geometry_check_job is job
                and self._geometry_check_context_current(job["generation"], job["document"])
                and self._geometry_check_job is job)

    def _retire_geometry_check(self, job):
        # Detach before teardown: a reentrant new request owns its own timer
        # and status, even if an older close/poll callback resumes afterward.
        if self._geometry_check_job is job:
            self._geometry_check_job = None
            self.geometry_check_timer.stop()
        job["bundle"]["worker"].close()

    def _cancel_geometry_check(self, notify=False):
        job = self._geometry_check_job
        pending = job is not None or self._geometry_check_preparing
        self._geometry_check_generation += 1
        generation = self._geometry_check_generation
        if job is not None:
            self._retire_geometry_check(job)
        if pending and not self._geometry_check_closed and generation == self._geometry_check_generation:
            if notify:
                self.notify("Geometry check canceled")
            else:
                self.restore_status()
        return pending

    def _poll_geometry_check(self):
        job = self._geometry_check_job
        if job is None or self._geometry_check_preparing or self.core.busy:
            return
        if not self._geometry_check_current(job):
            if self._geometry_check_job is job:
                self._cancel_geometry_check()
            else:
                self._retire_geometry_check(job)
            return
        try:
            response = job["bundle"]["worker"].poll()
            if not self._geometry_check_current(job):
                self._retire_geometry_check(job)
                self._restore_geometry_check_status(job["generation"])
                return
            if response is None:
                return
            state = self.core.accept_geometry_check(job["document"], job["bundle"], response,
                is_current=lambda: self._geometry_check_current(job),
                owns_job=lambda: not self._geometry_check_closed and self._geometry_check_job is job
                    and self._geometry_check_generation == job["generation"])
        except Exception as exc:
            current = self._geometry_check_current(job)
            self._retire_geometry_check(job)
            if current and self._geometry_check_context_current(job["generation"], job["document"]):
                self.notify(str(exc), "error")
            else:
                self._restore_geometry_check_status(job["generation"])
            return
        current = self._geometry_check_current(job)
        self._retire_geometry_check(job)
        if not current or not self._geometry_check_context_current(job["generation"], job["document"]):
            self._restore_geometry_check_status(job["generation"])
            return
        if state is None:
            self.notify("Geometry check discarded because the project changed. Check again to use the current model.")
            return
        model_current = self.core._geometry_check_current(job["document"], job["bundle"],
                                                          require_worker_open=False)
        # Context was checked above. Native model reads can reenter, so the
        # final ownership fence must be pure before assigning UI state.
        if (self._geometry_check_closed or self._geometry_check_generation != job["generation"]
                or self._geometry_check_job is not None):
            return
        if not model_current:
            self.notify("Geometry check discarded because the project changed. Check again to use the current model.")
            return
        self.state = state
        self.refresh()
        if self._geometry_check_context_current(job["generation"], job["document"]):
            model_current = self.core._geometry_check_current(job["document"], job["bundle"],
                                                              require_worker_open=False)
            owns_publication = lambda: not self._geometry_check_closed and self._geometry_check_generation == job["generation"] and self._geometry_check_job is None
            if not owns_publication():
                return
            if not model_current:
                self.notify("Geometry check discarded because the project changed. Check again to use the current model.")
                return
            self._present_geometry_check(state, is_current=owns_publication)

    def _present_geometry_check(self, state, is_current=lambda: True):
        if not state or not is_current():
            return None
        report = state.get("geometry_check_report") or {}
        names = {body["id"]: body.get("name", body["id"]) for body in state.get("bodies", [])}
        for body in report.get("bodies", []):
            if not is_current():
                return None
            name = names.get(body["id"], body["id"])
            self.append_message(name + (": geometry valid" if body["valid"] else ": invalid geometry"))
            for issue in body.get("issues", []):
                if not is_current():
                    return None
                self.append_message(name + ": " + str(issue))
        if not is_current():
            return None
        if not report.get("bodies"):
            self.notify("No solids to check yet. Sketches are checked by the sketch solver.")
        elif report.get("status") == "invalid":
            self.notify("Invalid geometry — see Messages", "error")
        else:
            self.notify("Solid geometry is valid · export also checks automatically")
        return state

    def refresh(self):
        if not self.state:
            return
        doc = self.document()
        _, selected = self.history_controller.before_refresh(doc)
        identifier = self.state["document_id"]
        if self.assembly_state():
            self.workspace_mode = self.workspace_modes[identifier] = "assembly"
        else:
            self.workspace_mode = self.workspace_modes.setdefault(identifier, "part_studio")
        if self.assembly_state() or self.workspace_mode == "part_studio":
            self.workspace_documents["assembly" if self.assembly_state() else "part_studio"] = doc.Name
        self.mode_choice.blockSignals(True)
        self.mode_choice.setCurrentIndex(self.mode_choice.findData(self.workspace_mode))
        self.mode_choice.blockSignals(False)
        if self.workspace_mode == "assembly":
            self.rollback_bar.available = False
            self.rollback_bar.hide()
            self.rollback_label.hide()
            self.refresh_assembly(selected)
            return
        studio = self.state.get("studio") or {}
        self.rollback_label.setVisible(bool(studio))
        order = studio.get("feature_order", [])
        self.rollback_bar.blockSignals(True)
        self.rollback_bar.setRange(0, len(order))
        self.rollback_bar.setValue(studio.get("rollback_index", len(order)))
        self.rollback_bar.blockSignals(False)
        self.body_choice.show()
        self.filter.setPlaceholderText("Filter features")
        self.refreshing = True
        previous_body = self.body_choice.currentData()
        self.body_choice.blockSignals(True)
        self.body_choice.clear()
        for body in self.sketch_owners():
            self.body_choice.addItem(body.Label, body.Name)
        if previous_body:
            self.body_choice.setCurrentIndex(max(0, self.body_choice.findData(previous_body)))
        self.body_choice.blockSignals(False)
        self.features.blockSignals(True)
        rows = [{"key": "origin", "text": "Origin", "data": {QtCore.Qt.UserRole: "origin"},
                 "expand_new": True, "children": []}]
        for name, plane in [("Top", "XY"), ("Front", "XZ"), ("Right", "YZ")]:
            obj = self.plane(doc, plane)
            row = {"key": "plane:" + plane, "text": name,
                   "data": {QtCore.Qt.UserRole: "plane:" + plane},
                   "tooltip": name + " (" + plane + ") · select after Shift+S to start a sketch"}
            if obj:
                row["icon"] = icon_for("Plane", native=obj.ViewObject.Icon)
            rows[0]["children"].append(row)
        features = [f for f in self.state["features"] if f["type"] not in {"PartDesign::Body", "App::Point"}]
        order_index = {identifier: index for index, identifier in enumerate(order)}
        if order:
            features = [feature for feature in features if feature["id"] in order_index]
            features.sort(key=lambda feature: order_index[feature["id"]])
        for feature in features:
            obj = doc.getObject(feature["id"])
            health = feature.get("reference_health") or []
            health = list(health.values()) if isinstance(health, dict) else health
            unhealthy = [entry for entry in health if isinstance(entry, dict) and entry.get("status", entry.get("health")) in {"missing", "ambiguous"}]
            failed = bool(unhealthy) or any(flag in feature["state"] for flag in ["Invalid", "Error"])
            held = feature["id"] in order_index and order_index[feature["id"]] >= self.rollback_bar.value()
            row = {"key": feature["id"], "text": feature["name"] + ("  !" if failed else ""),
                   "data": {QtCore.Qt.UserRole: feature["id"], ROLLED_BACK_ROLE: held}, "italic": held}
            if obj and hasattr(obj, "ViewObject"):
                row["icon"] = obj.ViewObject.Icon
            tooltip = feature["type"].split("::")[-1] + " · " + feature["id"]
            if unhealthy:
                tooltip += "\n" + "\n".join(str(entry.get("input", "Reference")) + ": " + str(entry.get("status", entry.get("health"))) + " · " + str(entry.get("message", entry.get("error", ""))) for entry in unhealthy)
            row["tooltip"] = tooltip
            if failed or held or (obj and not obj.ViewObject.Visibility):
                row["color"] = COLORS["disabled_ink"] if held else COLORS["error"] if failed else COLORS["disabled_ink"]
            rows.append(row)
        self.items = self.feature_model.reconcile((identifier, "part_studio"), rows)
        self.history_controller.restore_selection()
        self.features.blockSignals(False)
        self.refreshing = False
        self.features_title.setText(f"Features ({len(features)})")
        self.filter_features()
        self.rollback_bar.bind_history(order, self.items,
                                       {feature["id"]: feature["name"] for feature in features},
                                       studio.get("rollback_index", len(order)), available=bool(studio))
        self.rollback_label.setText(self.rollback_bar.description())
        self.parts.blockSignals(True)
        part_rows = []
        count = 0
        if studio.get("enabled"):
            for entry in studio.get("parts", []):
                body = doc.getObject(entry["body"])
                row = {"key": entry["id"], "text": entry["name"], "checked": entry.get("visible", True),
                       "data": {QtCore.Qt.UserRole: entry["id"], QtCore.Qt.UserRole + 1: entry["body"]},
                       "bold": entry["body"] == self.body_choice.currentData()}
                if body:
                    row["icon"] = icon_for("Part", native=body.ViewObject.Icon)
                row["tooltip"] = entry["id"] + (" · active part for new features" if entry["body"] == self.body_choice.currentData() else "") + " · right-click to rename, color or operate on this part"
                part_rows.append(row)
                count += 1
        for body in [] if studio.get("enabled") else native_results(doc):
            solids = body.Shape.Solids if not body.Shape.isNull() else []
            count += len(solids)
            if not solids:
                continue
            body_name, body_label = body.Name, body.Label
            body_visible = body.ViewObject.Visibility
            body_icon = icon_for("Part", native=body.ViewObject.Icon)
            body_active = body_name == self.body_choice.currentData()
            for i, solid in enumerate(solids):
                part_rows.append({"key": body_name + ":" + str(i),
                                  "text": body_label if len(solids) == 1 else f"{body_label} · solid {i + 1}",
                                  "data": {QtCore.Qt.UserRole: body_name, QtCore.Qt.UserRole + 1: body_name},
                                  "checked": body_visible, "icon": body_icon,
                                  "bold": body_active})
        self.part_model.reconcile((identifier, "part_studio"), part_rows)
        self.parts.blockSignals(False)
        self.parts_title.setText(f"Parts ({count})")
        measured = self.state["measurements"]
        detail = self.status_detail()
        if self.state.get("import_source"):
            detail = "Imported STEP · " + (detail if measured or self.state["build_status"] in {"failed", "needs_rebuild"} else "Reference geometry only · mm")
        self.status.setText(detail)
        if not self.state.get("managed", True):
            self.status.setText("Reference file · inspect or adopt a copy · " + detail)
        self.update_document_identity()
        self.main.setWindowTitle(self.state["name"] + " — KurtShape")
        if not self.task and not self.active_sketch():
            self.parameters()
        self.feedback_complete()

    def mark_active_part(self, item, body_name):
        font = item.font(0)
        font.setBold(body_name == self.body_choice.currentData())
        item.setFont(0, font)

    def update_document_identity(self):
        doc = self.document()
        state = self.state or {}
        saved = bool(doc and doc.FileName)
        modified = bool(doc and self.core._modified(doc))
        suffix = " · Unsaved" if not saved else " · Modified" if modified else ""
        self.document_name.setText(state.get("name", "New part studio") + suffix)

    def refresh_assembly(self, selected=None):
        assembly = self.assembly_state()
        doc = self.document()
        self.refreshing = True
        self.body_choice.hide()
        self.filter.setPlaceholderText("Filter instances and joints")
        self.features.blockSignals(True)
        rows = []
        for category, label in (("instances", "Instances"), ("joints", "Joints")):
            group = {"key": "assembly_group:" + category,
                     "text": label + " (" + str(len(assembly.get(category, []))) + ")",
                     "data": {QtCore.Qt.UserRole: "assembly_group:" + category},
                     "expand_new": True, "children": []}
            for entry in assembly.get(category, []):
                suffix = " · grounded" if entry.get("grounded") else (" · " + str(entry.get("joint_type", entry.get("type", "joint"))) if category == "joints" else "")
                if category == "joints" and entry.get("suppressed"):
                    suffix += " · suppressed"
                row = {"key": entry["id"], "text": entry["name"] + suffix,
                       "data": {QtCore.Qt.UserRole: entry["id"]},
                       "tooltip": entry["id"] + (" · reference fixed in place" if entry.get("grounded") else "")}
                obj = doc.getObject(entry["id"])
                if obj:
                    row["icon"] = obj.ViewObject.Icon
                group["children"].append(row)
            rows.append(group)
        identity = (self.state["document_id"], "assembly")
        self.items = self.feature_model.reconcile(identity, rows)
        self.history_controller.restore_selection()
        self.features.blockSignals(False)
        self.refreshing = False
        self.features_title.setText(assembly.get("name", "Assembly"))
        self.parts.blockSignals(True)
        part_rows = []
        for entry in assembly.get("instances", []):
            row = {"key": entry["id"],
                   "text": entry["name"] + (" · grounded" if entry.get("grounded") else ""),
                   "data": {QtCore.Qt.UserRole: entry["id"]}}
            obj = doc.getObject(entry["id"])
            if obj:
                row["icon"] = icon_for("Part", native=obj.ViewObject.Icon)
            part_rows.append(row)
        self.part_model.reconcile(identity, part_rows)
        self.parts.blockSignals(False)
        self.parts_title.setText("Instances (" + str(len(assembly.get("instances", []))) + ")")
        if not assembly:
            detail = "Create Assembly to begin. Insert saved FCStd parts, ground a reference, then connect native joints."
        elif self.state["build_status"] in {"failed", "needs_rebuild"}:
            detail = self.status_detail()
        else:
            detail = "Assembly · " + str(len(assembly.get("instances", []))) + " instances · " + str(len(assembly.get("joints", []))) + " joints · " + str(assembly.get("solver_status", "solved"))
            if assembly.get("disconnected_count"):
                detail += " · " + str(assembly["disconnected_count"]) + " unconnected"
        self.status.setText(detail)
        self.update_document_identity()
        self.main.setWindowTitle(self.state["name"] + " — KurtShape")
        self.filter_features()
        self.editor.hide()
        self.sync_edit_ui()
        self.feedback_complete()

    def filter_features(self, *args):
        text = self.filter.text().lower()
        for i in range(self.features.topLevelItemCount()):
            item = self.features.topLevelItem(i)
            if self.workspace_mode == "assembly":
                for j in range(item.childCount()):
                    child = item.child(j)
                    child.setHidden(bool(text and text not in child.text(0).lower()))
                item.setHidden(bool(text and all(item.child(j).isHidden() for j in range(item.childCount()))))
            else:
                item.setHidden(bool(text and item.data(0, QtCore.Qt.UserRole) != "origin" and text not in item.text(0).lower()))

    def selected(self):
        keys = self.history_controller.selected_ids()
        return keys[0] if len(keys) == 1 else None

    def selected_ids(self):
        return self.history_controller.feature_ids()

    def select_feature(self, key):
        if key in self.items:
            self.features.setCurrentItem(self.items[key], 0, QtCore.QItemSelectionModel.ClearAndSelect)
            self.features.scrollToItem(self.items[key])

    def history_selection(self, *args):
        if not self.refreshing:
            self.history_controller.highlight_planes()
        picking = bool(getattr(getattr(self, "sketch_plane_editor", None), "picking", False))
        if not self.refreshing and not self.pending_sketch and not self.active_sketch() and not picking:
            self.parameters(show=True)
        self.feedback_complete()

    def history_click(self, item, column=0):
        self.rollback_selected = False
        key = item.data(0, QtCore.Qt.UserRole)
        picker = getattr(self, "sketch_plane_editor", None)
        if picker and picker.history_pick(key):
            return
        if key.startswith("plane:"):
            if self.pending_sketch:
                self.begin_sketch(plane=key.split(":")[1])
                return
            obj = self.plane(self.document(), key.split(":")[1])
        else:
            obj = self.history_controller.resolve(key)
        if obj and not self.active_sketch():
            self.history_controller.sync_native_selection()
            if self.task and not self.task_profile and obj.TypeId == "Sketcher::SketchObject":
                self.task_profile = obj.Name
                self.editor_help.setText(obj.Label + " · " + ("Remove material" if self.task == "pocket" else "Extrude"))
                self.begin_preview()

    def history_double_click(self, item, column=0):
        key = item.data(0, QtCore.Qt.UserRole)
        if self.feature_held(key):
            self.notify("Roll forward through this feature before editing it.")
            return
        if self.workspace_mode == "assembly":
            return self.edit_assembly_selection()
        if key.startswith("plane:"):
            if not self.pending_sketch:
                self.start_sketch()
            if self.pending_sketch:
                self.begin_sketch(plane=key.split(":")[1])
        else:
            obj = self.document().getObject(key)
            if obj and obj.TypeId == "Sketcher::SketchObject":
                self.edit_sketch()
            elif self.editable_extrusion(key) is not None:
                self.edit_extrusion(key)
            else:
                self.parameters(show=True)

    def part_selection(self, item, column=0):
        self.rollback_selected = False
        Gui.Selection.clearSelection()
        identifier = item.data(0, QtCore.Qt.UserRole + 1) or item.data(0, QtCore.Qt.UserRole)
        obj = self.document().getObject(identifier)
        if obj:
            Gui.Selection.addSelection(obj)
            index = self.body_choice.findData(identifier)
            if index >= 0:
                QtCore.QTimer.singleShot(0, lambda: self.body_choice.setCurrentIndex(self.body_choice.findData(identifier)))

    def part_visibility_changed(self, item, column=0):
        if not self.refreshing and (self.state or {}).get("studio"):
            identifier = item.data(0, QtCore.Qt.UserRole)
            visible = item.checkState(0) == QtCore.Qt.Checked
            document_id = self.state["document_id"]
            # Native QTreeWidget still owns the emitting item until this signal
            # returns. A controller refresh must not delete it in that stack.
            QtCore.QTimer.singleShot(0, lambda: self.operation("set_part_appearance", part=identifier,
                                                            visible=visible, _document_id=document_id))

    def part_menu(self, position):
        item = self.parts.itemAt(position)
        if not item or self.workspace_mode != "part_studio":
            return
        self.parts.setCurrentItem(item)
        identifier = item.data(0, QtCore.Qt.UserRole)
        part_name, part_visible = item.text(0), item.checkState(0) == QtCore.Qt.Checked
        tokens = {"_expected_revision": self.state["revision"], "_document_id": self.state["document_id"]}
        menu = QtGui.QMenu(self)
        menu.addAction("Hide" if part_visible else "Show",
                       lambda: self.operation("set_part_appearance", part=identifier, visible=not part_visible, **tokens))
        def rename():
            name, accepted = QtGui.QInputDialog.getText(self.main, "Rename part", "Name", text=part_name)
            if accepted and name.strip():
                self.operation("set_part_appearance", part=identifier, name=name.strip(), **tokens)
        def color():
            entry = next((part for part in self.studio_parts() if part["id"] == identifier), {})
            initial = entry.get("color", [0.8, 0.8, 0.8])
            chosen = QtGui.QColorDialog.getColor(QtGui.QColor.fromRgbF(*initial), self.main, "Part color")
            if chosen.isValid():
                self.operation("set_part_appearance", part=identifier, color=[chosen.redF(), chosen.greenF(), chosen.blueF()], **tokens)
        menu.addAction("Rename", rename)
        menu.addAction("Color", color)
        menu.addSeparator()
        for label, operation in (("Split", "split_part"), ("Transform / copy", "transform_part"),
                                 ("Linear pattern", "linear_pattern_parts"), ("Circular pattern", "circular_pattern_parts"),
                                 ("Mirror", "mirror_parts")):
            menu.addAction(label, lambda checked=False, op=operation: self.studio_tool(op, part=identifier))
        menu.addAction("Delete part", lambda: self.operation("delete_part", part=identifier, **tokens))
        menu.exec_(self.parts.mapToGlobal(position))

    def commit_rollback(self):
        if not self.rollback_bar.isEnabled():
            return False
        self.rollback_selected = True
        current = (self.state or {}).get("studio") or {}
        if current.get("rollback_index") == self.rollback_bar.value():
            return True
        result = self.operation("rollback", index=self.rollback_bar.value())
        if not result:
            self.rollback_bar.setValue(current.get("rollback_index", len(current.get("feature_order", []))))
        self.rollback_bar.reveal()
        return result

    def move_rollback(self, delta):
        if not self.rollback_bar.isEnabled():
            return False
        self.rollback_selected = True
        current = (self.state or {}).get("studio") or {}
        index = max(0, min(len(current.get("feature_order", [])), current.get("rollback_index", 0) + delta))
        result = self.operation("rollback", index=index)
        self.rollback_bar.reveal()
        return result

    def feature_held(self, identifier):
        studio = (self.state or {}).get("studio") or {}
        order = studio.get("feature_order", [])
        return identifier in order and order.index(identifier) >= studio.get("rollback_index", len(order))

    def studio_parts(self):
        studio = (self.state or {}).get("studio") or {}
        if studio.get("enabled"):
            return studio.get("parts", [])
        doc = self.document()
        return [{"id": body.Name, "name": body.Label, "body": body.Name,
                 "feature": body.Tip.Name if body.Tip else None,
                 "visible": body.ViewObject.Visibility, "color": list(body.ViewObject.ShapeColor)}
                for body in bodies(doc) if not body.Shape.isNull() and body.Shape.Solids] if doc else []

    def fill_merge_parts(self, widget, selected=()):
        widget.blockSignals(True)
        widget.clear()
        for entry in self.studio_parts():
            item = QtGui.QListWidgetItem(entry["name"])
            item.setData(QtCore.Qt.UserRole, entry["id"])
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked if entry["id"] in selected else QtCore.Qt.Unchecked)
            widget.addItem(item)
        widget.blockSignals(False)

    @staticmethod
    def checked_parts(widget):
        return [widget.item(index).data(QtCore.Qt.UserRole) for index in range(widget.count())
                if widget.item(index).checkState() == QtCore.Qt.Checked]

    def scope_value(self, choice, parts):
        return "auto" if choice.currentData() == "auto" else self.checked_parts(parts)

    def result_operation_changed(self, *args):
        if self.task in {"pad", "pocket"}:
            self.studio_operation_explicit = True
            if isinstance(self.task_profile, dict):
                self.reverse.setChecked(self.result_operation.currentData() == "remove")
            self.configure_editor("extrude")
            self.schedule_preview()

    def choose_end_face(self):
        references = self.geometry_references("Face")
        if len(references) != 1:
            self.notify("Select one end face in the viewport.", "error")
            return
        self.up_to_face_reference = references[0]
        self.end_face.setText("Selected face · query retained")
        self.schedule_preview()

    def primary_feature_tool(self, tool):
        if tool.key in {"pad", "pocket"}:
            return self.extrude(tool.key == "pocket")
        operations = {"revolve": "revolve", "sweep": "sweep", "loft": "loft",
                      "linear_pattern": "linear_pattern_parts", "circular_pattern": "circular_pattern_parts",
                      "mirror": "mirror_parts", "fillet": "fillet", "chamfer": "chamfer", "shell": "shell",
                      "boolean": "boolean_parts", "datum_plane": "create_plane", "move_face": "move_face"}
        operation = operations.get(tool.key)
        return self.studio_tool(operation) if operation else self.native_command(tool.command, tool.workbench)

    def studio_from_sketch(self, operation):
        sketch = self.active_sketch()
        if sketch:
            identifier = sketch.Name
            if not self.finish_sketch():
                return False
            self.select_feature(identifier)
        return self.studio_tool(operation)

    def studio_selection(self):
        selected = {obj.Name for obj in Gui.Selection.getSelection()}
        return [entry["id"] for entry in self.studio_parts() if entry["body"] in selected or entry["feature"] in selected]

    def geometry_references(self, entity):
        references = []
        for selection in Gui.Selection.getSelectionEx():
            obj = selection.Object
            body = owner(self.document(), obj)
            feature = body.Tip if body and obj == body else obj
            for element in selection.SubElementNames:
                if element.startswith(entity) and feature:
                    references.append(self.reference_from_geometry(feature, element, entity))
        return references

    def reference_from_geometry(self, feature, element, entity):
        body = owner(self.document(), feature)
        if body and feature == body:
            feature = body.Tip
        reference = {"feature": feature.Name, "subelement": element}
        try:
            shape = feature.Shape.getElement(element)
            part = next((entry for entry in self.studio_parts() if entry["body"] == body.Name), None) if body else None
            if part or feature.TypeId == "Sketcher::SketchObject":
                query = ({"kind": "created_by", "feature": feature.Name, "entity_type": entity.lower()}
                         if feature.TypeId == "Sketcher::SketchObject" else
                         {"kind": "owned_by", "part": part["id"], "entity_type": entity.lower()})
                shape_geometry = getattr(shape, "Surface", None) if entity == "Face" else getattr(shape, "Curve", None)
                kind = type(shape_geometry).__name__.lower()
                kind = {"planesurface": "plane", "cylindricalsurface": "cylinder", "linesegment": "line"}.get(kind, kind)
                if kind in {"plane", "cylinder", "line", "circle", "sphere", "cone"}:
                    query = {"kind": "geometry", "geometry": kind, "query": query}
                world = feature.getGlobalPlacement() * feature.Placement.inverse()
                reference = {"kind": "closest", "point": list(world.multVec(App.Vector(*geometry.scalar(shape, "center_of_mass")))), "query": query}
        except Exception:
            pass
        return reference

    def project_selected_geometry(self):
        return self.sketch_references.use()

    def capture_feature_selection(self):
        if self.core.busy:
            return
        if self.studio_selection_callback:
            self.studio_selection_callback()
        elif self.task in {"pad", "pocket"} and not self.task_profile:
            references = self.geometry_references("Face")
            if len(references) == 1:
                self.task_profile = references[0]
                self.end_type.setCurrentIndex(0)
                self.end_type.model().item(1).setEnabled(False)
                self.end_type.model().item(2).setEnabled(False)
                self.depth.setEnabled(True)
                self.reverse.setChecked(self.result_operation.currentData() == "remove")
                self.editor_help.setText("Selected face · " + ("Remove material" if self.task == "pocket" else "Extrude"))
                self.begin_preview()

    def studio_tool(self, operation, part=None):
        """Stage shared typed operations in a revision-bound native dialog."""
        if not self.document() or self.workspace_mode != "part_studio":
            self.notify("Create or open a Part Studio first.")
            return None
        if self.active_sketch() or self.native_feature_task_active():
            self.notify("Finish or cancel the current edit before starting this tool.")
            return None
        if not self.state.get("managed", True):
            self.notify("Adopt a copy before editing this reference file.", "error")
            return None
        self.cancel_task()
        doc = self.document()
        self.state = self.core.inspect(doc, measure=self.MEASURE)
        tokens = {"_expected_revision": self.state["revision"], "_document_id": self.state["document_id"]}
        parts = self.studio_parts()
        selected_parts = [part] if part else self.studio_selection()
        labels = {"revolve": "Revolve", "sweep": "Sweep", "loft": "Loft", "boolean_parts": "Boolean parts",
                  "split_part": "Split part", "transform_part": "Transform / copy part",
                  "linear_pattern_parts": "Linear part pattern", "circular_pattern_parts": "Circular part pattern",
                  "mirror_parts": "Mirror parts", "fillet": "Fillet", "chamfer": "Chamfer", "shell": "Shell",
                  "create_plane": "Plane", "move_face": "Move face"}
        label = labels.get(operation, operation.replace("_", " ").capitalize())
        dialog = FeaturePanel(label, self.main)
        dialog.setObjectName("KurtShapeStudio_" + operation)
        dialog.setWindowTitle(label)
        layout = QtGui.QVBoxLayout(dialog.content)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        introduction = QtGui.QLabel("Select geometry in the viewport or feature history, then Confirm.")
        introduction.setWordWrap(True)
        layout.addWidget(introduction)
        form = QtGui.QFormLayout()
        form.setRowWrapPolicy(QtGui.QFormLayout.WrapLongRows)
        fields = {}
        values = {}
        pickers = {}
        active_picker = [None]
        def field(key, caption, widget, getter):
            widget.setObjectName("KurtShapeStudio_" + key)
            fields[key] = widget
            values[key] = getter
            form.addRow(caption, widget)
            return widget
        def choice(key, caption, entries, initial=None):
            widget = QtGui.QComboBox()
            for name, identifier in entries:
                widget.addItem(name, identifier)
            if initial is not None:
                widget.setCurrentIndex(max(0, widget.findData(initial)))
            return field(key, caption, widget, widget.currentData)
        def quantity(key, caption, value, unit="mm"):
            widget = QuantityField(unit)
            widget.setRange(-100000, 100000)
            widget.setDecimals(4)
            widget.setValue(value)
            return field(key, caption, widget, lambda: widget.lineEdit().text())
        def vector(key, caption, value, unit=None):
            widget = QtGui.QWidget()
            row = QtGui.QHBoxLayout(widget)
            row.setContentsMargins(0, 0, 0, 0)
            controls = []
            for axis, initial in zip(("X", "Y", "Z"), value):
                number = QuantityField(unit) if unit else QtGui.QDoubleSpinBox()
                number.setObjectName("KurtShapeStudio_" + key + axis)
                number.setRange(-100000, 100000)
                number.setDecimals(4)
                number.setValue(initial)
                row.addWidget(number)
                controls.append(number)
            return field(key, caption, widget, lambda: [number.value() for number in controls])
        def checklist(key, caption, entries, initial=()):
            widget = QtGui.QListWidget()
            widget.setMaximumHeight(115)
            for name, identifier in entries:
                item = QtGui.QListWidgetItem(name)
                item.setData(QtCore.Qt.UserRole, identifier)
                item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
                item.setCheckState(QtCore.Qt.Checked if identifier in initial else QtCore.Qt.Unchecked)
                widget.addItem(item)
            return field(key, caption, widget, lambda: self.checked_parts(widget))
        def reference_field(key, caption, entity, multiple=False):
            widget = ReferencePicker("Select " + caption.lower(), multiple)
            pickers[key] = (widget, entity)
            def activate():
                active_picker[0] = key
                for identifier, (picker, _) in pickers.items():
                    picker.pick.setChecked(identifier == key)
            widget.activated.connect(activate)
            activate()
            return field(key, caption, widget, widget.value)
        part_entries = [(entry["name"], entry["id"]) for entry in parts]
        sketch_entries = [(obj.Label, obj.Name) for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"]
        current = self.selected()
        creation = operation in {"revolve", "sweep", "loft"}
        scoped = creation or operation in {"linear_pattern_parts", "circular_pattern_parts", "mirror_parts"}
        if creation:
            if operation == "loft":
                sections = checklist("sections", "Sections · drag to order", sketch_entries, [obj.Name for obj in Gui.Selection.getSelection() if obj.TypeId == "Sketcher::SketchObject"])
                sections.setDragDropMode(QtGui.QAbstractItemView.InternalMove)
                sections.setDefaultDropAction(QtCore.Qt.MoveAction)
            else:
                choice("profile", "Profile", sketch_entries, current)
        if scoped:
            choice("operation", "Operation", [("New", "new"), ("Add", "add"), ("Remove", "remove"), ("Intersect", "intersect")], "new" if not creation or not parts else "add")
            choice("merge_scope", "Merge scope", [("Auto · touching parts", "auto"), ("Selected parts", "explicit")], "auto")
            checklist("scope_parts", "Parts", part_entries, selected_parts)
        if operation == "revolve":
            choice("axis_by", "Axis", [("Selected line", "selected"), ("Custom axis", "custom")], "selected")
            reference_field("axis_reference", "Axis line", "Edge")
            vector("axis_origin", "Axis origin", [0, 0, 0], "mm")
            vector("axis_direction", "Axis direction", [0, 1, 0])
            quantity("angle", "Angle", 360, "deg")
        elif operation == "sweep":
            path_references = self.geometry_references("Edge")
            choice("path_by", "Path source", [("Curve feature", "feature"), ("Selected edge", "selected")], "selected" if len(path_references) == 1 else "feature")
            entries = [(obj.Label, obj.Name) for obj in doc.Objects if hasattr(obj, "Shape") and obj.Shape.Edges]
            choice("path", "Path", entries)
            values["selected_path"] = lambda: path_references[0] if len(path_references) == 1 else None
            selected_hint = QtGui.QLabel("Selected edge · query retained" if len(path_references) == 1 else "Select one path edge in the viewport before opening Sweep.")
            selected_hint.setWordWrap(True)
            form.addRow("Selected path", selected_hint)
            fields["path_hint"] = selected_hint
        elif operation == "boolean_parts":
            checklist("targets", "Target parts", part_entries, selected_parts[:1])
            checklist("tools", "Tool parts", part_entries, selected_parts[1:])
            choice("kind", "Operation", [("Union", "union"), ("Subtract", "subtract"), ("Intersect", "intersect")], "union")
            widget = QtGui.QCheckBox("Keep tool parts")
            field("keep_tools", "", widget, widget.isChecked)
        elif operation == "split_part":
            choice("part", "Part", part_entries, (selected_parts or [None])[0])
            choice("split_by", "Split by", [("Plane", "plane"), ("Selected face", "face"), ("Sketch plane", "sketch")], "plane")
            vector("origin", "Plane origin", [0, 0, 0], "mm")
            vector("normal", "Plane normal", [1, 0, 0])
            choice("sketch", "Sketch", sketch_entries, current)
            refs = self.geometry_references("Face")
            values["face"] = lambda: refs[0] if refs else None
        elif operation == "transform_part":
            choice("part", "Part", part_entries, (selected_parts or [None])[0])
            choice("transform_by", "Transform by", [("Translation / rotation", "placement"), ("Coordinate system", "coordinate_system")], "placement")
            vector("translation", "Translation", [0, 0, 0], "mm")
            vector("rotation_axis", "Rotation axis", [0, 0, 1])
            quantity("rotation_angle", "Rotation", 0, "deg")
            vector("coordinate_origin", "Target origin", [0, 0, 0], "mm")
            vector("coordinate_x", "Target X", [1, 0, 0])
            vector("coordinate_y", "Target Y", [0, 1, 0])
            vector("coordinate_z", "Target Z", [0, 0, 1])
            widget = QtGui.QCheckBox("Create a copy")
            field("copy", "", widget, widget.isChecked)
        elif operation in {"linear_pattern_parts", "circular_pattern_parts", "mirror_parts"}:
            checklist("parts", "Parts", part_entries, selected_parts)
            if operation == "linear_pattern_parts":
                vector("direction", "Direction", [1, 0, 0])
                quantity("spacing", "Spacing", 20)
            else:
                if operation == "mirror_parts":
                    reference_field("plane", "Mirror plane", "Plane")
                vector("origin", "Origin", [0, 0, 0], "mm")
                vector("normal" if operation == "mirror_parts" else "axis_direction",
                       "Plane normal" if operation == "mirror_parts" else "Axis direction", [1, 0, 0] if operation == "mirror_parts" else [0, 0, 1])
            if operation != "mirror_parts":
                count = QtGui.QSpinBox()
                count.setRange(2, 100)
                count.setValue(3)
                field("count", "Count · including source", count, count.value)
            if operation == "circular_pattern_parts":
                quantity("angle", "Angle", 360, "deg")
        elif operation == "create_plane":
            values["body"] = lambda: active_plane_body
            active_plane_body = self.active_body().Name
            choice("base_plane", "Base plane", [("Top", "XY"), ("Front", "XZ"), ("Right", "YZ"), ("Selected plane / face", "selected")], "selected" if self.geometry_references("Face") else "XY")
            reference_field("support", "Plane or planar face", "Plane")
            quantity("offset", "Offset", 10)
        elif operation in {"fillet", "chamfer", "shell", "move_face"}:
            choice("part", "Part", part_entries, (selected_parts or [None])[0])
            faces = operation in {"shell", "move_face"}
            reference_field("faces" if faces else "edges", "Faces" if faces else "Edges", "Face" if faces else "Edge", True)
            quantity("distance" if operation == "move_face" else "thickness" if operation == "shell" else ("size" if operation == "chamfer" else "radius"),
                     "Offset distance" if operation == "move_face" else "Thickness" if operation == "shell" else ("Size" if operation == "chamfer" else "Radius"), 1)
            if operation == "move_face":
                introduction.setText("Select planar faces to offset. Positive distance adds material; negative distance removes it.")
            if operation == "shell":
                widget = QtGui.QCheckBox("Reverse wall direction")
                field("reversed", "", widget, widget.isChecked)
        layout.addLayout(form)
        hint = dialog.verdict
        dialog.set_status("Updating preview…")
        self.make_message_copyable(hint)
        hint.setWordWrap(True)
        hint.setObjectName("KurtShapeStudioPreviewHint")
        dialog.set_accept_enabled(False)
        self.register_editor_symbols(dialog)
        def proposal():
            result = {key: getter() for key, getter in values.items()}
            if scoped:
                result["merge_scope"] = "auto" if result["merge_scope"] == "auto" else result.pop("scope_parts")
                result.pop("scope_parts", None)
            if operation in {"revolve", "circular_pattern_parts"}:
                origin = result.pop("axis_origin", result.pop("origin", [0, 0, 0]))
                direction = result.pop("axis_direction")
                if operation == "revolve":
                    selected_axis = result.pop("axis_by") == "selected"
                    reference = result.pop("axis_reference")
                    result["axis"] = reference if selected_axis else {"origin": origin, "direction": direction}
                else:
                    result["axis"] = {"origin": origin, "direction": direction}
            if operation == "mirror_parts":
                result.pop("origin")
                result.pop("normal")
            if operation == "create_plane":
                if result["base_plane"] == "selected":
                    result.pop("base_plane")
                else:
                    result.pop("support")
            if operation == "sweep":
                path_by, selected_path = result.pop("path_by"), result.pop("selected_path")
                if path_by == "selected":
                    result["path"] = selected_path
            if operation == "split_part":
                kind = result.pop("split_by")
                origin, normal = result.pop("origin"), result.pop("normal")
                face, sketch = result.pop("face"), result.pop("sketch")
                if kind == "plane":
                    result["plane"] = {"origin": origin, "normal": normal}
                elif kind == "face":
                    result["face"] = face
                else:
                    result["sketch"] = sketch
            if operation == "transform_part":
                method = result.pop("transform_by")
                rotation = {"axis": result.pop("rotation_axis"), "angle": result.pop("rotation_angle")}
                coordinates = {"origin": result.pop("coordinate_origin"), "x": result.pop("coordinate_x"),
                               "y": result.pop("coordinate_y"), "z": result.pop("coordinate_z")}
                if method == "coordinate_system":
                    result.pop("translation")
                    result["coordinate_system"] = coordinates
                else:
                    result["rotation"] = rotation
            return dict(result, op=operation)
        def status(result):
            valid = bool(result and result.valid)
            provisional = bool(result and result.provisional)
            dialog.set_accept_enabled(valid)
            text = ("Preview · valid current parts" if valid else "Provisional preview · checking exact result…" if provisional
                    else result.error["message"] if result else "Updating preview…")
            if result and not valid and not provisional and operation in {"fillet", "chamfer"} and not fields["edges"].value():
                text = "Select one or more edges in the model."
            dialog.set_status(text,
                              "success" if valid else "error" if result and not provisional else "")
            entry = getattr(dialog, "preview_trace", None)
            if result:
                self.responsiveness.trace.mark(entry, "preview_provisional" if provisional else "preview_ready")
            self.responsiveness.ui_updated(entry)
        # QDialog hides before exec_ returns. Keep the staged task alive for
        # its final guarded evaluation and clear it immediately after commit.
        adapter = DebouncedExtrusionPreview(self.core, dialog, status=status,
                                            allowed=lambda: self.studio_dialog is dialog)
        def schedule(*args):
            try:
                def visible(key, state):
                    if key in fields:
                        fields[key].setVisible(state)
                        caption = form.labelForField(fields[key])
                        if caption:
                            caption.setVisible(state)
                if scoped:
                    merging = fields["operation"].currentData() != "new"
                    visible("merge_scope", merging)
                    visible("scope_parts", merging and fields["merge_scope"].currentData() == "explicit")
                if operation == "split_part":
                    kind = fields["split_by"].currentData()
                    visible("origin", kind == "plane")
                    visible("normal", kind == "plane")
                    visible("sketch", kind == "sketch")
                if operation == "sweep":
                    selected_path = fields["path_by"].currentData() == "selected"
                    visible("path", not selected_path)
                    visible("path_hint", selected_path)
                if operation == "revolve":
                    selected_axis = fields["axis_by"].currentData() == "selected"
                    visible("axis_reference", selected_axis)
                    visible("axis_origin", not selected_axis)
                    visible("axis_direction", not selected_axis)
                if operation == "mirror_parts":
                    visible("origin", False)
                    visible("normal", False)
                if operation == "create_plane":
                    visible("support", fields["base_plane"].currentData() == "selected")
                if operation == "transform_part":
                    coordinates = fields["transform_by"].currentData() == "coordinate_system"
                    for key in ("translation", "rotation_axis", "rotation_angle"):
                        visible(key, not coordinates)
                    for key in ("coordinate_origin", "coordinate_x", "coordinate_y", "coordinate_z"):
                        visible(key, coordinates)
                if adapter.evaluator:
                    dialog.preview_trace = self.responsiveness.trace.current
                    adapter.schedule(proposal())
                    if adapter.result is None:
                        status(None)
            except Exception as exc:
                adapter.overlay.clear()
                dialog.set_accept_enabled(False)
                dialog.set_status(str(exc), "error")
        for widget in fields.values():
            if isinstance(widget, ReferencePicker):
                widget.changed.connect(schedule)
                self.register_reference_symbols(widget)
                widget.changed.connect(lambda picker=widget: self.register_reference_symbols(picker))
            for control in [widget] + widget.findChildren(QtGui.QWidget):
                if isinstance(control, QtGui.QComboBox):
                    control.currentIndexChanged.connect(schedule)
                elif isinstance(control, QtGui.QListWidget):
                    control.itemChanged.connect(schedule)
                    control.model().rowsMoved.connect(schedule)
                elif isinstance(control, QtGui.QAbstractSpinBox):
                    control.lineEdit().textChanged.connect(schedule)
                    if isinstance(control, (QtGui.QSpinBox, QtGui.QDoubleSpinBox)):
                        # Native Qt stepping/setValue can suppress line-edit
                        # signals while changing the value read by proposal().
                        control.valueChanged.connect(schedule)
                elif isinstance(control, QtGui.QCheckBox):
                    control.toggled.connect(schedule)
        self.studio_dialog = dialog
        self.task_feedback(label + " · editing feature")
        dialog.source_document = doc.Name
        dialog.base_revision = tokens["_expected_revision"]
        dialog.fields = fields
        dialog.preview = adapter
        def capture():
            if self.studio_dialog is not dialog or self.document() is not doc:
                return
            key = active_picker[0]
            picker_entry = pickers.get(key)
            for selection in Gui.Selection.getSelectionEx():
                obj = selection.Object
                if obj.Document is not doc:
                    continue
                body = owner(doc, obj)
                part_id = next((entry["id"] for entry in parts if body and entry["body"] == body.Name), None)
                if part_id and "part" in fields:
                    fields["part"].setCurrentIndex(fields["part"].findData(part_id))
                if not picker_entry:
                    continue
                picker, entity = picker_entry
                feature = body.Tip if body and obj == body else obj
                if entity == "Plane" and obj.TypeId in {"App::Plane", "PartDesign::Plane"}:
                    picker.add({"feature": obj.Name}, obj.Label, (obj, ""))
                else:
                    prefix = "Face" if entity == "Plane" else entity
                    for element in selection.SubElementNames:
                        if element.startswith(prefix) and feature:
                            reference = ({"feature": feature.Name, "subelement": element} if entity == "Plane" or key == "axis_reference" and feature.TypeId == "Sketcher::SketchObject" else
                                         self.reference_from_geometry(feature, element, entity))
                            picker.add(reference, feature.Label + " · " + element, (obj, element))
                            if key == "axis_reference" and obj.TypeId == "Sketcher::SketchObject":
                                fields["profile"].setCurrentIndex(fields["profile"].findData(obj.Name))
        self.studio_selection_callback = capture
        def cleanup():
            if dialog.finished:
                return
            dialog.finished = True
            adapter.close()
            if self.studio_dialog is dialog:
                self.studio_dialog = None
                self.studio_selection_callback = None
            self.main.removeDockWidget(dialog)
            dialog.hide()
            dialog.deleteLater()
        def commit():
            if self.document() is not doc:
                cleanup()
                self.notify("Feature canceled because its source document is no longer active.")
                return
            adapter.schedule(proposal())
            evaluated = adapter.flush()
            if not evaluated or not evaluated.valid:
                return
            request = dict(evaluated.proposal)
            request.pop("op")
            request["id"] = self.unique(label.split()[0].replace("/", "") or "Feature")
            self.studio_committing = True
            try:
                result = self.operation(operation, **request, **tokens)
            finally:
                self.studio_committing = False
            if result:
                cleanup()
                self.complete_editor(result.get("created_feature", request["id"]))
        dialog.accepted.connect(commit)
        dialog.rejected.connect(cleanup)
        def begin():
            adapter.begin(doc, tokens["_expected_revision"])
            capture()
            schedule()
        self.editor.hide()
        self.main.addDockWidget(QtCore.Qt.RightDockWidgetArea, dialog)
        dialog.show_compact()
        QtCore.QTimer.singleShot(0, begin)
        return dialog

    def parameters(self, *args, show=False):
        if self.sketch_plane_editor.picking:
            return
        if not show and (not self.editor.isVisible() or self.editor_mode != "parameters"):
            return
        if self.workspace_mode == "assembly":
            self.editor.hide()
            return
        feature = next((f for f in (self.state or {}).get("features", []) if f["id"] == self.selected()), None)
        if feature and self.feature_held(feature["id"]):
            self.editor.hide()
            return
        if not feature or self.task or self.active_sketch() or self.studio_dialog:
            if not self.task and not self.active_sketch():
                self.editor.hide()
            return
        previous = self.parameter.currentText()
        self.parameter.blockSignals(True)
        self.parameter.clear()
        self.parameter.addItems(list(feature["parameters"]))
        index = self.parameter.findText(previous)
        if index >= 0:
            self.parameter.setCurrentIndex(index)
        self.parameter.blockSignals(False)
        self.editor_title.setText(feature["name"])
        kind = feature["type"].split("::")[-1]
        label = {"Pad": "Extrude", "Pocket": "Remove material", "Revolution": "Revolve",
                 "Groove": "Revolve remove", "AdditivePipe": "Sweep", "SubtractivePipe": "Sweep remove",
                 "AdditiveLoft": "Loft", "SubtractiveLoft": "Loft remove", "Thickness": "Shell",
                 "PolarPattern": "Circular pattern", "LinearPattern": "Linear pattern", "Plane": "Plane"}.get(kind, kind)
        obj = self.document().getObject(feature["id"])
        if obj and getattr(obj, "KurtShapeStudioOperation", ""):
            intent = json.loads(obj.KurtShapeStudioOperation)
            label = {"pad": "Extrude", "pocket": "Remove material", "revolve": "Revolve",
                     "sweep": "Sweep", "loft": "Loft", "split_part": "Split part", "transform_part": "Transform / copy part",
                     "linear_pattern_parts": "Linear part pattern", "circular_pattern_parts": "Circular part pattern",
                     "mirror_parts": "Mirror parts", "boolean_parts": "Boolean parts", "delete_part": "Delete part"}.get(intent["op"], label)
        self.editor_help.setText(label)
        self.configure_editor("parameters", feature["type"] == "Sketcher::SketchObject")
        self.parameter_value()
        if feature["parameters"] or show:
            if not self.editor.isVisible():
                self.editor.show_compact()

    def configure_editor(self, mode, sketch=False):
        self.editor_mode = mode
        self.editor.compact_minimum_height = 104 if mode in {"sketch", "placement"} else 180
        self.editor_help.setVisible(mode not in {"sketch", "placement"})
        self.sketch_plane_editor.widget.setVisible(mode in {"sketch", "placement"})
        if mode in {"sketch", "placement"}:
            self.sketch_plane_editor.refresh()
        self.preview_hint.setVisible(mode == "extrude")
        if mode != "extrude" and hasattr(self, "extrusion_preview"):
            self.extrusion_preview.clear()
        for control in [self.parameter, self.value, self.formula, self.depth, self.end_type, self.end_face, self.reverse,
                        self.result_operation, self.merge_scope, self.merge_parts]:
            visible = (mode == "parameters" and control in [self.parameter, self.value, self.formula]) or (mode == "extrude" and control in [self.depth, self.end_type, self.end_face, self.reverse, self.result_operation, self.merge_scope, self.merge_parts])
            if mode == "extrude" and self.task_edit is not None:
                # Existing features keep their operation and scope; only
                # their native dimension, formula, direction and end change.
                visible = control in [self.depth, self.formula, self.end_type, self.end_face, self.reverse, self.result_operation]
            if mode == "parameters" and not self.parameter.count():
                visible = False
            if control in [self.merge_scope, self.merge_parts] and self.result_operation.currentData() == "new":
                visible = False
            if control == self.merge_parts and self.merge_scope.currentData() != "explicit":
                visible = False
            if control == self.end_face and self.end_type.currentIndex() != 2:
                visible = False
            control.setVisible(visible)
            label = self.form.labelForField(control)
            if label:
                label.setVisible(visible)
        self.apply.setVisible(mode == "parameters" and self.parameter.count() > 0)
        self.clear_formula.setVisible(mode == "parameters" and self.parameter.count() > 0)
        self.edit_button.setVisible(mode == "parameters" and sketch)
        self.edit_extrusion_button.setVisible(mode == "parameters" and self.editable_extrusion(self.selected()) is not None)
        self.normal_button.setVisible(mode == "parameters" and sketch)
        self.iso_button.hide()
        self.confirm.setVisible(mode in {"sketch", "extrude"})
        self.editor.set_accept_enabled(mode == "sketch" and not self.sketch_plane_editor.picking)
        self.confirm.setText("Finish sketch" if mode == "sketch" else "Confirm")
        self.confirm.setAccessibleName(self.confirm.text())
        self.toolbar_labels.register(self.confirm, self.confirm.text())

    def complete_editor(self, feature=None):
        """Accepting a feature returns to the canvas without opening properties."""
        self.configure_editor(None)
        self.editor.hide()
        if feature:
            blocked = self.features.blockSignals(True)
            try:
                self.select_feature(feature)
            finally:
                self.features.blockSignals(blocked)
            self.history_controller.highlight_planes()

    def parameter_value(self, *args):
        feature = next((f for f in (self.state or {}).get("features", []) if f["id"] == self.selected()), None)
        info = feature and feature["parameters"].get(self.parameter.currentText())
        if info:
            self.value.setSuffix(" " + info["unit"])
            self.value.setValue(info["value"])
            self.value.setEnabled(info.get("editable", True))
            self.apply.setEnabled(True)
            self.formula.setText(info.get("expression") or "")
            self.clear_formula.setEnabled(bool(info.get("expression")))
            self.value.setToolTip("Driven by " + info["expression"] if info.get("expression") else "Driving dimension")

    def apply_parameter(self):
        if self.selected() and self.parameter.currentText():
            if self.formula.text().strip():
                self.operation("set_expression", feature=self.selected(), parameter=self.parameter.currentText(), expression=self.formula.text().strip())
            else:
                self.operation("set_parameter", feature=self.selected(), parameter=self.parameter.currentText(), value=self.value.lineEdit().text())

    def fill_recent(self, menu):
        menu.clear()
        for path in self.core.settings.data.get("recent_projects", []):
            if Path(path).suffix.lower() in {".fcstd", ".step", ".stp"} and Path(path).is_file():
                action = menu.addAction(Path(path).name)
                action.setToolTip(path)
                action.triggered.connect(lambda checked=False, p=path: self.open_path(p))
        if not menu.actions():
            menu.addAction("No recent projects").setEnabled(False)

    def fill_recovery(self, menu):
        menu.clear()
        records = self.core.recovery.available()
        for path, record in records:
            label = record["name"] + (" · unfinished sketch" if record.get("sketch") else " · checkpoint")
            action = menu.addAction(label)
            action.setToolTip(record.get("source_file") or str(path))
            action.triggered.connect(lambda checked=False, p=str(path): self.operation("recover", path=p))
        if not records:
            menu.addAction("No recoverable projects").setEnabled(False)

    def checkpoint_projects(self):
        try:
            self.core.recovery.poll()
        except Exception as exc:
            self.notify(str(exc), "error")
        if (self.core.busy or getattr(self, "_geometry_check_preparing", False)
                or getattr(self, "_step_export_preparing", False)
                or self.native_feature_task_active() or not self.responsiveness.is_idle()
                or (self.active_sketch() and self.sketch_references.native_tool)
                or QtGui.QApplication.mouseButtons() != QtCore.Qt.NoButton
                or self.task or self.studio_dialog or self.placement_document):
            return
        with self.history_controller.suspend_planes():
            for doc in list(self.core.documents.values()):
                if self.core._is_open(doc):
                    before = self.core.recovery.snapshot_count
                    try:
                        self.core.timings.measure("recovery_snapshot_gui", self.core.checkpoint, doc, background=True)
                    except Exception as exc:
                        self.notify("Recovery checkpoint failed: " + str(exc), "error")
                    if self.core.recovery.snapshot_count != before:
                        # Publication may finish while capture starts. Count
                        # native attempts, including failed ones, not futures.
                        break

    def feedback_complete(self):
        if hasattr(self, "responsiveness"):
            self.responsiveness.ui_updated()
        started = getattr(self, "feedback_started", None)
        if started is not None:
            elapsed = (time.perf_counter() - started) * 1000
            # Legacy metric is UI work completed, not a presented frame. Keep
            # long stalls; the separate monitor records paint/swap milestones.
            self.core.timings.record("input_to_feedback", elapsed)
            self.core.timings.record("input_to_feedback_" + self.feedback_kind, elapsed)
            self.feedback_started = None

    def pierce(self):
        sketch = self.active_sketch()
        if not sketch:
            self.notify("Edit a sketch before applying Pierce.", "error")
            return True
        selected = Gui.Selection.getSelectionEx()
        point = [(item.Object, name) for item in selected for name in item.SubElementNames if item.Object == sketch and name.startswith("Vertex")]
        curves = [(item.Object, name) for item in selected for name in item.SubElementNames if item.Object != sketch and name.startswith("Edge")]
        if len(point) != 1 or len(curves) != 1:
            self.notify("Select one sketch endpoint or center and one 3D curve edge, then press Shift+G.", "error")
            return True
        geometry, position = sketch.getGeoVertexIndex(int(point[0][1][6:]) - 1)
        self.operation("pierce", sketch=sketch.Name, geometry=geometry, point=position,
                       target=curves[0][0].Name, subelement=curves[0][1])
        return True

    def unique(self, base):
        doc = self.document()
        n, key = 1, base
        while doc.getObject(key):
            n += 1
            key = base + str(n)
        return key

    def new_part(self):
        doc = self.document()
        if not doc:
            self.notify("Create or open a project first.")
            return
        return self.operation("create_body", id=self.unique("Body"), name="Part " + str(len(self.sketch_owners()) + 1))

    def new(self):
        self.cancel_placement()
        if self.operation("new", name="Untitled part"):
            navigation.reset_new_document_view()
            Gui.activeDocument().activeView().setAxisCross(True)
            self.editor.hide()

    def open(self):
        if self.active_sketch() or self.native_feature_task_active():
            self.notify("Finish or cancel the current edit before opening a project.")
            return
        directory = Path(self.core.settings.last_directory)
        if not directory.is_dir():
            directory = self.core.settings.project_directory
            directory.mkdir(parents=True, exist_ok=True)
        path = QtGui.QFileDialog.getOpenFileName(self, "Open project or import STEP", str(directory),
            "CAD files (*.FCStd *.fcstd *.FCSTD *.step *.stp *.STEP *.STP);;FreeCAD project (*.FCStd *.fcstd *.FCSTD);;STEP geometry (*.step *.stp *.STEP *.STP)")[0]
        if path:
            return self.open_path(path)

    def open_path(self, path):
        op = "import_step" if Path(path).suffix.lower() in {".step", ".stp"} else "open"
        if op == "import_step":
            QtGui.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            state = self.operation(op, path=path)
        finally:
            if op == "import_step":
                QtGui.QApplication.restoreOverrideCursor()
        if state:
            self.core.settings.remember(path)
            self.isometric()
            self.fit()
            if op == "import_step":
                name = self.core.documents[state["document_id"]].Name
                # FreeCAD adds new view-provider nodes on the event loop.
                # Fit again after those nodes exist, while this import is
                # still active, so a direct/recent import cannot fit empty.
                QtCore.QTimer.singleShot(0, lambda: self.frame_import(name))
        return state

    def frame_import(self, name):
        if self.document() and self.document().Name == name and not self.active_sketch() and not self.native_feature_task_active():
            self.isometric()
            self.fit()

    def save(self, save_as=False):
        if not self.state:
            return
        if not self.state.get("managed", True):
            return self.adopt()
        if self.active_sketch() or self.native_feature_task_active():
            self.notify("Finish or cancel the current edit before saving the project.")
            return
        path = self.state.get("native_file") if not save_as else None
        if not path:
            self.core.settings.project_directory.mkdir(parents=True, exist_ok=True)
            imported = self.state.get("import_source")
            filename = Path(imported["path"]).stem + ".FCStd" if imported else ("my-assembly.FCStd" if self.assembly_state() else "my-part.FCStd")
            path = QtGui.QFileDialog.getSaveFileName(self, "Save project", self.state.get("native_file") or str(Path(self.core.settings.last_directory) / filename), "FreeCAD project (*.FCStd)")[0]
        if path:
            self.core.settings.grant_destination(path)
            return self.operation("save", path=path)

    def adopt(self):
        if not self.state:
            return
        unsupported = self.state.get("unsupported_objects", [])
        if unsupported:
            self.notify("Adoption needs unsupported objects resolved: " + ", ".join(unsupported), "error")
            return
        self.core.settings.project_directory.mkdir(parents=True, exist_ok=True)
        path = QtGui.QFileDialog.getSaveFileName(self, "Adopt a copy", str(Path(self.core.settings.last_directory) / "adopted-part.FCStd"), "FreeCAD project (*.FCStd)")[0]
        if path:
            self.core.settings.grant_destination(path)
            return self.operation("adopt", path=path)

    def start_step_export(self, path):
        """Start one UI export; the dialog has already authorized this destination."""
        if self._step_export_closed or self._step_export_preparing or self.core.busy:
            return None
        if self.active_sketch() or self.native_feature_task_active():
            self.notify("Finish or cancel the current edit before exporting the solid.")
            return None
        doc = self.document()
        if doc is None or not self.state:
            return None
        self._cancel_geometry_check()
        generation = self._step_export_generation + 1
        self._cancel_step_export()
        if not self._step_export_context_current(generation, doc):
            return None
        self._step_export_document = doc
        self._step_export_preparing = True
        self._step_export_preparing_generation = generation
        self.task_feedback("Preparing STEP export…")
        bundle = error = None
        try:
            with self.history_controller.suspend_planes():
                bundle = self.core.prepare_step_export(
                    doc, path, is_current=lambda: self._step_export_context_current(generation, doc))
        except Exception as exc:
            error = exc
        finally:
            self._step_export_preparing = False
            self._step_export_preparing_generation = None
        if not self._step_export_context_current(generation, doc):
            if bundle is not None:
                bundle["worker"].close()
            self._restore_step_export_status(generation)
            return None
        if error is not None:
            self.notify(str(error), "error")
            return None
        if bundle is None:
            # STL and conservative contexts keep the synchronous native contract.
            return self._step_export_fallback(doc, path, generation)
        job = {"document": doc, "generation": generation, "bundle": bundle}
        self._step_export_job = job
        try:
            bundle["worker"].submit(bundle["sequence"], bundle["envelope"])
        except Exception as exc:
            current = self._step_export_current(job)
            self._retire_step_export(job)
            if current and self._step_export_context_current(generation, doc):
                self.notify(str(exc), "error")
            else:
                self._restore_step_export_status(generation)
            return None
        if not self._step_export_current(job):
            self._retire_step_export(job)
            self._restore_step_export_status(generation)
            return None
        self.task_feedback("Exporting STEP… Escape to cancel")
        self.step_export_timer.start()
        return None

    def _step_export_fallback(self, doc, path, generation):
        self.task_feedback("Exporting…")
        response = error = None
        QtGui.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            if self._step_export_context_current(generation, doc):
                # STL can choose fallback before preparation synchronizes the
                # native document. Capture its token only after that sync.
                self.core.sync(doc)
                request = {"op": "export", "path": path, "document_id": self.core.identifier(doc),
                           "expected_revision": self.core._meta(doc).Revision, "measure": self.MEASURE}
                if self._step_export_context_current(generation, doc):
                    response = self.core.dispatch(request)
        except Exception as exc:
            error = exc
        finally:
            QtGui.QApplication.restoreOverrideCursor()
        if not self._step_export_context_current(generation, doc):
            self._restore_step_export_status(generation)
            return None
        if error is not None or response is None or not response["ok"]:
            self.notify(str(error) if error is not None else (response or {}).get("error", {}).get("message", "Export could not complete"), "error")
            return None
        self.state = response["result"]
        self.refresh()
        if self._step_export_context_current(generation, doc):
            self.notify("Exported " + Path(path).name)
        return None

    def _step_export_context_current(self, generation, doc):
        if self._step_export_closed or generation != self._step_export_generation:
            return False
        current = self.core._is_open(doc) and self.document() == doc
        return current and not self._step_export_closed and generation == self._step_export_generation

    def _step_export_current(self, job):
        return (self._step_export_job is job
                and self._step_export_context_current(job["generation"], job["document"])
                and self._step_export_job is job)

    def _restore_step_export_status(self, generation):
        if (not self._step_export_closed and generation == self._step_export_generation
                and self._step_export_job is None
                and self.message.text() in {"Preparing STEP export…", "Exporting…", "Exporting STEP… Escape to cancel"}):
            self.restore_status()

    def _retire_step_export(self, job):
        if self._step_export_job is job:
            self._step_export_job = None
            self.step_export_timer.stop()
        job["bundle"]["worker"].close()

    def _cancel_step_export(self, notify=False):
        job = self._step_export_job
        pending = job is not None or self._step_export_preparing
        self._step_export_generation += 1
        generation = self._step_export_generation
        if job is not None:
            self._retire_step_export(job)
        if pending and not self._step_export_closed and generation == self._step_export_generation:
            if notify:
                self.notify("STEP export canceled")
            else:
                self.restore_status()
        return pending

    def _poll_step_export(self):
        job = self._step_export_job
        if job is None or self._step_export_preparing or self.core.busy:
            return
        if not self._step_export_current(job):
            if self._step_export_job is job:
                self._cancel_step_export()
            else:
                self._retire_step_export(job)
            return
        try:
            response = job["bundle"]["worker"].poll()
            if not self._step_export_current(job):
                self._retire_step_export(job)
                self._restore_step_export_status(job["generation"])
                return
            if response is None:
                return
            provenance = self.core.accept_step_export(job["document"], job["bundle"], response,
                is_current=lambda: self._step_export_current(job),
                owns_job=lambda: not self._step_export_closed and self._step_export_job is job
                    and self._step_export_generation == job["generation"])
        except Exception as exc:
            current = self._step_export_current(job)
            self._retire_step_export(job)
            if current and self._step_export_context_current(job["generation"], job["document"]):
                invalid_state = job["bundle"].get("invalid_state")
                if invalid_state is not None:
                    owns_publication = lambda: not self._step_export_closed and self._step_export_job is None and self._step_export_generation == job["generation"]
                    # Context first, native model reads last, then pure ownership.
                    if (not self.core._step_export_current(job["document"], job["bundle"],
                            require_worker_open=False, require_valid=False) or not owns_publication()):
                        self._restore_step_export_status(job["generation"])
                        return
                    self.state = invalid_state
                    self.refresh()
                    if (self._step_export_context_current(job["generation"], job["document"])
                            and self.core._step_export_current(job["document"], job["bundle"],
                                require_worker_open=False, require_valid=False) and owns_publication()):
                        self.notify(str(exc), "error")
                elif self._step_export_context_current(job["generation"], job["document"]):
                    self.notify(str(exc), "error")
            self._restore_step_export_status(job["generation"])
            return
        current = self._step_export_current(job)
        self._retire_step_export(job)
        if not current or not self._step_export_context_current(job["generation"], job["document"]):
            self._restore_step_export_status(job["generation"])
            return
        if provenance is None:
            self.notify("STEP export discarded because the project or destination changed. Export again to use the current state.")
        else:
            self.notify("Exported " + job["bundle"]["destination"].name)

    def export(self):
        if not self.state:
            return
        if self.active_sketch() or self.native_feature_task_active():
            self.notify("Finish or cancel the current edit before exporting the solid.")
            return
        path = QtGui.QFileDialog.getSaveFileName(self, "Export current solid", str(Path(self.core.settings.last_directory) / "my-part.step"), "STEP (*.step *.stp);;STL (*.stl)")[0]
        if path:
            self.core.settings.grant_destination(path)
            self.start_step_export(path)

    def start_sketch(self):
        if self.state and not self.state.get("managed", True):
            self.notify("Adopt a copy before editing this reference file.", "error")
            return
        if self.active_sketch():
            self.notify("A sketch is already being edited.")
            return
        if self.native_feature_task_active():
            self.notify("Finish or cancel the current feature before starting a sketch.")
            return
        if not self.state:
            self.new()
        if not self.state:
            return
        self.cancel_task()
        for selected in Gui.Selection.getSelectionEx():
            for sub in selected.SubElementNames:
                if sub.startswith("Face"):
                    support = self.reference_from_geometry(selected.Object, sub, "Face")
                    body = owner(self.document(), selected.Object)
                    return self.begin_sketch(support=support, **({"body": body.Name} if body else {}))
            if selected.Object.TypeId in {"App::Plane", "PartDesign::Plane"}:
                return self.begin_sketch(support={"feature": selected.Object.Name})
        Gui.Selection.clearSelection()
        self.pending_sketch, self.selecting_support = True, False
        doc = self.document()
        self.placement_document = doc.Name
        body = self.active_body()
        if not body:
            self.notify("Choose a Body before starting a sketch.", "error")
            self.cancel_placement()
            return
        origin = body.Origin
        self.history_controller.planes.restore()
        self.plane_visibility = {origin.Name: origin.ViewObject.Visibility}
        origin.ViewObject.Visibility = True
        for plane in ["XY", "XZ", "YZ"]:
            obj = self.plane(doc, plane)
            self.plane_visibility[obj.Name] = obj.ViewObject.Visibility
            obj.ViewObject.Visibility = True
        self.items["origin"].setExpanded(True)
        self.editor_title.setText("New sketch")
        self.editor_help.setText("Click a planar face in the model, or Top, Front or Right in the history. One click starts the sketch.")
        self.configure_editor("placement")
        self.task_feedback("New sketch · select a plane or planar face")
        self.editor.show_compact()
        self.notify("Select a face or plane for the sketch · Escape cancels")

    def cancel_placement(self):
        doc = App.listDocuments().get(self.placement_document) if self.placement_document else None
        if doc:
            for name, visible in self.plane_visibility.items():
                obj = doc.getObject(name)
                if obj:
                    obj.ViewObject.Visibility = visible
        self.plane_visibility = {}
        self.placement_document = None
        self.pending_sketch = self.selecting_support = False
        if not self.active_sketch() and not self.task:
            self.editor.hide()

    def choose_support(self, document, identifier, subelement):
        if not self.pending_sketch or not self.document() or self.document().Name != document:
            self.selecting_support = False
            return
        support = {"feature": identifier}
        if subelement:
            support = self.reference_from_geometry(self.document().getObject(identifier), subelement, "Face")
        body = owner(self.document(), self.document().getObject(identifier))
        if not self.begin_sketch(support=support, **({"body": body.Name} if body else {})):
            self.selecting_support = False

    def begin_sketch(self, **attachment):
        identifier = self.unique("Sketch")
        if not self.operation("create_sketch", id=identifier, **attachment):
            return None
        self.cancel_placement()
        self.select_feature(identifier)
        return self.edit_sketch()

    def edit_sketch(self):
        obj = self.document().getObject(self.selected() or "") if self.document() else None
        if obj and self.feature_held(obj.Name):
            self.notify("Roll forward through this sketch before editing it.")
            return None
        if not obj or obj.TypeId != "Sketcher::SketchObject":
            self.notify("Select a sketch in the feature history.")
            return None
        if self.active_sketch():
            return None
        self.entering_sketch = True
        try:
            if not self.operation("begin_sketch_edit", feature=obj.Name):
                return None
            self.cancel_placement()
            Gui.Selection.clearSelection()
            Gui.activateWorkbench("SketcherWorkbench")
            view = Gui.activeDocument().activeView()
            camera = view.getCamera()
            self.history_controller.planes.restore()
            self.sketch_history.enter(obj)
            navigation.allow_sketch_3d(obj, view)
            Gui.getDocument(obj.Document.Name).setEdit(obj.Name)
            self.sketch_snapping.begin(obj, self.main.devicePixelRatioF())
            navigation.allow_sketch_3d(obj, view, camera=camera)
            navigation.apply_navigation(view)
            self.sketch_history.apply()
        except Exception as exc:
            self.sketch_snapping.restore()
            self.operation("finish_sketch_edit", cancel=True)
            self.sketch_history.leave()
            self.notify(str(exc), "error")
            return None
        finally:
            self.entering_sketch = False
        self.sync_edit_ui()
        self.notify("Sketch editing · highlight an edge, then U to use it · Ctrl-select a center and edge, then D to dimension")
        return obj

    def finish_sketch(self, cancel=False):
        if self.sketch_plane_editor.picking and not cancel:
            self.notify("Select a replacement sketch plane, or press Escape to keep the current plane.")
            return None
        if not self.active_sketch() and not (self.state or {}).get("active_sketch_edit"):
            return None
        sketch_name = (self.active_sketch().Name if self.active_sketch()
                       else (self.state or {}).get("active_sketch_edit"))
        self.finishing_sketch = True
        self.sketch_references.end_tool()
        try:
            self.sketch_plane_editor.close()
            if self.active_sketch():
                Gui.activeDocument().resetEdit()
            result = self.operation("finish_sketch_edit", cancel=bool(cancel))
            if result:
                self.sketch_snapping.restore()
                self.sketch_history.leave()
                if not cancel:
                    show_unconsumed_sketch(self.document().getObject(sketch_name))
                self.complete_editor()
            else:
                feature = (self.state or {}).get("active_sketch_edit")
                if feature and self.document().getObject(feature) and not self.active_sketch():
                    Gui.activeDocument().setEdit(feature)
                self.sketch_history.apply()
        finally:
            self.finishing_sketch = False
        self.sync_edit_ui()
        hide_native_panels()
        return result

    def sync_edit_ui(self):
        sketch = self.active_sketch() or (self.sketch_plane_editor.sketch() if self.sketch_plane_editor.picking else None)
        if sketch is None and not self.entering_sketch and not self.finishing_sketch:
            self.sketch_snapping.restore()
        self.sketch_snapping.sync_tool(self.sketch_references.native_command_for_context())
        self.sketch_cursor.sync(self.sketch_references.native_command_for_context())
        self.sketch_history.apply()
        self.sketch_colors.apply()
        self.sketch_regions.apply()
        self.sketch_plane_editor.apply_visibility()
        native_task = self.native_feature_task_active()
        self.rollback_bar.setEnabled(not bool(sketch) and not native_task)
        for action in self.file_actions:
            action.setEnabled(not bool(sketch) and not native_task)
        for action in self.history_actions:
            action.setEnabled(not native_task)
        for action in self.model_actions:
            action.setEnabled(not native_task and (not self.state or self.state.get("managed", True)))
        self.mode_choice.setEnabled(not bool(sketch) and not native_task)
        assembly = self.assembly_state()
        for action in self.assembly_actions:
            action.setEnabled(not bool(sketch) and not native_task and bool(self.state) and self.state.get("managed", True)
                              and (not assembly if action.text() == "Create Assembly" else bool(assembly)))
        self.model_bar.setVisible(not bool(sketch) and self.workspace_mode == "part_studio")
        self.assembly_bar.setVisible(not bool(sketch) and self.workspace_mode == "assembly")
        self.sketch_bar.setVisible(bool(sketch))
        hide_native_panels()
        if sketch:
            self.task = None
            self.editor_title.setText(sketch.Label)
            already_sketch = self.editor_mode == "sketch"
            self.configure_editor("sketch", True)
            if not self.editor.isVisible() or not already_sketch:
                self.task_feedback("Editing sketch · mm")
                self.editor.show_compact()
        elif native_task:
            self.editor.hide()

    def extrude(self, cut=False, choose_new=False):
        if self.studio_dialog:
            self.studio_dialog.reject()
        if self.native_feature_task_active():
            self.notify("Finish or cancel the current feature before starting another tool.")
            return
        if self.active_sketch():
            profile = self.active_sketch().Name
            if not self.finish_sketch():
                return
            self.select_feature(profile)
        selected = Gui.Selection.getSelection()
        selected_faces = [] if choose_new else self.geometry_references("Face")
        profile = None if choose_new else (selected[0].Name if selected and selected[0].TypeId == "Sketcher::SketchObject" else self.selected())
        obj = self.document().getObject(profile or "") if self.document() else None
        if not self.document():
            self.notify("Create or open a project first.")
            return
        self.cancel_placement()
        self.extrusion_preview.clear()
        self.reset_edit_controls()
        self.task, self.task_profile = ("pocket" if cut else "pad"), (selected_faces[0] if len(selected_faces) == 1 else obj.Name if obj and obj.TypeId == "Sketcher::SketchObject" else None)
        self.task_document = self.document().Name
        self.studio_operation_explicit = False
        self.up_to_face_reference = None
        self.end_face.setText("Use selected face")
        profile_owner = owner(self.document(), obj)
        self.result_operation.blockSignals(True)
        default = "remove" if cut else ("add" if profile_owner and not profile_owner.Shape.isNull() and profile_owner.Shape.Solids else "new")
        self.result_operation.setCurrentIndex(self.result_operation.findData(default))
        self.result_operation.blockSignals(False)
        self.merge_scope.setCurrentIndex(0)
        self.fill_merge_parts(self.merge_parts, [entry["id"] for entry in self.studio_parts() if entry["body"] == (profile_owner.Name if profile_owner else "")])
        self.editor_title.setText("Remove material" if cut else "Extrude")
        self.editor_help.setText("Selected face" if isinstance(self.task_profile, dict) else obj.Label + " · " + ("Remove material" if cut else "Extrude") if self.task_profile else "Select a closed sketch or a planar face.")
        self.end_type.setCurrentIndex(1 if cut else 0)
        self.end_type.model().item(1).setEnabled(True)
        if isinstance(self.task_profile, dict):
            self.end_type.setCurrentIndex(0)
            self.end_type.model().item(1).setEnabled(False)
            self.end_type.model().item(2).setEnabled(False)
            self.depth.setEnabled(True)
            self.result_operation.setCurrentIndex(self.result_operation.findData("remove" if cut else "add"))
        else:
            self.end_type.model().item(2).setEnabled(True)
        self.depth.setEnabled(isinstance(self.task_profile, dict) or not cut)
        self.reverse.setChecked(isinstance(self.task_profile, dict) and cut)
        self.configure_editor("extrude")
        self.task_feedback("Remove material · editing feature" if cut else "Extrude · editing feature")
        self.editor.show_compact()
        self.depth.setFocus()
        self.depth.selectAll()
        self.begin_preview()

    def extrusion_proposal(self):
        if self.task_edit is not None:
            return self.extrusion_edit_proposal()
        if isinstance(self.task_profile, dict):
            return {"op": "extrude_face", "face": self.task_profile,
                    "length": self.depth.lineEdit().text(), "reversed": self.reverse.isChecked(),
                    "operation": self.result_operation.currentData(),
                    "merge_scope": self.scope_value(self.merge_scope, self.merge_parts)}
        proposal = {"op": self.task, "profile": self.task_profile,
                    "length": self.depth.lineEdit().text()}
        if ((self.state or {}).get("studio", {}).get("enabled") or self.studio_operation_explicit
                or self.merge_scope.currentData() == "explicit" or self.task == "pad" and self.end_type.currentIndex() == 1):
            proposal["operation"] = self.result_operation.currentData()
            proposal["merge_scope"] = self.scope_value(self.merge_scope, self.merge_parts)
        if self.task == "pad" or self.reverse.isChecked():
            proposal["reversed"] = self.reverse.isChecked()
        if self.task == "pocket" and "operation" in proposal and self.end_type.currentIndex() == 0:
            # A studio Remove cuts into the material with native Reversed set.
            # Reverse direction must flip that default, as it does elsewhere.
            proposal["reversed"] = not self.reverse.isChecked()
        if self.task == "pocket":
            proposal["through_all"] = self.end_type.currentIndex() == 1
        elif self.end_type.currentIndex() == 1:
            proposal.pop("length", None)
            proposal["end_type"] = "through_all"
        if self.end_type.currentIndex() == 2:
            proposal.pop("length", None)
            proposal.pop("through_all", None)
            proposal["end_type"] = "up_to_face"
            proposal["up_to_face"] = self.up_to_face_reference
        return proposal

    def editable_extrusion(self, key):
        """Current native settings of an Extrude/Remove, or None when not supported here."""
        doc = self.document()
        if not doc or not isinstance(key, str) or key.startswith("plane:") or self.workspace_mode == "assembly":
            return None
        try:
            return extrusion_edit.describe(doc, key)
        except OperationError:
            return None

    def edit_extrusion(self, key=None):
        """Reopen an existing Extrude/Remove in the feature dialog with its current settings."""
        key = key or self.selected()
        doc = self.document()
        if not doc or not key:
            self.notify("Select an Extrude or Remove material feature to edit.")
            return False
        if self.state and not self.state.get("managed", True):
            self.notify("Adopt a copy before editing this reference file.", "error")
            return False
        if self.feature_held(key):
            self.notify("Roll forward through this feature before editing it.")
            return False
        if self.active_sketch():
            self.notify("Finish the sketch before editing another feature.")
            return False
        if self.native_feature_task_active():
            self.notify("Finish or cancel the current feature before starting another tool.")
            return False
        try:
            info = extrusion_edit.describe(doc, key)
        except OperationError as exc:
            self.notify(str(exc), "error")
            return False
        if self.studio_dialog:
            self.studio_dialog.reject()
        self.cancel_placement()
        self.extrusion_preview.clear()
        self.task = "pocket" if info["kind"] == "remove" else "pad"
        self.task_profile, self.task_document, self.task_edit = info["feature"], doc.Name, info
        self.studio_operation_explicit = False
        self.up_to_face_reference = None
        controls = (self.depth, self.end_type, self.reverse, self.result_operation, self.formula, self.merge_scope)
        blocked = [control.blockSignals(True) for control in controls]
        try:
            self.result_operation.setCurrentIndex(max(0, self.result_operation.findData(info["operation"])))
            self.result_operation.setEnabled(False)
            self.result_operation.setToolTip("An existing feature keeps its result operation")
            self.merge_scope.setCurrentIndex(0)
            names = ("blind", "through_all", "up_to_face")
            for index, name in enumerate(names):
                self.end_type.model().item(index).setEnabled(name in info["end_types"])
            self.end_type.setCurrentIndex(names.index(info["end_type"]))
            self.end_type.setToolTip("; ".join(info["limitations"]))
            self.end_face.setText("End face · " + (info["end_face"] or "retained"))
            self.end_face.setEnabled(False)
            # Load the authoritative value without the creation range clamp
            # (tiny or formula-signed depths). The widget may still round its
            # display; an untouched field is therefore never resent.
            self.depth.setRange(-1e6, 1e6)
            if info["length"]["value"] is not None:
                self.depth.setValue(info["length"]["value"])
            self.edit_depth_touched = False
            self.formula.setText(info["length"]["expression"] or "")
            self.formula.setPlaceholderText("Optional depth formula, e.g. Plate.Constraints.Width / 2")
            self.reverse.setChecked(info["reversed"])
            self.reverse.setEnabled(info["reverse_editable"])
            self.reverse.setToolTip(info["reverse_reason"] or "Reverse this feature's direction")
        finally:
            for control, previous in zip(controls, blocked):
                control.blockSignals(previous)
        self.editor_title.setText(info["label"])
        self.configure_editor("extrude")
        self.sync_edit_controls()
        self.task_feedback(("Remove material" if info["kind"] == "remove" else "Extrude") + " · editing " + info["label"])
        self.editor.show_compact()
        if self.depth.isEnabled():
            self.depth.setFocus()
            self.depth.selectAll()
        self.begin_preview()
        return True

    def sync_edit_controls(self):
        info = self.task_edit
        if info is None:
            return
        blind = self.end_type.currentIndex() == 0
        self.depth.setEnabled(blind and not self.formula.text().strip())
        self.formula.setEnabled(blind)
        native = info["length"]["value"]
        exact = f"{native:.12g} mm" if native is not None else None
        rounded = False
        if exact and not self.edit_depth_touched:
            try:
                rounded = abs(number(self.depth.lineEdit().text(), "Depth") - native) > 1e-12
            except OperationError:
                rounded = True
        self.depth.setToolTip(("Driven by the formula below; clear it to enter a depth"
                               if self.formula.text().strip() else "Depth")
                              + (f" · exact value {exact} is kept unless you change it" if rounded else ""))
        direction = extrusion_edit.direction_after(info, self.reverse.isChecked())
        reference = info["direction_reference"]
        words = {"along": "along the " + reference, "against": "against the " + reference,
                 "both": "in both directions"}[direction]
        kind = "Remove material" if info["kind"] == "remove" else "Extrude"
        self.editor_help.setText(f"{info['profile']['label'] or 'Profile'} · {kind} · {words}"
                                 + (f" · depth {exact} (shown rounded)" if rounded else ""))

    def extrusion_edit_proposal(self):
        """Only changed fields; unchanged formulas and directions are never resent."""
        info = self.task_edit
        proposal = {"op": "edit_extrusion", "feature": info["feature"]}
        end_type = ("blind", "through_all", "up_to_face")[self.end_type.currentIndex()]
        if end_type != info["end_type"]:
            proposal["end_type"] = end_type
        if end_type == "blind":
            formula, current = self.formula.text().strip(), info["length"]["expression"]
            text = self.depth.lineEdit().text()
            if formula:
                if formula != current:
                    proposal["expression"] = formula
            else:
                if current:
                    # Clearing keeps the native, last evaluated depth.
                    proposal["expression"] = None
                # Only an explicit user change sends a depth. Display text
                # can be rounded, clamped or stale and is never authoritative.
                if self.edit_depth_touched:
                    try:
                        unchanged = abs(number(text, "Depth", True) - (info["length"]["value"] or 0)) < 1e-12
                    except OperationError:
                        unchanged = False
                    if not unchanged:
                        proposal["length"] = text
        if self.reverse.isEnabled() and self.reverse.isChecked() != info["reversed"]:
            proposal["reversed"] = self.reverse.isChecked()
        return proposal

    def mark_depth_touched(self, *args):
        if self.task_edit is not None:
            self.edit_depth_touched = True

    def edit_unchanged(self):
        return self.task_edit is not None and set(self.extrusion_edit_proposal()) == {"op", "feature"}

    def accept_edit(self):
        info = self.task_edit
        proposal = self.extrusion_edit_proposal()
        if set(proposal) == {"op", "feature"}:
            self.task = self.task_profile = self.task_document = None
            self.reset_edit_controls()
            self.extrusion_preview.clear()
            self.complete_editor(info["feature"])
            return True
        # Same exact-preview acceptance as creation: commit only a current,
        # valid preview of these fields against its base revision.
        self.extrusion_preview.schedule(proposal)
        preview = self.extrusion_preview.flush()
        if not preview or not preview.valid:
            return False
        args = dict(preview.proposal)
        args.pop("op")
        args["_expected_revision"] = preview.base_revision
        result = self.operation("edit_extrusion", **args)
        if result:
            self.task = self.task_profile = self.task_document = None
            self.reset_edit_controls()
            self.complete_editor(info["feature"])
        elif self.task_edit is not None:
            self.begin_preview()
        return result

    def reset_edit_controls(self):
        """Return shared Extrude controls to their creation-time behavior."""
        self.task_edit = None
        self.edit_depth_touched = False
        self.depth.setRange(0.01, 100000)
        self.result_operation.setEnabled(True)
        self.result_operation.setToolTip("")
        self.reverse.setEnabled(True)
        self.reverse.setToolTip("")
        self.end_type.setToolTip("")
        self.end_face.setEnabled(True)
        self.formula.setEnabled(True)
        self.formula.setPlaceholderText("Example: Plate.Constraints.Width / 2")
        for index in range(self.end_type.count()):
            self.end_type.model().item(index).setEnabled(True)

    def begin_preview(self):
        if self.task not in {"pad", "pocket"} or not self.task_profile:
            self.preview_status(None)
            return
        self.state = self.core.inspect(self.document(), measure=self.MEASURE)
        self.extrusion_preview.begin(self.document(), self.state["revision"])
        self.schedule_preview()

    def schedule_preview(self, *args):
        if not hasattr(self, "extrusion_preview") or self.task not in {"pad", "pocket"}:
            return
        self.end_face.setVisible(self.end_type.currentIndex() == 2)
        end_label = self.form.labelForField(self.end_face)
        if end_label:
            end_label.setVisible(self.end_face.isVisible())
        self.merge_parts.setVisible(self.result_operation.currentData() != "new" and self.merge_scope.currentData() == "explicit")
        scope_label = self.form.labelForField(self.merge_parts)
        if scope_label:
            scope_label.setVisible(self.merge_parts.isVisible())
        if self.task_edit is not None:
            self.sync_edit_controls()
            if self.extrusion_preview.evaluator is not None and self.edit_unchanged():
                self.extrusion_preview.idle()
                self.preview_status(None)
                return
        if self.task_profile:
            if self.extrusion_preview.evaluator is None:
                self.preview_status(None)
                return
            self.extrusion_preview.trace_entry = self.responsiveness.trace.current
            self.extrusion_preview.schedule(self.extrusion_proposal())
            # Native quantities normalize on focus loss. Equal physical intent
            # retains its valid result, so a Confirm press is never disabled
            # halfway through the click merely by added decimal places.
            if self.extrusion_preview.result is None:
                self.editor.set_accept_enabled(False)
                self.editor.set_status("Updating preview…")
        else:
            self.editor.set_accept_enabled(False)
            self.editor.set_status("Select a closed sketch to preview the extrusion.")

    def preview_status(self, result):
        if self.task not in {"pad", "pocket"}:
            self.preview_hint.clear()
            return
        self.editor.set_accept_enabled(bool(result and result.valid))
        if result is None and self.task_edit is not None and self.extrusion_preview.evaluator is not None and self.edit_unchanged():
            self.editor.set_accept_enabled(True)
            self.editor.set_status("No changes · Confirm or Cancel closes without changing the model")
        elif result is None:
            self.editor.set_status("Select a closed sketch to preview the extrusion." if not self.task_profile else "Preview cleared. Start Extrude again to refresh.")
        elif result.valid and self.task_edit is not None:
            change = (result.measurements or {}).get("edit_volume_change_mm3")
            detail = f" · part volume {change:+.3f} mm³" if isinstance(change, (int, float)) else ""
            self.editor.set_status("Preview · edited " + self.task_edit["label"] + detail, "success")
        elif result.valid:
            operation = result.proposal.get("operation", "remove" if self.task == "pocket" else "add")
            self.editor.set_status("Preview · removed material" if operation in {"remove", "intersect"} else "Preview · added material", "success")
        elif result.provisional:
            self.editor.set_status("Provisional preview · checking exact result…")
        else:
            text = ("Select an end face for Up to face." if self.end_type.currentIndex() == 2 and not self.up_to_face_reference
                    else result.error["message"])
            self.editor.set_status(text, "error")
        entry = getattr(self.extrusion_preview, "trace_entry", None)
        if result:
            self.responsiveness.trace.mark(entry, "preview_provisional" if result.provisional else "preview_ready")
        self.responsiveness.ui_updated(entry)

    def accept_task(self):
        if self.studio_dialog:
            self.studio_dialog.accept()
            return True
        if self.sketch_plane_editor.picking:
            self.notify("Select a replacement sketch plane, or press Escape to keep the current plane.")
            return False
        if self.active_sketch():
            return self.finish_sketch()
        if self.task in {"pad", "pocket"}:
            if not self.document() or self.document().Name != self.task_document:
                self.cancel_task()
                self.notify("Feature canceled because its source document is no longer active.")
                return False
            if self.task_edit is not None:
                return self.accept_edit()
            kind, profile = self.task, self.task_profile
            if not profile:
                self.notify("Select a closed sketch profile from the history.")
                return False
            # Re-evaluate the current fields before acceptance, including the
            # revision guard. The visible preview and committed solid agree.
            self.extrusion_preview.schedule(self.extrusion_proposal())
            preview = self.extrusion_preview.flush()
            if not preview or not preview.valid:
                return False
            args = dict(preview.proposal)
            operation = args.pop("op")
            args.update(id=self.unique("ExtrudeRemove" if kind == "pocket" else "Extrude"),
                        _expected_revision=preview.base_revision)
            result = self.operation(operation, **args)
            if result:
                obj = self.document().getObject(args["id"])
                if isinstance(profile, str):
                    self.document().getObject(profile).ViewObject.Visibility = False
                if obj:
                    obj.ViewObject.Visibility = True
                self.task = self.task_profile = self.task_document = None
                self.complete_editor(obj.Name if obj else result.get("created_feature", args["id"]))
            else:
                self.begin_preview()
            return result
        return False

    def accept_repeat(self):
        kind = self.task
        editing = self.task_edit is not None
        result = self.accept_task() if kind else False
        if result and kind in {"pad", "pocket"} and not editing:
            self.extrude(kind == "pocket", choose_new=True)
        return result

    def cancel_task(self):
        if self._cancel_step_export(notify=True):
            return
        if self._cancel_geometry_check(notify=True):
            return True
        if self.sketch_plane_editor.picking:
            return self.sketch_plane_editor.resume()
        if self.sketch_references.stop():
            self.notify("Sketch reference picking ended")
            return True
        if self.studio_dialog:
            self.studio_dialog.reject()
            self.notify("Feature canceled")
            return True
        self.extrusion_preview.clear()
        if self.pending_sketch:
            self.cancel_placement()
            self.notify("Sketch placement canceled")
            return True
        if self.task:
            editing = self.task_edit is not None
            self.task = self.task_profile = self.task_document = None
            self.reset_edit_controls()
            self.editor.hide()
            self.notify("Edit canceled · model unchanged" if editing else "Feature canceled")
            return True
        return False

    def fit(self):
        if Gui.activeDocument():
            Gui.activeDocument().activeView().fitAll()

    def history_move(self, op):
        self.sketch_references.end_tool(stop_native=bool(self.active_sketch()))
        if self.active_sketch():
            self.router._last_native = None
        return self.operation(op)

    def isometric(self):
        return navigation.view_isometric_keep_sketch()

    def normal(self):
        obj = self.active_sketch()
        selection = Gui.Selection.getSelectionEx()
        placement = None
        if not obj and selection:
            obj = selection[0].Object
            if selection[0].SubObjects and hasattr(selection[0].SubObjects[0], "normalAt"):
                normal = selection[0].SubObjects[0].normalAt(0, 0)
                placement = App.Placement(App.Vector(), App.Rotation(App.Vector(0, 0, 1), normal))
        if not obj and self.document():
            key = self.selected() or ""
            obj = self.plane(self.document(), key.split(":")[1]) if key.startswith("plane:") else self.document().getObject(key)
        if placement is None and obj and obj.TypeId in {"Sketcher::SketchObject", "App::Plane", "PartDesign::Plane"}:
            placement = obj.getGlobalPlacement()
        if placement is not None:
            camera = Gui.activeDocument().activeView().getCameraOrientation()
            if abs(sum(a*b for a,b in zip(camera.Q, placement.Rotation.Q))) > 1-1e-6:
                placement.Rotation = placement.Rotation * App.Rotation(App.Vector(1, 0, 0), 180)
            return navigation.normal_to_sketch(placement)
        if Gui.activeDocument():
            Gui.activeDocument().activeView().viewTop()
        return True

    def toggle_planes(self):
        doc = self.document()
        if doc and self.active_body():
            planes = [self.plane(doc, key) for key in ["XY", "XZ", "YZ"]]
            visible = not any(obj.ViewObject.Visibility for obj in planes)
            self.active_body().Origin.ViewObject.Visibility = visible
            for obj in planes:
                obj.ViewObject.Visibility = visible

    def toggle_sketches(self):
        if self.document():
            sketches = [o for o in self.document().Objects if o.TypeId == "Sketcher::SketchObject"]
            visible = not any(o.ViewObject.Visibility for o in sketches)
            for obj in sketches:
                obj.ViewObject.Visibility = visible
            self.refresh()

    def hide_selected(self):
        selected = Gui.Selection.getSelection()
        if not selected:
            hovered = Gui.Selection.getPreselection()
            if hovered and hovered.Object:
                selected = [hovered.Object]
        for obj in selected:
            obj.ViewObject.Visibility = False
        self.refresh()

    def show_hidden(self):
        if self.document() and self.workspace_mode == "assembly":
            for entry in self.assembly_state().get("instances", []):
                obj = self.document().getObject(entry["id"])
                if obj:
                    obj.ViewObject.Visibility = True
            self.refresh()
            return
        if self.document():
            for obj in self.document().Objects:
                if obj.TypeId == "Sketcher::SketchObject" or any(obj == body.Tip or obj == body for body in bodies(self.document())):
                    obj.ViewObject.Visibility = True
            self.refresh()

    def rename_selected(self):
        selected = Gui.Selection.getSelection()
        identifier = self.assembly_selected_id() if self.workspace_mode == "assembly" else None
        obj = self.document().getObject(identifier) if identifier else (selected[0] if len(selected) == 1 else (self.document().getObject(self.selected() or "") if self.document() else None))
        if obj and self.feature_held(obj.Name):
            self.notify("Roll forward through this feature before editing it.")
            return None
        if obj:
            tokens = self.assembly_tokens() if self.workspace_mode == "assembly" else {}
            name, accepted = QtGui.QInputDialog.getText(self, "Rename " + ("assembly object" if identifier else "feature"), "Name", text=obj.Label)
            if accepted:
                self.operation("rename_feature", feature=obj.Name, name=name, **tokens)

    def delete_selected(self):
        if self.active_sketch():
            return self.native_command("Std_Delete")
        if self.workspace_mode == "assembly":
            if not self.assembly_ready():
                return None
            identifier = self.assembly_selected_id()
            if identifier:
                return self.operation("delete_assembly_object", feature=identifier)
            self.notify("Select an instance or joint to remove. Connected instances require removing their joints first.")
            return None
        return self.history_controller.delete()

    def history_menu(self, position):
        item = self.features.itemAt(position)
        if not item:
            return
        if not item.isSelected():
            self.features.setCurrentItem(item)
        key = item.data(0, QtCore.Qt.UserRole)
        obj = self.plane(self.document(), key.split(":")[1]) if key.startswith("plane:") else self.document().getObject(key)
        if not obj:
            return
        menu = QtGui.QMenu(self)
        menu.addAction("Hide" if obj.ViewObject.Visibility else "Show", lambda: self.set_visibility(obj, not obj.ViewObject.Visibility))
        if self.workspace_mode == "assembly":
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(obj)
            instances = {entry["id"] for entry in self.assembly_state().get("instances", [])}
            if key in instances:
                menu.addAction("Ground as reference", self.ground_assembly_instance)
                menu.addAction("Move free instance", self.move_assembly_selection)
            else:
                menu.addAction("Edit joint", self.edit_assembly_selection)
                menu.addAction("Move allowed coordinate", self.move_assembly_selection)
            menu.addAction("Rename", self.rename_selected)
            menu.addAction("Remove", self.delete_selected)
            menu.exec_(self.features.mapToGlobal(position))
            return
        keys = self.selected_ids()
        if len(keys) > 1:
            menu.clear()
            menu.addAction("Delete selected features", self.delete_selected).setEnabled(not any(self.feature_held(name) for name in keys))
            menu.exec_(self.features.mapToGlobal(position))
            return
        if obj.TypeId == "Sketcher::SketchObject":
            menu.addAction("Edit sketch", self.edit_sketch).setEnabled(not self.feature_held(key))
        if not key.startswith("plane:"):
            extrusion = self.editable_extrusion(key)
            if extrusion is not None:
                menu.addAction("Edit " + ("Remove material" if extrusion["kind"] == "remove" else "Extrude"),
                               lambda: self.edit_extrusion(key)).setEnabled(not self.feature_held(key))
            elif obj.TypeId.startswith("PartDesign::"):
                menu.addAction("Edit feature", self.edit_native_feature).setEnabled(not self.feature_held(key))
            menu.addAction("Rename", self.rename_selected).setEnabled(not self.feature_held(key))
            menu.addAction("Delete", self.delete_selected).setEnabled(not self.feature_held(key))
            menu.addAction("Feature settings", lambda: self.parameters(show=True)).setEnabled(not self.feature_held(key))
            order = ((self.state or {}).get("studio") or {}).get("feature_order", [])
            if key in order:
                menu.addSeparator()
                menu.addAction("Roll back before " + obj.Label, lambda: self.rollback_to(order.index(key)))
                menu.addAction("Roll forward through " + obj.Label, lambda: self.rollback_to(order.index(key) + 1))
                menu.addAction("Roll to end of history", lambda: self.rollback_to(len(order)))
        menu.exec_(self.features.mapToGlobal(position))

    def rollback_to(self, index):
        self.rollback_bar.setValue(index)
        return self.commit_rollback()

    def set_visibility(self, obj, visible):
        obj.ViewObject.Visibility = visible
        if obj.TypeId == "App::Plane":
            body = owner(self.document(), obj)
            if body:
                body.Origin.ViewObject.Visibility = True
        self.refresh()

    def feature_from_sketch(self, command):
        sketch = self.active_sketch()
        if sketch:
            name = sketch.Name
            if not self.finish_sketch():
                return False
            self.select_feature(name)
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(self.document().getObject(name))
        return self.native_command(command)

    def native_command(self, command, workbench=None):
        if command not in Gui.listCommands():
            self.notify("Tool unavailable: " + command, "error")
            return False

        if command.startswith("Sketcher_") and not self.active_sketch():
            self.notify("Start or edit a sketch before using this tool.")
            return False
        modeling = command.startswith("PartDesign_") or command in self.catalog_model_commands
        if (modeling or command.startswith("Sketcher_")) and self.state and not self.state.get("managed", True):
            self.notify("Adopt a copy before editing this reference file.", "error")
            return False
        if modeling and self.active_sketch():
            self.notify("Finish the sketch before creating a solid feature.")
            return False
        if modeling and self.native_feature_task_active():
            self.notify("Finish or cancel the current feature before starting another tool.")
            return False
        try:
            if modeling:
                self.cancel_task()
                if not self.document():
                    return False
                Gui.activateWorkbench(workbench or "PartDesignWorkbench")
                obj = self.document().getObject(self.selected() or "")
                if obj and not Gui.Selection.getSelection():
                    Gui.Selection.addSelection(obj)
            if self.sketch_references.start_dimension(command):
                self.sketch_cursor.sync(None)
                return True
            if not self.sketch_references.before_native(command):
                return False
            if command.startswith("Sketcher_"):
                # Recovered/native-opened managed sketches can enter the
                # editor without passing through edit_sketch().
                self.sketch_snapping.begin(self.active_sketch(), self.main.devicePixelRatioF())
            run_sketch_command(command)
            self.sketch_snapping.before_native(command)
            self.sketch_cursor.sync(self.sketch_references.native_command_for_context())
            if command == "Sketcher_Dimension":
                self.sketch_references.show_dimension_cursor()
            if self.active_sketch() and command.startswith(("Sketcher_Constrain", "Sketcher_Toggle")):
                self.core.record_edit_boundary(self.document())
            self.sync_edit_ui()
            hide_native_panels()
            return True
        except Exception as exc:
            if command.startswith("Sketcher_"):
                # A failed command must not leave recovery waiting forever
                # for a remembered drawing tool that never started.
                try:
                    Gui.runCommand("Sketcher_StopOperation")
                except Exception:
                    pass
                self.sketch_references.end_tool()
                self.router._last_native = None
            self.notify(str(exc), "error")
            return False

    def edit_native_feature(self):
        if self.state and not self.state.get("managed", True):
            self.notify("Adopt a copy before editing this reference file.", "error")
            return
        obj = self.document().getObject(self.selected() or "") if self.document() else None
        if obj and self.feature_held(obj.Name):
            self.notify("Roll forward through this feature before editing it.")
            return None
        if obj and obj.TypeId.startswith("PartDesign::") and not self.active_sketch():
            self.cancel_task()
            Gui.activateWorkbench("PartDesignWorkbench")
            self.editor.hide()
            Gui.activeDocument().setEdit(obj.Name)
            hide_native_panels()

    def measure(self):
        selections = Gui.Selection.getSelectionEx()
        shapes = [shape for s in selections for shape in s.SubObjects]
        if not shapes:
            shapes = [s.Object.Shape for s in selections if hasattr(s.Object, "Shape")]
        if len(shapes) >= 2:
            self.notify(f"Minimum distance: {geometry.distance(shapes[0], shapes[1]):.4f} mm")
        elif shapes:
            shape = shapes[0]
            if shape.ShapeType == "Edge":
                self.notify(f"Edge length: {geometry.scalar(shape, 'length'):.4f} mm")
            elif shape.ShapeType == "Face":
                self.notify(f"Face area: {geometry.scalar(shape, 'area'):.4f} mm²")
            else:
                self.notify(f"Volume: {geometry.scalar(shape, 'volume'):.4f} mm³ · area: {geometry.scalar(shape, 'area'):.4f} mm²")
        else:
            doc, body = self.document(), self.active_body()
            if not doc or not body:
                self.notify("Select an edge, face, part, or two shapes to measure.")
                return
            body_name, body_label = body.Name, body.Label
            state = self.core.inspect(doc, measure="full")
            entry = next((entry for entry in state["bodies"] if entry["id"] == body_name), None)
            measured = (entry or {}).get("measurements") or (entry or {}).get("retained_geometry_measurements")
            if not measured or measured.get("volume_mm3") is None or measured.get("center_of_mass_mm") is None:
                self.notify("The active part has no solid to measure.")
                return
            center = measured["center_of_mass_mm"]
            self.notify(f"{body_label} · volume: {measured['volume_mm3']:.4f} mm³ · area: {measured['area_mm2']:.4f} mm²"
                        + " · centre of mass: " + ", ".join(f"{value:.4f}" for value in center) + " mm")

    def view_step(self, axis, degrees=15, pan=False):
        if not Gui.activeDocument():
            return
        view = Gui.activeDocument().activeView()
        camera = view.getCameraOrientation()
        if pan:
            node = view.getCameraNode()
            if hasattr(node, "height"):
                span = float(node.height.getValue())
            else:
                import math
                span = float(node.focalDistance.getValue()) * 2 * math.tan(float(node.heightAngle.getValue()) / 2)
            offset = camera.multVec(App.Vector(*axis)) * (span * .06)
            pos = node.position.getValue().getValue()
            node.position.setValue(pos[0] + offset.x, pos[1] + offset.y, pos[2] + offset.z)
        else:
            view.setCameraOrientation((camera * App.Rotation(App.Vector(*axis), degrees)).Q)

    def isolate(self):
        selected = {o.Name for o in Gui.Selection.getSelection()}
        if not selected or not self.document():
            self.notify("Select a part or feature to isolate.")
            return
        if getattr(self, "isolated_visibility", None):
            for key, visible in self.isolated_visibility.items():
                obj = self.document().getObject(key)
                if obj:
                    obj.ViewObject.Visibility = visible
            self.isolated_visibility = None
        else:
            self.isolated_visibility = {}
            for obj in self.document().Objects:
                if obj.TypeId.startswith(("Sketcher::", "PartDesign::")) and obj.TypeId != "PartDesign::Body":
                    self.isolated_visibility[obj.Name] = obj.ViewObject.Visibility
                    obj.ViewObject.Visibility = obj.Name in selected
        self.refresh()

    def transparent(self):
        for obj in Gui.Selection.getSelection():
            if hasattr(obj.ViewObject, "Transparency"):
                obj.ViewObject.Transparency = 0 if obj.ViewObject.Transparency else 75

    def shortcut_callbacks(self):
        callbacks = {
            "local.new": self.new, "local.open": self.open, "local.save": self.save,
            "sketch.start": self.start_sketch, "feature.extrude": lambda: self.extrude(False),
            "feature.revolve": lambda: self.studio_from_sketch("revolve"),
            "feature.fillet": lambda: self.studio_tool("fillet"),
            "history.rollback_up": lambda: self.move_rollback(-1),
            "history.rollback_down": lambda: self.move_rollback(1),
            "general.cancel": self.cancel_task, "general.accept": lambda: self.accept_task() if self.task or self.studio_dialog else False,
            "general.accept_repeat": self.accept_repeat,
            "general.undo": lambda: self.history_move("undo"), "general.redo": lambda: self.history_move("redo"),
            "general.delete": self.delete_selected, "general.delete_backspace": self.delete_selected,
            "general.rename": self.rename_selected, "general.measure": self.measure,
            "general.clear_selection": Gui.Selection.clearSelection,
            "general.tabs": lambda: Gui.runCommand("Std_Windows"), "general.tab_manager": lambda: Gui.runCommand("Std_Windows"),
            "view.normal": self.normal, "view.planes": self.toggle_planes, "view.sketches": self.toggle_sketches,
            "view.hide": self.hide_selected, "view.show_hidden": self.show_hidden,
            "view.isolate": self.isolate, "view.transparent": self.transparent,
        }
        rotations = {"left": (0, 1, 0), "right": (0, -1, 0), "up": (1, 0, 0), "down": (-1, 0, 0)}
        pans = {"left": (-1, 0, 0), "right": (1, 0, 0), "up": (0, 1, 0), "down": (0, -1, 0)}
        for direction in rotations:
            for degrees in [5, 15, 90]:
                callbacks[f"view.rotate_{direction}_{degrees}"] = lambda a=rotations[direction], d=degrees: self.view_step(a, d)
            callbacks[f"view.pan_{direction}"] = lambda a=pans[direction]: self.view_step(a, pan=True)
        callbacks.update(self.general_actions.callbacks())
        callbacks["sketch.pierce"] = self.pierce
        callbacks["sketch.project"] = self.project_selected_geometry
        callbacks.update({"assembly.insert": self.insert_assembly_part,
                          "assembly.fasten": lambda: self.assembly_joint("fixed"),
                          "assembly.mates": self.toggle_assembly_joints,
                          "assembly.show_mates": self.toggle_assembly_joints})
        callbacks.update(viewport_callbacks(self))
        return callbacks

    def eventFilter(self, watched, event):
        self.sketch_cursor.event(watched, event)
        self.sketch_snapping.event(watched, event)
        self.sketch_regions.event(watched, event)
        if self.sketch_references.event(watched, event):
            self.sketch_snapping.sync_tool(self.sketch_references.native_command_for_context())
            self.sketch_cursor.sync(self.sketch_references.native_command_for_context())
            return True
        if watched is self.rollback_bar and event.type() in {QtCore.QEvent.FocusIn, QtCore.QEvent.MouseButtonPress}:
            self.rollback_selected = True
        elif event.type() == QtCore.QEvent.MouseButtonPress:
            self.rollback_selected = False
        if event.type() == QtCore.QEvent.Show and isinstance(watched, QtGui.QDockWidget) and (watched.objectName() == "Report view" or watched.windowTitle() == "Report view"):
            # Native OutputWindow preferences may request this dock on any
            # report entry. Messages is the app's explicitly opened log view.
            watched.hide()
        if event.type() in {QtCore.QEvent.KeyPress, QtCore.QEvent.MouseButtonPress}:
            self.feedback_started = time.perf_counter()
            self.feedback_kind = "ordinary"
        if event.type() == QtCore.QEvent.MouseButtonRelease and self.active_sketch():
            self.core.record_edit_boundary(self.document())
            self.core.observer.state(self.document())["refresh"] = True
        if self.task_edit is not None and (
                watched is self.depth.native and event.type() in {QtCore.QEvent.MouseButtonPress, QtCore.QEvent.Wheel}
                or watched in {self.depth.native, self.depth.lineEdit()} and event.type() == QtCore.QEvent.KeyPress
                and event.key() in {QtCore.Qt.Key_Up, QtCore.Qt.Key_Down, QtCore.Qt.Key_PageUp, QtCore.Qt.Key_PageDown}):
            self.mark_depth_touched()
        if event.type() == QtCore.QEvent.KeyPress and event.key() in {QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter}:
            if watched is self.depth.lineEdit() and self.task:
                if event.modifiers() & QtCore.Qt.ShiftModifier:
                    self.accept_repeat()
                else:
                    self.accept_task()
                return True
            if watched is self.value.lineEdit() and not self.active_sketch():
                self.apply_parameter()
                return True
            if watched is self.formula:
                if self.task_edit is not None:
                    self.accept_task()
                else:
                    self.apply_parameter()
                return True
        if watched is self.main and event.type() == QtCore.QEvent.Close and (self.active_sketch() or (self.state or {}).get("active_sketch_edit")):
            if not self.finish_sketch():
                event.ignore()
                return True
        return False

    def shutdown(self):
        self._step_export_closed = True
        self._cancel_step_export()
        self._geometry_check_closed = True
        self._cancel_geometry_check()
        self.sketch_cursor.close()
        self.sketch_snapping.restore()
        self.responsiveness.close()
        self.sketch_plane_editor.close()
        self.sketch_colors.close()
        self.sketch_regions.close()
        self.sketch_history.close()
        self.history_controller.close()
        self.sketch_references.close()
        self.toolbar_labels.close()
        self.status_timer.stop()
        self.timer.stop()
        self.recovery_timer.stop()
        if self.studio_dialog:
            self.studio_dialog.reject()
        self.extrusion_preview.close()
        self.workspace_preferences.close()
        QtGui.QApplication.instance().removeEventFilter(self)
        self.router.uninstall()
        self.general_actions.close()
        for document, changed in self.report_connections:
            document.contentsChange.disconnect(changed)
        self.report_connections.clear()
        Gui.Selection.removeObserver(self.observer)
        self.bridge.close()
        self.core.close()

def start():
    main = Gui.getMainWindow()
    preferences = App.ParamGet("User parameter:BaseApp/Preferences/Document")
    preferences.SetBool("RecoveryEnabled", True)
    preferences.SetBool("AutoSaveEnabled", True)
    preferences.SetInt("AutoSaveTimeout", 1)
    App.saveParameter()
    Gui.activateWorkbench("PartDesignWorkbench")
    apply_theme(main)
    from .startup import maximize_on_primary_screen
    maximize_on_primary_screen(main)
    panel = Panel(Controller())
    main.addDockWidget(QtCore.Qt.LeftDockWidgetArea, panel)
    main.resizeDocks([panel], [250], QtCore.Qt.Horizontal)
    panel.show()
    hide_native_panels()
    Gui.kurtshape_panel = panel
    main.destroyed.connect(panel.shutdown)
    demo = ROOT / "examples" / "acceptance-plate.FCStd"
    if demo.exists() and os.environ.get("KURTSHAPE_DEMO"):
        panel.operation("open", path=str(demo))
        panel.isometric()
        panel.fit()
    else:
        panel.new()
    navigation.apply_navigation()
    for area in main.findChildren(QtGui.QMdiArea):
        for sub in area.subWindowList():
            if sub.windowTitle() in {"Start", "Start page"}:
                sub.close()
    return panel
