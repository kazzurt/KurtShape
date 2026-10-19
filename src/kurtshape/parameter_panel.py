"""Parameters section of the left panel and the persisted three-section layout.

Contract 3.2, feature 3b. Qt-only: FreeCAD is imported lazily (``Units.Quantity``
in :func:`normalize_value`, ``ParamGet`` in :class:`PreferenceStore`) and
FreeCADGui is never imported, so every widget runs offscreen with a fake adapter.

Every model read and write goes through an adapter. :class:`ParameterAdapter`
declares what the widget layer may ask for and holds the only error-code table;
:class:`ControllerParameterAdapter` is the only code that knows the parameter op
names, request fields and how to reach the backend. The widget layer never
builds a reference string and never owns the name rule: the pattern for the
local name hint is injected through ``adapter.name_pattern()``.

Commit rules (3b §4):
- a field is *edited* only after a user ``textEdited``; programmatic text never is;
- Enter always commits an edited field (a retry after a rejection, an overwrite
  in a conflict);
- losing focus commits only for Mouse, Tab, Backtab and Shortcut reasons; window
  deactivation, popups, the menu bar and Other leave a visible pending edit;
- a commit is decided synchronously, with the document and revision tokens
  captured then, and dispatched from a zero-delay timer whose context object is
  the section. Fields are retired before their row widget is removed or rebuilt,
  which drops any commit still aimed at them.
- the deferred run is authoritative. Qt delivers input that is already queued
  (a second Enter, a click elsewhere, typed-ahead text, Escape) before it, so a
  field has at most one scheduled commit: the same text joins it, new text
  replaces it, Escape drops it, and a commit already in flight is left to settle
  the field. At dispatch the field must still hold the decided text and nothing
  may block edits; otherwise nothing is sent.
- a scheduled commit that succeeds advances the expected revision of the later
  scheduled commits decided on the same revision: the section's own edit is not
  a change made elsewhere. Any other revision change still gives stale_revision.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field as dataclass_field
import math
import re

from PySide import QtCore, QtGui

from .theme import COLORS

LAYOUT_GROUP = "User parameter:KurtShape/Preferences/Layout"
LAYOUT_KEY = "LeftPanelSections"
DEFAULT_SIZES = (450, 120, 150)
SAVE_DELAY_MS = 400
MAX_SECTION_SIZE = 20000

TYPES = ("length", "angle", "number")
TYPE_CHOICES = (("length", "Length (mm)"), ("angle", "Angle (°)"), ("number", "Number (no unit)"))
TYPE_DESCRIPTIONS = dict(TYPE_CHOICES)
DEFAULT_VALUES = {"length": "10", "angle": "0", "number": "1"}
TYPE_UNITS = {"length": "mm", "angle": "°", "number": ""}
NATIVE_UNITS = {"mm": "mm", "deg": "°", "": ""}

NO_DOCUMENT = "Open or create a part studio to add parameters"
EMPTY = "No parameters · + adds one"
NOT_A_NUMBER = "Not a number. Start a formula with =, e.g. =shaft_diameter + 2 mm"
PENDING_NOTE = "Not applied yet · Enter applies, Esc discards"
STALE_NOTE = "Last evaluated value; may be out of date"
FORMULA_NOTE = "Driven by a formula"
ADD_TOOLTIP = "Add parameter"
COMMITTED = "Parameter update complete"

AFFECTS_SHOWN = 8
CONSUMERS_SHOWN = 8
VALUE_PADDING = 18
FORMULA_ICON_WIDTH = 18
VALUE_MIN_WIDTH = 64
VALUE_MAX_FRACTION = 0.45
UNIT_WIDTH = 34
NOTE_LINES = 3
CLAMP_TOLERANCE = 1e-9

# Focus moves that stay inside the window and are deliberate. ActiveWindow,
# Popup, MenuBar and Other never commit (3b D5).
COMMIT_REASONS = frozenset({QtCore.Qt.MouseFocusReason, QtCore.Qt.TabFocusReason,
                            QtCore.Qt.BacktabFocusReason, QtCore.Qt.ShortcutFocusReason})


# --------------------------------------------------------------------------
# Pure helpers


def format_number(value):
    """Short and exact enough to edit; never FreeCAD's two-decimal UserString."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "?"
    if not math.isfinite(value):
        return str(value)
    if value == 0:
        return "0"
    if abs(value) < 1e-4:
        return format(value, ".6g")
    text = format(round(value, 6), "f").rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def unit_text(row):
    """Unit column text from the backend's native unit (degrees for angles)."""
    native = row.get("native_unit")
    if native is not None:
        return NATIVE_UNITS.get(native, str(native))
    return TYPE_UNITS.get(row.get("type"), "")


def first_line(text):
    return str(text or "").strip().splitlines()[0] if str(text or "").strip() else ""


@dataclass(frozen=True)
class Request:
    """One value commit, already classified locally; the backend re-validates."""
    value: object = None
    expression: str | None = None
    clears_formula: bool = False
    expected_native: float | None = None

    def args(self):
        """Request fields in the 3a contract shape."""
        if self.expression is not None:
            return {"expression": self.expression}
        args = {"value": self.value}
        if self.clears_formula:
            args["expression"] = None
        return args


@dataclass(frozen=True)
class LocalError:
    message: str
    field: str = "value"


@dataclass(frozen=True)
class Outcome:
    ok: bool
    code: str | None = None
    message: str = ""
    field: str | None = None
    transient: bool = False
    details: dict = dataclass_field(default_factory=dict)
    refresh: bool = False


@dataclass(frozen=True)
class Rejection:
    text: str
    code: str | None
    transient: bool
    message: str = ""


def normalize_value(kind, text, formula_row=False):
    """Classify typed text into a :class:`Request` or a :class:`LocalError`.

    ``Units.Quantity`` is used only to classify; the backend parses again. A bare
    number means mm for a length and degrees for an angle (GUI angles are typed
    in degrees). A literal on a formula row also clears the formula, in one
    request.
    """
    text = (text or "").strip()
    if not text:
        return LocalError("Enter a value")
    if text.startswith("="):
        rest = text[1:].strip()
        return Request(expression=rest) if rest else LocalError("Enter a formula after =")
    import FreeCAD as App
    try:
        quantity = App.Units.Quantity(text)
        value = float(quantity.Value)
    except Exception:
        return LocalError(NOT_A_NUMBER)
    if not math.isfinite(value):
        return LocalError("Enter a finite number")
    value += 0.0  # -0.0 becomes 0.0
    clears = bool(formula_row)
    if quantity.Unit == App.Units.Quantity(1).Unit:
        if kind == "length":
            return Request(value=f"{value!r} mm", clears_formula=clears, expected_native=value)
        if kind == "angle":
            return Request(value=f"{value!r} deg", clears_formula=clears, expected_native=value)
        return Request(value=value, clears_formula=clears, expected_native=value)
    expected = None
    if kind == "length" and quantity.Unit == App.Units.Length:
        expected = float(quantity.getValueAs("mm"))
    elif kind == "angle" and quantity.Unit == App.Units.Angle:
        expected = float(quantity.getValueAs("deg"))
    return Request(value=text, clears_formula=clears, expected_native=expected)


def _set_property(widget, name, value):
    if widget.property(name) == value:
        return
    widget.setProperty(name, value)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


_FORMULA_ICON = None


def _formula_icon():
    global _FORMULA_ICON
    if _FORMULA_ICON is None:
        pixmap = QtGui.QPixmap(FORMULA_ICON_WIDTH, 14)
        pixmap.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        font = QtGui.QFont(QtGui.QApplication.font())
        font.setItalic(True)
        font.setPointSizeF(max(6.0, font.pointSizeF() - 1) if font.pointSizeF() > 0 else 8.0)
        painter.setFont(font)
        painter.setPen(QtGui.QColor(COLORS["selection_ink"]))
        painter.drawText(pixmap.rect(), QtCore.Qt.AlignCenter, "ƒx")
        painter.end()
        _FORMULA_ICON = QtGui.QIcon(pixmap)
    return _FORMULA_ICON


