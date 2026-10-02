"""Context-aware Onshape defaults on the authoritative native document.

Application-level ShortcutOverride/KeyPress routing avoids competing native
workbench bindings. CAD and Qt imports are lazy for headless routing tests.
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def normalize_key(key):
    key = key.strip().replace("Control+", "Ctrl+")
    aliases = {"Return": "Enter", "Esc": "Escape", "PgUp": "PageUp", "PgDown": "PageDown", "Del": "Delete"}
    pieces = key.split("+")
    base = aliases.get(pieces[-1], pieces[-1])
    if len(base) == 1 and base.isalpha():
        base = base.upper()
    modifiers = set(pieces[:-1])
    if base == "?":
        base = "/"
        modifiers.add("Shift")
    return "+".join([m for m in ("Ctrl", "Alt", "Shift", "Meta") if m in modifiers] + [base])


def active_contexts(context):
    result = list(context) if isinstance(context, (tuple, list, set)) else [context or "part_studio"]
    if "sketch" in result and "part_studio" not in result:
        result.append("part_studio")
    if any(c in result for c in ("sketch", "part_studio", "assembly")) and "view" not in result:
        result.append("view")
    if "general" not in result:
        result.append("general")
    return result


def load_registry(path=None):
    data = json.loads(Path(path or ROOT / "shortcuts.json").read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("shortcuts"), list):
        raise ValueError("Unsupported shortcut registry schema")
    seen, ids = set(), set()
    for item in data["shortcuts"]:
        if item["id"] in ids:
            raise ValueError("Duplicate shortcut action: " + item["id"])
        ids.add(item["id"])
        for context in item["contexts"]:
            pair = (context, normalize_key(item["key"]))
            if pair in seen:
                raise ValueError("Ambiguous shortcut: " + str(pair))
            seen.add(pair)
    return data


class ShortcutRouter:
    """callbacks maps action ids to zero-argument callables (False defers).

    context_provider returns a context name or ordered names. status_callback
    receives a message. native_runner(command_id) optionally wraps native tools
    in the owner's normal safety path. Callbacks override registry backends.
    available_actions() gives registry dicts plus resolved_status, context only.
    """
    def __init__(self, app, callbacks, context_provider, status_callback,
                 registry_path=None, native_runner=None):
        self.app = app
        self.callbacks = dict(callbacks)
        self.context_provider = context_provider
        self.status_callback = status_callback
        self.registry = load_registry(registry_path)
        self.entries = self.registry["shortcuts"]
        self.native_runner = native_runner
        self._filter = None
        self._dialogs = {}
        self._last_native = None
        self._native_context = None

    _toggle_tools = {"sketch.arc", "sketch.circle", "sketch.center_rectangle", "sketch.corner_rectangle",
                     "sketch.line", "sketch.point", "sketch.extend", "sketch.trim", "sketch.project", "sketch.offset"}

    def resolve(self, key, context=None):
        key = normalize_key(key)
        contexts = active_contexts(context if context is not None else self.context_provider())
        for name in contexts:
            for item in self.entries:
                if name in item["contexts"] and normalize_key(item["key"]) == key:
                    return item
        return None

    @staticmethod
    def _commands():
        try:
            import FreeCADGui as Gui
            return set(Gui.listCommands())
        except ImportError:
            return set()

    def action_status(self, entry):
        if entry["id"] in self.callbacks or entry["id"] in {"general.help", "general.palette", "general.search"}:
            return "available"
        if entry.get("native_command"):
            return "native equivalent" if self.native_runner or entry["native_command"] in self._commands() else "native tool unavailable"
        if entry["status"] == "pass_through":
            return "recorded gesture; compatibility unverified"
        return "unavailable"

    def available_actions(self, context=None):
        contexts = active_contexts(context if context is not None else self.context_provider())
        keys, result = set(), []
        for name in contexts:
            for entry in self.entries:
                key = normalize_key(entry["key"])
                if name in entry["contexts"] and key not in keys:
                    keys.add(key)
                    result.append(dict(entry, resolved_status=self.action_status(entry)))
        return result

    def dispatch(self, key, context=None):
        entry = self.resolve(key, context)
        return self.invoke(entry["id"], context) if entry else False

    def invoke(self, action, context=None):
        entry = next((e for e in self.entries if e["id"] == action), None)
        if entry is None or entry["status"] == "pass_through":
            return False
        try:
            if action in self.callbacks:
                handled = self.callbacks[action]() is not False
                self._last_native = None
                return handled
            builtin = {"general.help": self.show_help, "general.palette": self.show_palette, "general.search": self.show_search}
            if action in builtin:
                builtin[action]()
                return True
            command = entry.get("native_command")
            if command:
                current = context if context is not None else self.context_provider()
                same_sketch = "sketch" in active_contexts(current) and current == self._native_context
                if same_sketch and self._last_native == command and entry["id"] in self._toggle_tools:
                    command = "Sketcher_StopOperation"
                    self._last_native = None
                else:
                    self._last_native = command
                self._native_context = current
                if self.native_runner:
                    self.native_runner(command)
                else:
                    import FreeCADGui as Gui
                    if command not in Gui.listCommands():
                        raise RuntimeError("Native command is unavailable: " + command)
                    Gui.runCommand(command)
                return True
            context = context if context is not None else self.context_provider()
            note = entry.get("note") or "This operation is not implemented in this local modeling slice."
            self.status_callback(f"{entry['label']} ({entry['key']}; {context}): {note}")
            return True  # Never fall through to an unrelated native shortcut.
        except Exception as exc:
            self.status_callback(entry["label"] + ": " + str(exc))
            return True

    def install(self):
        if self._filter is not None or self.app is None:
            return
        from PySide import QtCore, QtGui
        owner = self
        class Filter(QtCore.QObject):
            def eventFilter(self, watched, event):
                if event.type() == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.RightButton:
                    # Native right-click cancels a continuous Sketcher tool.
                    owner._last_native = None
                    return False
                if event.type() not in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress):
                    return False
                widget = owner.app.focusWidget()
                key = owner._event_key(event, QtCore)
                if owner._dialog_has_focus(widget):
                    help_dialog = owner._dialogs.get("help")
                    if key == "Shift+/" and help_dialog is not None and widget.window() is help_dialog:
                        if event.type() == QtCore.QEvent.KeyPress:
                            help_dialog.close()
                        event.accept()
                        return True
                    return False
                if owner.app.activePopupWidget() is not None:
                    return False
                if not key:
                    return False
                entry = owner.resolve(key)
                if entry is None or entry["status"] == "pass_through":
                    return False
                global_file_action = entry["id"] in {"local.save", "local.new", "local.open"}
                if owner._text_input(widget, QtGui) and key != "Escape" and not global_file_action:
                    return False
                # Dimension input dialogs retain Enter and Escape handling.
                if widget is not None and isinstance(widget.window(), QtGui.QDialog):
                    return False
                if event.type() == QtCore.QEvent.ShortcutOverride:
                    event.accept()
                    return True
                if event.isAutoRepeat():
                    event.accept()
                    return True
                handled = owner.invoke(entry["id"])
                if handled:
                    event.accept()
                return handled
        self._filter = Filter(self.app)
        self.app.installEventFilter(self._filter)

    def uninstall(self):
        if self._filter is not None:
            self.app.removeEventFilter(self._filter)
            self._filter.deleteLater()
            self._filter = None

    @staticmethod
    def _event_key(event, QtCore):
        qt, code = QtCore.Qt, event.key()
        special = {qt.Key_Escape: "Escape", qt.Key_Return: "Enter", qt.Key_Enter: "Enter", qt.Key_Space: "Space",
                   qt.Key_Delete: "Delete", qt.Key_Backspace: "Backspace", qt.Key_Left: "Left", qt.Key_Right: "Right",
                   qt.Key_Up: "Up", qt.Key_Down: "Down", qt.Key_Home: "Home", qt.Key_End: "End",
                   qt.Key_PageUp: "PageUp", qt.Key_PageDown: "PageDown", qt.Key_BracketLeft: "[",
                   qt.Key_BracketRight: "]", qt.Key_QuoteLeft: "`", qt.Key_Slash: "/"}
        shifted = {"!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6", "&": "7", "?": "/"}
        if code in special:
            base = special[code]
        elif 0 <= code < 128:
            base = shifted.get(chr(code), chr(code))
        else:
            return None
        mods = event.modifiers()
        prefix = [name for mask, name in ((qt.ControlModifier, "Ctrl"), (qt.AltModifier, "Alt"),
                                          (qt.ShiftModifier, "Shift"), (qt.MetaModifier, "Meta")) if mods & mask]
        return normalize_key("+".join(prefix + [base]))

    @staticmethod
    def _text_input(widget, QtGui):
        while widget is not None:
            if isinstance(widget, (QtGui.QLineEdit, QtGui.QTextEdit, QtGui.QPlainTextEdit, QtGui.QAbstractSpinBox)):
                return True
            if isinstance(widget, QtGui.QComboBox) and widget.isEditable():
                return True
            widget = widget.parentWidget()
        return False

    def _dialog_has_focus(self, widget):
        return widget is not None and any(dialog is not None and widget.window() is dialog for dialog in self._dialogs.values())

    def show_help(self, parent=None):
        self._show_command_dialog("help", parent)

    def show_palette(self, parent=None):
        from PySide import QtGui
        menu = QtGui.QMenu(parent or self.app.activeWindow())
        actions = {}
        entries = {entry["id"]: entry for entry in self.available_actions()}
        def add(target, action_id):
            entry = entries.get(action_id)
            if entry is None:
                return
            label = entry["label"] + "  (" + entry["key"] + ")"
            if entry["resolved_status"] not in {"available", "native equivalent"}:
                label += " — unavailable"
            actions[target.addAction(label)] = action_id
        if "sketch" in active_contexts(self.context_provider()):
            for action_id in ("sketch.line", "sketch.circle", "sketch.arc", "sketch.corner_rectangle",
                              "sketch.center_rectangle", "sketch.point", "sketch.trim", "sketch.offset", "sketch.construction"):
                add(menu, action_id)
            constraints = menu.addMenu("Constraints and dimensions")
            for action_id in ("sketch.dimension", "sketch.coincident", "sketch.concentric", "sketch.horizontal", "sketch.vertical",
                              "sketch.parallel", "sketch.perpendicular", "sketch.equal", "sketch.tangent", "sketch.symmetric",
                              "sketch.midpoint", "sketch.fix", "sketch.curvature", "sketch.normal", "sketch.pierce"):
                add(constraints, action_id)
        else:
            for action_id in ("sketch.start", "feature.extrude", "feature.revolve", "feature.fillet"):
                add(menu, action_id)
        menu.addSeparator()
        for action_id in ("view.fit", "view.normal", "view.isometric"):
            add(menu, action_id)
        views = menu.addMenu("Standard views")
        for action_id in ("view.front", "view.back", "view.left", "view.right", "view.top", "view.bottom"):
            add(views, action_id)
        menu.addSeparator()
        for action_id in ("general.undo", "general.redo", "local.save", "general.search", "general.help"):
            add(menu, action_id)
        chosen = menu.exec(QtGui.QCursor.pos())
        if chosen in actions:
            self.invoke(actions[chosen])

    def show_search(self, parent=None):
        self._show_command_dialog("search", parent)

    def _show_command_dialog(self, mode, parent):
        from PySide import QtCore, QtGui
        previous = self._dialogs.get(mode)
        if previous is not None and previous.isVisible():
            if mode == "help":
                previous.close()
            else:
                previous.activateWindow()
                previous.raise_()
            return
        dialog = QtGui.QDialog(parent or self.app.activeWindow())
        dialog.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        dialog.setWindowTitle("Onshape keyboard shortcuts" if mode == "help" else "Search tools")
        dialog.resize(770, 570)
        layout = QtGui.QVBoxLayout(dialog)
        search = QtGui.QLineEdit()
        search.setPlaceholderText("Filter by tool, shortcut, context, or availability")
        layout.addWidget(search)
        table = QtGui.QTreeWidget()
        table.setHeaderLabels(["Tool", "Shortcut", "Context", "Availability"])
        table.setColumnWidth(0, 280)
        table.setColumnWidth(1, 120)
        table.setColumnWidth(2, 125)
        layout.addWidget(table)
        entries = self.entries if mode == "help" else self.available_actions()
        for entry in entries:
            item = QtGui.QTreeWidgetItem([entry["label"], entry["key"], ", ".join(entry["contexts"]), self.action_status(entry)])
            item.setData(0, QtCore.Qt.UserRole, entry["id"])
            item.setToolTip(0, entry.get("note", ""))
            table.addTopLevelItem(item)
        def filter_items(value):
            for i in range(table.topLevelItemCount()):
                item = table.topLevelItem(i)
                item.setHidden(value.lower() not in " ".join(item.text(c) for c in range(4)).lower())
        search.textChanged.connect(filter_items)
        def activate(item, *_):
            action = item.data(0, QtCore.Qt.UserRole)
            dialog.close()
            self.invoke(action)
        table.itemActivated.connect(activate)
        close = QtGui.QDialogButtonBox(QtGui.QDialogButtonBox.Close)
        close.rejected.connect(dialog.close)
        layout.addWidget(close)
        self._dialogs[mode] = dialog
        def forget_dialog():
            if self._dialogs.get(mode) is dialog:
                self._dialogs.pop(mode, None)
        dialog.destroyed.connect(forget_dialog)
        dialog.show()
        search.setFocus()
