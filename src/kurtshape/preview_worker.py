"""Private process transport for exact previews; no GUI/native handles cross it.

The parent owns one process and at most one submitted request. Requests and
results are JSON; source geometry is an immutable private FCStd snapshot.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import uuid


def _snapshot_file_identity(path):
    path = Path(path)
    stat = path.stat()
    if not path.is_file():
        raise RuntimeError("Preview snapshot is not a native file")
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def _validate_transport_snapshot(path, identity):
    """Validate the parent's pinned file identity before native opening."""
    try:
        current = _snapshot_file_identity(path)
    except OSError as exc:
        raise RuntimeError("Preview snapshot is unavailable") from exc
    if current != tuple(identity):
        raise RuntimeError("Preview snapshot changed before worker loading")
    return current


class NativePreviewWorker:
    def __init__(self, executable, parent_directory, timeout=120):
        parent = Path(parent_directory) / "exact-preview-workers"
        parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="preview-task-", dir=parent, ignore_cleanup_errors=True)
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

    def borrow_snapshot(self, lease):
        """Take ownership only on success; callers release a rejected lease."""
        if self.closed or self.process is not None or self._snapshot_lease is not None:
            raise RuntimeError("Preview worker cannot accept another snapshot")
        path = Path(lease.path).resolve(strict=True)
        identity = tuple(lease.file_identity)
        _validate_transport_snapshot(path, identity)
        self.snapshot = path
        self._snapshot_identity = identity
        self._snapshot_lease = lease

    def _start(self):
        if self.closed or self.process is not None:
            raise RuntimeError("Preview worker is closed or already started")
        identity = self._snapshot_identity or _snapshot_file_identity(self.snapshot)
        _validate_transport_snapshot(self.snapshot, identity)
        environment = os.environ.copy()
        for name, child in (("KURTSHAPE_SESSION_DIR", "session"), ("FREECAD_USER_HOME", "user-data"),
                            ("APPDATA", "appdata"), ("LOCALAPPDATA", "localappdata"),
                            ("TEMP", "temporary"), ("TMP", "temporary")):
            path = self.folder / child
            path.mkdir(exist_ok=True)
            environment[name] = str(path)
        environment.update(PYTHONDONTWRITEBYTECODE="1", QT_QPA_PLATFORM="offscreen")
        self.log = (self.folder / "native-worker.log").open("wb")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.process = subprocess.Popen(
            [self.executable, "-B", "-P", str(Path(__file__).resolve()), str(self.folder), self.token,
             str(self.snapshot), json.dumps(identity)],
            stdin=subprocess.PIPE, stdout=self.log, stderr=subprocess.STDOUT,
            env=environment, cwd=self.folder, creationflags=flags)

    def start(self):
        if self.closed or self.process is not None:
            raise RuntimeError("Preview worker is closed or already started")
        try:
            self._start()
        except BaseException:
            self.close()
            raise

    def submit(self, sequence, proposal):
        if self.closed or self.active is not None:
            raise RuntimeError("Preview worker is closed or already evaluating")
        if self.process is None:
            self.start()
        request = {"task": self.token, "sequence": sequence, "proposal": proposal}
        # Large selector lists go through a private file; only a tiny wake-up
        # record goes through the bounded OS pipe while native Python starts.
        request_path = self.folder / ("request-" + str(sequence) + ".json")
        request_path.write_text(json.dumps(request, allow_nan=False), encoding="utf-8")
        self.process.stdin.write((json.dumps({"task": self.token, "sequence": sequence}) + "\n").encode("utf-8"))
        self.process.stdin.flush()
        self.active = sequence
        self.started = time.monotonic()

    def poll(self):
        if self.closed or self.active is None:
            return None
        path = self.folder / ("result-" + str(self.active) + ".json")
        if path.exists():
            try:
                response = json.loads(path.read_text(encoding="utf-8"))
            except PermissionError:
                # Windows scanners can briefly deny access even after atomic
                # publication. Retry on the next Qt poll, subject to timeout.
                response = None
            if response is not None:
                if response.get("task") != self.token or response.get("sequence") != self.active:
                    raise RuntimeError("Exact preview response belongs to another task")
                try:
                    path.unlink()
                except PermissionError:
                    # A cleanup lock cannot invalidate geometry already read.
                    # The owned task directory is cleaned again on close.
                    pass
                self.active = None
                return response
        if self.process.poll() is not None:
            raise RuntimeError("Exact preview worker stopped; restart the feature tool")
        if time.monotonic() - self.started > self.timeout:
            raise TimeoutError("Exact preview exceeded its time limit; simplify the feature or try again")
        return None

    def close(self):
        with self._close_lock:
            if self.closed:
                return
            self.closed = True
            process, log, temporary = self.process, self.log, self.temporary
            lease = self._snapshot_lease
        # Waiting for process handles and deleting files are pure file work.
        # Keep cancellation from waiting on Windows process/file teardown.
        def reap():
            exited = process is None
            try:
                if process is not None:
                    while not exited:
                        try:
                            process.kill()
                        except OSError:
                            pass
                        try:
                            process.wait(timeout=10)
                            exited = True
                        except subprocess.TimeoutExpired:
                            continue
                        except OSError:
                            # A wait error does not establish that native file
                            # readers have stopped. Poll may independently prove
                            # exit; otherwise preserve the lease and retry.
                            try:
                                exited = process.poll() is not None
                            except OSError:
                                pass
                            if not exited:
                                time.sleep(.1)
                    if process.stdin:
                        try:
                            process.stdin.close()
                        except (OSError, ValueError):
                            pass
            finally:
                # An unexpected wait failure also retains the pin. Never put
                # release/cleanup in an unconditional timeout/error finally.
                if exited:
                    try:
                        if log is not None:
                            log.close()
                    finally:
                        try:
                            temporary.cleanup()
                        finally:
                            try:
                                if lease is not None:
                                    lease.release()
                            finally:
                                self._snapshot_lease = None
                                self.cleanup_complete.set()
        threading.Thread(target=reap, name="KurtShape-preview-cleanup", daemon=True).start()