# --------------------------------------------------------------------------
# Adapter layer


_BINDING = re.compile(r"in property binding '[^'#]*#([^'.]+)\.([^']+)'")
_UNIT_REASON = "{name} is a unit or keyword in formulas (like mm, in, t, deg) · use a longer name such as thickness."


class ParameterAdapter:
    """Everything the widget layer may ask of the backend.

    Subclasses supply the reads and writes. ``key()`` must return fresh data on
    every call (it is compared by equality with the cached key). The error-code
    table below is the only place error codes are interpreted.
    """

    NAME_REASONS = {
        "format": "Start with a lowercase letter; use letters, digits or _ (up to 64).",
        "reserved": "{name} is reserved.",
        "reserved_attribute": "{name} is a built-in property name · choose another name.",
        "constant": "{name} is a formula constant (like pi or e).",
        "function": "{name} is a formula function.",
        "expression_token": _UNIT_REASON,
        "unit": _UNIT_REASON,
    }
    NAME_CODES = frozenset({"invalid_parameter_name", "duplicate_parameter"})
    VALUE_CODES = frozenset({"invalid_argument", "unit_mismatch", "invalid_expression", "expression_cycle",
                             "expression_driven", "unsupported_parameter"})
    FEATURE_CODES = frozenset({"build_failed", "empty_cut", "empty_add", "invalid_geometry"})
    REFRESH_CODES = frozenset({"missing_parameter"})
    FLOW_CODES = frozenset({"parameter_in_use", "rename_failed"})
    TRANSIENT_CODES = frozenset({"stale_revision", "busy", "sketch_edit_active", "managed_sketch_mismatch",
                                 "document_changed", "not_applied"})

    # Reads. key() -> (document_id, managed, rows, set_state) | None.
    def key(self):
        raise NotImplementedError

    def revision(self):
        raise NotImplementedError

    def usage(self, name):
        """{used_by:[{feature, parameter, label, held}], used_by_parameters, affects, parts} | None."""
        return None

    def blocker(self):
        return None

    def name_pattern(self):
        return None

    def rolled_back(self):
        return False

    # Writes; each returns an Outcome.
    def set_value(self, name, request, tokens):
        raise NotImplementedError

    def create(self, name, kind, request, tokens):
        raise NotImplementedError

    def rename(self, name, new_name, tokens):
        raise NotImplementedError

    def delete(self, name, keep_values, tokens):
        raise NotImplementedError

    # Feedback.
    def notify(self, message, severity=None):
        pass

    def show_use(self, feature, parameter):
        pass

    @classmethod
    def name_message(cls, reason, name):
        template = cls.NAME_REASONS.get(reason)
        return template.format(name=name) if template else None

    @classmethod
    def translate(cls, error):
        """Wire error -> Outcome: the field it belongs to, and whether a retry may help."""
        error = dict(error or {})
        code = str(error.pop("code", None) or "operation_failed")
        message = str(error.pop("message", None) or "Not applied")
        details = error
        if code in cls.NAME_CODES:
            name = details.get("name") or ""
            if code == "duplicate_parameter":
                existing = details.get("existing") or name
                message = f"A parameter named {existing} already exists."
            else:
                message = cls.name_message(details.get("reason"), name) or message
            return Outcome(False, code, message, "name", False, details)
        if code in cls.FEATURE_CODES:
            feature = details.get("feature")
            if feature and str(feature) not in message:
                message = f"{message} · {feature}"
            return Outcome(False, code, message, "value", False, details)
        if code in cls.REFRESH_CODES:
            return Outcome(False, code, "Renamed or deleted elsewhere", None, False, details, refresh=True)
        if code in cls.FLOW_CODES:
            return Outcome(False, code, message, None, False, details)
        if code in cls.TRANSIENT_CODES:
            return Outcome(False, code, message, None, True, details)
        return Outcome(False, code, message, "value", False, details)

    @staticmethod
    def evaluation(set_state):
        """None while the parameter set is up to date; otherwise what the banner says."""
        if not set_state:
            return None
        state = set_state.get("state")
        if isinstance(state, str):
            flags = {"invalid": {"Invalid"}, "needs_rebuild": {"Touched"}}.get(state, set())
        else:
            flags = set(state or ())
        failed = bool(flags & {"Invalid", "Error"})
        if not failed and "Touched" not in flags:
            return None
        error = set_state.get("error") or {}
        return {"kind": "failed" if failed else "touched", "name": error.get("name"),
                "message": first_line(error.get("message"))}

    @staticmethod
    def set_state_from(state):
        """inspect ``parameter_set``, else derived from ``build_errors`` on the container."""
        explicit = state.get("parameter_set")
        if explicit is not None:
            return explicit
        set_id = next((str(row.get("expression_ref")).split(".", 1)[0] for row in state.get("parameters") or ()
                       if "." in str(row.get("expression_ref") or "")), None)
        if not set_id:
            return None
        errors = [error for error in state.get("build_errors") or () if error.get("feature") == set_id]
        if not errors:
            return None
        message = str(errors[0].get("message") or "")
        match = _BINDING.search(message)
        name = match.group(2) if match and match.group(1) == set_id else None
        return {"id": set_id, "label": set_id, "state": ["Invalid"], "error": {"name": name, "message": message}}


