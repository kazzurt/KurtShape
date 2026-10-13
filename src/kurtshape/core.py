"""Typed operations over one native FreeCAD document; no parallel feature graph."""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
import uuid
import traceback
import weakref

import FreeCAD as App
import Part
import Sketcher
from .document_state import DocumentState
from .settings import Settings
from .request_ledger import RequestLedger, RequestStatusLookup
from .bodies import bodies, owner, origin_plane, results as native_results
from .recovery import RecoveryStore
from .timing import Timings
from . import assembly as native_assembly
from . import studio
from . import selectors as native_selectors
from . import reference_tools
from .sketch_tools import restore_sketch_content, reference_errors as sketch_reference_errors
from . import modeling_geometry
from .contract import CONTRACT_VERSION, CONTRACT_REVISION
from .native_content import native_content_fingerprints
from . import geometry
from . import incremental_intent, inspection_cache
from .snapshots import SnapshotKey, SnapshotStore

ROOT = Path(__file__).resolve().parents[2]
WRITE_ROOT = ROOT.parent.resolve()
METADATA = "KurtShapeProject"
SKETCH_CANCEL_BOUNDARY = "KurtShape: cancelled sketch edit"


class OperationError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details


def number(value, name, positive=False, unit="mm"):
    if isinstance(value, str):
        try:
            quantity = App.Units.Quantity(value)
            target_unit = App.Units.Quantity("1 " + unit).Unit
            if quantity.Unit == App.Units.Quantity(1).Unit:
                value = quantity.Value
            elif quantity.Unit == target_unit:
                value = math.radians(quantity.Value) if unit == "rad" else quantity.Value
            else:
                raise ValueError("Wrong dimension")
        except Exception as exc:
            raise OperationError("invalid_argument", f"{name} requires a finite {unit} quantity") from exc
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise OperationError("invalid_argument", f"{name} must be a finite number in {unit}")
    if positive and value <= 0:
        raise OperationError("invalid_argument", f"{name} must be positive")
    if abs(value) > 1e6:
        raise OperationError("invalid_argument", f"{name} exceeds the 1 km slice limit")
    return float(value)


def write_path(raw, suffixes, roots=None):
    if not isinstance(raw, str) or not Path(raw).is_absolute():
        raise OperationError("invalid_argument", "Destination must be an absolute path")
    path = Path(raw).resolve()
    if not any(path.is_relative_to(root) for root in (roots or {WRITE_ROOT})):
        raise OperationError("path_outside_workspace", "Choose this project folder in the app before an assistant writes there")
    if path.suffix.lower() not in suffixes:
        raise OperationError("invalid_format", f"Expected {', '.join(suffixes)}")
    if not path.parent.is_dir():
        raise OperationError("missing_directory", "Create the descriptive destination folder first")
    return path


def metadata(doc):
    meta = doc.getObject(METADATA)
    if meta:
        return meta
    meta = doc.addObject("App::FeaturePython", METADATA)
    meta.Label = "KurtShape project"
    for name, value in [("DocumentId", str(uuid.uuid4())), ("Revision", str(uuid.uuid4())),
                        ("BuildStatus", "sketch_only"), ("LastFailure", ""), ("SourceMapping", "{}")]:
        meta.addProperty("App::PropertyString", name, "KurtShape")
        setattr(meta, name, value)
        meta.setEditorMode(name, 1)
    return meta


def engine_stamp():
    return ".".join(App.Version()[:3]), Part.OCC_VERSION


def ensure_engine_properties(meta):
    for name in ("EngineFreeCAD", "EngineOCCT", "RebuildReason"):
        if name not in meta.PropertiesList:
            meta.addProperty("App::PropertyString", name, "KurtShape")
            meta.setEditorMode(name, 1)


def native_parameters(obj):
    params = {}
    if obj.TypeId == "Sketcher::SketchObject":
        for i, c in enumerate(obj.Constraints):
            if c.Type in {"Distance", "DistanceX", "DistanceY", "Diameter", "Radius", "Angle"}:
                name = c.Name or f"Constraints[{i}]"
                aliases={f"Constraints.{c.Name}",f"Constraints[{i}]"}
                expression=next((value for path,value in obj.ExpressionEngine if path.lstrip(".") in aliases),None)
                params[name] = {"value": float(c.Value), "unit": "rad" if c.Type == "Angle" else "mm", "constraint_index": i,
                                "constraint_type": c.Type, "name": c.Name or None,
                                "editable":bool(c.Driving) and expression is None,"expression":expression}
    if obj.TypeId == "PartDesign::Pad" or (obj.TypeId == "PartDesign::Pocket" and str(obj.Type) == "Length"):
        expression=next((value for path,value in obj.ExpressionEngine if path.lstrip(".")=="Length"),None)
        params["Length"] = {"value": obj.Length.Value, "unit": "mm", "editable":expression is None,"expression":expression}
    if obj.TypeId == "PartDesign::Plane" and "Offset" in obj.PropertiesList:
        expression = next((value for path, value in obj.ExpressionEngine if path.lstrip(".") == "Offset"), None)
        params["Offset"] = {"value": obj.Offset.Value, "unit": "mm", "editable": expression is None,
                            "expression": expression, "native_property": "Offset"}
    tool = getattr(obj, "KurtShapeTool", None) or obj
    for native_property, public_name, unit in (("LengthFwd", "Length", "mm"), ("Angle", "Angle", "rad"),
                                             ("Radius", "Radius", "mm"), ("Size", "Size", "mm"), ("Value", "Thickness", "mm")):
        supported = ((tool.TypeId == "Part::Extrusion" and native_property == "LengthFwd") or
                     (tool.TypeId == "Part::Revolution" and native_property == "Angle") or
                     (tool.TypeId == "PartDesign::Fillet" and native_property == "Radius") or
                     (tool.TypeId == "PartDesign::Chamfer" and native_property == "Size") or
                     (tool.TypeId == "PartDesign::Thickness" and native_property == "Value"))
        if not supported:
            continue
        value = getattr(tool, native_property)
        numeric = float(value.Value if hasattr(value, "Value") else value)
        expression = next((value for path, value in tool.ExpressionEngine if path.lstrip(".") == native_property), None)
        params[public_name] = {"value": math.radians(numeric) if unit == "rad" else numeric,
                               "unit": unit, "editable": expression is None, "expression": expression,
                               "native_feature": tool.Name, "native_property": native_property}
    return params


def _native_value(value):
    """Stable serialization of native links, quantities and attachment transforms."""
    if hasattr(value, "Name"):
        return {"object": value.Name}
    if isinstance(value, (tuple, list)):
        return [_native_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _native_value(item) for key, item in value.items()}
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if isinstance(value, App.Vector):
        return [value.x, value.y, value.z]
    if isinstance(value, App.Placement):
        return {"base": _native_value(value.Base), "rotation": list(value.Rotation.Q)}
    if hasattr(value, "Value") and hasattr(value, "Unit"):
        return {"value": value.Value, "unit": str(value.Unit)}
    # FreeCAD value types provide deterministic textual serialization; never
    # include opaque Python object reprs containing changing memory addresses.
    result = str(value)
    return re.sub(r" at 0x[0-9A-Fa-f]+", "", result)


def native_intent(doc, objects=None):
    """Read native modeling intent, including native edits made outside our panel."""
    state = []
    for obj in doc.Objects if objects is None else objects:
        if obj.Name == METADATA or obj.TypeId.startswith(("App::Origin", "App::Line", "App::Plane")):
            continue
        item = {"id": obj.Name, "type": obj.TypeId, "label": obj.Label, "properties": {}}
        for key in obj.PropertiesList:
            if key in {"Shape", "InternalShape", "ExpressionEngine", "Geometry", "Constraints", "Proxy", "PlacementList", "Visibility",
                       "QueryHealth", "QueryResolutionLog"}:
                continue
            try:
                if "Shape" in obj.getTypeIdOfProperty(key):
                    continue
                item["properties"][key] = _native_value(getattr(obj, key))
            except Exception:
                pass
        item["expressions"] = [(str(a), str(b)) for a, b in getattr(obj, "ExpressionEngine", [])]
        if obj.TypeId == "Sketcher::SketchObject":
            # Content is the kernel's exact persisted geometry XML. Repr is
            # abbreviated for splines and can miss edits to interior poles.
            item["geometry"] = [g.Content for g in obj.Geometry]
            item["construction"] = [obj.getConstruction(i) for i in range(obj.GeometryCount)]
            item["constraints"] = [
                [c.Type, c.First, c.FirstPos, c.Second, c.SecondPos, c.Third, c.ThirdPos, c.Value,
                 c.Name, c.Driving] for i, c in enumerate(obj.Constraints)]
        state.append(item)
    return state


def intent_signature(doc):
    return hashlib.sha256(json.dumps({"label": doc.Label, "objects": native_intent(doc)}, sort_keys=True).encode()).hexdigest()


def native_feature_summary(obj):
    """Uncached feature record; also the oracle for incremental inspection."""
    result = {"id": obj.Name, "name": obj.Label, "type": obj.TypeId,
              "parameters": native_parameters(obj), "dependencies": [x.Name for x in obj.OutList],
              "expressions": list(getattr(obj, "ExpressionEngine", [])), "state": list(obj.State)}
    if obj.TypeId == "Sketcher::SketchObject":
        result.update(fully_constrained=bool(obj.FullyConstrained), geometry_count=obj.GeometryCount,
                      constraint_count=obj.ConstraintCount,
                      placement={"position_mm": _native_value(obj.Placement.Base), "rotation_xyzw": list(obj.Placement.Rotation.Q)},
                      support=[{"feature": linked.Name, "subelements": list(elements)} for linked, elements in obj.AttachmentSupport],
                      map_mode=str(obj.MapMode))
    if obj.TypeId in {"PartDesign::Pad", "PartDesign::Pocket"}:
        result["reversed"] = bool(obj.Reversed)
    if "SourceFeatureId" in obj.PropertiesList:
        result["source_feature_id"] = obj.SourceFeatureId
        result["source_feature_name"] = obj.SourceFeatureName
    result["reference_health"] = json.loads(getattr(obj, "QueryHealth", "[]"))
    if obj.TypeId == "Sketcher::SketchObject":
        result["reference_health"].extend({"input": error["input"], "status": "missing",
                                           "code": error["code"], "error": error["message"]}
                                          for error in sketch_reference_errors(obj))
    result["selectors"] = json.loads(getattr(obj, "QueryInputs", "{}"))
    return result


def measurements(shape):
    return geometry.measurements(shape)


