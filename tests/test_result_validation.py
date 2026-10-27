"""Contract 3.2 U3 (F1): result validation on edits and rebuilds.

Kurt's example: a 20x20x10 block, a 20x20 Add ("Raise", 15 mm from z=0) and a blind 3 mm
Remove ("TopCut", a 4x4 square on a datum plane at z=15). Editing Raise to 5 mm makes the Add
add nothing; editing it to 11 mm empties TopCut. Both now reject like creation would, with the
creation codes and ``validation:"history"``; rollback, rebuild and undo/redo expose failures
without rejecting; inspect reads the stamped O(1) summary; export validates pending operations.

The class runs the audit mode (every reused verdict is re-checked and compared), so a stale
reuse fails loudly here instead of silently in production.
"""
from contextlib import contextmanager
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
from kurtshape import geometry, result_checks, studio
from kurtshape.core import Controller, OperationError
from kurtshape.extrusion_preview import ExtrusionEvaluator
from kurtshape.result_checks import ResultChecks

PROPERTY = result_checks.PROPERTY
BLOCK = 20 * 20 * 10


@contextmanager
def counting():
    """Count real history checks (ResultChecks._check; the audit re-check is excluded), BRepChecks,
    per-operation fingerprints, key tables and validations."""
    counts = {"check_operation": 0, "check_shape": 0, "fingerprint": 0, "key_table": 0, "validate": 0}

    def wrap(target, name, key):
        original = getattr(target, name)

        def wrapper(*args, **kwargs):
            counts[key] += 1
            return original(*args, **kwargs)
        return patch.object(target, name, wrapper)

    with wrap(ResultChecks, "_check", "check_operation"), wrap(geometry, "check_shape", "check_shape"), \
            wrap(ResultChecks, "_fingerprint", "fingerprint"), wrap(ResultChecks, "key_table", "key_table"), \
            wrap(ResultChecks, "validate", "validate"):
        yield counts


class ResultValidationBase:
    """Shared fixture (a mixin, so the runner sees only the two registered TestCase classes)."""
    def setUp(self):
        self.initial = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="result-validation-")
        audit = patch.object(result_checks, "AUDIT", True)
        audit.start()
        self.addCleanup(audit.stop)
        self.core = Controller()
        self.core.default_measure = False  # the default level BRepChecks results on every response; count only result checks
        self.core.settings.roots.add(self.folder)
        self.state = self.core.dispatch({"op": "new", "name": "Result validation"})["result"]

    def tearDown(self):
        self.core.close()
        for name in set(App.listDocuments()) - self.initial:
            App.closeDocument(name)

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    @property
    def meta(self):
        return self.core._meta(self.doc)

    def request(self, op, **kwargs):
        return self.core.dispatch({"op": op, "document_id": self.state["document_id"],
                                   "expected_revision": self.state["revision"], **kwargs})

    def call(self, op, **kwargs):
        response = self.request(op, **kwargs)
        self.assertTrue(response["ok"], response)
        if "revision" in response["result"]:
            self.state = response["result"]
        return response["result"]

    def inspect(self, **kwargs):
        return self.call("inspect", **kwargs)

    def checks(self, state=None):
        return (state or self.inspect())["result_checks"]

    def keys(self):
        table = self.core.result_checks.key_table(self.doc, stamp=False)
        return {name: entry.key for name, entry in table.ops.items()}

    def snapshot(self):
        doc = self.doc
        return (self.meta.Revision, doc.UndoCount, sorted(obj.Name for obj in doc.Objects),
                {studio.part_id(body): None if body.Shape.isNull() else round(body.Shape.Volume, 6)
                 for body in studio.current_parts(doc)},
                getattr(self.meta, PROPERTY), self.keys())

    def reject(self, code, op, **kwargs):
        before = self.snapshot()
        response = self.request(op, **kwargs)
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], code, response["error"])
        self.assertEqual(self.snapshot(), before, "a rejected request leaves document, history, keys and verdict table unchanged")
        return response["error"]

    def preview(self, **proposal):
        response = self.core.dispatch({"op": "preview", "document_id": self.state["document_id"],
                                       "expected_revision": self.state["revision"], "proposal": proposal})
        self.assertTrue(response["ok"], response)
        return response["result"]

    # --- the model ---------------------------------------------------------------------------
    def block(self):
        self.call("sketch_rectangle", id="Base", width=20, height=20)
        self.call("pad", id="Block", profile="Base", length=10, operation="new")
        return "Body"

    def raise_(self, length=15):
        self.call("create_sketch", id="Cap", plane="XY")
        self.call("add_rectangle", sketch="Cap", width=20, height=20)
        return self.call("pad", id="Raise", profile="Cap", length=length, operation="add", merge_scope=["Body"])

    def topcut(self, depth=3):
        self.call("create_plane", id="TopPlane", origin=[0, 0, 15], normal=[0, 0, 1])
        self.call("create_sketch", id="TopSketch", support={"feature": "TopPlane"})
        self.call("add_rectangle", sketch="TopSketch", x=8, y=8, width=4, height=4)
        # The sketch normal points +Z (away from the material); reversed cuts down into Raise (z 12..15).
        return self.call("pocket", id="TopCut", profile="TopSketch", length=depth, through_all=False, reversed=True,
                         operation="remove", merge_scope=["Body"])

    def hole(self):
        self.call("sketch_circle", id="HoleSketch", x=10, y=10, diameter=4, plane="XY")
        return self.call("pocket", id="Hole", profile="HoleSketch", through_all=True, operation="remove", merge_scope=["Body"])

    def kurt_model(self):
        self.block()
        self.raise_(15)
        return self.topcut()

    def tool(self, feature="Raise"):
        return getattr(self.doc.getObject(feature), "KurtShapeTool")

    def native_length(self, value, feature="Raise", inspect=True):
        """A native change outside any managed operation (property editor, console); refreshes the revision."""
        self.tool(feature).LengthFwd = value
        self.doc.recompute()
        if inspect:
            self.state = self.inspect()

    def booleans(self, feature):
        return [self.doc.getObject(name) for name in getattr(self.doc.getObject(feature), "KurtShapeOutputTips", [])]

    def report_rows(self, state):
        return {row["feature"]: row for row in state["result_check_report"]["checked"]}