class ControllerParameterAdapter(ParameterAdapter):
    """Reaches the 3a backend through the Panel; the only owner of op and field names.

    Reads never dispatch on the refresh path: rows come from the inspect payload
    the panel already holds. Usage is read lazily (hover, menu, delete) and cached
    per (document_id, revision). Writes go through ``panel.operation`` so each
    commit is one native transaction and one undo step.
    """

    EDITING = "Finish or cancel the current sketch/feature to edit parameters"
    ASSEMBLY = "Parameters are edited in part studios"
    REFERENCE = "Reference file · adopt a copy to edit parameters"

    def __init__(self, panel):
        self.panel = panel
        self._usage_key = None
        self._usage = {}

    def _state(self):
        return getattr(self.panel, "state", None) or None

    def _assembly(self):
        return getattr(self.panel, "workspace_mode", "part_studio") == "assembly"

    def key(self):
        state = self._state()
        if not state or self._assembly() or not self.panel.document():
            return None
        return (state.get("document_id"), bool(state.get("managed")), list(state.get("parameters") or ()),
                self.set_state_from(state))

    def revision(self):
        state = self._state()
        return state.get("revision") if state else None

    def blocker(self):
        panel = self.panel
        state = self._state()
        if not state or not panel.document():
            return NO_DOCUMENT
        if self._assembly():
            return self.ASSEMBLY
        if not state.get("managed"):
            return self.REFERENCE
        editor = getattr(panel, "sketch_plane_editor", None)
        core = getattr(panel, "core", None)
        if (state.get("active_sketch_edit") or panel.active_sketch() or getattr(editor, "picking", False)
                or getattr(panel, "selecting_support", False) or getattr(panel, "task", None)
                or getattr(panel, "pending_sketch", False) or getattr(panel, "studio_dialog", None)
                or panel.native_feature_task_active() or getattr(core, "busy", False)):
            return self.EDITING
        return None

    def name_pattern(self):
        try:
            from . import parameters
        except ImportError:
            return None
        pattern = getattr(parameters, "NAME_PATTERN", None)
        return getattr(pattern, "pattern", pattern)

    def rolled_back(self):
        studio = (self._state() or {}).get("studio") or {}
        order = studio.get("feature_order") or ()
        return studio.get("rollback_index", len(order)) < len(order)

    def usage(self, name):
        state = self._state()
        if not state:
            return None
        key = (state.get("document_id"), state.get("revision"))
        if key != self._usage_key:
            self._usage_key, self._usage = key, {}
        if name not in self._usage:
            row = self._usage_row(state, name)
            self._usage[name] = None if row is None else self._normalize_usage(state, row)
        return copy.deepcopy(self._usage[name])

    @staticmethod
    def _pick(found, name):
        if isinstance(found, dict):
            if name in found and isinstance(found[name], dict):
                return found[name]
            found = found.get("parameters")
        for row in found or ():
            if isinstance(row, dict) and row.get("name") == name:
                return row
        return None

    def _usage_row(self, state, name):
        doc = self.panel.document()
        try:
            from . import parameters
        except ImportError:
            parameters = None
        helper = getattr(parameters, "usage_rows", None)
        if helper is not None and doc is not None:
            try:
                row = self._pick(helper(doc, [name]), name)
            except Exception:
                row = None
            if row is not None:
                return row
        response = self.panel.core.dispatch({"op": "list_parameters", "document_id": state.get("document_id"),
                                             "names": [name]})
        if not response.get("ok"):
            return None
        return self._pick(response.get("result") or {}, name)

    @staticmethod
    def _normalize_usage(state, row):
        features = state.get("features") or ()
        names = {feature.get("id"): feature.get("name") or feature.get("id") for feature in features}
        held = {feature.get("id") for feature in features if feature.get("rolled_back")}
        used_by = []
        for entry in row.get("used_by") or ():
            feature = entry.get("feature")
            what = entry.get("parameter") or entry.get("path") or ""
            label = str(names.get(feature, feature or "?")) + (" · " + str(what).lstrip(".") if what else "")
            used_by.append({"feature": feature, "parameter": entry.get("parameter"), "label": label,
                            "held": feature in held})
        affects = row.get("affects") or {}
        parts = (state.get("studio") or {}).get("parts") or ()
        part_names = {part.get("id"): part.get("name") or part.get("id") for part in parts}
        return {"used_by": used_by, "used_by_parameters": list(row.get("used_by_parameters") or ()),
                "affects": [names.get(feature, feature) for feature in affects.get("features") or ()],
                "parts": [part_names.get(part, part) for part in affects.get("parts") or ()] if len(parts) > 1 else []}

    def _write(self, op, args, tokens):
        panel = self.panel
        panel.last_operation_error = None
        result = panel.operation(op, **args, **tokens)
        if result is not None:
            return Outcome(True)
        error = getattr(panel, "last_operation_error", None)
        if not error:
            label = getattr(panel, "message", None)
            error = {"code": "not_applied", "message": label.text() if label is not None else "Not applied"}
        return self.translate(error)

    def set_value(self, name, request, tokens):
        return self._write("edit_parameter", {"name": name, **request.args()}, tokens)

    def create(self, name, kind, request, tokens):
        return self._write("create_parameter", {"name": name, "type": kind, **request.args()}, tokens)

    def rename(self, name, new_name, tokens):
        return self._write("rename_parameter", {"name": name, "new_name": new_name}, tokens)

    def delete(self, name, keep_values, tokens):
        return self._write("delete_parameter", {"name": name, "freeze_consumers": bool(keep_values)}, tokens)

    def notify(self, message, severity=None):
        if severity == "error":
            self.panel.notify(message, "error")
        else:
            self.panel.notify(message)

    def show_use(self, feature, parameter):
        handler = getattr(self.panel, "show_parameter_use", None)
        if handler is not None:
            handler(feature, parameter)


# --------------------------------------------------------------------------
# Widgets


class _Pending:
    __slots__ = ("field", "request", "tokens", "explicit", "text")

    def __init__(self, field, request, tokens, explicit, text):
        self.field, self.request, self.tokens, self.explicit, self.text = field, request, tokens, explicit, text


class _Row:
    __slots__ = ("name", "item", "field", "row")

    def __init__(self, name, item, field, row=None):
        self.name, self.item, self.field, self.row = name, item, field, row


class ParameterValueEdit(QtGui.QLineEdit):
    """Value field: the evaluated value at rest, the value or ``=formula`` while focused."""

    def __init__(self, section, name):
        super().__init__()
        self.setObjectName("KurtShapeParameterValue")
        self.section = section
        self.name = name
        self.row = None
        self.supported = True
        self.formula = False
        self.accepted_text = ""
        self.display_text = ""
        self.edited = False
        self.base_text = None
        self.rejected = None
        self.committing = False
        self.retired = False
        self.target = None
        self.note = None
        self.conflict_note = None
        self.formula_action = None
        self.setAccessibleName(name + " value")
        self.setProperty("validation", "")
        self.setProperty("stale", "false")
        self.textEdited.connect(self._text_edited)

    @property
    def conflict(self):
        return self.edited and self.base_text is not None and self.accepted_text != self.base_text

    def _text_edited(self, text):
        if self.retired:
            return
        if not self.edited:
            self.edited = True
            self.base_text = self.accepted_text
        if self.property("validation") == "pending":
            _set_property(self, "validation", "")
            self.note = None
        if self.rejected is not None and text.strip() != self.rejected.text:
            _set_property(self, "validation", "")

    def set_formula_marker(self, formula):
        if formula and self.formula_action is None:
            self.formula_action = self.addAction(_formula_icon(), QtGui.QLineEdit.TrailingPosition)
            self.formula_action.setToolTip(FORMULA_NOTE)
        elif not formula and self.formula_action is not None:
            self.removeAction(self.formula_action)
            self.formula_action = None

    def show_resting_text(self):
        """Accepted text while focused, display text otherwise (cursor at the start)."""
        text = self.accepted_text if self.hasFocus() else self.display_text
        if self.text() != text:
            self.setText(text)
        if not self.hasFocus():
            self.setCursorPosition(0)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        if not self.retired:
            self.section._field_focused(self, event.reason())

    def focusOutEvent(self, event):
        reason = event.reason()
        super().focusOutEvent(event)
        if not self.retired:
            self.section._field_unfocused(self, reason)

    def keyPressEvent(self, event):
        key = event.key()
        if not self.retired:
            if key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
                event.accept()
                self.section.commit(self, explicit=True)
                return
            if key == QtCore.Qt.Key_Escape and self.section.revert(self):
                event.accept()
                return
            modifiers = event.modifiers()
            plain = modifiers == QtCore.Qt.NoModifier or modifiers == QtCore.Qt.KeypadModifier
            if plain and key in (QtCore.Qt.Key_Up, QtCore.Qt.Key_Down):
                if self.section.focus_adjacent(self, -1 if key == QtCore.Qt.Key_Up else 1):
                    event.accept()
                    return
        super().keyPressEvent(event)

    def event(self, event):
        if event.type() == QtCore.QEvent.ToolTip and not self.retired:
            self.setToolTip(self.section.tooltip(self.name, self))
        return super().event(event)


class ParameterTree(QtGui.QTreeWidget):
    """Name / Value / Unit rows; Enter focuses the value field and F2 renames."""

    def __init__(self, section):
        super().__init__()
        self.section = section
        self.setObjectName("KurtShapeParameters")
        self.setColumnCount(3)
        self.setHeaderHidden(True)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setSelectionMode(QtGui.QAbstractItemView.SingleSelection)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        header = self.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QtGui.QHeaderView.Stretch)
        header.setSectionResizeMode(1, QtGui.QHeaderView.Fixed)
        header.setSectionResizeMode(2, QtGui.QHeaderView.Fixed)
        header.resizeSection(1, VALUE_MIN_WIDTH)
        header.resizeSection(2, UNIT_WIDTH)

    def keyPressEvent(self, event):
        key = event.key()
        if key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter) and self.section.focus_current_field():
            event.accept()
            return
        if key == QtCore.Qt.Key_F2:
            event.accept()
            self.section.rename_current()
            return
        super().keyPressEvent(event)

    def viewportEvent(self, event):
        if event.type() == QtCore.QEvent.ToolTip:
            item = self.itemAt(event.pos())
            name = item.data(0, QtCore.Qt.UserRole) if item is not None else None
            if name:
                QtGui.QToolTip.showText(event.globalPos(), self.section.tooltip(name), self.viewport())
            else:
                QtGui.QToolTip.hideText()
            event.accept()
            return True
        return super().viewportEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.section._update_value_width()


