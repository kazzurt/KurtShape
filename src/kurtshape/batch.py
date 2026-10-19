"""Contract 3.2 F4: atomic batches of modeling operations (``batch`` and ``preview`` of a batch).

A batch runs 1-32 typed modeling steps inside **one** native transaction: one undo step and
one revision change when it is accepted, nothing at all when any step (or the final result
validation) fails. Steps run through ``Controller._model_step`` -- the same per-step gates
as single operations -- and never open, commit or abort transactions, rotate the revision,
sync or inspect. Feature 1's result validation runs once, over the whole batch window, before
the commit (decision D7), so "change, then repair" sequences are accepted.

Steps reference earlier steps by alias (``"as"``): ``{"$ref": alias}`` is that step's
created feature, ``{"$part": alias}`` its single output part. Only whole values are
substituted; feature ids inside expression strings must be explicit ids.

``OPS`` is derived: every model operation except ``EXCLUDED`` (the one hand-kept list, each
with its reason). ``SplitGuard`` detects a step that broke the batch transaction and undoes
what it can, reporting ``transaction_split`` honestly.
"""
from __future__ import annotations

import copy
import json
import re
import time

import FreeCAD as App

MAX_STEPS = 32
MAX_DEPTH = 64
MAX_LABEL = 80
ALIAS_PATTERN = r"^[A-Za-z][A-Za-z0-9_]{0,31}$"
REFERENCE_KEYS = ("$ref", "$part")
FAILURE_RECORD_BYTES = 2048
DISCARD_BOUNDARY = "KurtShape: discarded failed batch"
_DELETE = "A cascade removes other native objects and helpers; review it as its own undoable step (delete_features_plan)"
_PARAMETER_IDENTITY = ("Native abort and undo restore a parameter wrongly when one transaction changes its identity "
                       "more than once; run it as its own request")
EXCLUDED = {
    "rebuild": "Whole-document revalidation; every step already rebuilds",
    "rollback": "Moves the insertion bar mid-batch; roll back before or after the batch",
    "delete_feature": _DELETE,
    "delete_features": _DELETE,
    "repair_orphan_helpers": "Maintenance cleanup, not modeling",
    "duplicate_feature": "The GUI clipboard workflow with its own pending-transaction rule",
    "rename_parameter": _PARAMETER_IDENTITY,
    "delete_parameter": _PARAMETER_IDENTITY,
}
# Ops whose handler creates no feature: a {"$ref"} to them is refused before anything runs.
NO_FEATURE = frozenset({"add_rectangle", "add_circle", "add_line", "add_arc", "add_polyline", "set_parameter",
                        "set_expression", "edit_extrusion", "edit_dress_up", "set_sketch_support", "pierce",
                        "project_geometry", "rename_feature", "create_parameter", "edit_parameter"})
# Ops whose created feature is never a part: a {"$part"} to them is refused before anything runs.
NO_PART = NO_FEATURE | frozenset({"create_sketch", "sketch_rectangle", "sketch_circle", "create_plane", "create_helix"})


def operations():
    """``Controller.MODEL_OPS`` minus ``EXCLUDED`` (computed on use: core imports this module)."""
    from .core import Controller
    return frozenset(Controller.MODEL_OPS) - frozenset(EXCLUDED)


def __getattr__(name):
    if name == "OPS":
        return operations()
    raise AttributeError(name)


def _error(code, message, **details):
    from .core import OperationError
    return OperationError(code, message, **details)


def capabilities():
    return {"operation": "batch", "operations": sorted(operations()), "excluded": dict(EXCLUDED), "max_steps": MAX_STEPS,
            "references": {"$ref": "the created feature of an earlier step with that \"as\" alias",
                           "$part": "the single output part id of an earlier step with that \"as\" alias"},
            "undo": "one native undo step", "preview": "preview with proposal {op:\"batch\", steps, label?}",
            "validation": "per-step gates, then result checks once before the commit"}


# --------------------------------------------------------------------------- validation (before any mutation)

