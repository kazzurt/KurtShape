"""Pure wording rules for the shell's feedback (slice A/B U7): errors, status, shortcuts, Messages.

No FreeCAD or Qt import: ``ui.py`` feeds these functions the controller's payloads and the
shortcut registry, and ``tests/test_feedback_ui.py`` pins them directly.
"""
from __future__ import annotations

import json



# --- Error details (C-03, H-02) -------------------------------------------------------------

REQUEST_FEATURE_KEYS = ("feature", "id", "profile", "sketch")


def failing_features(error, request=None):
    """Feature ids an error names, most specific first: ``feature``, ``features``, ``trigger``; then,
    for an error that names none of its own, the rejected request's ``feature``, ``id`` (the new
    feature), ``profile`` and ``sketch``."""
    error = error if isinstance(error, dict) else {}
    found = []

    def add(value):
        if isinstance(value, dict):
            value = value.get("feature") or value.get("id")
        if isinstance(value, str) and value and value not in found:
            found.append(value)

    add(error.get("feature"))
    features = error.get("features")
    for entry in features if isinstance(features, (list, tuple)) else ():
        add(entry)
    trigger = error.get("trigger")
    if isinstance(trigger, dict):
        add(trigger.get("feature"))
    if isinstance(request, dict):
        for key in REQUEST_FEATURE_KEYS:
            add(request.get(key))
    return found


def compose_error(error, names=None, prefix="", request=None):
    """The status line and the Messages entry for one rejected operation.

    ``names`` maps feature ids to history names. The status line is ``message · feature · code``
    (the feature omitted when neither the error nor the rejected ``request`` names one); the
    Messages entry starts with that line, adds one line per failing feature that carries its own
    message, the trigger and the hint, and ends with the payload's other fields as JSON. ``feature`` is the
    first candidate (``failing_features``); ``candidates`` are all of them, for the selection.
    """
    error = dict(error) if isinstance(error, dict) else {"message": str(error)}
    names = names or {}
    code = str(error.get("code") or "operation_failed")
    message = str(error.get("message") or "Operation failed").strip()
    candidates = failing_features(error, request)
    feature = candidates[0] if candidates else None
    label = names.get(feature, feature) if feature else None
    status = prefix + message + (" · " + str(label) if label else "") + " · " + code
    lines = [status]
    features = error.get("features")
    for entry in features if isinstance(features, (list, tuple)) else ():
        if isinstance(entry, dict) and entry.get("message"):
            ident = entry.get("feature") or entry.get("id") or "?"
            lines.append("  " + str(names.get(ident, ident)) + ": " + str(entry["message"]))
    trigger = error.get("trigger")
    if isinstance(trigger, dict) and trigger.get("op"):
        target = trigger.get("feature")
        lines.append("  while " + str(trigger["op"]) + (" on " + str(names.get(target, target)) if target else ""))
    if error.get("hint"):
        lines.append("  hint: " + str(error["hint"]))
    # Every field but the message, which the first line already carries (each failure is logged once).
    details = {key: value for key, value in error.items() if key != "message"}
    lines.append("  details: " + json.dumps(details, sort_keys=True, default=str, ensure_ascii=False))
    return {"status": status, "message": "\n".join(lines), "code": code, "feature": feature,
            "candidates": candidates}


# --- Honest status (A-10) ---------------------------------------------------------------------

REBUILD_REASONS = {"engine_changed": "geometry engine changed",
                   "saved_by_other_build": "saved by another application build",
                   "engine_unrecorded": "geometry engine not recorded",
                   "missing_shapes": "stored geometry is missing"}

# History rows the panel never lists; a document with nothing else is an empty part.
NON_HISTORY_TYPES = {"PartDesign::Body", "App::Point"}


def rebuild_reason_text(state):
    return REBUILD_REASONS.get((state or {}).get("rebuild_reason"), "pending model changes")


def _feature_label(state, identifier):
    for row in (state or {}).get("features", ()) or ():
        if row.get("id") == identifier:
            return row.get("name") or identifier
    return identifier


