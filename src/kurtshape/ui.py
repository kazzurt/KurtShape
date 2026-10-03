"""Onshape-style desktop organization around one native FreeCAD document."""
from __future__ import annotations
import os
import time
from pathlib import Path
import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui
from .core import Controller, ROOT, METADATA
from .bridge import Bridge
from . import navigation
from .shortcuts import ShortcutRouter
from .general_actions import GeneralActions
from .viewport_actions import callbacks as viewport_callbacks
from .theme import apply_theme
from .feature_tools import available_catalog
from .quantity_field import QuantityField
from .bodies import bodies, owner, origin_plane, results as native_results

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
        if p.pending_sketch and not p.selecting_support:
            obj = App.getDocument(document).getObject(object_name)
            if obj and (obj.TypeId in {"App::Plane", "PartDesign::Plane"} or subelement.startswith("Face")):
                p.selecting_support = True
                QtCore.QTimer.singleShot(0, lambda: p.choose_support(document, object_name, subelement))

class Panel(QtGui.QDockWidget):
    def __init__(self, controller):
        super().__init__("Feature history")
        self.setObjectName("KurtShapeHistory")
        self.setFeatures(QtGui.QDockWidget.NoDockWidgetFeatures)
        self.setMinimumWidth(235)
        self.setMaximumWidth(430)
        self.core, self.state = controller, None
        self.pending_sketch = self.selecting_support = self.refreshing = False
        self.plane_visibility, self.items = {}, {}
        self.task = self.task_profile = self.last_document = self.last_status = None
        self.finishing_sketch = False
        self.entering_sketch = False
        self.placement_document = self.task_document = None
        self.workspace_modes = {}
        self.workspace_documents = {}
        self.workspace_mode = "part_studio"
        self.main = Gui.getMainWindow()
        self.main.installEventFilter(self)
        self.main.menuBar().hide()
        self.main.statusBar().show()
        self.make_history()
        self.make_editor()
        self.model_actions = []
        self.tool_menus = {}
        self.make_toolbars()
        self.make_messages()
        self.observer = SelectionObserver(self)
        Gui.Selection.addObserver(self.observer)
        self.general_actions = GeneralActions(self)
        self.router = ShortcutRouter(QtGui.QApplication.instance(), self.shortcut_callbacks(), self.context,
                                     self.notify, native_runner=self.native_command)
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
        QtGui.QApplication.instance().installEventFilter(self)

    def make_history(self):
        container = QtGui.QWidget()
        layout = QtGui.QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.filter = QtGui.QLineEdit()
        self.filter.setPlaceholderText("Filter features")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self.filter_features)
        layout.addWidget(self.filter)
        self.features_title = QtGui.QLabel("Features")
        self.features_title.setObjectName("SectionTitle")
        layout.addWidget(self.features_title)
        self.features = QtGui.QTreeWidget()
        self.features.setHeaderHidden(True)
        self.features.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.features.customContextMenuRequested.connect(self.history_menu)
        self.features.currentItemChanged.connect(self.history_selection)
        self.features.itemClicked.connect(self.history_click)
        self.features.itemDoubleClicked.connect(self.history_double_click)
        layout.addWidget(self.features, 1)
        self.parts_title = QtGui.QLabel("Parts (0)")
        self.parts_title.setObjectName("SectionTitle")
        layout.addWidget(self.parts_title)
        self.body_choice = QtGui.QComboBox()
        self.body_choice.setToolTip("Body for new sketches and native features")
        self.body_choice.currentIndexChanged.connect(self.change_body)
        layout.addWidget(self.body_choice)
        self.parts = QtGui.QTreeWidget()
        self.parts.setHeaderHidden(True)
        self.parts.setMaximumHeight(145)
        self.parts.setMinimumHeight(58)
        self.parts.itemClicked.connect(self.part_selection)
        layout.addWidget(self.parts)
        self.status = QtGui.QLabel("Create or open a part studio")
        self.status.setWordWrap(True)
        self.status.setMargin(9)
        self.status.setStyleSheet("color:#586679; border-top:1px solid #d1d8e1")
        layout.addWidget(self.status)
        self.setWidget(container)

    def make_editor(self):
        self.editor = QtGui.QDockWidget("Feature settings", self.main)
        self.editor.setObjectName("KurtShapeEditor")
        self.editor.setFeatures(QtGui.QDockWidget.DockWidgetClosable)
        self.editor.setMinimumWidth(265)
        self.editor.setMaximumWidth(420)
        widget = QtGui.QWidget()
        layout = QtGui.QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        self.editor_title = QtGui.QLabel("Select a feature")
        self.editor_title.setStyleSheet("font-size:15px;font-weight:600")
        layout.addWidget(self.editor_title)
        self.editor_help = QtGui.QLabel("")
        self.editor_help.setWordWrap(True)
        layout.addWidget(self.editor_help)
        self.form = QtGui.QFormLayout()
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
        self.end_type.addItems(["Blind", "Through all"])
        self.end_type.currentIndexChanged.connect(lambda: self.depth.setEnabled(self.end_type.currentIndex() == 0))
        self.reverse = QtGui.QCheckBox("Reverse direction")
        self.formula = QtGui.QLineEdit()
        self.formula.setPlaceholderText("Example: Plate.Constraints.Width / 2")
        self.formula.installEventFilter(self)
        self.depth.lineEdit().installEventFilter(self)
        self.value.lineEdit().installEventFilter(self)
        for label, control in [("Dimension", self.parameter), ("Value", self.value), ("Formula", self.formula), ("End condition", self.end_type), ("Depth", self.depth), ("", self.reverse)]:
            self.form.addRow(label, control)
        layout.addLayout(self.form)
        self.apply = QtGui.QPushButton("Apply dimension")
        self.apply.clicked.connect(self.apply_parameter)
        layout.addWidget(self.apply)
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
        self.task_buttons = QtGui.QWidget()
        row = QtGui.QHBoxLayout(self.task_buttons)
        row.setContentsMargins(0, 8, 0, 0)
        self.confirm = QtGui.QPushButton("Confirm")
        self.confirm.setObjectName("Confirm")
        self.confirm.clicked.connect(self.accept_task)
        self.cancel = QtGui.QPushButton("Cancel")
        self.cancel.setObjectName("Cancel")
        self.cancel.clicked.connect(lambda: self.finish_sketch(cancel=True) if self.active_sketch() else self.cancel_task())
        row.addWidget(self.confirm)
        row.addWidget(self.cancel)
        layout.addWidget(self.task_buttons)
        layout.addStretch()
        self.editor.setWidget(widget)
        self.main.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.editor)
        self.editor.hide()
        self.configure_editor(None)

    def tool_icon(self, icon, command=None):
        result = QtGui.QIcon()
        if command:
            try:
                info = Gui.Command.get(command).getInfo()
                if info.get("pixmap"):
                    return Gui.getIcon(info["pixmap"])
            except Exception:
                pass
        if icon:
            result = QtGui.QIcon(icon) if str(icon).startswith(":/") else Gui.getIcon(icon)
        return result

    def tool(self, bar, text, callback, tip="", icon=None, modeling=False, command=None):
        action = QtGui.QAction(self.tool_icon(icon, command), text, self)
        action.setObjectName("KurtShapeTool_" + text.replace(" ", "_"))
        action.setToolTip(tip or text)
        action.setStatusTip(tip or text)
        action.triggered.connect(lambda checked=False: callback())
        bar.addAction(action)
        if modeling:
            self.model_actions.append(action)
        if action.icon().isNull():
            bar.widgetForAction(action).setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
        return action

    def tool_menu(self, bar, label, tools, modeling=False):
        menu = QtGui.QMenu(label, self.main)
        for native in tools:
            action = QtGui.QAction(self.tool_icon(native.icon, native.command), native.label, menu)
            action.setData(native.command)
            action.setToolTip(native.tip)
            action.setStatusTip(native.tip)
            action.triggered.connect(lambda checked=False, tool=native: self.native_command(tool.command, tool.workbench))
            menu.addAction(action)
            if modeling:
                self.model_actions.append(action)
        action = menu.menuAction()
        bar.addAction(action)
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
        button.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)

    def make_toolbars(self):
        self.catalog = available_catalog()
        self.catalog_model_commands = {tool.command for tool in self.catalog["all"] if tool.workbench != "SketcherWorkbench"}
        self.document_bar = QtGui.QToolBar("Document", self.main)
        self.document_bar.setObjectName("KurtShapeDocumentBar")
        self.document_bar.setMovable(False)
        self.document_bar.setIconSize(QtCore.QSize(20, 20))
        logo = QtGui.QLabel("  KurtShape  ")
        logo.setStyleSheet("font-size:17px;font-weight:700;color:#1c5fa8;padding-right:8px")
        self.document_bar.addWidget(logo)
        self.document_name = QtGui.QLabel("New part studio")
        self.document_name.setStyleSheet("font-weight:600;padding:0 14px")
        self.document_name.setMinimumWidth(160)
        self.document_bar.addWidget(self.document_name)
        self.mode_choice = QtGui.QComboBox()
        self.mode_choice.setObjectName("KurtShapeWorkspaceMode")
        self.mode_choice.addItem("Part Studio", "part_studio")
        self.mode_choice.addItem("Assembly", "assembly")
        self.mode_choice.setToolTip("Return to an open Part Studio or Assembly; a new Part Studio opens if none is available")
        self.mode_choice.currentIndexChanged.connect(lambda: self.set_workspace_mode(self.mode_choice.currentData()))
        self.document_bar.addWidget(self.mode_choice)
        for name, callback, tip in [("New", self.new, "New part studio · Ctrl+N"), ("Open", self.open, "Open FCStd or import STEP / STP · Ctrl+O"), ("Save", self.save, "Save project · Ctrl+S"), ("Export", self.export, "Export current solid · STEP / STL")]:
            self.tool(self.document_bar, name, callback, tip)
        recent = QtGui.QMenu("Recent projects", self.main)
        recent.aboutToShow.connect(lambda: self.fill_recent(recent))
        action = recent.menuAction()
        action.setText("Recent")
        self.document_bar.addAction(action)
        self.bind_tool_menu(self.document_bar.widgetForAction(action), recent)
        self.tool(self.document_bar, "Example", lambda: self.operation("open", path=str(ROOT / "examples" / "acceptance-plate.FCStd")), "Open the development example")
        self.tool(self.document_bar, "Adopt copy", self.adopt, "Create a managed copy of an inspected native file")
        recovery_menu = QtGui.QMenu("Recovery", self.main)
        recovery_menu.aboutToShow.connect(lambda: self.fill_recovery(recovery_menu))
        self.document_bar.addAction(recovery_menu.menuAction())
        self.bind_tool_menu(self.document_bar.widgetForAction(recovery_menu.menuAction()), recovery_menu)
        self.document_bar.addSeparator()
        self.tool(self.document_bar, "Undo", lambda: self.history_move("undo"), "Undo · Ctrl+Z", ":/icons/edit-undo.svg")
        self.tool(self.document_bar, "Redo", lambda: self.history_move("redo"), "Redo · Ctrl+Y", ":/icons/edit-redo.svg")
        spacer = QtGui.QWidget()
        spacer.setSizePolicy(QtGui.QSizePolicy.Expanding, QtGui.QSizePolicy.Preferred)
        self.document_bar.addWidget(spacer)
        self.tool(self.document_bar, "Search", lambda: self.router.show_search(self.main), "Search commands · Alt+C")
        self.tool(self.document_bar, "Shortcuts", lambda: self.router.show_help(self.main), "Keyboard shortcuts · Shift+/")
        self.main.addToolBar(QtCore.Qt.TopToolBarArea, self.document_bar)
        self.main.addToolBarBreak(QtCore.Qt.TopToolBarArea)
        self.model_bar = QtGui.QToolBar("Part Studio", self.main)
        self.model_bar.setObjectName("KurtShapeModelBar")
        self.model_bar.setMovable(False)
        self.model_bar.setIconSize(QtCore.QSize(24, 24))
        self.model_bar.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        self.tool(self.model_bar, "New Body", lambda: self.operation("create_body", id=self.unique("Body")), "Add a native Body", modeling=True)
        for name, callback, tip, icon in [
            ("Sketch", self.start_sketch, "Create sketch · Shift+S", "Sketcher_NewSketch"),
            ("Extrude", lambda: self.extrude(False), "Extrude sketch · Shift+E", "PartDesign_Pad"),
            ("Remove", lambda: self.extrude(True), "Remove material with a sketch", "PartDesign_Pocket")]:
            self.tool(self.model_bar, name, callback, tip, ":/icons/" + icon + ".svg", modeling=True, command=icon)
        self.model_bar.addSeparator()
        for native in self.catalog["primary"]:
            label = "Pattern" if native.key == "linear_pattern" else native.label
            self.tool(self.model_bar, label, lambda tool=native: self.native_command(tool.command, tool.workbench),
                      native.tip, native.icon, modeling=True, command=native.command)
        self.model_bar.addSeparator()
        group_labels = {"Add material":"Build", "Remove material":"Cut", "Modify":"Modify", "Pattern":"Patterns", "Reference":"Reference", "Part tools":"Shape tools"}
        for category, tools in self.catalog["groups"]:
            self.tool_menu(self.model_bar, group_labels[category], tools, modeling=True)
        self.model_bar.addSeparator()
        for name, callback, tip, icon in [("Rebuild", lambda: self.operation("rebuild"), "Recompute native model", "Std_Refresh"), ("Fit", self.fit, "Fit · F", "Std_ViewFitAll"), ("Normal", self.normal, "Normal · N", "Std_ViewTop"), ("3D", self.isometric, "Isometric · Shift+7", "Std_ViewIsometric"), ("Planes", self.toggle_planes, "Show / hide planes · P", "PartDesign_Plane")]:
            self.tool(self.model_bar, name, callback, tip, icon, modeling=name == "Rebuild", command=icon)
        self.main.addToolBar(QtCore.Qt.TopToolBarArea, self.model_bar)
        self.assembly_actions = []
        self.assembly_bar = QtGui.QToolBar("Assembly", self.main)
        self.assembly_bar.setObjectName("KurtShapeAssemblyBar")
        self.assembly_bar.setMovable(False)
        self.assembly_bar.setIconSize(QtCore.QSize(24, 24))
        for label, callback, tip in [
            ("Create Assembly", self.create_assembly, "Create one assembly in this project"),
            ("Insert", self.insert_assembly_part, "Insert a saved FCStd part · I"),
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
        self.main.addToolBar(QtCore.Qt.TopToolBarArea, self.assembly_bar)
        self.assembly_bar.hide()
        self.sketch_bar = QtGui.QToolBar("Sketch", self.main)
        self.sketch_bar.setObjectName("KurtShapeSketchBar")
        self.sketch_bar.setMovable(False)
        self.sketch_bar.setIconSize(QtCore.QSize(24, 24))
        self.sketch_bar.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        for name, command, key in [("Line", "Sketcher_CreateLine", "L"), ("Rectangle", "Sketcher_CreateRectangle", "G"), ("Circle", "Sketcher_CreateCircle", "C"), ("Arc", "Sketcher_Create3PointArc", "A"), ("Spline", "Sketcher_CreateBSpline", ""), ("Point", "Sketcher_CreatePoint", "Shift+S"), ("Dimension", "Sketcher_Dimension", "D"), ("Trim", "Sketcher_Trimming", "M"), ("Construction", "Sketcher_ToggleConstruction", "Q")]:
            self.tool(self.sketch_bar, name, lambda c=command: self.native_command(c), name + (" · " + key if key else ""), ":/icons/" + command + ".svg", command=command)
        self.sketch_bar.addSeparator()
        for category, tools in self.catalog["sketch_groups"]:
            self.tool_menu(self.sketch_bar, category, tools)
        self.tool(self.sketch_bar, "Pierce", self.pierce, "Select a sketch point and crossing curve · Shift+G")
        self.sketch_bar.addSeparator()
        self.tool(self.sketch_bar, "Extrude", lambda: self.extrude(False), "Finish this sketch and extrude · Shift+E", "PartDesign_Pad")
        self.tool(self.sketch_bar, "Revolve", lambda: self.feature_from_sketch("PartDesign_Revolution"), "Finish this sketch and revolve", "PartDesign_Revolution")
        self.sketch_bar.addSeparator()
        self.tool(self.sketch_bar, "Normal", self.normal, "Normal to sketch · N")
        self.tool(self.sketch_bar, "3D", self.isometric, "Sketch in 3D · Shift+7")
        finish = self.tool(self.sketch_bar, "Finish sketch", self.finish_sketch, "Commit changes", ":/icons/dialog-ok.svg")
        self.sketch_bar.widgetForAction(finish).setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.sketch_cancel_action = self.tool(self.sketch_bar, "Cancel sketch", lambda: self.finish_sketch(cancel=True), "Discard this edit session", ":/icons/dialog-cancel.svg")
        self.sketch_bar.widgetForAction(self.sketch_cancel_action).setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.main.addToolBar(QtCore.Qt.TopToolBarArea, self.sketch_bar)
        self.sketch_bar.hide()
        self.message = QtGui.QLabel("Ready · Middle drag: orbit · Ctrl+middle: pan · Shift+middle: zoom")
        self.main.statusBar().insertPermanentWidget(0, self.message, 1)

    def notify(self, message, *args):
        self.feedback_complete()
        self.message.setStyleSheet("color:#a2322c" if args and args[0] == "error" else "color:#405267")
        self.message.setText(str(message))
        self.message.setToolTip(str(message))
        if args and args[0] == "error" and hasattr(self, "messages"):
            self.messages.appendPlainText(str(message))
            self.messages_dock.show()

    def make_messages(self):
        self.messages_dock = QtGui.QDockWidget("Messages", self.main)
        self.messages_dock.setObjectName("KurtShapeMessages")
        self.messages = QtGui.QPlainTextEdit()
        self.messages.setReadOnly(True)
        self.messages.setMaximumBlockCount(200)
        self.messages_dock.setWidget(self.messages)
        self.main.addDockWidget(QtCore.Qt.BottomDockWidgetArea, self.messages_dock)
        self.messages_dock.hide()
        self.report_connections = []
        for dock in self.main.findChildren(QtGui.QDockWidget):
            if dock.objectName() == "Report view" or dock.windowTitle() == "Report view":
                for widget in dock.findChildren(QtGui.QTextEdit) + dock.findChildren(QtGui.QPlainTextEdit):
                    previous = [widget.toPlainText()]
                    def changed(w=widget, seen=previous):
                        text = w.toPlainText()
                        added = text[len(seen[0]):] if text.startswith(seen[0]) else text
                        seen[0] = text
                        if added.strip():
                            self.notify(added.strip(), "error")
                    widget.textChanged.connect(changed)
                    self.report_connections.append((widget, changed))

    def context(self):
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
            self.notify("Create Assembly, then insert parts from saved FCStd projects. Import STEP through Open and save it as FCStd first.")
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
            self.notify("Adopt a copy before editing this native reference.", "error")
            return False
        response = self.core.dispatch({"op": "inspect", "document_id": self.core.identifier(self.document())})
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
            current = self.core.inspect(self.document())
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
            path = QtGui.QFileDialog.getOpenFileName(self, "Insert saved part into assembly", self.core.settings.last_directory,
                "FreeCAD project (*.FCStd *.fcstd *.FCSTD)")[0]
        if not path:
            return None
        response = self.core.dispatch({"op": "assembly_candidates", "path": str(path)})
        if not response["ok"]:
            self.notify(response["error"]["message"], "error")
            return None
        candidates = response["result"].get("candidates", [])
        if not candidates:
            self.notify("This FCStd has no eligible Body or solid. Import STEP through Open, save FCStd, then insert it.", "error")
            return None
        if source_id is None:
            dialog = QtGui.QDialog(self.main)
            dialog.setObjectName("KurtShapeAssemblyInsertDialog")
            dialog.setWindowTitle("Insert part")
            layout = QtGui.QVBoxLayout(dialog)
            help_text = QtGui.QLabel("Choose the Body or solid to embed. Repeat Insert for another independent instance. STEP parts: Open STEP, save FCStd, then choose that project here.")
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
        return selected or (bodies(doc)[0] if doc and len(bodies(doc)) == 1 else None)

    def plane(self, doc, plane):
        return native_plane(doc, plane, self.active_body())

    def change_body(self, *args):
        if not self.refreshing and self.state:
            body = self.active_body()
            if body and Gui.activeDocument():
                Gui.activeDocument().activeView().setActiveObject("pdbody", body)
            self.refresh()

    def maximize_document_view(self):
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
        for identifier in list(self.core.sketch_edits):
            owner = self.core.documents.get(identifier)
            if owner and self.core._is_open(owner) and (doc is None or doc.Name != owner.Name) and not self.finishing_sketch:
                App.setActiveDocument(owner.Name)
                doc = owner
                self.notify("Finish or cancel the active sketch before switching documents.")
        if (self.task_document and (not doc or doc.Name != self.task_document)) or (self.placement_document and (not doc or doc.Name != self.placement_document)):
            self.cancel_task()
        if doc and any(self.core._is_open(d) and d.Name == doc.Name for d in self.core.documents.values()):
            if not processed and not self.core.needs_refresh(doc) and self.last_document == doc.Name:
                if self.state.get("active_sketch_edit") and not self.active_sketch() and not self.finishing_sketch and not self.entering_sketch:
                    self.finish_sketch()
                return
            previous = (self.state or {}).get("revision")
            result = self.core.dispatch({"op": "inspect", "document_id": self.core.identifier(doc)})
            if result["ok"]:
                self.state = result["result"]
                if previous != self.state["revision"] and self.feedback_started is not None:
                    self.feedback_kind = "model"
                if processed or previous != self.state["revision"] or self.last_document != doc.Name or self.last_status != self.state["build_status"]:
                    self.refresh()
                if self.last_document != doc.Name:
                    self.maximize_document_view()
                self.last_document, self.last_status = doc.Name, self.state["build_status"]
                self.core.observer.state(doc)["refresh"] = False
                if self.state.get("active_sketch_edit") and not self.active_sketch() and not self.finishing_sketch and not self.entering_sketch:
                    self.finish_sketch()
                self.sync_edit_ui()
        elif self.state is not None:
            self.cancel_placement()
            self.state = None
            self.features.clear()
            self.parts.clear()
            self.items.clear()
            self.parameter.clear()
            self.status.setText("Create or open a part studio")
            self.document_name.setText("New part studio")
            self.editor.hide()
            self.sync_edit_ui()

    def operation(self, op, **args):
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
        if op in self.core.CREATE_OPS:
            self.cancel_task()
        if op not in self.core.CREATE_OPS:
            doc = self.document()
            if not doc or not self.state:
                self.notify("Create or open a project first.", "error")
                return None
            response = self.core.dispatch({"op": "inspect", "document_id": self.core.identifier(doc)})
            if not response["ok"]:
                self.notify(response["error"]["message"], "error")
                return None
            self.state = response["result"]
            if staged_document and staged_document != self.state["document_id"]:
                self.notify("Assembly command canceled because its source project is no longer active.", "error")
                return None
            args.update(document_id=self.state["document_id"], expected_revision=staged_revision or self.state["revision"])
            if op in self.core.MODEL_OPS - {"create_body", "rebuild"} and "body" not in args:
                target = doc.getObject(args.get("feature") or args.get("profile") or args.get("sketch") or args.get("support", {}).get("feature") or "")
                body = owner(doc, target) or self.active_body()
                if body:
                    args["body"] = body.Name
        response = self.core.dispatch({"op": op, **args})
        if not response["ok"]:
            if self.document() and self.state:
                self.state = self.core.inspect(self.document())
            if self.active_sketch() and self.core.identifier(self.document()) not in self.core.sketch_edits:
                Gui.activeDocument().resetEdit()
                self.sync_edit_ui()
            self.notify(response["error"]["message"], "error")
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
        self.notify(op.replace("_", " ").capitalize() + " complete")
        if op == "import_step":
            count = self.state["measurements"]["solid_count"] if self.state["measurements"] else 0
            self.notify(f"STEP imported · {count} solids · geometry only. Save as FCStd to keep your project.")
        if op in {"create_assembly", "insert_assembly_part", "ground_assembly_instance", "create_assembly_joint", "edit_assembly_joint", "move_assembly_joint", "move_assembly_instance", "delete_assembly_object", "solve_assembly"}:
            assembly = self.assembly_state()
            self.notify("Assembly " + str(assembly.get("solver_status", "updated")) + " · " + str(len(assembly.get("instances", []))) + " instances · " + str(len(assembly.get("joints", []))) + " joints")
        if op == "recover" and self.state.get("active_sketch_edit"):
            Gui.activeDocument().setEdit(self.state["active_sketch_edit"])
            self.sync_edit_ui()
        return self.state

    def refresh(self):
        if not self.state:
            return
        doc, selected = self.document(), self.selected()
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
            self.refresh_assembly(selected)
            return
        self.body_choice.show()
        self.filter.setPlaceholderText("Filter features")
        expanded = {key for key, item in self.items.items() if item.isExpanded()}
        if not self.items:
            expanded.add("origin")
        self.refreshing = True
        previous_body = self.body_choice.currentData()
        self.body_choice.blockSignals(True)
        self.body_choice.clear()
        for body in bodies(doc):
            self.body_choice.addItem(body.Label, body.Name)
        if previous_body:
            self.body_choice.setCurrentIndex(max(0, self.body_choice.findData(previous_body)))
        self.body_choice.blockSignals(False)
        self.features.blockSignals(True)
        self.features.clear()
        self.items = {}
        origin = QtGui.QTreeWidgetItem(["Origin"])
        origin.setData(0, QtCore.Qt.UserRole, "origin")
        self.features.addTopLevelItem(origin)
        self.items["origin"] = origin
        for name, plane in [("Top", "XY"), ("Front", "XZ"), ("Right", "YZ")]:
            obj = self.plane(doc, plane)
            item = QtGui.QTreeWidgetItem(origin, [name])
            item.setData(0, QtCore.Qt.UserRole, "plane:" + plane)
            if obj:
                item.setIcon(0, obj.ViewObject.Icon)
            item.setToolTip(0, name + " (" + plane + ") · select after Shift+S to start a sketch")
            self.items["plane:" + plane] = item
        features = [f for f in self.state["features"] if f["type"] not in {"PartDesign::Body", "App::Point"}]
        for feature in features:
            obj = doc.getObject(feature["id"])
            failed = any(flag in feature["state"] for flag in ["Invalid", "Error"])
            item = QtGui.QTreeWidgetItem([feature["name"] + ("  !" if failed else "")])
            item.setData(0, QtCore.Qt.UserRole, feature["id"])
            if obj and hasattr(obj, "ViewObject"):
                item.setIcon(0, obj.ViewObject.Icon)
            item.setToolTip(0, feature["type"].split("::")[-1] + " · " + feature["id"])
            if failed or (obj and not obj.ViewObject.Visibility):
                item.setForeground(0, QtGui.QBrush(QtGui.QColor("#a2322c" if failed else "#748292")))
            self.features.addTopLevelItem(item)
            self.items[feature["id"]] = item
        for key in expanded:
            if key in self.items:
                self.items[key].setExpanded(True)
        if selected in self.items:
            self.features.setCurrentItem(self.items[selected])
        self.features.blockSignals(False)
        self.refreshing = False
        self.features_title.setText(f"Features ({len(features)})")
        self.filter_features()
        self.parts.clear()
        count = 0
        for body in native_results(doc):
            solids = body.Shape.Solids if not body.Shape.isNull() else []
            count += len(solids)
            for i, solid in enumerate(solids):
                item = QtGui.QTreeWidgetItem([body.Label if len(solids) == 1 else f"{body.Label} · solid {i + 1}"])
                item.setData(0, QtCore.Qt.UserRole, body.Name)
                item.setIcon(0, body.ViewObject.Icon)
                self.parts.addTopLevelItem(item)
        self.parts_title.setText(f"Parts ({count})")
        geometry = self.state["measurements"]
        detail = "Rebuild required · retained geometry" if self.state["build_status"] in {"failed", "needs_rebuild"} else (f"{geometry['solid_count']} solid · {geometry['volume_mm3']:,.2f} mm³" if geometry else "Sketches only · mm")
        if self.state.get("import_source"):
            detail = "Imported STEP · " + (detail if geometry or self.state["build_status"] in {"failed", "needs_rebuild"} else "Reference geometry only · mm")
        self.status.setText(detail)
        if not self.state.get("managed", True):
            self.status.setText("Native reference · inspect or adopt a copy · " + detail)
        self.document_name.setText(self.state["name"])
        self.main.setWindowTitle(self.state["name"] + " — KurtShape")
        if not self.task and not self.active_sketch():
            self.parameters()
        self.feedback_complete()

    def refresh_assembly(self, selected=None):
        assembly = self.assembly_state()
        doc = self.document()
        self.refreshing = True
        self.body_choice.hide()
        self.filter.setPlaceholderText("Filter instances and joints")
        self.features.blockSignals(True)
        self.features.clear()
        self.items = {}
        for category, label in (("instances", "Instances"), ("joints", "Joints")):
            group = QtGui.QTreeWidgetItem([label + " (" + str(len(assembly.get(category, []))) + ")"])
            group.setData(0, QtCore.Qt.UserRole, "assembly_group:" + category)
            self.features.addTopLevelItem(group)
            group.setExpanded(True)
            for entry in assembly.get(category, []):
                suffix = " · grounded" if entry.get("grounded") else (" · " + str(entry.get("joint_type", entry.get("type", "joint"))) if category == "joints" else "")
                if category == "joints" and entry.get("suppressed"):
                    suffix += " · suppressed"
                item = QtGui.QTreeWidgetItem(group, [entry["name"] + suffix])
                item.setData(0, QtCore.Qt.UserRole, entry["id"])
                obj = doc.getObject(entry["id"])
                if obj:
                    item.setIcon(0, obj.ViewObject.Icon)
                item.setToolTip(0, entry["id"] + (" · reference fixed in place" if entry.get("grounded") else ""))
                self.items[entry["id"]] = item
        if selected in self.items:
            self.features.setCurrentItem(self.items[selected])
        self.features.blockSignals(False)
        self.refreshing = False
        self.features_title.setText(assembly.get("name", "Assembly"))
        self.parts.clear()
        for entry in assembly.get("instances", []):
            item = QtGui.QTreeWidgetItem([entry["name"] + (" · grounded" if entry.get("grounded") else "")])
            item.setData(0, QtCore.Qt.UserRole, entry["id"])
            obj = doc.getObject(entry["id"])
            if obj:
                item.setIcon(0, obj.ViewObject.Icon)
            self.parts.addTopLevelItem(item)
        self.parts_title.setText("Instances (" + str(len(assembly.get("instances", []))) + ")")
        if not assembly:
            detail = "Create Assembly to begin. Insert saved FCStd parts, ground a reference, then connect native joints."
        elif self.state["build_status"] in {"failed", "needs_rebuild"}:
            detail = "Assembly unresolved · see Messages and solve before export"
        else:
            detail = "Assembly · " + str(len(assembly.get("instances", []))) + " instances · " + str(len(assembly.get("joints", []))) + " joints · " + str(assembly.get("solver_status", "solved"))
            if assembly.get("disconnected_count"):
                detail += " · " + str(assembly["disconnected_count"]) + " unconnected"
        self.status.setText(detail)
        self.document_name.setText(self.state["name"])
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
        item = self.features.currentItem()
        return item.data(0, QtCore.Qt.UserRole) if item else None

    def select_feature(self, key):
        if key in self.items:
            self.features.setCurrentItem(self.items[key])
            self.features.scrollToItem(self.items[key])

    def history_selection(self, *args):
        if not self.refreshing and not self.pending_sketch and not self.active_sketch():
            self.parameters()
        self.feedback_complete()

    def history_click(self, item, column=0):
        key = item.data(0, QtCore.Qt.UserRole)
        if key.startswith("plane:"):
            if self.pending_sketch:
                self.begin_sketch(plane=key.split(":")[1])
                return
            obj = self.plane(self.document(), key.split(":")[1])
        else:
            obj = self.document().getObject(key) if self.document() else None
        if obj and not self.active_sketch():
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(obj)
            if self.task and not self.task_profile and obj.TypeId == "Sketcher::SketchObject":
                self.task_profile = obj.Name
                self.editor_help.setText(obj.Label + " · native " + ("Pocket" if self.task == "pocket" else "Pad"))
                self.confirm.setEnabled(True)

    def history_double_click(self, item, column=0):
        key = item.data(0, QtCore.Qt.UserRole)
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
            else:
                self.parameters(show=True)

    def part_selection(self, item, column=0):
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.document().getObject(item.data(0, QtCore.Qt.UserRole)))

    def parameters(self, *args, show=False):
        if self.workspace_mode == "assembly":
            self.editor.hide()
            return
        feature = next((f for f in (self.state or {}).get("features", []) if f["id"] == self.selected()), None)
        if not feature or self.task or self.active_sketch():
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
        self.editor_help.setText(feature["type"].split("::")[-1] + " · native feature")
        self.configure_editor("parameters", feature["type"] == "Sketcher::SketchObject")
        self.parameter_value()
        if feature["parameters"] or show:
            self.editor.show()

    def configure_editor(self, mode, sketch=False):
        for control in [self.parameter, self.value, self.formula, self.depth, self.end_type, self.reverse]:
            visible = (mode == "parameters" and control in [self.parameter, self.value, self.formula]) or (mode == "extrude" and control in [self.depth, self.end_type, self.reverse])
            if control == self.end_type and self.task != "pocket":
                visible = False
            control.setVisible(visible)
            label = self.form.labelForField(control)
            if label:
                label.setVisible(visible)
        self.apply.setVisible(mode == "parameters" and self.parameter.count() > 0)
        self.clear_formula.setVisible(mode == "parameters" and self.parameter.count() > 0)
        self.edit_button.setVisible(mode == "parameters" and sketch)
        self.normal_button.setVisible(sketch)
        self.iso_button.setVisible(mode == "sketch")
        self.task_buttons.setVisible(mode in {"sketch", "placement", "extrude"})
        self.confirm.setVisible(mode != "placement")
        self.confirm.setEnabled(mode != "extrude" or bool(self.task_profile))
        self.confirm.setText("Finish sketch" if mode == "sketch" else "Confirm")

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
        if self.core.busy or self.native_feature_task_active():
            return
        for doc in list(self.core.documents.values()):
            if self.core._is_open(doc):
                try:
                    self.core.timings.measure("recovery_checkpoint", self.core.checkpoint, doc)
                except Exception as exc:
                    self.notify("Recovery checkpoint failed: " + str(exc), "error")

    def feedback_complete(self):
        started = getattr(self, "feedback_started", None)
        if started is not None:
            elapsed = (time.perf_counter() - started) * 1000
            if elapsed < 5000:
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

    def new(self):
        self.cancel_placement()
        if self.operation("new", name="Untitled part"):
            self.isometric()
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
            path = QtGui.QFileDialog.getSaveFileName(self, "Save native project", self.state.get("native_file") or str(Path(self.core.settings.last_directory) / filename), "FreeCAD project (*.FCStd)")[0]
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
        path = QtGui.QFileDialog.getSaveFileName(self, "Adopt a native copy", str(Path(self.core.settings.last_directory) / "adopted-part.FCStd"), "FreeCAD project (*.FCStd)")[0]
        if path:
            self.core.settings.grant_destination(path)
            return self.operation("adopt", path=path)

    def export(self):
        if not self.state:
            return
        if self.active_sketch() or self.native_feature_task_active():
            self.notify("Finish or cancel the current edit before exporting the solid.")
            return
        path = QtGui.QFileDialog.getSaveFileName(self, "Export current solid", str(Path(self.core.settings.last_directory) / "my-part.step"), "STEP (*.step);;STL (*.stl)")[0]
        if path:
            self.core.settings.grant_destination(path)
            self.operation("export", path=path)

    def start_sketch(self):
        if self.state and not self.state.get("managed", True):
            self.notify("Adopt a copy before editing this native reference.", "error")
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
                    return self.begin_sketch(support={"feature": selected.Object.Name, "subelement": sub})
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
        self.editor.show()
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
            support["subelement"] = subelement
        if not self.begin_sketch(support=support):
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
            navigation.allow_sketch_3d(obj, view)
            Gui.getDocument(obj.Document.Name).setEdit(obj.Name)
            navigation.allow_sketch_3d(obj, view, camera=camera)
            navigation.apply_navigation(view)
        except Exception as exc:
            self.operation("finish_sketch_edit", cancel=True)
            self.notify(str(exc), "error")
            return None
        finally:
            self.entering_sketch = False
        self.sync_edit_ui()
        self.notify("Sketch editing · middle drag orbits · N returns normal · G rectangle · C circle")
        return obj

    def finish_sketch(self, cancel=False):
        if not self.active_sketch() and not (self.state or {}).get("active_sketch_edit"):
            return None
        self.finishing_sketch = True
        try:
            if self.active_sketch():
                Gui.activeDocument().resetEdit()
            result = self.operation("finish_sketch_edit", cancel=bool(cancel))
            if not result:
                feature = (self.state or {}).get("active_sketch_edit")
                if feature and self.document().getObject(feature) and not self.active_sketch():
                    Gui.activeDocument().setEdit(feature)
        finally:
            self.finishing_sketch = False
        self.sync_edit_ui()
        hide_native_panels()
        if not result:
            self.messages_dock.show()
        return result

    def sync_edit_ui(self):
        sketch = self.active_sketch()
        native_task = self.native_feature_task_active()
        for action in self.document_bar.actions():
            if action.text() in {"New", "Open", "Save", "Export"}:
                action.setEnabled(not bool(sketch) and not native_task)
            elif action.text() in {"Undo", "Redo"}:
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
            self.editor_help.setText("Orbit to inspect this sketch in 3D. N returns normal. Finish commits changes; Cancel restores the sketch from before this edit.")
            self.configure_editor("sketch", True)
            self.editor.hide()
        elif native_task:
            self.editor.hide()

    def extrude(self, cut=False, choose_new=False):
        if self.native_feature_task_active():
            self.notify("Finish or cancel the current feature before starting another tool.")
            return
        if self.active_sketch():
            profile = self.active_sketch().Name
            if not self.finish_sketch():
                return
            self.select_feature(profile)
        selected = Gui.Selection.getSelection()
        profile = None if choose_new else (selected[0].Name if selected and selected[0].TypeId == "Sketcher::SketchObject" else self.selected())
        obj = self.document().getObject(profile or "") if self.document() else None
        if not self.document():
            self.notify("Create or open a project first.")
            return
        self.cancel_placement()
        self.task, self.task_profile = ("pocket" if cut else "pad"), (obj.Name if obj and obj.TypeId == "Sketcher::SketchObject" else None)
        self.task_document = self.document().Name
        self.editor_title.setText("Remove material" if cut else "Extrude")
        self.editor_help.setText(obj.Label + " · native " + ("Pocket" if cut else "Pad") if self.task_profile else "Select a closed sketch profile from the history.")
        self.end_type.setCurrentIndex(1 if cut else 0)
        self.depth.setEnabled(not cut)
        self.reverse.setChecked(False)
        self.configure_editor("extrude")
        self.editor.show()
        self.depth.setFocus()
        self.depth.selectAll()

    def accept_task(self):
        if self.active_sketch():
            return self.finish_sketch()
        if self.task in {"pad", "pocket"}:
            if not self.document() or self.document().Name != self.task_document:
                self.cancel_task()
                self.notify("Feature canceled because its source document is no longer active.")
                return False
            kind, profile = self.task, self.task_profile
            if not profile:
                self.notify("Select a closed sketch profile from the history.")
                return False
            args = {"id": self.unique("Pocket" if kind == "pocket" else "Pad"), "profile": profile,
                    "length": self.depth.value()}
            if kind == "pad" or self.reverse.isChecked():
                args["reversed"] = self.reverse.isChecked()
            if kind == "pocket":
                args["through_all"] = self.end_type.currentIndex() == 1
            result = self.operation(kind, **args)
            if result:
                obj = self.document().getObject(args["id"])
                self.document().getObject(profile).ViewObject.Visibility = False
                obj.ViewObject.Visibility = True
                self.task = self.task_profile = self.task_document = None
                self.select_feature(obj.Name)
                self.parameters(show=True)
            return result
        return False

    def accept_repeat(self):
        kind = self.task
        result = self.accept_task() if kind else False
        if result and kind in {"pad", "pocket"}:
            self.extrude(kind == "pocket", choose_new=True)
        return result

    def cancel_task(self):
        if self.pending_sketch:
            self.cancel_placement()
            self.notify("Sketch placement canceled")
            return True
        if self.task:
            self.task = self.task_profile = self.task_document = None
            self.editor.hide()
            self.notify("Feature canceled")
            return True
        return False

    def fit(self):
        if Gui.activeDocument():
            Gui.activeDocument().activeView().fitAll()

    def history_move(self, op):
        if self.active_sketch():
            Gui.runCommand("Sketcher_StopOperation")
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
        key = self.selected()
        if key and key != "origin" and not key.startswith("plane:"):
            return self.operation("delete_feature", feature=key)
        self.notify("Select a feature to delete.")

    def history_menu(self, position):
        item = self.features.itemAt(position)
        if not item:
            return
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
        if obj.TypeId == "Sketcher::SketchObject":
            menu.addAction("Edit sketch", self.edit_sketch)
        if not key.startswith("plane:"):
            if obj.TypeId.startswith("PartDesign::"):
                menu.addAction("Edit feature", self.edit_native_feature)
            menu.addAction("Rename", self.rename_selected)
            menu.addAction("Delete", self.delete_selected)
            menu.addAction("Feature settings", lambda: self.parameters(show=True))
        menu.exec_(self.features.mapToGlobal(position))

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
            self.notify("Native command unavailable: " + command, "error")
            return False

        if command.startswith("Sketcher_") and not self.active_sketch():
            self.notify("Start or edit a sketch before using this tool.")
            return False
        modeling = command.startswith("PartDesign_") or command in self.catalog_model_commands
        if (modeling or command.startswith("Sketcher_")) and self.state and not self.state.get("managed", True):
            self.notify("Adopt a copy before editing this native reference.", "error")
            return False
        if modeling and self.active_sketch():
            self.notify("Finish the sketch before creating a solid feature.")
            return False
        if modeling and self.native_feature_task_active():
            self.notify("Finish or cancel the current feature before starting another tool.")
            return False
        try:
            if modeling:
                if not self.document():
                    return False
                Gui.activateWorkbench(workbench or "PartDesignWorkbench")
                obj = self.document().getObject(self.selected() or "")
                if obj and not Gui.Selection.getSelection():
                    Gui.Selection.addSelection(obj)
            Gui.runCommand(command)
            self.sync_edit_ui()
            hide_native_panels()
            return True
        except Exception as exc:
            self.notify(str(exc), "error")
            return False

    def edit_native_feature(self):
        if self.state and not self.state.get("managed", True):
            self.notify("Adopt a copy before editing this native reference.", "error")
            return
        obj = self.document().getObject(self.selected() or "") if self.document() else None
        if obj and obj.TypeId.startswith("PartDesign::") and not self.active_sketch():
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
            self.notify(f"Minimum distance: {shapes[0].distToShape(shapes[1])[0]:.4f} mm")
        elif shapes:
            shape = shapes[0]
            if shape.ShapeType == "Edge":
                self.notify(f"Edge length: {shape.Length:.4f} mm")
            elif shape.ShapeType == "Face":
                self.notify(f"Face area: {shape.Area:.4f} mm²")
            else:
                self.notify(f"Volume: {shape.Volume:.4f} mm³ · area: {shape.Area:.4f} mm²")
        else:
            self.notify("Select an edge, face, part, or two shapes to measure.")

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
            "general.cancel": self.cancel_task, "general.accept": lambda: self.accept_task() if self.task else False,
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
        callbacks.update({"assembly.insert": self.insert_assembly_part,
                          "assembly.fasten": lambda: self.assembly_joint("fixed"),
                          "assembly.mates": self.toggle_assembly_joints,
                          "assembly.show_mates": self.toggle_assembly_joints})
        callbacks.update(viewport_callbacks(self))
        return callbacks

    def eventFilter(self, watched, event):
        if event.type() in {QtCore.QEvent.KeyPress, QtCore.QEvent.MouseButtonPress}:
            self.feedback_started = time.perf_counter()
            self.feedback_kind = "ordinary"
        if event.type() == QtCore.QEvent.MouseButtonRelease and self.active_sketch():
            self.core.record_edit_boundary(self.document())
            self.core.observer.state(self.document())["refresh"] = True
        if event.type() == QtCore.QEvent.KeyPress and event.key() in {QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter}:
            if watched is self.depth.lineEdit() and self.task:
                self.depth.interpretText()
                if event.modifiers() & QtCore.Qt.ShiftModifier:
                    self.accept_repeat()
                else:
                    self.accept_task()
                return True
            if watched is self.value.lineEdit() and not self.active_sketch():
                self.apply_parameter()
                return True
            if watched is self.formula:
                self.apply_parameter()
                return True
        if watched is self.main and event.type() == QtCore.QEvent.Close and (self.active_sketch() or (self.state or {}).get("active_sketch_edit")):
            if not self.finish_sketch():
                event.ignore()
                return True
        return False

    def shutdown(self):
        self.timer.stop()
        self.recovery_timer.stop()
        QtGui.QApplication.instance().removeEventFilter(self)
        self.router.uninstall()
        self.general_actions.close()
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
    screen = QtGui.QApplication.primaryScreen().availableGeometry()
    main.resize(min(1440, int(screen.width() * .94)), min(920, int(screen.height() * .9)))
    panel = Panel(Controller())
    main.addDockWidget(QtCore.Qt.LeftDockWidgetArea, panel)
    main.resizeDocks([panel], [265], QtCore.Qt.Horizontal)
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
