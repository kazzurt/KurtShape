"""Result checks on edits and rebuilds (contract 3.2, F1).

A *result operation* is an active or held studio operation recorded as ``pad``,
``pocket``, ``revolve``, ``sweep`` or ``loft`` (``extrude_face`` records ``pad``) with
``operation`` add, remove or intersect and a ``KurtShapeNeutralToolBody``. Each gets
a content-addressed key: a Merkle digest of the native intent of its input closure
(geometry-relevant properties only) plus the engine stamp and the checker version.
Verdicts of the 3.1 post-conditions, run at the operation's own history position,
live in a controller-wide store keyed by that key and are persisted compactly in
``KurtShapeProject.KurtShapeResultChecks``. ``validate`` runs only for operations
whose key changed or whose verdict cannot be reused; inspect reads an O(1) stamped
summary. See ``runtime/contract-3.2/specs/validation.md``.
"""
from __future__ import annotations

from collections import OrderedDict, namedtuple
import hashlib
import json
import math
import os
import time

from . import document_state, parameters, studio
from .bodies import owner as body_owner

CHECKER_VERSION = 1
VERDICT_LIMIT = 4096
PROPERTY = "KurtShapeResultChecks"
RESULT_OPS = frozenset({"pad", "pocket", "revolve", "sweep", "loft", "extrude_face"})
RESULT_KINDS = frozenset({"add", "remove", "intersect"})
RETRY_CODES = frozenset({"build_failed", "invalid_geometry", "empty_cut", "empty_add"})
MODES = ("edit", "navigate", "rebuild", "report", "check", "export", "preview")
# Properties that never feed geometry: studio bookkeeping, presentation, session noise.
BOOKKEEPING = frozenset({
    "KurtShapeStudioOperation", "KurtShapeOutputParts", "KurtShapeOutputTips", "KurtShapeConsumedParts",
    "KurtShapeInputSnapshots", "KurtShapeInputPartIds", "KurtShapeMergePartIds", "KurtShapeInternal",
    "KurtShapeOperationOwner", "KurtShapeTool", "KurtShapeNeutralToolBody", "KurtShapeScopeBounds",
    "KurtShapePartId", "KurtShapePartName", "KurtShapePartVisible", "KurtShapePartColor", "KurtShapeObsolete",
    "KurtShapeOutputGeneration", "KurtShapeInputBinder", "KurtShapeGeometryBinder", "KurtShapePatternToolParts",
    "KurtShapePatternSourceParts", "QueryHealth", "QueryResolutionLog", "Label", "Label2", "Visibility",
    "SourceFeatureId", "SourceFeatureName", "AttacherEngine", "_ElementMapVersion", "_GroupTouched",
    "ExpressionEngine"})
# Native changes that never stale the result table (document_state._COSMETIC).
COSMETIC = frozenset(document_state._METADATA) | {"Label2", "_GroupTouched"}
AUDIT = os.environ.get("KURTSHAPE_RESULT_CHECK_AUDIT") == "1"
REJECTING_MODES = frozenset({"edit", "preview"})

Entry = namedtuple("Entry", "key active outputs status reason verdict")
Table = namedtuple("Table", "token ops")
# The result-operation list changes only with the feature order or the object set (F1 §5.2).
studio.document_index._DEPENDENCIES.setdefault("result_ops", {"structure", "history"})


def capabilities():
    """The ``capabilities.result_checks`` block (F1 §6)."""
    return {"operations": sorted(RESULT_OPS), "kinds": sorted(RESULT_KINDS),
            "validated": ["creation", "managed edits", "finish_sketch_edit", "preview", "check_geometry", "export"],
            "exposed_only": ["rollback", "rebuild", "undo", "redo", "native edits"],
            "interactive": "never during inspect or live preview", "export": "required", "persisted": True,
            "checker": CHECKER_VERSION}


def operations(doc):
    """Result operations in history order (active and held), cached in the document index."""
    index = studio.document_index.get(doc)
    if index is not None and "result_ops" in index.derived:
        return list(index.derived["result_ops"])
    result = []
    for obj in studio.order(doc):
        recorded = getattr(obj, "KurtShapeStudioOperation", "")
        if not recorded or "KurtShapeNeutralToolBody" not in obj.PropertiesList:
            continue
        try:
            request = json.loads(recorded)
        except ValueError:
            continue
        op = request.get("op")
        kind = request.get("operation", "remove" if op == "pocket" else "new")
        if op in RESULT_OPS and kind in RESULT_KINDS:
            result.append(obj)
    if index is not None:
        index.derived["result_ops"] = tuple(result)
    return result


