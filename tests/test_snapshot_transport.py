"""Accepted recovery archives across the actual preview coordinator boundary."""
from dataclasses import replace
import hashlib
from pathlib import Path
import time
import unittest
from unittest.mock import Mock, patch

import FreeCAD as App
from test_extrusion_preview import ExtrusionPreviewTests
from kurtshape.extrusion_preview import ExtrusionResult
from kurtshape.preview_worker import NativePreviewWorker


class SnapshotTransportTests(unittest.TestCase):
    # Reuse fixtures explicitly without inheriting and rerunning another suite.
    setUp = ExtrusionPreviewTests.setUp
    tearDown = ExtrusionPreviewTests.tearDown
    doc = ExtrusionPreviewTests.doc
    call = ExtrusionPreviewTests.call
    preview = ExtrusionPreviewTests.preview
    invariant = ExtrusionPreviewTests.invariant

    def adapter(self):
        adapter = ExtrusionPreviewTests._adapter_without_qt(self)
        adapter.source_key = None
        adapter.snapshot_captures = adapter.snapshot_reuses = 0
        proposal = adapter.evaluator._proposal(
            dict(op="pad", profile="Profile", length=2), solve=False)
        adapter.pending = adapter.normalized = proposal
        return adapter, proposal

    def archive(self):
        self.call("sketch_rectangle", id="Profile", width=20, height=10)
        manifest = self.core.checkpoint(self.doc)
        self.assertIsNotNone(manifest)
        key = self.core.snapshot_key(self.doc)
        lease = self.core.snapshots.try_acquire(key)
        self.assertIsNotNone(lease)
        path = lease.path
        lease.release()
        return key, path, manifest

    def worker(self):
        worker = NativePreviewWorker(Path(App.getHomePath()) / "bin" / "python.exe", self.folder)
        self.addCleanup(self.close_worker, worker)
        return worker

    @staticmethod
    def close_worker(worker):
        worker.close()
        if not worker.cleanup_complete.wait(15):
            raise AssertionError("Owned preview worker did not finish cleanup")

    def test_recovery_archive_reaches_actual_worker_without_another_capture(self):
        self.call("sketch_rectangle", id="Profile", width=20, height=10)
        adapter, proposal = self.adapter()
        # The independent owned oracle can emit a native state notification.
        # Publish recovery after it, so the lease targets the accepted state
        # actually submitted by the coordinator.
        reference = self.preview().evaluate(proposal)
        self.assertTrue(reference.valid, reference.error)
        manifest = self.core.checkpoint(self.doc)
        self.assertIsNotNone(manifest)
        key = self.core.snapshot_key(self.doc)
        lease = self.core.snapshots.try_acquire(key)
        self.assertIsNotNone(lease)
        archive = lease.path
        lease.release()
        recovery, _ = self.core.recovery.read(manifest)
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        archive_hash, recovery_hash = digest(archive), digest(recovery)
        baseline = self.invariant()
        self.assertEqual(self.core.snapshot_key(self.doc), key)
        adapter._start_exact()
        worker = adapter.worker
        self.assertIsNotNone(worker, adapter.result)
        self.addCleanup(self.close_worker, worker)
        self.assertEqual(worker.snapshot, archive)
        self.assertEqual(adapter.snapshot_captures, 0)
        self.assertEqual(adapter.snapshot_reuses, 1)
        self.assertEqual(self.core.recovery.snapshot_count, 1)
        replies = []
        native_poll = worker.poll

        def observe():
            response = native_poll()
            if response is not None:
                replies.append(response)
            return response

        with patch.object(worker, "poll", side_effect=observe):
            deadline = time.monotonic() + 35
            while adapter.evaluating and time.monotonic() < deadline:
                adapter._poll()
                time.sleep(.02)
        self.assertFalse(adapter.evaluating, "Actual borrowed worker exceeded 35 seconds")
        self.assertIsNotNone(adapter.result)
        self.assertTrue(adapter.result.valid, adapter.result.error)
        self.assertEqual(len(replies), 1)
        self.assertTrue(replies[0]["snapshot_reused"], replies[0])
        self.assertEqual(replies[0]["snapshot_capture_delta"], 0)
        self.assertAlmostEqual(adapter.result.measurements["volume_mm3"], reference.measurements["volume_mm3"])
        self.assertEqual(adapter.result.measurements["bbox_mm"], reference.measurements["bbox_mm"])
        self.assertIs(adapter.current_result(proposal), adapter.result)
        self.assertEqual(self.invariant(), baseline)
        self.assertEqual(digest(archive), archive_hash)
        self.assertEqual(digest(recovery), recovery_hash)

        process, lease = worker.process, worker._snapshot_lease
        self.assertIsNotNone(lease)
        self.core.snapshots.retire_document(key.instance_id)
        self.assertTrue(archive.exists())
        native_release, exit_codes = lease.release, []

        def release_after_exit():
            exit_codes.append(process.poll())
            native_release()

        with patch.object(lease, "release", side_effect=release_after_exit):
            adapter.clear()
            self.assertTrue(worker.cleanup_complete.wait(15))
        self.assertEqual(len(exit_codes), 1)
        self.assertIsNotNone(exit_codes[0])
        self.assertFalse(archive.exists())
        self.assertEqual(digest(recovery), recovery_hash)
        self.assertEqual(self.invariant(), baseline)

    def test_reentrant_acquisition_cannot_revive_canceled_or_replaced_preview(self):
        self.archive()
        for replacement in (False, True):
            with self.subTest(replacement=replacement):
                adapter, proposal = self.adapter()
                worker = self.worker()
                worker.submit = Mock()
                native_acquire = self.core.snapshots.try_acquire
                leases = []
                new_worker = Mock()
                new_result = ExtrusionResult(True, self.state["revision"], proposal)

                def acquire(key):
                    self.assertIs(adapter.snapshotting, worker)
                    adapter._start_exact()
                    adapter._poll()
                    self.assertIsNone(adapter.current_result(proposal))
                    lease = native_acquire(key)
                    self.assertIsNotNone(lease)
                    leases.append(lease)
                    adapter.clear()
                    self.assertFalse(worker.closed)
                    if replacement:
                        adapter.begin(self.doc, self.state["revision"])
                        adapter.pending = adapter.normalized = proposal
                        adapter.result, adapter.worker = new_result, new_worker
                    return lease

                with patch("kurtshape.preview_worker.NativePreviewWorker", return_value=worker), \
                        patch.object(self.core.snapshots, "try_acquire", side_effect=acquire):
                    adapter._start_exact()
                worker.submit.assert_not_called()
                self.assertTrue(worker.cleanup_complete.wait(15))
                self.assertEqual(len(leases), 1)
                self.assertIsNone(leases[0]._record)
                self.assertIsNone(adapter.snapshotting)
                self.assertFalse(self.core.busy)
                self.assertIs(adapter.result, new_result if replacement else None)
                new_worker.submit.assert_not_called()
                new_worker.close.assert_not_called()
                adapter.close()

    def test_failed_borrow_releases_lease_without_submitting(self):
        self.archive()
        adapter, _ = self.adapter()
        worker = self.worker()
        worker.snapshot.write_bytes(b"untouched private snapshot")
        worker.submit = Mock()
        leases = []

        def reject(lease):
            leases.append(lease)
            self.assertEqual(worker.snapshot.read_bytes(), b"untouched private snapshot")
            raise OSError("Injected snapshot handoff failure")

        with patch("kurtshape.preview_worker.NativePreviewWorker", return_value=worker), \
                patch.object(worker, "borrow_snapshot", side_effect=reject):
            adapter._start_exact()
        worker.submit.assert_not_called()
        self.assertEqual(len(leases), 1)
        self.assertIsNone(leases[0]._record)
        self.assertFalse(adapter.evaluating)
        self.assertFalse(adapter.result.valid)
        self.assertFalse(self.core.busy)

    def test_cache_acquisition_failure_uses_owned_native_capture(self):
        self.archive()
        adapter, _ = self.adapter()
        worker = self.worker()
        worker.submit = Mock()
        with patch("kurtshape.preview_worker.NativePreviewWorker", return_value=worker), \
                patch.object(self.core.snapshots, "try_acquire", side_effect=OSError("Cache unavailable")):
            adapter._start_exact()
        worker.submit.assert_called_once()
        self.assertTrue(worker.snapshot.is_file())
        self.assertIsNone(worker._snapshot_lease)
        self.assertEqual(adapter.snapshot_captures, 1)
        self.assertEqual(adapter.snapshot_reuses, 0)
        self.assertFalse(self.core.busy)

    def test_every_snapshot_key_field_invalidates_cached_and_inflight_results(self):
        self.archive()
        key = self.core.snapshot_key(self.doc)
        changes = dict(instance_id="replacement-instance", revision="replacement-revision",
                       generation=key.generation + 1, serial=key.serial + 1, policy="replacement-policy")
        for field, value in changes.items():
            for inflight in (False, True):
                with self.subTest(field=field, inflight=inflight):
                    adapter, proposal = self.adapter()
                    self.assertTrue(adapter._sync_generation())
                    result = adapter.result = ExtrusionResult(True, self.state["revision"], proposal)
                    adapter.exact_cache[adapter._key(proposal)] = result
                    worker = adapter.worker = Mock()
                    adapter.evaluating = inflight
                    adapter.submitted = (adapter.sequence, proposal, adapter.source_generation)
                    with patch.object(self.core, "snapshot_key", return_value=replace(key, **{field: value})):
                        self.assertFalse(adapter._sync_generation())
                    worker.close.assert_called_once()
                    self.assertIsNone(adapter.worker)
                    self.assertIsNone(adapter.result)
                    self.assertFalse(adapter.evaluating)
                    self.assertFalse(adapter.exact_cache)
                    worker.poll.assert_not_called()
                    adapter.close()