def status_text(state, editing=None):
    """(text, severity) for the document status line; severity is "", "warning" or "error".

    States, first match wins: failed (naming the first failing feature), editing a sketch
    (``editing`` or the state's ``active_sketch_edit``; never "Rebuild required", since a sketch
    under edit is always touched), needs rebuild, empty part, sketches only, valid solids.
    """
    state = state or {}
    status = state.get("build_status")
    checks = state.get("result_checks") or {}
    pending = " · checks pending" if checks.get("status") == "pending" else ""
    if editing is None:
        editing = bool(state.get("active_sketch_edit"))
    if status == "failed":
        failed = checks.get("failed") or []
        if failed:
            row = failed[0]
            more = " (+%d more)" % (len(failed) - 1) if len(failed) > 1 else ""
            return ("Result check failed · " + str(_feature_label(state, row.get("feature"))) + " · "
                    + str(row.get("code") or "failed") + more + " — see Messages", "error")
        errors = [row for row in state.get("build_errors") or () if isinstance(row, dict)]
        named = next((row for row in errors if row.get("feature")), None)
        if state.get("geometry_check") == "invalid":
            return "Invalid geometry" + (" · " + str(_feature_label(state, named["feature"])) if named else "") \
                + " — see Messages", "error"
        if named:
            more = " (+%d more)" % (len(errors) - 1) if len(errors) > 1 else ""
            return ("Build failed · " + str(_feature_label(state, named["feature"])) + ": "
                    + str(named.get("message") or named.get("code") or "error") + more, "error")
        return "Build failed — see Messages", "error"
    if editing:
        return "Editing sketch · mm", ""
    if status == "needs_rebuild":
        return "Rebuild required · " + rebuild_reason_text(state), "warning"
    measured = state.get("measurements")
    if not measured:
        rows = [row for row in state.get("features") or () if row.get("type") not in NON_HISTORY_TYPES]
        return ("Sketches only · mm" if rows else "Empty part · mm") + pending, ""
    detail = str(measured["solid_count"]) + " solid(s)"
    if measured.get("volume_mm3") is not None:
        detail += f" · {measured['volume_mm3']:,.2f} mm³"
    if state.get("geometry_check") == "valid":
        detail += " · checked"
    return detail + pending, ""


# --- Hover-label shortcuts (A-05) -------------------------------------------------------------

# Toolbar tools whose action is a registry callback rather than the native command they show.
TOOL_ACTIONS = {"New": "local.new", "Open": "local.open", "Save": "local.save", "Shortcuts": "general.help",
                "Undo": "general.undo", "Redo": "general.redo", "Sketch": "sketch.start",
                "Extrude": "feature.extrude", "Revolve": "feature.revolve", "Fit": "view.fit",
                "Normal": "view.normal", "3D": "view.isometric", "Show planes": "view.planes",
                "Insert": "assembly.insert", "Fixed": "assembly.fasten", "Joints": "assembly.mates",
                "Pierce": "sketch.pierce", "Use": "sketch.project"}
# Tools with no keyboard equivalent even though a registry entry shares their command (the editor's
# Confirm / Cancel symbols resolve Enter / Escape in ui.py, where the editor's mode is known).
NO_SHORTCUT = {"Rebuild", "Check geometry"}


def registry_shortcut(router, context, action=None, command=None):
    """The current key of ``action`` (else of the entry running native ``command``) in ``context``.

    ``router`` is the live ShortcutRouter (its ``entries`` and ``resolve``). Empty when the action is
    unavailable there, has no key or is shadowed by another binding of the same key (the hover label
    then shows no key rather than one that does something else).
    """
    for entry in router.entries or ():
        if action is not None:
            if entry.get("id") != action:
                continue
        elif not command or entry.get("native_command") != command:
            continue
        if entry.get("status") in {"unsupported", "pass_through"} or not entry.get("key"):
            continue
        if router.resolve(entry["key"], context) is entry:
            return entry["key"]
    return ""


def tool_shortcut(router, context, label, command=None):
    """The key a toolbar tool's hover label shows: its registry action, else its native command's."""
    if label in NO_SHORTCUT:
        return ""
    action = TOOL_ACTIONS.get(label)
    if action is not None:
        return registry_shortcut(router, context, action=action)
    return registry_shortcut(router, context, command=command)


# --- Messages dot by severity (A-08) ----------------------------------------------------------

SEVERITIES = ("info", "warning", "error")


def native_severity(colors, error_color, warning_color):
    """Severity of a native report fragment from the text colors FreeCAD's report view used."""
    found = {str(color).lower() for color in colors or ()}
    if error_color and str(error_color).lower() in found:
        return "error"
    if warning_color and str(warning_color).lower() in found:
        return "warning"
    return "info"


class UnreadMessages:
    """Unread Messages lines and the warnings/errors among them that light the dot.

    Every line that arrives while the dock is hidden is unread (the hover help counts them);
    only warnings and errors light the dot, and lines that belong to the startup backlog count
    as neither.
    """

    def __init__(self):
        self.count = 0
        self.alerts = 0
        self.startup = True

    @property
    def dot(self):
        return self.alerts > 0

    def end_startup(self):
        self.startup = False

    def add(self, severity="info", visible=False):
        """Count one arriving line; True when it counts as unread."""
        if visible or self.startup:
            return False
        self.count += 1
        if severity in {"warning", "error"}:
            self.alerts += 1
        return True

    def escalate(self, severity, visible=False):
        """A line ``add`` counted as unread (info) turned out to be a warning or error: native report
        lines are classified after they arrive. Nothing changes once the lines were seen."""
        if not visible and self.count and severity in {"warning", "error"}:
            self.alerts += 1

    def seen(self):
        self.count = self.alerts = 0

    def button_text(self):
        return "Messages" + (" •" if self.dot else "")

    def tooltip(self, visible):
        if visible:
            return "Hide messages"
        text = "Show messages"
        if self.count:
            text += " · " + str(self.count) + " unread"
        if self.alerts:
            text += " · " + str(self.alerts) + (" warning or error" if self.alerts == 1 else " warnings or errors")
        return text
