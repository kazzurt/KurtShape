"""Native STEP jobs retain source truth and publish only a current verified pair."""
from dataclasses import asdict, replace
from contextlib import ExitStack
import copy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
from kurtshape import assembly, geometry
from kurtshape.core import Controller, OperationError, native_intent
from kurtshape.preview_worker import _snapshot_file_identity
from kurtshape.snapshots import SnapshotKey, SnapshotStore
from kurtshape.step_export_worker import NativeStepExportWorker, world_fingerprints, _artifact_info, _export_document
from native_validation_snapshot import snapshot_document, placement_record
from test_borrowed_preview import BorrowedPreviewTests


class StepExportWorkerLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.folder = support.scratch(self, prefix="step-export-worker-lifetime-")
        self.store = SnapshotStore(self.folder / "accepted-export-archives")
        self.addCleanup(self.store.close)
        self.source = self.folder / "accepted-source.FCStd"
        self.source.write_bytes(b"immutable native archive fixture")
        self.key = SnapshotKey("instance", "revision", 3, 7)
        self.assertTrue(self.store.publish(self.key, self.source))
        self.worker = NativeStepExportWorker("private-native-python", self.folder, timeout=.05)
        self.addCleanup(self.cleanup_worker)

    def cleanup_worker(self):
        self.worker.close()
        self.assertTrue(self.worker.cleanup_complete.wait(5), "STEP cleanup did not confirm exit")

    def borrow(self):
        lease = self.store.try_acquire(self.key)
        self.assertIsNotNone(lease)
        self.worker.borrow_snapshot(lease)
        self.store.close()
        return lease

    def process(self):
        process = self.worker.process = Mock()
        process.stdin = io.BytesIO()
        process.wait.return_value = 0
        self.worker.active = 1
        self.worker.started = time.monotonic()
        self.worker._envelope = {"snapshot_key": asdict(self.key)}
        return process

    def test_published_result_waits_for_successful_exit_and_artifact_survives_poll(self):
        lease = self.borrow()
        process = self.process()
        process.poll.return_value = None
        artifact = self.worker.folder / "export.step"
        artifact.write_bytes(b"private completed STEP bytes")
        response = dict(self.worker._envelope, task=self.worker.token, sequence=1, ok=True,
                        artifact=_artifact_info(artifact))
        (self.worker.folder / "result-1.json").write_text(json.dumps(response), encoding="utf-8")
        self.assertIsNone(self.worker.poll(), "A result file is not proof of child exit")
        self.assertEqual(self.worker.active, 1)
        self.assertIsNotNone(lease._record)
        process.poll.return_value = 0
        self.assertEqual(self.worker.poll(), response)
        self.assertEqual(self.worker.validated_artifact(response), artifact)
        self.assertIsNone(self.worker.poll())
        self.assertTrue(artifact.is_file())
        self.assertTrue(lease.path.is_file())
        self.worker.close()
        self.assertTrue(self.worker.cleanup_complete.wait(2))
        self.assertFalse(artifact.exists())
        self.assertIsNone(lease._record)
        self.assertEqual(self.source.read_bytes(), b"immutable native archive fixture")

    def test_nonzero_exit_never_delivers_existing_result(self):
        self.borrow()
        process = self.process()
        process.poll.return_value = 1
        (self.worker.folder / "result-1.json").write_text(json.dumps({"task": self.worker.token, "sequence": 1}), encoding="utf-8")
        with self.assertRaises(RuntimeError):
            self.worker.poll()
        self.assertIsNone(self.worker._completed_response)

    def test_start_failure_releases_exactly_once(self):
        lease = self.borrow()
        with patch.object(lease, "release", wraps=lease.release) as release, \
                patch("kurtshape.step_export_worker.subprocess.Popen", side_effect=OSError("Cannot launch STEP worker")):
            with self.assertRaisesRegex(OSError, "Cannot launch"):
                self.worker.start()
            self.worker.close()
            self.assertTrue(self.worker.cleanup_complete.wait(2))
            release.assert_called_once()
        self.assertFalse(lease.path.exists())
        self.assertFalse(self.worker.folder.exists())

    def test_cancel_before_start_releases_once_without_launching(self):
        lease = self.borrow()
        with patch.object(lease, "release", wraps=lease.release) as release, \
                patch("kurtshape.step_export_worker.subprocess.Popen") as launch:
            self.worker.close()
            self.worker.close()
            self.assertTrue(self.worker.cleanup_complete.wait(2))
            release.assert_called_once()
            launch.assert_not_called()
        self.assertFalse(lease.path.exists())
        self.assertEqual(self.source.read_bytes(), b"immutable native archive fixture")

    def test_tampered_snapshot_fails_before_launch(self):
        lease = self.borrow()
        lease.path.write_bytes(b"changed captured archive")
        with patch("kurtshape.step_export_worker.subprocess.Popen") as launch:
            with self.assertRaisesRegex(RuntimeError, "changed"):
                self.worker.start()
            launch.assert_not_called()
        self.assertTrue(self.worker.cleanup_complete.wait(2))
        self.assertIsNone(lease._record)

    def test_repeated_wait_timeouts_retain_lease_until_confirmed_exit(self):
        lease = self.borrow()
        process = self.process()
        process.kill.side_effect = OSError("Busy native handle")
        waiting, release_exit = threading.Event(), threading.Event()
        self.addCleanup(release_exit.set)
        attempts = []
        def wait(timeout):
            attempts.append(timeout)
            if len(attempts) <= 2:
                raise subprocess.TimeoutExpired("owned STEP process", timeout)
            waiting.set()
            if not release_exit.wait(3):
                raise subprocess.TimeoutExpired("owned STEP process", timeout)
            return 0
        process.wait.side_effect = wait
        self.worker.close()
        self.assertTrue(waiting.wait(2))
        self.worker.close()
        self.assertFalse(self.worker.cleanup_complete.is_set())
        self.assertIsNotNone(lease._record)
        self.assertTrue(lease.path.is_file())
        self.assertTrue(self.worker.folder.is_dir())
        release_exit.set()
        self.assertTrue(self.worker.cleanup_complete.wait(2))
        self.assertIsNone(lease._record)
        self.assertFalse(lease.path.exists())
        self.assertTrue(process.stdin.closed)

    def test_timeout_does_not_release_running_child_lease(self):
        lease = self.borrow()
        process = self.process()
        process.poll.return_value = None
        self.worker.started = time.monotonic() - 2
        with self.assertRaises(TimeoutError):
            self.worker.poll()
        self.assertTrue(lease.path.is_file())
        self.assertIsNotNone(lease._record)
        self.worker.close()
        self.assertTrue(self.worker.cleanup_complete.wait(2))
        self.assertIsNone(lease._record)


class StepExportJobTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="step-export-job-")
        self.core = Controller()
        self.workers = []
        self.state = None
        self.call("new", name="Native STEP export jobs")

    def tearDown(self):
        for worker in self.workers:
            worker.close()
            self.assertTrue(worker.cleanup_complete.wait(15), "Owned STEP child did not exit")
        self.core.close()
        for name in set(App.listDocuments()) - self.names:
            App.closeDocument(name)

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def call(self, op, **arguments):
        request = dict(op=op, measure=False, **arguments)
        if op not in self.core.CREATE_OPS | {"capabilities", "request_status"}:
            request.update(document_id=self.state["document_id"], expected_revision=self.state["revision"])
        response = self.core.dispatch(request)
        self.assertTrue(response["ok"], response)
        if "document_id" in response["result"]:
            self.state = response["result"]
        return response["result"]

    def plate(self):
        self.call("sketch_rectangle", id="Plate", width=20, height=10)
        self.call("pad", id="Pad", profile="Plate", length=6)
        return self.doc.Body

    def stable_result(self):
        obj = self.doc.addObject("Part::Feature", "ExportSolid")
        obj.Shape = Part.makeBox(20, 10, 6)
        self.doc.recompute()
        self.core.sync(self.doc)
        self.state = self.core.inspect(self.doc, measure=False)
        return obj

    def mutate_result(self):
        self.doc.ExportSolid.Shape = Part.makeBox(20, 10, 9)
        self.doc.recompute()

    def invalid_solid(self, *, diagonal=False):
        points = ([(0, 0), (10, 10), (0, 10), (10, 0), (0, 0)] if diagonal else
                  [(0, 0), (10, 0), (10, 10), (5, 10), (5, -5), (0, -5), (0, 0)])
        shape = Part.Face(Part.makePolygon([App.Vector(x, y, 0) for x, y in points])).extrude(App.Vector(0, 0, 5))
        self.assertEqual(len(shape.Solids), 1)
        self.assertFalse(shape.isValid(), "This fixture must be genuinely invalid native topology")
        obj = self.doc.addObject("Part::Feature", "DiagonalBowTie" if diagonal else "OrthogonalCrossing")
        obj.Shape = shape
        self.doc.recompute()
        self.core.sync(self.doc)
        self.state = self.core.inspect(self.doc, measure=False)
        return obj

    def invariant(self):
        return (snapshot_document(self.doc, self.core)["strict"], BorrowedPreviewTests.native_shapes(self.doc),
                dict(self.core.documents))

    def worker(self):
        executable = Path(App.getHomePath()) / "bin" / ("python.exe" if os.name == "nt" else "python")
        worker = NativeStepExportWorker(executable, self.folder, timeout=30)
        self.workers.append(worker)
        return worker

    def prepare(self, name="accepted.step", body=None):
        bundle = self.core.prepare_step_export(self.doc, str(self.folder / name), body=body,
            worker_factory=lambda *args, **kwargs: self.worker())
        self.assertIsNotNone(bundle, "A stable local solid must prepare a private STEP job")
        self.assertIsNone(bundle["worker"].process, "Capture must not launch the child")
        return bundle

    def reply(self, worker):
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            result = worker.poll()
            if result is not None:
                json.dumps(result, allow_nan=False)
                self.assertEqual(worker.process.poll(), 0, "The parent may read STEP only after exit")
                return result
            time.sleep(.02)
        self.fail("Private native STEP worker exceeded its bounded timeout")

    def completed_transport(self, bundle):
        """Real native artifact with deterministic exited transport for parent fault injection."""
        worker = bundle["worker"]
        shape = Part.makeCompound([assembly.global_shape(obj).copy() for obj in bundle["targets"]])
        artifact = worker.folder / "export.step"
        shape.exportStep(str(artifact))
        checks = [dict(geometry.check_shape(assembly.global_shape(obj).copy()), id=obj.Name) for obj in bundle["targets"]]
        response = dict(copy.deepcopy(bundle["envelope"]), task=worker.token, sequence=bundle["sequence"],
                        ok=True, checks=checks, measurements=copy.deepcopy(bundle["measurements"]),
                        engine=copy.deepcopy(bundle["provenance"]["engine"]), artifact=_artifact_info(artifact),
                        milliseconds=1.0, phase_milliseconds={}, export_work={})
        process = worker.process = Mock()
        process.stdin = io.BytesIO()
        process.poll.return_value = process.wait.return_value = 0
        worker.active, worker.started = bundle["sequence"], time.monotonic()
        worker._envelope = copy.deepcopy(bundle["envelope"])
        (worker.folder / ("result-" + str(worker.active) + ".json")).write_text(json.dumps(response), encoding="utf-8")
        self.assertEqual(worker.poll(), response)
        return response

    def assert_unpublished(self, bundle):
        self.assertFalse(bundle["destination"].exists())
        self.assertFalse(bundle["sidecar"].exists())
        self.assertFalse(bundle["published"])

    def assert_pair(self, bundle, provenance):
        self.assertEqual(json.loads(bundle["sidecar"].read_text(encoding="utf-8")), provenance)
        self.assertEqual(hashlib.sha256(bundle["destination"].read_bytes()).hexdigest(), provenance["sha256"])
        self.assertEqual(provenance["document_id"], self.core.identifier(self.doc))
        self.assertEqual(provenance["revision"], self.core._meta(self.doc).Revision)
        self.assertEqual(provenance["included_body_ids"], list(bundle["target_ids"]))
        self.assertEqual(provenance["geometry_check"]["status"], "valid")

    def assert_geometry_equal(self, first, second):
        self.assertEqual(len(first.Solids), len(second.Solids))
        self.assertAlmostEqual(first.Volume, second.Volume, places=7)
        for field in ("XMin", "YMin", "ZMin", "XMax", "YMax", "ZMax"):
            self.assertAlmostEqual(getattr(first.BoundBox, field), getattr(second.BoundBox, field), places=7)

    def test_actual_unsaved_moved_world_export_matches_sync_and_preserves_source(self):
        body = self.stable_result()
        body.Placement = App.Placement(App.Vector(7, 11, 13), App.Rotation())
        self.doc.recompute()
        self.core.sync(self.doc)
        self.state = self.core.inspect(self.doc, measure=False)
        oracle = self.folder / "synchronous-oracle.step"
        self.core._export(self.doc, str(oracle))
        before = self.invariant()
        bundle = self.prepare()
        self.assertEqual(bundle["target_ids"], (body.Name,))
        self.assertFalse(bundle["snapshot_reused"])
        worker = bundle["worker"]
        archive = worker.snapshot.read_bytes()
        worker.submit(bundle["sequence"], bundle["envelope"])
        response = self.reply(worker)
        self.assertTrue(response["ok"], response)
        provenance = self.core.accept_step_export(self.doc, bundle, response)
        self.assertIsNotNone(provenance)
        self.assert_pair(bundle, provenance)
        self.assertIsNone(provenance["native_file"])
        self.assert_geometry_equal(Part.read(str(bundle["destination"])), Part.read(str(oracle)))
        self.assert_geometry_equal(Part.read(str(bundle["destination"])), assembly.global_shape(body).copy())
        self.assertEqual(self.invariant(), before)
        self.assertEqual(worker.snapshot.read_bytes(), archive)
        self.assertTrue((worker.folder / "export.step").is_file())
        self.assertIsNone(self.core.accept_step_export(self.doc, bundle, response), "Publication is one-shot")
        worker.close()
        self.assertTrue(worker.cleanup_complete.wait(10))
        self.assertTrue(bundle["destination"].is_file())

    def test_actual_saved_selected_body_reuses_exact_lease_and_keeps_original_provenance(self):
        body = self.plate()
        body.Placement = App.Placement(App.Vector(7, 11, 13), App.Rotation())
        self.doc.addObject("Part::Feature", "ExcludedResult").Shape = Part.makeBox(2, 3, 4, App.Vector(50, 0, 0))
        self.doc.recompute()
        self.core.sync(self.doc)
        self.state = self.core.inspect(self.doc, measure=False)
        saved = self.folder / "authored-project.FCStd"
        self.call("save", path=str(saved))
        saved_bytes = saved.read_bytes()
        App.closeDocument(self.doc.Name)
        self.call("open", path=str(saved))
        oracle = self.folder / "synchronous-selected-body.step"
        self.core._export(self.doc, str(oracle), body_id="Body")
        self.assertIsNotNone(self.core.checkpoint(self.doc))
        key = self.core.snapshot_key(self.doc)
        lease = self.core.snapshots.try_acquire(key)
        self.assertIsNotNone(lease)
        path, archive = lease.path, lease.path.read_bytes()
        lease.release()
        before = self.invariant()
        bundle = self.prepare("accepted.stp", body="Body")
        self.assertEqual(bundle["target_ids"], ("Body",))
        self.assertTrue(bundle["snapshot_reused"])
        worker = bundle["worker"]
        self.assertEqual(worker.snapshot, path)
        worker.submit(bundle["sequence"], bundle["envelope"])
        response = self.reply(worker)
        self.assertTrue(response["ok"], response)
        provenance = self.core.accept_step_export(self.doc, bundle, response)
        self.assert_pair(bundle, provenance)
        self.assertEqual(Path(provenance["native_file"]), saved)
        self.assertEqual(provenance["format"], ".stp")
        self.assert_geometry_equal(Part.read(str(bundle["destination"])), assembly.global_shape(self.doc.Body).copy())
        self.assert_geometry_equal(Part.read(str(bundle["destination"])), Part.read(str(oracle)))
        self.assertEqual(saved.read_bytes(), saved_bytes)
        self.assertEqual(path.read_bytes(), archive)
        self.assertEqual(self.invariant(), before)
        self.core.snapshots.retire_document(key.instance_id)
        self.assertTrue(path.exists())
        worker.close()
        self.assertTrue(worker.cleanup_complete.wait(10))
        self.assertFalse(path.exists())
        self.assertEqual(saved.read_bytes(), saved_bytes)
        self.doc.Body.Placement = App.Placement(App.Vector(19, 23, 29), App.Rotation())
        self.doc.recompute()
        self.core.sync(self.doc)
        moved = self.invariant()
        factory = Mock(side_effect=AssertionError("Moving a reopened Body must not silently rewrite it to qualify"))
        self.assertIsNone(self.core.prepare_step_export(self.doc, str(self.folder / "moved-reopened-body.step"),
                                                      worker_factory=factory))
        factory.assert_not_called()
        self.assertEqual(self.invariant(), moved)
        self.assertEqual(saved.read_bytes(), saved_bytes)

    def test_actual_reopened_imported_export_preserves_import_and_saved_provenance(self):
        imported = self.folder / "external-authored-source.step"
        shape = Part.makeBox(3, 4, 5, App.Vector(2, 6, 10))
        shape.exportStep(str(imported))
        original = imported.read_bytes()
        self.call("import_step", path=str(imported))
        import_source = json.loads(self.core._meta(self.doc).ImportSource)
        saved = self.folder / "saved-import.FCStd"
        self.call("save", path=str(saved))
        saved_bytes = saved.read_bytes()
        App.closeDocument(self.doc.Name)
        self.call("open", path=str(saved))
        before = self.invariant()
        bundle = self.prepare()
        worker = bundle["worker"]
        archive = worker.snapshot.read_bytes()
        worker.submit(bundle["sequence"], bundle["envelope"])
        response = self.reply(worker)
        self.assertTrue(response["ok"], response)
        provenance = self.core.accept_step_export(self.doc, bundle, response)
        self.assert_pair(bundle, provenance)
        self.assertEqual(provenance["import_source"], import_source)
        self.assertEqual(Path(provenance["native_file"]), saved)
        self.assert_geometry_equal(Part.read(str(bundle["destination"])), shape)
        self.assertEqual(imported.read_bytes(), original)
        self.assertEqual(saved.read_bytes(), saved_bytes)
        self.assertEqual(worker.snapshot.read_bytes(), archive)
        self.assertEqual(self.invariant(), before)

    def test_actual_invalid_and_numeric_incompatible_archives_never_publish(self):
        for diagonal in (False, True):
            with self.subTest(diagonal=diagonal):
                if diagonal:
                    self.call("new", name="Diagonal archive rejection")
                obj = self.invalid_solid(diagonal=diagonal)
                before = self.invariant()
                authored = native_intent(self.doc)
                oracle_state = oracle_snapshot = oracle_check = oracle_error = None
                if not diagonal:
                    # Compare the real synchronous error outcome in this same
                    # document, then reset only derived checks. No strict
                    # snapshot field is omitted to make the comparison pass.
                    with self.assertRaises(OperationError) as synchronous:
                        self.core._export(self.doc, str(self.folder / "invalid-synchronous-oracle.step"))
                    self.assertEqual(synchronous.exception.code, "invalid_geometry")
                    oracle_error = synchronous.exception
                    oracle_state = self.core.inspect(self.doc, measure=False)
                    oracle_snapshot = self.invariant()
                    oracle_check = self.core.geometry.check(obj)
                    self.assertEqual(oracle_state["build_status"], "failed")
                    self.assertEqual(oracle_state["geometry_check"], "invalid")
                    self.assertFalse(oracle_check["valid"])
                    self.core.geometry.drop_document(self.doc)
                    self.core._build_status(self.doc)
                    self.assertEqual(self.core._meta(self.doc).BuildStatus, "valid")
                    self.assertEqual(self.invariant(), before, "Derived-only oracle reset must preserve every native field")
                if diagonal:
                    # Deliberately exercise the child's independent exact
                    # proof even though parent admission selects sync fallback.
                    factory = Mock(side_effect=AssertionError("Unstable input must not allocate a child"))
                    self.assertIsNone(self.core.prepare_step_export(self.doc, str(self.folder / "diagonal.step"),
                                                                  body=obj.Name, worker_factory=factory))
                    factory.assert_not_called()
                    worker = self.worker()
                    self.doc.saveCopy(str(worker.snapshot))
                    key = self.core.snapshot_key(self.doc)
                    worker.own_snapshot(key, _snapshot_file_identity(worker.snapshot))
                    bundle = {"worker": worker, "sequence": 1, "published": False,
                              "destination": self.folder / "diagonal.step", "sidecar": self.folder / "diagonal.step.json",
                              "envelope": {"snapshot_key": asdict(key), "document_id": self.core.identifier(self.doc),
                                           "target_ids": [obj.Name], "target_fingerprints": world_fingerprints(self.doc, [obj.Name]),
                                           "format": ".step", "settings": {"writer": "FreeCAD Part/OCCT"}}}
                else:
                    bundle = self.prepare("invalid.step", body=obj.Name)
                worker = bundle["worker"]
                archive = worker.snapshot.read_bytes()
                worker.submit(bundle["sequence"], bundle["envelope"])
                response = self.reply(worker)
                self.assertFalse(response["ok"], response)
                expected = "step_export_snapshot_incompatible" if diagonal else "invalid_geometry"
                self.assertEqual(response["error"]["code"], expected)
                if not diagonal:
                    self.assertFalse(response["checks"][0]["valid"])
                    self.assertTrue(response["checks"][0]["issues"])
                if not diagonal:
                    with self.assertRaises(OperationError) as failed:
                        self.core.accept_step_export(self.doc, bundle, response)
                    self.assertEqual(failed.exception.code, expected)
                    self.assertEqual(str(failed.exception), str(oracle_error))
                    self.assertEqual(failed.exception.details["features"], oracle_error.details["features"])
                    self.assertEqual(self.core.inspect(self.doc, measure=False), oracle_state)
                    self.assertEqual(bundle["invalid_state"], oracle_state)
                    self.assertEqual(self.invariant(), oracle_snapshot)
                    actual_check = self.core.geometry.check(obj)
                    self.assertEqual((actual_check["valid"], actual_check["issues"]),
                                     (oracle_check["valid"], oracle_check["issues"]))
                    self.assertTrue(math.isfinite(actual_check["ms"]) and actual_check["ms"] >= 0)
                self.assert_unpublished(bundle)
                self.assertFalse((worker.folder / "export.step").exists())
                self.assertEqual(worker.snapshot.read_bytes(), archive)
                self.assertEqual(native_intent(self.doc), authored)
                self.assertEqual(self.invariant(), before)

    def test_child_attachment_and_changed_world_geometry_fail_before_export(self):
        self.stable_result()
        bundle = self.prepare()
        worker = bundle["worker"]
        before, archive = self.invariant(), worker.snapshot.read_bytes()
        from kurtshape.preview_worker import _attach_preview_document
        for boundary in ("refused", "changed"):
            with self.subTest(boundary=boundary):
                other = Controller()
                clone = App.newDocument("STEPAttachmentProof", hidden=True, temp=True)
                try:
                    clone.load(str(worker.snapshot))
                    def attach(*args):
                        if boundary == "refused":
                            return None
                        result = _attach_preview_document(*args)
                        self.assertIsNotNone(result)
                        clone.ExportSolid.Placement = App.Placement(App.Vector(5, 0, 0), App.Rotation())
                        clone.recompute()
                        self.assertNotEqual(world_fingerprints(clone, ["ExportSolid"]), bundle["envelope"]["target_fingerprints"])
                        return result
                    with patch("kurtshape.preview_worker._attach_preview_document", side_effect=attach) as attached, \
                            patch.object(geometry, "check_shape") as check:
                        with self.assertRaises(OperationError) as failed:
                            _export_document(other, clone, worker.snapshot, _snapshot_file_identity(worker.snapshot),
                                             bundle["envelope"], worker.folder, {}, {})
                        self.assertEqual(failed.exception.code, "step_export_snapshot_incompatible")
                        attached.assert_called_once()
                        check.assert_not_called()
                    self.assertFalse((worker.folder / "export.step").exists())
                finally:
                    other.close()
                    App.closeDocument(clone.Name)
                    App.setActiveDocument(self.doc.Name)
                self.assertEqual(self.invariant(), before)
                self.assertEqual(worker.snapshot.read_bytes(), archive)

    def test_invalid_verdict_rollback_status_failure_releases_busy_and_discards_receipt(self):
        obj = self.invalid_solid()
        bundle = self.prepare(body=obj.Name)
        worker = bundle["worker"]
        check = dict(geometry.check_shape(obj.Shape.copy()), id=obj.Name)
        self.assertFalse(check["valid"])
        response = dict(copy.deepcopy(bundle["envelope"]), task=worker.token, sequence=bundle["sequence"],
                        ok=False, checks=[check], milliseconds=1.0, engine=copy.deepcopy(bundle["provenance"]["engine"]),
                        error={"code": "invalid_geometry", "message": "Geometry check failed; nothing was exported",
                               "features": [{"feature": obj.Name, "issues": check["issues"]}]})
        worker.process = Mock()
        worker.process.stdin = io.BytesIO()
        worker.process.poll.return_value = worker.process.wait.return_value = 0
        worker._completed_response = copy.deepcopy(response)
        imported = []
        original_status = self.core._build_status
        def status(doc, *args, **kwargs):
            cached = self.core.geometry.check(obj)
            if imported and cached is None:
                raise RuntimeError("Injected rollback status failure")
            value = original_status(doc, *args, **kwargs)
            if cached is not None:
                imported.append(True)
            return value
        def current():
            # Reject only after a real invalid verdict was actually imported.
            return not imported
        with patch.object(self.core, "_build_status", side_effect=status):
            with self.assertRaisesRegex(OperationError, "Injected rollback status failure"):
                self.core.accept_step_export(self.doc, bundle, response, is_current=current)
        self.assertTrue(imported)
        self.assertFalse(self.core.busy)
        self.assertIsNone(self.core.geometry.check(obj))
        self.assertNotIn(bundle["topology_keys"][0], self.core.geometry._checks)
        self.assertNotIn("invalid_state", bundle)
        self.assert_unpublished(bundle)

    def test_every_snapshot_key_field_rejects_stale_publication(self):
        self.stable_result()
        bundle = self.prepare()
        response = self.completed_transport(bundle)
        key = bundle["snapshot_key"]
        changes = {"instance_id": "other-instance", "revision": "other-revision", "generation": key.generation + 1,
                   "serial": key.serial + 1, "policy": "other-policy"}
        for field, value in changes.items():
            with self.subTest(field=field), patch.object(self.core, "snapshot_key", return_value=replace(key, **{field: value})):
                self.assertIsNone(self.core.accept_step_export(self.doc, bundle, response))
                self.assert_unpublished(bundle)

    def test_actual_topology_placement_and_membership_changes_reject_even_with_old_key(self):
        for mutation in ("topology", "placement", "membership"):
            with self.subTest(mutation=mutation):
                self.call("new", name="Independent stale STEP " + mutation)
                body = self.stable_result()
                bundle = self.prepare(mutation + ".step")
                response = self.completed_transport(bundle)
                if mutation == "topology":
                    self.mutate_result()
                elif mutation == "placement":
                    body.Placement = App.Placement(App.Vector(3, 4, 5), App.Rotation())
                else:
                    self.doc.addObject("Part::Feature", "AdditionalResult").Shape = Part.makeBox(2, 3, 4, App.Vector(30, 0, 0))
                self.doc.recompute()
                self.core.sync(self.doc)
                with patch.object(self.core, "snapshot_key", return_value=bundle["snapshot_key"]):
                    self.assertIsNone(self.core.accept_step_export(self.doc, bundle, response))
                self.assert_unpublished(bundle)

    def test_foreign_document_cancellation_owner_and_closed_worker_reject(self):
        self.stable_result()
        bundle = self.prepare()
        response = self.completed_transport(bundle)
        other = App.newDocument("ForeignSTEPJob")
        self.assertIsNone(self.core.accept_step_export(other, bundle, response))
        self.assertIsNone(self.core.accept_step_export(self.doc, bundle, response, is_current=lambda: False))
        self.assertIsNone(self.core.accept_step_export(self.doc, bundle, response, owns_job=lambda: False))
        bundle["worker"].close()
        self.assertTrue(bundle["worker"].cleanup_complete.wait(5))
        self.assertIsNone(self.core.accept_step_export(self.doc, bundle, response))
        self.assert_unpublished(bundle)

    def test_same_document_mutation_in_final_callback_cannot_publish(self):
        self.stable_result()
        bundle = self.prepare()
        response = self.completed_transport(bundle)
        calls = []
        def current():
            calls.append(True)
            if len(calls) == 2:
                self.mutate_result()
            return True
        self.assertIsNone(self.core.accept_step_export(self.doc, bundle, response, is_current=current))
        self.assertEqual(len(calls), 2)
        self.assert_unpublished(bundle)

    def test_explicit_save_rejects_old_provenance_even_with_same_key(self):
        self.stable_result()
        bundle = self.prepare()
        response = self.completed_transport(bundle)
        self.call("save", path=str(self.folder / "new-authored-location.FCStd"))
        self.assertTrue(self.doc.FileName)
        with patch.object(self.core, "snapshot_key", return_value=bundle["snapshot_key"]):
            self.assertIsNone(self.core.accept_step_export(self.doc, bundle, response))
        self.assert_unpublished(bundle)

    def test_document_close_rejects_completed_result(self):
        self.stable_result()
        bundle = self.prepare()
        response = self.completed_transport(bundle)
        original = self.doc
        App.closeDocument(original.Name)
        self.assertIsNone(self.core.accept_step_export(original, bundle, response))
        self.assert_unpublished(bundle)

    def test_changed_destination_or_sidecar_preserves_intervening_bytes(self):
        self.stable_result()
        for suffix in ("geometry", "sidecar"):
            with self.subTest(suffix=suffix):
                bundle = self.prepare(suffix + ".step")
                response = self.completed_transport(bundle)
                target = bundle["destination"] if suffix == "geometry" else bundle["sidecar"]
                target.write_bytes(b"another writer owns these bytes")
                self.assertIsNone(self.core.accept_step_export(self.doc, bundle, response))
                self.assertEqual(target.read_bytes(), b"another writer owns these bytes")
                self.assertFalse(bundle["published"])

    def test_malformed_identity_targets_checks_measurements_and_nonfinite_response_reject(self):
        self.stable_result()
        bundle = self.prepare()
        response = self.completed_transport(bundle)
        changes = {"task": "other", "sequence": 8, "document_id": "other", "target_ids": [],
                   "snapshot_key": {}, "target_fingerprints": [], "format": ".stl", "settings": {},
                   "checks": [], "measurements": {}, "engine": {}, "milliseconds": float("nan")}
        for field, value in changes.items():
            with self.subTest(field=field):
                changed = dict(response, **{field: value})
                with self.assertRaises(OperationError):
                    self.core.accept_step_export(self.doc, bundle, changed)
                self.assert_unpublished(bundle)
        for value in (False, -1, float("inf")):
            changed = copy.deepcopy(response)
            changed["checks"][0]["ms"] = value
            with self.subTest(check_ms=value), self.assertRaises(OperationError):
                self.core.accept_step_export(self.doc, bundle, changed)
            self.assert_unpublished(bundle)

    def test_artifact_path_escape_wrong_digest_and_changed_bytes_reject(self):
        self.stable_result()
        bundle = self.prepare()
        response = self.completed_transport(bundle)
        worker = bundle["worker"]
        sentinel = self.folder / "untouched.step"
        sentinel.write_bytes(b"outside private artifact")
        for field, value in (("name", "../untouched.step"), ("name", str(sentinel)),
                             ("sha256", "0" * 64), ("size", 1), ("identity", [0, 0, 1, 0])):
            with self.subTest(field=field, value=value):
                changed = copy.deepcopy(response)
                changed["artifact"][field] = value
                worker._completed_response = copy.deepcopy(changed)
                with self.assertRaises(OperationError):
                    self.core.accept_step_export(self.doc, bundle, changed)
                self.assert_unpublished(bundle)
                self.assertEqual(sentinel.read_bytes(), b"outside private artifact")
        worker._completed_response = copy.deepcopy(response)
        with (worker.folder / "export.step").open("ab") as stream:
            stream.write(b"tamper")
        with self.assertRaises(OperationError):
            self.core.accept_step_export(self.doc, bundle, response)
        self.assert_unpublished(bundle)

    def test_second_replace_failure_restores_existing_and_absent_pairs(self):
        self.stable_result()
        for existing in (False, True):
            with self.subTest(existing=existing):
                name = "existing.step" if existing else "absent.step"
                path = self.folder / name
                sidecar = path.with_suffix(path.suffix + ".json")
                if existing:
                    path.write_bytes(b"previous geometry")
                    sidecar.write_bytes(b"previous provenance")
                bundle = self.prepare(name)
                response = self.completed_transport(bundle)
                original = os.replace
                def fail_second(source, target):
                    if Path(target) == sidecar:
                        raise OSError("Injected second replacement failure")
                    return original(source, target)
                with patch("kurtshape.core.os.replace", side_effect=fail_second):
                    with self.assertRaises(OperationError) as failed:
                        self.core.accept_step_export(self.doc, bundle, response)
                self.assertEqual(failed.exception.code, "export_failed")
                self.assertFalse(bundle["published"])
                self.assertEqual(list(self.folder.glob("*.step-job-*.stage")), [])
                if existing:
                    self.assertEqual(path.read_bytes(), b"previous geometry")
                    self.assertEqual(sidecar.read_bytes(), b"previous provenance")
                else:
                    self.assert_unpublished(bundle)

    def test_rollback_failure_preserves_recovery_geometry(self):
        self.stable_result()
        path = self.folder / "accepted.step"
        sidecar = path.with_suffix(path.suffix + ".json")
        path.write_bytes(b"previous geometry")
        sidecar.write_bytes(b"previous provenance")
        bundle = self.prepare()
        response = self.completed_transport(bundle)
        original = os.replace
        def fail_commit_and_restore(source, target):
            if Path(target) == sidecar or Path(source).name.endswith(".recovery"):
                raise OSError("Injected commit and recovery failure")
            return original(source, target)
        with patch("kurtshape.core.os.replace", side_effect=fail_commit_and_restore):
            with self.assertRaises(OperationError) as failed:
                self.core.accept_step_export(self.doc, bundle, response)
        self.assertEqual(failed.exception.code, "export_recovery_required")
        self.assertEqual(path.with_name(path.name + ".recovery").read_bytes(), b"previous geometry")
        self.assertEqual(sidecar.read_bytes(), b"previous provenance")
        self.assertTrue(failed.exception.details["staged_files"])
        for stage in failed.exception.details["staged_files"]:
            self.assertTrue(Path(stage).is_file())
        self.assertTrue(any(Path(stage).read_bytes().startswith(b"{")
                            for stage in failed.exception.details["staged_files"]))
        self.assertFalse(bundle["published"])

    def test_native_change_during_first_replace_rolls_back_complete_pair(self):
        self.stable_result()
        path = self.folder / "accepted.step"
        sidecar = path.with_suffix(path.suffix + ".json")
        path.write_bytes(b"previous geometry")
        sidecar.write_bytes(b"previous provenance")
        bundle = self.prepare()
        response = self.completed_transport(bundle)
        original, changed = os.replace, []
        def replace_and_change(source, target):
            result = original(source, target)
            if Path(target) == path and not changed:
                changed.append(True)
                self.mutate_result()
            return result
        with patch("kurtshape.core.os.replace", side_effect=replace_and_change):
            with self.assertRaises(OperationError) as failed:
                self.core.accept_step_export(self.doc, bundle, response)
        self.assertEqual(failed.exception.code, "export_failed")
        self.assertEqual(changed, [True])
        self.assertEqual(path.read_bytes(), b"previous geometry")
        self.assertEqual(sidecar.read_bytes(), b"previous provenance")
        self.assertFalse(bundle["published"])

    def test_fresh_pad_and_unsaved_import_use_exact_synchronous_fallback(self):
        for kind in ("fresh-pad", "unsaved-import"):
            with self.subTest(kind=kind):
                if kind == "fresh-pad":
                    self.plate()
                    expected_import = None
                else:
                    source = self.folder / "fresh-import-source.step"
                    Part.makeBox(3, 4, 5, App.Vector(2, 6, 10)).exportStep(str(source))
                    source_bytes = source.read_bytes()
                    self.call("import_step", path=str(source))
                    expected_import = json.loads(self.core._meta(self.doc).ImportSource)
                before = self.invariant()
                expected_shape = assembly.global_shape(self.doc.Body).copy()
                path = self.folder / (kind + ".step")
                factory = Mock(side_effect=AssertionError("Inexact native roundtrip must use the synchronous oracle"))
                self.assertIsNone(self.core.prepare_step_export(self.doc, str(path), worker_factory=factory))
                factory.assert_not_called()
                self.assertFalse(path.exists())
                self.core._export(self.doc, str(path))
                provenance = json.loads(path.with_suffix(".step.json").read_text(encoding="utf-8"))
                self.assertEqual(provenance["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
                self.assertEqual(provenance["import_source"], expected_import)
                self.assertIsNone(provenance["native_file"])
                self.assert_geometry_equal(Part.read(str(path)), expected_shape)
                self.assertEqual(self.invariant(), before)
                if kind == "unsaved-import":
                    self.assertEqual(source.read_bytes(), source_bytes)

    def test_injected_target_enumeration_rejects_real_scaled_local_link_before_capture(self):
        source = self.doc.addObject("Part::Feature", "ExportSolid")
        source.Shape = Part.makeBox(20, 10, 6)
        link = self.doc.addObject("App::Link", "ScaledLocalOccurrence")
        link.setLink(source)
        link.Scale = 2.0
        self.doc.recompute()
        self.core.sync(self.doc)
        self.assertIn("Touched", self.core._meta(self.doc).State,
                      "The metadata admission guard must not mask the Link guard under test")
        self.assertIs(geometry.source_of(link), source)
        self.assertEqual(self.core.geometry.check_key(link), self.core.geometry.check_key(source))
        self.assertAlmostEqual(link.Shape.Volume, source.Shape.Volume * 8)
        def link_source_snapshot():
            shapes = []
            for obj in (source, link):
                shape = obj.Shape
                shapes.append({"id": obj.Name, "type": obj.TypeId,
                               "placement": placement_record(obj.Placement),
                               "shape_placement": placement_record(shape.Placement),
                               "brep": shape.exportBrepToString(),
                               "map": dict(shape.ElementMap), "reverse_map": dict(shape.ElementReverseMap),
                               "map_version": shape.ElementMapVersion, "map_size": shape.ElementMapSize})
            return (native_intent(self.doc), shapes, self.core._meta(self.doc).Revision,
                    self.doc.FileName, self.doc.UndoCount, self.doc.RedoCount,
                    list(self.doc.UndoNames), list(self.doc.RedoNames), bool(self.doc.HasPendingTransaction))
        before = link_source_snapshot()
        factory = Mock(side_effect=AssertionError("A scaled linked source must not allocate a worker"))
        # Ordinary native results exclude a bare App::Link. Inject only its
        # enumeration to exercise the defensive admission boundary with real
        # linked/scaled native topology, without claiming Studio integration.
        with patch.object(self.core, "_geometry_check_targets", return_value=[link]), \
                patch("kurtshape.step_export_worker.world_roundtrip_stable",
                      side_effect=AssertionError("Link guard must precede geometry eligibility work")), \
                patch("kurtshape.step_capture.roundtrip_digest",
                      side_effect=AssertionError("Link guard must precede geometry eligibility work")):
            self.assertIsNone(self.core.prepare_step_export(self.doc, str(self.folder / "linked-result.step"),
                                                          worker_factory=factory))
        factory.assert_not_called()
        self.assertEqual(link_source_snapshot(), before)

    def test_clean_metadata_after_native_edit_falls_back_and_child_retains_exact_attachment_rejection(self):
        obj = self.doc.addObject("Part::Feature", "EditedStandaloneSolid")
        obj.Shape = Part.makeBox(20, 12, 8)
        self.doc.recompute()
        self.core.sync(self.doc)
        self.state = self.core.inspect(self.doc, measure=False)
        self.assertIn("Touched", self.core._meta(self.doc).State)
        # Even an otherwise unchanged native recompute may clear the metadata
        # flag required by strict attachment equivalence. Never touch or rewrite
        # the source to qualify it for a child.
        unchanged_brep = obj.Shape.exportBrepToString()
        self.doc.recompute()
        self.core.sync(self.doc)
        self.assertNotIn("Touched", self.core._meta(self.doc).State)
        self.assertEqual(obj.Shape.exportBrepToString(), unchanged_brep)
        factory = Mock(side_effect=AssertionError("Clean metadata must fall back before worker allocation"))
        for edited in (False, True):
            with self.subTest(edited=edited):
                if edited:
                    obj.Shape = Part.makeBox(20, 12, 9)
                    self.doc.recompute()
                    self.core.sync(self.doc)
                self.assertNotIn("Touched", self.core._meta(self.doc).State)
                before = self.invariant()
                with patch("kurtshape.step_export_worker.world_roundtrip_stable",
                           side_effect=AssertionError("Metadata guard must precede roundtrip admission")), \
                patch("kurtshape.step_capture.roundtrip_digest",
                      side_effect=AssertionError("Metadata guard must precede roundtrip admission")):
                    self.assertIsNone(self.core.prepare_step_export(self.doc, str(self.folder / "clean-metadata.step"),
                                                                  worker_factory=factory))
                factory.assert_not_called()
                self.assertEqual(self.invariant(), before)
        # Bypass parent admission only to retain the independent child proof.
        # Its archive and original source remain exact; attachment must still
        # reject the derived metadata-flag difference, not normalize it away.
        worker = self.worker()
        self.doc.saveCopy(str(worker.snapshot))
        key = self.core.snapshot_key(self.doc)
        worker.own_snapshot(key, _snapshot_file_identity(worker.snapshot))
        envelope = {"snapshot_key": asdict(key), "document_id": self.core.identifier(self.doc),
                    "target_ids": [obj.Name], "target_fingerprints": world_fingerprints(self.doc, [obj.Name]),
                    "format": ".step", "settings": {"writer": "FreeCAD Part/OCCT"}}
        archive, before = worker.snapshot.read_bytes(), self.invariant()
        worker.submit(1, envelope)
        response = self.reply(worker)
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], "step_export_snapshot_incompatible")
        self.assertIn("Native attachment changed", response["error"]["message"])
        self.assertEqual(response["checks"], [])
        self.assertIsNone(response["artifact"])
        self.assertFalse((worker.folder / "export.step").exists())
        self.assertFalse((self.folder / "clean-metadata.step").exists())
        self.assertFalse((self.folder / "clean-metadata.step.json").exists())
        self.assertEqual(worker.snapshot.read_bytes(), archive)
        self.assertEqual(self.invariant(), before)
        destination = self.folder / "latest-edited-solid.step"
        self.core._export(self.doc, str(destination))
        exported = Part.read(str(destination))
        self.assert_geometry_equal(exported, obj.Shape.copy())
        self.assertEqual(len(exported.Solids), 1)
        self.assertAlmostEqual(exported.Volume, 20 * 12 * 9)
        self.assertAlmostEqual(exported.BoundBox.ZLength, 9)
        provenance = json.loads(destination.with_suffix(".step.json").read_text(encoding="utf-8"))
        self.assertEqual(provenance["sha256"], hashlib.sha256(destination.read_bytes()).hexdigest())
        self.assertEqual(provenance["document_id"], self.core.identifier(self.doc))
        self.assertEqual(provenance["revision"], key.revision)
        self.assertEqual(provenance["included_body_ids"], [obj.Name])
        self.assertIsNone(provenance["native_file"])
        self.assertIsNone(provenance["import_source"])
        self.assertAlmostEqual(provenance["shape"]["volume_mm3"], 20 * 12 * 9)
        self.assertEqual(provenance["shape"]["bbox_mm"]["size"], [20, 12, 9])
        self.assertEqual(worker.snapshot.read_bytes(), archive)
        self.assertEqual(self.invariant(), before)

    def test_stl_busy_and_no_solid_use_synchronous_fallback_without_worker(self):
        factory = Mock(side_effect=AssertionError("Fallback must not construct a child"))
        self.assertIsNone(self.core.prepare_step_export(self.doc, str(self.folder / "empty.step"), worker_factory=factory))
        self.plate()
        self.assertIsNone(self.core.prepare_step_export(self.doc, str(self.folder / "mesh.stl"), worker_factory=factory))
        self.core.busy = True
        try:
            self.assertIsNone(self.core.prepare_step_export(self.doc, str(self.folder / "busy.step"), worker_factory=factory))
        finally:
            self.core.busy = False
        factory.assert_not_called()

    def _cancellation_fixture(self):
        self.stable_result()
        # Establish real eligibility/capture before any injected cancellation.
        positive = self.prepare("cancellation-positive.step")
        self.assertTrue(positive["worker"].snapshot.is_file())
        self.assertEqual(positive["target_ids"], ("ExportSolid",))
        positive["worker"].close()
        self.assertTrue(positive["worker"].cleanup_complete.wait(2))
        path = self.folder / "cancelled-capture.step"
        sidecar = path.with_suffix(".step.json")
        path.write_bytes(b"Existing STEP destination")
        sidecar.write_bytes(b"Existing provenance destination")
        return path, sidecar, self.invariant()

    def _assert_cancelled_capture_preserves_source(self, failure, path, sidecar, before):
        self.assertEqual(failure.exception.code, "cancelled_step_export")
        self.assertFalse(self.core.busy)
        self.assertEqual(path.read_bytes(), b"Existing STEP destination")
        self.assertEqual(sidecar.read_bytes(), b"Existing provenance destination")
        self.assertEqual(self.invariant(), before)

    def test_prepare_owner_cancelled_after_real_admission_never_allocates_or_falls_back(self):
        from kurtshape import step_capture
        path, sidecar, before = self._cancellation_fixture()
        original = step_capture.roundtrip_digest
        admitted = []
        def admit(*args, **kwargs):
            result = original(*args, **kwargs)
            self.assertTrue(result[0], "Cancellation must follow genuine native admission")
            admitted.append(True)
            return result
        factory = Mock(side_effect=AssertionError("Cancelled admission allocated a worker"))
        with patch.object(step_capture, "roundtrip_digest", side_effect=admit), \
                patch.object(self.core.snapshots, "try_acquire") as acquire, \
                patch.object(NativeStepExportWorker, "own_snapshot") as capture, \
                patch.object(NativeStepExportWorker, "borrow_snapshot") as borrow, \
                patch.object(NativeStepExportWorker, "submit") as submit, \
                patch.object(self.core, "_export") as fallback:
            with self.assertRaises(OperationError) as failure:
                self.core.prepare_step_export(self.doc, str(path), worker_factory=factory,
                                              is_current=lambda: not admitted)
            self.assertEqual(admitted, [True])
            for operation in (factory, acquire, capture, borrow, submit, fallback):
                operation.assert_not_called()
        self._assert_cancelled_capture_preserves_source(failure, path, sidecar, before)

    def test_prepare_owner_retirement_during_allocation_closes_before_any_capture(self):
        path, sidecar, before = self._cancellation_fixture()
        for callback_failure in (False, RuntimeError("Owner callback failed")):
            with self.subTest(callback_failure=callback_failure), ExitStack() as stack:
                allocated, close_observations = [], []
                def current():
                    if allocated and isinstance(callback_failure, Exception):
                        raise callback_failure
                    return not allocated
                def factory(*args, **kwargs):
                    worker = self.worker()
                    original_close = worker.close
                    def close():
                        # Check before close can remove an accidental capture.
                        close_observations.append({"snapshot_exists": worker.snapshot.exists(),
                                                   "process": worker.process,
                                                   "lease": worker._snapshot_lease})
                        original_close()
                    close_spy = stack.enter_context(patch.object(worker, "close", side_effect=close))
                    allocated.append((worker, close_spy))
                    return worker
                acquire = stack.enter_context(patch.object(self.core.snapshots, "try_acquire"))
                capture = stack.enter_context(patch.object(NativeStepExportWorker, "own_snapshot"))
                borrow = stack.enter_context(patch.object(NativeStepExportWorker, "borrow_snapshot"))
                submit = stack.enter_context(patch.object(NativeStepExportWorker, "submit"))
                fallback = stack.enter_context(patch.object(self.core, "_export"))
                with self.assertRaises(OperationError) as failure:
                    self.core.prepare_step_export(self.doc, str(path), worker_factory=factory, is_current=current)
                self.assertEqual(len(allocated), 1)
                worker, close_spy = allocated[0]
                close_spy.assert_called_once_with()
                self.assertEqual(close_observations, [{"snapshot_exists": False, "process": None, "lease": None}])
                self.assertTrue(worker.closed)
                self.assertTrue(worker.cleanup_complete.wait(2))
                for operation in (acquire, capture, borrow, submit, fallback):
                    operation.assert_not_called()
                self._assert_cancelled_capture_preserves_source(failure, path, sidecar, before)

    def _cancel_during_snapshot_acquisition(self, callback_failure=None):
        path, sidecar, before = self._cancellation_fixture()
        archive = self.folder / "cancellation-lease.FCStd"
        self.doc.saveCopy(str(archive))
        key = self.core.snapshot_key(self.doc)
        self.assertTrue(self.core.snapshots.publish(key, archive))
        original_acquire = self.core.snapshots.try_acquire
        archive_bytes = archive.read_bytes()
        acquired, allocated, close_observations = [], [], []
        with ExitStack() as stack:
            def current():
                if acquired and callback_failure is not None:
                    raise callback_failure
                return not acquired
            def acquire(requested_key):
                lease = original_acquire(requested_key)
                self.assertIsNotNone(lease)
                release = stack.enter_context(patch.object(lease, "release", wraps=lease.release))
                acquired.append((lease, release, lease.path.read_bytes()))
                return lease
            def factory(*args, **kwargs):
                worker = self.worker()
                original_close = worker.close
                def close():
                    close_observations.append({"snapshot_exists": worker.snapshot.exists(),
                                               "process": worker.process,
                                               "lease": worker._snapshot_lease})
                    original_close()
                close_spy = stack.enter_context(patch.object(worker, "close", side_effect=close))
                allocated.append((worker, close_spy))
                return worker
            acquire_spy = stack.enter_context(patch.object(self.core.snapshots, "try_acquire", side_effect=acquire))
            capture = stack.enter_context(patch.object(NativeStepExportWorker, "own_snapshot"))
            borrow = stack.enter_context(patch.object(NativeStepExportWorker, "borrow_snapshot"))
            submit = stack.enter_context(patch.object(NativeStepExportWorker, "submit"))
            fallback = stack.enter_context(patch.object(self.core, "_export"))
            with self.assertRaises(OperationError) as failure:
                self.core.prepare_step_export(self.doc, str(path), worker_factory=factory, is_current=current)
            acquire_spy.assert_called_once_with(key)
            self.assertEqual(len(acquired), 1)
            lease, release, retained_bytes = acquired[0]
            release.assert_called_once_with()
            self.assertIsNone(lease._record)
            self.assertEqual(lease.path.read_bytes(), retained_bytes)
            self.assertEqual(archive.read_bytes(), archive_bytes)
            self.assertEqual(len(allocated), 1)
            worker, close_spy = allocated[0]
            close_spy.assert_called_once_with()
            self.assertEqual(close_observations, [{"snapshot_exists": False, "process": None, "lease": None}])
            self.assertTrue(worker.closed)
            self.assertTrue(worker.cleanup_complete.wait(2))
            for operation in (capture, borrow, submit, fallback):
                operation.assert_not_called()
            self._assert_cancelled_capture_preserves_source(failure, path, sidecar, before)

    def test_prepare_owner_cancelled_by_real_lease_acquisition_releases_without_borrow(self):
        self._cancel_during_snapshot_acquisition()

    def test_prepare_owner_callback_oserror_after_acquisition_is_not_optional_cache_failure(self):
        self._cancel_during_snapshot_acquisition(OSError("Owner disappeared during snapshot acquisition"))

    def test_prepare_without_owner_or_with_current_owner_keeps_independent_final_guards(self):
        self.stable_result()
        before = self.invariant()
        for mode in ("omitted", "none", "current"):
            with self.subTest(mode=mode):
                callback = Mock(return_value=True)
                options = {} if mode == "omitted" else {"is_current": callback if mode == "current" else None}
                with patch.object(self.core, "_step_export_current", wraps=self.core._step_export_current) as model_guard, \
                        patch.object(self.core, "_step_export_destination_current",
                                     wraps=self.core._step_export_destination_current) as destination_guard:
                    bundle = self.core.prepare_step_export(self.doc, str(self.folder / (mode + ".step")),
                        worker_factory=lambda *args, **kwargs: self.worker(), **options)
                self.assertIsNotNone(bundle, "A current eligible fixture must retain ordinary preparation")
                self.assertIsNone(bundle["worker"].process)
                self.assertTrue(bundle["worker"].snapshot.is_file())
                model_guard.assert_called_once_with(self.doc, bundle)
                destination_guard.assert_called_once_with(bundle)
                if mode == "current":
                    self.assertGreater(callback.call_count, 0)
                else:
                    callback.assert_not_called()
                bundle["worker"].close()
                self.assertTrue(bundle["worker"].cleanup_complete.wait(2))
                self.assertFalse(self.core.busy)
                self.assertEqual(self.invariant(), before)