class ParameterSection(QtGui.QWidget):
    """'Parameters (n)' header with '+', state banner, compact rows and an error line."""

    def __init__(self, adapter, parent=None):
        super().__init__(parent)
        self.setObjectName("KurtShapeParameterSection")
        self.adapter = adapter
        self.rows = {}
        self.order = []
        self.cache_key = None
        self.document_id = None
        self.managed = False
        self.evaluation_state = None
        self.created = 0
        self.closing = False
        self.editable = None
        self.block_reason = None
        self.dialog = None
        self.unavailable_reason = NO_DOCUMENT
        self._pending = []
        self._value_width = None
        layout = QtGui.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.header = QtGui.QWidget()
        self.header.setObjectName("KurtShapeParameterHeader")
        header_layout = QtGui.QHBoxLayout(self.header)
        header_layout.setContentsMargins(0, 0, 4, 0)
        header_layout.setSpacing(0)
        self.title = QtGui.QLabel("Parameters (0)")
        self.title.setObjectName("SectionTitle")
        header_layout.addWidget(self.title, 1)
        # Deliberately not registered with ToolbarLabels: its native tooltip
        # must stay visible while the button is disabled (3b §3).
        self.add_button = QtGui.QToolButton()
        self.add_button.setObjectName("KurtShapeAddParameter")
        self.add_button.setText("+")
        self.add_button.setAccessibleName("Add parameter")
        self.add_button.setToolTip(ADD_TOOLTIP)
        self.add_button.setAutoRaise(True)
        self.add_button.clicked.connect(self.add_parameter)
        header_layout.addWidget(self.add_button)
        layout.addWidget(self.header)
        self.banner = QtGui.QLabel()
        self.banner.setObjectName("KurtShapeParameterState")
        self.banner.setProperty("severity", "warning")
        self.banner.setWordWrap(True)
        self.banner.setMargin(6)
        self.banner.setTextFormat(QtCore.Qt.PlainText)
        self.banner.hide()
        layout.addWidget(self.banner)
        self.tree = ParameterTree(self)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.itemDoubleClicked.connect(self._double_clicked)
        layout.addWidget(self.tree, 1)
        self.empty = QtGui.QLabel(NO_DOCUMENT)
        self.empty.setObjectName("KurtShapeParameterEmpty")
        self.empty.setWordWrap(True)
        self.empty.setMargin(8)
        self.empty.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        layout.addWidget(self.empty, 1)
        self.error = QtGui.QLabel()
        self.error.setObjectName("KurtShapeParameterError")
        self.error.setProperty("severity", "error")
        self.error.setWordWrap(True)
        self.error.setMargin(6)
        self.error.setTextFormat(QtCore.Qt.PlainText)
        self.error.hide()
        layout.addWidget(self.error)
        self.tree.hide()
        self._set_editable(NO_DOCUMENT)

    # -- size -------------------------------------------------------------

    def _row_height(self):
        if self.tree.topLevelItemCount():
            height = self.tree.sizeHintForRow(0)
            if height > 0:
                return height
        return self.tree.fontMetrics().height() + 8

    def minimumSizeHint(self):
        height = self.header.sizeHint().height() + 2 * self._row_height() + 2 * self.tree.frameWidth()
        for label in (self.banner, self.error):
            if not label.isHidden():
                height += min(label.sizeHint().height(), self._note_height(label))
        return QtCore.QSize(120, height)

    def _note_height(self, label):
        return label.fontMetrics().lineSpacing() * NOTE_LINES + 2 * label.margin() + 2

    def _update_value_width(self):
        if not self.rows:
            return
        metrics = self.tree.fontMetrics()
        widest = max(metrics.horizontalAdvance(entry.field.display_text or "")
                     + (FORMULA_ICON_WIDTH if entry.field.formula else 0) for entry in self.rows.values())
        ceiling = int(self.tree.viewport().width() * VALUE_MAX_FRACTION)
        width = max(VALUE_MIN_WIDTH, min(widest + VALUE_PADDING, ceiling))
        if width != self._value_width:
            self._value_width = width
            self.tree.header().resizeSection(1, width)

    # -- refresh ----------------------------------------------------------

    def refresh(self, force=False):
        """Cheap unless the adapter key changed: set_editable plus one equality compare."""
        if self.closing:
            return
        key = self.adapter.key()
        if key is None:
            if self.cache_key is not None or self.rows or self.document_id is not None:
                self._become_unavailable(NO_DOCUMENT)
            return
        self._set_editable(self.adapter.blocker())
        if not force and key == self.cache_key:
            return
        self.cache_key = key
        document_id, managed, rows, set_state = key
        self.managed = bool(managed)
        self.evaluation_state = self.adapter.evaluation(set_state)
        if self.dialog is not None and self.dialog.document_id != document_id:
            self._reject_dialog("Parameter dialog closed: project changed")
        self._reconcile(document_id, rows)
        names = set(self.order)
        if self.dialog is not None and self.dialog.mode == "rename" and not self.dialog.submitting \
                and self.dialog.original not in names:
            self._reject_dialog("Parameter dialog closed: renamed or deleted elsewhere")
        self._show_banner()
        self.title.setText(f"Parameters ({len(self.order)})")
        self.tree.setVisible(bool(self.order))
        self.empty.setVisible(not self.order)
        if not self.order:
            self.empty.setText(EMPTY if self.managed else ControllerParameterAdapter.REFERENCE)
        self._update_value_width()
        self.updateGeometry()

    def clear(self):
        """No document: drop rows, reset the cached key and disable '+'."""
        self._become_unavailable(NO_DOCUMENT)

    def set_unavailable(self, reason, retire_reason="workspace changed"):
        """Assembly workspace and similar: no rows here, and the next refresh rebuilds."""
        if self.cache_key is None and not self.rows and self.unavailable_reason == reason and self.dialog is None:
            return
        self._become_unavailable(reason, retire_reason)

    def _become_unavailable(self, reason, retire_reason="project changed"):
        if self.dialog is not None:
            self._reject_dialog("Parameter dialog closed: " + reason[:1].lower() + reason[1:])
        self._retire_all(retire_reason)
        self.tree.clear()
        self.rows, self.order = {}, []
        self.cache_key = None
        self.document_id = None
        self.evaluation_state = None
        self.unavailable_reason = reason
        self._hide_line()
        self._show_banner()
        self.title.setText("Parameters (0)")
        self.tree.hide()
        self.empty.setText(reason)
        self.empty.show()
        self._set_editable(reason)
        self.updateGeometry()

    def set_editable(self):
        """Re-check the adapter's blocker; touches widgets only when it changed."""
        if self.closing:
            return
        self._set_editable(self.unavailable_reason if self.cache_key is None else self.adapter.blocker())

    sync_editable = set_editable

    def _set_editable(self, reason):
        editable = reason is None
        if editable == self.editable and reason == self.block_reason:
            return
        self.editable, self.block_reason = editable, reason
        self.add_button.setEnabled(editable)
        self.add_button.setToolTip(ADD_TOOLTIP if editable else ADD_TOOLTIP + " · " + reason)
        for entry in self.rows.values():
            entry.field.setReadOnly(not (editable and entry.field.supported))

    def _reconcile(self, document_id, rows):
        switched = document_id != self.document_id
        scroll = self.tree.verticalScrollBar().value()
        if switched:
            self._retire_all("project changed")
            self.tree.clear()
            self.rows, self.order = {}, []
            self.document_id = document_id
            self._hide_line()
        wanted, seen = [], set()
        for row in rows:
            name = row.get("name")
            if name and name not in seen:
                seen.add(name)
                wanted.append(row)
        for name in [name for name in self.order if name not in seen]:
            entry = self.rows.pop(name)
            self._retire(entry, "renamed or deleted elsewhere")
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(entry.item))
        changed = False
        for position, row in enumerate(wanted):
            name = row["name"]
            entry = self.rows.get(name)
            if entry is None:
                item = QtGui.QTreeWidgetItem()
                item.setData(0, QtCore.Qt.UserRole, name)
                self.tree.insertTopLevelItem(position, item)
                entry = self.rows[name] = _Row(name, item, self._new_field(item, name))
                changed = True
            elif self.tree.indexOfTopLevelItem(entry.item) != position:
                # An item widget cannot move with its item: take, reinsert, rebuild.
                focused = entry.field.hasFocus()
                self._retire(entry, "list changed")
                self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(entry.item))
                self.tree.insertTopLevelItem(position, entry.item)
                entry.field = self._new_field(entry.item, name)
                if focused:
                    entry.field.setFocus(QtCore.Qt.OtherFocusReason)
                changed = True
            self._apply_row(entry, row)
        self.order = [row["name"] for row in wanted]
        if changed:
            self._chain_tab_order()
        if not switched:
            self.tree.verticalScrollBar().setValue(scroll)

    def _new_field(self, item, name):
        field = ParameterValueEdit(self, name)
        field.setReadOnly(not self.editable)
        self.tree.setItemWidget(item, 1, field)
        self.created += 1
        return field

    def _chain_tab_order(self):
        fields = [self.rows[name].field for name in self.order]
        for first, second in zip(fields, fields[1:]):
            QtGui.QWidget.setTabOrder(first, second)

    def _apply_row(self, entry, row):
        entry.row = row
        item, field, name = entry.item, entry.field, entry.name
        evaluation = self.evaluation_state
        formula = bool(row.get("expression"))
        failing = row.get("status") == "invalid" or bool(evaluation and evaluation.get("name") == name)
        name_text = name + ("  !" if failing else "")
        if item.text(0) != name_text:
            item.setText(0, name_text)
        item.setData(0, QtCore.Qt.ForegroundRole, QtGui.QBrush(QtGui.QColor(COLORS["error"])) if failing else None)
        unit = unit_text(row)
        if item.text(2) != unit:
            item.setText(2, unit)
            item.setForeground(2, QtGui.QBrush(QtGui.QColor(COLORS["muted"])))
        field.supported = row.get("type") in TYPES
        field.formula = formula
        field.row = row
        field.set_formula_marker(formula)
        _set_property(field, "stale", "true" if formula and evaluation else "false")
        field.setReadOnly(not (self.editable and field.supported))
        display = format_number(row.get("native_value"))
        accepted = "=" + str(row["expression"]) if formula else display
        field.display_text = display
        if field.committing:
            field.accepted_text = accepted
            self._clean(field)
            field.show_resting_text()
        elif not field.edited:
            field.accepted_text = accepted
            field.show_resting_text()
        else:
            had_conflict = field.conflict
            previous = field.accepted_text
            field.accepted_text = accepted
            if field.conflict and (not had_conflict or previous != accepted):
                self._show_conflict(field)
            elif had_conflict and not field.conflict:
                self._conflict_resolved(field)

    # -- retire -----------------------------------------------------------

    def _retire(self, entry, reason):
        field = entry.field
        if field.retired:
            return
        edited = field.edited
        field.retired = True
        field.blockSignals(True)
        self._pending = [pending for pending in self._pending if pending.field is not field]
        if edited and reason:
            self.adapter.notify(f"Unapplied edit to {entry.name} discarded: {reason}")

    def _retire_all(self, reason):
        for name in list(self.order):
            entry = self.rows.get(name)
            if entry is not None:
                self._retire(entry, reason)
        self._pending = []

    # -- notes ------------------------------------------------------------

    def _show_line(self, text, severity="error"):
        _set_property(self.error, "severity", severity)
        self.error.setText(text)
        self.error.setToolTip(text)
        self.error.setMaximumHeight(self._note_height(self.error))
        if self.error.isHidden():
            self.error.show()
            self.updateGeometry()

    def _hide_line(self):
        if not self.error.isHidden():
            self.error.hide()
            self.error.clear()
            self.updateGeometry()

    def _show_banner(self):
        evaluation = self.evaluation_state
        if not evaluation:
            if not self.banner.isHidden():
                self.banner.hide()
                self.updateGeometry()
            return
        if evaluation["kind"] == "touched":
            text = "Parameters changed outside KurtShape · Rebuild to re-evaluate"
        else:
            failing = ""
            if evaluation.get("name"):
                failing = " · " + evaluation["name"] + (": " + evaluation["message"] if evaluation.get("message") else "")
            elif evaluation.get("message"):
                failing = " · " + evaluation["message"]
            text = "Parameters not fully evaluated" + failing + " · Rebuild to re-evaluate"
        self.banner.setText(text)
        self.banner.setToolTip(text)
        self.banner.setMaximumHeight(self._note_height(self.banner))
        if self.banner.isHidden():
            self.banner.show()
            self.updateGeometry()

    def _accepted_display(self, field):
        unit = unit_text(field.row or {})
        return field.display_text + (" " + unit if unit else "")

    def _typed_display(self, field, text):
        unit = unit_text(field.row or {})
        try:
            float(text)
        except ValueError:
            return text
        return text + (" " + unit if unit else "")

    def _show_conflict(self, field):
        typed = self._typed_display(field, field.text().strip())
        accepted = self._accepted_display(field)
        field.note = field.conflict_note = (f"{field.name} changed elsewhere to {accepted} · "
                                            f"Enter applies {typed}, Esc takes {accepted}")
        self._show_line(field.note, "warning")

    def _conflict_resolved(self, field):
        """The value went back to what the edit started from: the conflict note no longer applies."""
        note, field.conflict_note = field.conflict_note, None
        if note is None:
            return
        if field.note == note:
            field.note = None
        if self.error.text() == note:
            self._hide_line()

    # -- field events -----------------------------------------------------

    def _field_focused(self, field, reason):
        self.set_editable()
        entry = self.rows.get(field.name)
        if entry is not None and entry.field is field:
            self.tree.setCurrentItem(entry.item, 0, QtCore.QItemSelectionModel.ClearAndSelect)
        if field.property("validation") == "pending":
            _set_property(field, "validation", "")
            field.note = None
        if not field.edited:
            field.target = (self.document_id, field.name)
            if field.text() != field.accepted_text:
                field.setText(field.accepted_text)
            field.selectAll()
            if reason == QtCore.Qt.MouseFocusReason:
                # The mouse release would collapse the selection again.
                QtCore.QTimer.singleShot(0, field, field.selectAll)

    def _field_unfocused(self, field, reason):
        if field.edited:
            if reason in COMMIT_REASONS:
                self.commit(field, explicit=False)
            elif field.property("validation") != "invalid":
                _set_property(field, "validation", "pending")
                field.note = PENDING_NOTE
        if not field.edited:
            field.show_resting_text()

    def focus_adjacent(self, field, step):
        if field.name not in self.order:
            return False
        index = self.order.index(field.name) + step
        if not 0 <= index < len(self.order):
            return False
        self.rows[self.order[index]].field.setFocus(QtCore.Qt.TabFocusReason)
        return True

    # -- commits ----------------------------------------------------------

    def _clean(self, field):
        field.edited = False
        field.base_text = None
        field.rejected = None
        field.note = None
        field.conflict_note = None
        _set_property(field, "validation", "")

    def _unchanged(self, field, request):
        """A literal equal to the stored literal: 3a asks the panel not to send it."""
        if field.formula or request.expression is not None or request.expected_native is None:
            return False
        try:
            current = float((field.row or {}).get("native_value"))
        except (TypeError, ValueError):
            return False
        return abs(current - request.expected_native) <= 1e-12 * max(1.0, abs(current))

    def _prepare(self, field, explicit):
        """Decide one commit synchronously. Returns a _Pending, or None when nothing is sent."""
        if field.retired or self.closing or not field.edited:
            return None
        text = field.text().strip()
        if text == field.accepted_text:
            self._clean(field)
            return None
        if not explicit:
            if field.conflict:
                self._show_conflict(field)
                return None
            if field.rejected is not None and field.rejected.text == text and not field.rejected.transient:
                return None
        request = normalize_value((field.row or {}).get("type"), text, field.formula)
        if isinstance(request, LocalError):
            self._reject(field, text, Outcome(False, "local_error", request.message, request.field), keep_focus=False)
            return None
        if self._unchanged(field, request):
            self._clean(field)
            if not field.hasFocus():
                field.show_resting_text()
            return None
        reason = self.adapter.blocker()
        if reason:
            self._reject(field, text, Outcome(False, "blocked", reason, None, True), keep_focus=False)
            return None
        document_id = field.target[0] if field.target else self.document_id
        tokens = {"_document_id": document_id, "_expected_revision": self.adapter.revision()}
        return _Pending(field, request, tokens, explicit, text)

    def _scheduled(self, field):
        return next((pending for pending in self._pending if pending.field is field), None)

    def commit(self, field, explicit):
        """Decide now; dispatch from a zero-delay timer bound to this section.

        A field has at most one scheduled commit. A later decision for the same
        text (a second Enter, the click that follows Enter) joins it and only
        records whether the user is still in the field; new text replaces it.
        A commit already in flight settles the field itself.
        """
        if field.committing:
            return False
        scheduled = self._scheduled(field)
        if scheduled is not None:
            if not (field.retired or self.closing) and field.edited and field.text().strip() == scheduled.text:
                scheduled.explicit = explicit
                return True
            self._pending.remove(scheduled)
        pending = self._prepare(field, explicit)
        if pending is None:
            return False
        self._pending.append(pending)
        QtCore.QTimer.singleShot(0, self, self._run_pending)
        return True

    def _run_pending(self):
        while self._pending and not self.closing:
            pending = self._pending.pop(0)
            decided = pending.tokens.get("_expected_revision")
            outcome = self._execute(pending)
            if outcome is not None and outcome.ok:
                self._advance(decided, pending.tokens.get("_document_id"))

    def _advance(self, decided, document_id):
        """Later scheduled commits decided on the same revision follow this section's own edit."""
        current = self.adapter.revision()
        if decided is None or current is None or current == decided:
            return
        for later in self._pending:
            tokens = later.tokens
            if tokens.get("_expected_revision") == decided and tokens.get("_document_id") == document_id:
                tokens["_expected_revision"] = current

    def _execute(self, pending):
        field = pending.field
        if self.closing or field.retired:
            return None
        if not field.edited or field.text().strip() != pending.text:
            # Escape, a refresh or newer typing settled the field after the decision.
            return None
        reason = self.adapter.blocker()
        if reason:
            # A tool or dialog opened between the decision and the dispatch.
            outcome = Outcome(False, "blocked", reason, None, True)
            self._reject(field, pending.text, outcome, keep_focus=False)
            return outcome
        field.committing = True
        try:
            outcome = self.adapter.set_value(field.name, pending.request, pending.tokens)
        finally:
            field.committing = False
        if field.retired:
            if not outcome.ok:
                self._show_line(f"{field.name}: {outcome.message}", "error")
            return outcome
        if outcome.ok:
            self._committed(field, pending)
        else:
            self._reject(field, pending.text, outcome, keep_focus=pending.explicit)
        return outcome

    def _committed(self, field, pending):
        self._clean(field)
        field.show_resting_text()
        self._hide_line()
        expected = pending.request.expected_native
        try:
            actual = float((field.row or {}).get("native_value"))
        except (TypeError, ValueError):
            actual = None
        if expected is not None and actual is not None \
                and abs(actual - expected) > CLAMP_TOLERANCE * max(1.0, abs(expected)):
            unit = unit_text(field.row or {})
            suffix = " " + unit if unit else ""
            message = (f"{field.name} stored as {format_number(actual)}{suffix} "
                       f"(requested {format_number(expected)}{suffix})")
            self._show_line(message, "warning")
            self.adapter.notify(message, "warning")
        if self.adapter.rolled_back():
            usage = self.adapter.usage(field.name) or {}
            held = sum(1 for entry in usage.get("used_by") or () if entry.get("held"))
            if held:
                self.adapter.notify(f"{COMMITTED} · {held} uses after the rollback bar are checked "
                                    "when you roll forward")

    def _reject(self, field, text, outcome, keep_focus):
        field.rejected = Rejection(text, outcome.code, outcome.transient, outcome.message)
        _set_property(field, "validation", "invalid")
        accepted = self._accepted_display(field)
        field.note = f"Not applied: {outcome.message}. Esc restores {accepted}"
        self._show_line(f"{field.name}: {outcome.message} · kept {accepted}", "error")
        if outcome.refresh:
            self.refresh(force=True)
        if keep_focus and not field.retired:
            if not field.hasFocus():
                field.setFocus(QtCore.Qt.OtherFocusReason)
            field.selectAll()

    def revert(self, field):
        """Escape: restore the accepted value without dispatching."""
        if field.retired or not (field.edited or field.rejected is not None):
            return False
        # A commit decided but not yet dispatched is discarded with the edit.
        self._pending = [pending for pending in self._pending if pending.field is not field]
        self._clean(field)
        field.setText(field.accepted_text if field.hasFocus() else field.display_text)
        if field.hasFocus():
            field.selectAll()
        self._hide_line()
        return True

    def unapplied(self):
        """C25: a row whose field holds an edit that was not applied (edited or rejected, not retired)."""
        return any(not entry.field.retired and (entry.field.edited or entry.field.rejected is not None)
                   for entry in self.rows.values())

    def cancel_edit(self):
        """For the ``general.cancel`` wrapper: True only when it reverted a focused parameter field."""
        widget = QtGui.QApplication.focusWidget()
        if not isinstance(widget, ParameterValueEdit) or widget.section is not self:
            return False
        return self.revert(widget)

    def flush_pending(self):
        """Apply any pending edit before Save/Export/New/Open/switch/Close; False refuses the action."""
        if self.closing:
            return True
        if self._pending:
            self._run_pending()
            self.refresh()  # a stale_revision answer re-inspected the model: compare against what stands now
        for name in list(self.order):
            entry = self.rows.get(name)
            if entry is None:
                continue
            field = entry.field
            if field.retired or not field.edited:
                continue
            text = field.text().strip()
            if text == field.accepted_text:
                self._clean(field)
                field.show_resting_text()
                continue
            refusal = f"Apply or discard the edit to {name} first · Enter applies, Esc discards"
            if field.conflict or (field.rejected is not None and field.rejected.text == text
                                  and not field.rejected.transient):
                self._show_line(refusal, "error")
                self.adapter.notify(refusal, "error")
                return False
            pending = self._prepare(field, explicit=True)
            if pending is None:
                if field.edited and not field.retired:
                    # A local error or a blocker: the reason is on the error line.
                    self.adapter.notify(refusal, "error")
                    return False
                continue
            outcome = self._execute(pending)
            if outcome is None or not outcome.ok:
                return False
        return True

    def close(self):
        """Panel shutdown: no further commits run, and the dialog closes."""
        self.closing = True
        self._pending = []
        if self.dialog is not None:
            dialog, self.dialog = self.dialog, None
            try:
                dialog.reject()
            except RuntimeError:  # already deleted with the main window
                pass

    # -- selection and tooltips ------------------------------------------

    def current_name(self):
        item = self.tree.currentItem()
        return item.data(0, QtCore.Qt.UserRole) if item is not None else None

    def owns_focus(self):
        widget = QtGui.QApplication.focusWidget()
        return widget is not None and (widget is self.tree or widget is self.tree.viewport())

    def select(self, name, focus_value=False):
        entry = self.rows.get(name)
        if entry is None or entry.field.retired:
            return False
        self.tree.setCurrentItem(entry.item, 0, QtCore.QItemSelectionModel.ClearAndSelect)
        self.tree.scrollToItem(entry.item)
        if focus_value:
            entry.field.setFocus(QtCore.Qt.OtherFocusReason)
        return True

    def focus_current_field(self):
        name = self.current_name()
        return self.select(name, focus_value=True) if name else False

    def tooltip(self, name, field=None):
        entry = self.rows.get(name)
        if entry is None or entry.row is None:
            return ""
        row = entry.row
        kind = row.get("type")
        unit = unit_text(row)
        lines = []
        if kind in TYPES:
            lines.append(f"{name} · {TYPE_DESCRIPTIONS[kind]}")
        else:
            lines.append(f"{name} · Unsupported native type {row.get('native_type') or kind}")
        lines.append("Value: " + format_number(row.get("native_value")) + (" " + unit if unit else ""))
        if row.get("expression"):
            lines.append("Formula: = " + str(row["expression"]))
        if row.get("expression_ref"):
            lines.append("Use in feature formulas as " + str(row["expression_ref"]))
        usage = self.adapter.usage(name)
        if usage is not None:
            used_by = usage.get("used_by") or []
            lines.append("Used by: " + (", ".join(entry["label"] for entry in used_by) if used_by else "nothing yet"))
            if usage.get("used_by_parameters"):
                lines.append("Used by parameters: " + ", ".join(usage["used_by_parameters"]))
            affects = list(usage.get("affects") or ())
            if affects:
                shown = ", ".join(affects[:AFFECTS_SHOWN]) + (", …" if len(affects) > AFFECTS_SHOWN else "")
                parts = usage.get("parts") or []
                lines.append(f"Affects: {shown} ({len(affects)} features)"
                             + (" in " + ", ".join(parts) if parts else ""))
        evaluation = self.evaluation_state
        if evaluation and row.get("expression"):
            lines.append(STALE_NOTE)
        if row.get("status") == "invalid" or (evaluation and evaluation.get("name") == name):
            message = first_line(row.get("error")) or (evaluation or {}).get("message") or ""
            lines.append("Not evaluated" + (": " + message if message else ""))
        if field is not None and field.note:
            lines.append(field.note)
        return "\n".join(lines)

    # -- actions ----------------------------------------------------------

    def _check_action(self):
        if not self.flush_pending():
            return False
        self.set_editable()
        if not self.editable:
            self.adapter.notify(self.block_reason or NO_DOCUMENT)
            return False
        return True

    def add_parameter(self):
        if self.dialog is not None or not self._check_action():
            return None
        return self._open_dialog(ParameterDialog(self, "add"))

    def rename_current(self):
        name = self.current_name()
        if not name:
            self.adapter.notify("Select a parameter to rename.")
            return None
        return self.rename(name)

    def rename(self, name):
        if self.dialog is not None or not self._check_action() or name not in self.rows:
            return None
        return self._open_dialog(ParameterDialog(self, "rename", name))

    def _open_dialog(self, dialog):
        self.dialog = dialog
        dialog.finished.connect(lambda *args, dialog=dialog: self._dialog_finished(dialog))
        dialog.open()
        return dialog

    def _dialog_finished(self, dialog):
        if self.dialog is dialog:
            self.dialog = None
        dialog.deleteLater()

    def _reject_dialog(self, message):
        dialog, self.dialog = self.dialog, None
        if dialog is not None:
            dialog.reject()
            self.adapter.notify(message)

    def _dialog_succeeded(self, name, focus_value):
        QtCore.QTimer.singleShot(0, self, lambda: self.select(name, focus_value=focus_value))

    def delete_current(self):
        name = self.current_name()
        if not name:
            self.adapter.notify("Select a parameter to delete.")
            return None
        return self.delete(name)

    def delete(self, name):
        if not self._check_action() or name not in self.rows:
            return None
        usage = self.adapter.usage(name)
        tokens = {"_document_id": self.document_id, "_expected_revision": self.adapter.revision()}
        if usage is not None and not usage.get("used_by") and not usage.get("used_by_parameters"):
            outcome = self.adapter.delete(name, False, tokens)
        else:
            consumers = None if usage is None else (
                [entry["label"] for entry in usage.get("used_by") or ()]
                + [parameter + " (formula)" for parameter in usage.get("used_by_parameters") or ()])
            if not self._confirm_delete(name, consumers):
                return None
            outcome = self.adapter.delete(name, True, tokens)
        if not outcome.ok:
            self._show_line(f"{name}: {outcome.message}", "error")
        return outcome

    def _confirm_delete(self, name, consumers):
        box = QtGui.QMessageBox(self.window())
        box.setIcon(QtGui.QMessageBox.Warning)
        box.setWindowTitle("Delete parameter")
        if consumers is None:
            listed = "Its uses could not be listed."
        else:
            listed = "\n".join(consumers[:CONSUMERS_SHOWN])
            if len(consumers) > CONSUMERS_SHOWN:
                listed += f"\n… and {len(consumers) - CONSUMERS_SHOWN} more"
        box.setText(f"{name} is used by:\n\n{listed}\n\nTheir current values are kept; the formulas that read {name} are removed.")
        delete = box.addButton("Delete and keep current values", QtGui.QMessageBox.AcceptRole)
        cancel = box.addButton(QtGui.QMessageBox.Cancel)
        box.setDefaultButton(cancel)
        box.exec()
        return box.clickedButton() is delete

    def copy_reference(self, name=None):
        name = name or self.current_name()
        entry = self.rows.get(name) if name else None
        if entry is None:
            self.adapter.notify("Select a parameter to copy its reference.")
            return True
        reference = (entry.row or {}).get("expression_ref")
        if not reference:
            self.adapter.notify(f"{name} has no reference to copy.")
            return True
        QtGui.QApplication.clipboard().setText(str(reference))
        self.adapter.notify(f"Copied {reference} · paste into a feature's Formula field")
        return True

    def paste(self):
        self.adapter.notify("Paste into a parameter value field")
        return True

    def replace_formula(self, name):
        """One request {value: '<native_value> <unit>', expression: None}."""
        entry = self.rows.get(name)
        if entry is None or not entry.field.formula or not self._check_action():
            return None
        row = entry.row or {}
        try:
            native = float(row.get("native_value"))
        except (TypeError, ValueError):
            return None
        native_unit = row.get("native_unit") or ""
        value = f"{native!r} {native_unit}".strip() if native_unit else native
        request = Request(value=value, clears_formula=True, expected_native=native)
        tokens = {"_document_id": self.document_id, "_expected_revision": self.adapter.revision()}
        outcome = self.adapter.set_value(name, request, tokens)
        if not outcome.ok:
            self._show_line(f"{name}: {outcome.message}", "error")
        return outcome

    def _double_clicked(self, item, column):
        name = item.data(0, QtCore.Qt.UserRole)
        if name and column == 0:
            self.rename(name)

    def _context_menu(self, position):
        if not self.flush_pending():
            return
        menu = self.build_context_menu(position)
        menu.exec(self.tree.viewport().mapToGlobal(position))
        menu.deleteLater()

    def build_context_menu(self, position):
        """The parameter context menu, built after any pending edit has been applied."""
        menu = QtGui.QMenu(self.tree)
        item = self.tree.itemAt(position)
        name = item.data(0, QtCore.Qt.UserRole) if item is not None else None
        self.set_editable()
        if not name:
            add = menu.addAction("Add parameter…")
            add.setEnabled(bool(self.editable) and self.document_id is not None)
            add.triggered.connect(self.add_parameter)
            return menu
        self.tree.setCurrentItem(item, 0, QtCore.QItemSelectionModel.ClearAndSelect)
        entry = self.rows[name]
        copy_action = menu.addAction("Copy reference")
        copy_action.setEnabled(bool((entry.row or {}).get("expression_ref")))
        copy_action.triggered.connect(lambda checked=False, name=name: self.copy_reference(name))
        # Parented explicitly: a submenu returned by addMenu(str) is Python-owned
        # and would be collected before the menu runs.
        used = QtGui.QMenu("Used by", menu)
        menu.addMenu(used)
        usage = self.adapter.usage(name) or {}
        for consumer in usage.get("used_by") or ():
            action = used.addAction(consumer["label"])
            action.triggered.connect(lambda checked=False, consumer=consumer:
                                     self.adapter.show_use(consumer["feature"], consumer.get("parameter")))
        for parameter in usage.get("used_by_parameters") or ():
            action = used.addAction(parameter + " (formula)")
            action.triggered.connect(lambda checked=False, parameter=parameter: self.select(parameter))
        if used.isEmpty():
            used.addAction("Not used yet").setEnabled(False)
        if entry.field.formula:
            replace = menu.addAction("Replace formula with value")
            replace.setEnabled(bool(self.editable))
            replace.triggered.connect(lambda checked=False, name=name: self.replace_formula(name))
        menu.addSeparator()
        rename = menu.addAction("Rename…")
        rename.setEnabled(bool(self.editable))
        rename.triggered.connect(lambda checked=False, name=name: self.rename(name))
        delete = menu.addAction("Delete…")
        delete.setEnabled(bool(self.editable))
        delete.triggered.connect(lambda checked=False, name=name: self.delete(name))
        return menu


