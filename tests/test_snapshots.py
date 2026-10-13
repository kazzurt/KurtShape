"""Immutable archive lifetime, accepted-state reuse and recovery boundaries."""
from dataclasses import replace
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import support

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import FreeCAD as App
from kurtshape.core import Controller
from kurtshape.snapshots import SnapshotKey, SnapshotStore


class SnapshotStoreTests(unittest.TestCase):
    def setUp(self):
        self.folder = support.scratch(self, prefix="immutable-snapshot-lifetime-")
        self.store = SnapshotStore(self.folder / "snapshots")
        self.addCleanup(self.store.close)
        self.source = self.folder / "source.FCStd"
        self.source.write_bytes(b"original archive")
        self.key = SnapshotKey("instance-a", "revision-a", 1, 1)

    def test_replacement_and_close_preserve_pinned_files_until_release(self):
        self.assertTrue(self.store.publish(self.key, self.source))
        first = self.store.try_acquire(self.key)
        self.assertIsNotNone(first)
        newer = replace(self.key, revision="revision-b", serial=2)
        self.source.write_bytes(b"new archive")
        self.assertTrue(self.store.publish(newer, self.source))
        self.assertIsNone(self.store.try_acquire(self.key))
        self.assertEqual(first.path.read_bytes(), b"original archive")
        second = self.store.try_acquire(newer)
        self.store.close()
        self.assertIsNone(self.store.try_acquire(newer))
        self.assertTrue(first.path.exists())
        self.assertTrue(second.path.exists())
        first.release()
        first.release()
        second.release()
        self.assertFalse(first.path.exists())
        self.assertFalse(second.path.exists())

    def test_changed_cache_archive_is_rejected_without_corrupting_source(self):
        self.store.publish(self.key, self.source)
        lease = self.store.try_acquire(self.key)
        lease.path.write_bytes(b"invalid replacement")
        self.assertIsNone(self.store.try_acquire(self.key))
        self.assertEqual(self.source.read_bytes(), b"original archive")
        self.assertTrue(lease.path.exists())
        lease.release()
        self.assertFalse(lease.path.exists())

    def test_document_retirement_rejects_late_publication_and_new_instance_is_distinct(self):
        self.store.publish(self.key, self.source)
        lease = self.store.try_acquire(self.key)
        self.store.retire_document(self.key.instance_id)
        self.assertFalse(self.store.publish(self.key, self.source))
        self.assertIsNone(self.store.try_acquire(self.key))
        replacement = replace(self.key, instance_id="instance-b")
        self.assertTrue(self.store.publish(replacement, self.source))
        fresh = self.store.try_acquire(replacement)
        self.assertNotEqual(fresh.path, lease.path)
        self.assertTrue(lease.path.exists())
        lease.release()
        fresh.release()

    def test_old_publisher_and_failed_copy_cannot_replace_current_archive(self):
        newer = replace(self.key, revision="revision-b", serial=2)
        self.store.publish(newer, self.source)
        self.assertFalse(self.store.publish(self.key, self.source))
        with patch("kurtshape.snapshots.shutil.copyfile", side_effect=OSError("copy failed")):
            with self.assertRaisesRegex(OSError, "copy failed"):
                self.store.publish(replace(newer, serial=3), self.source)
        lease = self.store.try_acquire(newer)
        self.assertEqual(lease.path.read_bytes(), b"original archive")
        self.assertEqual(len(list(self.store.directory.glob("*.FCStd"))), 1)
        lease.release()


class NativeSnapshotSharingTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="accepted-snapshot-sharing-")
        self.core = Controller()
        result = self.core.dispatch({"op": "new", "name": "Snapshot sharing", "measure": False})
        self.assertTrue(result["ok"], result)
        self.doc = self.core.documents[result["result"]["document_id"]]

    def tearDown(self):
        self.core.close()
        for name in set(App.listDocuments()) - self.names:
            App.closeDocument(name)

    def test_ordinary_recovery_publishes_matching_immutable_archive(self):
        before = self.core.snapshot_key(self.doc)
        manifest = self.core.checkpoint(self.doc)
        self.assertIsNotNone(manifest)
        self.assertEqual(self.core.recovery.snapshot_count, 1)
        after = self.core.snapshot_key(self.doc)
        self.assertEqual(before, after)
        lease = self.core.snapshots.try_acquire(after)
        self.assertIsNotNone(lease)
        native, record = self.core.recovery.read(manifest)
        self.assertEqual(native.read_bytes(), lease.path.read_bytes())
        self.assertNotEqual(native, lease.path)
        self.assertEqual(record["revision"], lease.key.revision)
        self.doc.Label = "Changed accepted state"
        self.core.sync(self.doc)
        self.assertIsNone(self.core.snapshots.try_acquire(self.core.snapshot_key(self.doc)))
        self.assertTrue(lease.path.exists())
        lease.release()

    def test_forced_capture_and_pending_transaction_bypass_shared_cache(self):
        self.core.checkpoint(self.doc, force=True)
        self.assertEqual(self.core.recovery.snapshot_count, 1)
        self.assertEqual(self.core.snapshots.published, 0)
        self.doc.openTransaction("Native draft")
        # A document Label change is not recorded by native object undo.
        # Materialize the native transaction before checking its boundary.
        self.doc.addObject("PartDesign::Body", "DraftBody")
        self.assertTrue(self.doc.HasPendingTransaction)
        self.assertIsNone(self.core.snapshot_key(self.doc))
        self.core.recovery.last.clear()
        self.core.checkpoint(self.doc)
        self.assertEqual(self.core.recovery.snapshot_count, 2)
        self.assertEqual(self.core.snapshots.published, 0)
        self.doc.abortTransaction()

    def test_cache_copy_failure_does_not_fail_durable_recovery(self):
        with patch.object(self.core.snapshots, "publish", side_effect=OSError("optional cache failed")):
            manifest = self.core.checkpoint(self.doc)
        self.assertIsNotNone(manifest)
        self.assertEqual(self.core.recovery.snapshot_cache_failures, 1)
        archive, record = self.core.recovery.read(manifest)
        self.assertTrue(archive.is_file())
        self.assertEqual(record["revision"], self.core._meta(self.doc).Revision)

    def test_recomputed_generation_and_document_close_retire_reuse(self):
        self.core.checkpoint(self.doc)
        key = self.core.snapshot_key(self.doc)
        lease = self.core.snapshots.try_acquire(key)
        self.assertIsNotNone(lease)
        self.doc.recompute()
        self.core.sync(self.doc)
        self.assertIsNone(self.core.snapshots.try_acquire(self.core.snapshot_key(self.doc)))
        App.closeDocument(self.doc.Name)
        self.assertIsNone(self.core.snapshots.try_acquire(key))
        self.assertTrue(lease.path.exists())
        lease.release()
        self.assertFalse(lease.path.exists())