def _check_refs(value, aliases, path, depth, where):
    if depth > MAX_DEPTH:
        raise _error("invalid_argument", "Step values nest too deeply", fields=["steps"], path=path, batch=where)
    if isinstance(value, dict):
        special = [key for key in value if isinstance(key, str) and key.startswith("$")]
        if special:
            if len(value) != 1 or special[0] not in REFERENCE_KEYS or not isinstance(value[special[0]], str):
                raise _error("invalid_argument", "A reference is {\"$ref\": alias} or {\"$part\": alias}", fields=["steps"],
                             path=path, batch=where)
            kind, alias = special[0], value[special[0]]
            if alias not in aliases:
                raise _error("invalid_step_reference", "Unknown, forward or self reference " + repr(alias)[:40],
                             reference={kind: alias}, path=path, batch=where)
            source = aliases[alias]
            if kind == "$ref" and source in NO_FEATURE or kind == "$part" and source in NO_PART:
                raise _error("invalid_step_reference", "Step " + repr(alias)[:40] + " (" + source + ") creates no "
                             + ("feature" if kind == "$ref" else "part"), reference={kind: alias}, path=path, batch=where)
            return
        for key, item in value.items():
            _check_refs(item, aliases, path + "." + str(key), depth + 1, where)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _check_refs(item, aliases, path + "[" + str(index) + "]", depth + 1, where)


