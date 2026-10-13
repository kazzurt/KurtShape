"""One bounded native geometry-check job over an immutable accepted archive.

Only detached JSON crosses this boundary. The parent's captured topology cache
keys stay in the parent; a child's native shape identity is never a cache key.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import uuid

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kurtshape.preview_worker import NativePreviewWorker, _validate_transport_snapshot


def _json_copy(value):
    return json.loads(json.dumps(value, allow_nan=False))


def target_fingerprints(document, target_ids):
    """Describe exactly the detached native topology checked by the oracle.

    Use the existing native fingerprint policy for the transient Checked bit.
    Every numeric BRep coefficient, other native flag and complete map value
    remains significant. Unknown native reads fail closed, never omit fields.
    """
    from kurtshape.geometry import source_of
    from kurtshape.assembly import canonical_brep
    rows = {}
    for name in target_ids:
        target = document.getObject(name)
        if target is None or target.Document != document:
            raise ValueError("Geometry check target is missing")
        source = source_of(target)
        if source.Document != document:
            raise ValueError("Foreign geometry check sources are unsupported")
        shape = source.Shape.copy()
        rows[name] = {
            "source_name": source.Name, "source_type": source.TypeId,
            "brep_sha256": hashlib.sha256(canonical_brep(shape.exportBrepToString()).encode("utf-8")).hexdigest(),
            "element_map": dict(shape.ElementMap),
            "element_reverse_map": dict(shape.ElementReverseMap),
            "element_map_version": shape.ElementMapVersion,
            "element_map_size": shape.ElementMapSize,
        }
    return _json_copy(rows)


def _validate_envelope(envelope):
    envelope = _json_copy(envelope)
    if not isinstance(envelope, dict) or set(envelope) != {
            "snapshot_key", "target_ids", "document_id", "target_fingerprints"}:
        raise ValueError("Invalid geometry check envelope")
    key = envelope["snapshot_key"]
    if (not isinstance(key, dict) or set(key) != {
            "instance_id", "revision", "generation", "serial", "policy"}
            or any(not isinstance(key[name], str) or not key[name]
                   for name in ("instance_id", "revision", "policy"))
            or any(type(key[name]) is not int or key[name] < 0 for name in ("generation", "serial"))):
        raise ValueError("Invalid geometry check snapshot key")
    names = envelope["target_ids"]
    if (not isinstance(names, list) or not names or len(names) > 10000
            or any(not isinstance(name, str) or not name or len(name) > 255 for name in names)
            or len(set(names)) != len(names)):
        raise ValueError("Invalid geometry check targets")
    if not isinstance(envelope["document_id"], str) or not envelope["document_id"]:
        raise ValueError("Invalid geometry check document identity")
    fingerprints = envelope["target_fingerprints"]
    if not isinstance(fingerprints, dict) or set(fingerprints) != set(names):
        raise ValueError("Missing geometry check topology fingerprints")
    return envelope


class NativeGeometryCheckWorker(NativePreviewWorker):
    """Reuse the preview worker's nonblocking, confirmed-exit lease cleanup."""

    def __init__(self, executable, parent_directory, timeout=120):
        # The transport's lifecycle methods operate on these same fields. A
        # dedicated directory avoids creating misleading preview artifacts.
        parent = Path(parent_directory) / "geometry-check-jobs"
        parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="geometry-check-", dir=parent,
                                                      ignore_cleanup_errors=True)
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

    def borrow_snapshot(self, lease):
        if self._accepted_key is not None:
            raise RuntimeError("Geometry check worker already owns a snapshot")
        key = _json_copy(asdict(lease.key))
        super().borrow_snapshot(lease)
        self._accepted_key = key

    def own_snapshot(self, key, identity):
        """Bind a guarded capture, retaining its originally acquired identity."""
        if self.closed or self.process is not None or self._accepted_key is not None:
            raise RuntimeError("Geometry check worker cannot accept another snapshot")
        path = Path(self.snapshot).resolve(strict=True)
        if path != (self.folder / "source.FCStd").resolve(strict=True):
            raise RuntimeError("Geometry check capture is not owned by this job")
        accepted_key = _json_copy(asdict(key))
        identity = tuple(identity)
        _validate_transport_snapshot(path, identity)
        self._snapshot_identity = identity
        self._accepted_key = accepted_key

    def _start(self):
        if self.closed or self.process is not None or self._accepted_key is None:
            raise RuntimeError("Geometry check worker requires an immutable snapshot")
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
            raise RuntimeError("Geometry check worker accepts one numbered job")
        envelope = _validate_envelope(envelope)
        if envelope["snapshot_key"] != self._accepted_key:
            raise RuntimeError("Geometry check job does not match its immutable snapshot")
        try:
            super().submit(sequence, envelope)
            self._submitted = True
        except BaseException:
            self.close()
            raise

    def poll(self):
        try:
            return super().poll()
        except RuntimeError:
            # This child exits after publishing its one result. Publication
            # can fall between the base transport's first file check and its
            # process-exit check. Once exit is confirmed, perform one final
            # read through the same parser and task/sequence validation.
            if (not self.closed and self.active is not None and self.process is not None
                    and self.process.poll() is not None
                    and (self.folder / ("result-" + str(self.active) + ".json")).exists()):
                return super().poll()
            raise


