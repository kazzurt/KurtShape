"""Contract 3.2 U2b: the unsaved-changes flag, the F-05 GUI-flag restore, failure-record skips and close_document.

Headless, so the modified flag is the session basis (saved revision versus current revision);
the GUI basis is verified by the document-lifecycle GUI recipe. The F-05 restore is observed
through recorders patched over Controller._modified and _restore_modified.
"""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
from kurtshape.core import Controller, OperationError


class DocumentLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.initial = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="document-lifecycle-")
        self.core = Controller()
        self.core.settings.roots.add(self.folder)
        self.state = None
        self.new("Lifecycle")

    def tearDown(self):
        self.core.close()
        for name in set(App.listDocuments()) - self.initial:
            App.closeDocument(name)

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def new(self, name):
        response = self.core.dispatch({"op": "new", "name": name})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        return self.state

    def request(self, op, **args):
        return self.core.dispatch({"op": op, "document_id": self.state["document_id"],
                                   "expected_revision": self.state["revision"], **args})

    def call(self, op, **args):
        response = self.request(op, **args)
        self.assertTrue(response["ok"], response)
        if "revision" in response["result"]:
            self.state = response["result"]
        return response["result"]

    def reject(self, code, op, **args):
        before = self.invariant()
        response = self.request(op, **args)
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], code, response["error"])
        self.assertEqual(self.invariant(), before, "a rejected request leaves the document unchanged")
        return response["error"]

    def invariant(self):
        doc = self.doc
        return (self.core._meta(doc).Revision, doc.UndoCount, doc.RedoCount, sorted(obj.Name for obj in doc.Objects))

    def flags(self):
        state = self.call("inspect")
        return state["modified"], state["modified_basis"], state["unsaved"]

    def plate(self):
        self.call("sketch_rectangle", id="Base", width=20, height=10)
        self.call("pad", id="Plate", profile="Base", length=6, operation="new")

    def open(self, path, **extra):
        response = self.core.dispatch({"op": "open", "path": str(path), **extra})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        return response["result"]

    def native_file(self, name):
        """A plain FreeCAD file (no KurtShape metadata) in the granted folder."""
        doc = App.newDocument(name)
        doc.addObject("PartDesign::Body", "Body")
        box = doc.addObject("Part::Box", "Box")
        box.Length = box.Width = box.Height = 5
        doc.recompute()
        path = self.folder / (name + ".FCStd")
        doc.saveAs(str(path))
        App.closeDocument(doc.Name)
        return path

    # --- the modified flag ------------------------------------------------------------

    def test_session_modified_flag_follows_save_open_and_mutations(self):
        self.assertEqual(self.flags(), (True, "session", True), "new documents start unsaved")
        self.plate()
        path = self.folder / "lifecycle.FCStd"
        saved = self.call("save", path=str(path))
        self.assertEqual((saved["modified"], saved["unsaved"]), (False, False), "the save response is already clean")
        self.assertEqual(self.flags(), (False, "session", False))
        self.call("sketch_circle", id="Hole", x=5, y=5, diameter=2)
        self.assertEqual(self.flags(), (True, "session", True), "a mutation makes a saved document modified, hence unsaved")
        self.call("save", path=str(path))
        self.assertEqual(self.flags(), (False, "session", False))
        self.call("check_geometry")
        self.call("export", path=str(self.folder / "lifecycle.stl"))
        self.reject("missing_reference", "pad", id="Nope", profile="Missing", length=2, operation="add")
        self.assertEqual(self.flags(), (False, "session", False), "reads, export and rejections leave the flag alone")
        closed = self.call("close_document")
        self.assertFalse(closed["closed"]["modified"])
        opened = self.open(path)
        self.assertEqual((opened["modified"], opened["unsaved"]), (False, False))
        self.assertEqual(self.flags(), (False, "session", False))
        # recover: the recovered document is a new unsaved copy
        manifest = self.core.checkpoint(self.doc, force=True)
        self.call("close_document")
        response = self.core.dispatch({"op": "recover", "path": str(manifest)})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        self.assertEqual(self.flags(), (True, "session", True))
        self.call("close_document", discard=True)
        # import_step: a new document that was never saved
        self.open(path)
        step = self.folder / "lifecycle.step"
        self.call("export", path=str(step))
        self.call("close_document")
        response = self.core.dispatch({"op": "import_step", "path": str(step)})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        self.assertEqual(self.flags(), (True, "session", True))
        self.call("close_document", discard=True)
        # adopt: the adopted copy was just written
        self.open(self.native_file("plain"))
        self.assertFalse(self.state["managed"])
        self.assertEqual(self.flags(), (False, "session", False), "an opened native file is clean")
        adopted = self.call("adopt", path=str(self.folder / "adopted.FCStd"))
        self.assertTrue(adopted["managed"])
        self.assertEqual((adopted["modified"], adopted["unsaved"]), (False, False))
        self.assertEqual(self.flags(), (False, "session", False))

    # --- close_document ------------------------------------------------------------------

    def test_close_clean_saved_document_and_reopen(self):
        self.plate()
        path = self.folder / "clean.FCStd"
        self.call("save", path=str(path))
        identifier, revision = self.state["document_id"], self.state["revision"]
        request = {"op": "close_document", "document_id": identifier, "expected_revision": revision, "request_id": "close-1"}
        response = self.core.dispatch(request)
        self.assertTrue(response["ok"], response)
        closed = response["result"]["closed"]
        self.assertEqual((closed["document_id"], closed["revision"], closed["native_file"]), (identifier, revision, str(path)))
        self.assertEqual((closed["modified"], closed["never_saved"], closed["discarded_unsaved_changes"]), (False, False, False))
        self.assertIsNone(closed["recovery_manifest"])
        self.assertEqual(response["result"]["open_documents"], [])
        self.assertIn("operation_ms", response["result"])
        listed = self.core.dispatch({"op": "list_documents"})["result"]["documents"]
        self.assertEqual([entry["document_id"] for entry in listed], [])
        self.assertNotIn(identifier, self.core.documents)
        self.assertNotIn(identifier, self.core.signatures)
        later = self.core.dispatch({"op": "inspect", "document_id": identifier})
        self.assertEqual(later["error"]["code"], "unknown_document")
        self.assertEqual(self.core.dispatch(request), response, "an identical retry replays the closed result")
        self.assertEqual(self.core.ledger.status("close-1")["status"], "completed")
        copy = self.folder / "clean-copy.FCStd"
        copy.write_bytes(path.read_bytes())
        self.open(path)
        duplicate = self.core.dispatch({"op": "open", "path": str(copy)})
        self.assertEqual(duplicate["error"]["code"], "duplicate_document_id")
        self.call("close_document")
        self.open(copy)
        self.assertEqual(self.state["document_id"], identifier)

    def test_close_rejects_unsaved_or_never_saved_without_discard(self):
        self.plate()
        error = self.reject("unsaved_changes", "close_document")
        self.assertEqual(error["reasons"], ["modified", "never_saved"])
        self.assertEqual(error["modified_basis"], "session")
        self.assertIsNone(error["native_file"])
        self.assertEqual(error["revision"], self.state["revision"])
        self.assertIsNone(self.core.last_failures.get(self.state["document_id"]), "a refused close is no failed attempt")
        self.assertEqual(getattr(self.core._meta(self.doc), "LastFailure", ""), "")
        path = self.folder / "dirty.FCStd"
        self.call("save", path=str(path))
        self.call("sketch_circle", id="Hole", x=5, y=5, diameter=2)
        error = self.reject("unsaved_changes", "close_document", discard=False)
        self.assertEqual(error["reasons"], ["modified"])
        self.assertEqual(error["native_file"], str(path))
        self.assertEqual(self.core.dispatch({"op": "list_documents"})["result"]["documents"][0]["document_id"], self.state["document_id"])

    def test_close_with_discard_writes_durable_checkpoint(self):
        self.plate()
        path = self.folder / "durable.FCStd"
        self.call("save", path=str(path))
        self.call("sketch_circle", id="Hole", x=5, y=5, diameter=2)
        self.call("pocket", id="Cut", profile="Hole", length=2, through_all=False, reversed=False, operation="remove")
        identifier, revision = self.state["document_id"], self.state["revision"]
        closed = self.call("close_document", discard=True)["closed"]
        self.assertTrue(closed["discarded_unsaved_changes"])
        self.assertEqual(closed["modified"], True)
        manifest = Path(closed["recovery_manifest"])
        self.assertTrue(manifest.is_file(), manifest)
        self.assertEqual(manifest.name, f"{identifier}.discarded-{revision.replace('-', '')[:12]}.json")
        self.assertLessEqual(len(str(manifest.with_suffix(".saving.FCStd"))), 220, "saveCopy fails on longer paths")
        record = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertTrue(record["discarded"])
        self.assertEqual((record["document_id"], record["revision"]), (identifier, revision))
        self.assertTrue((manifest.parent / record["snapshot"]).is_file())
        self.open(path)
        self.assertIsNone(self.doc.getObject("Cut"), "the saved file predates the discarded edit")
        # Two ordinary forced checkpoints later the discard manifest still recovers.
        self.call("sketch_circle", id="Other", x=10, y=5, diameter=1)
        self.core.checkpoint(self.doc, force=True)
        self.call("sketch_circle", id="Other2", x=12, y=5, diameter=1)
        self.core.checkpoint(self.doc, force=True)
        self.call("close_document", discard=True)
        response = self.core.dispatch({"op": "recover", "path": str(manifest)})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        self.assertIsNotNone(self.doc.getObject("Cut"), "recover restores the discarded feature")
        self.assertEqual(self.flags(), (True, "session", True))
        self.call("close_document", discard=True)
        # Retention: only the newest discard_keep pairs survive.
        for index in range(self.core.recovery.discard_keep + 3):
            self.new("Throwaway %d" % index)
            self.call("close_document", discard=True)
        manifests = [p for p in self.core.recovery.directory.glob("*.discarded-*.json") if ".previous" not in p.name]
        self.assertEqual(len(manifests), self.core.recovery.discard_keep)
        for item in manifests:
            self.assertTrue(item.with_suffix(".FCStd").is_file(), item)
        snapshots = [p for p in self.core.recovery.directory.glob("*.discarded-*.FCStd") if ".previous" not in p.name and ".saving" not in p.name]
        self.assertEqual(len(snapshots), self.core.recovery.discard_keep)
        self.assertNotIn(manifest, manifests, "the oldest discard pair was pruned")

    def test_close_rejects_cross_document_users(self):
        self.plate()
        source = self.doc
        source_state = self.state
        self.call("save", path=str(self.folder / "source.FCStd"))
        source_state = self.state
        self.new("User")
        self.call("save", path=str(self.folder / "user.FCStd"))  # FreeCAD links need a saved owner document
        user = self.doc
        link = user.addObject("App::Link", "Borrowed")
        link.LinkedObject = source.getObject("Plate")
        user.recompute()
        self.state = source_state
        error = self.reject("document_in_use", "close_document")
        self.assertEqual(error["users"], [{"document": user.Name, "object": "Borrowed"}])
        error = self.reject("document_in_use", "close_document", discard=True)
        self.assertEqual(error["users"], [{"document": user.Name, "object": "Borrowed"}])
        self.assertIsNone(self.core.last_failures.get(self.state["document_id"]))

    def test_close_rejects_stale_revision_sketch_edit_pending_transaction_and_bad_discard(self):
        self.plate()
        self.call("save", path=str(self.folder / "guards.FCStd"))
        response = self.core.dispatch({"op": "close_document", "document_id": self.state["document_id"], "expected_revision": "stale"})
        self.assertEqual(response["error"]["code"], "stale_revision")
        self.reject("invalid_argument", "close_document", discard="yes")
        self.call("begin_sketch_edit", feature="Base")
        self.reject("sketch_edit_active", "close_document")
        self.call("finish_sketch_edit", cancel=True)
        # FreeCAD opens the document transaction lazily: a change must follow openTransaction.
        self.doc.openTransaction("foreign pending")
        self.doc.addObject("Part::Box", "Foreign")
        self.assertTrue(self.doc.HasPendingTransaction)
        self.state = self.core.inspect(self.doc)  # the native change rotates the revision
        try:
            response = self.request("close_document", discard=True)
            self.assertFalse(response["ok"], response)
            self.assertEqual(response["error"]["code"], "unmanaged_transaction", response["error"])
        finally:
            self.doc.abortTransaction()
        self.assertFalse(self.doc.HasPendingTransaction)
        self.assertIsNone(self.doc.getObject("Foreign"))
        self.state = self.call("inspect")
        self.call("close_document", discard=True)

    def test_close_rejects_while_editor_activity_reports_the_document(self):
        self.plate()
        self.call("save", path=str(self.folder / "editing.FCStd"))
        name = self.doc.Name
        self.core.editor_activity = lambda doc_name: "feature_editor" if doc_name == name else None
        error = self.reject("user_editing", "close_document")
        self.assertEqual(error["tool"], "feature_editor")
        self.assertIsNone(self.core.last_failures.get(self.state["document_id"]))
        self.core.editor_activity = None
        self.call("close_document")

    def test_close_unmanaged_reference_file(self):
        path = self.native_file("reference")
        self.open(path)
        self.assertFalse(self.state["managed"])
        self.assertIn("close_document", self.state["operations"])
        self.call("close_document")
        self.open(path)
        doc = self.doc
        doc.addObject("Part::Box", "Extra")
        doc.recompute()
        state = self.call("inspect")
        self.assertTrue(state["modified"], "a native edit rotates the session revision")
        error = self.reject("unsaved_changes", "close_document", discard=True)
        self.assertTrue(error["discard_unsupported"])
        self.assertEqual(error["reasons"], ["modified"])
        self.reject("unsaved_changes", "close_document")
        self.assertIn(doc.Name, App.listDocuments())

    def test_checkpoint_failure_keeps_the_document_open(self):
        self.plate()
        with patch.object(self.core.recovery, "capture_discarded", side_effect=OSError("disk full")):
            error = self.reject("checkpoint_failed", "close_document", discard=True)
        self.assertIn("disk full", error["cause"])
        self.assertIn(self.doc.Name, App.listDocuments())
        self.assertIn(self.state["document_id"], self.core.documents)
        self.assertEqual(self.call("inspect")["revision"], self.state["revision"])
        # with the checkpoint writable the same request closes it
        closed = self.call("close_document", discard=True)
        self.assertEqual(closed["closed"]["document_id"], self.state["document_id"])
        self.assertNotIn(self.state["document_id"], self.core.documents)

    def test_failed_undo_after_the_native_history_moved_keeps_the_gui_flag(self):
        self.plate()
        self.call("sketch_rectangle", id="Second", x=30, width=5, height=5)
        moved, restored = [], []
        real_history, real_recompute = self.core._native_history, self.core._recompute

        def history(doc, op):
            real_history(doc, op)
            moved.append(op)

        def recompute(doc, *args, **kwargs):
            if moved:
                raise OperationError("unstable_merge_scope", "forced failure after the native undo")
            return real_recompute(doc, *args, **kwargs)

        with patch.object(Controller, "_modified", staticmethod(lambda doc: True)), \
                patch.object(Controller, "_restore_modified", staticmethod(lambda doc, value: restored.append(value))), \
                patch.object(self.core, "_native_history", history), patch.object(self.core, "_recompute", recompute):
            response = self.request("undo")
        self.assertFalse(response["ok"], response)
        self.assertEqual((response["error"]["code"], moved), ("unstable_merge_scope", ["undo"]))
        self.assertEqual(restored, [], "the native undo ran, so the document is not shown as clean")
        self.assertIsNone(self.doc.getObject("Second"), "the undone state stays (no transaction to abort)")

    def test_close_document_is_not_previewable(self):
        self.plate()
        self.assertNotIn("close_document", Controller.MODEL_OPS)
        self.assertIn("close_document", Controller.LIFECYCLE_OPS)
        self.assertIn("close_document", Controller.OPS)
        self.reject("unsupported_preview", "preview", proposal={"op": "close_document"})
        capabilities = self.core.dispatch({"op": "capabilities"})["result"]
        self.assertNotIn("close_document", capabilities["preview_operations"])
        self.assertNotIn("close_document", capabilities["read_operations"])

    # --- F-05 and failure records ------------------------------------------------------------

    def test_rejected_request_restores_pre_request_gui_flag(self):
        self.plate()
        flag = {"value": False}
        restored = []

        def modified(doc):
            return flag["value"]

        def restore(doc, value):
            restored.append((doc.Name, value))
            flag["value"] = value

        with patch.object(Controller, "_modified", staticmethod(modified)), \
                patch.object(Controller, "_restore_modified", staticmethod(restore)):
            self.assertEqual(self.flags(), (False, "gui", True), "the GUI basis wins when a GUI flag exists; never saved stays unsaved")
            # post-write rejection: an Add inside the plate adds nothing
            self.call("sketch_rectangle", id="Inner", x=5, y=2, width=5, height=5)
            restored.clear()
            flag["value"] = False
            self.reject("empty_add", "pad", id="Nothing", profile="Inner", length=3, operation="add")
            self.assertEqual(restored[-1], (self.doc.Name, False))
            # pre-write rejection
            restored.clear()
            self.reject("missing_reference", "pad", id="Nope", profile="Missing", length=2, operation="add")
            self.assertEqual(restored, [(self.doc.Name, False)])
            # a dirty document stays dirty
            restored.clear()
            flag["value"] = True
            self.reject("missing_reference", "pad", id="Nope", profile="Missing", length=2, operation="add")
            self.assertEqual(restored, [(self.doc.Name, True)])
            flag["value"] = False
            # a failure after the commit does not restore
            restored.clear()
            with patch.object(Controller, "inspect", side_effect=RuntimeError("inspect broke after the commit")):
                response = self.request("sketch_circle", id="Late", x=15, y=5, diameter=1)
            self.assertFalse(response["ok"])
            self.assertEqual(response["error"]["code"], "operation_failed")
            self.assertEqual(restored, [], "a committed change is never shown as clean")
            self.state = self.call("inspect")
            self.assertIsNotNone(self.doc.getObject("Late"))
            # the sketch-lease path keeps its own draft handling
            restored.clear()
            self.call("begin_sketch_edit", feature="Base")
            response = self.request("add_circle", sketch="Base", x=0, y=0, diameter=-1)
            self.assertFalse(response["ok"], response)
            self.assertEqual(restored, [], "a lease rejection preserves the draft, not the flag")
            self.state = self.call("inspect")  # a failed command inside the lease advances the revision
            self.call("finish_sketch_edit", cancel=True)

    def test_non_mutating_errors_write_no_failure_metadata(self):
        self.plate()
        meta = self.core._meta(self.doc)
        before = (getattr(meta, "LastFailure", ""), self.core.last_failures.get(self.state["document_id"]),
                  self.core.observer.state(self.doc)["change_serial"], self.core.observer.state(self.doc)["generation"])
        failures = [
            self.request("resolve_selector", selector={"kind": "no_such_kind"}),
            self.request("check_geometry", body="NoSuchBody"),
            self.request("preview", proposal={"op": "rebuild"}),
            self.core.dispatch({"op": "operation_schema", "operations": ["nope"]}),
        ]
        for response in failures:
            self.assertFalse(response["ok"], response)
        self.assertEqual(failures[0]["error"]["code"], "invalid_selector")
        self.assertEqual(failures[1]["error"]["code"], "missing_body")
        self.assertEqual(failures[2]["error"]["code"], "unsupported_preview")
        self.assertEqual(failures[3]["error"]["code"], "invalid_argument")
        unclonable = self.request("preview", proposal={"op": "pad", "id": "X", "length": 3})
        self.assertTrue(unclonable["ok"], unclonable)
        self.assertFalse(unclonable["result"]["accepted"])
        after = (getattr(meta, "LastFailure", ""), self.core.last_failures.get(self.state["document_id"]),
                 self.core.observer.state(self.doc)["change_serial"], self.core.observer.state(self.doc)["generation"])
        self.assertEqual(after, before, "reads never record a failed attempt")
        self.assertIsNone(self.call("inspect")["last_failed_attempt"])
        # A failed mutation still does.
        self.reject("missing_reference", "pad", id="Nope", profile="Missing", length=2, operation="add")
        self.assertIsNotNone(self.core.last_failures.get(self.state["document_id"]))
        self.assertEqual(self.call("inspect")["last_failed_attempt"]["error"]["code"], "missing_reference")