def _snapshot_equivalence_state(core, document):
    """Conservative native attachment oracle, evaluated only at worker startup.

    Session revision and derived verdicts may change during attach. Every other
    project metadata value, property schema, authored field and native map
    marker remains significant. Shape map fields are read from actual shapes,
    not inferred from the object's sometimes-empty marker property.
    """
    from kurtshape.core import METADATA, native_intent, _native_value
    meta = document.getObject(METADATA)
    if meta is None:
        raise ValueError("Preview archive has no managed project metadata")
    schema, maps, flags = {}, {}, {}
    for obj in document.Objects:
        properties = {name: obj.getTypeIdOfProperty(name) for name in obj.PropertiesList}
        schema[obj.Name] = (obj.TypeId, properties)
        flags[obj.Name] = tuple(obj.State)
        for name, type_id in properties.items():
            if "Shape" in type_id:
                shape = getattr(obj, name)
                maps[(obj.Name, name)] = (shape.ElementMapVersion, shape.ElementMapSize)
    intent = native_intent(document)
    # The full-intent oracle intentionally tolerates unreadable properties for
    # ordinary inspection. Borrowing needs a stricter proof: a silently omitted
    # authored field cannot establish equivalence. Detect omissions from the
    # schema already read, without invoking any native getter a second time.
    excluded = {"Shape", "InternalShape", "ExpressionEngine", "Geometry", "Constraints", "Proxy",
                "PlacementList", "Visibility", "QueryHealth", "QueryResolutionLog"}
    expected_objects = {name for name, (type_id, _) in schema.items()
                        if name != METADATA and not type_id.startswith(("App::Origin", "App::Line", "App::Plane"))}
    if {item["id"] for item in intent} != expected_objects:
        raise ValueError("Preview native intent inventory is incomplete")
    for item in intent:
        properties = schema[item["id"]][1]
        expected = {name for name, type_id in properties.items()
                    if name not in excluded and "Shape" not in type_id}
        if expected - set(item["properties"]):
            raise ValueError("Preview native intent has unreadable authored properties")
    return {"label": document.Label, "use_hasher": bool(document.UseHasher),
            "intent": intent, "schema": schema, "flags": flags,
            "metadata": {name: _native_value(getattr(meta, name)) for name in meta.PropertiesList
                         if name not in {"Revision", "BuildStatus", "LastFailure"}},
            "generation": core.observer.state(document)["generation"], "maps": maps}