class ResultValidationTests(ResultValidationBase, unittest.TestCase):
    def test_edit_extrusion_that_empties_an_add_rejects_like_creation(self):
        self.kurt_model()
        self.assertEqual(self.checks()["status"], "valid")
        error = self.reject("empty_add", "edit_extrusion", feature="Raise", length=5)
        self.assertEqual((error["feature"], error["validation"], error["previous_status"]), ("Raise", "history", "valid"))
        self.assertEqual(error["trigger"], {"op": "edit_extrusion", "feature": "Raise"})
        self.assertTrue(error["message"].startswith("Change not applied"), error["message"])
        self.assertEqual(error["refine"]["retried_unrefined"], True)
        self.assertEqual(error["refine"]["refined_failure"]["code"], "empty_add")
        # The same 5 mm Add created directly gives the same code (creation path, unchanged).
        preview = self.preview(op="pad", id="Low", profile="Cap", length=5, operation="add", merge_scope=["Body"])
        self.assertFalse(preview["valid"])
        self.assertEqual(preview["error"]["code"], "empty_add")

    def test_direct_and_indirect_parameter_edits_reject_empty_results(self):
        self.kurt_model()
        self.reject("empty_add", "set_parameter", feature="Raise", parameter="Length", value=5)
        self.reject("empty_add", "set_expression", feature="Raise", parameter="Length", expression="5 mm")
        self.reject("empty_add", "set_expression", feature="Raise", parameter="Length", expression="Cap.Constraints.Width / 4")
        # Indirect: an upstream dimension drives the depth through an accepted expression.
        self.call("set_expression", feature="Raise", parameter="Length", expression="Cap.Constraints.Width * 0.75")
        self.reject("empty_add", "set_parameter", feature="Cap", parameter="Width", value=20 / 3)
        state = self.call("set_expression", feature="Raise", parameter="Length", expression="Cap.Constraints.Width * 0.7")
        rows = self.report_rows(state)
        self.assertAlmostEqual(rows["Raise"]["volume_delta_mm3"], 20 * 20 * 4, places=5)
        self.assertAlmostEqual(rows["TopCut"]["volume_delta_mm3"], -4 * 4 * 2, places=5)
        self.assertEqual(state["result_check_report"]["status"], "valid")

    def test_upstream_edit_validates_downstream_at_its_history_position(self):
        self.block()
        self.raise_(15)
        self.hole()
        self.topcut()
        self.call("fillet", id="Round", part="Body", radius=0.3, edges=[{"selector": {
            "kind": "geometry", "geometry": "circle", "radius": 2.0,
            "query": {"kind": "owned_by", "part": "Body", "entity_type": "edge"}}, "all": True}])
        topcut = self.doc.getObject("TopCut")
        body = self.doc.getObject(topcut.KurtShapeOutputParts[0])
        tip = self.doc.getObject(topcut.KurtShapeOutputTips[0])
        self.assertNotEqual(body.Tip.Name, tip.Name, "the fillet moved the output Body's Tip past TopCut's result")
        error = self.reject("empty_cut", "edit_extrusion", feature="Raise", length=11)
        self.assertEqual((error["feature"], error["trigger"]), ("TopCut", {"op": "edit_extrusion", "feature": "Raise"}))
        state = self.call("edit_extrusion", feature="Raise", length=14)
        rows = self.report_rows(state)
        self.assertTrue(rows["Raise"]["affected"] and rows["TopCut"]["affected"], rows)
        verdict = self.core.result_checks.verdicts[self.keys()["TopCut"]]
        self.assertAlmostEqual(verdict["parts"][0]["volume_after_mm3"], tip.Shape.Volume, places=6)
        self.assertNotAlmostEqual(verdict["parts"][0]["volume_after_mm3"], body.Shape.Volume, places=3)
        self.assertEqual(self.checks()["status"], "valid")

    def test_rejected_edit_restores_document_and_history(self):
        self.kurt_model()
        self.call("set_parameter", feature="Raise", parameter="Length", value=14)
        undo_count = self.doc.UndoCount
        self.reject("empty_add", "edit_extrusion", feature="Raise", length=5)
        self.assertEqual(self.doc.UndoCount, undo_count)
        state = self.call("undo")
        self.assertAlmostEqual(self.tool().LengthFwd.Value, 15)
        self.assertEqual(state["result_checks"]["status"], "valid", state["result_checks"])

    def test_accepted_edit_leaves_status_current(self):
        self.kurt_model()
        self.call("set_parameter", feature="Raise", parameter="Length", value=14)
        self.call("rename_feature", feature="Raise", name="Lifted")
        self.call("set_part_appearance", part="Body", color=[0.5, 0.5, 0.5])
        with counting() as counts:
            state = self.inspect()
        self.assertEqual(state["result_checks"]["status"], "valid", state["result_checks"])
        self.assertEqual((counts["key_table"], counts["check_operation"], counts["fingerprint"]), (0, 0, 0))
        self.assertEqual(state["bodies"][0]["result_check"], "valid")
        self.assertEqual(state["bodies"][0]["geometry_state"], "current")
        self.assertEqual({f["id"]: f.get("result_check") for f in state["features"] if f.get("result_check")},
                         {"Raise": "valid", "TopCut": "valid"})
        # A pre-existing failure stays visible across an unrelated accepted edit.
        self.native_length(11)
        self.call("rebuild")
        self.assertEqual(self.checks()["status"], "failed")
        state = self.call("sketch_rectangle", id="Aside", x=50, width=5, height=5)
        self.assertEqual(state["build_status"], "failed")
        self.assertEqual([row["feature"] for row in state["build_errors"] if row.get("source") == "result_check"], ["TopCut"])
        self.assertEqual(state["result_checks"]["failed"][0]["code"], "empty_cut")

    def test_unchanged_history_is_not_rechecked_or_fingerprinted(self):
        # Production counts: the audit re-check (test mode) would add one BRepCheck per reused verdict.
        audit_off = patch.object(result_checks, "AUDIT", False)
        audit_off.start()
        self.addCleanup(audit_off.stop)
        self.block()
        with counting() as counts:
            self.raise_(15)
        self.assertEqual(counts["check_shape"], 1, "creation runs its own BRepCheck once")
        self.assertEqual(counts["check_operation"], 0, "the post-dispatch validator reuses the seeded verdict")
        self.assertEqual(counts["fingerprint"], 2, "one seed fingerprint plus one confirmation")
        with counting() as counts:
            self.topcut()
        self.assertEqual((counts["check_shape"], counts["check_operation"]), (1, 0))
        with counting() as counts:
            state = self.call("edit_extrusion", feature="Raise", length=14)
        self.assertEqual(counts["check_operation"], 2, "the edited Add and its downstream Remove")
        self.assertEqual(state["result_check_report"]["reused"], 0)
        with counting() as counts:
            self.call("rename_feature", feature="Raise", name="Lifted")
            self.call("set_part_appearance", part="Body", color=[0.2, 0.4, 0.6])
            self.call("create_sketch", id="Side", plane="XZ")
            self.call("add_rectangle", sketch="Side", x=30, width=2, height=2)
        self.assertEqual((counts["check_operation"], counts["fingerprint"]), (0, 0), counts)
        with counting() as counts:
            self.call("rebuild")
        self.assertEqual(counts["check_operation"], 0, counts)
        with counting() as counts:
            self.call("undo")
            self.call("redo")
        self.assertEqual(counts["check_operation"], 0, counts)
        with counting() as counts:
            self.inspect()
        self.assertEqual((counts["check_operation"], counts["key_table"]), (0, 0), counts)

    def test_rollback_navigation_exposes_but_never_rejects(self):
        self.kurt_model()
        order = self.state["studio"]["feature_order"]
        self.call("rollback", index=order.index("TopCut"))
        state = self.call("edit_extrusion", feature="Raise", length=11)
        self.assertEqual(state["result_checks"]["status"], "valid", "the held TopCut does not count")
        state = self.call("rollback", index=len(order))
        self.assertEqual(state["build_status"], "failed")
        self.assertEqual(state["result_check_report"]["mode"], "navigate")
        self.assertEqual([row["feature"] for row in state["result_check_report"]["failed"]], ["TopCut"])
        self.assertEqual(state["result_checks"]["failed"][0]["code"], "empty_cut")
        with counting() as counts:
            self.call("rollback", index=len(order) - 1)
            self.call("rollback", index=len(order))
        self.assertEqual(counts["check_operation"], 0, "single steps reuse verdicts")
        state = self.call("edit_extrusion", feature="Raise", length=14)
        self.assertEqual((state["build_status"], state["result_checks"]["status"]), ("valid", "valid"))

    def test_native_change_outside_transaction_is_pending_and_export_validates(self):
        self.kurt_model()
        self.native_length(11, inspect=False)
        with counting() as counts:
            state = self.inspect()
        self.state = state
        self.assertEqual(state["build_status"], "valid")
        self.assertEqual((state["result_checks"]["status"], state["result_checks"]["reason"]), ("pending", "native_change"))
        self.assertEqual(counts["check_operation"], 0)
        path = self.folder / "pending.step"
        response = self.request("export", path=str(path))
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], "build_failed")
        self.assertIn("TopCut", [row.get("feature") for row in response["error"]["features"]])
        self.assertFalse(path.exists())
        self.state = self.inspect()
        revision = self.state["revision"]
        state = self.call("check_geometry")
        self.assertEqual(state["result_check_report"]["status"], "failed")
        self.assertEqual(state["revision"], revision)
        self.assertEqual(state["build_status"], "failed")

    def test_stale_failure_survives_an_unrelated_edit(self):
        self.kurt_model()
        self.call("sketch_rectangle", id="Aside", x=50, width=5, height=5)
        self.native_length(11)
        state = self.call("check_geometry")
        self.assertEqual(state["result_checks"]["status"], "failed")
        self.native_length(12)  # still empty; the table is stale again
        self.assertEqual((self.state["result_checks"]["status"], self.state["result_checks"]["failed"][0]["stale"]), ("failed", True))
        self.assertEqual((self.state["bodies"][0]["result_check"], self.state["bodies"][0]["build_status"]), ("failed", "failed"),
                         "the part row follows the stale failure")
        with counting() as counts:
            state = self.call("undo")
        self.assertEqual(counts["check_operation"], 0, "report mode never checks")
        self.assertEqual((state["build_status"], state["result_checks"]["status"]), ("failed", "failed"),
                         "a known failure never clears without revalidating its operation")
        self.assertTrue(state["result_checks"]["failed"][0]["stale"])
        self.assertEqual(state["bodies"][0]["result_check"], "failed")
        with counting() as counts:
            state = self.call("redo")
        self.assertEqual((counts["check_operation"], state["build_status"]), (0, "failed"))
        with counting() as counts:
            state = self.call("sketch_rectangle", id="Aside2", x=60, width=5, height=5)
        self.assertEqual(counts["check_operation"], 1, "an edit revalidates the previously failed operation")
        self.assertEqual([(row["feature"], row["stale"]) for row in state["result_checks"]["failed"]], [("TopCut", False)])
        self.native_length(15)
        state = self.call("sketch_rectangle", id="Aside3", x=70, width=5, height=5)
        self.assertEqual((state["build_status"], state["result_checks"]["status"]), ("valid", "valid"),
                         "revalidating the operation clears the failure")

    def test_label_only_native_change_keeps_status_valid(self):
        self.kurt_model()
        self.doc.getObject("Raise").Label = "Lifted"
        with counting() as counts:
            state = self.inspect()
        self.state = state
        self.assertEqual(state["result_checks"]["status"], "valid", state["result_checks"])
        self.assertNotIn("reason", state["result_checks"])
        self.assertEqual(counts["check_operation"], 0)

    def test_recovery_after_correcting_a_failure(self):
        self.kurt_model()
        self.native_length(11)
        state = self.call("check_geometry")
        self.assertEqual(state["result_checks"]["status"], "failed")
        state = self.call("sketch_rectangle", id="Aside", x=50, width=5, height=5)
        self.assertEqual([row["feature"] for row in state["result_checks"]["failed"]], ["TopCut"])
        state = self.call("edit_extrusion", feature="Raise", length=12)
        self.assertEqual(state["result_checks"]["status"], "failed", "an edit affecting an already failed op is accepted")
        state = self.call("edit_extrusion", feature="Raise", length=15)
        self.assertEqual((state["build_status"], state["result_checks"]["status"]), ("valid", "valid"))
        path = self.folder / "recovered.step"
        self.call("export", path=str(path))
        self.assertTrue(path.exists())

    def test_refine_retry_on_edit_is_transactional_and_reported(self):
        self.kurt_model()
        forced = {"TopCut"}
        real = studio.check_operation

        def failing_refined(doc, rep, kernel=True, facts=None):
            if rep.Name in forced and studio.refine_state(rep)["applied"]:
                raise OperationError("empty_cut", "forced refined failure", feature=rep.Name, part="Body")
            return real(doc, rep, kernel=kernel, facts=facts)

        with patch.object(result_checks, "AUDIT", False), patch.object(studio, "check_operation", failing_refined):
            state = self.call("edit_extrusion", feature="Raise", length=14)
            row = self.report_rows(state)["TopCut"]
            self.assertEqual([r["feature"] for r in state["result_check_report"]["checked"]].count("TopCut"), 1,
                             "the retried operation has one checked row")
            self.assertEqual(state["result_check_report"]["retry"], "TopCut")
            self.assertEqual({k: row["refine"][k] for k in ("requested", "applied", "retried_unrefined")},
                             {"requested": True, "applied": False, "retried_unrefined": True})
            self.assertEqual(row["refine"]["refined_failure"]["code"], "empty_cut")
            self.assertTrue(all(boolean.Refine is False for boolean in self.booleans("TopCut")))
            self.call("undo")
            self.assertTrue(all(boolean.Refine is True for boolean in self.booleans("TopCut")), "undo restores Refine")
            forced = {"Raise", "TopCut"}
            error = self.reject("empty_cut", "edit_extrusion", feature="Raise", length=13)
            self.assertEqual(error["feature"], "TopCut")
            self.assertTrue(error["refine"]["hint"].startswith("One unrefined retry"), error["refine"])
            self.assertTrue(all(boolean.Refine is True for boolean in self.booleans("Raise")), "the abort undid the retry")
        self.core.result_checks.verdicts.clear()  # verdicts produced by the forced checker must not be reused
        self.call("sketch_circle", id="SideSketch", x=3, y=3, diameter=2, plane="XY")
        self.call("pocket", id="Side", profile="SideSketch", through_all=True, operation="remove", refine=False)
        state = self.call("edit_extrusion", feature="Raise", length=14)
        self.assertEqual(self.report_rows(state)["Side"]["refine"],
                         {"requested": False, "applied": False, "retried_unrefined": False})

    def test_finish_sketch_edit_validates_against_the_lease_baseline(self):
        self.kurt_model()
        self.call("begin_sketch_edit", feature="TopSketch")
        with counting() as counts:
            self.call("set_parameter", feature="TopSketch", parameter="OriginX", value=100)
        self.assertEqual(counts["validate"], 0, "in-lease commands are not validated")
        response = self.request("finish_sketch_edit")
        self.assertFalse(response["ok"], response)
        error = response["error"]
        self.assertEqual((error["code"], error["feature"]), ("empty_cut", "TopCut"))
        self.assertEqual(error["trigger"], {"op": "finish_sketch_edit", "feature": "TopSketch"})
        self.assertFalse(error.get("refine", {}).get("retried_unrefined"), "finish never retries unrefined")
        self.state = self.inspect()
        self.assertEqual(self.state["active_sketch_edit"], "TopSketch", "the lease and its draft are kept")
        self.assertEqual(self.state["result_checks"]["reason"], "sketch_edit_active")
        state = self.call("finish_sketch_edit", cancel=True)
        self.assertEqual(state["result_checks"]["status"], "valid", state["result_checks"])
        self.assertIsNone(state["active_sketch_edit"])

    def test_gui_style_lease_finish_rejection_keeps_refine_and_draft(self):
        self.kurt_model()
        self.call("begin_sketch_edit", feature="TopSketch")
        self.call("set_parameter", feature="TopSketch", parameter="OriginX", value=100)
        if self.doc.HasPendingTransaction:
            self.doc.commitTransaction()  # native Sketcher tools commit their own transactions
        self.assertFalse(self.doc.HasPendingTransaction)
        response = self.request("finish_sketch_edit")
        self.assertEqual(response["error"]["code"], "empty_cut", response)
        self.assertTrue(all(boolean.Refine is True for boolean in self.booleans("TopCut")))
        sketch = self.doc.getObject("TopSketch")
        origin = next(c for c in sketch.Constraints if c.Name == "OriginX")
        self.assertAlmostEqual(origin.Value, 100, msg="the draft is kept for the user to fix")
        self.state = self.inspect()
        self.assertEqual(self.state["active_sketch_edit"], "TopSketch")
        self.call("finish_sketch_edit", cancel=True)
        self.assertAlmostEqual(next(c for c in self.doc.getObject("TopSketch").Constraints if c.Name == "OriginX").Value, 8)
        # An accepted finish after native commits is one undo step.
        undo_before = self.doc.UndoCount
        self.call("begin_sketch_edit", feature="TopSketch")
        self.call("set_parameter", feature="TopSketch", parameter="OriginX", value=9)
        if self.doc.HasPendingTransaction:
            self.doc.commitTransaction()
        self.call("set_parameter", feature="TopSketch", parameter="OriginY", value=9)
        state = self.call("finish_sketch_edit")
        self.assertEqual(self.doc.UndoCount, undo_before + 1)
        self.assertEqual(state["result_checks"]["status"], "valid")
        self.assertAlmostEqual(self.report_rows(state)["TopCut"]["volume_delta_mm3"], -4 * 4 * 3, places=5)

    def test_preview_and_commit_agree(self):
        self.kurt_model()
        before = self.snapshot()
        preview = self.preview(op="edit_extrusion", feature="Raise", length=11)
        self.assertFalse(preview["valid"])
        self.assertFalse(preview["accepted"])
        self.assertEqual((preview["error"]["code"], preview["error"]["feature"]), ("empty_cut", "TopCut"))
        self.assertEqual(self.snapshot(), before)
        # With a pre-existing failure an unrelated proposal is valid: the commit would be accepted.
        self.native_length(11)
        self.state = self.call("rebuild")
        self.assertEqual(self.state["result_checks"]["status"], "failed")
        preview = self.preview(op="sketch_rectangle", id="Aside", x=50, width=5, height=5)
        self.assertTrue(preview["valid"], preview)
        self.assertEqual(preview["build_status"], "failed")
        self.assertEqual([row["feature"] for row in preview["result_check_report"]["failed"]], ["TopCut"])
        state = self.call("sketch_rectangle", id="Aside", x=50, width=5, height=5)
        self.assertEqual(state["build_status"], "failed")

    def test_live_edit_preview_skips_history_validation(self):
        self.kurt_model()
        evaluator = ExtrusionEvaluator(self.core, self.doc, self.state["revision"])
        self.addCleanup(evaluator.close)
        with counting() as counts:
            result = evaluator.evaluate({"op": "edit_extrusion", "feature": "Raise", "length": 12})
        self.assertTrue(result.valid, getattr(result, "error", None))
        self.assertEqual((counts["validate"], counts["check_operation"]), (0, 0), counts)

    def test_verdicts_persist_across_save_and_reopen(self):
        self.block()
        self.raise_(15)
        self.hole()
        self.topcut()
        self.call("sketch_rectangle", id="Keep", width=16, height=16)
        self.call("pad", id="Trim", profile="Keep", length=20, operation="intersect", merge_scope=["Body"])
        self.call("sketch_circle", id="SideSketch", x=3, y=3, diameter=2, plane="XY")
        self.call("pocket", id="Side", profile="SideSketch", through_all=True, operation="remove", refine=False)
        keys = self.keys()
        self.assertEqual(self.checks()["status"], "valid")
        path = self.folder / "persisted.FCStd"
        self.call("save", path=str(path))
        App.closeDocument(self.doc.Name)
        with counting() as counts:
            response = self.core.dispatch({"op": "open", "path": str(path)})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        self.assertEqual((counts["check_operation"], counts["fingerprint"]), (0, 0), "attach computes keys only")
        self.assertEqual(self.state["result_checks"]["status"], "valid", self.state["result_checks"])
        self.assertEqual(self.keys(), keys, "keys survive save and reopen")
        step = self.folder / "persisted.step"
        with counting() as counts:
            self.call("export", path=str(step))
        self.assertTrue(step.exists())
        self.assertEqual(counts["check_operation"], 0, "persisted verdicts are confirmed by fingerprint, not rechecked")
        self.assertEqual(counts["fingerprint"], len(keys))
        sidecar = step.with_suffix(".step.json")
        self.assertTrue(sidecar.exists(), "export writes its provenance sidecar")
        self.assertEqual(json.loads(sidecar.read_text(encoding="utf-8"))["result_checks"],
                         {"status": "valid", "operations": len(keys), "checker": 1})
        # Without the property (an old file) a fresh session is pending until a check.
        self.meta.removeProperty(PROPERTY)
        self.call("save", path=str(path))
        App.closeDocument(self.doc.Name)
        self.core.close()
        self.core = Controller()
        self.core.settings.roots.add(self.folder)
        with counting() as counts:
            response = self.core.dispatch({"op": "open", "path": str(path)})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        self.assertIn(PROPERTY, self.meta.PropertiesList, "attach creates the table property")
        self.assertEqual((self.state["result_checks"]["status"], self.state["result_checks"]["reason"]), ("pending", "not_validated"))
        self.assertEqual(counts["check_operation"], 0)
        state = self.call("check_geometry")
        self.assertEqual(state["result_checks"]["status"], "valid", state["result_checks"])
        self.assertEqual(self.keys(), keys)

    def test_shared_body_growth_does_not_change_keys(self):
        self.kurt_model()
        keys = self.keys()
        seeded = {}
        remember = ResultChecks.remember

        def spy(checks, doc, name, report):
            seeded[name] = remember(checks, doc, name, report)
            return seeded[name]

        with counting() as counts, patch.object(ResultChecks, "remember", spy):
            self.call("create_sketch", id="Unrelated", body="Body", plane="XY")
            self.call("add_rectangle", sketch="Unrelated", x=30, width=2, height=2)
            self.assertEqual({k: self.keys()[k] for k in keys}, keys, "a sketch in the part's Body changes no key")
            self.call("sketch_rectangle", id="SideProfile", x=14, y=14, width=4, height=4)
            self.call("pad", id="Side", profile="SideProfile", length=20, operation="add", merge_scope=["Body"])
        self.assertEqual({k: self.keys()[k] for k in keys}, keys, "a later operation changes no upstream key")
        self.assertEqual(counts["check_operation"], 0, "nothing was rechecked")
        self.assertEqual(seeded["Side"], self.keys()["Side"], "creation key equals the post-dispatch key")
        self.call("set_parameter", feature="TopSketch", parameter="Width", value=3)
        changed = self.keys()
        self.assertEqual(changed["Raise"], keys["Raise"])
        self.assertNotEqual(changed["TopCut"], keys["TopCut"], "an input edit changes the downstream key")

    def test_delete_of_a_consumed_operation_is_structural_first(self):
        # The result validator's cascade hint is reachable only for deletions that pass the structural
        # gate; deleting an operation another result consumes is refused there (3.1 behaviour).
        self.kurt_model()
        error = self.reject("external_dependency", "delete_feature", feature="Raise")
        self.assertNotIn("validation", error)
        error = self.reject("external_dependency", "delete_feature", feature="Raise", cascade=True)
        self.assertEqual(error["feature"], "TopPlane", "cascade covers helpers, not later features")
        self.call("delete_features", features=["TopCut", "TopSketch", "TopPlane"])
        state = self.call("delete_feature", feature="Raise")
        self.assertIsNone(self.doc.getObject("Raise"))
        self.assertIn(state["result_checks"]["status"], {"valid", "not_applicable"}, state["result_checks"])
        self.assertEqual(state["build_status"], "valid")

    def test_check_geometry_during_lease_reports_pending(self):
        self.kurt_model()
        self.call("begin_sketch_edit", feature="TopSketch")
        stored = getattr(self.meta, PROPERTY)
        revision = self.state["revision"]
        with counting() as counts:
            state = self.call("check_geometry")
        report = state["result_check_report"]
        self.assertEqual((report["mode"], report["status"], report["reason"]), ("check", "pending", "sketch_edit_active"))
        self.assertEqual(counts["check_operation"], 0)
        self.assertEqual(getattr(self.meta, PROPERTY), stored, "nothing is persisted during a lease")
        self.assertEqual(state["revision"], revision)
        self.call("finish_sketch_edit", cancel=True)

    def test_rebuild_after_native_change_exposes_but_does_not_reject(self):
        self.kurt_model()
        self.native_length(11)
        state = self.call("rebuild")
        self.assertEqual(state["build_status"], "failed")
        self.assertEqual(state["result_check_report"]["mode"], "rebuild")
        self.assertEqual([row["feature"] for row in state["result_check_report"]["failed"]], ["TopCut"])
        self.assertEqual([row for row in state["build_errors"] if row.get("source") == "result_check"][0]["code"], "empty_cut")
        self.assertEqual(state["bodies"][0]["result_check"], "failed")
        self.assertEqual(state["bodies"][0]["build_status"], "failed")

    def test_prepare_jobs_validate_pending_then_capture(self):
        self.kurt_model()
        self.native_length(14)
        # The fresh boolean's plane frames acquire signed zero components on
        # native restore. A saved/reopened model has stable exact transport,
        # while its pending result operations still need validation.
        path = self.folder / "pending-saved-model.FCStd"
        self.call("save", path=str(path))
        self.call("close_document")
        response = self.core.dispatch({"op": "open", "path": str(path), "measure": False})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        self.assertEqual(self.checks()["status"], "pending")
        key = self.core.snapshot_key(self.doc)
        from kurtshape.geometry_check_worker import source_roundtrip_stable
        admission = []
        def admit(doc, targets):
            stable = source_roundtrip_stable(doc, targets)
            admission.append((counts["check_operation"], stable))
            return stable
        with counting() as counts, patch("kurtshape.geometry_check_worker.source_roundtrip_stable", side_effect=admit):
            bundle = self.core.prepare_geometry_check(self.doc)
        self.assertIsNotNone(bundle, "a pending model validates synchronously, then captures")
        bundle["worker"].close()
        self.assertTrue(bundle["worker"].cleanup_complete.wait(15))
        self.assertEqual(admission, [(2, True)], "validation precedes real exact-transport admission")
        self.assertEqual(counts["check_operation"], 2, counts)
        self.assertEqual(self.core.snapshot_key(self.doc), key, "the verdict table write leaves the snapshot key alone")
        self.assertEqual(self.checks()["status"], "valid")
        self.native_length(11)
        self.assertIsNone(self.core.prepare_step_export(self.doc, str(self.folder / "blocked.step")),
                          "a failing pending operation blocks the capture through the BuildStatus gate")
        self.assertEqual(self.meta.BuildStatus, "failed")
        self.assertEqual(self.checks()["status"], "failed")
        self.state = self.inspect()
        response = self.request("export", path=str(self.folder / "blocked.step"))
        self.assertEqual(response["error"]["code"], "build_failed", response)

    def test_prepare_jobs_validates_pending_before_inexact_archive_fallback(self):
        from kurtshape.geometry_check_worker import source_roundtrip_stable, target_fingerprints
        self.kurt_model()
        self.native_length(14)
        self.assertEqual(self.checks()["status"], "pending")
        key = self.core.snapshot_key(self.doc)
        targets = [obj.Name for obj in self.core._geometry_check_targets(self.doc)]
        before = target_fingerprints(self.doc, targets)
        admission = []
        def admit(doc, names):
            stable = source_roundtrip_stable(doc, names)
            admission.append((counts["check_operation"], stable))
            return stable
        factory = Mock(side_effect=AssertionError("An inexact archive must use synchronous checking"))
        with counting() as counts, patch("kurtshape.geometry_check_worker.source_roundtrip_stable", side_effect=admit):
            bundle = self.core.prepare_geometry_check(self.doc, worker_factory=factory)
        self.assertIsNone(bundle)
        factory.assert_not_called()
        self.assertEqual(admission, [(2, False)], "pending validation runs even when transport is ineligible")
        self.assertEqual(counts["check_operation"], 2, counts)
        self.assertEqual(self.core.snapshot_key(self.doc), key)
        self.assertEqual(self.checks()["status"], "valid")
        state = self.call("check_geometry")
        self.assertEqual(state["geometry_check"], "valid")
        self.assertEqual(state["build_status"], "valid")
        self.assertEqual(target_fingerprints(self.doc, targets), before)

    # --- Contract 3.2 U5: parameters reach the result-check keys (C17) -------------------------
    def test_parameter_edit_emptying_add_rejects_empty_add_and_keeps_accepted(self):
        self.block()
        self.call("create_parameter", name="cap_height", type="length", value=15)
        self.raise_(15)
        self.call("edit_extrusion", feature="Raise", expression="cap_height")
        error = self.reject("empty_add", "edit_parameter", name="cap_height", value=5)
        self.assertEqual(error["parameter"]["accepted"]["value"], 15.0)
        self.assertEqual((error["validation"], error["feature"]), ("history", "Raise"))
        self.assertEqual(self.checks()["status"], "valid")

    def test_parameter_edit_keeps_unrelated_result_keys(self):
        self.kurt_model()  # block, Raise (Add), TopCut (Remove)
        self.call("create_parameter", name="cut_depth", type="length", value=3)
        self.call("edit_extrusion", feature="TopCut", expression="cut_depth")
        # Raise reads its own parameter: its key holds the set-reading formula, so the set changing must not re-key it.
        self.call("create_parameter", name="raise_height", type="length", value=15)
        self.call("edit_extrusion", feature="Raise", expression="raise_height")
        before = self.keys()
        with patch.object(result_checks, "AUDIT", True):
            self.call("edit_parameter", name="cut_depth", value=2)
        self.assertEqual(self.core.result_checks.audit_mismatches, [], "every reused verdict matches a fresh check")
        after = self.keys()
        self.assertEqual(after["Raise"], before["Raise"], "a late parameter edit leaves earlier result keys unchanged")
        self.assertNotEqual(after["TopCut"], before["TopCut"], "its consumer is re-keyed")
        self.call("rename_parameter", name="cut_depth", new_name="pocket_depth")
        self.assertEqual(self.keys(), after, "a rename changes no key")
        self.call("edit_parameter", name="pocket_depth", value=2)
        self.assertEqual(self.keys(), after, "a no-op edit changes no key")
        self.call("delete_parameter", name="pocket_depth", freeze_consumers=True)
        self.assertEqual(self.keys(), after, "freezing changes no key")
        self.assertEqual(self.checks()["status"], "valid")