class ParameterDialog(QtGui.QDialog):
    """Add (name, type, value) or rename (name only); window-modal, opened with open()."""

    def __init__(self, section, mode="add", name=None):
        super().__init__(section.window())
        self.setObjectName("KurtShapeParameterDialog")
        self.setWindowTitle("Add parameter" if mode == "add" else "Rename parameter")
        self.setWindowModality(QtCore.Qt.WindowModal)
        self.section = section
        self.adapter = section.adapter
        self.mode = mode
        self.original = name
        self.document_id = section.document_id
        self.submitting = False
        self.created_name = None
        pattern = self.adapter.name_pattern()
        self._pattern = re.compile(pattern) if pattern else None
        layout = QtGui.QVBoxLayout(self)
        form = QtGui.QFormLayout()
        self.name_edit = QtGui.QLineEdit(name or "")
        self.name_edit.setObjectName("KurtShapeParameterName")
        self.name_edit.setPlaceholderText("shaft_diameter")
        self.name_edit.setAccessibleName("Parameter name")
        form.addRow("Name", self.name_edit)
        self.type_choice = self.value_edit = None
        if mode == "add":
            self.type_choice = QtGui.QComboBox()
            self.type_choice.setObjectName("KurtShapeParameterType")
            for kind, label in TYPE_CHOICES:
                self.type_choice.addItem(label, kind)
            self.type_choice.currentIndexChanged.connect(self._type_changed)
            form.addRow("Type", self.type_choice)
            self.value_edit = QtGui.QLineEdit(DEFAULT_VALUES["length"])
            self.value_edit.setObjectName("KurtShapeParameterInitialValue")
            self.value_edit.setPlaceholderText("10 or =formula")
            self.value_edit.setAccessibleName("Parameter value")
            form.addRow("Value", self.value_edit)
        layout.addLayout(form)
        if mode == "rename":
            note = QtGui.QLabel("Formulas that use it are updated")
            note.setObjectName("KurtShapeParameterRenameNote")
            layout.addWidget(note)
        self.message = QtGui.QLabel()
        self.message.setObjectName("KurtShapeParameterDialogError")
        self.message.setProperty("severity", "error")
        self.message.setWordWrap(True)
        self.message.setTextFormat(QtCore.Qt.PlainText)
        self.message.hide()
        layout.addWidget(self.message)
        buttons = QtGui.QDialogButtonBox()
        self.accept_button = buttons.addButton("Add" if mode == "add" else "Rename", QtGui.QDialogButtonBox.AcceptRole)
        self.accept_button.setDefault(True)
        self.accept_button.setAutoDefault(True)
        cancel = buttons.addButton(QtGui.QDialogButtonBox.Cancel)
        self.accept_button.clicked.connect(self.submit)
        cancel.clicked.connect(self.reject)
        layout.addWidget(buttons)
        self.name_edit.textChanged.connect(self._validate_name)
        self._validate_name()
        self.name_edit.setFocus(QtCore.Qt.OtherFocusReason)
        self.name_edit.selectAll()

    def _type_changed(self, *args):
        if self.value_edit.text().strip() in DEFAULT_VALUES.values():
            self.value_edit.setText(DEFAULT_VALUES[self.type_choice.currentData()])

    def _show_message(self, text):
        self.message.setText(text or "")
        self.message.setVisible(bool(text))

    def _validate_name(self, *args):
        name = self.name_edit.text().strip()
        hint = None
        if not name or self.mode == "rename" and name == self.original:
            hint = ""
        elif self._pattern is not None and not self._pattern.fullmatch(name):
            hint = self.adapter.name_message("format", name) or "Invalid name"
        self.accept_button.setEnabled(hint is None)
        self._show_message(hint)
        return hint is None

    def submit(self):
        if self.submitting or not self._validate_name():
            return None
        name = self.name_edit.text().strip()
        if self.mode == "add":
            kind = self.type_choice.currentData()
            request = normalize_value(kind, self.value_edit.text(), False)
            if isinstance(request, LocalError):
                self._failed(request.message, "value")
                return None
        self.submitting = True
        try:
            tokens = {"_document_id": self.document_id}
            if self.mode == "add":
                outcome = self.adapter.create(name, kind, request, tokens)
            else:
                outcome = self.adapter.rename(self.original, name, tokens)
        finally:
            self.submitting = False
        if self.section.dialog is not self:
            return outcome  # closed while the command ran (project changed)
        if outcome.ok:
            self.created_name = name
            self.accept()
            self.section._dialog_succeeded(name, focus_value=self.mode == "add")
        else:
            self._failed(outcome.message, outcome.field)
        return outcome

    def _failed(self, message, field):
        self._show_message(message)
        target = self.name_edit if field == "name" or self.value_edit is None else self.value_edit
        target.setFocus(QtCore.Qt.OtherFocusReason)
        target.selectAll()