def _current_targets(document, names):
    from kurtshape.bodies import results as native_results
    available = {obj.Name: obj for obj in native_results(document)
                 if not obj.Shape.isNull() and obj.Shape.Solids}
    if any(name not in available for name in names):
        raise ValueError("Geometry check target is no longer a current solid result")
    return [available[name] for name in names]


def _local_dependencies(document):
    for obj in document.Objects:
        dependencies = list(obj.OutList)
        linked = getattr(obj, "LinkedObject", None)
        if linked is not None:
            linked = linked[0] if isinstance(linked, tuple) else linked
            dependencies.append(linked)
        if any(dependency is None or dependency.Document != document for dependency in dependencies):
            raise ValueError("Foreign geometry check dependencies are unsupported")


def _check_document(core, document, path, identity, envelope, phases):
    from kurtshape import geometry
    from kurtshape.core import METADATA, OperationError
    from kurtshape.extrusion_preview import _normalize_preview_source, _preview_phase
    from kurtshape.preview_worker import _attach_preview_document

    def incompatible(message):
        raise OperationError("geometry_check_snapshot_incompatible", message)

    _validate_transport_snapshot(path, identity)
    metadata = document.getObject(METADATA)
    if (metadata is None or metadata.DocumentId != envelope["document_id"]
            or metadata.Revision != envelope["snapshot_key"]["revision"]):
        incompatible("The archive does not match the captured project revision")
    try:
        with _preview_phase(phases, "source_equivalence"):
            _normalize_preview_source(core, document)
            _local_dependencies(document)
            _current_targets(document, envelope["target_ids"])
            if target_fingerprints(document, envelope["target_ids"]) != envelope["target_fingerprints"]:
                incompatible("The loaded archive does not match the captured geometry")
        snapshot = _attach_preview_document(core, document, path, identity, phases)
        if snapshot is None:
            incompatible("Native attachment changed the captured project")
        with _preview_phase(phases, "source_equivalence"):
            _local_dependencies(document)
            targets = _current_targets(document, envelope["target_ids"])
            if target_fingerprints(document, envelope["target_ids"]) != envelope["target_fingerprints"]:
                incompatible("Native attachment changed the captured geometry")
    except OperationError:
        raise
    except Exception as exc:
        incompatible("The captured native state could not be verified: " + str(exc))
    checks = []
    with _preview_phase(phases, "check"):
        for target in targets:
            snapshot.validate(core, document, snapshot.revision)
            checks.append(dict(geometry.check_shape(geometry.source_of(target).Shape.copy()), id=target.Name))
    snapshot.validate(core, document, snapshot.revision)
    with _preview_phase(phases, "source_equivalence"):
        if target_fingerprints(document, envelope["target_ids"]) != envelope["target_fingerprints"]:
            incompatible("Native checks changed the captured geometry")
    _validate_transport_snapshot(path, identity)
    return checks


def run_worker(folder, token, snapshot_path, snapshot_identity):
    """Native child entry point; one request, finite atomic JSON response."""
    import FreeCAD as App
    import Part
    from kurtshape.core import Controller, OperationError
    from kurtshape.extrusion_preview import _preview_phase

    signal = json.loads(sys.stdin.buffer.readline())
    if signal.get("task") != token or type(signal.get("sequence")) is not int or signal["sequence"] < 0:
        raise ValueError("Invalid private geometry check request")
    sequence = signal["sequence"]
    request_path = folder / ("request-" + str(sequence) + ".json")
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request_path.unlink()
    if request.get("task") != token or request.get("sequence") != sequence:
        raise ValueError("Private geometry check request identity changed")
    envelope = _validate_envelope(request["proposal"])
    response = dict(envelope, task=token, sequence=sequence, ok=False, checks=[], error=None)
    phases = {}
    began = time.perf_counter()
    core = Controller()
    try:
        identity = _validate_transport_snapshot(snapshot_path, snapshot_identity)
        with _preview_phase(phases, "source_open"):
            document = App.openDocument(str(snapshot_path))
        _validate_transport_snapshot(snapshot_path, identity)
        response["checks"] = _check_document(core, document, snapshot_path, identity, envelope, phases)
        response.update(ok=True, engine={"FreeCAD": App.Version(), "OCCT": Part.OCC_VERSION})
    except Exception as exc:
        response["error"] = ({"code": exc.code, "message": str(exc)} if isinstance(exc, OperationError)
                             else {"code": "geometry_check_failed", "message": str(exc)})
    finally:
        core.close()
        for name in list(App.listDocuments()):
            App.closeDocument(name)
    response["milliseconds"] = (time.perf_counter() - began) * 1000
    response["phase_milliseconds"] = phases
    destination = folder / ("result-" + str(sequence) + ".json")
    stage = destination.with_suffix(".writing")
    stage.write_text(json.dumps(response, allow_nan=False), encoding="utf-8")
    os.replace(stage, destination)


if __name__ == "__main__":
    run_worker(Path(sys.argv[1]).resolve(), sys.argv[2], Path(sys.argv[3]).resolve(), json.loads(sys.argv[4]))