class ResultValidationPerfTests(ResultValidationBase, unittest.TestCase):
    def setUp(self):
        support.perf_only(self)
        super().setUp()

    def test_plate_edit_checks_only_affected_operations(self):
        self.call("sketch_rectangle", id="Base", width=40, height=40)
        self.call("pad", id="Plate", profile="Base", length=10, operation="new")
        names = []
        for index in range(16):
            sketch, hole = f"H{index}S", f"H{index}"
            self.call("sketch_circle", id=sketch, x=5 + (index % 4) * 10, y=5 + (index // 4) * 10, diameter=3, plane="XY")
            self.call("pocket", id=hole, profile=sketch, through_all=True, operation="remove")
            names.append(hole)
        self.assertEqual(self.checks()["status"], "valid")
        with counting() as counts:
            state = self.call("set_parameter", feature="H0S", parameter="Diameter", value=4)
        self.assertEqual(counts["check_operation"], 16, "every downstream Remove consumes the changed result")
        self.assertEqual(state["result_check_report"]["status"], "valid")
        with counting() as counts:
            self.call("rebuild")
        self.assertEqual(counts["check_operation"], 0)
        with counting() as counts:
            self.call("undo")
        self.assertEqual(counts["check_operation"], 0)
        with counting() as counts:
            self.call("rename_feature", feature="H5", name="Fifth")
        self.assertEqual((counts["check_operation"], counts["fingerprint"]), (0, 0))
        report = self.core.timings.report()
        self.assertIn("result_validation", report)
        self.assertIn("result_keys", report)


if __name__ == "__main__":
    unittest.main()