def validate(controller, request):
    """Structural checks of a batch request (or batch proposal); returns the steps. Raises before any mutation."""
    from . import operation_schemas
    from .contract import REQUEST_SIZE_LIMIT
    label = request.get("label")
    if label is not None and (not isinstance(label, str) or not 1 <= len(label) <= MAX_LABEL or not label.isprintable()):
        raise _error("invalid_argument", "label has 1 to 80 printable characters", fields=["label"])
    steps = request.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS or not all(isinstance(step, dict) for step in steps):
        raise _error("invalid_argument", "steps is a list of 1 to %d step objects" % MAX_STEPS, fields=["steps"])
    try:
        size = len(json.dumps(steps, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError):
        raise _error("invalid_argument", "steps must be JSON values", fields=["steps"]) from None
    if size > REQUEST_SIZE_LIMIT:
        raise _error("request_too_large", "The steps exceed the request size limit", bytes=size, limit=REQUEST_SIZE_LIMIT)
    allowed = operations()
    aliases, ids = {}, {}
    for index, step in enumerate(steps):
        op = step.get("op")
        where = {"step": index, "op": op[:64] if isinstance(op, str) else None}
        if not isinstance(op, str) or op not in allowed:
            reason = (EXCLUDED.get(op) if isinstance(op, str) and op in EXCLUDED else "Batches do not nest" if op == "batch"
                      else "Only modeling operations can be batched")
            raise _error("unsupported_operation", "Step %d: %s cannot be batched" % (index, str(op)[:64]), reason=reason,
                         batch=where)
        transport = sorted(set(step) & controller.TRANSPORT_FIELDS)
        if transport:
            raise _error("unknown_argument", "Step %d carries request envelope fields" % index, fields=transport,
                         transport=transport, batch=where)
        unknown = sorted(set(step) - set(controller.ARGS[op]) - {"op", "as"})
        if unknown:
            raise _error("unknown_argument", "Unsupported step fields", fields=unknown, batch=where)
        alias = step.get("as")
        if alias is not None and (not isinstance(alias, str) or not re.fullmatch(ALIAS_PATTERN, alias) or alias in aliases):
            raise _error("invalid_argument", "as is a unique alias: a letter, then up to 31 letters, digits or underscores",
                         fields=["as"], batch=where)
        _check_refs({key: value for key, value in step.items() if key != "as"}, aliases, "steps[%d]" % index, 0, where)
        if isinstance(step.get("id"), str):
            if step["id"] in ids:
                raise _error("invalid_argument", "Duplicate id " + step["id"] + " in the batch", fields=["id"],
                             first_step=ids[step["id"]], batch=where)
            ids[step["id"]] = index
        absent, groups = operation_schemas.missing_arguments(op, step)
        if absent or groups:
            fields = list(absent or groups[0])
            raise _error("invalid_argument", "Step %d: missing required fields: %s" % (index, ", ".join(fields)),
                         fields=fields, one_of=bool(groups and not absent), reason="missing_required", batch=where)
        if alias is not None:
            aliases[alias] = op
    return steps


# --------------------------------------------------------------------------- execution

def transaction_name(request):
    label = request.get("label")
    return "KurtShape: batch " + label if label else "KurtShape: batch (%d steps)" % len(request["steps"])


def deadline(controller):
    budget = getattr(controller, "request_budget_s", None)
    return time.perf_counter() + budget if budget else None


def _budget_error(controller, deadline, message, steps_completed):
    budget = getattr(controller, "request_budget_s", None) or 0
    started = deadline - budget
    return _error("batch_time_budget_exceeded", message, steps_completed=steps_completed,
                  elapsed_ms=round((time.perf_counter() - started) * 1000, 1), budget_ms=round(budget * 1000, 1))


def resolve(value, outputs, path="step"):
    if isinstance(value, dict):
        if len(value) == 1 and next(iter(value)) in REFERENCE_KEYS and isinstance(next(iter(value.values())), str):
            kind, alias = next(iter(value.items()))
            output = outputs[alias]
            if kind == "$ref":
                if not output["feature"]:
                    raise _error("invalid_step_reference", "Step " + alias + " created no feature", reference=value, path=path)
                return output["feature"]
            if len(output["parts"]) != 1:
                raise _error("invalid_step_reference", "Step " + alias + " produced " + str(len(output["parts"]))
                             + " parts; $part needs exactly one", reference=value, path=path, parts=list(output["parts"]))
            return output["parts"][0]
        return {key: resolve(item, outputs, path + "." + str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve(item, outputs, path + "[" + str(index) + "]") for index, item in enumerate(value)]
    return copy.deepcopy(value)


def step_parts(doc, created):
    """Output part ids of a step's created object (``$part`` and the report rows)."""
    from . import studio
    from .bodies import owner
    obj = doc.getObject(created) if isinstance(created, str) else None
    if obj is None:
        return []
    names = getattr(obj, "KurtShapeOutputParts", None)
    if names:
        return [studio.part_id(doc.getObject(name)) for name in names if doc.getObject(name) is not None]
    if obj.TypeId == "PartDesign::Body":
        return [studio.part_id(obj)]
    body = owner(doc, obj)
    if (obj.TypeId.startswith("PartDesign::") and body is not None and obj.TypeId != "PartDesign::Body"
            and hasattr(obj, "Shape") and not obj.Shape.isNull() and obj.Shape.Solids):
        return [studio.part_id(body)]
    return []


def _wrap(controller, exc, index, step, resolved, rows, step_count, phase="step"):
    from .core import OperationError
    from . import assembly
    op = step.get("op")
    if isinstance(exc, KeyError):
        exc = controller._missing_field_error(exc, op, resolved or step) or exc
    if isinstance(exc, (OperationError, assembly.AssemblyError)):
        code, message, details = exc.code, str(exc), dict(getattr(exc, "details", {}) or {})
    else:
        controller._log_exception()
        code, message, details = "operation_failed", str(exc), {}
    details.pop("batch", None)
    error = OperationError(code, "Step %d (%s): %s" % (index, op, message), **details,
                           batch={"step": index, "op": op, "as": step.get("as"), "phase": phase,
                                  "steps_completed": len(rows), "step_count": step_count, "rolled_back": True,
                                  "step_request": resolved if resolved is not None else None})
    error.batch_rows = rows
    return error


def run(controller, doc, steps, *, transaction_id, window, deadline=None):
    """Run the steps in the open batch transaction; returns the report rows. Raises a step-attributed error."""
    from . import studio
    from .core import INTERNAL_REPORTS
    rows, outputs = [], {}
    for index, step in enumerate(steps):
        resolved = None
        try:
            if deadline is not None and index > 0 and time.perf_counter() > deadline:
                raise _budget_error(controller, deadline, "The batch exceeded its time budget; split it", index)
            resolved = resolve({key: value for key, value in step.items() if key != "as"}, outputs, "steps[%d]" % index)
            before = [obj.Name for obj in studio.order(doc)]
            began = time.perf_counter()
            outcome = controller._model_step(doc, resolved)
            active = (App.getActiveTransaction() or (None, None))[1]
            if active != transaction_id:
                raise _error("transaction_split", "The step left the batch transaction", active=bool(active))
            window.step_done(index)
            created = outcome.created_feature
            parts = step_parts(doc, created)
            row = {"index": index, "op": step["op"], "as": step.get("as"), "created_feature": created,
                   "features": [name for name in (obj.Name for obj in studio.order(doc)) if name not in before],
                   "parts": parts, "ms": round((time.perf_counter() - began) * 1000, 2)}
            row.update({key: value for key, value in outcome.reports.items() if key not in INTERNAL_REPORTS})
            # A finished step's parameter context must not name a later step's failure.
            controller._reports.pop("parameter_context", None)
            rows.append(row)
            if step.get("as") is not None:
                outputs[step["as"]] = {"feature": created, "parts": parts}
        except Exception as exc:
            error = _wrap(controller, exc, index, step, resolved, rows, len(steps))
            # A step that aborted or replaced the batch transaction before failing broke it too (F4 §3.6).
            error.split = (App.getActiveTransaction() or (None, None))[1] != transaction_id
            raise error from exc
    return rows


def finish_validation(controller, doc, window, rows, steps, deadline=None):
    """Feature 1's result checks once over the batch window; failures name the step that last changed the result."""
    from .core import OperationError
    if deadline is not None and time.perf_counter() > deadline:
        raise _final(_budget_error(controller, deadline, "The batch exceeded its time budget before its result checks",
                                   len(rows)), None, steps, rows)
    try:
        return window.finish()
    except OperationError as exc:
        feature = exc.details.get("feature")
        step = window.attribution(feature) if isinstance(feature, str) else None
        raise _final(exc, step, steps, rows) from exc
    except Exception as exc:
        controller._log_exception()
        raise _final(OperationError("operation_failed", str(exc)), None, steps, rows) from exc


def _final(exc, step, steps, rows):
    from .core import OperationError
    details = dict(exc.details)
    details.pop("batch", None)
    prefix = "Step %d (%s): " % (step, steps[step]["op"]) if step is not None else ""
    error = OperationError(exc.code, prefix + str(exc), **details,
                           batch={"step": step, "op": steps[step]["op"] if step is not None else None,
                                  "as": steps[step].get("as") if step is not None else None, "phase": "final_validation",
                                  "steps_completed": len(rows), "step_count": len(steps), "rolled_back": True})
    error.batch_rows = rows
    return error


def report(request, name, rows, validation):
    return {"label": request.get("label"), "transaction": name, "base_revision": request.get("expected_revision"),
            "step_count": len(request["steps"]), "completed_steps": len(rows),
            "created_features": [row["created_feature"] for row in rows if row["created_feature"]],
            "steps": rows, "validation": validation}


def _clip(value, limit):
    return value[:limit] if isinstance(value, str) else None


def failure_record(request, error):
    """The compact persisted failure record (D13): no steps, no step_request, at most 2 KiB. Never raises."""
    try:
        steps = request.get("steps")
        raw = error.get("batch") if isinstance(error.get("batch"), dict) else {}
        batch = {key: value for key, value in raw.items() if key != "step_request"}
        batch.update({key: _clip(batch.get(key), limit) for key, limit in (("op", 64), ("as", 32), ("phase", 32))
                      if key in batch})
        record = {"request": {"op": "batch", "request_id": _clip(request.get("request_id"), 128),
                              "label": _clip(request.get("label"), MAX_LABEL),
                              "step_count": len(steps) if isinstance(steps, list) else 0},
                  "error": {"code": _clip(error.get("code"), 64), "message": str(error.get("message", ""))[:500],
                            **({"feature": error["feature"][:64]} if isinstance(error.get("feature"), str) else {}),
                            "batch": batch},
                  "rejected": True}
        if len(json.dumps(record, default=str)) > FAILURE_RECORD_BYTES:
            record["error"] = {"code": record["error"]["code"], "message": record["error"]["message"][:300],
                               "batch": {key: batch.get(key) for key in ("step", "phase", "rolled_back")}}
        return record
    except Exception:
        return {"request": {"op": "batch"}, "error": {"code": str(error.get("code"))[:64]}, "rejected": True}


# --------------------------------------------------------------------------- transaction splits

class SplitGuard:
    """Undo what a batch left committed when a step broke its transaction (F4 §3.6)."""

    def __init__(self, controller, doc):
        self.controller = controller
        state = controller.observer.state(doc)
        self.names0 = list(doc.UndoNames)
        self.commits0 = state.get("commit_count", 0)
        self.signature0 = controller.signatures.get(controller.identifier(doc))
        self.objects0 = {obj.Name for obj in doc.Objects}
        self.transaction_id = None

    def after_abort(self, doc, exc):
        controller = self.controller
        code = getattr(exc, "code", None)
        committed = controller.observer.state(doc).get("commit_count", 0) - self.commits0
        split = code == "transaction_split" or getattr(exc, "split", False)
        if committed == 0 and App.getActiveTransaction() is None and not split:
            return exc
        try:
            return self._recover(doc, exc, code, committed)
        except Exception as failure:
            # Recovery itself failed: leave no transaction behind, rotate the revision, report honestly.
            controller._log_exception()
            try:
                if doc.HasPendingTransaction:
                    doc.abortTransaction()
                if App.getActiveTransaction():
                    App.closeActiveTransaction(True)
                controller._new_revision(doc)
            except Exception:
                pass
            error = _error("transaction_split", "A step broke the batch transaction and recovery failed; inspect it",
                           rolled_back=False, revision_rotated=True,
                           cause={"code": code or "operation_failed", "message": str(exc)[:300]},
                           recovery_error=str(failure)[:300])
            error.batch_rows = getattr(exc, "batch_rows", [])
            return error

    def _recover(self, doc, exc, code, committed):
        controller = self.controller
        if doc.HasPendingTransaction:
            doc.abortTransaction()
        if App.getActiveTransaction():
            App.closeActiveTransaction(True)
        added = committed
        names = list(doc.UndoNames)
        if added > 0 and names[added:] != self.names0[:len(names) - added]:
            added = None
        if added:
            for _ in range(added):
                doc.undo()
            controller._recompute(doc)
        objects = {obj.Name for obj in doc.Objects}
        restored = added is not None and controller._signature(doc) == self.signature0 and objects == self.objects0
        if added:
            doc.openTransaction(DISCARD_BOUNDARY)
            controller._new_revision(doc)
            doc.commitTransaction()
            if App.getActiveTransaction():
                App.closeActiveTransaction()
        else:
            controller._new_revision(doc)
        details = {"rolled_back": restored, "revision_rotated": True}
        if not restored:
            details["residual_objects"] = {"added": sorted(objects - self.objects0), "removed": sorted(self.objects0 - objects)}
        if code != "transaction_split":
            details["cause"] = {"code": code or "operation_failed", "message": str(exc)[:300]}
        batch_details = dict(getattr(exc, "details", {}).get("batch") or {})
        if batch_details:
            batch_details["rolled_back"] = restored
            details["batch"] = batch_details
        error = _error("transaction_split", "A step broke the batch transaction; " + (
            "the batch was undone" if restored else "the document could not be fully restored; inspect it"), **details)
        error.batch_rows = getattr(exc, "batch_rows", [])
        return error
