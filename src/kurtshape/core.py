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

import FreeCAD as App
import Part
import Sketcher

ROOT = Path(__file__).resolve().parents[2]
WRITE_ROOT = ROOT.parent.resolve()
METADATA = "KurtShapeProject"
SKETCH_CANCEL_BOUNDARY = "KurtShape: cancelled sketch edit"


class OperationError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details


def number(value, name, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise OperationError("invalid_argument", f"{name} must be a finite number in mm")
    if positive and value <= 0:
        raise OperationError("invalid_argument", f"{name} must be positive")
    if abs(value) > 1e6:
        raise OperationError("invalid_argument", f"{name} exceeds the 1 km slice limit")
    return float(value)


def write_path(raw, suffixes):
    path = Path(raw).resolve()
    if not path.is_relative_to(WRITE_ROOT):
        raise OperationError("path_outside_workspace", "Generated files must stay within CADkz/Codex")
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


def native_intent(doc):
    """Read native modeling intent, including native edits made outside our panel."""
    state = []
    for obj in doc.Objects:
        if obj.Name == METADATA or obj.TypeId.startswith(("App::Origin", "App::Line", "App::Plane")):
            continue
        item = {"id": obj.Name, "type": obj.TypeId, "label": obj.Label, "properties": {}}
        for key in obj.PropertiesList:
            if key in {"Shape", "InternalShape", "ExpressionEngine", "Geometry", "Constraints", "Proxy", "PlacementList", "Visibility"}:
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
    return hashlib.sha256(json.dumps(native_intent(doc), sort_keys=True).encode()).hexdigest()


def measurements(shape):
    box = shape.BoundBox
    volume = sum(s.Volume for s in shape.Solids)
    center = [sum(s.Volume * getattr(s.CenterOfMass,axis) for s in shape.Solids) / volume for axis in ("x","y","z")] if volume else None
    return {"valid": bool(shape.isValid()), "solid_count": len(shape.Solids),
            "volume_mm3": shape.Volume, "area_mm2": shape.Area,
            "bbox_mm": {"min": [box.XMin, box.YMin, box.ZMin], "max": [box.XMax, box.YMax, box.ZMax],
                        "size": [box.XLength, box.YLength, box.ZLength]},
            "center_of_mass_mm": center}


class Controller:
    READ_OPS = {"inspect", "list_documents"}
    MODEL_OPS = {"create_sketch", "sketch_rectangle", "sketch_circle", "add_rectangle", "add_circle", "add_line",
                 "pad", "pocket", "set_parameter", "rename_feature", "delete_feature", "rebuild"}
    EDIT_OPS = {"add_rectangle", "add_circle", "add_line", "set_parameter", "finish_sketch_edit", "undo", "redo"}
    OPS = READ_OPS | MODEL_OPS | {"new", "open", "begin_sketch_edit", "finish_sketch_edit", "undo", "redo", "save", "export"}
    ARGS = {
        "new": {"name"}, "open": {"path"}, "inspect": set(), "list_documents": set(),
        "create_sketch": {"id", "plane", "support", "source_feature_id", "source_feature_name"},
        "sketch_rectangle": {"id","width","height","x","y","plane","support","source_feature_id","source_feature_name"},
        "sketch_circle": {"id","x","y","diameter","plane","support","center_on","source_feature_id","source_feature_name"},
        "add_rectangle": {"sketch", "width", "height", "x", "y", "construction"},
        "add_circle": {"sketch", "x", "y", "diameter", "construction"},
        "add_line": {"sketch", "x1", "y1", "x2", "y2", "construction"},
        "begin_sketch_edit": {"feature"}, "finish_sketch_edit": {"cancel"},
        "pad": {"id","profile","length","reversed","source_feature_id","source_feature_name"},
        "pocket": {"id","profile","length","through_all","reversed","source_feature_id","source_feature_name"},
        "rename_feature": {"feature", "name"}, "delete_feature": {"feature", "cascade"},
        "set_parameter": {"feature","parameter","value"}, "rebuild": set(), "undo": set(), "redo": set(),
        "save": {"path"}, "export": {"path"},
    }

    def __init__(self):
        self.documents = {}
        self.signatures = {}
        self.last_failures = {}
        self.sketch_edits = {}
        self.busy = False

    def attach(self, doc):
        meta = metadata(doc)
        existing=self.documents.get(meta.DocumentId)
        if existing is not None and self._is_open(existing) and existing.Name!=doc.Name:
            raise OperationError("duplicate_document_id", "Close the existing project before opening another copy with the same document ID", existing_document=existing.Name)
        if existing is None or not self._is_open(existing):
            # Edit leases belong to a live native document instance, not to
            # its persisted UUID. A closed document's snapshots/history must
            # never be applied to a reopened copy with the same project ID.
            self.sketch_edits.pop(meta.DocumentId, None)
        # A copied/opened file receives a fresh session revision, preventing old-client ABA.
        meta.Revision = str(uuid.uuid4())
        self.documents[meta.DocumentId] = doc
        if meta.LastFailure:
            try:
                self.last_failures[meta.DocumentId]=json.loads(meta.LastFailure)
            except ValueError:
                pass
        self.signatures[meta.DocumentId] = intent_signature(doc)
        doc.UndoMode = 1
        self._build_status(doc)
        return doc

    def _doc(self, request):
        identifier = request.get("document_id")
        doc = self.documents.get(identifier)
        if doc is None or not self._is_open(doc):
            raise OperationError("unknown_document", "Document is not open in this session")
        self.sync(doc)
        return doc

    @staticmethod
    def _is_open(doc):
        try:
            return doc.Name in App.listDocuments()
        except (NameError,ReferenceError):
            return False

    def _prune_closed_sketch_edits(self):
        for identifier in list(self.sketch_edits):
            doc = self.documents.get(identifier)
            if doc is None or not self._is_open(doc):
                self.sketch_edits.pop(identifier, None)

    def sync(self, doc):
        meta = metadata(doc)
        signature = intent_signature(doc)
        if self.signatures.get(meta.DocumentId) != signature:
            meta.Revision = str(uuid.uuid4())
            self.signatures[meta.DocumentId] = signature
            self._record_sketch_edit(doc)
        self._build_status(doc)

    def _sketch_edit_signature(self, doc, name):
        item = next(item for item in native_intent(doc) if item["id"] == name)
        return hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()

    def _record_sketch_edit(self, doc):
        editing = self.sketch_edits.get(metadata(doc).DocumentId)
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
        identifier = metadata(doc).DocumentId
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
        sketch.restoreContent(editing["initial"])
        doc.recompute()
        self.sketch_edits.pop(identifier, None)
        if undone:
            doc.openTransaction(SKETCH_CANCEL_BOUNDARY)
            self._new_revision(doc)
            doc.commitTransaction()
        else:
            self._new_revision(doc)

    def _commit_sketch_edit(self, doc):
        """Group native command commits within the exclusive sketch lease."""
        editing = self.sketch_edits[metadata(doc).DocumentId]
        if doc.HasPendingTransaction:
            doc.commitTransaction()
        if doc.UndoCount < editing["undo_before"]:
            raise OperationError("sketch_history_changed", "Native document history changed outside the managed sketch lease")
        if doc.UndoCount > editing["undo_before"] + 1:
            sketch = doc.getObject(editing["feature"])
            final = bytes(sketch.dumpContent())
            label = sketch.Label
            while doc.UndoCount > editing["undo_before"]:
                doc.undo()
            sketch = doc.getObject(editing["feature"])
            if sketch is None:
                raise OperationError("sketch_history_changed", "The accepted sketch no longer exists in native history")
            doc.openTransaction(f"KurtShape: edit {label}")
            sketch.restoreContent(final)
            doc.recompute()
            errors = self._build_status(doc)
            if errors:
                raise OperationError("build_failed", "Grouped sketch edit could not rebuild native features", features=errors)
            doc.commitTransaction()

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

    def _build_status(self, doc):
        errors = []
        pending = []
        for obj in doc.Objects:
            if obj.Name == METADATA:
                continue
            flags = set(obj.State)
            if "Touched" in flags and obj.TypeId.startswith(("Sketcher::","PartDesign::")):
                pending.append(obj.Name)
            if "Invalid" in flags or "Error" in flags:
                errors.append({"feature": obj.Name, "message": obj.getStatusString()})
        body = doc.getObject("Body")
        solid = body and not body.Shape.isNull() and bool(body.Shape.Solids)
        if solid and not body.Shape.isValid():
            errors.append({"feature": "Body", "message": "Invalid solid"})
        status = "failed" if errors else ("needs_rebuild" if pending else ("valid" if solid else "sketch_only"))
        meta = metadata(doc)
        if meta.BuildStatus != status:
            meta.BuildStatus = status
        return errors

    def inspect(self, doc):
        self.sync(doc)
        meta = metadata(doc)
        features = []
        for obj in doc.Objects:
            if obj.Name == METADATA or obj.TypeId.startswith(("App::Origin", "App::Line", "App::Plane")):
                continue
            f = {"id": obj.Name, "name": obj.Label, "type": obj.TypeId,
                 "parameters": native_parameters(obj), "dependencies": [x.Name for x in obj.OutList],
                 "expressions": list(getattr(obj, "ExpressionEngine", [])), "state": list(obj.State)}
            if obj.TypeId == "Sketcher::SketchObject":
                f.update(fully_constrained=bool(obj.FullyConstrained), geometry_count=obj.GeometryCount,
                         constraint_count=obj.ConstraintCount,
                         placement={"position_mm": _native_value(obj.Placement.Base), "rotation_xyzw": list(obj.Placement.Rotation.Q)},
                         support=[{"feature": linked.Name, "subelements": list(elements)} for linked, elements in obj.AttachmentSupport],
                         map_mode=str(obj.MapMode))
            if obj.TypeId in {"PartDesign::Pad", "PartDesign::Pocket"}:
                f["reversed"] = bool(obj.Reversed)
            if "SourceFeatureId" in obj.PropertiesList:
                f["source_feature_id"] = obj.SourceFeatureId
                f["source_feature_name"] = obj.SourceFeatureName
            features.append(f)
        body = doc.getObject("Body")
        available_geometry = measurements(body.Shape) if body and not body.Shape.isNull() and body.Shape.Solids else None
        geometry = available_geometry if meta.BuildStatus=="valid" else None
        return {"document_id": meta.DocumentId, "revision": meta.Revision, "name": doc.Label,
                "native_file": doc.FileName or None, "units": "mm", "build_status": meta.BuildStatus,
                "build_errors": self._build_status(doc), "features": features,
                "measurements": geometry, "retained_geometry_measurements": available_geometry if meta.BuildStatus in {"failed","needs_rebuild"} else None,
                "last_failed_attempt": self.last_failures.get(meta.DocumentId),
                "active_sketch_edit": self.sketch_edits.get(meta.DocumentId, {}).get("feature"),
                "operations": sorted(self.OPS)}

    def dispatch(self, request):
        start = time.perf_counter()
        doc = None
        transaction = False
        try:
            self._prune_closed_sketch_edits()
            if not isinstance(request, dict) or request.get("op") not in self.OPS:
                raise OperationError("unsupported_operation", "Unknown operation")
            op = request["op"]
            unknown = set(request) - self.ARGS[op] - {"op", "document_id", "expected_revision"}
            if unknown:
                raise OperationError("unknown_argument", "Unsupported request fields", fields=sorted(unknown))
            if op == "list_documents":
                return {"ok": True, "result": {"documents": [self.inspect(d) for d in self.documents.values() if self._is_open(d)]}}
            if op in {"new", "open"} and any(identifier in self.sketch_edits and self._is_open(existing)
                                                         for identifier, existing in self.documents.items()):
                raise OperationError("sketch_edit_active", "Finish or cancel the active sketch before changing documents")
            if op in {"new", "open"} and getattr(App, "GuiUp", False):
                import FreeCADGui as Gui
                if Gui.Control.activeDialog() or any(Gui.getDocument(name) and Gui.getDocument(name).getInEdit() for name in App.listDocuments()):
                    raise OperationError("sketch_edit_active", "Finish or cancel graphical editing before changing documents")
            if op == "new":
                doc = self.attach(App.newDocument("KurtShape"))
                doc.Label = str(request.get("name", "New part"))[:120]
                doc.addObject("PartDesign::Body", "Body")
                doc.recompute()
                self.signatures[metadata(doc).DocumentId] = intent_signature(doc)
            elif op == "open":
                path = Path(request["path"]).resolve()
                if path.suffix.lower() != ".fcstd" or not path.is_file():
                    raise OperationError("invalid_format", "Open requires an existing native .FCStd file")
                doc = App.openDocument(str(path))
                if not doc.getObject(METADATA):
                    App.closeDocument(doc.Name)
                    doc = None
                    raise OperationError("unmanaged_document", "Native file has no KurtShape metadata; use native FreeCAD to inspect it")
                try:
                    self.attach(doc)
                except OperationError:
                    App.closeDocument(doc.Name)
                    doc=None
                    raise
                for obj in doc.Objects:
                    if obj.TypeId.startswith(("Sketcher::", "PartDesign::")):
                        obj.touch()
                doc.recompute()
            else:
                doc = self._doc(request)
                if op != "inspect":
                    expected = request.get("expected_revision")
                    if expected != metadata(doc).Revision:
                        raise OperationError("stale_revision", "Inspect the current document before mutating", expected=expected, actual=metadata(doc).Revision)
                    if self.busy:
                        raise OperationError("busy", "A modeling operation is already active")
                    editing = self.sketch_edits.get(metadata(doc).DocumentId)
                    if editing:
                        if op not in self.EDIT_OPS:
                            raise OperationError("sketch_edit_active", "Finish or cancel the managed sketch before another operation", feature=editing["feature"])
                        target = request.get("sketch") if op.startswith("add_") else request.get("feature")
                        if target is not None and target != editing["feature"]:
                            raise OperationError("managed_sketch_mismatch", "Only the sketch in the active edit session may be changed", feature=editing["feature"])
                    if getattr(App, "GuiUp", False):
                        import FreeCADGui as Gui
                        native_edit = Gui.activeDocument().getInEdit() if Gui.activeDocument() else None
                        native_object = getattr(native_edit, "Object", native_edit)
                        managed_native_edit = bool(editing and native_object and native_object.Document == doc
                                                   and native_object.Name == editing["feature"])
                        if (Gui.Control.activeDialog() or native_edit) and not managed_native_edit:
                            raise OperationError("sketch_edit_active", "Finish or cancel graphical editing before another operation")
                    self.busy = True
                if op == "begin_sketch_edit":
                    sketch = self._profile(doc, request["feature"])
                    if doc.HasPendingTransaction:
                        raise OperationError("unmanaged_transaction", "Finish the existing native transaction before starting sketch editing")
                    undo_before = doc.UndoCount
                    initial = bytes(sketch.dumpContent())
                    doc.openTransaction(f"KurtShape: edit {sketch.Label}")
                    self.sketch_edits[metadata(doc).DocumentId] = {
                        "feature": sketch.Name, "signature": self._sketch_edit_signature(doc, sketch.Name),
                        "initial": initial, "undo_before": undo_before,
                        "undo": [initial], "redo": []}
                    self._new_revision(doc)
                elif op == "finish_sketch_edit":
                    editing = self.sketch_edits.get(metadata(doc).DocumentId)
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
                        self._profile(doc, editing["feature"])
                        doc.recompute()
                        errors = self._build_status(doc)
                        if errors:
                            raise OperationError("build_failed", "Finishing sketch editing could not rebuild native features", features=errors)
                        self._commit_sketch_edit(doc)
                    self.sketch_edits.pop(metadata(doc).DocumentId, None)
                    transaction = False
                    doc.recompute()
                    self._new_revision(doc)
                elif op in self.MODEL_OPS:
                    editing = self.sketch_edits.get(metadata(doc).DocumentId)
                    if not editing:
                        doc.openTransaction(f"KurtShape: {op}")
                    transaction = True
                    self._model_operation(doc, request)
                    doc.recompute()
                    errors = self._build_status(doc)
                    if errors and not editing:
                        raise OperationError("build_failed", "Native feature rebuild failed", features=errors)
                    if not editing and (op in {"pad", "pocket"} or (op == "set_parameter" and doc.Body.Tip and doc.Body.Tip.TypeId != "Sketcher::SketchObject")):
                        if metadata(doc).BuildStatus != "valid" or len(doc.Body.Shape.Solids) != 1:
                            raise OperationError("build_failed", "Operation must produce one valid solid")
                    if not editing:
                        doc.commitTransaction()
                    transaction = False
                    self._new_revision(doc)
                elif op in {"undo", "redo"}:
                    editing = self.sketch_edits.get(metadata(doc).DocumentId)
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
                        sketch.restoreContent(snapshot)
                        doc.recompute()
                        editing["signature"] = self._sketch_edit_signature(doc, sketch.Name)
                    else:
                        self._native_history(doc, op)
                    doc.recompute()
                    self._new_revision(doc)
                elif op == "save":
                    self._save(doc, request["path"])
                elif op == "export":
                    self._export(doc, request["path"])
            result = self.inspect(doc)
            if op in {"save", "open"} and getattr(App, "GuiUp", False):
                import FreeCADGui as Gui
                # saveCopy intentionally preserves the GUI dirty flag; open
                # touches session metadata/rebuild caches. Only clear the UI
                # flag after the successful disk operation and final inspect.
                # This neither rewrites the accepted file nor changes undo.
                Gui.getDocument(doc.Name).Modified = False
            result["operation_ms"] = round((time.perf_counter() - start) * 1000, 2)
            return {"ok": True, "result": result}
        except Exception as exc:
            if transaction and doc:
                ended_edit = metadata(doc).DocumentId in self.sketch_edits
                if ended_edit:
                    try:
                        self._rollback_sketch_edit(doc)
                    except Exception as rollback_error:
                        # An external native history change must be reported,
                        # never escaped from dispatch or repaired by undoing
                        # unrelated accepted transactions.
                        exc = rollback_error
                        self._new_revision(doc)
                else:
                    doc.abortTransaction()
                    doc.recompute()
                    self.signatures[metadata(doc).DocumentId] = intent_signature(doc)
                    self._build_status(doc)
            code = exc.code if isinstance(exc, OperationError) else "operation_failed"
            error = {"code": code, "message": str(exc), **(exc.details if isinstance(exc, OperationError) else {})}
            if doc and code not in {"stale_revision", "busy", "sketch_edit_active", "managed_sketch_mismatch", "sketch_editor_open"}:
                self.last_failures[metadata(doc).DocumentId] = {"request": request, "error": error, "rejected": True}
                metadata(doc).LastFailure=json.dumps(self.last_failures[metadata(doc).DocumentId])
            return {"ok": False, "error": error}
        finally:
            self.busy = False

    def _new_revision(self, doc):
        meta = metadata(doc)
        meta.Revision = str(uuid.uuid4())
        self.signatures[meta.DocumentId] = intent_signature(doc)
        self._record_sketch_edit(doc)
        self._build_status(doc)

    def _id(self, doc, request, fallback):
        name = request.get("id", fallback)
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name):
            raise OperationError("invalid_argument", "Feature ID must be an ASCII letter followed by letters/digits/underscores")
        if doc.getObject(name):
            raise OperationError("duplicate_feature", f"Feature {name} already exists")
        return name

    def _profile(self, doc, name):
        obj = doc.getObject(name)
        if not obj or obj.TypeId != "Sketcher::SketchObject" or obj not in doc.Body.Group:
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

    def _sketch_support(self, doc, req):
        if "plane" in req and "support" in req:
            raise OperationError("invalid_argument", "Choose one origin plane or one native planar support")
        if "support" not in req:
            plane = req.get("plane", "XY")
            if plane not in {"XY", "XZ", "YZ"}:
                raise OperationError("unsupported_plane", "Origin plane must be XY, XZ or YZ")
            return doc.getObject(plane + "_Plane"), ""
        reference = req["support"]
        if not isinstance(reference, dict) or not isinstance(reference.get("feature"), str) or set(reference) - {"feature", "subelement"}:
            raise OperationError("invalid_argument", "support requires a native feature ID and optional FaceN subelement")
        obj = doc.getObject(reference["feature"])
        if obj is None:
            raise OperationError("missing_reference", "Sketch support does not exist in this document")
        # A displayed Body face is owned by its current solid Tip. Link the
        # sketch to that feature, avoiding a self-reference through its Body.
        if obj == doc.Body:
            obj = doc.Body.Tip
        origins = list(doc.Body.Origin.OriginFeatures)
        if obj is None or (obj not in doc.Body.Group and obj not in origins):
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
        support, element = self._sketch_support(doc, req)
        sk = doc.addObject("Sketcher::SketchObject", self._id(doc, req, fallback))
        doc.Body.addObject(sk)
        sk.AttachmentSupport = (support, [element])
        sk.MapMode = "FlatFace"
        doc.recompute()
        if "Error" in sk.State or "Invalid" in sk.State:
            raise OperationError("attachment_failed", "Native sketch attachment failed", status=sk.getStatusString())
        return sk

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

    def _delete_feature(self, doc, req):
        target = doc.getObject(req["feature"])
        if target is None:
            raise OperationError("missing_reference", "Feature ID does not exist")
        if not self._deletable_feature(target, doc.Body):
            raise OperationError("unsupported_feature", "Delete supports sketches, native datum planes and built-in PartDesign features in this Body")
        cascade = req.get("cascade", False)
        if not isinstance(cascade, bool):
            raise OperationError("invalid_argument", "cascade must be boolean")
        pending = [target]
        removed = {target.Name}
        while pending:
            obj = pending.pop()
            for dependent in obj.InList:
                if dependent == doc.Body or dependent.Name in removed:
                    continue
                if dependent not in doc.Body.Group:
                    raise OperationError("external_dependency", "A feature outside this Body depends on the deletion", feature=dependent.Name)
                if not self._deletable_feature(dependent, doc.Body):
                    raise OperationError("unsupported_dependency", "A script-owned or unsupported feature depends on this deletion", feature=dependent.Name)
                removed.add(dependent.Name)
                pending.append(dependent)
        if len(removed) > 1 and not cascade:
            raise OperationError("dependent_features", "Deletion requires explicit cascade because native features depend on it", dependents=sorted(removed-{target.Name}))
        # Remove consumers first. Keep upstream features and choose the latest
        # surviving solid as Tip so deleting the last sketch does not retarget
        # the Body to an earlier sketch.
        ordered = [obj.Name for obj in doc.Body.Group if obj.Name in removed]
        for name in reversed(ordered):
            doc.removeObject(name)
        solids = [obj for obj in doc.Body.Group if obj.TypeId.startswith("PartDesign::") and hasattr(obj,"Shape") and not obj.Shape.isNull() and obj.Shape.Solids]
        # Body.Tip must be a PartDesign feature. A surviving Sketcher profile
        # is editable history, but assigning it as Tip produces a Body error.
        doc.Body.Tip = solids[-1] if solids else None
        meta = metadata(doc)
        mapping = json.loads(meta.SourceMapping)
        meta.SourceMapping = json.dumps({key:value for key,value in mapping.items() if value not in removed}, sort_keys=True)

    def _model_operation(self, doc, req):
        op = req["op"]
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
            prior_volume=doc.Body.Shape.Volume if not doc.Body.Shape.isNull() else 0
            if op=="pocket" and prior_volume<=0:
                raise OperationError("missing_body", "Pocket requires an existing solid")
            feature=doc.Body.newObject("PartDesign::Pad" if op=="pad" else "PartDesign::Pocket",self._id(doc,req,"Pad" if op=="pad" else "Pocket"))
            feature.Profile=profile
            if "reversed" in req and not isinstance(req["reversed"], bool):
                raise OperationError("invalid_argument", "reversed must be boolean")
            if op=="pad":
                feature.Length=number(req["length"],"length",True)
                feature.Reversed = req.get("reversed", False)
            else:
                if "through_all" in req and not isinstance(req["through_all"], bool):
                    raise OperationError("invalid_argument", "through_all must be boolean")
                feature.Reversed=req.get("reversed", False)
                feature.Type=1 if req.get("through_all",True) else 0
                if str(feature.Type)=="Length":
                    feature.Length=number(req["length"],"length",True)
            doc.recompute()
            if op=="pocket":
                def cut_valid():
                    return (not doc.Body.Shape.isNull() and doc.Body.Shape.isValid() and len(doc.Body.Shape.Solids)==1
                            and doc.Body.Shape.Volume < prior_volume - 1e-7
                            and not set(feature.State) & {"Error", "Invalid"})
                # Native Pocket goes against the sketch normal by default.
                # At a bottom/origin plane that direction may contain no
                # material. Try the opposite only when direction was omitted.
                if not cut_valid() and "reversed" not in req:
                    feature.Reversed = True
                    doc.recompute()
                if not cut_valid():
                    raise OperationError("empty_cut", "Pocket removes no valid material in the requested direction")
        elif op=="set_parameter":
            feature=doc.getObject(req["feature"])
            if not feature:
                raise OperationError("missing_reference", "Feature ID does not exist")
            parameter=req["parameter"]
            if parameter not in native_parameters(feature):
                raise OperationError("unsupported_parameter", "Only named driving sketch dimensions and pad/pocket Length are supported")
            info=native_parameters(feature)[parameter]
            if feature.TypeId=="Sketcher::SketchObject" and not feature.Constraints[info["constraint_index"]].Driving:
                raise OperationError("unsupported_parameter", "This parameter is not a supported driving length dimension")
            value=number(req["value"],"value",info.get("constraint_type") not in {"DistanceX", "DistanceY", "Angle"})
            property_path=(f"Constraints.{info['name']}" if info.get("name") else f"Constraints[{info['constraint_index']}]") if feature.TypeId=="Sketcher::SketchObject" else parameter
            aliases={property_path}
            if feature.TypeId=="Sketcher::SketchObject":
                aliases.add(f"Constraints[{native_parameters(feature)[parameter]['constraint_index']}]")
            if any(path.lstrip(".") in aliases for path,_ in feature.ExpressionEngine):
                raise OperationError("expression_driven", "Edit the upstream driving parameter instead")
            if feature.TypeId=="Sketcher::SketchObject":
                feature.setDatum(native_parameters(feature)[parameter]["constraint_index"],App.Units.Quantity(f"{value} {info['unit']}"))
                if feature.solve()!=0:
                    raise OperationError("constraint_conflict", "Dimension produces a sketch solver conflict")
            else:
                feature.Length=value
        elif op == "rename_feature":
            feature = doc.getObject(req["feature"])
            if feature is None:
                raise OperationError("missing_reference", "Feature ID does not exist")
            if feature != doc.Body and feature not in doc.Body.Group:
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
            created.Label=str(req.get("source_feature_name",req["source_feature_id"]))
            for prop,value in [("SourceFeatureId",req["source_feature_id"]),("SourceFeatureName",req.get("source_feature_name",req["source_feature_id"]))]:
                created.addProperty("App::PropertyString",prop,"Onshape source")
                setattr(created,prop,str(value))
                created.setEditorMode(prop,1)
            meta=metadata(doc)
            mapping=json.loads(meta.SourceMapping)
            mapping[str(req["source_feature_id"])]=created.Name
            meta.SourceMapping=json.dumps(mapping,sort_keys=True)

    def _save(self, doc, raw):
        path=write_path(raw,{".fcstd"})
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

    def _export(self, doc, raw):
        path=write_path(raw,{".step",".stp",".stl"})
        if metadata(doc).BuildStatus!="valid":
            raise OperationError("build_failed", "Only a current valid solid can be exported")
        stage=path.with_name(path.stem + ".exporting" + path.suffix)
        if path.suffix.lower()==".stl":
            import MeshPart
            mesh=MeshPart.meshFromShape(Shape=doc.Body.Shape,LinearDeflection=0.05,AngularDeflection=0.1,Relative=False)
            mesh.write(str(stage))
        else:
            Part.export([doc.Body],str(stage))
        provenance={"document_id":metadata(doc).DocumentId,"revision":metadata(doc).Revision,"units":"mm",
                    "sha256":hashlib.sha256(stage.read_bytes()).hexdigest(),
                    "native_file":doc.FileName or None,"format":path.suffix.lower(),"shape":measurements(doc.Body.Shape),
                    "settings":{"linear_deflection_mm":0.05,"angular_deflection_rad":0.1} if path.suffix.lower()==".stl" else {"writer":"FreeCAD Part/OCCT"}}
        sidecar=path.with_suffix(path.suffix+".json")
        temp=sidecar.with_suffix(sidecar.suffix+".saving")
        temp.write_text(json.dumps(provenance,indent=2),encoding="utf-8")
        self._replace_export_pair([(stage,path),(temp,sidecar)])

    def _replace_export_pair(self, pairs):
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
                os.replace(stage,target)
                committed.append(target)
        except OSError as exc:
            failures=[]
            for target in reversed(committed):
                try:
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