# --------------------------------------------------------------------------
# Layout persistence


class PreferenceStore:
    """The saved section heights in the private FreeCAD profile."""

    def __init__(self, group=LAYOUT_GROUP, key=LAYOUT_KEY):
        self.group, self.key = group, key

    def get(self):
        import FreeCAD as App
        return App.ParamGet(self.group).GetString(self.key, "")

    def set(self, text):
        import FreeCAD as App
        App.ParamGet(self.group).SetString(self.key, text)
        App.saveParameter()


class SectionLayout(QtCore.QObject):
    """Restore and persist the splitter's section heights.

    Moves are remembered in memory on every ``splitterMoved`` and written
    ``SAVE_DELAY_MS`` after the last one. ``flush()`` writes the remembered
    string without touching any Qt object, so it is safe while the window is
    being destroyed.
    """

    def __init__(self, splitter, store, defaults=DEFAULT_SIZES, delay=SAVE_DELAY_MS):
        super().__init__()
        self.splitter = splitter
        self.store = store
        self.defaults = tuple(defaults)
        self._text = None
        self._dirty = False
        self.writes = 0
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(delay)
        self.timer.timeout.connect(self.save)
        splitter.splitterMoved.connect(self._moved)

    def parse(self, text):
        try:
            sizes = [int(part) for part in str(text).split(",")]
        except (TypeError, ValueError):
            return None
        if len(sizes) != self.splitter.count() or any(not 1 <= size <= MAX_SECTION_SIZE for size in sizes):
            return None
        return sizes

    def restore(self):
        """Apply the stored sizes, or the defaults; programmatic sizes never write."""
        sizes = self.parse(self.store.get())
        if sizes is None:
            if len(self.defaults) != self.splitter.count():
                return None
            sizes = list(self.defaults)
        self.splitter.setSizes(sizes)
        return sizes

    def _moved(self, *args):
        self._text = ",".join(str(size) for size in self.splitter.sizes())
        self._dirty = True
        self.timer.start()

    def save(self):
        if self._dirty and self._text:
            self.store.set(self._text)
            self._dirty = False
            self.writes += 1

    def flush(self):
        self.save()
