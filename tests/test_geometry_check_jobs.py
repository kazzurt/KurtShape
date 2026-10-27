"""Detached native geometry jobs preserve parent state and process ownership."""
from dataclasses import asdict, replace
import copy
import io
import json
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
from kurtshape import geometry
from kurtshape.core import Controller, OperationError
from kurtshape.geometry_check_worker import NativeGeometryCheckWorker, target_fingerprints
from kurtshape.geometry_check_worker import _check_document
from kurtshape.preview_worker import _snapshot_file_identity
from kurtshape.snapshots import SnapshotKey, SnapshotStore
from native_validation_snapshot import snapshot_document
from test_borrowed_preview import BorrowedPreviewTests


class GeometryCheckWorkerLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.folder = support.scratch(self, prefix="geometry-check-worker-lifetime-")
        self.store = SnapshotStore(self.folder / "geometry-check-archives")
        self.addCleanup(self.store.close)
        self.source = self.folder / "accepted-source.FCStd"
        self.source.write_bytes(b"immutable native archive fixture")
        self.key = SnapshotKey("instance", "revision", 3, 7)
        self.assertTrue(self.store.publish(self.key, self.source))
        self.worker = NativeGeometryCheckWorker("private-native-python", self.folder, timeout=.01)
        self.addCleanup(self.cleanup_worker)

    def cleanup_worker(self):
        self.worker.close()
        self.assertTrue(self.worker.cleanup_complete.wait(5), "Geometry worker cleanup did not finish")

    def borrow(self):
        lease = self.store.try_acquire(self.key)
        self.assertIsNotNone(lease)
        self.addCleanup(lambda: lease.release() if self.worker._snapshot_lease is not lease else None)
        self.worker.borrow_snapshot(lease)
        self.store.close()
        return lease

    def test_cancel_before_start_releases_once_and_preserves_original(self):
        lease = self.borrow()
        with patch.object(lease, "release", wraps=lease.release) as release:
            self.worker.close()
            self.worker.close()
            self.assertTrue(self.worker.cleanup_complete.wait(2))
            release.assert_called_once()
        self.assertFalse(lease.path.exists())
        self.assertEqual(self.source.read_bytes(), b"immutable native archive fixture")
        self.assertFalse(self.worker.folder.exists())

    def test_start_failure_releases_pin_and_private_resources(self):
        lease = self.borrow()
        with patch("kurtshape.geometry_check_worker.subprocess.Popen", side_effect=OSError("Cannot launch native checker")):
            with self.assertRaisesRegex(OSError, "Cannot launch"):
                self.worker.start()
        self.assertTrue(self.worker.closed)
        self.assertTrue(self.worker.cleanup_complete.wait(2))
        self.assertFalse(lease.path.exists())
        self.assertFalse(self.worker.folder.exists())
        self.assertTrue(self.worker.log is None or self.worker.log.closed)

    def test_repeated_wait_timeouts_and_kill_errors_retain_archive_until_exit(self):
        lease = self.borrow()
        process = self.worker.process = Mock()
        process.stdin = io.BytesIO()
        process.kill.side_effect = OSError("Native handle still busy")
        waiting, allow_exit = threading.Event(), threading.Event()
        self.addCleanup(allow_exit.set)
        attempts = []
        def wait(timeout):
            attempts.append(timeout)
            if len(attempts) <= 2:
                raise subprocess.TimeoutExpired("owned geometry process", timeout)
            waiting.set()
            if not allow_exit.wait(3):
                raise subprocess.TimeoutExpired("owned geometry process", timeout)
            return 0
        process.wait.side_effect = wait
        self.worker.close()
        self.assertTrue(waiting.wait(2))
        self.worker.close()
        self.assertGreaterEqual(process.kill.call_count, 3)
        self.assertFalse(self.worker.cleanup_complete.is_set())
        self.assertIsNotNone(lease._record)
        self.assertTrue(lease.path.is_file())
        self.assertTrue(self.worker.folder.is_dir())
        allow_exit.set()
        self.assertTrue(self.worker.cleanup_complete.wait(2))
        self.assertIsNone(lease._record)
        self.assertFalse(lease.path.exists())
        self.assertTrue(process.stdin.closed)

    def test_runtime_timeout_keeps_pin_until_cancel_confirms_exit(self):
        lease = self.borrow()
        process = self.worker.process = Mock()
        process.stdin = io.BytesIO()
        process.poll.return_value = None
        process.wait.return_value = 0
        self.worker.active = 1
        self.worker.started = time.monotonic() - 2
        with self.assertRaises(TimeoutError):
            self.worker.poll()
        self.assertTrue(lease.path.exists())
        self.assertIsNotNone(lease._record)
        self.worker.close()
        self.assertTrue(self.worker.cleanup_complete.wait(2))
        process.wait.assert_called()
        self.assertIsNone(lease._record)

    def test_wait_error_needs_independent_exit_confirmation(self):
        lease = self.borrow()
        process = self.worker.process = Mock()
        process.stdin = io.BytesIO()
        process.kill.side_effect = OSError("Already stopped")
        process.wait.side_effect = OSError("Wait handle unavailable")
        process.poll.return_value = 0
        self.worker.close()
        self.assertTrue(self.worker.cleanup_complete.wait(2))
        process.poll.assert_called()
        self.assertIsNone(lease._record)

    def test_tampered_lease_is_rejected_before_launch(self):
        lease = self.borrow()
        lease.path.write_bytes(b"changed while start was queued")
        with patch("kurtshape.geometry_check_worker.subprocess.Popen") as launch:
            with self.assertRaisesRegex(RuntimeError, "changed"):
                self.worker.start()
        launch.assert_not_called()
        self.assertTrue(self.worker.cleanup_complete.wait(2))
        self.assertIsNone(lease._record)

    def test_result_published_during_exit_poll_is_delivered(self):
        self.borrow()
        process = self.worker.process = Mock()
        process.stdin = io.BytesIO()
        process.wait.return_value = 0
        self.worker.active = 1
        self.worker.started = time.monotonic()
        path = self.worker.folder / "result-1.json"
        self.assertFalse(path.exists())
        expected = {"task": self.worker.token, "sequence": 1, "ok": True,
                    "checks": [{"id": "Body", "valid": True, "issues": [], "ms": 1.0}]}
        published = []
        def exit_after_publish():
            if not published:
                self.assertFalse(path.exists())
                stage = path.with_suffix(".writing")
                stage.write_text(json.dumps(expected), encoding="utf-8")
                os.replace(stage, path)
                published.append(True)
            return 0
        process.poll.side_effect = exit_after_publish
        self.assertEqual(self.worker.poll(), expected)
        self.assertEqual(published, [True])
        self.assertIsNone(self.worker.active)
        self.assertFalse(path.exists())

    def test_duplicate_parent_key_receipt_restores_original_or_absent_verdict(self):
        key = ("Document", "Pad", 3, 123)
        original = {"valid": True, "issues": [], "ms": 1.0}
        first = {"valid": False, "issues": ["First verdict"], "ms": 2.0}
        second = {"valid": False, "issues": ["Second verdict"], "ms": 3.0}
        for already_cached in (False, True):
            with self.subTest(already_cached=already_cached):
                cache = geometry.GeometryCache()
                if already_cached:
                    cache.accept_checks([(key, original)])
                previous = cache._checks.get(key)
                receipt = cache.accept_checks([(key, first), (key, second)])
                self.assertEqual(cache._checks[key], second)
                cache.discard_accepted_checks(receipt)
                if already_cached:
                    self.assertIs(cache._checks[key], previous)
                    self.assertEqual(cache._checks[key], original)
                else:
                    self.assertNotIn(key, cache._checks)


class GeometryCheckJobTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="geometry-check-job-")
        self.core = Controller()
        self.workers = []
        self.state = None
        self.call("new", name="Native geometry check jobs")

    def tearDown(self):
        for worker in self.workers:
            worker.close()
            self.assertTrue(worker.cleanup_complete.wait(15), "Owned native checker did not exit")
        self.core.close()
        for name in set(App.listDocuments()) - self.names:
            App.closeDocument(name)

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def call(self, op, **arguments):
        request = dict(op=op, measure=False, **arguments)
        if op != "new":
            request.update(document_id=self.state["document_id"], expected_revision=self.state["revision"])
        response = self.core.dispatch(request)
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        return self.state

    def plate(self):
        self.call("sketch_rectangle", id="Plate", width=20, height=10)
        self.call("pad", id="Pad", profile="Plate", length=6)
        return self.doc.Body

    def invalid_solid(self, *, diagonal=False):
        # The diagonal wire intentionally exercises an inexact native archive
        # round trip. Orthogonal crossings keep every direction coefficient
        # exact and exercise delivery of a real invalid native verdict.
        points = ([(0, 0), (10, 10), (0, 10), (10, 0), (0, 0)] if diagonal else
                  [(0, 0), (10, 0), (10, 10), (5, 10), (5, -5), (0, -5), (0, 0)])
        shape = Part.Face(Part.makePolygon([App.Vector(x, y, 0) for x, y in points])).extrude(App.Vector(0, 0, 5))
        self.assertFalse(shape.isNull())
        self.assertEqual(len(shape.Solids), 1)
        self.assertFalse(shape.isValid(), "The invalid fixture must be a real invalid native solid")
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
        worker = NativeGeometryCheckWorker(executable, self.folder, timeout=30)
        self.workers.append(worker)
        return worker

    def reply(self, worker):
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            result = worker.poll()
            if result is not None:
                json.dumps(result, allow_nan=False)
                return result
            time.sleep(.02)
        self.fail("Private native geometry worker exceeded its bounded timeout")

    def envelope(self, targets):
        names = [obj.Name for obj in targets]
        return {"snapshot_key": asdict(self.core.snapshot_key(self.doc)),
                "document_id": self.core.identifier(self.doc), "target_ids": names,
                "target_fingerprints": target_fingerprints(self.doc, names)}

    def prepare(self, body=None):
        bundle = self.core.prepare_geometry_check(self.doc, body=body,
            worker_factory=lambda *args, **kwargs: self.worker())
        self.assertIsNotNone(bundle, "A stable uncached local solid must prepare an asynchronous check")
        self.assertIsNone(bundle["worker"].process, "Preparing a capture must not start its child")
        return bundle

    def response(self, bundle):
        checks = []
        for name in bundle["target_ids"]:
            obj = self.doc.getObject(name)
            checks.append(dict(id=name, **geometry.check_shape(geometry.source_of(obj).Shape.copy())))
        return dict(bundle["envelope"], task=bundle["worker"].token, sequence=bundle["sequence"],
            ok=True, checks=checks, engine={"FreeCAD": list(App.Version()), "OCCT": Part.OCC_VERSION},
            phase_milliseconds={}, milliseconds=1.0)

    def owned_archive(self, worker):
        self.doc.saveCopy(str(worker.snapshot))
        self.core.sync(self.doc)
        worker.own_snapshot(self.core.snapshot_key(self.doc), _snapshot_file_identity(worker.snapshot))
        return worker.snapshot.read_bytes()

    def test_oblique_curve_uses_synchronous_check_without_allocating_worker(self):
        from kurtshape.geometry_check_worker import source_roundtrip_stable
        obj = self.doc.addObject("Part::Feature", "ObliqueTorus")
        obj.Shape = Part.makeTorus(50.479194424640504, 22,
            App.Vector(-338.98113751727601, -246.28421259793501, 22.8399742042516),
            App.Vector(.18735110628408988, -.95350077593135429, -.23608437744254279))
        self.doc.recompute()
        self.core.sync(self.doc)
        self.state = self.core.inspect(self.doc, measure=False)
        before = self.invariant()
        self.assertFalse(source_roundtrip_stable(self.doc, [obj.Name]),
                         "The regression needs a real numerically unstable native round trip")
        factory = Mock(side_effect=AssertionError("Inexact capture must not allocate a worker"))
        self.assertIsNone(self.core.prepare_geometry_check(self.doc, worker_factory=factory))
        factory.assert_not_called()
        self.assertEqual(self.invariant(), before)
        result = self.call("check_geometry")
        self.assertEqual(result["geometry_check"], "valid")
        self.assertEqual(result["build_status"], "valid")
        self.assertEqual(self.invariant(), before)


    def test_diagonal_invalid_shape_falls_back_and_keeps_native_invalid_verdict(self):
        obj = self.invalid_solid(diagonal=True)
        before = BorrowedPreviewTests.native_shapes(self.doc)
        revision = self.state["revision"]
        factory = Mock(side_effect=AssertionError("Inexact capture must not allocate a worker"))
        self.assertIsNone(self.core.prepare_geometry_check(self.doc, worker_factory=factory))
        factory.assert_not_called()
        result = self.call("check_geometry")
        self.assertEqual(result["geometry_check"], "invalid")
        self.assertEqual(result["build_status"], "failed")
        entry, = result["geometry_check_report"]["bodies"]
        self.assertEqual(entry["id"], obj.Name)
        self.assertTrue(any("Self-intersecting wire" in issue for issue in entry["issues"]))
        self.assertEqual(result["revision"], revision)
        self.assertEqual(BorrowedPreviewTests.native_shapes(self.doc), before)


    def test_unstable_embedded_fallback_preserves_genuine_source_change_detection(self):
        source = App.newDocument("UnstableSource", hidden=True)
        try:
            obj = source.addObject("Part::Feature", "Curved")
            obj.Shape = Part.makeTorus(50.479194424640504, 22,
                App.Vector(-338.98113751727601, -246.28421259793501, 22.8399742042516),
                App.Vector(.18735110628408988, -.95350077593135429, -.23608437744254279))
            path = self.folder / "curved-source.FCStd"
            source.recompute()
            source.saveAs(str(path))
        finally:
            App.closeDocument(source.Name)
            App.setActiveDocument(self.doc.Name)
        self.call("create_assembly")
        self.call("insert_assembly_part", path=str(path), source_id="Curved", id="Occurrence")
        embedded = self.doc.Occurrence.LinkedObject
        seal = embedded.SourceGeometryFingerprint
        embedded.Placement.Base.x += .01
        self.doc.recompute()
        self.core.sync(self.doc)
        self.state = self.core.inspect(self.doc, measure=False)
        self.assertEqual(self.state["build_status"], "failed")
        before = target_fingerprints(self.doc, ["Occurrence"])
        revision = self.state["revision"]
        factory = Mock(side_effect=AssertionError("Inexact capture must not allocate a worker"))
        self.assertIsNone(self.core.prepare_geometry_check(self.doc, worker_factory=factory))
        factory.assert_not_called()
        result = self.call("check_geometry")
        self.assertEqual(result["geometry_check"], "valid")
        self.assertEqual(result["build_status"], "failed")
        self.assertEqual(result["revision"], revision)
        self.assertEqual(embedded.SourceGeometryFingerprint, seal)
        self.assertEqual(target_fingerprints(self.doc, ["Occurrence"]), before)
        exported = self.core.dispatch(dict(op="export", path=str(self.folder / "changed-source.step"),
            document_id=self.state["document_id"], expected_revision=self.state["revision"]))
        self.assertFalse(exported["ok"], exported)
        self.assertEqual(exported["error"]["code"], "build_failed")


    def test_actual_owned_worker_valid_check_matches_native_oracle_and_preserves_source(self):
        body = self.plate()
        expected = geometry.check_shape(body.Shape.copy())
        worker = self.worker()
        archive = self.owned_archive(worker)
        envelope = self.envelope([body])
        before = self.invariant()
        worker.submit(1, envelope)
        result = self.reply(worker)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["snapshot_key"], envelope["snapshot_key"])
        self.assertEqual(result["target_ids"], [body.Name])
        self.assertEqual(result["document_id"], envelope["document_id"])
        self.assertEqual([(row["id"], row["valid"], row["issues"]) for row in result["checks"]],
                         [(body.Name, expected["valid"], expected["issues"])])
        self.assertEqual(self.invariant(), before)
        self.assertEqual(worker.snapshot.read_bytes(), archive)
        self.assertIsNone(worker._snapshot_lease)

    def test_child_rejects_attachment_without_equivalence_before_any_check(self):
        body = self.plate()
        worker = self.worker()
        archive = self.owned_archive(worker)
        envelope = self.envelope([body])
        before = self.invariant()
        other = Controller()
        clone = App.newDocument("GeometryCheckAttachmentProof", hidden=True, temp=True)
        try:
            clone.load(str(worker.snapshot))
            with patch("kurtshape.preview_worker._attach_preview_document", return_value=None) as attach, \
                    patch.object(geometry, "check_shape") as check:
                with self.assertRaises(OperationError) as failed:
                    _check_document(other, clone, worker.snapshot, _snapshot_file_identity(worker.snapshot), envelope, {})
                self.assertEqual(failed.exception.code, "geometry_check_snapshot_incompatible")
                self.assertIn("attachment changed", str(failed.exception))
                attach.assert_called_once()
                check.assert_not_called()
        finally:
            other.close()
            App.closeDocument(clone.Name)
            App.setActiveDocument(self.doc.Name)
        self.assertEqual(self.invariant(), before)
        self.assertEqual(worker.snapshot.read_bytes(), archive)

    def test_child_rejects_actual_topology_change_before_or_during_attachment(self):
        from kurtshape.preview_worker import _attach_preview_document
        body = self.plate()
        worker = self.worker()
        archive = self.owned_archive(worker)
        envelope = self.envelope([body])
        before = self.invariant()
        for boundary in ("load", "attach"):
            with self.subTest(boundary=boundary):
                other = Controller()
                clone = App.newDocument("GeometryCheckTopologyProof", hidden=True, temp=True)
                try:
                    clone.load(str(worker.snapshot))
                    def change_shape():
                        clone.Pad.Length = 9
                        clone.recompute()
                        self.assertNotEqual(target_fingerprints(clone, ["Body"]), envelope["target_fingerprints"])
                    def attach_and_change(*args):
                        snapshot = _attach_preview_document(*args)
                        self.assertIsNotNone(snapshot, "The unmodified clone must pass attachment equivalence")
                        change_shape()
                        return snapshot
                    if boundary == "load":
                        change_shape()
                    with patch("kurtshape.preview_worker._attach_preview_document", side_effect=attach_and_change) as attach, \
                            patch.object(geometry, "check_shape") as check:
                        with self.assertRaises(OperationError) as failed:
                            _check_document(other, clone, worker.snapshot, _snapshot_file_identity(worker.snapshot), envelope, {})
                        self.assertEqual(failed.exception.code, "geometry_check_snapshot_incompatible")
                        self.assertIn("geometry", str(failed.exception))
                        self.assertEqual(attach.call_count, int(boundary == "attach"))
                        check.assert_not_called()
                finally:
                    other.close()
                    App.closeDocument(clone.Name)
                    App.setActiveDocument(self.doc.Name)
                self.assertEqual(self.invariant(), before)
                self.assertEqual(worker.snapshot.read_bytes(), archive)

    def test_actual_worker_rejects_diagonal_bow_tie_archive_numeric_changes(self):
        obj = self.invalid_solid(diagonal=True)
        expected = geometry.check_shape(obj.Shape.copy())
        self.assertFalse(expected["valid"])
        self.assertTrue(any("Self-intersecting wire" in issue for issue in expected["issues"]))
        worker = self.worker()
        archive = self.owned_archive(worker)
        envelope = self.envelope([obj])
        before = self.invariant()
        worker.submit(1, envelope)
        response = self.reply(worker)
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["checks"], [])
        self.assertEqual(response["error"]["code"], "geometry_check_snapshot_incompatible")
        self.assertIn("loaded archive", response["error"]["message"])
        self.assertEqual(response["target_fingerprints"], envelope["target_fingerprints"])
        self.assertEqual(self.invariant(), before)
        self.assertEqual(worker.snapshot.read_bytes(), archive)
        self.assertIsNone(self.core.geometry.check(obj))

    def test_actual_leased_worker_orthogonal_invalid_check_matches_oracle_and_releases_after_exit(self):
        obj = self.invalid_solid()
        expected = geometry.check_shape(obj.Shape.copy())
        self.assertTrue(any("Self-intersecting wire" in issue for issue in expected["issues"]))
        manifest = self.core.checkpoint(self.doc)
        self.assertIsNotNone(manifest)
        key = self.core.snapshot_key(self.doc)
        lease = self.core.snapshots.try_acquire(key)
        self.assertIsNotNone(lease)
        worker = self.worker()
        self.addCleanup(lambda: lease.release() if worker._snapshot_lease is not lease else None)
        worker.borrow_snapshot(lease)
        archive = lease.path.read_bytes()
        recovery, _ = self.core.recovery.read(manifest)
        recovery_bytes = recovery.read_bytes()
        before = self.invariant()
        worker.submit(1, self.envelope([obj]))
        result = self.reply(worker)
        self.assertTrue(result["ok"], result)
        self.assertEqual([(row["id"], row["valid"], row["issues"]) for row in result["checks"]],
                         [(obj.Name, expected["valid"], expected["issues"])])
        self.assertEqual(self.invariant(), before)
        self.assertEqual(lease.path.read_bytes(), archive)
        self.assertEqual(recovery.read_bytes(), recovery_bytes)
        self.core.snapshots.retire_document(key.instance_id)
        self.assertTrue(lease.path.exists())
        native_release, exits = lease.release, []
        def release():
            exits.append(worker.process.poll())
            native_release()
        with patch.object(lease, "release", side_effect=release):
            worker.close()
            self.assertTrue(worker.cleanup_complete.wait(15))
        self.assertEqual(len(exits), 1)
        self.assertIsNotNone(exits[0])
        self.assertFalse(lease.path.exists())
        self.assertEqual(recovery.read_bytes(), recovery_bytes)
        self.assertEqual(self.invariant(), before)

    def test_controller_accepts_actual_owned_result_and_reuses_parent_cache(self):
        body = self.plate()
        before = self.invariant()
        bundle = self.prepare()
        self.assertFalse(bundle["snapshot_reused"])
        worker = bundle["worker"]
        self.assertTrue(worker.snapshot.is_file())
        self.assertIsNone(worker._snapshot_lease)
        worker.submit(bundle["sequence"], bundle["envelope"])
        response = self.reply(worker)
        self.assertTrue(response["ok"], response)
        with patch.object(geometry, "check_shape", side_effect=AssertionError("Parent acceptance must not check geometry")):
            accepted = self.core.accept_geometry_check(self.doc, bundle, response)
            self.assertEqual(accepted["geometry_check"], "valid")
            self.assertEqual(accepted["geometry_check_report"]["status"], "valid")
            self.assertTrue(self.core.geometry.check(body)["valid"])
            factory = Mock(side_effect=AssertionError("Cached checks must not create another worker"))
            self.assertIsNone(self.core.prepare_geometry_check(self.doc, worker_factory=factory))
            factory.assert_not_called()
            result = self.call("check_geometry")
            self.assertEqual(result["geometry_check_report"]["status"], "valid")
        self.assertEqual(self.invariant(), before)

    def test_controller_reuses_exact_recovery_lease_and_publishes_orthogonal_invalid_build_status(self):
        obj = self.invalid_solid()
        expected = geometry.check_shape(obj.Shape.copy())
        manifest = self.core.checkpoint(self.doc)
        self.assertIsNotNone(manifest)
        key = self.core.snapshot_key(self.doc)
        lease = self.core.snapshots.try_acquire(key)
        self.assertIsNotNone(lease)
        path = lease.path
        original = path.read_bytes()
        lease.release()
        before = self.invariant()
        bundle = self.prepare(body=obj.Name)
        self.assertTrue(bundle["snapshot_reused"])
        self.assertEqual(bundle["worker"].snapshot, path)
        self.assertIsNotNone(bundle["worker"]._snapshot_lease)
        self.assertEqual(bundle["snapshot_key"], key)
        self.assertEqual(self.invariant(), before)
        bundle["worker"].submit(bundle["sequence"], bundle["envelope"])
        response = self.reply(bundle["worker"])
        self.assertTrue(response["ok"], response)
        accepted = self.core.accept_geometry_check(self.doc, bundle, response)
        self.assertEqual(accepted["geometry_check"], "invalid")
        self.assertEqual(accepted["build_status"], "failed")
        entry, = accepted["geometry_check_report"]["bodies"]
        self.assertEqual((entry["id"], entry["valid"], entry["issues"]),
                         (obj.Name, expected["valid"], expected["issues"]))
        self.assertEqual(BorrowedPreviewTests.native_shapes(self.doc), before[1])
        self.assertEqual(path.read_bytes(), original)
        with patch.object(geometry, "check_shape", side_effect=AssertionError("Accepted invalid verdict must remain cached")):
            self.assertIsNone(self.core.prepare_geometry_check(self.doc))
            self.assertEqual(self.call("check_geometry")["geometry_check_report"]["status"], "invalid")

    def test_every_snapshot_key_field_rejects_stale_publication(self):
        body = self.plate()
        bundle = self.prepare()
        response = self.response(bundle)
        key = bundle["snapshot_key"]
        changes = {"instance_id": "replacement-instance", "revision": "replacement-revision",
                   "generation": key.generation + 1, "serial": key.serial + 1, "policy": "other-policy"}
        for field, value in changes.items():
            with self.subTest(field=field), patch.object(self.core, "snapshot_key", return_value=replace(key, **{field: value})):
                self.assertIsNone(self.core.accept_geometry_check(self.doc, bundle, response))
            self.assertIsNone(self.core.geometry.check(body))

    def test_original_parent_topology_key_rejects_result_even_if_snapshot_key_is_unchanged(self):
        body = self.plate()
        bundle = self.prepare()
        response = self.response(bundle)
        self.doc.Pad.Length = 9
        self.doc.recompute()
        self.core.sync(self.doc)
        self.assertNotEqual(self.core.geometry.check_key(body), bundle["topology_keys"][0])
        with patch.object(self.core, "snapshot_key", return_value=bundle["snapshot_key"]):
            self.assertIsNone(self.core.accept_geometry_check(self.doc, bundle, response))
        self.assertIsNone(self.core.geometry.check(body))

    def test_changed_result_membership_rejects_all_targets_atomically(self):
        body = self.plate()
        bundle = self.prepare()
        response = self.response(bundle)
        extra = self.doc.addObject("Part::Feature", "NewResult")
        extra.Shape = Part.makeBox(2, 3, 4, App.Vector(30, 0, 0))
        self.doc.recompute()
        self.core.sync(self.doc)
        with patch.object(self.core, "snapshot_key", return_value=bundle["snapshot_key"]):
            self.assertIsNone(self.core.accept_geometry_check(self.doc, bundle, response))
        self.assertIsNone(self.core.geometry.check(body))
        self.assertIsNone(self.core.geometry.check(extra))

    def test_foreign_document_closed_worker_and_canceled_generation_never_publish(self):
        body = self.plate()
        bundle = self.prepare()
        response = self.response(bundle)
        other = App.newDocument("ForeignGeometryCheckInstance")
        self.assertIsNone(self.core.accept_geometry_check(other, bundle, response))
        self.assertIsNone(self.core.accept_geometry_check(self.doc, bundle, response, is_current=lambda: False))
        bundle["worker"].close()
        self.assertTrue(bundle["worker"].cleanup_complete.wait(5))
        self.assertIsNone(self.core.accept_geometry_check(self.doc, bundle, response))
        self.assertIsNone(self.core.geometry.check(body))

    def test_cancellation_during_final_parent_validation_prevents_cache_insertion(self):
        body = self.plate()
        bundle = self.prepare()
        response = self.response(bundle)
        current = Mock(side_effect=[True, False])
        self.assertIsNone(self.core.accept_geometry_check(self.doc, bundle, response, is_current=current))
        self.assertEqual(current.call_count, 2)
        self.assertIsNone(self.core.geometry.check(body))

    def test_same_document_mutation_in_final_callback_cannot_seed_a_verdict(self):
        body = self.plate()
        bundle = self.prepare()
        response = self.response(bundle)
        calls = []
        def current():
            calls.append(True)
            if len(calls) == 2:
                self.doc.Pad.Length = 9
                self.doc.recompute()
            return True
        with patch.object(self.core.geometry, "accept_checks", wraps=self.core.geometry.accept_checks) as accept:
            self.assertIsNone(self.core.accept_geometry_check(self.doc, bundle, response, is_current=current))
            accept.assert_not_called()
        self.assertEqual(len(calls), 2)
        self.assertAlmostEqual(self.doc.Pad.Length.Value, 9)
        self.assertNotEqual(self.core.snapshot_key(self.doc), bundle["snapshot_key"])
        self.assertIsNone(self.core.geometry.check(body))
        self.assertNotIn(bundle["topology_keys"][0], self.core.geometry._checks)

    def test_mutation_during_inspection_discards_only_just_imported_verdict(self):
        body = self.plate()
        other = self.doc.addObject("Part::Feature", "PreviouslyCheckedResult")
        other.Shape = Part.makeBox(2, 3, 4, App.Vector(30, 0, 0))
        self.doc.recompute()
        self.core.sync(self.doc)
        prior_check = self.core.geometry.check(other, compute=True)
        prior_key = self.core.geometry.check_key(other)
        bundle = self.prepare(body=body.Name)
        response = self.response(bundle)
        original_inspect = self.core.inspect
        observed = []
        def inspect_and_change(doc, *args, **kwargs):
            state = original_inspect(doc, *args, **kwargs)
            observed.append(bundle["topology_keys"][0] in self.core.geometry._checks)
            doc.Pad.Length = 9
            doc.recompute()
            return state
        with patch.object(self.core, "inspect", side_effect=inspect_and_change):
            self.assertIsNone(self.core.accept_geometry_check(self.doc, bundle, response))
        self.assertEqual(observed, [True], "The mutation must occur after actual verdict import")
        self.assertNotIn(bundle["topology_keys"][0], self.core.geometry._checks)
        self.assertIsNone(self.core.geometry.check(body))
        self.assertEqual(self.core.geometry._checks[prior_key], prior_check,
                         "Discarding the stale job must preserve an unrelated cached verdict")

    def test_post_inspection_cancellation_removes_invalid_verdict_and_failed_status(self):
        obj = self.invalid_solid()
        original_status = self.core._meta(self.doc).BuildStatus
        self.assertNotEqual(original_status, "failed")
        bundle = self.prepare(body=obj.Name)
        response = self.response(bundle)
        self.assertFalse(response["checks"][0]["valid"])
        calls = []
        def current():
            calls.append(True)
            if len(calls) == 3:
                self.assertEqual(self.core._meta(self.doc).BuildStatus, "failed")
                self.assertIn(bundle["topology_keys"][0], self.core.geometry._checks)
                return False
            return True
        self.assertIsNone(self.core.accept_geometry_check(self.doc, bundle, response, is_current=current))
        self.assertEqual(len(calls), 3)
        self.assertNotIn(bundle["topology_keys"][0], self.core.geometry._checks)
        self.assertIsNone(self.core.geometry.check(obj))
        self.assertEqual(self.core._meta(self.doc).BuildStatus, original_status)
        self.assertFalse(self.core.busy)

    def test_malformed_second_verdict_never_publishes_first_valid_verdict(self):
        body = self.plate()
        other = self.doc.addObject("Part::Feature", "OtherResult")
        other.Shape = Part.makeBox(2, 3, 4, App.Vector(30, 0, 0))
        self.doc.recompute()
        self.core.sync(self.doc)
        bundle = self.prepare()
        original = self.response(bundle)
        self.assertEqual(len(original["checks"]), 2)
        for bad in (float("nan"), float("inf"), -1, "not a number"):
            with self.subTest(bad=bad):
                response = copy.deepcopy(original)
                response["checks"][1]["ms"] = bad
                with self.assertRaises(OperationError):
                    self.core.accept_geometry_check(self.doc, bundle, response)
                self.assertIsNone(self.core.geometry.check(body))
                self.assertIsNone(self.core.geometry.check(other))
        response = copy.deepcopy(original)
        response["checks"][1]["id"] = response["checks"][0]["id"]
        with self.assertRaises(OperationError):
            self.core.accept_geometry_check(self.doc, bundle, response)
        self.assertIsNone(self.core.geometry.check(body))

    def test_wrong_task_sequence_targets_and_document_echo_are_rejected(self):
        body = self.plate()
        bundle = self.prepare()
        original = self.response(bundle)
        for field, value in (("task", "foreign-task"), ("sequence", bundle["sequence"] + 1),
                             ("document_id", "other-document"), ("target_ids", ["MissingResult"]),
                             ("snapshot_key", dict(original["snapshot_key"], serial=-1))):
            with self.subTest(field=field):
                response = copy.deepcopy(original)
                response[field] = value
                with self.assertRaises(OperationError):
                    self.core.accept_geometry_check(self.doc, bundle, response)
                self.assertIsNone(self.core.geometry.check(body))

    def test_draft_pending_and_busy_documents_do_not_prepare_a_worker(self):
        self.plate()
        factory = Mock(side_effect=AssertionError("Ineligible document must not construct a worker"))
        self.core.busy = True
        try:
            self.assertIsNone(self.core.prepare_geometry_check(self.doc, worker_factory=factory))
        finally:
            self.core.busy = False
        self.doc.openTransaction("Pending native geometry edit")
        transaction = (App.getActiveTransaction() or (None, None))[1]
        self.doc.Pad.Label = "Pending Pad"
        try:
            self.assertIsNone(self.core.prepare_geometry_check(self.doc, worker_factory=factory))
        finally:
            self.doc.abortTransaction()
            if transaction is not None and (App.getActiveTransaction() or (None, None))[1] == transaction:
                App.closeActiveTransaction(True)
        self.core.sync(self.doc)
        self.state = self.core.inspect(self.doc, measure=False)
        self.call("begin_sketch_edit", feature="Plate")
        self.assertIsNone(self.core.prepare_geometry_check(self.doc, worker_factory=factory))
        self.call("finish_sketch_edit", cancel=True)
        factory.assert_not_called()

    def test_foreign_native_dependency_requires_synchronous_fallback(self):
        self.plate()
        external = App.newDocument("ExternalGeometryCheckSource")
        source = external.addObject("Part::Feature", "ExternalBox")
        source.Shape = Part.makeBox(2, 3, 4)
        external.recompute()
        external.saveAs(str(self.folder / "external-geometry-source.FCStd"))
        self.doc.saveAs(str(self.folder / "geometry-check-owner.FCStd"))
        self.doc.Pad.addProperty("App::PropertyXLink", "GeometryCheckForeignProbe")
        self.doc.Pad.GeometryCheckForeignProbe = source
        self.doc.recompute()
        self.core.sync(self.doc)
        self.assertIn(source, self.doc.Pad.OutList)
        factory = Mock(side_effect=AssertionError("Foreign closure must use synchronous check"))
        self.assertIsNone(self.core.prepare_geometry_check(self.doc, worker_factory=factory))
        factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
