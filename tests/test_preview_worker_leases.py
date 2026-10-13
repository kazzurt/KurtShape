"""Pinned preview archives survive every owned process lifetime boundary."""
import io
import json
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest.mock import Mock, patch
import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kurtshape.preview_worker import NativePreviewWorker, _validate_transport_snapshot
from kurtshape.snapshots import SnapshotKey, SnapshotStore


class PreviewWorkerLeaseTests(unittest.TestCase):
    def setUp(self):
        self.folder = support.scratch(self, prefix="preview-worker-lease-lifetime-")
        self.store = SnapshotStore(self.folder / "retained-native-archives")
        self.addCleanup(self.store.close)
        self.source = self.folder / "accepted-source.FCStd"
        self.source.write_bytes(b"immutable native archive fixture")
        self.key = SnapshotKey("instance", "revision", 3, 7)
        self.store.publish(self.key, self.source)
        self.worker = NativePreviewWorker("private-native-python", self.folder)
        self.addCleanup(self.cleanup_worker)

    def cleanup_worker(self):
        self.worker.close()
        self.assertTrue(self.worker.cleanup_complete.wait(5), "Owned cleanup did not finish")

    def lease(self):
        lease = self.store.try_acquire(self.key)
        self.assertIsNotNone(lease)
        # Successful transfer leaves cleanup solely with the process owner.
        self.addCleanup(lambda: lease.release() if self.worker._snapshot_lease is not lease else None)
        return lease

    @staticmethod
    def stopped_process():
        process = Mock()
        process.poll.return_value = 0
        process.wait.return_value = 0
        process.stdin = io.BytesIO()
        return process

    def test_close_before_start_releases_once_and_never_deletes_original(self):
        lease = self.lease()
        path = lease.path
        self.worker.borrow_snapshot(lease)
        self.store.close()
        self.assertTrue(path.is_file())
        with patch.object(lease, "release", wraps=lease.release) as release:
            self.worker.close()
            self.worker.close()
            self.assertTrue(self.worker.cleanup_complete.wait(2))
            release.assert_called_once()
        self.assertFalse(path.exists())
        self.assertTrue(self.source.exists())
        self.assertFalse(self.worker.folder.exists())

    def test_repeated_wait_timeouts_and_kill_errors_preserve_pin_until_confirmed_exit(self):
        lease = self.lease()
        path = lease.path
        self.worker.borrow_snapshot(lease)
        self.store.close()
        process = self.worker.process = Mock()
        process.stdin = io.BytesIO()
        process.kill.side_effect = OSError("Native process handle is still busy")
        waiting, allow_exit = threading.Event(), threading.Event()
        self.addCleanup(allow_exit.set)
        attempts = []
        def wait(timeout):
            attempts.append(timeout)
            if len(attempts) <= 2:
                raise subprocess.TimeoutExpired("owned preview process", timeout)
            waiting.set()
            if not allow_exit.wait(3):
                raise subprocess.TimeoutExpired("owned preview process", timeout)
            return 0
        process.wait.side_effect = wait
        self.worker.close()
        self.assertTrue(waiting.wait(2))
        self.worker.close()
        self.assertEqual(len(attempts), 3)
        self.assertGreaterEqual(process.kill.call_count, 3)
        self.assertFalse(self.worker.cleanup_complete.is_set())
        self.assertTrue(path.is_file())
        self.assertTrue(self.worker.folder.is_dir())
        self.assertIsNotNone(lease._record)
        allow_exit.set()
        self.assertTrue(self.worker.cleanup_complete.wait(2))
        self.assertFalse(path.exists())
        self.assertIsNone(lease._record)
        self.assertTrue(process.stdin.closed)

    def test_wait_error_requires_independent_exit_confirmation(self):
        lease = self.lease()
        self.worker.borrow_snapshot(lease)
        self.store.close()
        process = self.worker.process = self.stopped_process()
        process.kill.side_effect = OSError("Already exited")
        process.wait.side_effect = OSError("Wait handle unavailable")
        self.worker.close()
        self.assertTrue(self.worker.cleanup_complete.wait(2))
        process.poll.assert_called_once()
        self.assertFalse(lease.path.exists())

    def test_start_failure_releases_lease_and_closes_private_resources(self):
        lease = self.lease()
        self.worker.borrow_snapshot(lease)
        self.store.close()
        with patch("kurtshape.preview_worker.subprocess.Popen", side_effect=OSError("Cannot launch native Python")):
            with self.assertRaisesRegex(OSError, "Cannot launch"):
                self.worker.start()
        self.assertTrue(self.worker.closed)
        self.assertTrue(self.worker.cleanup_complete.wait(2))
        self.assertTrue(self.worker.log.closed)
        self.assertFalse(lease.path.exists())
        self.assertFalse(self.worker.folder.exists())

    def test_transport_passes_explicit_path_and_pinned_identity(self):
        lease = self.lease()
        self.worker.borrow_snapshot(lease)
        process = self.stopped_process()
        with patch("kurtshape.preview_worker.subprocess.Popen", return_value=process) as launch:
            self.worker.start()
        command = launch.call_args.args[0]
        self.assertEqual(Path(command[-2]), lease.path)
        self.assertEqual(tuple(json.loads(command[-1])), lease.file_identity)
        self.assertEqual(_validate_transport_snapshot(command[-2], json.loads(command[-1])), lease.file_identity)
        self.assertFalse((self.worker.folder / "source.FCStd").exists())

    def test_changed_lease_before_start_fails_without_launch_and_then_releases(self):
        lease = self.lease()
        self.worker.borrow_snapshot(lease)
        lease.path.write_bytes(b"archive changed while startup was queued")
        self.store.close()
        with patch("kurtshape.preview_worker.subprocess.Popen") as launch:
            with self.assertRaisesRegex(RuntimeError, "changed"):
                self.worker.start()
        launch.assert_not_called()
        self.assertTrue(self.worker.cleanup_complete.wait(2))
        self.assertFalse(lease.path.exists())

    def test_transport_rejects_late_archive_change_before_native_open(self):
        lease = self.lease()
        identity = list(lease.file_identity)
        lease.path.write_bytes(b"changed after parent spawn")
        with self.assertRaisesRegex(RuntimeError, "changed"):
            _validate_transport_snapshot(lease.path, identity)

    def test_rejected_borrow_keeps_caller_ownership(self):
        first, rejected = self.lease(), self.lease()
        self.worker.borrow_snapshot(first)
        with self.assertRaisesRegex(RuntimeError, "another snapshot"):
            self.worker.borrow_snapshot(rejected)
        self.assertIsNotNone(rejected._record)
        self.worker.close()
        self.assertTrue(self.worker.cleanup_complete.wait(2))
        self.assertIsNotNone(rejected._record)
        with self.assertRaisesRegex(RuntimeError, "another snapshot"):
            self.worker.borrow_snapshot(rejected)
        self.assertIsNotNone(rejected._record)

    def test_changed_file_rejected_before_borrow_keeps_caller_ownership(self):
        lease = self.lease()
        lease.path.write_bytes(b"changed before ownership transfer")
        with self.assertRaisesRegex(RuntimeError, "changed"):
            self.worker.borrow_snapshot(lease)
        self.assertIsNotNone(lease._record)
        self.assertIsNone(self.worker._snapshot_lease)
        self.assertEqual(self.worker.snapshot, self.worker.folder / "source.FCStd")

    def test_released_lease_cannot_be_borrowed_even_when_archive_remains_cached(self):
        lease = self.lease()
        path = lease.path
        lease.release()
        self.assertTrue(path.is_file())
        with self.assertRaisesRegex(RuntimeError, "released"):
            self.worker.borrow_snapshot(lease)
        self.assertIsNone(self.worker._snapshot_lease)
        self.assertEqual(self.worker.snapshot, self.worker.folder / "source.FCStd")

    def test_borrow_after_launch_rejected_and_owned_capture_transport_still_works(self):
        self.worker.snapshot.write_bytes(b"owned GUI capture")
        process = self.stopped_process()
        with patch("kurtshape.preview_worker.subprocess.Popen", return_value=process) as launch:
            self.worker.start()
        command = launch.call_args.args[0]
        self.assertEqual(Path(command[-2]), self.worker.folder / "source.FCStd")
        _validate_transport_snapshot(command[-2], json.loads(command[-1]))
        rejected = self.lease()
        with self.assertRaisesRegex(RuntimeError, "another snapshot"):
            self.worker.borrow_snapshot(rejected)
        self.assertIsNotNone(rejected._record)
