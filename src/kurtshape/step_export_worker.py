"""Private STEP job: immutable input, detached world shapes, retained artifact.

The child never receives a destination. The parent may consume the fixed
artifact only after confirmed child exit and complete byte/identity validation.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kurtshape.geometry_check_worker import NativeGeometryCheckWorker, _local_dependencies
from kurtshape.preview_worker import NativePreviewWorker, _validate_transport_snapshot

MAX_JSON_BYTES = 8 * 1024 * 1024
ARTIFACT_NAME = "export.step"
SETTINGS = {"writer": "FreeCAD Part/OCCT"}


def _json_bytes(value):
    payload = json.dumps(value, allow_nan=False).encode("utf-8")
    if len(payload) > MAX_JSON_BYTES:
        raise ValueError("STEP job JSON exceeds the 8 MiB limit")
    return payload


def _json_copy(value):
    return json.loads(_json_bytes(value))


def _regular_identity(path):
    info = Path(path).lstat()
    if (not stat.S_ISREG(info.st_mode) or Path(path).is_symlink()
            or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
        raise ValueError("STEP job artifact must be a regular non-link file")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _read_json(path):
    if _regular_identity(path)[2] > MAX_JSON_BYTES:
        raise ValueError("STEP job JSON exceeds the 8 MiB limit")
    with Path(path).open("rb") as stream:
        payload = stream.read(MAX_JSON_BYTES + 1)
    if len(payload) > MAX_JSON_BYTES:
        raise ValueError("STEP job JSON exceeds the 8 MiB limit")
    def reject(value):
        raise ValueError("Nonfinite STEP job JSON: " + value)
    return json.loads(payload, parse_constant=reject)


def _artifact_info(path):
    """Hash one stable regular file, checking the opened handle and pathname."""
    path = Path(path)
    identity = _regular_identity(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != identity:
            raise ValueError("STEP artifact changed while opening")
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
        finished = os.fstat(stream.fileno())
        if (finished.st_dev, finished.st_ino, finished.st_size, finished.st_mtime_ns) != identity:
            raise ValueError("STEP artifact changed while reading")
    if _regular_identity(path) != identity:
        raise ValueError("STEP artifact changed while hashing")
    return {"name": ARTIFACT_NAME, "size": identity[2], "sha256": digest.hexdigest(), "identity": list(identity)}


def world_fingerprints(document, target_ids):
    """Ordered exact export geometry/placement proof; only Checked is canonical."""
    from kurtshape.assembly import global_shape, canonical_brep
    from kurtshape.core import _native_value
    rows = []
    for name in target_ids:
        target = document.getObject(name)
        if target is None or target.Document != document:
            raise ValueError("STEP export target is missing")
        shape = global_shape(target).copy()
        rows.append({
            "id": target.Name, "type": target.TypeId,
            "part_id": getattr(target, "KurtShapePartId", target.Name),
            "placement": _native_value(target.Placement),
            "global_placement": _native_value(target.getGlobalPlacement()),
            "brep_sha256": hashlib.sha256(canonical_brep(shape.exportBrepToString()).encode("utf-8")).hexdigest(),
            "element_map": dict(shape.ElementMap), "element_reverse_map": dict(shape.ElementReverseMap),
            "element_map_version": shape.ElementMapVersion, "element_map_size": shape.ElementMapSize,
        })
    return _json_copy(rows)


def world_roundtrip_stable(document, target_ids):
    """Admit only exact detached BRep round trips, retaining every coefficient.

    This is an eligibility check, never a replacement for the captured world
    fingerprint or the child's archive comparisons. Unstable native frames
    retain the synchronous export path without changing the source geometry.
    """
    try:
        import Part
        from kurtshape.assembly import global_shape, canonical_brep
        for name in target_ids:
            target = document.getObject(name)
            if target is None or target.Document != document:
                return False
            original = global_shape(target).copy().exportBrepToString()
            restored = Part.Shape()
            restored.importBrepFromString(original)
            if canonical_brep(original) != canonical_brep(restored.exportBrepToString()):
                return False
        return True
    except Exception:
        return False


def _validate_envelope(envelope):
    envelope = _json_copy(envelope)
    if not isinstance(envelope, dict) or set(envelope) != {
            "snapshot_key", "document_id", "target_ids", "target_fingerprints", "format", "settings"}:
        raise ValueError("Invalid STEP export envelope")
    key = envelope["snapshot_key"]
    if (not isinstance(key, dict) or set(key) != {"instance_id", "revision", "generation", "serial", "policy"}
            or any(not isinstance(key[name], str) or not key[name] for name in ("instance_id", "revision", "policy"))
            or any(type(key[name]) is not int or key[name] < 0 for name in ("generation", "serial"))):
        raise ValueError("Invalid STEP export snapshot key")
    names = envelope["target_ids"]
    if (not isinstance(names, list) or not names or len(names) > 10000
            or any(not isinstance(name, str) or not name or len(name) > 255 for name in names)
            or len(set(names)) != len(names)):
        raise ValueError("Invalid STEP export target identities")
    if not isinstance(envelope["document_id"], str) or not envelope["document_id"]:
        raise ValueError("Invalid STEP export document identity")
    fingerprints = envelope["target_fingerprints"]
    if (not isinstance(fingerprints, list) or len(fingerprints) != len(names)
            or any(not isinstance(row, dict) for row in fingerprints)
            or [row.get("id") for row in fingerprints] != names):
        raise ValueError("Invalid ordered STEP export fingerprints")
    if envelope["format"] not in {".step", ".stp"} or envelope["settings"] != SETTINGS:
        raise ValueError("Unsupported STEP export format or settings")
    return envelope


class NativeStepExportWorker(NativeGeometryCheckWorker):
    """Use established lease teardown, retaining results until explicit close."""

    def __init__(self, executable, parent_directory, timeout=120):
        parent = Path(parent_directory) / "step-export-jobs"
        parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="step-export-", dir=parent, ignore_cleanup_errors=True)
        self.folder = Path(self.temporary.name)
        self.snapshot = self.folder / "source.FCStd"
        self.token = uuid.uuid4().hex
        self.executable = str(executable)
        self.timeout = timeout
        self.process = self.log = None
        self.active = None
        self.started = 0
        self.closed = False
        self._snapshot_lease = None
        self._snapshot_identity = None
        self.cleanup_complete = threading.Event()
        self._close_lock = threading.Lock()
        self._accepted_key = None
        self._submitted = False
        self._envelope = None
        self._completed_response = None

    def _start(self):
        if self.closed or self.process is not None or self._accepted_key is None:
            raise RuntimeError("STEP export worker requires an immutable snapshot")
        _validate_transport_snapshot(self.snapshot, self._snapshot_identity)
        environment = os.environ.copy()
        for name, child in (("KURTSHAPE_SESSION_DIR", "session"), ("FREECAD_USER_HOME", "user-data"),
                            ("APPDATA", "appdata"), ("LOCALAPPDATA", "localappdata"),
                            ("TEMP", "temporary"), ("TMP", "temporary")):
            path = self.folder / child
            path.mkdir(exist_ok=True)
            environment[name] = str(path)
        environment.update(PYTHONDONTWRITEBYTECODE="1", QT_QPA_PLATFORM="offscreen")
        self.log = (self.folder / "native-worker.log").open("wb")
        self.process = subprocess.Popen(
            [self.executable, "-B", str(Path(__file__).resolve()), str(self.folder), self.token,
             str(self.snapshot), json.dumps(self._snapshot_identity)],
            stdin=subprocess.PIPE, stdout=self.log, stderr=subprocess.STDOUT,
            env=environment, cwd=self.folder, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def submit(self, sequence, envelope):
        if self._submitted or type(sequence) is not int or sequence < 0:
            raise RuntimeError("STEP export worker accepts one numbered job")
        envelope = _validate_envelope(envelope)
        if envelope["snapshot_key"] != self._accepted_key:
            raise RuntimeError("STEP export job does not match its immutable snapshot")
        _json_bytes({"task": self.token, "sequence": sequence, "proposal": envelope})
        self._envelope = envelope
        try:
            NativePreviewWorker.submit(self, sequence, envelope)
            self._submitted = True
        except BaseException:
            self.close()
            raise

    def poll(self):
        if self.closed or self.active is None:
            return None
        # Retain active and its original deadline throughout child teardown.
        # Reading only after exit also closes the publish/exit observation race.
        exit_code = self.process.poll()
        expired = time.monotonic() - self.started > self.timeout
        if exit_code is None:
            if expired:
                raise TimeoutError("STEP export exceeded its time limit")
            return None
        if exit_code != 0:
            raise RuntimeError("STEP export worker stopped before completing")
        try:
            response = _read_json(self.folder / ("result-" + str(self.active) + ".json"))
        except PermissionError:
            if expired:
                raise TimeoutError("STEP export result remained unavailable after child exit")
            return None
        if (not isinstance(response, dict) or response.get("task") != self.token
                or type(response.get("sequence")) is not int or response["sequence"] != self.active
                or any(response.get(name) != value for name, value in self._envelope.items())):
            raise RuntimeError("STEP export response belongs to another captured job")
        self._completed_response = _json_copy(response)
        self.active = None
        return response

    def validated_artifact(self, response):
        if (self.closed or self.process is None or self.process.poll() != 0
                or self._completed_response is None or response != self._completed_response
                or response.get("ok") is not True):
            raise RuntimeError("STEP artifact is not owned by a completed successful job")
        artifact = response.get("artifact")
        if (not isinstance(artifact, dict) or set(artifact) != {"name", "size", "sha256", "identity"}
                or artifact["name"] != ARTIFACT_NAME or type(artifact["size"]) is not int or artifact["size"] <= 0
                or not isinstance(artifact["sha256"], str) or len(artifact["sha256"]) != 64
                or not isinstance(artifact["identity"], list) or len(artifact["identity"]) != 4
                or any(type(value) is not int for value in artifact["identity"])):
            raise ValueError("Invalid STEP artifact description")
        folder_info = self.folder.lstat()
        if (not stat.S_ISDIR(folder_info.st_mode) or self.folder.is_symlink()
                or getattr(folder_info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            raise ValueError("STEP job directory changed")
        path = self.folder / ARTIFACT_NAME
        if _artifact_info(path) != artifact:
            raise ValueError("STEP artifact bytes or identity changed after export")
        return path


def _targets(document, names):
    from kurtshape.assembly import assemblies
    from kurtshape.bodies import results
    if assemblies(document) or any(obj.TypeId.startswith("Assembly::") for obj in document.Objects):
        raise ValueError("Assembly STEP jobs require the synchronous export path")
    _local_dependencies(document)
    available = {obj.Name: obj for obj in results(document) if not obj.Shape.isNull() and obj.Shape.Solids}
    if any(name not in available for name in names):
        raise ValueError("STEP export target is no longer a current solid result")
    return [available[name] for name in names]


def _export_document(core, document, path, identity, envelope, folder, phases, work):
    import Part
    from kurtshape import geometry
    from kurtshape.assembly import global_shape
    from kurtshape.core import METADATA, OperationError
    from kurtshape.extrusion_preview import _normalize_preview_source, _preview_phase
    from kurtshape.preview_worker import _attach_preview_document

    def incompatible(message):
        raise OperationError("step_export_snapshot_incompatible", message)

    _validate_transport_snapshot(path, identity)
    metadata = document.getObject(METADATA)
    if (metadata is None or metadata.DocumentId != envelope["document_id"]
            or metadata.Revision != envelope["snapshot_key"]["revision"]):
        incompatible("The archive does not match the captured export revision")
    if metadata.BuildStatus != "valid":
        raise OperationError("build_failed", "Only a current valid solid can be exported")
    try:
        with _preview_phase(phases, "source_equivalence"):
            _normalize_preview_source(core, document)
            _targets(document, envelope["target_ids"])
            if world_fingerprints(document, envelope["target_ids"]) != envelope["target_fingerprints"]:
                incompatible("The loaded archive does not match the captured world geometry")
        snapshot = _attach_preview_document(core, document, path, identity, phases)
        if snapshot is None:
            incompatible("Native attachment changed the captured export project")
        with _preview_phase(phases, "source_equivalence"):
            targets = _targets(document, envelope["target_ids"])
            if world_fingerprints(document, envelope["target_ids"]) != envelope["target_fingerprints"]:
                incompatible("Native attachment changed the captured world geometry")
        if core._meta(document).BuildStatus != "valid":
            raise OperationError("build_failed", "The captured export project is not valid")
    except OperationError:
        raise
    except Exception as exc:
        incompatible("The captured export state could not be verified: " + str(exc))
    checks = []
    work.update(start_ns=time.perf_counter_ns(), clock="time.perf_counter_ns")
    try:
        with _preview_phase(phases, "check"):
            for target in targets:
                snapshot.validate(core, document, snapshot.revision)
                checks.append(dict(geometry.check_shape(global_shape(target).copy()), id=target.Name))
        if any(not check["valid"] for check in checks):
            raise OperationError("invalid_geometry", "Geometry check failed; nothing was exported", checks=checks,
                                 features=[{"feature": check["id"], "issues": check["issues"]} for check in checks if not check["valid"]])
        core.geometry.accept_checks([(core.geometry.check_key(target), check) for target, check in zip(targets, checks)])
        with _preview_phase(phases, "measurements"):
            measurements = core._geometry(document, targets, "full")
        artifact_path = folder / ARTIFACT_NAME
        with _preview_phase(phases, "export_write"):
            shape = Part.makeCompound([global_shape(target).copy() for target in targets])
            shape.exportStep(str(artifact_path))
            with artifact_path.open("rb+") as artifact_file:
                artifact_file.flush()
                os.fsync(artifact_file.fileno())
        with _preview_phase(phases, "artifact_seal"):
            artifact = _artifact_info(artifact_path)
            if artifact["size"] <= 0:
                raise OperationError("step_export_failed", "Native STEP export was empty")
    finally:
        work["end_ns"] = time.perf_counter_ns()
    snapshot.validate(core, document, snapshot.revision)
    with _preview_phase(phases, "source_equivalence"):
        if (world_fingerprints(document, envelope["target_ids"]) != envelope["target_fingerprints"]
                or [obj.Name for obj in _targets(document, envelope["target_ids"])] != envelope["target_ids"]):
            incompatible("Native export changed the captured world geometry")
    _validate_transport_snapshot(path, identity)
    return checks, measurements, artifact


def run_worker(folder, token, snapshot_path, snapshot_identity):
    import FreeCAD as App
    import Part
    from kurtshape.core import Controller, OperationError
    from kurtshape.extrusion_preview import _preview_phase

    line = sys.stdin.buffer.readline(4097)
    if len(line) > 4096:
        raise ValueError("Invalid STEP export wake-up size")
    signal = json.loads(line)
    if signal.get("task") != token or type(signal.get("sequence")) is not int or signal["sequence"] < 0:
        raise ValueError("Invalid private STEP export request")
    sequence = signal["sequence"]
    request_path = folder / ("request-" + str(sequence) + ".json")
    request = _read_json(request_path)
    request_path.unlink()
    if request.get("task") != token or type(request.get("sequence")) is not int or request["sequence"] != sequence:
        raise ValueError("Private STEP export request identity changed")
    envelope = _validate_envelope(request["proposal"])
    response = dict(envelope, task=token, sequence=sequence, ok=False, checks=[], measurements=None,
                    artifact=None, error=None, engine={"FreeCAD": App.Version(), "OCCT": Part.OCC_VERSION})
    phases, work = {}, {}
    began = time.perf_counter()
    core = Controller()
    try:
        identity = _validate_transport_snapshot(snapshot_path, snapshot_identity)
        with _preview_phase(phases, "source_open"):
            document = App.openDocument(str(snapshot_path))
        _validate_transport_snapshot(snapshot_path, identity)
        checks, measurements, artifact = _export_document(core, document, snapshot_path, identity, envelope, folder, phases, work)
        response.update(ok=True, checks=checks, measurements=measurements, artifact=artifact)
    except Exception as exc:
        if isinstance(exc, OperationError):
            response["error"] = {"code": exc.code, "message": str(exc), **exc.details}
            response["checks"] = exc.details.get("checks", [])
        else:
            response["error"] = {"code": "step_export_failed", "message": str(exc)}
    finally:
        core.close()
        for name in list(App.listDocuments()):
            App.closeDocument(name)
    response.update(milliseconds=(time.perf_counter()-began)*1000, phase_milliseconds=phases, export_work=work)
    destination = folder / ("result-" + str(sequence) + ".json")
    stage = destination.with_suffix(".writing")
    with stage.open("wb") as stream:
        stream.write(_json_bytes(response))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(stage, destination)


if __name__ == "__main__":
    run_worker(Path(sys.argv[1]).resolve(), sys.argv[2], Path(sys.argv[3]).resolve(), json.loads(sys.argv[4]))
