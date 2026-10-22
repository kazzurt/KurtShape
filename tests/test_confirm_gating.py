"""Confirm in the Extrude / Remove dialog commits from a valid provisional preview (slice A/B U1)."""
from collections import OrderedDict
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import Mock

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
from kurtshape import confirm_gate
from kurtshape.core import Controller, intent_signature
from kurtshape.extrusion_preview import (DebouncedExtrusionPreview, ExtrusionEvaluator, ExtrusionResult,
                                         ProvisionalExtrusion)
from kurtshape.preview_worker import NativePreviewWorker


class ConfirmGatingTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="confirm-gating-tests-")
        self.core = Controller()
        self.state = None
        self.previews = []
        self.call("new")

    def tearDown(self):
        for preview in self.previews:
            preview.close()
        self.core.close()
        for name in set(App.listDocuments()) - self.names:
            App.closeDocument(name)

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def request(self, op, **args):
        request = dict(op=op, **args)
        if op != "new":
            request.update(document_id=self.state["document_id"], expected_revision=self.state["revision"])
        return self.core.dispatch(request)

    def call(self, op, **args):
        response = self.request(op, **args)
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        return self.state

    def volume(self):
        # A Part Studio document keeps its result in its parts; a legacy one in Body.
        return sum(obj.Shape.Volume for obj in self.doc.Objects
                   if obj.TypeId == "PartDesign::Body" and not obj.Shape.isNull() and obj.Shape.isValid())

    def invariant(self):
        return (intent_signature(self.doc), self.core._meta(self.doc).Revision, self.doc.UndoCount,
                self.doc.RedoCount, self.doc.HasPendingTransaction, round(self.volume(), 6))

    def evaluator(self):
        preview = ExtrusionEvaluator(self.core, self.doc, self.state["revision"])
        self.previews.append(preview)
        return preview

    def adapter(self):
        """The product adapter without Qt timers, as tests/test_extrusion_preview.py builds it."""
        adapter = object.__new__(DebouncedExtrusionPreview)
        adapter.controller = self.core
        adapter.evaluator = self.evaluator()
        adapter.provisional = ProvisionalExtrusion(adapter.evaluator)
        adapter.closed = adapter.evaluating = False
        adapter.allowed = None
        adapter.timer, adapter.poll_timer, adapter.lifetime_timer = Mock(), Mock(), Mock()
        adapter.timer.isActive.return_value = False
        adapter.overlay = Mock()
        adapter.worker = adapter.snapshotting = None
        adapter.pending = adapter.normalized = adapter.result = adapter.submitted = adapter.ready_sequence = None
        adapter.sequence = 0
        adapter.source_generation = None
        adapter.source_key = None
        adapter.snapshot_captures = adapter.snapshot_reuses = 0
        adapter.exact_cache = OrderedDict()
        adapter.status = Mock()
        adapter.delay_ms = 160
        adapter.normalizing = 0

        def display(result):
            adapter.result = result
            adapter.status(result)
            return result
        adapter._display = display
        self.addCleanup(adapter.close)
        return adapter

    def plate(self):
        self.call("sketch_rectangle", id="BaseProfile", width=20, height=10)
        self.call("pad", id="Pad", profile="BaseProfile", length=6)
        top = "Face" + str(next(index + 1 for index, face in enumerate(self.doc.Pad.Shape.Faces)
                                 if abs(face.CenterOfMass.z - 6) < 1e-7))
        self.call("sketch_circle", id="Profile", x=10, y=5, diameter=4, support={"feature": "Pad", "subelement": top})

    def exact_through_worker(self, proposal):
        worker = NativePreviewWorker(Path(App.getHomePath()) / "bin" / "python.exe", ROOT / "runtime")
        self.addCleanup(worker.close)
        self.doc.saveCopy(str(worker.snapshot))
        worker.submit(1, proposal)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            result = worker.poll()
            if result is not None:
                return result
            time.sleep(.02)
        self.fail("Private exact worker did not finish within 60 seconds")

    # -- the pure rule -------------------------------------------------------------------------

    def test_verdict_rule(self):
        fields = {"op": "pad", "profile": "Profile", "length": 2.0, "reversed": False, "body": "Body"}
        other = dict(fields, length=3.0)
        provisional = ExtrusionResult(False, "r1", fields, provisional=True, mesh={"triangles": [1]})
        exact_valid = ExtrusionResult(True, "r1", fields, measurements={"volume_mm3": 1.0})
        exact_invalid = ExtrusionResult(False, "r1", fields, error={"code": "empty_cut", "message": "x"})
        # (a) a valid provisional result enables Confirm while no exact result exists.
        self.assertEqual(confirm_gate.verdict(provisional, fields, provisional=True), confirm_gate.PROVISIONAL)
        self.assertTrue(confirm_gate.accept_enabled(provisional, provisional=True))
        # (b) an exact invalid result for the same fields disables it.
        self.assertIsNone(confirm_gate.verdict(exact_invalid, fields, provisional=True))
        self.assertFalse(confirm_gate.accept_enabled(exact_invalid, provisional=True))
        # (c) an exact valid result keeps it enabled.
        self.assertEqual(confirm_gate.verdict(exact_valid, fields, provisional=True), confirm_gate.EXACT)
        # (d) a provisional result for other fields than the current ones does not enable it.
        self.assertIsNone(confirm_gate.verdict(provisional, other, provisional=True))
        self.assertIsNone(confirm_gate.verdict(exact_valid, other, provisional=True))
        # No result, a provisional without a mesh, and the exact-only mode (the default) never enable.
        self.assertIsNone(confirm_gate.verdict(None, provisional=True))
        self.assertIsNone(confirm_gate.verdict(ExtrusionResult(False, "r1", fields, provisional=True), provisional=True))
        self.assertIsNone(confirm_gate.verdict(provisional, fields))
        self.assertIsNone(confirm_gate.verdict(provisional, fields, provisional=False))
        self.assertFalse(confirm_gate.accept_enabled(provisional))
        self.assertEqual(confirm_gate.verdict(exact_valid, fields, provisional=False), confirm_gate.EXACT)

    def test_provisional_acceptance_policy_follows_where_the_commit_validates_geometry(self):
        # Legacy pad: no empty-add check at commit -> exact only. Legacy pocket: cut_valid -> allowed.
        self.assertFalse(confirm_gate.provisional_allowed("pad", studio=False))
        self.assertTrue(confirm_gate.provisional_allowed("pocket", studio=False))
        # Part Studio Add / Remove / Intersect run result checks -> allowed for both kinds.
        self.assertTrue(confirm_gate.provisional_allowed("pad", studio=True))
        self.assertTrue(confirm_gate.provisional_allowed("pocket", studio=True))
        # Edits and other tasks never commit on a provisional.
        self.assertFalse(confirm_gate.provisional_allowed("pocket", studio=True, editing=True))
        self.assertFalse(confirm_gate.provisional_allowed("pad", studio=True, editing=True))
        for op in ("edit_extrusion", "extrude_face", "revolve", None):
            self.assertFalse(confirm_gate.provisional_allowed(op, studio=True), op)

    def test_rejection_memory_keeps_geometric_verdicts_and_retries_transient_failures(self):
        for code in ("empty_cut", "empty_add", "empty_merge_scope", "empty_preview", "build_failed", "invalid_geometry",
                     "open_profile", "invalid_argument", "missing_reference", "preview_render_failed",
                     "unsupported_transition", "operation_failed"):
            self.assertTrue(confirm_gate.remembers_rejection({"code": code, "message": "x"}), code)
        for code in ("preview_failed", "busy", "stale_revision", "stale_preview_snapshot", "invalid_preview_snapshot",
                     "preview_closed", "unknown_document", "sketch_edit_active", "document_changed",
                     "unmanaged_transaction", "sketch_history_changed", "sketch_editor_open", "user_editing", "checkpoint_failed"):
            self.assertFalse(confirm_gate.remembers_rejection({"code": code, "message": "x"}), code)
        self.assertFalse(confirm_gate.remembers_rejection(None))
        self.assertFalse(confirm_gate.remembers_rejection({}))
        self.assertFalse(confirm_gate.remembers_rejection({"code": ""}))

    # -- the adapter ---------------------------------------------------------------------------

    def test_flush_accepts_a_valid_provisional_only_for_the_current_fields(self):
        self.plate()
        # The exact reference comes from the worker process in the app; here an in-process
        # evaluate stands in for it, run before the adapter binds its source generation
        # (its snapshot saveCopy would otherwise read as a generation change).
        exact = self.evaluator().evaluate(dict(op="pad", profile="Profile", length=2, reversed=False))
        self.assertTrue(exact.valid, exact.error)
        adapter = self.adapter()
        adapter.schedule(dict(op="pad", profile="Profile", length="2 mm", reversed=False))
        shown = adapter.result
        self.assertTrue(shown is not None and shown.provisional and not shown.valid and shown.mesh)
        self.assertEqual(shown.base_revision, self.state["revision"])
        # The exact-only default is unchanged; provisional acceptance is explicit.
        self.assertIsNone(adapter.flush())
        self.assertIsNone(adapter.current_result())
        accepted = adapter.flush(provisional=True)
        self.assertIs(accepted, shown)
        self.assertEqual(accepted.proposal["length"], 2)
        # (d) fields that changed since the shown result never commit it: neither a
        # different proposal nor newer raw text the adapter has not scheduled yet.
        self.assertIsNone(adapter.current_result(dict(op="pad", profile="Profile", length=3, reversed=False), provisional=True))
        adapter.pending = dict(op="pad", profile="Profile", length="3 mm", reversed=False)
        self.assertIsNone(adapter.flush(provisional=True))
        self.assertIs(adapter.result, shown)
        adapter.pending = dict(op="pad", profile="Profile", length="0.2 cm", reversed=False)
        self.assertIs(adapter.flush(provisional=True), shown, "equal physical intent keeps the provisional verdict")
        # (b) an exact invalid verdict for these fields disables Confirm; (c) an exact valid one commits.
        adapter._display(ExtrusionResult(False, shown.base_revision, dict(shown.proposal),
                                         error={"code": "empty_cut", "message": "No material removed"}))
        self.assertIsNone(adapter.flush(provisional=True))
        self.assertFalse(confirm_gate.accept_enabled(adapter.result))
        self.assertEqual(exact.proposal, shown.proposal, "exact and provisional evaluate the same normalized fields")
        adapter._display(exact)
        self.assertIs(adapter.flush(provisional=True), exact)
        self.assertIs(adapter.flush(), exact)

    def test_provisional_acceptance_stays_exact_only_where_no_provisional_exists(self):
        self.plate()
        adapter = self.adapter()
        for proposal in (dict(op="pocket", profile="Profile", through_all=True, reversed=False),
                         dict(op="pad", profile="Profile", end_type="through_all", reversed=False),
                         dict(op="pocket", profile="Profile", length=2, through_all=False),  # legacy: direction omitted
                         dict(op="edit_extrusion", feature="Pad", length=9)):
            adapter.schedule(proposal)
            self.assertIsNone(adapter.result, proposal)
            self.assertIsNone(adapter.flush(provisional=True), proposal)

    def test_stale_revision_blocks_a_provisional_commit(self):
        self.plate()
        adapter = self.adapter()
        adapter.schedule(dict(op="pocket", profile="Profile", length=2, through_all=False, reversed=False))
        provisional = adapter.flush(provisional=True)
        self.assertTrue(provisional is not None and provisional.provisional)
        self.call("rename_feature", feature="Profile", name="Changed profile")
        self.assertIsNone(adapter.flush(provisional=True))
        self.assertIsNone(adapter.evaluator, "a newer accepted revision ends the preview task")
        # The commit itself is guarded by the provisional's base revision, so a commit that
        # slipped past the adapter would still be rejected with the model unchanged.
        baseline = self.invariant()
        args = {key: value for key, value in provisional.proposal.items() if key != "op"}
        response = self.core.dispatch(dict(op="pocket", id="Cut", document_id=self.state["document_id"],
                                           expected_revision=provisional.base_revision, **args))
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], "stale_revision", response["error"])
        self.assertEqual(self.invariant(), baseline)

    def _exact_response(self, adapter, valid, error=None, **extra):
        """Deliver a worker verdict for the adapter's submitted proposal through the real _poll."""
        adapter.submitted = (adapter.sequence, dict(adapter.normalized), adapter.source_generation)
        adapter.evaluating = True
        adapter.worker = Mock()
        adapter.worker.poll.return_value = dict(sequence=adapter.sequence, valid=valid, error=error,
                                                measurements=None, mesh=None, milliseconds=1.0,
                                                evaluation_delta=1, cached=False, **extra)
        adapter._poll()
        self.assertFalse(adapter.evaluating)
        return adapter.result

    def test_exact_rejection_is_remembered_until_the_fields_change(self):
        self.plate()
        adapter = self.adapter()
        raw = dict(op="pocket", profile="Profile", length="2 mm", through_all=False, reversed=True)
        adapter.schedule(raw)
        self.assertTrue(adapter.result.provisional)
        rejected = self._exact_response(adapter, False, {"code": "empty_cut", "message": "No material removed"})
        self.assertFalse(rejected.valid or rejected.provisional)
        self.assertIsNone(adapter.flush(provisional=True))
        # Scheduling the same raw fields again (as every Confirm path does first) must not
        # revive the provisional: the exact rejection stands and the button stays disabled.
        adapter.timer.reset_mock()
        adapter.schedule(dict(raw))
        self.assertIs(adapter.result, rejected)
        self.assertIsNone(adapter.flush(provisional=True))
        self.assertFalse(confirm_gate.accept_enabled(adapter.result, provisional=True))
        adapter.timer.start.assert_not_called()
        adapter.schedule(dict(raw, length="0.2 cm"))
        self.assertIs(adapter.result, rejected, "equal physical intent keeps the rejection")
        # Changed fields are evaluated afresh; returning to the rejected fields recalls the verdict.
        adapter.schedule(dict(raw, length="3 mm"))
        self.assertTrue(adapter.result.provisional)
        self.assertIsNotNone(adapter.flush(provisional=True))
        adapter.schedule(dict(raw))
        self.assertIs(adapter.result, rejected)
        # A valid exact verdict after a change is kept the same way.
        adapter.schedule(dict(raw, length="3 mm"))
        valid = self._exact_response(adapter, True)
        self.assertTrue(valid.valid)
        self.assertIs(adapter.flush(), valid)
        # Worker and transport failures are not verdicts about the fields: the same proposal retries.
        adapter.schedule(dict(raw, length="4 mm"))
        failed = self._exact_response(adapter, False, {"code": "preview_failed", "message": "worker stopped"})
        self.assertFalse(failed.valid)
        adapter.schedule(dict(raw, length="4 mm"))
        self.assertTrue(adapter.result.provisional)
        self.assertIsNotNone(adapter.flush(provisional=True))

    def test_commit_rejection_is_remembered_on_the_restarted_preview(self):
        self.plate()
        adapter = self.adapter()
        raw = dict(op="pocket", profile="Profile", length=2, through_all=False, reversed=True)
        adapter.schedule(raw)
        provisional = adapter.flush(provisional=True)
        self.assertTrue(provisional is not None and provisional.provisional)
        args = {key: value for key, value in provisional.proposal.items() if key != "op"}
        response = self.core.dispatch(dict(op="pocket", id="Cut", document_id=self.state["document_id"],
                                           expected_revision=provisional.base_revision, **args))
        self.assertFalse(response["ok"], response)
        # The dialog restarts the preview (same revision) and records the commit rejection.
        adapter.schedule(raw)
        self.assertTrue(adapter.result.provisional)
        adapter.reject(provisional.proposal, response["error"])
        self.assertEqual(adapter.result.error["code"], "empty_cut")
        self.assertFalse(adapter.result.provisional)
        self.assertIsNone(adapter.flush(provisional=True))
        self.assertFalse(confirm_gate.accept_enabled(adapter.result, provisional=True))
        adapter.schedule(dict(raw))
        self.assertEqual(adapter.result.error["code"], "empty_cut", "the same fields keep the rejection")
        adapter.schedule(dict(raw, length=3))
        self.assertTrue(adapter.result.provisional, "changed fields are offered again")
        # Transient codes are not remembered.
        adapter.reject(dict(adapter.normalized), {"code": "stale_revision", "message": "changed"})
        self.assertTrue(adapter.result.provisional)

    def test_provisional_studio_add_inside_material_is_rejected_at_commit(self):
        """Part Studio Add runs result checks at commit, which is why its provisional may commit."""
        self.call("sketch_rectangle", id="StudioProfile", width=20, height=10)
        self.call("pad", id="Plate", profile="StudioProfile", length=6, operation="new")
        self.assertTrue(self.state["studio"]["enabled"])
        self.call("sketch_circle", id="Inner", x=10, y=5, diameter=4, plane="XY")
        adapter = self.adapter()
        adapter.schedule(dict(op="pad", profile="Inner", length=2, reversed=False, operation="add", merge_scope="auto"))
        provisional = adapter.flush(provisional=True)
        self.assertTrue(provisional is not None and provisional.provisional, adapter.result)
        args = {key: value for key, value in provisional.proposal.items() if key != "op"}
        baseline = self.invariant()
        response = self.core.dispatch(dict(op="pad", id="Inside", document_id=self.state["document_id"],
                                           expected_revision=provisional.base_revision, **args))
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], "empty_add", response["error"])
        self.assertEqual(self.invariant(), baseline)
        # The dialog restarts the preview and records the commit rejection on these fields.
        raw = dict(op="pad", profile="Inner", length=2, reversed=False, operation="add", merge_scope="auto")
        adapter.schedule(raw)
        self.assertTrue(adapter.result.provisional)
        renormalized = adapter.evaluator._proposal(provisional.proposal, solve=False)
        self.assertEqual(renormalized, adapter.normalized)
        adapter.reject(provisional.proposal, response["error"])
        self.assertEqual((adapter.result.error or {}).get("code"), "empty_add", adapter.result)
        self.assertFalse(adapter.result.provisional)
        self.assertIsNone(adapter.flush(provisional=True))

    def test_scoped_proposal_on_a_legacy_document_runs_the_studio_result_checks_at_commit(self):
        """A pad/pocket carrying operation or merge_scope is a Part Studio operation even on a
        document that is not a Part Studio yet, so its provisional may commit (item 5)."""
        self.plate()
        self.assertFalse(self.state["studio"]["enabled"])
        self.call("sketch_circle", id="Inner", x=10, y=5, diameter=4, plane="XY")
        self.assertTrue(confirm_gate.provisional_allowed("pad", studio=False, proposal={"operation": "add"}))
        self.assertTrue(confirm_gate.provisional_allowed("pad", studio=False, proposal={"merge_scope": "auto"}))
        self.assertFalse(confirm_gate.provisional_allowed("pad", studio=False, proposal={"length": 2}))
        self.assertFalse(confirm_gate.provisional_allowed("pad", studio=False, proposal={"operation": "add"}, editing=True))
        adapter = self.adapter()
        raw = dict(op="pad", profile="Inner", length=2, reversed=False, operation="add")
        adapter.schedule(raw)
        provisional = adapter.flush(provisional=True)
        self.assertTrue(provisional is not None and provisional.provisional, adapter.result)
        args = {key: value for key, value in provisional.proposal.items() if key != "op"}
        baseline = self.invariant()
        response = self.core.dispatch(dict(op="pad", id="Inside", document_id=self.state["document_id"],
                                           expected_revision=provisional.base_revision, **args))
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], "empty_add", response["error"])
        self.assertEqual(self.invariant(), baseline)
        adapter.schedule(raw)
        self.assertTrue(adapter.result.provisional)
        adapter.reject(provisional.proposal, response["error"])
        self.assertEqual((adapter.result.error or {}).get("code"), "empty_add", adapter.result)
        self.assertIsNone(adapter.flush(provisional=True))
        # A scoped Remove that removes nothing is rejected the same way (a studio Remove with
        # reversed=True cuts into the material; reversed=False on a top-face sketch cuts into air).
        self.call("sketch_circle", id="Above", x=10, y=5, diameter=4,
                  support={"feature": "Pad", "subelement": "Face" + str(next(
                      index + 1 for index, face in enumerate(self.doc.Pad.Shape.Faces) if abs(face.CenterOfMass.z - 6) < 1e-7))})
        adapter = self.adapter()
        adapter.schedule(dict(op="pocket", profile="Above", length=2, through_all=False, reversed=False, operation="remove"))
        provisional = adapter.flush(provisional=True)
        self.assertTrue(provisional is not None and provisional.provisional, adapter.result)
        args = {key: value for key, value in provisional.proposal.items() if key != "op"}
        baseline = self.invariant()
        response = self.core.dispatch(dict(op="pocket", id="Air", document_id=self.state["document_id"],
                                           expected_revision=provisional.base_revision, **args))
        self.assertFalse(response["ok"], response)
        # The studio result checks report a cut that touches no part of the scope as
        # empty_merge_scope (an empty_cut where a part is touched); both are remembered.
        self.assertIn(response["error"]["code"], {"empty_cut", "empty_merge_scope"}, response["error"])
        self.assertTrue(confirm_gate.remembers_rejection(response["error"]))
        self.assertEqual(self.invariant(), baseline)

    # -- the commit ----------------------------------------------------------------------------

    def test_committed_feature_from_the_provisional_proposal_matches_the_exact_preview_volume(self):
        self.plate()
        adapter = self.adapter()
        adapter.schedule(dict(op="pad", profile="Profile", length="2 mm", reversed=False))
        provisional = adapter.flush(provisional=True)
        self.assertTrue(provisional is not None and provisional.provisional)
        proposal = dict(provisional.proposal)
        exact = self.exact_through_worker(proposal)
        self.assertTrue(exact["valid"], exact["error"])
        self.assertEqual(exact["proposal"], proposal, "the exact preview evaluates the same normalized proposal")
        reference = self.evaluator().evaluate(proposal)
        self.assertTrue(reference.valid, reference.error)
        args = {key: value for key, value in proposal.items() if key != "op"}
        baseline = self.invariant()
        response = self.core.dispatch(dict(op="pad", id="Extrude", document_id=self.state["document_id"],
                                           expected_revision=provisional.base_revision, **args))
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, exact["measurements"]["volume_mm3"], delta=1e-6)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, reference.shape.Volume, delta=1e-6)
        self.assertEqual(self.doc.UndoCount, baseline[2] + 1)
        self.assertIsNotNone(self.doc.getObject("Extrude"))

    def test_provisional_remove_that_removes_nothing_is_rejected_at_commit(self):
        """The provisional path shows a mesh; the operation itself validates and keeps the model."""
        self.plate()
        adapter = self.adapter()
        adapter.schedule(dict(op="pocket", profile="Profile", length=2, through_all=False, reversed=True))
        provisional = adapter.flush(provisional=True)
        self.assertTrue(provisional is not None and provisional.provisional, adapter.result)
        args = {key: value for key, value in provisional.proposal.items() if key != "op"}
        baseline = self.invariant()
        response = self.core.dispatch(dict(op="pocket", id="Cut", document_id=self.state["document_id"],
                                           expected_revision=provisional.base_revision, **args))
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], "empty_cut", response["error"])
        self.assertEqual(self.invariant(), baseline)