def _attach_preview_document(core, document, path, source_identity, phases):
    """Return a borrowed descriptor only when attachment preserves loaded state."""
    from kurtshape.extrusion_preview import (ImmutablePreviewSnapshot,
                                             _normalize_preview_source, _preview_phase)
    from kurtshape.core import OperationError
    def check_identity():
        try:
            unchanged = ImmutablePreviewSnapshot._identity(path) == source_identity
        except OSError as exc:
            raise OperationError("invalid_preview_snapshot", "The preview archive is unavailable") from exc
        if not unchanged:
            raise OperationError("invalid_preview_snapshot", "The preview archive changed while opening")
    check_identity()
    before = None
    try:
        with _preview_phase(phases, "source_normalize"):
            _normalize_preview_source(core, document)
        with _preview_phase(phases, "source_equivalence"):
            before = _snapshot_equivalence_state(core, document)
    except Exception:
        # Missing/unknown native metadata must select the existing owned-copy
        # path, never an optimistic equivalence decision.
        pass
    with _preview_phase(phases, "source_attach"):
        core.attach(document)
    check_identity()
    if before is None:
        return None
    try:
        with _preview_phase(phases, "source_equivalence"):
            if before != _snapshot_equivalence_state(core, document):
                return None
    except Exception:
        return None
    snapshot = ImmutablePreviewSnapshot.bind(core, document, path)
    if snapshot.file_identity != source_identity:
        raise OperationError("invalid_preview_snapshot", "The preview archive changed while binding")
    return snapshot


def run_worker(folder, token, snapshot_path=None, snapshot_identity=None):
    """Runs only under bundled native Python in the isolated child process."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import FreeCAD as App
    from kurtshape.core import Controller
    from kurtshape.extrusion_preview import (ExtrusionEvaluator, ImmutablePreviewSnapshot,
                                             render_mesh, _preview_phase)
    core = Controller()
    evaluator = None
    source_phases = {}
    try:
        path = Path(snapshot_path) if snapshot_path is not None else folder / "source.FCStd"
        source_identity = (_validate_transport_snapshot(path, snapshot_identity)
                           if snapshot_identity is not None else ImmutablePreviewSnapshot._identity(path))
        with _preview_phase(source_phases, "source_open"):
            document = App.openDocument(str(path))
        snapshot = _attach_preview_document(core, document, path, source_identity, source_phases)
        evaluator = ExtrusionEvaluator(core, document, core._meta(document).Revision,
                                       snapshot_source=snapshot)
        for line in sys.stdin.buffer:
            signal = json.loads(line)
            if signal.get("task") != token or type(signal.get("sequence")) is not int:
                raise ValueError("Invalid private preview request")
            request_path = folder / ("request-" + str(signal["sequence"]) + ".json")
            request = json.loads(request_path.read_text(encoding="utf-8"))
            request_path.unlink()
            if request.get("task") != token or request.get("sequence") != signal["sequence"]:
                raise ValueError("Private preview request identity changed")
            began = time.perf_counter()
            evaluations_before = evaluator.evaluations
            captures_before = evaluator.snapshot_captures
            result = evaluator.evaluate(request["proposal"])
            response = {"task": token, "sequence": request["sequence"], "valid": result.valid,
                        "proposal": result.proposal, "body_id": result.body_id,
                        "error": result.error, "measurements": result.measurements,
                        "cached": result.cached, "mesh": None}
            response["evaluation_delta"] = evaluator.evaluations - evaluations_before
            response["snapshot_reused"] = snapshot is not None
            response["snapshot_capture_delta"] = evaluator.snapshot_captures - captures_before
            phases = dict(result.phase_milliseconds or {})
            phases.update(source_phases)
            source_phases.clear()
            if result.valid:
                try:
                    with _preview_phase(phases, "render"):
                        response["mesh"] = render_mesh(result.material_shape, result.shape)
                        response["measurements"] = dict(result.measurements or {},
                                                         material_volume_mm3=result.material_shape.Volume)
                except Exception as exc:
                    response.update(valid=False, error={"code": "preview_render_failed", "message": str(exc)})
            response["milliseconds"] = (time.perf_counter() - began) * 1000
            response["phase_milliseconds"] = phases
            destination = folder / ("result-" + str(request["sequence"]) + ".json")
            stage = destination.with_suffix(".writing")
            stage.write_text(json.dumps(response, allow_nan=False), encoding="utf-8")
            os.replace(stage, destination)
    finally:
        if evaluator is not None:
            evaluator.close()
        core.close()
        for name in list(App.listDocuments()):
            App.closeDocument(name)


if __name__ == "__main__":
    run_worker(Path(sys.argv[1]).resolve(), sys.argv[2],
               Path(sys.argv[3]).resolve() if len(sys.argv) > 3 else None,
               json.loads(sys.argv[4]) if len(sys.argv) > 4 else None)