class Controller:
    READ_OPS = {"inspect", "list_documents", "capabilities", "request_status", "preview", "diagnostics", "assembly_candidates", "resolve_selector", "check_geometry"}
    ASSEMBLY_OPS = {"create_assembly", "insert_assembly_part", "ground_assembly_instance", "create_assembly_joint",
                    "edit_assembly_joint", "move_assembly_joint", "move_assembly_instance", "delete_assembly_object", "solve_assembly"}
    MODEL_OPS = {"create_body", "create_sketch", "sketch_rectangle", "sketch_circle", "add_rectangle", "add_circle", "add_line",
                 "pad", "pocket", "set_parameter", "set_expression", "set_sketch_support", "duplicate_feature", "pierce", "rename_feature", "delete_feature", "delete_features", "rebuild"} | studio.OPS | reference_tools.OPS | modeling_geometry.OPS
    EDIT_OPS = {"add_rectangle", "add_circle", "add_line", "set_parameter", "set_expression", "set_sketch_support", "pierce", "project_geometry", "finish_sketch_edit", "undo", "redo"}
    CREATE_OPS = {"new", "open", "recover", "import_step"}
    OPS = READ_OPS | MODEL_OPS | ASSEMBLY_OPS | CREATE_OPS | {"adopt", "begin_sketch_edit", "finish_sketch_edit", "undo", "redo", "save", "export"}
    ARGS = {
        "new": {"name"}, "open": {"path"}, "import_step": {"path"}, "recover": {"path"}, "adopt": {"path"}, "create_body": {"id", "name"}, "inspect": set(), "list_documents": set(), "check_geometry": {"body"},
        "create_sketch": {"id", "plane", "support", "source_feature_id", "source_feature_name"},
        "sketch_rectangle": {"id","width","height","x","y","plane","support","source_feature_id","source_feature_name"},
        "sketch_circle": {"id","x","y","diameter","plane","support","center_on","source_feature_id","source_feature_name"},
        "add_rectangle": {"sketch", "width", "height", "x", "y", "construction"},
        "add_circle": {"sketch", "x", "y", "diameter", "construction"},
        "add_line": {"sketch", "x1", "y1", "x2", "y2", "construction"},
        "begin_sketch_edit": {"feature"}, "finish_sketch_edit": {"cancel"},
        "set_sketch_support": {"sketch", "plane", "support"},
        "pad": {"id","profile","length","reversed","source_feature_id","source_feature_name"},
        "pocket": {"id","profile","length","through_all","reversed","source_feature_id","source_feature_name"},
        "rename_feature": {"feature", "name"}, "delete_feature": {"feature", "cascade"},
        "delete_features": {"features", "cascade"},
        "set_parameter": {"feature","parameter","value"}, "rebuild": set(), "undo": set(), "redo": set(),
        "set_expression": {"feature", "parameter", "expression"},
        "duplicate_feature": {"feature", "fingerprint"},
        "pierce": {"sketch", "geometry", "point", "target", "subelement"},
        "save": {"path"}, "export": {"path", "body"},
        "capabilities": set(), "request_status": {"request_id"}, "preview": {"proposal"}, "diagnostics": set(),
        "assembly_candidates": {"path"}, "create_assembly": {"id", "name"},
        "insert_assembly_part": {"assembly", "path", "source_id", "id", "name"},
        "ground_assembly_instance": {"assembly", "instance"},
        "create_assembly_joint": {"assembly", "joint_type", "first", "second", "id", "name"},
        "edit_assembly_joint": {"assembly", "joint", "joint_type", "first", "second", "name"},
        "move_assembly_joint": {"assembly", "joint", "value"},
        "move_assembly_instance": {"assembly", "instance", "position_mm", "rotation_xyzw"},
        "delete_assembly_object": {"assembly", "feature", "cascade"}, "solve_assembly": {"assembly"},
        "resolve_selector": {"selector"},
    }
    for _op, _args in studio.ARGS.items():
        ARGS[_op] = ARGS.get(_op, set()) | set(_args)
    for _op, _args in reference_tools.ARGS.items():
        ARGS[_op] = ARGS.get(_op, set()) | set(_args)
    for _op, _args in modeling_geometry.ARGS.items():
        ARGS[_op] = ARGS.get(_op, set()) | set(_args)
    ARGS["pad"] |= {"end_type", "up_to_face"}
    ARGS["pocket"] |= {"end_type", "up_to_face"}
    for _op in MODEL_OPS - {"create_body", "rebuild"} | {"begin_sketch_edit"}:
        ARGS[_op] = ARGS[_op] | {"body"}
    for _op in MODEL_OPS:
        if "id" in ARGS[_op]:
            ARGS[_op] |= {"source_feature_id", "source_feature_name"}

    def __init__(self):
        self.documents = {}
        self.signatures = {}
        self.last_failures = {}
        self.sketch_edits = {}
        self.busy = False
        self.settings = Settings(ROOT)
        self.geometry = geometry.GeometryCache(shape_of=native_assembly.global_shape,
                                               dependencies_of=self._shape_dependencies)
        self.default_measure = True
        self.observer = DocumentState(self)
        self.geometry.observer = self.observer
        self.ledger = RequestLedger()
        # Only the canonical Controller opts in. Subclasses/custom adapters
        # keep their existing dispatch contract and owner-thread validation.
        self.request_status_lookup = (RequestStatusLookup(self.ledger, self.__dict__)
                                      if type(self) is Controller else None)
        self.unmanaged = {}
        self.timings = Timings()
        self.recovery = RecoveryStore(self.settings.path.parent)
        self.snapshots = SnapshotStore(self.settings.path.parent / "snapshots")
        self._geometry_check_workers = weakref.WeakSet()
        self._step_export_workers = weakref.WeakSet()

    def snapshot_key(self, doc):
        """Accepted geometry only; drafts and native transactions cannot share."""
        if (not self._is_open(doc) or not self.is_managed(doc)
                or self.identifier(doc) in self.sketch_edits or doc.HasPendingTransaction):
            return None
        state = self.observer.state(doc)
        return SnapshotKey(state["instance_id"], self._meta(doc).Revision,
                           state["generation"], state["change_serial"])

    @staticmethod
    def _geometry_check_targets(doc, body=None):
        targets = native_results(doc)
        if body is not None:
            target = next((obj for obj in targets if obj.Name == body or getattr(obj, "KurtShapePartId", None) == body), None)
            if target is None:
                raise OperationError("missing_body", "body must identify a current solid result")
            targets = [target]
        return [obj for obj in targets if not obj.Shape.isNull() and obj.Shape.Solids]

    def prepare_geometry_check(self, doc, body=None, *, worker_factory=None):
        """Capture one accepted UI check; None retains synchronous behavior.

        The UI guards reentrant capture and owns cancellation. Native archive
        capture/fingerprints remain on this thread; checking runs in the child.
        """
        from dataclasses import asdict
        from . import document_index
        from .geometry_check_worker import NativeGeometryCheckWorker, target_fingerprints
        from .preview_worker import _snapshot_file_identity
        if self.busy or not self._is_open(doc) or not self.is_managed(doc):
            return None
        self.sync(doc)
        key = self.snapshot_key(doc)
        if key is None or App.getActiveTransaction():
            return None
        index = document_index.get(doc)
        if index is None or not document_index.local_dependencies(index):
            return None
        targets = self._geometry_check_targets(doc, body)
        if not targets or all(self.geometry.check(obj) is not None for obj in targets):
            return None
        executable = Path(App.getHomePath()) / "bin" / ("python.exe" if os.name == "nt" else "python")
        worker = (worker_factory or NativeGeometryCheckWorker)(executable, ROOT / "runtime")
        self._geometry_check_workers.add(worker)
        self.busy = True
        lease = None
        began = time.perf_counter()
        try:
            names = tuple(obj.Name for obj in targets)
            topology = tuple(self.geometry.check_key(obj) for obj in targets)
            fingerprints = target_fingerprints(doc, names)
            try:
                lease = self.snapshots.try_acquire(key)
            except OSError:
                lease = None
            reused = lease is not None
            if lease is not None:
                if lease.key != key or self.snapshot_key(doc) != key:
                    raise OperationError("stale_geometry_check", "The document changed during snapshot acquisition")
                worker.borrow_snapshot(lease)
                lease = None
            else:
                doc.saveCopy(str(worker.snapshot))
                # Pin the identity acquired at capture, never a later replacement.
                worker.own_snapshot(key, _snapshot_file_identity(worker.snapshot))
            bundle = {"worker": worker, "document": doc, "document_id": self.identifier(doc),
                "snapshot_key": key, "target_ids": names, "topology_keys": topology,
                "targets": tuple(targets),
                "body": body, "sequence": 1, "snapshot_reused": reused,
                "envelope": {"document_id": self.identifier(doc), "snapshot_key": asdict(key),
                    "target_ids": list(names), "target_fingerprints": fingerprints}}
            if not self._geometry_check_current(doc, bundle):
                raise OperationError("stale_geometry_check", "The document changed during geometry-check capture")
            return bundle
        except BaseException:
            worker.close()
            raise
        finally:
            if lease is not None:
                lease.release()
            self.busy = False
            self.timings.record("geometry_check_snapshot_gui", (time.perf_counter() - began) * 1000)

    def _geometry_check_current(self, doc, bundle, *, require_worker_open=True):
        try:
            if (doc is not bundle["document"] or not self._is_open(doc)
                    or self.documents.get(bundle["document_id"]) is not doc
                    or (require_worker_open and bundle["worker"].closed)
                    or self.snapshot_key(doc) != bundle["snapshot_key"]):
                return False
            targets = self._geometry_check_targets(doc, bundle["body"])
            names = tuple(obj.Name for obj in targets)
            topology = tuple(self.geometry.check_key(obj) for obj in targets)
            key = self.snapshot_key(doc)
            # Native reads above can reenter. Recheck owner/key and original
            # wrappers after them, before this result can authorize publication.
            return (names == bundle["target_ids"] and topology == bundle["topology_keys"]
                    and len(targets) == len(bundle["targets"])
                    and all(current is original for current, original in zip(targets, bundle["targets"]))
                    and key == bundle["snapshot_key"] and (not require_worker_open or not bundle["worker"].closed)
                    and doc is bundle["document"] and self.documents.get(bundle["document_id"]) is doc)
        except (AttributeError, RuntimeError, ReferenceError, OperationError):
            return False

    def accept_geometry_check(self, doc, bundle, response, *, is_current=None, owns_job=None):
        """Publish a complete verdict under parent topology keys, or discard it."""
        if (self.busy or is_current is not None and not is_current()
                or not self._geometry_check_current(doc, bundle)):
            return None
        from dataclasses import asdict
        worker = bundle["worker"]
        try:
            json.dumps(response, allow_nan=False)
            if (not isinstance(response, dict) or response.get("task") != worker.token
                    or response.get("sequence") != bundle["sequence"]
                    or response.get("snapshot_key") != asdict(bundle["snapshot_key"])
                    or response.get("document_id") != bundle["document_id"]
                    or response.get("target_ids") != list(bundle["target_ids"])
                    or response.get("target_fingerprints") != bundle["envelope"]["target_fingerprints"]):
                raise ValueError("Geometry check response identity does not match")
            if response.get("ok") is not True:
                error = response.get("error") or {}
                raise OperationError(str(error.get("code", "geometry_check_failed")),
                                     str(error.get("message", "Geometry check could not complete")))
            checks = response.get("checks")
            if (not isinstance(checks, list) or len(checks) != len(bundle["target_ids"])
                    or [row.get("id") for row in checks] != list(bundle["target_ids"])):
                raise ValueError("Geometry check targets do not match")
            if response.get("engine") != {"FreeCAD": list(App.Version()), "OCCT": Part.OCC_VERSION}:
                raise ValueError("Geometry check engine does not match")
            if (type(response.get("milliseconds")) not in (int, float)
                    or not math.isfinite(response["milliseconds"]) or response["milliseconds"] < 0):
                raise ValueError("Invalid geometry check duration")
            entries = list(zip(bundle["topology_keys"], checks))
            # All native reads/reentrancy guards precede the atomic pure-Python
            # cache import. No event pumping or child topology keys are used.
            if ((is_current is not None and not is_current())
                    or not self._geometry_check_current(doc, bundle)
                    or (owns_job is not None and not owns_job())):
                return None
            self.busy = True
            receipt = None
            published = False
            try:
                receipt = self.geometry.accept_checks(entries)
                self._build_status(doc)
                state = self.inspect(doc)
                state["geometry_check_report"] = {"status": "valid" if all(row["valid"] for row in checks) else "invalid",
                    "revision": self._meta(doc).Revision, "engine": response["engine"],
                    "bodies": [{"id": row["id"], "valid": row["valid"], "issues": list(row["issues"]), "check_ms": row["ms"]} for row in checks],
                    "ms": response["milliseconds"]}
                # Context/status reads can process events. Validate the model
                # after those reads, then use only a pure UI ownership fence.
                if ((is_current is not None and not is_current())
                        or not self._geometry_check_current(doc, bundle)
                        or (owns_job is not None and not owns_job())):
                    return None
                published = True
                return state
            finally:
                if receipt is not None and not published:
                    self.geometry.discard_accepted_checks(receipt)
                    # An invalid imported verdict may have affected derived
                    # metadata. Rebuild that status from the current cache,
                    # never restore a captured status onto a changed model.
                    try:
                        if self.documents.get(bundle["document_id"]) is doc and self._is_open(doc):
                            self._build_status(doc)
                    except (RuntimeError, ReferenceError):
                        pass
                self.busy = False
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise OperationError("invalid_geometry_check_response", str(exc)) from exc

    @staticmethod
    def _export_file_identity(path):
        """Pin destination content, including absence, without following links."""
        import stat
        path = Path(path)
        try:
            info = path.lstat()
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(info.st_mode) or path.is_symlink():
            raise OperationError("export_destination_invalid", "Export destination must be an ordinary file")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        after = path.lstat()
        identity = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, digest)
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != identity[:4]:
            raise OperationError("stale_export_destination", "Export destination changed while being inspected")
        return identity

    def _step_export_provenance(self, doc, targets, format):
        meta = self._meta(doc)
        return {"document_id": meta.DocumentId, "revision": meta.Revision, "units": "mm",
                "source_mapping": json.loads(meta.SourceMapping),
                "import_source": json.loads(getattr(meta, "ImportSource", "{}")) or None,
                "assembly": None, "engine": {"FreeCAD": list(App.Version()), "OCCT": Part.OCC_VERSION},
                "native_file": doc.FileName or None, "format": format,
                "included_body_ids": [obj.Name for obj in targets],
                "included_part_ids": [getattr(obj, "KurtShapePartId", obj.Name) for obj in targets],
                "settings": {"writer": "FreeCAD Part/OCCT"}}

    def prepare_step_export(self, doc, raw, body=None, *, worker_factory=None, is_current=None):
        """Capture an eligible STEP job; ownership loss raises instead of falling back."""
        from dataclasses import asdict
        from . import document_index
        from .step_export_worker import NativeStepExportWorker, world_fingerprints, world_roundtrip_stable
        from .step_capture import roundtrip_digest, initial_world_fingerprints
        from .preview_worker import _snapshot_file_identity
        def require_current_request():
            if is_current is None:
                return
            try:
                current = bool(is_current())
            except Exception as exc:
                raise OperationError("cancelled_step_export", "STEP export ownership check failed") from exc
            if not current:
                raise OperationError("cancelled_step_export", "STEP export request is no longer current")

        require_current_request()
        path = write_path(raw, {".step", ".stp", ".stl"}, self.settings.roots)
        if (path.suffix.lower() not in {".step", ".stp"} or self.busy
                or not self._is_open(doc) or not self.is_managed(doc)):
            require_current_request()
            return None
        self.sync(doc)
        require_current_request()
        key = self.snapshot_key(doc)
        if key is None or App.getActiveTransaction() or native_assembly.assemblies(doc):
            require_current_request()
            return None
        index = document_index.get(doc)
        if index is None or not document_index.local_dependencies(index):
            require_current_request()
            return None
        if self._meta(doc).BuildStatus != "valid":
            require_current_request()
            return None
        # Attachment writes a fresh session revision. Clean metadata would
        # become Touched and fail the child's exact native-state comparison.
        # Keep that case synchronous rather than changing source flags.
        try:
            metadata = doc.getObject(METADATA)
            metadata_ready = metadata is not None and "Touched" in tuple(metadata.State)
        except (AttributeError, RuntimeError, ReferenceError, ValueError):
            metadata_ready = False
        require_current_request()
        if not metadata_ready:
            return None
        targets = self._geometry_check_targets(doc, body)
        if not targets:
            require_current_request()
            return None
        # A Link's world check can include scale, while its cache key belongs
        # to the linked source. Keep those occurrences on the sync path.
        try:
            linked = any(candidate.TypeId == "App::Link" or getattr(candidate, "LinkedObject", None) is not None
                         for obj in targets for candidate in (obj, geometry.source_of(obj)))
        except (AttributeError, RuntimeError, ReferenceError):
            linked = True
        require_current_request()
        if linked:
            return None
        # Exact stability is an admission test, never a replacement fingerprint.
        # Native archives can otherwise change signed-zero surface coefficients.
        stable, digest_ticket = roundtrip_digest(self, doc, [obj.Name for obj in targets], key)
        # Keep request callbacks outside admission's conservative exception boundary.
        require_current_request()
        if not stable:
            return None
        sidecar = path.with_suffix(path.suffix + ".json")
        destination_ids = tuple(self._export_file_identity(p) for p in (path, sidecar))
        parent_stat = path.parent.stat()
        executable = Path(App.getHomePath()) / "bin" / ("python.exe" if os.name == "nt" else "python")
        require_current_request()
        worker = (worker_factory or NativeStepExportWorker)(executable, ROOT / "runtime")
        self._step_export_workers.add(worker)
        self.busy = True
        lease = None
        began = time.perf_counter()
        try:
            require_current_request()
            names = tuple(obj.Name for obj in targets)
            fingerprints = initial_world_fingerprints(self, doc, names, key, digest_ticket)
            provenance = self._step_export_provenance(doc, targets, path.suffix.lower())
            shape = json.loads(json.dumps(self._geometry(doc, targets, "full"), allow_nan=False))
            shape["valid"] = True  # Publication still requires every child native verdict.
            require_current_request()
            try:
                lease = self.snapshots.try_acquire(key)
            except OSError:
                lease = None
            # A reentrant acquisition may retire the request; release locally
            # owned leases through finally before borrowing or saving anything.
            require_current_request()
            reused = lease is not None
            if lease is not None:
                if lease.key != key or self.snapshot_key(doc) != key:
                    raise OperationError("stale_step_export", "Project changed during snapshot acquisition")
                require_current_request()
                worker.borrow_snapshot(lease)
                lease = None
            else:
                doc.saveCopy(str(worker.snapshot))
                worker.own_snapshot(key, _snapshot_file_identity(worker.snapshot))
            bundle = {"worker": worker, "document": doc, "document_id": self.identifier(doc),
                      "snapshot_key": key, "target_ids": names, "targets": tuple(targets), "body": body,
                      "topology_keys": tuple(self.geometry.check_key(obj) for obj in targets),
                      "sequence": 1, "snapshot_reused": reused, "raw_destination": raw,
                      "destination": path, "sidecar": sidecar, "destination_identities": destination_ids,
                      "destination_parent_identity": (parent_stat.st_dev, parent_stat.st_ino),
                      "provenance": provenance, "measurements": shape, "published": False,
                      "envelope": {"snapshot_key": asdict(key), "document_id": self.identifier(doc),
                                   "target_ids": list(names), "target_fingerprints": fingerprints,
                                   "format": path.suffix.lower(), "settings": provenance["settings"]}}
            # Callbacks may be eventful. The independent native guards go last.
            require_current_request()
            if not self._step_export_current(doc, bundle) or not self._step_export_destination_current(bundle):
                raise OperationError("stale_step_export", "Project or export destination changed during capture")
            return bundle
        except BaseException:
            worker.close()
            raise
        finally:
            if lease is not None:
                lease.release()
            self.busy = False
            self.timings.record("step_export_snapshot_gui", (time.perf_counter() - began) * 1000)

    def _step_export_destination_current(self, bundle, *, check_files=True):
        try:
            path = write_path(bundle["raw_destination"], {".step", ".stp"}, self.settings.roots)
            parent = path.parent.stat()
            return (path == bundle["destination"]
                    and (parent.st_dev, parent.st_ino) == bundle["destination_parent_identity"]
                    and (not check_files or tuple(self._export_file_identity(p) for p in
                         (bundle["destination"], bundle["sidecar"])) == bundle["destination_identities"]))
        except (OSError, ValueError, OperationError):
            return False

    def _step_export_current(self, doc, bundle, *, require_worker_open=True, require_valid=True):
        from .step_export_worker import world_fingerprints
        try:
            if (bundle.get("published") or doc is not bundle["document"] or not self._is_open(doc)
                    or self.documents.get(bundle["document_id"]) is not doc
                    or require_worker_open and bundle["worker"].closed
                    or self.snapshot_key(doc) != bundle["snapshot_key"]
                    or App.getActiveTransaction() or native_assembly.assemblies(doc)):
                return False
            targets = self._geometry_check_targets(doc, bundle["body"])
            if (tuple(obj.Name for obj in targets) != bundle["target_ids"]
                    or len(targets) != len(bundle["targets"])
                    or not all(current is original for current, original in zip(targets, bundle["targets"]))
                    or tuple(self.geometry.check_key(obj) for obj in targets) != bundle["topology_keys"]
                    or require_valid and self._meta(doc).BuildStatus != "valid"
                    or self._step_export_provenance(doc, targets, bundle["provenance"]["format"]) != bundle["provenance"]
                    or world_fingerprints(doc, bundle["target_ids"]) != bundle["envelope"]["target_fingerprints"]):
                return False
            # Native reads may reenter; the accepted key and original owner go last.
            return (self._step_export_provenance(doc, targets, bundle["provenance"]["format"]) == bundle["provenance"]
                    and self.snapshot_key(doc) == bundle["snapshot_key"] and self._is_open(doc)
                    and self.documents.get(bundle["document_id"]) is doc
                    and (not require_worker_open or not bundle["worker"].closed))
        except (AttributeError, RuntimeError, ReferenceError, ValueError, OperationError):
            return False

    def accept_step_export(self, doc, bundle, response, *, is_current=None, owns_job=None):
        """Validate/copy private bytes and publish through the existing pair rollback."""
        from dataclasses import asdict
        import shutil
        worker = bundle["worker"]
        def current(require_valid=True):
            return ((is_current is None or is_current()) and self._step_export_current(doc, bundle, require_valid=require_valid)
                    and (owns_job is None or owns_job()))
        if self.busy or not current() or not self._step_export_destination_current(bundle):
            return None
        def verified_artifact():
            try:
                return worker.validated_artifact(response)
            except (OSError, ValueError, RuntimeError) as exc:
                raise OperationError("invalid_step_export_response", str(exc)) from exc
        stages = []
        preserve_stages = False
        try:
            json.dumps(response, allow_nan=False)
            if (not isinstance(response, dict) or response.get("task") != worker.token
                    or response.get("sequence") != bundle["sequence"]
                    or response.get("snapshot_key") != asdict(bundle["snapshot_key"])
                    or any(response.get(key) != bundle["envelope"][key]
                           for key in ("document_id", "target_ids", "target_fingerprints", "format", "settings"))):
                raise ValueError("STEP response does not match its captured request")
            if response.get("ok") is not True:
                error = response.get("error") or {}
                if error.get("code") == "invalid_geometry":
                    checks = response.get("checks")
                    duration = response.get("milliseconds")
                    if (worker.closed or worker.process is None or worker.process.poll() != 0
                            or response != worker._completed_response
                            or response.get("engine") != bundle["provenance"]["engine"]
                            or type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0
                            or not isinstance(checks, list) or len(checks) != len(bundle["target_ids"])
                            or any(not isinstance(row, dict) for row in checks)
                            or [row.get("id") for row in checks] != list(bundle["target_ids"])):
                        raise ValueError("Invalid STEP failure verdict identity")
                    for row in checks:
                        if (type(row.get("valid")) is not bool or not isinstance(row.get("issues"), list)
                                or any(not isinstance(issue, str) for issue in row["issues"])
                                or type(row.get("ms")) not in (int, float) or not math.isfinite(row["ms"]) or row["ms"] < 0):
                            raise ValueError("Invalid STEP failure verdict")
                    if all(row["valid"] for row in checks):
                        raise ValueError("STEP failure has no invalid geometry")
                    if not current() or not self._step_export_destination_current(bundle):
                        return None
                    self.busy = True
                    receipt = None
                    accepted = False
                    try:
                        receipt = self.geometry.accept_checks(list(zip(bundle["topology_keys"], checks)))
                        self._build_status(doc)
                        state = self.inspect(doc, False)
                        if (not current(require_valid=False) or not self._step_export_destination_current(bundle)
                                or owns_job is not None and not owns_job()):
                            return None
                        bundle["invalid_state"] = state
                        accepted = True
                    finally:
                        try:
                            if receipt is not None and not accepted:
                                self.geometry.discard_accepted_checks(receipt)
                                if self._is_open(doc) and self.documents.get(bundle["document_id"]) is doc:
                                    self._build_status(doc)
                        finally:
                            self.busy = False
                raise OperationError(str(error.get("code", "step_export_failed")),
                                     str(error.get("message", "STEP export could not complete")),
                                     **{key: value for key, value in error.items() if key not in {"code", "message"}})
            if response.get("engine") != bundle["provenance"]["engine"]:
                raise ValueError("STEP worker engine does not match")
            duration = response.get("milliseconds")
            if type(duration) not in (int, float) or duration < 0 or not math.isfinite(duration):
                raise ValueError("Invalid STEP worker duration")
            checks = response.get("checks")
            if (not isinstance(checks, list) or len(checks) != len(bundle["target_ids"])
                    or any(not isinstance(row, dict) for row in checks)
                    or [row.get("id") for row in checks] != list(bundle["target_ids"])):
                raise ValueError("STEP native check targets do not match")
            for row in checks:
                if (row.get("valid") is not True or row.get("issues") != []
                        or type(row.get("ms")) not in (int, float) or row["ms"] < 0 or not math.isfinite(row["ms"])):
                    raise ValueError("STEP output requires complete valid native checks")
            if response.get("measurements") != bundle["measurements"]:
                raise ValueError("STEP measurements do not match captured world geometry")
            artifact = verified_artifact()
            provenance = json.loads(json.dumps(bundle["provenance"], allow_nan=False))
            provenance.update(sha256=response["artifact"]["sha256"], shape=response["measurements"],
                geometry_check={"status": "valid", "bodies": [{"id": row["id"], "check_ms": row["ms"]} for row in checks]})
            path, sidecar = bundle["destination"], bundle["sidecar"]
            tag = ".step-job-" + uuid.uuid4().hex
            stage = path.with_name(path.name + tag + ".stage")
            meta_stage = sidecar.with_name(sidecar.name + tag + ".stage")
            stages = [stage, meta_stage]
            with artifact.open("rb") as source, stage.open("xb") as destination:
                shutil.copyfileobj(source, destination)
                destination.flush()
                os.fsync(destination.fileno())
            if (stage.stat().st_size != response["artifact"]["size"]
                    or hashlib.sha256(stage.read_bytes()).hexdigest() != provenance["sha256"]):
                raise ValueError("Copied STEP bytes do not match the verified artifact")
            # Revalidate child bytes too; no early worker close can delete this directory.
            verified_artifact()
            payload = json.dumps(provenance, indent=2, allow_nan=False).encode("utf-8")
            with meta_stage.open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            if meta_stage.read_bytes() != payload:
                raise ValueError("Copied STEP provenance is incomplete")
            if not current() or not self._step_export_destination_current(bundle):
                return None
            staged_ids = tuple(self._export_file_identity(p) for p in stages)
            def commit_current():
                try:
                    if not current() or not self._step_export_destination_current(bundle, check_files=False):
                        return False
                    # Destination-local renames retain each staged file identity.
                    expected = tuple(staged_ids[i] if not stages[i].exists() else bundle["destination_identities"][i]
                                     for i in range(2))
                    return (tuple(self._export_file_identity(p) for p in (path, sidecar)) == expected
                            and (owns_job is None or owns_job()))
                except (OSError, ValueError, OperationError):
                    return False
            self.busy = True
            try:
                def rollback_current(target):
                    try:
                        return self._export_file_identity(target) == staged_ids[0 if target == path else 1]
                    except (OSError, ValueError, OperationError):
                        return False
                self._replace_export_pair([(stage, path), (meta_stage, sidecar)],
                                          guard=commit_current, rollback_guard=rollback_current)
                bundle["published"] = True
            finally:
                self.busy = False
            return provenance
        except OperationError as exc:
            preserve_stages = exc.code == "export_recovery_required"
            if preserve_stages:
                exc.details["staged_files"] = [str(p) for p in stages if p.exists()]
            raise
        except (ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
            raise OperationError("invalid_step_export_response", str(exc)) from exc
        finally:
            # Only this job's unique uncommitted stages; final/recovery files are untouched.
            for stage in [] if preserve_stages else stages:
                try:
                    stage.unlink(missing_ok=True)
                except OSError:
                    pass

    def checkpoint(self, doc, force=False, background=False):
        if self.busy or not self.is_managed(doc):
            return None
        self.sync(doc)
        previous_busy = self.busy
        self.busy = True
        try:
            return self.recovery.capture(doc, self._meta(doc), self.sketch_edits.get(self.identifier(doc)), force,
                                         background=background,
                                         snapshot_cache=(self.snapshots, self.snapshot_key(doc),
                                                         lambda: self.snapshot_key(doc)) if not force else None)
        finally:
            self.busy = previous_busy

    def _signature(self, doc):
        if os.environ.get("KURTSHAPE_FULL_INTENT") == "1":
            return self.timings.measure("intent", intent_signature, doc)
        return self.timings.measure("intent", incremental_intent.signature, doc, self.observer, native_intent)

    def _recompute(self, doc):
        self.geometry.bind(doc)
        began = time.perf_counter()
        totals = {"native_recompute_ms": 0.0, "selector_evaluation_ms": 0.0}
        def native_pass():
            result = native_selectors.recompute(doc)
            metrics = native_selectors.rebuild_metrics(doc)
            for key in totals:
                totals[key] += metrics.get(key, 0.0)
            return result
        studio.prepare_recompute(doc)
        result = native_pass()
        for attempt in range(len(studio.order(doc)) + 1):
            if not studio.sync_auto_scopes(doc):
                break
            studio.prepare_recompute(doc)
            result = native_pass()
        else:
            raise OperationError("unstable_merge_scope", "Auto merge scopes did not stabilize during rebuild")
        studio.hide_internal(doc)
        studio.refresh_validation(doc)
        state = self.observer.state(doc)
        state["native_recomputed"] = False
        state["recomputed_objects"].clear()
        for label, key in (("native_recompute", "native_recompute_ms"),
                           ("selector_evaluation", "selector_evaluation_ms")):
            self.timings.record(label, totals[key])
        self.timings.record("managed_rebuild", (time.perf_counter() - began) * 1000)
        return result

    def _meta(self, doc):
        return self.unmanaged[doc.Name] if doc.Name in self.unmanaged else metadata(doc)

    def identifier(self, doc):
        return self._meta(doc).DocumentId

    def is_managed(self, doc):
        return doc.Name not in self.unmanaged and doc.getObject(METADATA) is not None

    def _body(self, doc, request=None, target=None):
        request = request or {}
        try:
            selected = studio.current_body(doc, request["body"]) if isinstance(request.get("body"), str) else None
        except OperationError as exc:
            if exc.code == "missing_part":
                raise OperationError("missing_body", "body must identify a native PartDesign Body") from exc
            raise
        if "body" in request and (selected is None or selected.TypeId != "PartDesign::Body"):
            raise OperationError("missing_body", "body must identify a native PartDesign Body")
        candidate = owner(doc, target)
        # A selected historical feature remains owned by its native generation.
        # Stable logical part IDs resolve to the current Body only for new work.
        if candidate and selected and getattr(candidate, "KurtShapePartId", candidate.Name) == getattr(selected, "KurtShapePartId", selected.Name):
            selected = candidate
        if selected and target and candidate != selected:
            raise OperationError("cross_body_reference", "Feature and support must belong to the selected Body")
        if selected or candidate:
            return selected or candidate
        eligible = studio.current_parts(doc) if studio.enabled(doc) else bodies(doc)
        if len(eligible) != 1:
            raise OperationError("ambiguous_body" if eligible else "missing_body", "Choose an explicit body ID")
        return eligible[0]

    def _shape_dependencies(self, obj):
        dependencies = []
        candidates = [obj]
        linked = getattr(obj, "LinkedObject", None)
        if linked is not None:
            linked = linked[0] if isinstance(linked, tuple) else linked
            candidates.append(linked)
            dependencies.append(linked)
        seen = {(obj.Document.Name, obj.Name)}
        while candidates:
            candidate = candidates.pop()
            if candidate.TypeId == "PartDesign::Body" and candidate.Tip is not None:
                dependencies.append(candidate.Tip)
            for parent in candidate.InList:
                key = (parent.Document.Name, parent.Name)
                if key not in seen and (parent.TypeId in {"App::Part", "PartDesign::Body"}
                                        or getattr(parent, "KurtShapeAssembly", "") == "1"):
                    seen.add(key)
                    dependencies.append(parent)
                    candidates.append(parent)
        return dependencies

    def _measure_level(self, measure):
        if measure is None:
            measure = self.default_measure
        if type(measure) is bool or type(measure) is str and measure == "full":
            return measure
        raise OperationError("invalid_argument", 'measure must be false, true or "full"')

    def _volume(self, obj):
        return self.geometry.facts(obj, ("volume",))["volume"]

    def _geometry(self, doc, objects=None, measure=None):
        objects = native_results(doc) if objects is None else objects
        solid_objects = [obj for obj in objects if not obj.Shape.isNull() and obj.Shape.Solids]
        if not solid_objects:
            return None
        fields = geometry.LEVELS[self._measure_level(measure)]
        result = geometry.aggregate([self.geometry.facts(obj, fields) for obj in solid_objects],
                                    [self.geometry.check(obj) for obj in solid_objects])
        if len(solid_objects) > 1 and not native_assembly.assemblies(doc):
            # Preserve native compound integration for Part Studio aggregates;
            # OCCT's curved-solid integration depends on the combined range.
            # Independent Assembly occurrences retain their accepted sums.
            for field, metric in (("volume", "volume_mm3"), ("area", "area_mm2")):
                if field in fields:
                    result[metric] = self.geometry.memo("aggregate_" + field, solid_objects, (),
                        lambda field=field: geometry.scalar(Part.makeCompound(
                            [native_assembly.global_shape(obj).copy() for obj in solid_objects]), field))
        return result

    def close(self):
        for worker in tuple(self._step_export_workers):
            worker.close()
        for worker in tuple(self._geometry_check_workers):
            worker.close()
        try:
            self.recovery.close()
        finally:
            try:
                self.snapshots.close()
            finally:
                try:
                    self.observer.close()
                finally:
                    self.geometry.close()

    def needs_refresh(self, doc):
        return self.observer.state(doc)["refresh"]

    def record_edit_boundary(self, doc):
        self.observer.state(doc)["snapshot_pending"] = True

    def _evaluated_shape(self, doc, body, measure=None):
        return geometry.measurement_dict(self.geometry.facts(body, geometry.LEVELS[self._measure_level(measure)]),
                                         self.geometry.check(body))

    def attach(self, doc, managed=True):
        self.observer.state(doc)
        native_scope_migrated = False
        if managed:
            self.unmanaged.pop(doc.Name, None)
            native_scope_migrated = studio.migrate_link_scopes(doc)
            native_selectors.migrate_link_scopes(doc)
        if not managed:
            from types import SimpleNamespace
            self.unmanaged[doc.Name] = SimpleNamespace(DocumentId=str(uuid.uuid4()), Revision=str(uuid.uuid4()),
                                                      BuildStatus="sketch_only", LastFailure="", SourceMapping="{}")
        meta = self._meta(doc)
        if managed:
            studio.record_legacy_order(doc)
        existing=self.documents.get(meta.DocumentId)
        if existing is not None and self._is_open(existing) and existing.Name!=doc.Name:
            raise OperationError("duplicate_document_id", "Close the existing project before opening another copy with the same document ID", existing_document=existing.Name)
        if existing is None or not self._is_open(existing):
            # Edit leases belong to a live native document instance, not to
            # its persisted UUID. A closed document's snapshots/history must
            # never be applied to a reopened copy with the same project ID.
            self.sketch_edits.pop(meta.DocumentId, None)
        if managed and not doc.UseHasher:
            self._restore_native_map_versions(doc)
        # A copied/opened file receives a fresh session revision, preventing old-client ABA.
        meta.Revision = str(uuid.uuid4())
        self.documents[meta.DocumentId] = doc
        self.geometry.bind(doc)
        if managed and native_scope_migrated and not doc.UseHasher:
            self._recompute(doc)
        if managed and doc.UseHasher:
            doc.UseHasher = False
            for obj in doc.Objects:
                if obj.TypeId.startswith(("Sketcher::", "PartDesign::")) or studio.enabled(doc) and obj.TypeId.startswith(("Part::", "App::Link")):
                    obj.touch()
            self._recompute(doc)
            self._mark_rebuilt(doc)
            self.observer.state(doc)["hasher_migrated"] = True
        if meta.LastFailure:
            try:
                self.last_failures[meta.DocumentId]=json.loads(meta.LastFailure)
            except ValueError:
                pass
        self.signatures[meta.DocumentId] = self._signature(doc)
        self.observer.state(doc)["intent_dirty"] = False
        self.observer.state(doc).pop("assembly_source_changed", None)
        doc.UndoMode = 1
        self._build_status(doc)
        return doc

    def _doc(self, request):
        identifier = request.get("document_id")
        doc = self.documents.get(identifier)
        if doc is None or not self._is_open(doc):
            raise OperationError("unknown_document", "Document is not open in this session")
        if request.get("op") != "inspect":
            self.sync(doc)
        return doc

    @staticmethod
    def _is_open(doc):
        try:
            return doc.Name in App.listDocuments()
        except (NameError,ReferenceError):
            return False

    @staticmethod
    def _native_edit_active():
        import FreeCADGui as Gui
        return bool(Gui.Control.activeDialog() or any(Gui.getDocument(name).getInEdit() for name in App.listDocuments()))

    def _prune_closed_sketch_edits(self):
        for identifier in list(self.sketch_edits):
            doc = self.documents.get(identifier)
            if doc is None or not self._is_open(doc):
                self.sketch_edits.pop(identifier, None)

    def sync(self, doc, included=None):
        meta = self._meta(doc)
        state = self.observer.state(doc)
        if state["native_recomputed"]:
            if self.is_managed(doc):
                studio.record_legacy_order(doc)
            self.timings.measure("native_reference_reconciliation", native_selectors.reconcile_native, doc)
            self.timings.measure("native_scope_validation", studio.refresh_validation, doc)
            state["native_recomputed"] = False
            state["recomputed_objects"].clear()
        if state["intent_dirty"]:
            signature = self._signature(doc)
            source_changed = state.pop("assembly_source_changed", False)
            if self.signatures.get(meta.DocumentId) != signature or source_changed:
                meta.Revision = str(uuid.uuid4())
                self.signatures[meta.DocumentId] = signature
            state["intent_dirty"] = False
        if state["snapshot_pending"]:
            self._record_sketch_edit(doc)
            state["snapshot_pending"] = False
        return self._build_status(doc, included)

    def _sketch_edit_signature(self, doc, name):
        item = native_intent(doc, [doc.getObject(name)])[0]
        return hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()

    def _record_sketch_edit(self, doc):
        editing = self.sketch_edits.get(self._meta(doc).DocumentId)
        if not editing:
            return
        sketch = doc.getObject(editing["feature"])
        if sketch is None:
            return
        signature = self._sketch_edit_signature(doc, sketch.Name)
        if signature != editing["signature"]:
            editing["undo"].append(bytes(sketch.dumpContent()))
            # These are native-object byte snapshots for the current edit's
            # undo cache, never a second model or saved feature representation.
            editing["undo"] = editing["undo"][-128:]
            editing["redo"].clear()
            editing["signature"] = signature

    def _rollback_sketch_edit(self, doc):
        """Abort a lease even when native resetEdit already committed it.

        The lease excludes other shared document mutations. Therefore only
        native transactions after its checkpoint belong to this edit. Native
        resetEdit commits instead of aborting; undo those transactions before
        restoring the exact accepted sketch buffer. A metadata boundary then
        invalidates redo of canceled geometry without deleting earlier undo.
        """
        identifier = self._meta(doc).DocumentId
        editing = self.sketch_edits[identifier]
        if doc.HasPendingTransaction:
            doc.abortTransaction()
        if doc.UndoCount < editing["undo_before"]:
            self.sketch_edits.pop(identifier, None)
            raise OperationError("sketch_history_changed", "Native document history changed outside the managed sketch lease")
        undone = False
        while doc.UndoCount > editing["undo_before"]:
            doc.undo()
            undone = True
        sketch = doc.getObject(editing["feature"])
        if sketch is None or sketch.TypeId != "Sketcher::SketchObject":
            self.sketch_edits.pop(identifier, None)
            raise OperationError("sketch_history_changed", "The accepted sketch no longer exists in native history")
        restore_sketch_content(sketch, editing["initial"])
        self._recompute(doc)
        self.sketch_edits.pop(identifier, None)
        if undone:
            doc.openTransaction(SKETCH_CANCEL_BOUNDARY)
            self._new_revision(doc)
            doc.commitTransaction()
        else:
            self._new_revision(doc)

    def _commit_sketch_edit(self, doc):
        """Group native command commits within the exclusive sketch lease."""
        editing = self.sketch_edits[self._meta(doc).DocumentId]
        from .sketch_tools import prune_use_sources
        prune_use_sources(doc, editing["feature"])
        if doc.HasPendingTransaction:
            doc.commitTransaction()
        if doc.UndoCount < editing["undo_before"]:
            raise OperationError("sketch_history_changed", "Native document history changed outside the managed sketch lease")
        if doc.UndoCount > editing["undo_before"] + 1:
            sketch = doc.getObject(editing["feature"])
            final = bytes(sketch.dumpContent())
            label = sketch.Label
            from .sketch_tools import capture_use_sources, restore_use_sources
            editing["use_sources"] = capture_use_sources(sketch)
            editing["grouping_started"] = True
            while doc.UndoCount > editing["undo_before"]:
                doc.undo()
            sketch = doc.getObject(editing["feature"])
            if sketch is None:
                raise OperationError("sketch_history_changed", "The accepted sketch no longer exists in native history")
            doc.openTransaction(f"KurtShape: edit {label}")
            restore_use_sources(doc, editing["use_sources"])
            restore_sketch_content(sketch, final)
            prune_use_sources(doc, editing["feature"])
            self._recompute(doc)
            errors = self._build_status(doc)
            if errors:
                raise OperationError("build_failed", "Grouped sketch edit could not rebuild native features", features=errors)
            doc.commitTransaction()
            editing.pop("grouping_started", None)

    def _preserve_sketch_draft(self, doc, draft):
        """Recover a rejected command or finalization without discarding the lease."""
        editing = self.sketch_edits[self._meta(doc).DocumentId]
        if editing.pop("grouping_started", False):
            if doc.HasPendingTransaction:
                doc.abortTransaction()
            if doc.UndoCount < editing["undo_before"]:
                raise OperationError("sketch_history_changed", "Native history crossed the edit checkpoint; draft recovery required")
            while doc.UndoCount > editing["undo_before"]:
                doc.undo()
        sketch = doc.getObject(editing["feature"])
        if sketch is None:
            raise OperationError("sketch_history_changed", "The edited sketch no longer exists; draft recovery required")
        if not doc.HasPendingTransaction:
            doc.openTransaction(f"KurtShape: edit {sketch.Label}")
        if editing.get("use_sources"):
            from .sketch_tools import restore_use_sources
            restore_use_sources(doc, editing["use_sources"])
        restore_sketch_content(sketch, draft)
        self._recompute(doc)
        editing["signature"] = self._sketch_edit_signature(doc, sketch.Name)
        self._new_revision(doc)

    def _native_history(self, doc, op):
        """Skip discard-only boundaries while preserving native model history."""
        names = "UndoNames" if op == "undo" else "RedoNames"
        while getattr(doc, names) and getattr(doc, names)[0] == SKETCH_CANCEL_BOUNDARY:
            getattr(doc, op)()
            self._new_revision(doc)
        if not getattr(doc, names):
            raise OperationError("empty_history", f"No {op} available")
        getattr(doc, op)()
        if op == "redo":
            while doc.RedoNames and doc.RedoNames[0] == SKETCH_CANCEL_BOUNDARY:
                doc.redo()

    @staticmethod
    def _modified(doc):
        if getattr(App, "GuiUp", False):
            import FreeCADGui as Gui
            gui_doc = Gui.getDocument(doc.Name)
            if gui_doc is not None:
                return gui_doc.Modified
        return None

    @staticmethod
    def _restore_modified(doc, value):
        if value is not None:
            import FreeCADGui as Gui
            Gui.getDocument(doc.Name).Modified = value

    def _restore_native_map_versions(self, doc):
        """Restore hidden Body and datum-plane markers from their stored maps."""
        modified = self._modified(doc)
        try:
            for obj in doc.Objects:
                if (obj.TypeId in ("PartDesign::Body", "PartDesign::Plane") and "_ElementMapVersion" in obj.PropertiesList
                        and not obj._ElementMapVersion and not obj.Shape.isNull()):
                    version = obj.getElementMapVersion("Shape")
                    if version:
                        obj._ElementMapVersion = version
        finally:
            self._restore_modified(doc, modified)

    @staticmethod
    def _expects_shape(obj):
        flags = set(obj.State)
        if flags & {"Touched", "Invalid", "Error"}:
            return False
        if obj.TypeId == "PartDesign::Body":
            return obj.Tip is not None and not set(obj.Tip.State) & {"Touched", "Invalid", "Error"}
        if obj.TypeId == "Sketcher::SketchObject":
            return any(not obj.getConstruction(index) for index in range(obj.GeometryCount))
        return obj.TypeId.startswith("PartDesign::") and not getattr(obj, "Suppressed", False)

    def _rebuild_reason_on_open(self, doc, adopt=False, saved_program_version=None):
        meta = self._meta(doc)
        modified = self._modified(doc)
        try:
            ensure_engine_properties(meta)
            stamp = engine_stamp()
            stored = meta.EngineFreeCAD, meta.EngineOCCT
            version = App.Version()
            recorded_version = doc.getProgramVersion() if saved_program_version is None else saved_program_version
            same_build = recorded_version == f"{version[0]}.{version[1]}R{version[3]}"
            if adopt and same_build and not any(self._expects_shape(obj) and obj.Shape.isNull()
                                                for obj in doc.Objects if hasattr(obj, "Shape") and studio.is_active(obj)):
                self._mark_rebuilt(doc)
                return
            reason = ("engine_changed" if any(stored) and stored != stamp else
                      "saved_by_other_build" if not same_build else
                      "engine_unrecorded" if not all(stored) else meta.RebuildReason)
            if meta.RebuildReason != reason:
                meta.RebuildReason = reason
        finally:
            self._restore_modified(doc, modified)

    def _mark_rebuilt(self, doc):
        meta = self._meta(doc)
        ensure_engine_properties(meta)
        meta.EngineFreeCAD, meta.EngineOCCT = engine_stamp()
        meta.RebuildReason = ""

    def _check_status(self, objects):
        targets = [obj for obj in objects if not obj.Shape.isNull() and obj.Shape.Solids]
        if not targets:
            return "not_applicable"
        checks = [self.geometry.check(obj) for obj in targets]
        return "invalid" if any(check is not None and not check["valid"] for check in checks) else (
            "not_checked" if any(check is None for check in checks) else "valid")

    def _build_status(self, doc, included=None):
        errors = native_assembly.validation_errors(doc, self.observer.state(doc)["generation"])
        errors.extend(studio.validation_errors(doc))
        errors.extend(native_selectors.reference_errors(doc))
        pending = []
        missing = []
        if any(error.get("code") == "auto_merge_scope_pending" for error in errors):
            pending.append("auto_merge_scope")
            errors = [error for error in errors if error.get("code") != "auto_merge_scope_pending"]
        for obj in doc.Objects:
            if obj.Name == METADATA or not studio.is_active(obj):
                continue
            flags = set(obj.State)
            if obj.TypeId == "Sketcher::SketchObject":
                errors.extend(sketch_reference_errors(obj))
            if "Touched" in flags and obj.TypeId.startswith(("Sketcher::","PartDesign::", "Part::", "Assembly::", "App::Link")):
                pending.append(obj.Name)
            if "Invalid" in flags or "Error" in flags:
                errors.append({"feature": obj.Name, "message": obj.getStatusString()})
            if hasattr(obj, "Shape") and self._expects_shape(obj) and obj.Shape.isNull():
                missing.append(obj.Name)
        included = native_results(doc) if included is None else included
        solids = [obj for obj in included if not obj.Shape.isNull() and obj.Shape.Solids]
        solid = bool(solids)
        for obj in solids:
            check = self.geometry.check(obj)
            if check is not None and not check["valid"]:
                errors.append({"feature": obj.Name, "message": "Invalid solid", "issues": check["issues"]})
        meta = self._meta(doc)
        reason = getattr(meta, "RebuildReason", "") or ("missing_shapes" if missing else None)
        self.observer.state(doc)["rebuild_reason"] = reason
        status = "failed" if errors else ("needs_rebuild" if pending or reason else ("valid" if solid else "sketch_only"))
        if meta.BuildStatus != status:
            modified = self._modified(doc)
            try:
                meta.BuildStatus = status
            finally:
                self._restore_modified(doc, modified)
        return errors

    def inspect(self, doc, measure=None):
        return self.timings.measure("inspection", self._inspect, doc, self._measure_level(measure))

    def _inspect(self, doc, measure):
        included = native_results(doc)
        errors = self.sync(doc, included)
        meta = self._meta(doc)
        features = []
        for obj in doc.Objects:
            if obj.Name == METADATA or obj.TypeId.startswith(("App::Origin", "App::Line", "App::Plane")):
                continue
            features.append(native_feature_summary(obj) if os.environ.get("KURTSHAPE_FULL_INSPECTION") == "1"
                            else inspection_cache.feature_summary(obj, self.observer, native_feature_summary))
        # Hidden native helpers own real inputs (for example an up-to-face Pad
        # or a split datum). Surface their health on the user-facing operation.
        feature_rows = {feature["id"]: feature for feature in features}
        for obj in doc.Objects:
            operation = getattr(obj, "KurtShapeOperationOwner", "")
            row = feature_rows.get(operation)
            if row is None or obj.Name == operation or "QueryInputs" not in obj.PropertiesList:
                continue
            row.setdefault("reference_consumers", []).append(obj.Name)
            for entry in json.loads(getattr(obj, "QueryHealth", "[]")):
                row["reference_health"].append(dict(entry, native_feature=obj.Name,
                                                   input=obj.Name + "." + entry["input"]))
        studio_state = studio.inspect(doc)
        if studio_state:
            positions = {name: index for index, name in enumerate(studio_state["feature_order"])}
            features.sort(key=lambda feature: positions.get(feature["id"], len(positions)))
            for feature in features:
                feature["rolled_back"] = feature["id"] in positions and positions[feature["id"]] >= studio_state["rollback_index"]
        available_geometry = self._geometry(doc, included, measure)
        measured_geometry = available_geometry if meta.BuildStatus=="valid" else None
        evaluated_results = []
        for obj in included:
            flags = set(obj.State) | {flag for member in getattr(obj, "Group", []) if studio.is_active(member) for flag in member.State}
            metrics = self._evaluated_shape(doc, obj, measure) if not obj.Shape.isNull() and obj.Shape.Solids else None
            status = "failed" if flags & {"Invalid", "Error"} or metrics and metrics["valid"] is False else ("needs_rebuild" if "Touched" in flags or getattr(meta, "RebuildReason", "") else ("valid" if metrics else "sketch_only"))
            if native_assembly.assemblies(doc) and meta.BuildStatus in {"failed", "needs_rebuild"}:
                status = meta.BuildStatus
            evaluated_results.append({"id": obj.Name, "name": obj.Label, "type": obj.TypeId, "build_status": status,
                                      "geometry_check": self._check_status([obj]),
                                      "measurements": metrics if status == "valid" else None,
                                      "retained_geometry_measurements": metrics if status in {"failed", "needs_rebuild"} else None})
        unsupported = [obj.Name for obj in doc.Objects if obj.Name != METADATA and
                       (any(link.Document != doc for link in obj.OutList) or
                        (obj.TypeId.endswith("Python") or "Proxy" in obj.PropertiesList) and not native_assembly.safe_object(obj))]
        return {"document_id": meta.DocumentId, "revision": meta.Revision, "name": doc.Label,
                "native_file": doc.FileName or None, "units": "mm", "build_status": meta.BuildStatus,
                "build_errors": errors, "features": features,
                "rebuild_reason": self.observer.state(doc).get("rebuild_reason"), "geometry_check": self._check_status(included),
                "measurements": measured_geometry, "retained_geometry_measurements": available_geometry if meta.BuildStatus in {"failed","needs_rebuild"} else None,
                "last_failed_attempt": self.last_failures.get(meta.DocumentId),
                "active_sketch_edit": self.sketch_edits.get(meta.DocumentId, {}).get("feature"),
                "managed": self.is_managed(doc), "unsupported_objects": unsupported, "bodies": evaluated_results,
                "import_source": json.loads(getattr(meta, "ImportSource", "{}")) or None,
                "assembly": native_assembly.inspect(doc),
                "studio": studio_state,
                "operations": sorted(self.OPS if self.is_managed(doc) else self.READ_OPS | self.CREATE_OPS | {"adopt"})}

    def dispatch(self, request):
        tracked = isinstance(request, dict) and request.get("op") not in self.READ_OPS and "request_id" in request
        if tracked:
            try:
                replay = self.ledger.register(request, "started")
            except (ValueError, TypeError):
                return {"ok": False, "error": {"code": "invalid_argument", "message": "Request must contain finite JSON values"}}
            if replay is not None:
                return replay
        response = self.timings.measure("operation", self._dispatch, request)
        if tracked:
            self.ledger.complete(request["request_id"], response)
        return response

    def _dispatch(self, request):
        start = time.perf_counter()
        doc = None
        transaction = False
        draft = None
        draft_history = None
        created_feature = None
        owns_busy = False
        assembly_transaction_id = None
        model_transaction_id = None
        try:
            self._prune_closed_sketch_edits()
            if not isinstance(request, dict) or request.get("op") not in self.OPS:
                raise OperationError("unsupported_operation", "Unknown operation")
            op = request["op"]
            unknown = set(request) - self.ARGS[op] - {"op", "document_id", "expected_revision", "request_id", "measure"}
            if unknown:
                raise OperationError("unknown_argument", "Unsupported request fields", fields=sorted(unknown))
            if "measure" in request and request["measure"] is None:
                raise OperationError("invalid_argument", 'measure must be false, true or "full"')
            measure = self._measure_level(request.get("measure"))
            if op == "capabilities":
                return {"ok": True, "result": {"contract": CONTRACT_VERSION, "contract_revision": CONTRACT_REVISION, "session_id": self.ledger.session_id,
                    "measurement": {"levels": [False, True, "full"], "default": self.default_measure,
                                    "fields": {"false": ["solid_count"], "true": ["solid_count", "volume_mm3", "area_mm2", "bbox_mm"],
                                               "full": ["solid_count", "volume_mm3", "area_mm2", "bbox_mm", "center_of_mass_mm"]}},
                    "geometry_check": {"operation": "check_geometry", "export": "required", "interactive": "native feature state only"},
                    "operations": sorted(self.OPS), "preview_operations": sorted(self.MODEL_OPS - {"rebuild"}),
                    "import_formats": [".step", ".stp"],
                    "assembly": {"level": "single", "source_formats": [".fcstd", ".step", ".stp"], "source_policy": "embedded_shape_snapshot",
                                 "joint_types": ["fixed", "revolute", "slider"], "solver": "native FreeCAD Assembly",
                                 "motion_units": {"revolute": "deg", "slider": "mm"}, "nested_assemblies": False},
                    "retry": {"scope": "session", "result_limit": self.ledger.limit, "session_request_limit": self.ledger.session_request_limit,
                              "missing_status": "not_recorded does not prove a request never executed; reconcile after restart or eviction"},
                    "request_size_limit_bytes": 65536, "engine": {"FreeCAD": App.Version(), "OCCT": Part.OCC_VERSION}}}
            if op == "request_status":
                return {"ok": True, "result": self.ledger.status(request.get("request_id"))}
            if op == "diagnostics":
                return {"ok": True, "result": {"timings": self.timings.report(), "engine": {"FreeCAD": App.Version(), "OCCT": Part.OCC_VERSION},
                    "recovery_directory": str(self.recovery.directory), "checkpoint_interval_seconds": self.recovery.interval_seconds}}
            if op == "list_documents":
                return {"ok": True, "result": {"documents": [self.inspect(d, measure) for d in self.documents.values() if self._is_open(d)]}}
            if op == "assembly_candidates":
                if self.busy:
                    raise OperationError("busy", "Finish the active operation before inspecting an assembly source")
                if self.sketch_edits or getattr(App, "GuiUp", False) and self._native_edit_active():
                    raise OperationError("sketch_edit_active", "Finish graphical editing before choosing an assembly source")
                self.busy = owns_busy = True
                return {"ok": True, "result": {"candidates": native_assembly.candidates(request.get("path")), "source_policy": "embedded_shape_snapshot"}}
            if op not in self.READ_OPS and self.busy:
                raise OperationError("busy", "A modeling operation is already active")
            if op in self.CREATE_OPS and any(identifier in self.sketch_edits and self._is_open(existing)
                                                         for identifier, existing in self.documents.items()):
                raise OperationError("sketch_edit_active", "Finish or cancel the active sketch before changing documents")
            if op in self.CREATE_OPS and getattr(App, "GuiUp", False):
                import FreeCADGui as Gui
                if Gui.Control.activeDialog() or any(Gui.getDocument(name) and Gui.getDocument(name).getInEdit() for name in App.listDocuments()):
                    raise OperationError("sketch_edit_active", "Finish or cancel graphical editing before changing documents")
            if op == "new":
                self.busy = owns_busy = True
                doc = self.attach(App.newDocument("KurtShape"))
                doc.Label = str(request.get("name", "New part"))[:120]
                doc.addObject("PartDesign::Body", "Body")
                self._recompute(doc)
                self._mark_rebuilt(doc)
                self.signatures[self._meta(doc).DocumentId] = self._signature(doc)
            elif op == "import_step":
                self.busy = owns_busy = True
                doc = self._import_step(request.get("path"))
            elif op in {"open", "recover"}:
                self.busy = owns_busy = True
                recovery_record = None
                if op == "recover":
                    path, recovery_record = self.recovery.read(request["path"])
                else:
                    path = Path(request["path"]).resolve()
                if path.suffix.lower() != ".fcstd" or not path.is_file():
                    raise OperationError("invalid_format", "Open requires an existing native .FCStd file")
                doc = App.openDocument(str(path))
                try:
                    self.attach(doc, managed=doc.getObject(METADATA) is not None)
                except OperationError:
                    App.closeDocument(doc.Name)
                    doc=None
                    raise
                if self.is_managed(doc):
                    if op == "recover":
                        for obj in doc.Objects:
                            if obj.TypeId.startswith(("Sketcher::", "PartDesign::")) or studio.enabled(doc) and obj.TypeId.startswith(("Part::", "App::Link")):
                                obj.touch()
                        self._recompute(doc)
                    elif not self.observer.state(doc).get("hasher_migrated"):
                        self._rebuild_reason_on_open(doc)
                        studio.refresh_validation(doc)
                    if native_assembly.inspect(doc):
                        try:
                            native_assembly.solve(doc)
                        except native_assembly.AssemblyError as assembly_error:
                            self.last_failures[self.identifier(doc)] = {"request": request,
                                "error": {"code": assembly_error.code, "message": str(assembly_error)}, "rejected": False}
                            self._meta(doc).LastFailure = json.dumps(self.last_failures[self.identifier(doc)])
                        self._recompute(doc)
                if recovery_record:
                    doc.FileName = ""
                    feature = recovery_record.get("sketch")
                    if feature:
                        import base64
                        sketch = doc.getObject(feature)
                        initial = base64.b64decode(recovery_record["accepted_sketch"], validate=True)
                        draft = base64.b64decode(recovery_record["draft_sketch"], validate=True) if recovery_record.get("draft_sketch") else bytes(sketch.dumpContent())
                        restore_sketch_content(sketch, initial)
                        self._recompute(doc)
                        undo_before = doc.UndoCount
                        doc.openTransaction("KurtShape: recover unfinished sketch")
                        restore_sketch_content(sketch, draft)
                        self._recompute(doc)
                        self.sketch_edits[self.identifier(doc)] = {"feature": feature, "initial": initial,
                            "undo_before": undo_before, "signature": self._sketch_edit_signature(doc, feature),
                            "undo": [initial, draft], "redo": []}
                        self._new_revision(doc)
            else:
                doc = self._doc(request)
                check_report = None
                if op == "resolve_selector":
                    return {"ok": True, "result": {"matches": native_selectors.resolve(doc, request.get("selector"))}}
                if op == "preview":
                    return {"ok": True, "result": self._preview(doc, request)}
                if not self.is_managed(doc) and op not in self.READ_OPS | {"adopt"}:
                    raise OperationError("unmanaged_document", "Inspect this native file or adopt a copy before editing")
                if op not in self.READ_OPS:
                    expected = request.get("expected_revision")
                    if expected != self._meta(doc).Revision:
                        raise OperationError("stale_revision", "Inspect the current document before mutating", expected=expected, actual=self._meta(doc).Revision)
                    if self.busy:
                        raise OperationError("busy", "A modeling operation is already active")
                    editing = self.sketch_edits.get(self._meta(doc).DocumentId)
                    if editing:
                        if op not in self.EDIT_OPS:
                            raise OperationError("sketch_edit_active", "Finish or cancel the managed sketch before another operation", feature=editing["feature"])
                        target = request.get("sketch") if op.startswith("add_") or op in {"pierce", "project_geometry", "set_sketch_support"} else request.get("feature")
                        if target is not None and target != editing["feature"]:
                            raise OperationError("managed_sketch_mismatch", "Only the sketch in the active edit session may be changed", feature=editing["feature"])
                    if getattr(App, "GuiUp", False):
                        import FreeCADGui as Gui
                        if op in self.ASSEMBLY_OPS and self._native_edit_active():
                            raise OperationError("sketch_edit_active", "Finish graphical editing before changing the assembly")
                        native_edit = Gui.activeDocument().getInEdit() if Gui.activeDocument() else None
                        native_object = getattr(native_edit, "Object", native_edit)
                        managed_native_edit = bool(editing and native_object and native_object.Document == doc
                                                   and native_object.Name == editing["feature"])
                        if (Gui.Control.activeDialog() or native_edit) and not managed_native_edit:
                            raise OperationError("sketch_edit_active", "Finish or cancel graphical editing before another operation")
                    self.busy = True
                    owns_busy = True
                if op == "adopt":
                    doc = self._adopt(doc, request["path"])
                elif op == "check_geometry":
                    began = time.perf_counter()
                    targets = native_results(doc)
                    if "body" in request:
                        target = next((obj for obj in targets if obj.Name == request["body"] or getattr(obj, "KurtShapePartId", None) == request["body"]), None)
                        if target is None:
                            raise OperationError("missing_body", "body must identify a current solid result")
                        targets = [target]
                    targets = [obj for obj in targets if not obj.Shape.isNull() and obj.Shape.Solids]
                    if not targets:
                        raise OperationError("no_solid", "No solid result is available to check")
                    checks = [(obj, self.geometry.check(obj, compute=True)) for obj in targets]
                    self._build_status(doc)
                    check_report = {"status": "valid" if all(check["valid"] for _, check in checks) else "invalid",
                                    "revision": self._meta(doc).Revision, "engine": {"FreeCAD": App.Version(), "OCCT": Part.OCC_VERSION},
                                    "bodies": [{"id": obj.Name, "valid": check["valid"], "issues": check["issues"], "check_ms": check["ms"]}
                                               for obj, check in checks], "ms": (time.perf_counter() - began) * 1000}
                elif op == "begin_sketch_edit":
                    sketch = self._profile(doc, request["feature"])
                    self._body(doc, request, sketch)
                    if doc.HasPendingTransaction:
                        raise OperationError("unmanaged_transaction", "Finish the existing native transaction before starting sketch editing")
                    undo_before = doc.UndoCount
                    initial = bytes(sketch.dumpContent())
                    doc.openTransaction(f"KurtShape: edit {sketch.Label}")
                    self.sketch_edits[self._meta(doc).DocumentId] = {
                        "feature": sketch.Name, "signature": self._sketch_edit_signature(doc, sketch.Name),
                        "initial": initial, "undo_before": undo_before,
                        "undo": [initial], "redo": []}
                    self._new_revision(doc)
                elif op == "finish_sketch_edit":
                    editing = self.sketch_edits.get(self._meta(doc).DocumentId)
                    if not editing:
                        raise OperationError("no_sketch_edit", "No managed sketch edit session is active")
                    if not isinstance(request.get("cancel", False), bool):
                        raise OperationError("invalid_argument", "cancel must be boolean")
                    # The GUI must resetEdit first; that stops Sketcher's tools
                    # before this shared transaction is committed or aborted.
                    if getattr(App, "GuiUp", False):
                        import FreeCADGui as Gui
                        gui_doc = Gui.getDocument(doc.Name)
                        if gui_doc and gui_doc.getInEdit():
                            raise OperationError("sketch_editor_open", "Close the native sketch editor before finishing the managed session")
                    transaction = True
                    if request.get("cancel", False):
                        self._rollback_sketch_edit(doc)
                    else:
                        draft = bytes(doc.getObject(editing["feature"]).dumpContent())
                        self._profile(doc, editing["feature"])
                        self._recompute(doc)
                        errors = self._build_status(doc)
                        if errors:
                            raise OperationError("build_failed", "Finishing sketch editing could not rebuild native features", features=errors)
                        self._commit_sketch_edit(doc)
                    self.sketch_edits.pop(self._meta(doc).DocumentId, None)
                    transaction = False
                    self._recompute(doc)
                    self._new_revision(doc)
                elif op in self.ASSEMBLY_OPS:
                    if op != "create_assembly":
                        native_assembly.get(doc, request.get("assembly"))
                    if doc.HasPendingTransaction:
                        raise OperationError("unmanaged_transaction", "Finish the native transaction before changing the assembly")
                    doc.openTransaction(f"KurtShape: {op.replace('_', ' ')}")
                    assembly_transaction_id = (App.getActiveTransaction() or (None, None))[1]
                    transaction = True
                    created_feature = native_assembly.handle(doc, request)
                    created_feature = created_feature.Name if hasattr(created_feature, "Name") else created_feature
                    self._recompute(doc)
                    errors = self._build_status(doc)
                    if errors:
                        raise OperationError("build_failed", "Assembly could not solve or rebuild", features=errors)
                    doc.commitTransaction()
                    if assembly_transaction_id is not None and (App.getActiveTransaction() or (None, None))[1] == assembly_transaction_id:
                        App.closeActiveTransaction()
                    transaction = False
                    self._new_revision(doc)
                elif op in self.MODEL_OPS:
                    editing = self.sketch_edits.get(self._meta(doc).DocumentId)
                    if editing:
                        draft = bytes(doc.getObject(editing["feature"]).dumpContent())
                        draft_history = (list(editing["undo"]), list(editing["redo"]))
                        # Native Sketcher tools commit their command on Escape
                        # while the managed edit lease remains open. Continue
                        # that lease in a native transaction before authoring
                        # selector links or further sketch geometry.
                        if not doc.HasPendingTransaction:
                            doc.openTransaction(f"KurtShape: edit {doc.getObject(editing['feature']).Label}")
                    if not editing:
                        if op == "duplicate_feature" and doc.HasPendingTransaction:
                            raise OperationError("unmanaged_transaction", "Finish the native transaction before another operation")
                        doc.openTransaction(f"KurtShape: {op}")
                        model_transaction_id = (App.getActiveTransaction() or (None, None))[1]
                    transaction = True
                    created_feature = self._model_operation(doc, request)
                    studio.reconcile(doc)
                    self._recompute(doc)
                    if op == "rebuild":
                        self._mark_rebuilt(doc)
                    errors = self._build_status(doc)
                    if errors and not editing:
                        raise OperationError("build_failed", "Native feature rebuild failed", features=errors)
                    affected = doc.getObject(request.get("profile") or request.get("feature") or created_feature or "")
                    affected_body = owner(doc, affected)
                    if not editing and affected_body and not studio.enabled(doc) and (op in {"pad", "pocket"} or op in {"set_parameter", "set_expression", "duplicate_feature"} and affected_body.Tip and affected_body.Tip.TypeId != "Sketcher::SketchObject"):
                        if self._meta(doc).BuildStatus != "valid" or len(affected_body.Shape.Solids) != 1:
                            raise OperationError("build_failed", "Operation must produce one valid solid")
                    if not editing:
                        doc.commitTransaction()
                        if model_transaction_id is not None and (App.getActiveTransaction() or (None, None))[1] == model_transaction_id:
                            App.closeActiveTransaction()
                    transaction = False
                    self._new_revision(doc)
                elif op in {"undo", "redo"}:
                    editing = self.sketch_edits.get(self._meta(doc).DocumentId)
                    if editing:
                        sketch = doc.getObject(editing["feature"])
                        if op == "undo":
                            if len(editing["undo"]) < 2:
                                raise OperationError("empty_history", "No sketch edit to undo")
                            editing["redo"].append(editing["undo"].pop())
                            snapshot = editing["undo"][-1]
                        else:
                            if not editing["redo"]:
                                raise OperationError("empty_history", "No sketch edit to redo")
                            snapshot = editing["redo"].pop()
                            editing["undo"].append(snapshot)
                        restore_sketch_content(sketch, snapshot)
                        self._recompute(doc)
                        editing["signature"] = self._sketch_edit_signature(doc, sketch.Name)
                    else:
                        self._native_history(doc, op)
                    self._recompute(doc)
                    self._new_revision(doc)
                elif op == "save":
                    self._save(doc, request["path"])
                elif op == "export":
                    self._export(doc, request["path"], request.get("body"))
            result = self.inspect(doc, measure)
            if op == "check_geometry":
                result["geometry_check_report"] = check_report
            if created_feature:
                result["created_feature"] = created_feature
            if op in {"save", "open"} and getattr(App, "GuiUp", False):
                import FreeCADGui as Gui
                # saveCopy intentionally preserves the GUI dirty flag; open
                # touches session metadata/rebuild caches. Only clear the UI
                # flag after the successful disk operation and final inspect.
                # This neither rewrites the accepted file nor changes undo.
                Gui.getDocument(doc.Name).Modified = False
            if op == "import_step" and getattr(App, "GuiUp", False):
                import FreeCADGui as Gui
                Gui.getDocument(doc.Name).Modified = True
            result["operation_ms"] = round((time.perf_counter() - start) * 1000, 2)
            return {"ok": True, "result": result}
        except Exception as caught:
            exc = caught
            if transaction and doc:
                ended_edit = self._meta(doc).DocumentId in self.sketch_edits
                if ended_edit:
                    if draft is not None:
                        try:
                            self.recovery.capture(doc, self._meta(doc), self.sketch_edits[self.identifier(doc)], force=True, draft=draft)
                        except Exception as recovery_error:
                            self.last_failures[self.identifier(doc)] = {"recovery_error": str(recovery_error)}
                    try:
                        if draft is not None:
                            self._preserve_sketch_draft(doc, draft)
                            if draft_history is not None:
                                editing = self.sketch_edits[self._meta(doc).DocumentId]
                                editing["undo"], editing["redo"] = draft_history
                        else:
                            self._rollback_sketch_edit(doc)
                    except Exception as rollback_error:
                        # An external native history change must be reported,
                        # never escaped from dispatch or repaired by undoing
                        # unrelated accepted transactions.
                        exc = rollback_error
                        self._new_revision(doc)
                else:
                    doc.abortTransaction()
                    if assembly_transaction_id is not None and (App.getActiveTransaction() or (None, None))[1] == assembly_transaction_id:
                        App.closeActiveTransaction(True)
                    if model_transaction_id is not None and (App.getActiveTransaction() or (None, None))[1] == model_transaction_id:
                        App.closeActiveTransaction(True)
                    self._recompute(doc)
                    self.signatures[self._meta(doc).DocumentId] = self._signature(doc)
                    self.observer.state(doc).pop("assembly_source_changed", None)
                    self._build_status(doc)
            known_error = isinstance(exc, (OperationError, native_assembly.AssemblyError))
            code = exc.code if known_error else "operation_failed"
            if not known_error:
                log_path = Path(os.environ.get("KURTSHAPE_SESSION_DIR", str(ROOT / "runtime"))) / "kurtshape.log"
                try:
                    log_path.parent.mkdir(parents=True, exist_ok=True)
                    with log_path.open("a", encoding="utf-8") as log:
                        log.write(traceback.format_exc() + "\n")
                except OSError:
                    pass
            error = {"code": code, "message": str(exc), **(getattr(exc, "details", {}) if known_error else {})}
            if doc and code not in {"stale_revision", "busy", "sketch_edit_active", "managed_sketch_mismatch", "sketch_editor_open"}:
                self.last_failures[self._meta(doc).DocumentId] = {"request": request, "error": error, "rejected": True}
                self._meta(doc).LastFailure=json.dumps(self.last_failures[self._meta(doc).DocumentId])
            return {"ok": False, "error": error}
        finally:
            if owns_busy:
                self.busy = False

    def _new_revision(self, doc):
        meta = self._meta(doc)
        meta.Revision = str(uuid.uuid4())
        self.signatures[meta.DocumentId] = self._signature(doc)
        self.observer.state(doc)["intent_dirty"] = False
        self.observer.state(doc).pop("assembly_source_changed", None)
        self._record_sketch_edit(doc)
        self._build_status(doc)

    def _preview(self, doc, request):
        if self.busy:
            raise OperationError("busy", "Finish the active operation before previewing")
        if not self.is_managed(doc):
            raise OperationError("unmanaged_document", "Adopt a copy before previewing changes")
        if request.get("expected_revision") != self._meta(doc).Revision:
            raise OperationError("stale_revision", "Inspect before previewing a proposal")
        if self._meta(doc).DocumentId in self.sketch_edits or doc.HasPendingTransaction:
            raise OperationError("sketch_edit_active", "Finish editing before previewing")
        if getattr(App, "GuiUp", False):
            import FreeCADGui as Gui
            if Gui.Control.activeDialog() or any(Gui.getDocument(name).getInEdit() for name in App.listDocuments()):
                raise OperationError("sketch_edit_active", "Finish graphical editing before previewing")
        proposal = request.get("proposal")
        if not isinstance(proposal, dict) or proposal.get("op") not in self.MODEL_OPS - {"rebuild"} or set(proposal) - self.ARGS[proposal["op"]] - {"op"}:
            raise OperationError("unsupported_preview", "Preview requires a supported typed modeling operation")
        import tempfile
        from .extrusion_preview import _capture_gui, _restore_gui
        clone = None
        preview_transaction_id = None
        active = App.ActiveDocument
        gui_state = _capture_gui(doc)
        previous_busy = self.busy
        self.busy = True
        try:
            with tempfile.TemporaryDirectory(prefix="kurtshape-parameter-preview-") as temporary:
                path = Path(temporary) / "native-preview.FCStd"
                doc.saveCopy(str(path))
                clone = App.openDocument(str(path), True)
                failure = None
                try:
                    clone.openTransaction("KurtShape: disposable preview")
                    preview_transaction_id = (App.getActiveTransaction() or (None, None))[1]
                    self._model_operation(clone, proposal)
                    studio.reconcile(clone)
                    self._recompute(clone)
                    errors = self._build_status(clone)
                    if errors:
                        raise OperationError("build_failed", "Preview could not rebuild", features=errors)
                    affected_body = owner(clone, clone.getObject(proposal.get("feature", "")))
                    if affected_body and not studio.enabled(clone) and affected_body.Tip and affected_body.Tip.TypeId != "Sketcher::SketchObject":
                        if self._meta(clone).BuildStatus != "valid" or len(affected_body.Shape.Solids) != 1:
                            raise OperationError("build_failed", "Preview must produce one valid solid in the affected Body")
                except Exception as exc:
                    failure = {"code": getattr(exc, "code", "preview_failed"), "message": str(exc)}
                errors = self._build_status(clone)
                status = self._meta(clone).BuildStatus
                evaluated = {"build_status": status, "build_errors": errors,
                             "measurements": self._geometry(clone, measure=request.get("measure")) if status == "valid" else None}
                clone.commitTransaction()
                if preview_transaction_id is not None and (App.getActiveTransaction() or (None, None))[1] == preview_transaction_id:
                    App.closeActiveTransaction()
                return {"base_revision": request["expected_revision"], "proposal": proposal,
                        "valid": failure is None and evaluated["build_status"] in {"valid", "sketch_only"},
                        "error": failure, "build_status": evaluated["build_status"], "build_errors": evaluated["build_errors"],
                        "measurements": evaluated["measurements"], "discarded": True}
        finally:
            try:
                if clone:
                    name = clone.Name
                    if clone.HasPendingTransaction:
                        clone.abortTransaction()
                    if preview_transaction_id is not None and (App.getActiveTransaction() or (None, None))[1] == preview_transaction_id:
                        App.closeActiveTransaction(True)
                    App.closeDocument(name)
                    self.geometry.drop_document(name)
                    self.observer.states.pop(name, None)
                if active and self._is_open(active):
                    App.setActiveDocument(active.Name)
                if self._is_open(doc):
                    _restore_gui(doc, gui_state)
            finally:
                self.busy = previous_busy

    def _adopt(self, source, raw):
        path = write_path(raw, {".fcstd"}, self.settings.roots)
        if path.exists() or source.FileName and path == Path(source.FileName).resolve():
            raise OperationError("adoption_destination_exists", "Adoption requires a new file, preserving the original")
        unsupported = self.inspect(source)["unsupported_objects"]
        if unsupported:
            raise OperationError("unsupported_adoption", "Resolve script-owned objects or external document links before adoption", objects=unsupported)
        import tempfile
        clone = None
        saved_program_version = source.getProgramVersion()
        try:
            with tempfile.TemporaryDirectory(prefix="kurtshape-native-adoption-") as temporary:
                source.saveCopy(str(Path(temporary) / "adoption-source.FCStd"))
                clone = App.openDocument(str(Path(temporary) / "adoption-source.FCStd"))
                clone.openTransaction("KurtShape: adopt native copy")
                meta = metadata(clone)
                meta.DocumentId = str(uuid.uuid4())
                self._rebuild_reason_on_open(clone, adopt=True, saved_program_version=saved_program_version)
                self._recompute(clone)
                clone.commitTransaction()
                self.attach(clone)
                self._save(clone, str(path))
                return clone
        except Exception:
            if clone:
                self.documents.pop(self.identifier(clone), None)
                App.closeDocument(clone.Name)
            raise

    def _import_step(self, raw):
        """Read neutral geometry, then publish a complete new native project.

        Flatten STEP occurrences into independent Bodies with native base
        features. Keep non-solid leaves as references rather than dropping
        them. No edits, writes or transactions touch the current document.
        """
        if not isinstance(raw, str) or not Path(raw).is_absolute():
            raise OperationError("invalid_argument", "STEP source must be an absolute file path")
        path = Path(raw).resolve()
        if path.suffix.lower() not in {".step", ".stp"}:
            raise OperationError("invalid_format", "Import requires a .step or .stp file")
        if not path.is_file():
            raise OperationError("missing_file", "STEP source file does not exist")

        def digest():
            with path.open("rb") as source:
                return hashlib.file_digest(source, "sha256").hexdigest()

        source_hash = digest()
        try:
            shape = Part.read(str(path))
        except Exception as exc:
            raise OperationError("step_import_failed", "STEP could not be read; check the source file", reason=str(exc)) from exc
        if source_hash != digest():
            raise OperationError("source_changed", "STEP source changed while being imported; retry with a stable file")
        if shape.isNull():
            raise OperationError("empty_step", "STEP file contains no usable geometry")
        if not shape.isValid():
            raise OperationError("invalid_step_geometry", "STEP contains invalid geometry; repair it before importing")

        leaves = []
        def collect(item):
            if item.ShapeType in {"Compound", "CompSolid"}:
                for child in item.childShapes():
                    collect(child)
            else:
                leaves.append(item)
        collect(shape)
        if not leaves:
            raise OperationError("empty_step", "STEP file contains no usable geometry")

        active, imported = App.activeDocument(), None
        try:
            imported = App.newDocument("KurtShapeSTEP")
            imported.Label = path.stem[:120]
            solid_ids, reference_ids = [], []
            for leaf in leaves:
                if leaf.ShapeType == "Solid":
                    body = imported.addObject("PartDesign::Body", "Body")
                    body.Label = "Imported solid " + str(len(solid_ids) + 1)
                    base = body.newObject("PartDesign::Feature", "ImportedSolid")
                    base.Label = "STEP solid " + str(len(solid_ids) + 1)
                    base.Shape = leaf
                    body.Tip = base
                    solid_ids.append(body.Name)
                else:
                    reference = imported.addObject("Part::Feature", "ImportedReference")
                    reference.Label = "STEP reference " + str(len(reference_ids) + 1)
                    reference.Shape = leaf
                    reference_ids.append(reference.Name)
            meta = metadata(imported)
            meta.addProperty("App::PropertyString", "ImportSource", "KurtShape")
            meta.ImportSource = json.dumps({"format": "STEP", "path": str(path), "sha256": source_hash,
                "body_ids": solid_ids, "reference_ids": reference_ids,
                "feature_history": "unavailable", "assembly_structure": "flattened"}, sort_keys=True)
            meta.setEditorMode("ImportSource", 1)
            self._recompute(imported)
            self.attach(imported)
            self._mark_rebuilt(imported)
            if self._build_status(imported):
                raise OperationError("invalid_step_geometry", "Imported STEP could not form valid native geometry")
            return imported
        except Exception:
            if imported:
                identifier = self.identifier(imported)
                self.documents.pop(identifier, None)
                self.signatures.pop(identifier, None)
                App.closeDocument(imported.Name)
            if active and self._is_open(active):
                App.setActiveDocument(active.Name)
            raise

    def _id(self, doc, request, fallback):
        name = request.get("id", fallback)
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name):
            raise OperationError("invalid_argument", "Feature ID must be an ASCII letter followed by letters/digits/underscores")
        if doc.getObject(name):
            raise OperationError("duplicate_feature", f"Feature {name} already exists")
        return name

    def _profile(self, doc, name):
        obj = doc.getObject(name)
        if not obj or obj.TypeId != "Sketcher::SketchObject" or owner(doc, obj) is None:
            raise OperationError("missing_reference", "Profile must name a sketch in this body")
        if obj.solve() != 0:
            raise OperationError("constraint_conflict", "Sketch solver reports conflicting constraints")
        return obj

    def _dimension(self, sketch, constraint, name):
        i = sketch.addConstraint(constraint)
        existing = {item.Name for item in sketch.Constraints if item.Name}
        selected = name
        n = 2
        while selected in existing:
            selected = f"{name}_{n}"
            n += 1
        sketch.renameConstraint(i, selected)

    def _sketch_support(self, doc, req, body):
        if "plane" in req and "support" in req:
            raise OperationError("invalid_argument", "Choose one origin plane or one native planar support")
        if "support" not in req:
            plane = req.get("plane", "XY")
            if plane not in {"XY", "XZ", "YZ"}:
                raise OperationError("unsupported_plane", "Origin plane must be XY, XZ or YZ")
            return origin_plane(body, plane), ""
        reference = req["support"]
        if not isinstance(reference, dict) or not isinstance(reference.get("feature"), str) or set(reference) - {"feature", "subelement"}:
            raise OperationError("invalid_argument", "support requires a native feature ID and optional FaceN subelement")
        obj = doc.getObject(reference["feature"])
        if obj is None:
            raise OperationError("missing_reference", "Sketch support does not exist in this document")
        # A displayed Body face is owned by its current solid Tip. Link the
        # sketch to that feature, avoiding a self-reference through its Body.
        if obj == body:
            obj = body.Tip
        origins = list(body.Origin.OriginFeatures)
        if obj is None or (obj not in body.Group and obj not in origins):
            raise OperationError("unsupported_reference", "Sketch support must belong to the active native Body")
        element = reference.get("subelement", "")
        if obj.TypeId in {"App::Plane", "PartDesign::Plane"}:
            if element not in {"", None}:
                raise OperationError("unsupported_reference", "Select the datum plane itself, without a face subelement")
            return obj, ""
        if not isinstance(element, str) or not re.fullmatch(r"Face[1-9][0-9]*", element):
            raise OperationError("ambiguous_support", "A solid support must identify exactly one planar FaceN")
        if not hasattr(obj, "Shape") or obj.Shape.isNull() or not obj.Shape.Solids:
            raise OperationError("unsupported_reference", "Face support requires a native solid feature")
        index = int(element[4:]) - 1
        if index >= len(obj.Shape.Faces):
            raise OperationError("missing_reference", "Selected face does not exist")
        if not isinstance(obj.Shape.Faces[index].Surface, Part.Plane):
            raise OperationError("nonplanar_support", "A sketch needs a planar face or datum plane")
        return obj, element

    def _new_sketch(self, doc, req, fallback):
        target = doc.getObject(req.get("support", {}).get("feature", ""))
        body = self._body(doc, req, target)
        support, element = self._sketch_support(doc, req, body)
        sk = doc.addObject("Sketcher::SketchObject", self._id(doc, req, fallback))
        body.addObject(sk)
        sk.AttachmentSupport = (support, [element])
        sk.MapMode = "FlatFace"
        self._recompute(doc)
        if "Error" in sk.State or "Invalid" in sk.State:
            raise OperationError("attachment_failed", "Native sketch attachment failed", status=sk.getStatusString())
        if req.get("_support_selector"):
            native_selectors.bind(sk, "support", req["_support_selector"], native_property="AttachmentSupport")
        return sk

    def _set_sketch_support(self, doc, req, body):
        sk = self._profile(doc, req.get("sketch"))
        if ("plane" not in req and "support" not in req) or ("plane" in req and "support" in req):
            raise OperationError("invalid_argument", "Choose one origin plane or one native planar support")
        if "support" in req:
            name = req["support"].get("feature")
            source = doc.getObject(name) if isinstance(name, str) else None
            source = body.Tip if source == body else source
            if source is not None:
                from .sketch_tools import validate_reference_source
                validate_reference_source(doc, sk, source)
        support, element = self._sketch_support(doc, req, body)
        # Attachment moves the sketch coordinate frame. Its native Geometry,
        # Constraints and ExpressionEngine continue to describe local intent.
        native_selectors.unbind(sk, "support")
        sk.AttachmentSupport = (support, [element])
        sk.MapMode = "FlatFace"
        if req.get("_support_selector"):
            native_selectors.bind(sk, "support", req["_support_selector"], native_property="AttachmentSupport")
        self._recompute(doc)
        if {"Error", "Invalid"} & set(sk.State):
            raise OperationError("attachment_failed", "Native sketch attachment failed", status=sk.getStatusString())
        if sk.solve() != 0:
            raise OperationError("constraint_conflict", "The replacement support conflicts with sketch constraints")

    @staticmethod
    def _construction(req):
        value = req.get("construction", False)
        if not isinstance(value, bool):
            raise OperationError("invalid_argument", "construction must be boolean")
        return value

    def _position_constraints(self, sk, geometry, point, x, y, x_name, y_name):
        if x == 0 and y == 0:
            sk.addConstraint(Sketcher.Constraint("Coincident", geometry, point, -1, 1))
            return
        for kind, value, axis, name in [("DistanceX", x, -2, x_name), ("DistanceY", y, -1, y_name)]:
            if value == 0:
                sk.addConstraint(Sketcher.Constraint("PointOnObject", geometry, point, axis))
            else:
                self._dimension(sk, Sketcher.Constraint(kind, geometry, point, value), name)

    def _add_rectangle(self, sk, req):
        width, height = number(req["width"], "width", True), number(req["height"], "height", True)
        x, y = number(req.get("x", 0), "x"), number(req.get("y", 0), "y")
        construction = self._construction(req)
        start = sk.GeometryCount
        pts = [(x,y), (x+width,y), (x+width,y+height), (x,y+height)]
        for i, a in enumerate(pts):
            b = pts[(i+1)%4]
            sk.addGeometry(Part.LineSegment(App.Vector(*a,0), App.Vector(*b,0)), construction)
        for i in range(4):
            sk.addConstraint(Sketcher.Constraint("Coincident", start+i, 2, start+(i+1)%4, 1))
            sk.addConstraint(Sketcher.Constraint("Horizontal" if i%2==0 else "Vertical", start+i))
        self._position_constraints(sk, start, 1, x, y, "OriginX", "OriginY")
        self._dimension(sk, Sketcher.Constraint("Distance", start, width), "Width")
        self._dimension(sk, Sketcher.Constraint("Distance", start+1, height), "Height")

    def _add_circle(self, sk, req):
        x, y = number(req["x"], "x"), number(req["y"], "y")
        diameter = number(req["diameter"], "diameter", True)
        i = sk.addGeometry(Part.Circle(App.Vector(x,y,0), App.Vector(0,0,1), diameter/2), self._construction(req))
        self._position_constraints(sk, i, 3, x, y, "CenterX", "CenterY")
        self._dimension(sk, Sketcher.Constraint("Diameter", i, diameter), "Diameter")

    def _add_line(self, sk, req):
        x1, y1 = number(req["x1"], "x1"), number(req["y1"], "y1")
        x2, y2 = number(req["x2"], "x2"), number(req["y2"], "y2")
        if math.hypot(x2-x1, y2-y1) < 1e-7:
            raise OperationError("invalid_argument", "Line endpoints must be distinct")
        i = sk.addGeometry(Part.LineSegment(App.Vector(x1,y1,0), App.Vector(x2,y2,0)), self._construction(req))
        self._position_constraints(sk, i, 1, x1, y1, "StartX", "StartY")
        self._position_constraints(sk, i, 2, x2, y2, "EndX", "EndY")

    @staticmethod
    def _deletable_feature(obj, body):
        if obj == body or obj not in body.Group:
            return False
        if obj.TypeId in {"Sketcher::SketchObject", "PartDesign::Plane"}:
            return True
        # Native toolbar features share PartDesign::Feature. Keep script-owned
        # proxies and arbitrary App/Part geometry outside this deletion API.
        return (obj.TypeId.startswith("PartDesign::") and obj.isDerivedFrom("PartDesign::Feature")
                and not obj.TypeId.endswith("Python") and "Proxy" not in obj.PropertiesList)

    def delete_features_plan(self, doc, features, body=None):
        """Read-only deletion closure for the history confirmation UI."""
        if (not isinstance(features, list) or not features or len(features) > 1024
                or any(not isinstance(name, str) or not name for name in features)
                or len(set(features)) != len(features)):
            raise OperationError("invalid_argument", "Choose distinct native feature IDs (maximum 1024)")
        request = {"body": body} if body is not None else {}
        targets, owners = [], {}
        for name in features:
            target = doc.getObject(name)
            if target is None:
                raise OperationError("missing_reference", "Feature ID does not exist", feature=name)
            selected_body = self._body(doc, request, target)
            if not self._deletable_feature(target, selected_body):
                raise OperationError("unsupported_feature", "Delete supports sketches, native datum planes and built-in PartDesign features in their Body", feature=name)
            targets.append(target)
            owners[name] = selected_body
        pending = list(targets)
        selected = {target.Name for target in targets}
        removed = set(selected)
        while pending:
            obj = pending.pop()
            selected_body = owners[obj.Name]
            for dependent in obj.InList:
                if dependent == selected_body or dependent.Name == METADATA:
                    continue
                if dependent not in selected_body.Group:
                    raise OperationError("external_dependency", "A feature outside this Body depends on the deletion", feature=dependent.Name)
                if not self._deletable_feature(dependent, selected_body):
                    raise OperationError("unsupported_dependency", "A script-owned or unsupported feature depends on this deletion", feature=dependent.Name)
                if dependent.Name in removed:
                    continue
                removed.add(dependent.Name)
                owners[dependent.Name] = selected_body
                pending.append(dependent)
        ordered = [obj.Name for obj in studio.order(doc) if obj.Name in removed]
        ordered.extend(obj.Name for obj in doc.Objects if obj.Name in removed and obj.Name not in ordered)
        return {"selected": [name for name in ordered if name in selected],
                "dependents": [name for name in ordered if name not in selected], "removed": ordered}

    def _delete_features(self, doc, req):
        cascade = req.get("cascade", False)
        if not isinstance(cascade, bool):
            raise OperationError("invalid_argument", "cascade must be boolean")
        plan = self.delete_features_plan(doc, req.get("features"), req.get("body"))
        if plan["dependents"] and not cascade:
            raise OperationError("dependent_features", "Deletion requires explicit cascade because unselected native features depend on it", dependents=plan["dependents"])
        removed = set(plan["removed"])
        affected = {owner(doc, doc.getObject(name)).Name for name in removed}
        # Native dependencies establish removal order even if a user reordered
        # Body.Group. Consumers must go before their supporting features.
        ordered, visiting = [], set()
        def upstream(obj):
            if obj.Name in visiting:
                return
            visiting.add(obj.Name)
            for source in obj.OutList:
                if source.Name in removed:
                    upstream(source)
            ordered.append(obj.Name)
        for name in plan["removed"]:
            upstream(doc.getObject(name))
        for name in reversed(ordered):
            doc.removeObject(name)
        from .sketch_tools import prune_use_sources
        for name in ordered:
            prune_use_sources(doc, name)
        for body_name in affected:
            body = doc.getObject(body_name)
            solids = [obj for obj in body.Group if obj.TypeId.startswith("PartDesign::") and hasattr(obj,"Shape") and not obj.Shape.isNull() and obj.Shape.Solids]
            # Body.Tip accepts a native PartDesign result, never a Sketcher profile.
            body.Tip = solids[-1] if solids else None
        meta = self._meta(doc)
        mapping = json.loads(meta.SourceMapping)
        meta.SourceMapping = json.dumps({key:value for key,value in mapping.items() if value not in removed}, sort_keys=True)

    def _delete_feature(self, doc, req):
        self._delete_features(doc, dict(req, features=[req["feature"]]))

    def _model_operation(self, doc, req):
        op = req["op"]
        if op == "delete_features":
            self._delete_features(doc, req)
            return None
        if op in modeling_geometry.OPS:
            created = modeling_geometry.handle(self, doc, req)
            self._record_source(doc, req, doc.getObject(created) if created else None)
            return created
        if op in studio.OPS - {"pad", "pocket"} or op in {"pad", "pocket"} and ("operation" in req or "merge_scope" in req):
            if reference_tools.is_selector(req.get("face")):
                original_face = req["face"]
                req = dict(req, face=native_selectors.native_reference(doc, original_face, entity_type="face"),
                           _face_selector=reference_tools.selector_value(original_face))
            created = studio.handle(self, doc, req)
            self._record_source(doc, req, doc.getObject(created) if created else None)
            return created
        if op in reference_tools.OPS:
            created = reference_tools.handle(self, doc, req)
            self._record_source(doc, req, doc.getObject(created) if created else None)
            return created
        if op == "pad" and req.get("end_type") == "through_all":
            raise OperationError("invalid_argument", "Through all extrusion requires an explicit studio result operation or merge scope")
        if reference_tools.is_selector(req.get("support")):
            original = req["support"]
            before = doc.getObject(req.get("sketch", "")) if op == "set_sketch_support" else None
            req = dict(req, support=native_selectors.native_reference(doc, original, before=before, entity_type="face"),
                       _support_selector=reference_tools.selector_value(original))
        if op == "rename_feature":
            target = doc.getObject(req.get("feature", ""))
            assembly_state = native_assembly.inspect(doc)
            ids = ({entry["id"] for entry in assembly_state["instances"] + assembly_state["joints"]} | {assembly_state["id"]}) if assembly_state else set()
            if target and target.Name in ids:
                if not isinstance(req.get("name"), str) or not req["name"].strip() or len(req["name"]) > 120 or any(ord(c) < 32 for c in req["name"]):
                    raise OperationError("invalid_argument", "Name must contain 1 to 120 characters")
                target.Label = req["name"].strip()
                return None
        if op == "create_body":
            created = doc.addObject("PartDesign::Body", self._id(doc, req, "Body"))
            created.Label = str(req.get("name", created.Name))[:120]
            return created.Name
        if "support" in req and not isinstance(req["support"], dict):
            raise OperationError("invalid_argument", "support requires a native reference object")
        target = doc.getObject(req.get("feature") or req.get("profile") or req.get("sketch") or req.get("support", {}).get("feature") or "")
        needs_body = op not in {"rebuild", "set_parameter", "set_expression"} or "body" in req
        body = self._body(doc, req, target) if needs_body else None
        if op == "set_sketch_support":
            self._set_sketch_support(doc, req, body)
            return None
        if op == "create_sketch":
            sk = self._new_sketch(doc, req, "Sketch")
        elif op == "sketch_rectangle":
            sk = self._new_sketch(doc, req, "Rectangle")
            self._add_rectangle(sk, req)
            if sk.solve() != 0:
                raise OperationError("constraint_conflict", "Rectangle solver failed")
        elif op == "sketch_circle":
            sk = self._new_sketch(doc, req, "Circle")
            self._add_circle(sk, req)
            if req.get("center_on"):
                rectangle = self._profile(doc,req["center_on"])
                if not {"Width", "Height"}.issubset(native_parameters(rectangle)) or req["x"]==0 or req["y"]==0:
                    raise OperationError("unsupported_reference", "Centered circle needs a nonzero center and a named rectangle")
                # v1 centered expressions are defined for an origin-anchored rectangle.
                if any(p.startswith("Origin") for p in native_parameters(rectangle)):
                    raise OperationError("unsupported_reference", "Centered expression requires an origin-anchored rectangle")
                if not sk.Placement.isSame(rectangle.Placement, 1e-7):
                    raise OperationError("unsupported_reference", "Centered expression requires sketches in the same native coordinate plane")
                sk.setExpression("Constraints.CenterX", f"{rectangle.Name}.Constraints.Width / 2")
                sk.setExpression("Constraints.CenterY", f"{rectangle.Name}.Constraints.Height / 2")
            if sk.solve()!=0:
                raise OperationError("constraint_conflict", "Circle solver failed")
        elif op in {"add_rectangle", "add_circle", "add_line"}:
            sk = self._profile(doc, req["sketch"])
            getattr(self, "_" + op)(sk, req)
            if sk.solve() != 0:
                raise OperationError("constraint_conflict", "New geometry produces a sketch solver conflict")
        elif op in {"pad", "pocket"}:
            profile=self._profile(doc,req["profile"])
            if profile.Shape.isNull() or not profile.Shape.Wires:
                raise OperationError("open_profile", "Sketch must contain a closed profile")
            prior_volume=self._volume(body) if op == "pocket" and not body.Shape.isNull() else 0
            if op=="pocket" and prior_volume<=0:
                raise OperationError("missing_body", "Pocket requires an existing solid")
            feature=body.newObject("PartDesign::Pad" if op=="pad" else "PartDesign::Pocket",self._id(doc,req,"Pad" if op=="pad" else "Pocket"))
            feature.Profile=profile
            if "reversed" in req and not isinstance(req["reversed"], bool):
                raise OperationError("invalid_argument", "reversed must be boolean")
            up_to_face = req.get("end_type") == "up_to_face" or "up_to_face" in req
            if req.get("end_type", "blind") not in {"blind", "through_all", "up_to_face"}:
                raise OperationError("invalid_argument", "end_type must be blind, through_all or up_to_face")
            if up_to_face:
                reference = native_selectors.native_reference(doc, req.get("up_to_face"), entity_type="face")
                target_face = doc.getObject(reference["feature"])
                if target_face == feature or feature in target_face.OutListRecursive:
                    raise OperationError("cyclic_reference", "End face must precede this feature")
                feature.Type = "UpToFace"
                feature.UpToFace = (target_face, [reference["subelement"]])
                if reference_tools.is_selector(req["up_to_face"]):
                    native_selectors.bind(feature, "up_to_face", reference_tools.selector_value(req["up_to_face"]), native_property="UpToFace")
            elif op=="pad":
                feature.Length=number(req["length"],"length",True)
                feature.Reversed = req.get("reversed", False)
            else:
                if "through_all" in req and not isinstance(req["through_all"], bool):
                    raise OperationError("invalid_argument", "through_all must be boolean")
                feature.Reversed=req.get("reversed", False)
                feature.Type=1 if req.get("end_type") == "through_all" or req.get("through_all",True) else 0
                if str(feature.Type)=="Length":
                    feature.Length=number(req["length"],"length",True)
            self._recompute(doc)
            if op=="pocket":
                def cut_valid():
                    return (not body.Shape.isNull() and len(body.Shape.Solids)==1
                            and self._volume(body) < prior_volume - 1e-7
                            and not set(feature.State) & {"Error", "Invalid"})
                # Native Pocket goes against the sketch normal by default.
                # At a bottom/origin plane that direction may contain no
                # material. Try the opposite only when direction was omitted.
                if not cut_valid() and "reversed" not in req:
                    feature.Reversed = True
                    self._recompute(doc)
                if not cut_valid():
                    raise OperationError("empty_cut", "Pocket removes no valid material in the requested direction")
        elif op in {"set_parameter", "set_expression"}:
            feature=doc.getObject(req["feature"])
            if not feature:
                raise OperationError("missing_reference", "Feature ID does not exist")
            parameter=req["parameter"]
            if parameter not in native_parameters(feature):
                raise OperationError("unsupported_parameter", "Choose an editable parameter reported by inspect")
            info=native_parameters(feature)[parameter]
            if info.get("native_feature"):
                feature = doc.getObject(info["native_feature"])
            if feature.TypeId=="Sketcher::SketchObject" and not feature.Constraints[info["constraint_index"]].Driving:
                raise OperationError("unsupported_parameter", "This parameter is not a supported driving length dimension")
            value = number(req["value"], "value", parameter != "Offset" and info.get("constraint_type") not in {"DistanceX", "DistanceY", "Angle"}, info["unit"]) if op == "set_parameter" else None
            property_path=(f"Constraints.{info['name']}" if info.get("name") else f"Constraints[{info['constraint_index']}]") if feature.TypeId=="Sketcher::SketchObject" else info.get("native_property", parameter)
            aliases={property_path}
            if feature.TypeId=="Sketcher::SketchObject":
                aliases.add(f"Constraints[{native_parameters(feature)[parameter]['constraint_index']}]")
            if op == "set_expression":
                expression = req.get("expression")
                if expression is not None and (not isinstance(expression, str) or len(expression) > 512 or not re.fullmatch(r"[A-Za-z0-9_ .+*/()\[\]-]+", expression)):
                    raise OperationError("invalid_argument", "Use a dimensional formula with named properties and arithmetic")
                feature.setExpression(property_path, expression)
                self._recompute(doc)
                if set(feature.State) & {"Invalid", "Error"}:
                    raise OperationError("invalid_expression", "Formula is invalid, has a missing reference, or has incompatible units", status=feature.getStatusString())
                return
            if any(path.lstrip(".") in aliases for path,_ in feature.ExpressionEngine):
                raise OperationError("expression_driven", "Edit the upstream driving parameter instead")
            if feature.TypeId=="Sketcher::SketchObject":
                feature.setDatum(native_parameters(feature)[parameter]["constraint_index"],App.Units.Quantity(f"{value} {info['unit']}"))
                if feature.solve()!=0:
                    raise OperationError("constraint_conflict", "Dimension produces a sketch solver conflict")
            else:
                setattr(feature, property_path, math.degrees(value) if info["unit"] == "rad" else value)
        elif op == "duplicate_feature":
            source = doc.getObject(req["feature"])
            if source is None or source not in body.Group or source.TypeId not in {"Sketcher::SketchObject", "PartDesign::Pad", "PartDesign::Pocket"}:
                raise OperationError("unsupported_feature", "Duplicate supports a native sketch, Pad or Pocket in this Body")
            if req.get("fingerprint"):
                try:
                    fingerprints = native_content_fingerprints(bytes(source.dumpContent()))
                except ValueError as exc:
                    raise OperationError("changed_source", "Copied feature changed; copy it again") from exc
                if req["fingerprint"] not in fingerprints:
                    raise OperationError("changed_source", "Copied feature changed; copy it again")
            previous_tip = body.Tip
            created = doc.copyObject(source, False)
            body.addObject(created)
            created.Label = source.Label + " copy"
            if created.TypeId == "Sketcher::SketchObject":
                body.Tip = previous_tip
            return created.Name
        elif op == "pierce":
            sketch = self._profile(doc, req["sketch"])
            query = req.get("target") if reference_tools.is_selector(req.get("target")) else None
            if query:
                reference = native_selectors.native_reference(doc, query, before=sketch, entity_type="edge")
                req = dict(req, target=reference["feature"], subelement=reference["subelement"])
            source = doc.getObject(req["target"])
            geometry, point = req["geometry"], req.get("point", 1)
            if isinstance(geometry, bool) or not isinstance(geometry, int) or not 0 <= geometry < sketch.GeometryCount or isinstance(point, bool) or point not in {1, 2, 3}:
                raise OperationError("invalid_argument", "Choose one native sketch endpoint or center")
            if source is None or source == sketch or source not in body.Group or not re.fullmatch(r"Edge[1-9][0-9]*", str(req["subelement"])):
                raise OperationError("invalid_argument", "Select an independent native curve edge in this Body")
            if sketch in source.OutListRecursive:
                raise OperationError("cyclic_reference", "Pierce cannot reference a downstream feature")
            previous = len(sketch.ExternalGeo)
            from .sketch_tools import external_links
            external_slot = len(external_links(sketch))
            sketch.addExternal(source.Name, req["subelement"], False, True)
            self._recompute(doc)
            external = sketch.ExternalGeo[previous:]
            if len(external) != 1 or not isinstance(external[0], Part.Point):
                raise OperationError("ambiguous_intersection", "Curve must cross the sketch plane at exactly one point")
            sketch.addConstraint(Sketcher.Constraint("Coincident", geometry, point, -(previous + 1), 1))
            if query:
                native_selectors.bind(sketch, "pierce_" + str(previous), reference_tools.selector_value(query),
                                      mode="external", index=external_slot, intersection=True)
            if sketch.solve() != 0:
                raise OperationError("constraint_conflict", "Pierce conflicts with existing sketch constraints")
        elif op == "rename_feature":
            feature = doc.getObject(req["feature"])
            if feature is None:
                raise OperationError("missing_reference", "Feature ID does not exist")
            if feature != body and feature not in body.Group:
                raise OperationError("unsupported_feature", "Rename requires a feature in the active Body")
            label = req["name"]
            if not isinstance(label, str) or not label.strip() or len(label) > 120 or any(ord(c) < 32 for c in label):
                raise OperationError("invalid_argument", "Feature name must contain 1–120 printable characters")
            feature.Label = label.strip()
        elif op == "delete_feature":
            self._delete_feature(doc, req)
        elif op=="rebuild":
            for obj in doc.Objects:
                if obj.TypeId.startswith(("Sketcher::","PartDesign::")):
                    obj.touch()
        if op in {"create_sketch", "sketch_rectangle", "sketch_circle", "pad", "pocket"} and req.get("source_feature_id"):
            created = sk if op in {"create_sketch", "sketch_rectangle", "sketch_circle"} else feature
            self._record_source(doc, req, created)

    def _record_source(self, doc, req, created):
        if created is None or not req.get("source_feature_id"):
            return
        created.Label = str(req.get("source_feature_name", req["source_feature_id"]))
        for prop, value in [("SourceFeatureId", req["source_feature_id"]),
                            ("SourceFeatureName", req.get("source_feature_name", req["source_feature_id"]))]:
            if prop not in created.PropertiesList:
                created.addProperty("App::PropertyString", prop, "Onshape source")
            setattr(created, prop, str(value))
            created.setEditorMode(prop, 1)
        meta = self._meta(doc)
        mapping = json.loads(meta.SourceMapping)
        mapping[str(req["source_feature_id"])] = created.Name
        meta.SourceMapping = json.dumps(mapping, sort_keys=True)

    def _save(self, doc, raw):
        path=write_path(raw,{".fcstd"}, self.settings.roots)
        stage=path.with_name(path.stem + ".saving.FCStd")
        old_name=doc.FileName
        try:
            doc.saveCopy(str(stage))
            # Ensure stage is a readable native ZIP before replacing the previous file.
            import zipfile
            with zipfile.ZipFile(stage) as archive:
                if "Document.xml" not in archive.namelist() or archive.testzip():
                    raise OperationError("save_failed", "Native staged file is corrupt")
            if path.exists():
                import shutil
                shutil.copy2(path,path.with_suffix(".recovery.FCStd"))
            os.replace(stage,path)
            doc.FileName=str(path)
        except Exception:
            doc.FileName=old_name
            raise

    def _export(self, doc, raw, body_id=None):
        path=write_path(raw,{".step",".stp",".stl"}, self.settings.roots)
        if self._meta(doc).BuildStatus!="valid":
            raise OperationError("build_failed", "Only a current valid solid can be exported")
        stage=path.with_name(path.stem + ".exporting" + path.suffix)
        assembly_state = native_assembly.inspect(doc)
        if assembly_state and body_id is not None:
            raise OperationError("invalid_argument", "Assembly export includes every occurrence; omit body")
        included = [self._body(doc, {"body": body_id})] if body_id is not None else native_results(doc)
        included = [obj for obj in included if not obj.Shape.isNull() and obj.Shape.Solids]
        verdicts = {obj.Name: self.geometry.check(obj, compute=True) for obj in included}
        if any(not check["valid"] for check in verdicts.values()):
            self._build_status(doc)
            raise OperationError("invalid_geometry", "Geometry check failed; nothing was exported",
                                 features=[{"feature": name, "issues": check["issues"]}
                                           for name, check in verdicts.items() if not check["valid"]])
        # Native writers may change shared TShape serialization flags. Export
        # detached world shapes so source geometry and cached verdicts stay exact.
        shape = Part.makeCompound([native_assembly.global_shape(obj).copy() for obj in included])
        if path.suffix.lower()==".stl":
            import MeshPart
            mesh=MeshPart.meshFromShape(Shape=shape,LinearDeflection=0.05,AngularDeflection=0.1,Relative=False)
            mesh.write(str(stage))
        else:
            # Write each current transformed result exactly once. Internal source
            # storage and the Assembly aggregate must never join this list.
            shape.exportStep(str(stage))
        provenance={"document_id":self._meta(doc).DocumentId,"revision":self._meta(doc).Revision,"units":"mm",
                    "source_mapping":json.loads(self._meta(doc).SourceMapping),
                    "import_source":json.loads(getattr(self._meta(doc), "ImportSource", "{}")) or None,
                    "assembly": assembly_state,
                    "engine":{"FreeCAD":App.Version(),"OCCT":Part.OCC_VERSION},
                    "sha256":hashlib.sha256(stage.read_bytes()).hexdigest(),
                    "native_file":doc.FileName or None,"format":path.suffix.lower(),"included_body_ids":[obj.Name for obj in included],"shape":self._geometry(doc, included, "full"),
                    "geometry_check": {"status": "valid", "bodies": [{"id": name, "check_ms": check["ms"]} for name, check in verdicts.items()]},
                    "included_part_ids":[getattr(obj,"KurtShapePartId",obj.Name) for obj in included],
                    "settings":{"linear_deflection_mm":0.05,"angular_deflection_rad":0.1} if path.suffix.lower()==".stl" else {"writer":"FreeCAD Part/OCCT"}}
        sidecar=path.with_suffix(path.suffix+".json")
        temp=sidecar.with_suffix(sidecar.suffix+".saving")
        temp.write_text(json.dumps(provenance,indent=2),encoding="utf-8")
        self._replace_export_pair([(stage,path),(temp,sidecar)])

    def _replace_export_pair(self, pairs, guard=None, rollback_guard=None):
        """Stage both outputs first; rollback successful replaces if its partner fails.

        A filesystem cannot atomically rename two files. SHA256 in the manifest
        detects interrupted pairs; recovery copies also preserve the prior export.
        """
        import shutil
        import stat
        previous={}
        for stage,target in pairs:
            if target.exists():
                if not target.is_file() or not (target.stat().st_mode & stat.S_IWRITE):
                    raise OperationError("export_destination_readonly", f"Export destination is not writable: {target.name}")
                backup=target.with_name(target.name+".recovery")
                shutil.copy2(target,backup)
                previous[target]=backup
            else:
                previous[target]=None
        committed=[]
        try:
            for stage,target in pairs:
                if guard is not None and not guard():
                    raise OSError("STEP export ownership changed before replacement")
                os.replace(stage,target)
                committed.append(target)
                if guard is not None and not guard():
                    raise OSError("STEP export ownership changed during replacement")
        except OSError as exc:
            failures=[]
            for target in reversed(committed):
                try:
                    if rollback_guard is not None and not rollback_guard(target):
                        raise OSError("Export destination changed after this job replaced it; recovery preserved")
                    backup=previous[target]
                    if backup:
                        os.replace(backup,target)
                    else:
                        target.unlink()
                except OSError as recovery_error:
                    failures.append({"path":str(target),"recovery":str(previous[target]),"error":str(recovery_error)})
            if failures:
                raise OperationError("export_recovery_required", "Export pair replacement and recovery failed; check preserved recovery files", failures=failures) from exc
            raise OperationError("export_failed", "Export replacement failed; previous geometry/provenance restored") from exc