def recorded_request(obj):
    try:
        return json.loads(getattr(obj, "KurtShapeStudioOperation", "") or "{}")
    except ValueError:
        return {}


def recorded_kind(obj):
    request = recorded_request(obj)
    return request.get("operation", "remove" if request.get("op") == "pocket" else "new")


def output_pairs(doc, obj):
    """``[(body, tip), …]`` of the recorded output parts; None entries for missing objects."""
    names = list(getattr(obj, "KurtShapeOutputParts", []))
    tips = list(getattr(obj, "KurtShapeOutputTips", []))
    return [(doc.getObject(name), doc.getObject(tips[index]) if index < len(tips) else None)
            for index, name in enumerate(names)]


def result_shape(body, tip):
    """The output at its own history position: the Body when the tip is still its Tip, else the tip in world frame."""
    if body is None or tip is None:
        return None
    if body.Tip is not None and body.Tip.Name == tip.Name:
        return body.Shape
    shape = tip.Shape.copy()
    shape.Placement = body.Placement.multiply(shape.Placement)
    return shape


def fingerprint(shape):
    """Copy-free vertex fingerprint: stable across tessellation and reopen (F1 r2_fp)."""
    if shape is None or shape.isNull():
        return None
    sums = [0.0, 0.0, 0.0, 0.0]
    for vertex in shape.Vertexes:
        x, y, z = vertex.X, vertex.Y, vertex.Z
        sums[0] += x
        sums[1] += y
        sums[2] += z
        sums[3] += x * x + y * y + z * z
    return [shape.ShapeType, len(shape.Solids), len(shape.Shells), len(shape.Faces), len(shape.Edges), len(shape.Vertexes),
            *[round(value, 6) + 0.0 for value in sums]]


def _quantize(value):
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        value = round(value, 9)
        return 0.0 if value == 0 else value
    if isinstance(value, dict):
        return {key: _quantize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_quantize(item) for item in value]
    return value


def op_roots(doc, obj):
    """Recorded output tips, the neutral tool Body and the input snapshots of a result operation."""
    roots = [tip for _, tip in output_pairs(doc, obj) if tip is not None]
    tool = getattr(obj, "KurtShapeNeutralToolBody", None)
    if tool is not None:
        roots.append(tool)
    roots.extend(snapshot for snapshot in getattr(obj, "KurtShapeInputSnapshots", []) if snapshot is not None)
    return roots


