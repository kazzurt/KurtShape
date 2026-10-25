"""Contract 3.2 U1: the shared dispatch pipeline (integration plan C8, C9, C10, C11, C12).

One typed modeling step runs through Controller._model_step inside the caller's
transaction; previews run the same step on the clone, so they apply exactly the
commit's gates and report ``accepted``. Handler reports travel in the per-request
``_reports`` mapping. Inspect output is unchanged from the frozen 3.1 tree, which
the golden comparison below proves by running the frozen copy itself.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import patch

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
from kurtshape import studio
from kurtshape.core import Controller, ModelStep, NULL_WINDOW, ValidationWindow

F31 = ROOT / "runtime" / "bench" / "f31"
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
GOLDEN_HOLES = 9
# Inspect keys later 3.2 units add on purpose (each listed in OPERATION_CONTRACT
# §3.2.0 with its own test). The 3.1 golden cannot contain them, so they are
# dropped from the live output before the comparison. U1 adds none.
ADDITIVE_INSPECT_KEYS = frozenset({"modified", "modified_basis", "unsaved",  # U2b
                                   "result_checks", "result_check", "geometry_state"})  # U3 (inspect, features[], bodies[])
# Top-level-only additions: inspect ``parameters`` (U5) shares its name with feature rows' ``parameters``.
TOP_LEVEL_ADDITIVE_32 = frozenset({"parameter_set", "parameters", "other_parameter_sets"})  # U5
# Operations contract 3.2 adds (each documented in OPERATION_CONTRACT §3.2.0/§3.2.5); the
# inspect ``operations`` list grows by exactly these, so they are dropped before comparing.
NEW_OPERATIONS_32 = frozenset({"operation_schema", "close_document", "render_view",  # render_view: U4
                               "list_parameters", "create_parameter", "edit_parameter", "rename_parameter",
                               "delete_parameter",  # U5
                               "batch",  # U6
                               "set_view",  # GUI view op, 2026-10-20 (OPERATION_CONTRACT "Viewport camera")
                               "measure", "assembly_instance_source", "set_assembly_folders", "move_assembly_instances"})  # assembly UX program, 2026-10-24 (docs/assembly-ux/STATUS.md)

GOLDEN_CHILD = r'''
import json, sys
from pathlib import Path
f31, out, holes = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
sys.path[:0] = [str(f31 / "src"), str(f31 / "tools" / "perf"), str(f31 / "tests")]
import kurtshape
assert Path(kurtshape.__file__).resolve().is_relative_to(f31.resolve()), kurtshape.__file__
from bench_core import Benchmark
result = {"source": kurtshape.__file__}
for fixture in ("plate", "studio"):
    bench = Benchmark(out.parent / ("golden-" + fixture), fixture=fixture, holes=holes, repeat=1, measure=False)
    bench.build()
    result[fixture] = {str(level): bench.core.inspect(bench.doc, level) for level in (False, True, "full")}
    bench.close()
out.write_text(json.dumps(result, default=str), encoding="utf-8")
'''


def masked(value, drop=()):
    """Inspect output with run-specific values replaced: UUIDs, file paths, dropped keys.

    A feature row's ``dependencies`` is the raw native OutList; for a tool whose
    Placement expression links other objects FreeCAD orders those links by object
    pointer, which differs between processes with different allocation histories
    (3.1 behaviour, reproduced on the frozen tree). The list is compared as a multiset.
    """
    if isinstance(value, dict):
        return {key: ("<path>" if key == "native_file" else sorted(item) if key == "dependencies" and isinstance(item, list)
                      else [op for op in item if op not in NEW_OPERATIONS_32] if key == "operations" and isinstance(item, list)
                      else masked(item, drop))
                for key, item in value.items() if key not in drop}
    if isinstance(value, list):
        return [masked(item, drop) for item in value]
    if isinstance(value, str) and UUID.match(value):
        return "<uuid>"
    return value


class DispatchPipelineTests(unittest.TestCase):
    def setUp(self):
        self.initial = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="dispatch-pipeline-")
        self.core = Controller()
        self.state = None
        self.new("Pipeline")

    def tearDown(self):
        if self.core is not None:
            self.core.close()
        for name in set(App.listDocuments()) - self.initial:
            App.closeDocument(name)

    def release_controller(self):
        """Close this test's controller and documents before another Controller builds in-process.

        Two live controllers observe every document of the process; building the
        golden fixtures under one at a time keeps the comparison about the trees.
        """
        self.core.close()
        self.core = None
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
        self.state = response["result"]
        return response["result"]

    def reject(self, code, op, **args):
        revision, undo = self.state["revision"], self.doc.UndoCount
        response = self.request(op, **args)
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], code, response["error"])
        self.assertEqual((self.core._meta(self.doc).Revision, self.doc.UndoCount), (revision, undo))
        return response["error"]

    def preview(self, **proposal):
        response = self.request("preview", proposal=proposal)
        self.assertTrue(response["ok"], response)
        return response["result"]

    def mark_needs_rebuild(self):
        """A document whose stored engine stamp no longer matches: RebuildReason set, nothing else."""
        self.core._meta(self.doc).RebuildReason = "engine_changed"
        self.core._build_status(self.doc)
        self.call("inspect")
        self.assertEqual(self.state["build_status"], "needs_rebuild")
        self.assertEqual(self.state["rebuild_reason"], "engine_changed")

    # --- created_feature and created_sketches -------------------------------------

    def test_created_feature_is_reported_for_sketch_and_legacy_extrusion_ops(self):
        self.assertEqual(self.core.created_sketches, {})
        result = self.call("sketch_rectangle", id="Base", width=20, height=20)
        self.assertEqual(result["created_feature"], "Base")
        self.assertEqual(self.core.created_sketches, {}, "only create_sketch primes the lease pairing")
        result = self.call("sketch_circle", id="Round", x=5, y=5, diameter=4)
        self.assertEqual(result["created_feature"], "Round")
        result = self.call("pad", id="Block", profile="Base", length=10)
        self.assertEqual(result["created_feature"], "Block")
        self.assertNotIn("result_report", result, "legacy Pad has no studio result report")
        result = self.call("pocket", id="Cut", profile="Round", length=3, through_all=False)
        self.assertEqual(result["created_feature"], "Cut")
        self.assertEqual(self.core.created_sketches, {})
        result = self.call("create_sketch", id="Detail", plane="XY")
        self.assertEqual(result["created_feature"], "Detail")
        self.assertEqual(self.core.created_sketches,
                         {self.state["document_id"]: ("Detail", self.doc.UndoCount, self.state["revision"])})
        self.assertFalse(hasattr(self.core, "_new_sketch_name"))
        # The lease that directly follows the creation still pairs with it.
        self.call("begin_sketch_edit", feature="Detail")
        self.assertTrue(self.core.sketch_edits[self.state["document_id"]]["created"])
        self.assertEqual(self.core.created_sketches, {})
        self.call("finish_sketch_edit", cancel=True)

    def test_created_feature_in_a_sketch_lease_keeps_the_lease_rules(self):
        self.call("sketch_rectangle", id="Base", width=20, height=20)
        self.call("begin_sketch_edit", feature="Base")
        result = self.call("add_circle", sketch="Base", x=5, y=5, diameter=2)
        self.assertNotIn("created_feature", result)
        self.reject("sketch_edit_active", "create_sketch", id="Other", plane="XY")
        self.call("finish_sketch_edit")
        self.assertEqual(self.core.created_sketches, {})

    # --- preview accepted / valid (C11) and the commit gates (C9) -------------------

    def test_preview_on_a_needs_rebuild_studio_document_is_accepted_but_not_valid(self):
        self.call("sketch_rectangle", id="Base", width=20, height=20)
        self.call("pad", id="Block", profile="Base", length=10, operation="new")
        self.mark_needs_rebuild()
        preview = self.preview(op="set_parameter", feature="Base", parameter="Width", value=25)
        self.assertTrue(preview["accepted"], preview)
        self.assertFalse(preview["valid"], preview)
        self.assertIsNone(preview["error"])
        self.assertEqual(preview["build_status"], "needs_rebuild")
        self.assertIsNone(preview["measurements"])
        self.assertEqual(self.core._meta(self.doc).RebuildReason, "engine_changed", "the clone was discarded")
        result = self.call("set_parameter", feature="Base", parameter="Width", value=25)
        self.assertEqual(result["build_status"], "needs_rebuild")
        self.assertEqual(result["rebuild_reason"], "engine_changed")

    def test_single_op_preview_applies_the_legacy_single_solid_gate_exactly_as_commit(self):
        self.call("sketch_rectangle", id="Base", width=20, height=20)
        self.call("pad", id="Block", profile="Base", length=10)
        self.mark_needs_rebuild()
        # rename_feature is not gated at commit; before U1 the preview gated every proposal with a feature.
        preview = self.preview(op="rename_feature", feature="Block", name="Renamed block")
        self.assertTrue(preview["accepted"], preview)
        self.assertFalse(preview["valid"])
        self.assertEqual(preview["build_status"], "needs_rebuild")
        result = self.call("rename_feature", feature="Block", name="Renamed block")
        self.assertEqual(result["build_status"], "needs_rebuild")
        # A legacy pad is gated at commit while the Body is not valid; before U1 the
        # preview skipped that gate because the proposal names a profile, not a feature.
        self.call("sketch_rectangle", id="Boss", x=5, y=5, width=5, height=5)
        preview = self.preview(op="pad", id="Boss1", profile="Boss", length=4)
        self.assertFalse(preview["accepted"], preview)
        self.assertFalse(preview["valid"])
        self.assertEqual(preview["error"]["code"], "build_failed")
        self.assertEqual(preview["error"]["message"], "Operation must produce one valid solid")
        error = self.reject("build_failed", "pad", id="Boss1", profile="Boss", length=4)
        self.assertEqual(error["message"], preview["error"]["message"])

    def test_preview_of_a_valid_proposal_is_accepted_and_valid_with_its_report(self):
        self.call("sketch_rectangle", id="Base", width=20, height=20)
        self.call("pad", id="Block", profile="Base", length=10, operation="new")
        self.call("sketch_rectangle", id="Boss", x=5, y=5, width=5, height=5)
        # The boss sketch lies on XY at the block's base: 15 mm up adds the 5 mm above the block.
        preview = self.preview(op="pad", id="Boss1", profile="Boss", length=15, operation="add", merge_scope="auto")
        self.assertTrue(preview["accepted"], preview)
        self.assertTrue(preview["valid"])
        self.assertEqual(preview["build_status"], "valid")
        self.assertEqual(preview["result_report"]["feature"], "Boss1")
        self.assertEqual(preview["result_report"]["operation"], "add")
        self.assertAlmostEqual(preview["measurements"]["volume_mm3"], 20 * 20 * 10 + 5 * 5 * 5, places=3)
        self.assertEqual(self.core._reports, {}, "no report leaks out of the preview")
        self.assertEqual(set(App.listDocuments()) - self.initial, {self.doc.Name}, "the clone is gone")

    def test_preview_closes_a_foreign_app_transaction_left_by_the_proposal(self):
        """A rogue app-level transaction that outlives the clone's commit is aborted by the cleanup.

        FreeCAD semantics (probed on 1.1.4): App.setActiveTransaction while the clone's
        transaction is pending commits that transaction and installs the rogue; the
        clone's later commitTransaction then has nothing to commit and leaves the rogue
        active, where the source document's next property write would join it. The
        rogue is injected in the last controller call before the clone's commit.
        """
        self.call("sketch_rectangle", id="Base", width=20, height=20)
        self.call("pad", id="Block", profile="Base", length=10, operation="new")
        original = Controller._geometry
        rogue_ids = []

        def rogue(controller, doc, objects=None, measure=None):
            result = original(controller, doc, objects, measure)
            if doc is not self.doc:
                rogue_ids.append(App.setActiveTransaction("rogue app-level transaction"))
            return result

        closes = []
        close = App.closeActiveTransaction

        def recording_close(*args):
            closes.append((args, tuple(App.getActiveTransaction() or ())))
            return close(*args)

        with patch.object(Controller, "_geometry", rogue), patch.object(App, "closeActiveTransaction", recording_close):
            preview = self.preview(op="set_parameter", feature="Base", parameter="Width", value=25)
        self.assertTrue(preview["accepted"], preview)
        self.assertEqual(len(rogue_ids), 1, "the rogue was opened once, on the clone")
        self.assertIn(((True,), ("rogue app-level transaction", rogue_ids[0])), closes,
                      "cleanup aborts the transaction it did not find active before the preview")
        self.assertFalse(App.getActiveTransaction())
        self.assertFalse(self.doc.HasPendingTransaction)
        self.assertEqual(set(App.listDocuments()) - self.initial, {self.doc.Name})
        undo_before = self.doc.UndoCount
        self.call("set_parameter", feature="Base", parameter="Width", value=25)
        self.assertEqual(self.doc.UndoCount, undo_before + 1)
        self.assertEqual(self.doc.UndoNames[0], "KurtShape: set_parameter")

    # --- _reports (C8) and the window (C10) ---------------------------------------

    def test_reports_mapping_carries_result_and_repair_reports(self):
        self.call("sketch_rectangle", id="Base", width=20, height=10)
        self.call("pad", id="Plate", profile="Base", length=6, operation="new")
        plate_volume = sum(part.Shape.Volume for part in studio.current_parts(self.doc))
        self.call("sketch_circle", id="Hole", x=5, y=5, diameter=2, plane="XY")
        result = self.call("pocket", id="Cut", profile="Hole", length=2, through_all=False, reversed=False, operation="remove")
        report = result["result_report"]
        self.assertEqual((report["feature"], report["operation"]), ("Cut", "remove"))
        self.assertLess(report["volume_delta_mm3"], 0)
        self.assertEqual(self.core._reports, {}, "_model_step pops the per-step keys")
        # A native representative-only delete leaves the Cut's helpers orphaned.
        self.doc.openTransaction("legacy representative-only delete")
        self.doc.removeObject("Cut")
        self.doc.commitTransaction()
        self.core._recompute(self.doc)
        self.call("inspect")
        groups = self.request("orphan_helpers")["result"]["groups"]
        self.assertEqual([group["owner"] for group in groups], ["Cut"])
        preview = self.preview(op="repair_orphan_helpers")
        self.assertTrue(preview["accepted"], preview)
        self.assertEqual(preview["repair_report"]["removed_groups"], ["Cut"], "a preview carries the step reports")
        self.assertEqual([group["owner"] for group in self.request("orphan_helpers")["result"]["groups"]], ["Cut"])
        result = self.call("repair_orphan_helpers")
        self.assertEqual(result["repair_report"]["removed_groups"], ["Cut"])
        self.assertEqual(set(result["repair_report"]["removed_objects"]), set(groups[0]["objects"]))
        self.assertNotIn("result_report", result)
        self.assertEqual(self.core._reports, {})
        self.assertAlmostEqual(sum(part.Shape.Volume for part in studio.current_parts(self.doc)), plate_volume)
        # A rejected step leaves nothing behind for the next request.
        self.reject("missing_reference", "pad", id="Nope", profile="Missing", length=3, operation="add")
        self.assertEqual(self.core._reports, {})
        self.assertNotIn("result_report", self.call("inspect"))

    def test_model_step_returns_the_created_feature_and_its_reports(self):
        self.call("sketch_rectangle", id="Base", width=20, height=20)
        revision, undo = self.state["revision"], self.doc.UndoCount
        self.doc.openTransaction("probe")
        try:
            step = self.core._model_step(self.doc, {"op": "pad", "id": "Block", "profile": "Base", "length": 10,
                                                    "operation": "new"})
        finally:
            self.doc.abortTransaction()
        self.assertIsInstance(step, ModelStep)
        self.assertEqual(step.created_feature, "Block")
        self.assertEqual(step.reports, {}, "operation:new has no result report")
        self.assertEqual(self.core._meta(self.doc).Revision, revision, "_model_step never rotates the revision")
        self.assertEqual(self.doc.UndoCount, undo)
        self.assertIsNone(self.doc.getObject("Block"), "the probe transaction was aborted")

    def test_a_base_exception_in_dispatch_never_leaves_the_ledger_entry_started(self):
        # Fable review R5 (2026-10-19): only a BaseException escapes _dispatch; the ledger entry must still
        # complete, or request_status would report the request pending until the session ends.
        class Interrupted(BaseException):
            pass

        request = {"op": "sketch_rectangle", "document_id": self.state["document_id"], "request_id": "r5-1",
                   "expected_revision": self.state["revision"], "id": "R5", "width": 5, "height": 5}
        with patch.object(self.core, "_dispatch", side_effect=Interrupted()), self.assertRaises(Interrupted):
            self.core.dispatch(request)
        status = self.core.ledger.status("r5-1")
        self.assertEqual((status["status"], status["response"]["error"]["code"]), ("failed", "operation_failed"))
        # An identical replay returns the recorded failure; it does not run the operation.
        self.assertEqual(self.core.dispatch(dict(request))["error"]["code"], "operation_failed")
        self.assertNotIn("R5", [row["id"] for row in self.core.dispatch(
            {"op": "inspect", "document_id": self.state["document_id"]})["result"]["features"]])

    def test_null_window_is_a_no_op(self):
        self.assertIsNone(NULL_WINDOW.step_done(0))
        self.assertIsNone(NULL_WINDOW.finish())
        self.assertIsNone(NULL_WINDOW.attribution("Block"))
        # U3: every managed document gets the real window; without result operations it validates nothing.
        window = self.core._validation_window(self.doc, "edit", trigger={"op": "pad"})
        self.assertIsInstance(window, ValidationWindow)
        self.assertEqual(dict(window.before.ops), {}, "a document without result operations has an empty key table")
        self.assertIsNone(window.finish(), "nothing to validate: no report, no rejection")
        self.assertIsNone(window.attribution("Block"))
        self.assertNotIn("result_check_report", self.core._reports)
        self.assertIsInstance(self.core._validation_window(self.doc, "preview"), ValidationWindow)

    def test_document_state_counts_commits_and_notes_silent_intent_changes(self):
        state = self.core.observer.state(self.doc)
        commits = state["commit_count"]
        self.call("sketch_rectangle", id="Base", width=20, height=20)
        self.assertEqual(self.core.observer.state(self.doc)["commit_count"], commits + 1)
        self.reject("missing_reference", "pad", id="Nope", profile="Missing", length=3)
        self.assertEqual(self.core.observer.state(self.doc)["commit_count"], commits + 1, "an aborted transaction is no commit")
        sketch = self.doc.getObject("Base")
        state = self.core.observer.state(self.doc)
        serial, intent = state["change_serial"], state["intent_versions"].get("Base")
        self.core.observer.note_intent_change(sketch)
        state = self.core.observer.state(self.doc)
        self.assertGreater(state["change_serial"], serial)
        self.assertEqual(state["intent_versions"]["Base"], state["change_serial"])
        self.assertNotEqual(state["intent_versions"]["Base"], intent)
        self.assertTrue(state["intent_dirty"])

    # --- the frozen 3.1 golden ----------------------------------------------------

    def test_inspect_equals_the_frozen_3_1_tree_at_every_measure_level(self):
        if not (F31 / "src" / "kurtshape" / "core.py").is_file():
            self.skipTest("frozen 3.1 tree is not present at runtime/bench/f31")
        self.release_controller()
        script = self.folder / "golden_child.py"
        script.write_text(GOLDEN_CHILD, encoding="utf-8")
        golden_path = self.folder / "golden" / "inspect.json"
        golden_path.parent.mkdir(parents=True, exist_ok=True)
        environment = dict(os.environ)
        for name in ("KURTSHAPE_SESSION_DIR", "FREECAD_USER_HOME", "TEMP", "TMP", "APPDATA", "LOCALAPPDATA"):
            location = self.folder / "f31-env" / name.lower()
            location.mkdir(parents=True, exist_ok=True)
            environment[name] = str(location)
        environment.pop("KURTSHAPE_WRITE_EVIDENCE", None)
        completed = subprocess.run([sys.executable, "-B", str(script), str(F31), str(golden_path), str(GOLDEN_HOLES)],
                                   cwd=str(F31), env=environment, capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", timeout=900,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(completed.returncode, 0, completed.stdout[-3000:] + completed.stderr[-3000:])
        golden = json.loads(golden_path.read_text(encoding="utf-8"))
        self.assertTrue(golden["source"].lower().startswith(str(F31).lower()), golden["source"])
        saved_path = list(sys.path)
        try:
            sys.path.insert(0, str(ROOT / "tools" / "perf"))
            from bench_core import Benchmark
            self.assertTrue(Path(sys.modules["bench_core"].__file__).resolve().is_relative_to(ROOT / "tools"))
            for fixture in ("plate", "studio"):
                bench = Benchmark(self.folder / ("live-" + fixture), fixture=fixture, holes=GOLDEN_HOLES, repeat=1,
                                  measure=False)
                try:
                    bench.build()
                    for level in (False, True, "full"):
                        with self.subTest(fixture=fixture, measure=level):
                            live = json.loads(json.dumps(bench.core.inspect(bench.doc, level), default=str))
                            expected = golden[fixture][str(level)]
                            self.assertEqual(masked({key: item for key, item in live.items() if key not in TOP_LEVEL_ADDITIVE_32},
                                                    ADDITIVE_INSPECT_KEYS), masked(expected))
                finally:
                    bench.close()
        finally:
            sys.path[:] = saved_path