class ResultChecks:
    """Keys, verdicts and validation of result operations; one per Controller."""

    def __init__(self, controller, read_intent, engine_stamp):
        self.controller = controller
        self.read_intent = read_intent
        self.engine_stamp = engine_stamp
        self.verdicts = OrderedDict()
        self.digests = {}
        self.digesters = {}
        self.retries = 0
        self.audit_mismatches = []

    # ----------------------------------------------------------------- state access
    def _state(self, doc):
        return self.controller.observer.state(doc)

    def token(self, doc):
        state = self._state(doc)
        return (state["instance_id"], state["intent_epoch"], state.get("result_serial", 0), state.get("history_serial", 0))

    def table(self, doc):
        """The stamped table when it is current, else None."""
        table = self._state(doc).get("result_table")
        return table if table is not None and table.token == self.token(doc) else None

    def drop_document(self, name):
        self.digests = {key: value for key, value in self.digests.items() if key[0] != name}

    def register_digester(self, type_id, function):
        """F3 hook: ``function(obj, row) -> row`` replaces the generic property filter for one TypeId."""
        self.digesters[type_id] = function

    # ----------------------------------------------------------------- digests and keys
    def _intent_row(self, doc, obj):
        from .incremental_intent import IntentCache
        state = self._state(doc)
        cache = state.get("intent_cache")
        if cache is None:
            cache = state["intent_cache"] = IntentCache(doc)
        payload = cache.row(doc, state, obj, self.read_intent)
        return json.loads(payload) if payload else None

    def digest(self, doc, obj, mode):
        state = self._state(doc)
        version = (state["intent_epoch"], state["intent_versions"].get(obj.Name, 0))
        slot = (doc.Name, obj.Name, mode)
        cached = self.digests.get(slot)
        if cached is not None and cached[0] == version:
            return cached[1]
        row = self._intent_row(doc, obj) or {"id": obj.Name, "type": obj.TypeId, "properties": {}, "expressions": []}
        row = dict(row)
        row.pop("label", None)
        properties = dict(row.get("properties", {}))
        expressions = [list(item) for item in row.get("expressions", [])]
        if mode == "container":
            properties = {key: value for key, value in properties.items() if key == "Placement"}
            expressions = [item for item in expressions if str(item[0]).lstrip(".").startswith("Placement")]
            parameter_set = parameters.parameter_set(doc)
            if parameter_set is not None:  # C17, as below: the Placement value is keyed, not the formula text
                expressions = [item for item in expressions if not parameters.reads(parameter_set, str(item[1]))]
            row = {"id": row.get("id"), "type": row.get("type"), "properties": properties, "expressions": expressions}
        elif obj.TypeId in self.digesters:
            row = self.digesters[obj.TypeId](obj, row)
        else:
            row["properties"] = {key: value for key, value in properties.items() if key not in BOOKKEEPING}
            # Contract 3.2 C17: a formula that reads the parameter set is keyed by the value it produced (in
            # ``properties``), not its text, so renaming or freezing a parameter re-keys nothing.
            parameter_set = parameters.parameter_set(doc)
            if parameter_set is not None:
                expressions = [item for item in expressions if not parameters.reads(parameter_set, str(item[1]))]
            row["expressions"] = expressions
        text = json.dumps(_quantize(row), sort_keys=True, default=str)
        value = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self.digests[slot] = (version, value)
        return value

    def key_table(self, doc, stamp=True):
        """Keys of every result operation (Merkle over its input closure); stamps the table when asked."""
        began = time.perf_counter()
        ops = operations(doc)
        cutoff = studio._cutoff(doc)
        positions = {obj.Name: index for index, obj in enumerate(studio.order(doc))}
        tip_owner = {}
        for op in ops:
            for _, tip in output_pairs(doc, op):
                if tip is not None:
                    tip_owner[tip.Name] = op.Name
        by_name = {op.Name: op for op in ops}
        keys = {}
        touched_ops = set()
        unkeyable = set()
        visiting = set()

        def key_of(op):
            if op.Name in keys:
                return keys[op.Name]
            if op.Name in visiting:
                raise RuntimeError("result-check closure cycle at " + op.Name)
            visiting.add(op.Name)
            outputs = {name for name in getattr(op, "KurtShapeOutputParts", [])}
            roots = op_roots(doc, op)
            locals_ = {}
            containers = {}
            upstream = set()
            seen = set()
            stack = list(roots)
            touched = False
            for body, tip in output_pairs(doc, op):
                if body is not None:
                    containers[body.Name] = self.digest(doc, body, "container")
                    if set(body.State) & {"Touched", "Invalid", "Error"}:
                        touched = True
            while stack:
                node = stack.pop()
                if node is None or node.Name in seen:
                    continue
                seen.add(node.Name)
                if node.Document.Name != doc.Name:
                    unkeyable.add(op.Name)
                    continue
                if node.Name in tip_owner and tip_owner[node.Name] != op.Name:
                    upstream_key = key_of(by_name[tip_owner[node.Name]])
                    if upstream_key is None:
                        unkeyable.add(op.Name)
                    else:
                        upstream.add(upstream_key)
                    continue
                if node.TypeId.startswith(("App::Origin", "App::Line", "App::Plane", "App::VarSet")):
                    continue  # C17: the parameter set is reached through its consumers' values, never digested
                if node.TypeId in ("PartDesign::Body", "App::Part"):
                    is_root = any(node.Name == root.Name for root in roots)
                    internal = bool(getattr(node, "KurtShapeInternal", False))
                    if not (is_root or (internal and node.Name not in outputs)):
                        containers[node.Name] = self.digest(doc, node, "container")
                        continue
                if set(node.State) & {"Touched", "Invalid", "Error"}:
                    touched = True
                locals_[node.Name] = self.digest(doc, node, "local")
                container = body_owner(doc, node) if node.TypeId not in ("PartDesign::Body", "App::Part") else None
                if container is not None and container.Name not in locals_:
                    containers.setdefault(container.Name, self.digest(doc, container, "container"))
                stack.extend(node.OutList)
            visiting.discard(op.Name)
            if touched:
                touched_ops.add(op.Name)
            if op.Name in unkeyable:
                keys[op.Name] = None
                return None
            payload = (["result-check", CHECKER_VERSION, list(self.engine_stamp()), op.Name]
                       + sorted(name + ":" + value for name, value in locals_.items())
                       + sorted("[" + name + "]:" + value for name, value in containers.items())
                       + sorted(upstream))
            keys[op.Name] = hashlib.sha256(json.dumps(payload).encode("utf-8")).hexdigest()
            return keys[op.Name]

        entries = OrderedDict()
        for op in ops:
            try:
                key = key_of(op)
            except RuntimeError:
                key = None
                unkeyable.add(op.Name)
            active = positions.get(op.Name, len(positions)) < cutoff
            outputs = [studio.part_id(body) for body, _ in output_pairs(doc, op) if body is not None]
            verdict = self.verdicts.get(key) if key is not None else None
            if op.Name in touched_ops:
                status, reason = "pending", "native_pending"
            elif key is None:
                status, reason = "pending", "unkeyable"
            elif verdict is None:
                status, reason = "pending", "not_validated"
            else:
                status, reason = verdict["status"], None
            entries[op.Name] = Entry(key, active, outputs, status, reason, verdict)
        table = Table(self.token(doc), entries)
        if stamp:
            self._state(doc)["result_table"] = table
        self.controller.timings.record("result_keys", (time.perf_counter() - began) * 1000)
        return table

    def snapshot(self, doc):
        """The current table: the stamped one when current (O(1)), else freshly keyed; empty without the studio."""
        if not studio.enabled(doc):
            return Table(self.token(doc), OrderedDict())
        return self.table(doc) or self.key_table(doc)

    def restamp(self, doc, table):
        if table is not None:
            self._state(doc)["result_table"] = Table(self.token(doc), table.ops)

    def creation_key(self, doc, name):
        """The key of a just-created result operation (same DFS; D9)."""
        table = self.key_table(doc, stamp=False)
        entry = table.ops.get(name)
        return entry.key if entry else None

    # ----------------------------------------------------------------- verdict helpers
    def _store(self, key, verdict):
        if key is None:
            return
        self.verdicts[key] = verdict
        self.verdicts.move_to_end(key)
        while len(self.verdicts) > VERDICT_LIMIT:
            self.verdicts.popitem(last=False)

    def _shape_versions(self, doc, op):
        observer = self.controller.observer
        return tuple(observer.version(doc, root.Name, shape_only=True) for root in op_roots(doc, op))

    def _fingerprint(self, doc, op):
        tool = getattr(op, "KurtShapeNeutralToolBody", None)
        return {"tool": fingerprint(tool.Shape) if tool is not None else None,
                "outputs": [fingerprint(result_shape(body, tip)) for body, tip in output_pairs(doc, op)]}

    def _check(self, doc, op, kernel=True):
        """Run the 3.1 post-conditions at the op's own position; returns a verdict dict.

        The one real-check entry point (tests count it); the audit re-check goes through _verdict.
        """
        return self._verdict(doc, op, kernel, fingerprint=True)

    def _verdict(self, doc, op, kernel=True, fingerprint=True):
        began = time.perf_counter()
        try:
            report = studio.check_operation(doc, op, kernel=kernel, facts=self.controller.geometry)
            verdict = {"status": "valid", "parts": report["parts"], "tool_volume_mm3": report["tool_volume_mm3"],
                       "volume_delta_mm3": report["volume_delta_mm3"], "refine": report["refine"]}
        except Exception as exc:  # OperationError from the checker, or a missing recorded object
            from .core import OperationError
            if not isinstance(exc, OperationError):
                self.controller._log_exception()  # a checker bug is recorded as build_failed, and logged
            code = getattr(exc, "code", "build_failed")
            details = dict(getattr(exc, "details", {}))
            parts = details.get("parts") or []
            part = details.get("part") or (parts[0].get("part") if parts and isinstance(parts[0], dict) else None)
            verdict = {"status": "failed", "code": code, "message": str(exc), "check": details.get("check"),
                       "part": part, "issues": [str(item)[:200] for item in details.get("issues", [])][:20],
                       "parts": details.get("parts", []), "tool_volume_mm3": details.get("tool_volume_mm3"),
                       "refine": details.get("refine", self._refine_state(op))}
        verdict.update(fingerprint=self._fingerprint(doc, op) if fingerprint else None, check_ms=(time.perf_counter() - began) * 1000,
                       checker=CHECKER_VERSION, engine=list(self.engine_stamp()), feature=op.Name,
                       operation=recorded_kind(op))
        return verdict

    def _refine_state(self, op):
        try:
            return dict(studio.refine_state(op), retried_unrefined=False)
        except Exception:
            return None

    def remember(self, doc, name, report):
        """Seed the store after a creation check (D9): the post-dispatch validator reuses it."""
        op = doc.getObject(name)
        if op is None:
            return None
        key = self.creation_key(doc, name)
        if key is None:
            return None
        verdict = {"status": "valid", "parts": report["parts"], "tool_volume_mm3": report["tool_volume_mm3"],
                   "volume_delta_mm3": report["volume_delta_mm3"], "refine": report.get("refine"),
                   "fingerprint": self._fingerprint(doc, op), "check_ms": report.get("check_ms", 0.0),
                   "checker": CHECKER_VERSION, "engine": list(self.engine_stamp()), "feature": name,
                   "operation": recorded_kind(op)}
        self._store(key, verdict)
        self._state(doc).setdefault("result_confirmed", {})[name] = (key, self._shape_versions(doc, op))
        return key

    # ----------------------------------------------------------------- validation
    def validate(self, doc, mode, before=None, trigger=None, body=None, retry=False, persist=True):
        """Validate the document's result operations in ``mode`` (F1 §5.6); returns the report or None.

        ``retry`` (edit and preview) runs the bounded unrefined retry only while the request
        owns a pending native transaction it will commit or abort; without one no retry runs.
        """
        from .core import OperationError
        if mode not in MODES:
            raise ValueError("unknown result-check mode " + repr(mode))
        if not studio.enabled(doc):
            return None
        state = self._state(doc)
        if not operations(doc):
            # The last result operation went away: an empty, current table replaces any stale one.
            state["result_table"] = Table(self.token(doc), OrderedDict())
            state["result_failed"] = {}
            if persist:
                self.persist(doc)
            return None
        identifier = self.controller.identifier(doc)
        if mode == "check" and identifier in self.controller.sketch_edits:
            return {"mode": mode, "status": "pending", "reason": "sketch_edit_active", "checked": [], "reused": 0,
                    "fingerprinted": 0, "pending": [], "failed": [], "keys_ms": 0.0, "ms": 0.0}
        retry = bool(retry and mode in REJECTING_MODES and doc.HasPendingTransaction)
        # D10: a known failure clears only when its operation is revalidated. Previously failed
        # operations without a reusable verdict are checked (except in report mode, which keeps
        # the row as stale); a rejection restores the previously stamped table.
        previous_failed = dict(state.get("result_failed", {}))
        previous_table = state.get("result_table")
        began = time.perf_counter()
        table = self.key_table(doc)
        keys_ms = (time.perf_counter() - began) * 1000
        confirmed = state.setdefault("result_confirmed", {})
        checked, reused, fingerprinted, pending, failed = [], 0, 0, [], []
        stale_names = set()

        def keep_stale(op, entry):
            stale = previous_failed[op.Name]
            table.ops[op.Name] = entry._replace(status="failed", reason="stale", verdict=stale)
            failed.append(stale)
            stale_names.add(op.Name)
        before_ops = before.ops if before is not None else {}
        retried = None
        retry_report = None
        index = 0
        ops = operations(doc)
        while index < len(ops):
            op = ops[index]
            index += 1
            entry = table.ops.get(op.Name)
            if entry is None or not entry.active:
                continue
            if entry.reason == "native_pending":
                pending.append({"feature": op.Name, "reason": "native_pending"})
                continue
            key = entry.key
            if key is None:
                if mode in {"check", "export"}:
                    verdict = self._check(doc, op)
                    checked.append(self._report_row(verdict, True))
                    table.ops[op.Name] = entry._replace(status=verdict["status"], reason="unkeyable", verdict=verdict)
                    if verdict["status"] == "failed":
                        failed.append(verdict)
                else:
                    pending.append({"feature": op.Name, "reason": "unkeyable"})
                continue
            baseline = before_ops.get(op.Name)
            affected = baseline is None or baseline.key != key
            if body is not None and body not in entry.outputs:
                verdict = self.verdicts.get(key)
                if verdict is None and op.Name in previous_failed:
                    keep_stale(op, entry)
                elif verdict is None:
                    pending.append({"feature": op.Name, "reason": "not_validated"})
                elif verdict["status"] == "failed":
                    failed.append(verdict)
                continue
            must_check = ((mode in REJECTING_MODES and affected)
                          or (mode == "navigate" and (affected or baseline is None or not baseline.active))
                          or mode in {"rebuild", "check", "export"}
                          or (mode != "report" and op.Name in previous_failed))
            verdict = self.verdicts.get(key)
            versions = self._shape_versions(doc, op)
            if verdict is not None:
                if confirmed.get(op.Name) == (key, versions):
                    reused += 1
                elif mode in {"edit", "navigate", "report"} and not affected:
                    reused += 1
                else:
                    fingerprinted += 1
                    if self._fingerprint(doc, op) == verdict.get("fingerprint"):
                        confirmed[op.Name] = (key, versions)
                        reused += 1
                    elif mode == "report":
                        verdict = None
                        pending.append({"feature": op.Name, "reason": "geometry_changed"})
                    else:
                        verdict = None
                if verdict is not None and AUDIT and mode != "report":
                    self._audit(doc, op, verdict)
            if verdict is None and must_check and mode != "report":
                verdict = self._check(doc, op)
                self._store(key, verdict)
                confirmed[op.Name] = (key, versions)
                checked.append(self._report_row(verdict, affected))
            if verdict is None:
                if op.Name in previous_failed:
                    keep_stale(op, entry)
                elif not any(row["feature"] == op.Name for row in pending):
                    pending.append({"feature": op.Name, "reason": "not_validated"})
                continue
            table.ops[op.Name] = entry._replace(status=verdict["status"], reason=None, verdict=verdict)
            if verdict["status"] == "failed":
                rejecting = mode in REJECTING_MODES and affected and (baseline is None or baseline.status != "failed")
                if rejecting and retry and retried is None and verdict.get("code") in RETRY_CODES \
                        and studio.refine_state(op)["applied"]:
                    # D6: one unrefined retry per request, inside the request's transaction.
                    retried = op.Name
                    self.retries += 1
                    retry_report = {"code": verdict.get("code"), "message": verdict.get("message"),
                                    **{k: verdict[k] for k in ("check", "part", "issues") if verdict.get(k)}}
                    studio.retry_unrefined(self.controller, doc, op)
                    errors = self.controller._build_status(doc)
                    if errors:
                        if previous_table is not None:
                            state["result_table"] = previous_table
                        raise OperationError("build_failed", "Change not applied: the unrefined retry could not rebuild native features",
                                             feature=op.Name, features=errors, validation="history", trigger=trigger,
                                             previous_status=baseline.status if baseline is not None else "new",
                                             refine={"requested": True, "retried_unrefined": True, "refined_failure": retry_report})
                    table = self.key_table(doc)
                    checked[:] = [row for row in checked if row["feature"] != op.Name]  # one row per operation
                    index -= 1  # re-evaluate this operation with its new key
                    continue
                failed.append(verdict)
                if rejecting:
                    details = {key_: value for key_, value in verdict.items()
                               if key_ in {"parts", "tool_volume_mm3", "check", "part", "issues", "refine"} and value not in (None, [])}
                    error = OperationError(verdict.get("code", "build_failed"), "Change not applied: " + str(verdict.get("message")),
                                           feature=op.Name, validation="history", trigger=trigger,
                                           previous_status=baseline.status if baseline is not None else "new", **details)
                    if retried == op.Name:
                        error.details["refine"] = {"requested": True, "retried_unrefined": True, "refined_failure": retry_report,
                                                   "hint": "The unrefined retry failed too; rebuild an earlier refined result "
                                                           "with refine:false"}
                    elif retried is not None and verdict.get("code") in RETRY_CODES and studio.refine_state(op)["applied"]:
                        error.details["refine"] = {"requested": True, "retried_unrefined": False,
                                                   "hint": "One unrefined retry per request; retry this operation separately"}
                    if (trigger or {}).get("op") in {"delete_feature", "delete_features"}:
                        error.details["hint"] = ("The deletion leaves " + op.Name + " with an empty result: delete that "
                                                 "operation first, or pass cascade:true")
                    if previous_table is not None:
                        state["result_table"] = previous_table
                    raise error
        if retried is not None:
            for row in checked:
                if row["feature"] == retried:
                    row["refine"] = {"requested": True, "applied": False, "retried_unrefined": True,
                                     "refined_failure": retry_report}
        state["result_table"] = Table(self.token(doc), table.ops)
        state["result_failed"] = {row["feature"]: row for row in failed if isinstance(row, dict)}
        status = "failed" if failed else "pending" if pending else "valid"
        if persist:
            self.persist(doc)
        report = {"mode": mode, "status": status, "checked": checked, "reused": reused, "fingerprinted": fingerprinted,
                  "pending": pending, "failed": [self._failed_row(row, stale=row.get("feature") in stale_names) for row in failed],
                  "keys_ms": round(keys_ms, 3), "ms": round((time.perf_counter() - began) * 1000, 3)}
        if retried is not None:
            report["retry"] = retried
        self.controller.timings.record("result_validation", report["ms"])
        return report

    def _audit(self, doc, op, verdict):
        fresh = self._verdict(doc, op, fingerprint=False)
        if fresh["status"] != verdict["status"] or fresh.get("code") != verdict.get("code"):
            self.audit_mismatches.append({"feature": op.Name, "reused": verdict, "fresh": fresh})
            raise AssertionError("result-check audit mismatch for " + op.Name + ": " + json.dumps(
                {"reused": verdict.get("status"), "fresh": fresh.get("status"), "code": fresh.get("code")}))

    @staticmethod
    def _report_row(verdict, affected):
        row = {"feature": verdict["feature"], "operation": verdict.get("operation"), "status": verdict["status"],
               "affected": bool(affected), "check_ms": round(verdict.get("check_ms", 0.0), 3), "refine": verdict.get("refine")}
        if verdict["status"] == "valid":
            row["volume_delta_mm3"] = verdict.get("volume_delta_mm3")
        else:
            row.update(code=verdict.get("code"), message=verdict.get("message"), check=verdict.get("check"), part=verdict.get("part"))
        return row

    @staticmethod
    def _failed_row(verdict, stale):
        return {"feature": verdict["feature"], "code": verdict.get("code"), "check": verdict.get("check"),
                "part": verdict.get("part"), "message": verdict.get("message"), "stale": bool(stale), "source": "result_check"}

    # ----------------------------------------------------------------- status reads (never compute)
    @staticmethod
    def _not_applicable():
        return {"status": "not_applicable", "operations": 0, "pending": [], "failed": [], "checker": CHECKER_VERSION}

    def summary(self, doc):
        """The inspect block: O(1) when the table is current; never checks or fingerprints."""
        if not studio.enabled(doc):
            return self._not_applicable()
        state = self._state(doc)
        table = self.table(doc)
        identifier = self.controller.identifier(doc)
        if table is None:
            stored = state.get("result_table")
            live = operations(doc)
            count = len(stored.ops) if stored is not None else len(live)
            if count == 0 or not live:
                return self._not_applicable()
            failed = [self._failed_row(row, stale=True) for row in state.get("result_failed", {}).values()]
            reason = "sketch_edit_active" if identifier in self.controller.sketch_edits else (
                "native_change" if stored is not None else "not_validated")
            failed_names = set(state.get("result_failed", {}))
            pending = ([name for name, entry in stored.ops.items() if entry.active and name not in failed_names]
                       if stored is not None else [op.Name for op in live if op.Name not in failed_names])
            return {"status": "failed" if failed else "pending", "operations": count, "pending": pending,
                    "failed": failed, "reason": reason, "checker": CHECKER_VERSION}
        if not table.ops:
            return self._not_applicable()
        active = [(name, entry) for name, entry in table.ops.items() if entry.active]
        pending = [name for name, entry in active if entry.status == "pending"]
        failed = [self._failed_row(entry.verdict, stale=entry.reason == "stale") for name, entry in active if entry.status == "failed"]
        block = {"status": "failed" if failed else "pending" if pending else "valid", "operations": len(table.ops),
                 "pending": pending, "failed": failed, "checker": CHECKER_VERSION}
        if pending and not failed:
            reasons = {entry.reason for name, entry in active if entry.status == "pending"}
            block["reason"] = "native_pending" if reasons == {"native_pending"} else "not_validated"
        return block

    def provenance(self, doc):
        """The ``result_checks`` entry of export sidecars and STEP provenance."""
        summary = self.summary(doc)
        return {"status": summary["status"], "operations": summary["operations"], "checker": CHECKER_VERSION}

    def feature_status(self, doc, name):
        """``valid``, ``failed`` or ``pending`` for a result operation; None for any other feature."""
        if not studio.enabled(doc):
            return None
        table = self.table(doc)
        if table is None:
            stored = self._state(doc).get("result_table")
            if stored is None or name not in stored.ops:
                return None
            return "failed" if name in self._state(doc).get("result_failed", {}) else "pending"
        entry = table.ops.get(name)
        return entry.status if entry is not None else None

    def part_status(self, doc, part):
        """The worst status of the active result operations that output ``part``; None when none does."""
        if not studio.enabled(doc):
            return None
        table = self.table(doc)
        if table is None:
            stored = self._state(doc).get("result_table")
            if stored is None:
                return None
            rows = [(name, entry) for name, entry in stored.ops.items() if entry.active and part in entry.outputs]
            if not rows:
                return None
            failed = self._state(doc).get("result_failed", {})
            return "failed" if any(name in failed for name, _ in rows) else "pending"
        statuses = [entry.status for entry in table.ops.values() if entry.active and part in entry.outputs]
        if not statuses:
            return None
        return "failed" if "failed" in statuses else "pending" if "pending" in statuses else "valid"

    def has_failures(self, doc):
        """Active failed verdicts, or last-known failures while the table is stale (D7, D10)."""
        if not studio.enabled(doc):
            return False
        table = self.table(doc)
        if table is None:
            return bool(self._state(doc).get("result_failed"))
        return any(entry.active and entry.status == "failed" for entry in table.ops.values())

    def errors(self, doc):
        """Failure rows for build_errors (source result_check)."""
        summary = self.summary(doc)
        return [dict(row, source="result_check") for row in summary.get("failed", [])]

    def failed_parts(self, doc):
        table = self.table(doc)
        parts = set()
        if table is None:
            stored = self._state(doc).get("result_table")
            failed = self._state(doc).get("result_failed", {})
            for name, entry in (stored.ops.items() if stored is not None else ()):
                if entry.active and name in failed:
                    parts.update(entry.outputs)
            return parts
        for entry in table.ops.values():
            if entry.active and entry.status == "failed":
                parts.update(entry.outputs)
        return parts

    # ----------------------------------------------------------------- persistence
    def _persisted_document(self, doc):
        table = self.table(doc) or self._state(doc).get("result_table")
        ops = {}
        if table is not None:
            for name, entry in table.ops.items():
                if entry.key is None or entry.verdict is None:
                    continue
                verdict = entry.verdict
                ops[name] = {"key": entry.key, "status": verdict["status"], "code": verdict.get("code"), "check": verdict.get("check"),
                             "part": verdict.get("part"), "message": verdict.get("message"),
                             "volume_delta_mm3": verdict.get("volume_delta_mm3"), "fingerprint": verdict.get("fingerprint"),
                             "refine": {"requested": (verdict.get("refine") or {}).get("requested"),
                                        "applied": (verdict.get("refine") or {}).get("applied")}}
        return {"version": 1, "checker": CHECKER_VERSION, "engine": list(self.engine_stamp()), "operations": ops}

    def ensure_property(self, doc):
        """Create the hidden persisted table on a managed document outside any transaction (attach)."""
        meta = doc.getObject(studio.META)
        if meta is None or PROPERTY in meta.PropertiesList:
            return False
        modified = self.controller._modified(doc)
        try:
            meta.addProperty("App::PropertyString", PROPERTY, "KurtShape", "Result-check verdicts (contract 3.2)")
            meta.setEditorMode(PROPERTY, 3)
            setattr(meta, PROPERTY, json.dumps(self._persisted_document(doc), sort_keys=True))
        finally:
            self.controller._restore_modified(doc, modified)
        return True

    def load(self, doc):
        """Read persisted verdicts into the store (attach; never writes)."""
        meta = doc.getObject(studio.META)
        if meta is None or PROPERTY not in meta.PropertiesList:
            return 0
        try:
            stored = json.loads(getattr(meta, PROPERTY) or "{}")
        except ValueError:
            return 0
        loaded = 0
        for name, row in (stored.get("operations") or {}).items():
            key = row.get("key")
            if not key or row.get("status") not in ("valid", "failed"):
                continue
            verdict = {"status": row["status"], "code": row.get("code"), "check": row.get("check"), "part": row.get("part"),
                       "message": row.get("message"), "volume_delta_mm3": row.get("volume_delta_mm3"),
                       "fingerprint": row.get("fingerprint"), "refine": row.get("refine"), "parts": [], "issues": [],
                       "check_ms": 0.0, "checker": stored.get("checker"), "engine": stored.get("engine"),
                       "feature": name, "operation": None}
            if key not in self.verdicts:
                self._store(key, verdict)
                loaded += 1
        return loaded

    def persist(self, doc):
        """Write the compact table when it changed: inside a pending transaction, else preserving Modified."""
        meta = doc.getObject(studio.META)
        if meta is None or PROPERTY not in meta.PropertiesList or self.controller.identifier(doc) in self.controller.sketch_edits:
            return False
        text = json.dumps(self._persisted_document(doc), sort_keys=True)
        if getattr(meta, PROPERTY) == text:
            return False
        if doc.HasPendingTransaction:
            setattr(meta, PROPERTY, text)
            return True
        modified = self.controller._modified(doc)
        try:
            setattr(meta, PROPERTY, text)
        finally:
            self.controller._restore_modified(doc, modified)
        return True
