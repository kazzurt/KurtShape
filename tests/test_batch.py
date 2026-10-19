"""Contract 3.2 U6 (F4): atomic batches (BatchTests) and their bridge reconciliation (BatchBridgeTests).

Every rejection asserts the document is unchanged: revision, undo names, objects, intent signature
and part volumes (``state()``); pre-mutation rejections also keep the redo list.
"""
import ast
import json
import os
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch
import urllib.request

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
from kurtshape import batch, studio
from kurtshape.core import Controller, intent_signature
sys.path.insert(0, str(ROOT / "tools"))
from native_validation_snapshot import content_view, parameter_record, snapshot_document

EDGE_NEAR = {"kind": "closest", "point": [20, 10, 10], "query": {"kind": "owned_by", "part": "Body", "entity_type": "edge"}}


def rounded(value, digits=6):
    if isinstance(value, float):
        return 0.0 if abs(value) < 10 ** -digits else round(value, digits)
    return [rounded(item, digits) for item in value] if isinstance(value, (list, tuple)) else value


def shape_signature(shape):
    """Rounded geometry: topology counts, volume, area, box and sorted vertices (as test_operation_schemas)."""
    if shape.isNull():
        return None
    box = shape.BoundBox
    return {"counts": [len(shape.Solids), len(shape.Shells), len(shape.Faces), len(shape.Edges), len(shape.Vertexes)],
            "volume": rounded(shape.Volume, 3), "area": rounded(shape.Area, 3),
            "bbox": rounded([box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax], 4) if box.isValid() else None,
            "vertices": sorted(rounded([vertex.X, vertex.Y, vertex.Z], 4) for vertex in shape.Vertexes)}


def content(doc, core):
    """content_view without the BRep text digests: an aborted studio recompute rebuilds the same solid with
    different BRep text (seen on Block/BaseFeature), so ``geometry`` compares the solid itself instead."""
    view = content_view(snapshot_document(doc, core))
    for row in view["objects"]:
        for facts in row.get("shapes", {}).values():
            facts.pop("brep_sha256", None)
    return view


def differences(left, right, path="", found=None):
    """Up to ten paths where two snapshots differ (readable failures of the rollback oracle)."""
    found = [] if found is None else found
    if len(found) >= 10:
        return found
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right), key=str):
            differences(left.get(key), right.get(key), path + "." + str(key), found)
    elif isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        for index, (a, b) in enumerate(zip(left, right)):
            name = a.get("name") if isinstance(a, dict) else None
            differences(a, b, path + "[" + str(name or index) + "]", found)
    elif left != right:
        found.append(path + ": " + str(left)[:60] + " -> " + str(right)[:60])
    return found


class BatchFixture:
    def setUp(self):
        self.initial = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="batch-")
        self.core = Controller()
        self.core.settings.roots.add(self.folder)
        self.state = None
        self.addCleanup(self.close_all)

    def close_all(self):
        self.core.close()
        for name in set(App.listDocuments()) - self.initial:
            App.closeDocument(name)
        if App.getActiveTransaction():
            App.closeActiveTransaction(True)

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def new(self, name="Batch"):
        response = self.core.dispatch({"op": "new", "name": name})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]

    def request(self, op, **args):
        return self.core.dispatch({"op": op, "document_id": self.state["document_id"],
                                   "expected_revision": self.state["revision"], **args})

    def call(self, op, **args):
        response = self.request(op, **args)
        self.assertTrue(response["ok"], response)
        if "revision" in response["result"]:
            self.state = response["result"]
        return response["result"]

    def block(self):
        self.new()
        self.call("sketch_rectangle", id="Base", width=20, height=20)
        self.call("pad", id="Block", profile="Base", length=10, operation="new")

    def snapshot(self):
        doc = self.doc
        volumes = {studio.part_id(body): None if body.Shape.isNull() else round(body.Shape.Volume, 6)
                   for body in studio.current_parts(doc)}
        # content_view (BRep digests, placements, tips, groups, studio metadata, undo/redo) and the parameter
        # set read natively are the integration oracles (C32); the scalar keys keep messages readable.
        return {"revision": self.core._meta(doc).Revision, "undo": list(doc.UndoNames), "redo": list(doc.RedoNames),
                "objects": sorted(obj.Name for obj in doc.Objects), "intent": intent_signature(doc), "volumes": volumes,
                "pending": doc.HasPendingTransaction, "content": content(doc, self.core),
                "geometry": {obj.Name: shape_signature(obj.Shape) for obj in doc.Objects if hasattr(obj, "Shape")},
                "parameters": parameter_record(doc)}

    def reject(self, code, *, preview=False, keep_redo=True, **args):
        before = self.snapshot()
        if preview:
            response = self.request("preview", proposal={"op": "batch", **args})
            self.assertTrue(response["ok"], response)
            self.assertFalse(response["result"]["accepted"], response)
            error = response["result"]["error"]
        else:
            response = self.request("batch", **args)
            self.assertFalse(response["ok"], response)
            error = response["error"]
        self.assertEqual(error["code"], code, error)
        after = self.snapshot()
        if not keep_redo:
            for state in (before, after):
                state.pop("redo")
                for key in ("redo_names", "redo_count"):
                    state["content"].pop(key, None)
        self.assertEqual(after, before, "a rejected batch changes nothing: " + "; ".join(differences(before, after)))
        self.assertIsNone(App.getActiveTransaction())
        return error


class BatchTests(BatchFixture, unittest.TestCase):
    def boss_steps(self):
        return [{"op": "create_plane", "id": "Top", "origin": [0, 0, 10], "normal": [0, 0, 1]},
                {"op": "create_sketch", "id": "BossSketch", "as": "sk", "support": {"feature": "Top"}},
                {"op": "add_circle", "sketch": {"$ref": "sk"}, "x": 10, "y": 10, "diameter": 8},
                {"op": "pad", "id": "Boss", "as": "boss", "profile": {"$ref": "sk"}, "length": 5, "operation": "add",
                 "merge_scope": ["Body"]},
                {"op": "fillet", "id": "BossRound", "radius": 1,
                 "edges": [{"kind": "closest", "point": [10, 14, 15],  # on the top circle, off its seam
                            "query": {"kind": "owned_by", "part": "Body", "entity_type": "edge"}}]}]

    def test_batch_builds_editable_features_as_one_undo_step(self):
        self.block()
        before = self.snapshot()
        result = self.call("batch", label="boss with round", steps=self.boss_steps())
        report = result["batch_report"]
        self.assertEqual([row["created_feature"] for row in report["steps"]], ["Top", "BossSketch", None, "Boss", "BossRound"])
        self.assertEqual(report["created_features"], ["Top", "BossSketch", "Boss", "BossRound"])
        self.assertEqual(report["steps"][3]["parts"], ["Body"])
        self.assertIn("Boss", report["steps"][3]["features"])
        self.assertEqual(self.doc.UndoNames[0], "KurtShape: batch boss with round")
        self.assertEqual(self.doc.UndoNames[1:], before["undo"][:len(self.doc.UndoNames) - 1])
        self.assertNotEqual(result["revision"], before["revision"])
        self.assertEqual(result["build_status"], "valid")
        self.call("edit_extrusion", feature="Boss", length=6)
        self.call("edit_dress_up", feature="BossRound", radius=1.5)
        self.call("undo")
        self.call("undo")
        self.call("undo")
        after = self.snapshot()
        self.assertEqual((after["objects"], after["volumes"], after["intent"]),
                         (before["objects"], before["volumes"], before["intent"]))
        self.assertEqual(self.doc.RedoNames[0], "KurtShape: batch boss with round")
        self.call("redo")
        self.assertEqual(self.call("inspect")["build_status"], "valid")

    def test_failing_step_rolls_back_whole_batch_and_names_the_step(self):
        self.block()
        steps = [{"op": "edit_extrusion", "feature": "Block", "length": 14},
                 {"op": "create_sketch", "id": "Inner", "as": "inner", "plane": "XY"},
                 {"op": "add_rectangle", "sketch": {"$ref": "inner"}, "x": 5, "y": 5, "width": 4, "height": 4},
                 {"op": "pad", "id": "Inside", "profile": {"$ref": "inner"}, "length": 3, "operation": "add",
                  "merge_scope": ["Body"]}]
        error = self.reject("empty_add", keep_redo=False, steps=steps, request_id="fail-1")
        self.assertEqual({key: error["batch"][key] for key in ("step", "op", "phase", "steps_completed", "step_count",
                                                               "rolled_back")},
                         {"step": 3, "op": "pad", "phase": "step", "steps_completed": 3, "step_count": 4, "rolled_back": True})
        self.assertEqual(error["batch"]["step_request"]["profile"], "Inner", "the resolved step")
        self.assertTrue(error["message"].startswith("Step 3 (pad): "))
        self.assertEqual(error["feature"], "Inside")
        self.assertEqual(self.doc.getObject("Block").LengthFwd.Value, 10.0)
        record = self.call("inspect")["last_failed_attempt"]
        self.assertEqual(record["request"], {"op": "batch", "request_id": "fail-1", "label": None, "step_count": 4})
        self.assertNotIn("step_request", record["error"]["batch"])
        self.assertLessEqual(len(json.dumps(record)), batch.FAILURE_RECORD_BYTES)

    def test_references_resolve_to_created_features_and_parts(self):
        self.new()
        steps = [{"op": "create_body", "id": "Second", "as": "second"},
                 {"op": "sketch_rectangle", "id": "SecondProfile", "as": "prof", "body": {"$part": "second"},
                  "x": 40, "y": 0, "width": 10, "height": 10},
                 {"op": "pad", "id": "SecondBlock", "as": "blk", "profile": {"$ref": "prof"}, "length": 5,
                  "operation": "new", "body": {"$part": "second"}},
                 {"op": "fillet", "id": "SecondRound", "radius": 1,
                  "edges": [{"kind": "closest", "point": [50, 5, 5],
                             "query": {"kind": "owned_by", "part": {"$part": "blk"}, "entity_type": "edge"}}]}]
        result = self.call("batch", steps=steps)
        self.assertEqual(result["batch_report"]["steps"][2]["parts"], ["Second"])
        stored = json.loads(self.doc.getObject("SecondBlock").KurtShapeStudioOperation)
        self.assertNotIn("$", json.dumps(stored))
        self.assertEqual(stored["profile"], "SecondProfile")

    def test_structural_errors_reject_before_mutation(self):
        self.block()
        self.call("sketch_circle", id="Extra", x=15, y=15, diameter=2)
        self.call("undo")  # a non-empty redo list: pre-mutation rejections keep it
        self.assertTrue(self.doc.RedoNames)
        circle = {"op": "sketch_circle", "id": "C1", "as": "c", "x": 5, "y": 5, "diameter": 2}
        cases = [
            ({"steps": "nope"}, "invalid_argument"), ({"steps": []}, "invalid_argument"),
            ({"steps": 5}, "invalid_argument"), ({"steps": True}, "invalid_argument"),
            ({"steps": [{"op": ["x"]}]}, "unsupported_operation"), ({"steps": [{"op": {}}]}, "unsupported_operation"),
            ({"steps": [dict(circle, id="C%d" % i, **{"as": "c%d" % i}) for i in range(33)]}, "invalid_argument"),
            ({"steps": [1]}, "invalid_argument"), ({"steps": [circle], "label": ""}, "invalid_argument"),
            ({"steps": [dict(circle, **{"as": "9bad"})]}, "invalid_argument"),
            ({"steps": [circle, dict(circle, id="C2")]}, "invalid_argument"),
            ({"steps": [{"op": "add_circle", "sketch": {"$ref": "nope"}, "x": 1, "y": 1, "diameter": 1}]}, "invalid_step_reference"),
            ({"steps": [{"op": "add_circle", "sketch": {"$ref": "c"}, "x": 1, "y": 1, "diameter": 1}, circle]}, "invalid_step_reference"),
            ({"steps": [dict(circle, **{"as": "c"}), {"op": "add_circle", "as": "a", "sketch": {"$ref": "c"}, "x": 1, "y": 1,
                                                      "diameter": 1},
                        {"op": "add_circle", "sketch": {"$ref": "a"}, "x": 2, "y": 2, "diameter": 1}]}, "invalid_step_reference"),
            ({"steps": [circle, {"op": "transform_part", "part": {"$part": "c"}, "translation": [1, 0, 0]}]}, "invalid_step_reference"),
            ({"steps": [circle, {"op": "add_circle", "sketch": {"$ref": 1}, "x": 1, "y": 1, "diameter": 1}]}, "invalid_argument"),
            ({"steps": [circle, {"op": "add_circle", "sketch": {"$ref": "c", "x": 1}, "x": 1, "y": 1, "diameter": 1}]}, "invalid_argument"),
            ({"steps": [circle, dict(circle, **{"as": "d"})]}, "invalid_argument"),
            ({"steps": [{"op": "rebuild"}]}, "unsupported_operation"), ({"steps": [{"op": "undo"}]}, "unsupported_operation"),
            ({"steps": [{"op": "batch", "steps": []}]}, "unsupported_operation"),
            ({"steps": [{"op": "render_view"}]}, "unsupported_operation"),
            ({"steps": [{"op": "rename_parameter", "name": "a", "new_name": "b"}]}, "unsupported_operation"),
            ({"steps": [dict(circle, expected_revision="x")]}, "unknown_argument"),
            ({"steps": [dict(circle, colour=1)]}, "unknown_argument"),
            ({"steps": [{"op": "set_parameter", "feature": "Block"}]}, "invalid_argument"),
            ({"steps": [dict(circle, id="C%d" % i, **{"as": "c%d" % i}, name="x" * 3000) for i in range(25)]}, "request_too_large"),
        ]
        for args, code in cases:
            with self.subTest(args=json.dumps(args)[:120]):
                for preview in (False, True):
                    error = self.reject(code, preview=preview, **args)
                    if code in {"invalid_step_reference", "unsupported_operation", "unknown_argument"}:
                        self.assertIn("batch", error)
        error = self.reject("unsupported_operation", steps=[{"op": "delete_features", "features": ["Block"]}])
        self.assertEqual(error["reason"], batch.EXCLUDED["delete_features"])

    def test_runtime_reference_errors_roll_back(self):
        self.block()
        steps = [{"op": "split_part", "id": "Halves", "as": "halves", "part": "Body",
                  "plane": {"origin": [10, 0, 0], "normal": [1, 0, 0]}},
                 {"op": "set_part_appearance", "part": {"$part": "halves"}, "color": [1, 0, 0]}]
        error = self.reject("invalid_step_reference", keep_redo=False, steps=steps)
        self.assertEqual(len(error["parts"]), 2)
        self.assertEqual(error["batch"]["step"], 1)

    def test_stale_revision_and_pending_transaction_reject(self):
        self.block()
        steps = [{"op": "sketch_circle", "id": "C1", "x": 5, "y": 5, "diameter": 2}]
        response = self.core.dispatch({"op": "batch", "document_id": self.state["document_id"], "expected_revision": "old",
                                       "steps": steps})
        self.assertEqual(response["error"]["code"], "stale_revision")
        self.doc.openTransaction("native")
        self.doc.getObject("Base").Label = "Pending"
        try:
            self.call("inspect")  # the native edit rotated the revision; the guard after it is what is tested
            last_failure = self.core._meta(self.doc).LastFailure
            for preview in (False, True):
                if preview:
                    response = self.request("preview", proposal={"op": "batch", "steps": steps})
                    self.assertEqual(response["error"]["code"], "unmanaged_transaction")
                else:
                    self.assertEqual(self.request("batch", steps=steps)["error"]["code"], "unmanaged_transaction")
            self.assertEqual(self.core._meta(self.doc).LastFailure, last_failure,
                             "a refusal never writes into the user's pending transaction")
        finally:
            self.doc.abortTransaction()

    def test_identical_replay_never_reexecutes(self):
        self.block()
        steps = [{"op": "sketch_circle", "id": "C1", "x": 5, "y": 5, "diameter": 2}]
        request = {"op": "batch", "document_id": self.state["document_id"], "expected_revision": self.state["revision"],
                   "request_id": "replay-1", "steps": steps}
        first = self.core.dispatch(dict(request))
        undo = list(self.doc.UndoNames)
        self.assertEqual(self.core.dispatch(dict(request)), first)
        self.assertEqual(list(self.doc.UndoNames), undo)
        self.assertEqual(self.core.dispatch(dict(request, steps=steps * 1, label="other"))["error"]["code"], "request_id_reused")
        self.assertEqual(self.core.ledger.status("replay-1")["status"], "completed")
        failing = dict(request, request_id="replay-2", expected_revision=first["result"]["revision"],
                       steps=[{"op": "set_parameter", "feature": "Nope", "parameter": "Length", "value": 1}])
        failed = self.core.dispatch(dict(failing))
        self.assertEqual(self.core.dispatch(dict(failing)), failed)
        self.assertEqual(self.core.ledger.status("replay-2")["status"], "failed")

    def test_preview_batch_matches_commit_and_leaves_source_unchanged(self):
        self.block()
        before = self.snapshot()
        signatures, failures = dict(self.core.signatures), dict(self.core.last_failures)
        preview = self.call("preview", proposal={"op": "batch", "label": "boss", "steps": self.boss_steps()})
        self.assertEqual(self.snapshot(), before)
        self.assertEqual((dict(self.core.signatures), dict(self.core.last_failures)), (signatures, failures))
        self.assertEqual((preview["accepted"], preview["valid"], preview["discarded"]), (True, True, True))
        self.assertEqual(preview["proposal"], {"op": "batch", "label": "boss", "step_count": 5})
        self.assertIsNone(App.getActiveTransaction())
        committed = self.call("batch", label="boss", steps=self.boss_steps())
        def strip(value):  # wall-clock timings (row ms, result_report.check_ms) differ between runs
            if isinstance(value, dict):
                return {key: strip(item) for key, item in value.items() if key != "ms" and not key.endswith("_ms")}
            return [strip(item) for item in value] if isinstance(value, list) else value
        self.assertEqual(strip(preview["batch_report"]["steps"]), strip(committed["batch_report"]["steps"]))
        self.assertAlmostEqual(preview["measurements"]["volume_mm3"], committed["measurements"]["volume_mm3"], places=6)

    def test_preview_batch_failure_equals_commit_failure(self):
        self.block()
        steps = [{"op": "create_sketch", "id": "Inner", "as": "inner", "plane": "XY"},
                 {"op": "add_rectangle", "sketch": {"$ref": "inner"}, "x": 5, "y": 5, "width": 4, "height": 4},
                 {"op": "pad", "id": "Inside", "profile": {"$ref": "inner"}, "length": 3, "operation": "add",
                  "merge_scope": ["Body"]}]
        preview = self.call("preview", proposal={"op": "batch", "steps": steps})
        committed = self.request("batch", steps=steps)["error"]
        self.assertFalse(preview["accepted"])
        error = preview["error"]
        self.assertEqual((error["code"], error["message"], error["feature"]), (committed["code"], committed["message"], committed["feature"]))
        self.assertEqual({key: error["batch"][key] for key in ("step", "op", "as", "phase", "steps_completed")},
                         {key: committed["batch"][key] for key in ("step", "op", "as", "phase", "steps_completed")})
        self.assertAlmostEqual(error["tool_volume_mm3"], committed["tool_volume_mm3"], delta=1e-6 * abs(committed["tool_volume_mm3"]))
        self.assertEqual(preview["batch_report"]["completed_steps"], 2)
        self.assertIsNone(preview["measurements"])

    def test_batch_rejected_during_sketch_lease(self):
        self.block()
        self.call("begin_sketch_edit", feature="Base")
        steps = [{"op": "sketch_circle", "id": "C1", "x": 5, "y": 5, "diameter": 2}]
        self.assertEqual(self.request("batch", steps=steps)["error"]["code"], "sketch_edit_active")
        preview = self.request("preview", proposal={"op": "batch", "steps": steps})
        self.assertEqual(preview["error"]["code"], "sketch_edit_active")
        self.call("finish_sketch_edit", cancel=True)

    def test_every_batch_op_family_keeps_one_transaction(self):
        self.block()
        undo = len(self.doc.UndoNames)
        steps = [
            {"op": "create_parameter", "name": "boss_d", "type": "length", "value": 6},
            {"op": "create_plane", "id": "Top", "as": "top", "origin": [0, 0, 10], "normal": [0, 0, 1]},
            {"op": "create_sketch", "id": "BossSk", "as": "sk", "support": {"feature": {"$ref": "top"}}},
            {"op": "add_circle", "sketch": {"$ref": "sk"}, "x": 10, "y": 10, "diameter": 6},
            {"op": "add_line", "sketch": {"$ref": "sk"}, "x1": 0, "y1": 25, "x2": 5, "y2": 25, "construction": True},
            {"op": "pad", "id": "Boss", "as": "boss", "profile": {"$ref": "sk"}, "length": 4, "operation": "add",
             "merge_scope": ["Body"]},
            {"op": "edit_extrusion", "feature": "Boss", "length": 5},
            {"op": "sketch_circle", "id": "HoleSk", "x": 4, "y": 4, "diameter": 2},
            {"op": "pocket", "id": "Bore", "profile": "HoleSk", "through_all": True, "operation": "remove",
             "merge_scope": ["Body"]},
            {"op": "fillet", "id": "Round", "radius": 1, "edges": [EDGE_NEAR]},
            {"op": "edit_dress_up", "feature": "Round", "radius": 1.2},
            {"op": "sketch_rectangle", "id": "SideSk", "plane": "XZ", "x": 30, "y": 0, "width": 4, "height": 5},
            {"op": "revolve", "id": "Ring", "profile": "SideSk", "operation": "new",
             "axis": {"origin": [0, 0, 0], "direction": [0, 0, 1]}, "angle": "90 deg"},
            {"op": "set_parameter", "feature": "Boss", "parameter": "Length", "value": 6},
            {"op": "edit_parameter", "name": "boss_d", "value": 7},
            {"op": "rename_feature", "feature": "Boss", "name": "Boss renamed"},
            {"op": "set_part_appearance", "part": "Body", "color": [0.2, 0.4, 0.8]},
        ]
        transactions = set()
        original = self.core._model_step

        def spy(doc, req, **kwargs):
            outcome = original(doc, req, **kwargs)
            transactions.add((App.getActiveTransaction() or (None, None))[1])
            return outcome
        with patch.object(self.core, "_model_step", side_effect=spy):
            result = self.call("batch", label="families", steps=steps)
        self.assertEqual(len(transactions), 1)
        self.assertEqual(len(self.doc.UndoNames), undo + 1)
        for row in result["batch_report"]["steps"]:
            with self.subTest(op=row["op"]):
                self.assertEqual(row["created_feature"] is None, row["op"] in batch.NO_FEATURE)
        objects = sorted(obj.Name for obj in self.doc.Objects)
        self.call("undo")
        self.assertNotIn("Boss", [obj.Name for obj in self.doc.Objects])
        self.call("redo")
        self.assertEqual(sorted(obj.Name for obj in self.doc.Objects), objects)

    def rogue(self, op, action):
        """Patch the handler of ``op`` so that, after it runs, ``action(doc)`` breaks the batch transaction."""
        original = self.core._model_operation

        def handler(doc, req):
            created = original(doc, req)
            if req["op"] == op:
                action(doc)
            return created
        return patch.object(self.core, "_model_operation", side_effect=handler)

    def test_transaction_split_recovers_or_reports_honestly(self):
        self.block()
        steps = [{"op": "sketch_circle", "id": "C1", "x": 5, "y": 5, "diameter": 2},
                 {"op": "sketch_circle", "id": "C2", "x": 15, "y": 15, "diameter": 2}]
        before = self.snapshot()
        with self.rogue("sketch_circle", lambda doc: (doc.commitTransaction(), doc.openTransaction("Rogue"))):
            error = self.request("batch", steps=steps)["error"]
        self.assertEqual((error["code"], error["rolled_back"], error["revision_rotated"]), ("transaction_split", True, True))
        after = self.snapshot()
        self.assertEqual((after["objects"], after["intent"], after["volumes"]), (before["objects"], before["intent"], before["volumes"]))
        self.assertNotEqual(after["revision"], before["revision"])
        self.assertEqual(self.doc.UndoNames[0], batch.DISCARD_BOUNDARY)
        self.assertEqual(list(self.doc.UndoNames[1:]), before["undo"][:len(self.doc.UndoNames) - 1])
        self.assertEqual(list(self.doc.RedoNames), [])
        self.assertIsNone(App.getActiveTransaction())
        self.call("inspect")
        self.call("undo")  # skips the discard boundary: undoes the Block pad
        self.assertNotIn("Block", [obj.Name for obj in self.doc.Objects])
        self.call("redo")
        # (b) a rogue commit followed by a change outside any transaction cannot be restored.
        self.call("inspect")
        before = self.snapshot()

        def stray(doc):
            doc.commitTransaction()
            doc.addObject("App::FeaturePython", "Stray")
        with self.rogue("sketch_circle", stray):
            error = self.request("batch", steps=steps[:1])["error"]
        self.assertEqual((error["code"], error["rolled_back"]), ("transaction_split", False))
        self.assertEqual(error["residual_objects"]["added"], ["Stray"])
        self.assertNotEqual(self.snapshot()["revision"], before["revision"])
        # (c) a rogue open, then the step raises: the commit counter still finds the committed part.
        self.call("inspect")

        def open_then_fail(doc):
            doc.commitTransaction()
            doc.openTransaction("Rogue")
            raise RuntimeError("step failed after a rogue commit")
        with self.rogue("sketch_circle", open_then_fail):
            error = self.request("batch", steps=steps[:1])["error"]
        self.assertEqual((error["code"], error["cause"]["code"]), ("transaction_split", "operation_failed"))
        self.assertTrue(error["rolled_back"])
        # (d) at the native undo cap, behind 20 identically named entries, the commit counter still restores.
        self.call("inspect")
        for index in range(20):
            self.call("rename_feature", feature="Base", name="Base %d" % index)
        before = self.snapshot()
        with self.rogue("sketch_circle", lambda doc: (doc.commitTransaction(), doc.openTransaction("Rogue"))):
            error = self.request("batch", steps=steps[:1])["error"]
        self.assertEqual((error["code"], error["rolled_back"]), ("transaction_split", True))
        after = self.snapshot()
        self.assertEqual((after["objects"], after["intent"]), (before["objects"], before["intent"]))

    def test_in_step_abort_and_failing_recovery_are_reported(self):
        self.block()
        steps = [{"op": "sketch_circle", "id": "C1", "x": 5, "y": 5, "diameter": 2}]
        before = self.snapshot()

        def abort_change_fail(doc):
            App.closeActiveTransaction(True)
            doc.addObject("App::FeaturePython", "Outside")
            raise RuntimeError("step failed after aborting the batch")
        with self.rogue("sketch_circle", abort_change_fail):
            error = self.request("batch", steps=steps)["error"]
        self.assertEqual((error["code"], error["rolled_back"], error["cause"]["code"]),
                         ("transaction_split", False, "operation_failed"))
        self.assertEqual(error["residual_objects"]["added"], ["Outside"])
        self.assertNotEqual(self.snapshot()["revision"], before["revision"], "no ABA: the revision rotated")
        self.assertIsNone(App.getActiveTransaction())
        self.call("inspect")
        with self.rogue("sketch_circle", lambda doc: (doc.commitTransaction(), doc.openTransaction("Rogue"))):
            with patch.object(batch.SplitGuard, "_recover", side_effect=RuntimeError("recovery broke")):
                response = self.request("batch", steps=steps)
        self.assertEqual((response["error"]["code"], response["error"]["rolled_back"]), ("transaction_split", False))
        self.assertIn("recovery broke", response["error"]["recovery_error"])
        self.assertIsNone(App.getActiveTransaction())
        self.assertFalse(self.doc.HasPendingTransaction)

    def test_unexpected_exception_logs_and_rolls_back(self):
        self.block()
        log = Path(os.environ["KURTSHAPE_SESSION_DIR"]) / "kurtshape.log"
        count = log.read_text(encoding="utf-8").count("Traceback") if log.exists() else 0

        def boom(doc):
            raise ZeroDivisionError("boom")
        with self.rogue("sketch_circle", boom):
            error = self.reject("operation_failed", keep_redo=False,
                                steps=[{"op": "sketch_circle", "id": "C1", "x": 5, "y": 5, "diameter": 2}])
        self.assertEqual(error["batch"]["step"], 0)
        self.assertGreater(log.read_text(encoding="utf-8").count("Traceback"), count)

    def test_batch_in_rolled_back_history_inserts_at_bar_in_order(self):
        self.block()
        self.call("sketch_circle", id="Late", x=5, y=5, diameter=2)
        order = self.call("inspect")["studio"]["feature_order"]
        self.call("rollback", index=order.index("Late"))
        result = self.call("batch", steps=[{"op": "sketch_circle", "id": "A1", "x": 15, "y": 15, "diameter": 2},
                                           {"op": "sketch_circle", "id": "A2", "x": 15, "y": 5, "diameter": 2}])
        order = result["studio"]["feature_order"]
        self.assertEqual(order.index("A2"), order.index("A1") + 1)
        self.assertLess(order.index("A2"), order.index("Late"))

    def test_batch_ops_are_derived_and_classified(self):
        self.assertEqual(batch.OPS, frozenset(Controller.MODEL_OPS) - frozenset(batch.EXCLUDED))
        self.assertLessEqual(set(batch.EXCLUDED), Controller.MODEL_OPS)
        self.assertFalse(batch.OPS & (Controller.CREATE_OPS | Controller.READ_OPS | Controller.ASSEMBLY_OPS))
        self.assertIn("batch", Controller.OPS)
        self.assertNotIn("batch", Controller.MODEL_OPS)
        capabilities = self.core.dispatch({"op": "capabilities"})["result"]
        self.assertEqual(capabilities["batch"], batch.capabilities())
        self.assertIn("batch", capabilities["preview_operations"])
        self.assertTrue({"create_parameter", "edit_parameter"} <= batch.OPS)
        parameter_ops = {"create_parameter", "edit_parameter", "rename_parameter", "delete_parameter"}
        self.assertEqual(set(capabilities["parameters"]["batchable"]), parameter_ops & batch.OPS)

    def test_no_new_transaction_calls(self):
        """D12: the (module, function) pairs that call native transaction or history APIs are a reviewed list.

        Static: dynamic calls (``getattr(doc, op)()`` in ``_native_history``) and module-level code are not seen.
        """
        calls = {"openTransaction", "commitTransaction", "abortTransaction", "closeActiveTransaction",
                 "setActiveTransaction", "undo", "redo", "clearUndos"}
        found = set()
        for path in sorted((ROOT / "src" / "kurtshape").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for inner in ast.walk(node):
                    if (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute)
                            and inner.func.attr in calls):
                        found.add((path.stem, node.name))
        self.assertEqual(found, ALLOWED_TRANSACTION_CALLERS, "a new caller of transaction APIs needs review (F4 D12)")

    def test_preview_accepted_matches_commit_with_rebuild_reason(self):
        self.block()
        meta = self.core._meta(self.doc)
        meta.RebuildReason = "saved_by_other_build"
        self.call("inspect")
        steps = [{"op": "sketch_circle", "id": "C1", "x": 5, "y": 5, "diameter": 2}]
        preview = self.call("preview", proposal={"op": "batch", "steps": steps})
        single = self.call("preview", proposal=steps[0])
        for result in (preview, single):
            self.assertEqual((result["accepted"], result["valid"], result["build_status"]), (True, False, "needs_rebuild"))
        committed = self.call("batch", steps=steps)
        self.assertEqual(committed["build_status"], "needs_rebuild")

    def test_time_budget_rolls_back_in_commit_and_preview(self):
        self.block()
        self.core.request_budget_s = 0.05
        original = self.core._model_step

        def slow(doc, req, **kwargs):
            time.sleep(0.08)
            return original(doc, req, **kwargs)
        steps = [{"op": "sketch_circle", "id": "C%d" % i, "x": 2 + i, "y": 5, "diameter": 1} for i in range(3)]
        with patch.object(self.core, "_model_step", side_effect=slow):
            error = self.reject("batch_time_budget_exceeded", keep_redo=False, steps=steps)
            self.assertEqual(error["steps_completed"], 1)
            error = self.reject("batch_time_budget_exceeded", preview=True, steps=steps)

    def test_batch_validation_runs_once_and_attributes(self):
        self.block()
        self.call("create_sketch", id="Cap", plane="XY")
        self.call("add_rectangle", sketch="Cap", width=20, height=20)
        self.call("pad", id="Raise", profile="Cap", length=15, operation="add", merge_scope=["Body"])
        self.call("create_plane", id="TopPlane", origin=[0, 0, 15], normal=[0, 0, 1])
        self.call("create_sketch", id="TopSketch", support={"feature": "TopPlane"})
        self.call("add_rectangle", sketch="TopSketch", x=8, y=8, width=4, height=4)
        self.call("pocket", id="TopCut", profile="TopSketch", length=3, through_all=False, reversed=True,
                  operation="remove", merge_scope=["Body"])
        shorten = {"op": "edit_extrusion", "feature": "Raise", "length": 11}
        error = self.reject("empty_cut", keep_redo=False, steps=[{"op": "sketch_circle", "id": "Spare", "x": 2, "y": 2,
                                                                  "diameter": 1}, shorten])
        self.assertEqual((error["batch"]["phase"], error["batch"]["step"]), ("final_validation", 1))
        checks = self.core.result_checks
        calls = []
        original = checks._check
        with patch.object(checks, "_check", side_effect=lambda *a, **k: (calls.append(1), original(*a, **k))[1]):
            result = self.call("batch", steps=[shorten, {"op": "edit_extrusion", "feature": "Raise", "length": 14}])
        self.assertEqual(result["build_status"], "valid", "change then repair is accepted")
        self.assertTrue(1 <= len(calls) <= 2, "one check per affected result per batch: %d" % len(calls))

    def test_batch_parameters_drive_features_and_roll_back(self):
        self.block()
        steps = [{"op": "create_parameter", "name": "w", "type": "length", "value": 24},
                 {"op": "set_expression", "feature": "Base", "parameter": "Width", "expression": "w"},
                 {"op": "edit_parameter", "name": "w", "value": 26}]
        result = self.call("batch", steps=steps)
        self.assertEqual(result["parameters"][0]["value"], 26.0)
        width = next(row for row in result["features"] if row["id"] == "Base")["parameters"]["Width"]
        self.assertEqual((width["value"], width["expression"]), (26.0, "Params.w"))
        error = self.reject("expression_cycle", keep_redo=False, steps=[
            {"op": "create_parameter", "name": "a", "type": "length", "value": 1},
            {"op": "create_parameter", "name": "b", "type": "length", "expression": "a + 1 mm"},
            {"op": "edit_parameter", "name": "a", "expression": "b * 2"}])
        self.assertEqual(error["batch"]["step"], 2)
        self.assertNotIn("a", [row["name"] for row in self.call("inspect")["parameters"]])
        error = self.reject("unsupported_operation", steps=[{"op": "delete_parameter", "name": "w"}])
        self.assertIn("identity", error["reason"])

    def test_more_op_families_keep_one_transaction(self):
        """Sketch geometry, edits, holes, helices and part operations in one batch (spec test 11, continued)."""
        self.new()
        before = sorted(obj.Name for obj in self.doc.Objects)
        steps = [
            {"op": "sketch_rectangle", "id": "Base", "width": 40, "height": 20},
            {"op": "pad", "id": "Block", "profile": "Base", "length": 10, "operation": "new"},
            {"op": "chamfer", "id": "Bevel", "size": 1,
             "edges": [{"kind": "closest", "point": [40, 10, 10],
                        "query": {"kind": "owned_by", "part": "Body", "entity_type": "edge"}}]},
            {"op": "extrude_face", "id": "Raise", "length": 2,
             "face": {"kind": "closest", "point": [20, 10, 10],
                      "query": {"kind": "owned_by", "part": "Body", "entity_type": "face"}}},
            {"op": "create_parameter", "name": "d", "type": "length", "value": 4},
            {"op": "sketch_circle", "id": "Spot", "x": 10, "y": 10, "diameter": 4},
            {"op": "hole", "id": "Drill", "sketch": "Spot", "diameter": 4, "depth": 5, "reversed": True},
            {"op": "set_expression", "feature": "Drill", "parameter": "Diameter", "expression": "d"},
            {"op": "sketch_rectangle", "id": "ToolSk", "x": 60, "y": 0, "width": 5, "height": 5},
            {"op": "pad", "id": "ToolPad", "as": "tool", "profile": "ToolSk", "length": 5, "operation": "new"},
            {"op": "transform_part", "part": {"$part": "tool"}, "translation": [5, 0, 0]},
            {"op": "delete_part", "id": "RemoveTool", "part": {"$part": "tool"}},
            {"op": "create_helix", "id": "Coil", "pitch": 5, "height": 10, "radius": 3},
            {"op": "create_sketch", "id": "Loose", "as": "loose", "plane": "XY"},
            {"op": "add_rectangle", "sketch": {"$ref": "loose"}, "x": 120, "y": 0, "width": 2, "height": 2},
            {"op": "add_arc", "sketch": {"$ref": "loose"}, "cx": 100, "cy": 0, "radius": 5, "start_angle": 0,
             "end_angle": "90 deg"},
            {"op": "add_polyline", "sketch": {"$ref": "loose"}, "points": [[110, 0], [115, 0], [115, 5]]},
            {"op": "set_sketch_support", "sketch": {"$ref": "loose"}, "plane": "XZ"},
        ]
        transactions = set()
        original = self.core._model_step

        def spy(doc, req, **kwargs):
            outcome = original(doc, req, **kwargs)
            transactions.add((App.getActiveTransaction() or (None, None))[1])
            return outcome
        with patch.object(self.core, "_model_step", side_effect=spy):
            result = self.call("batch", label="more families", steps=steps)
        self.assertEqual(len(transactions), 1)
        for row in result["batch_report"]["steps"]:
            with self.subTest(op=row["op"]):
                self.assertEqual(row["created_feature"] is None, row["op"] in batch.NO_FEATURE)
        rows = result["batch_report"]["steps"]
        self.assertEqual(len(rows[9]["parts"]), 1, "a new studio part is one output part")
        self.assertEqual(rows[11]["parts"], [], "a deleted part has no output part")
        objects = sorted(obj.Name for obj in self.doc.Objects)
        self.call("undo")
        self.assertEqual(sorted(obj.Name for obj in self.doc.Objects), before, "one undo restores the object set")
        self.call("redo")
        self.assertEqual(sorted(obj.Name for obj in self.doc.Objects), objects)

    def test_legacy_pad_and_pocket_batch(self):
        self.new()
        steps = [{"op": "sketch_rectangle", "id": "Base", "width": 20, "height": 20},
                 {"op": "pad", "id": "Block", "profile": "Base", "length": 10},
                 {"op": "create_plane", "id": "Top", "as": "top", "base_plane": "XY", "offset": 10},
                 {"op": "sketch_circle", "id": "HoleSk", "as": "hole", "x": 10, "y": 10, "diameter": 4,
                  "support": {"feature": {"$ref": "top"}}},
                 {"op": "pocket", "id": "Bore", "profile": {"$ref": "hole"}, "through_all": True}]
        undo = list(self.doc.UndoNames)
        result = self.call("batch", steps=steps)
        rows = result["batch_report"]["steps"]
        self.assertEqual([row["created_feature"] for row in rows], ["Base", "Block", "Top", "HoleSk", "Bore"])
        self.assertEqual((rows[1]["parts"], rows[4]["parts"]), (["Body"], ["Body"]))
        self.assertAlmostEqual(result["measurements"]["volume_mm3"], 4000 - 3.141592653589793 * 4 * 10, places=3)
        self.assertEqual(list(self.doc.UndoNames[1:]), undo[:len(self.doc.UndoNames) - 1])

    def test_failure_records_stay_small_and_total(self):
        self.block()
        for args in ({"steps": 5}, {"steps": True}, {"steps": [{"op": ["x"]}]},
                     {"steps": [{"op": "x" * 5000}]}, {"steps": [{"op": "sketch_circle"}], "label": "y" * 5000}):
            with self.subTest(args=json.dumps(args)[:80]):
                response = self.request("batch", request_id="big-" + str(len(json.dumps(args))), **args)
                self.assertFalse(response["ok"])
                self.assertIn(response["error"]["code"], {"invalid_argument", "unsupported_operation"})
                record = self.call("inspect")["last_failed_attempt"]
                self.assertLessEqual(len(json.dumps(record)), batch.FAILURE_RECORD_BYTES)
                self.assertEqual(self.core.ledger.status(record["request"]["request_id"])["status"], "failed")

    def test_parameter_context_of_an_earlier_step_is_not_reported(self):
        self.block()
        steps = [{"op": "create_parameter", "name": "w", "type": "length", "value": 2},
                 {"op": "create_sketch", "id": "Inner", "as": "inner", "plane": "XY"},
                 {"op": "add_rectangle", "sketch": {"$ref": "inner"}, "x": 5, "y": 5, "width": 4, "height": 4},
                 {"op": "pad", "id": "Inside", "profile": {"$ref": "inner"}, "length": 3, "operation": "add",
                  "merge_scope": ["Body"]}]
        error = self.reject("empty_add", keep_redo=False, steps=steps)
        self.assertNotIn("parameter", error, "the failing pad is not a parameter edit")
        preview = self.call("preview", proposal={"op": "batch", "steps": steps})
        self.assertNotIn("parameter", preview["error"])


# The reviewed callers of native transaction and history APIs (F4 D12), contract 3.2 U6.
ALLOWED_TRANSACTION_CALLERS = {
    ("batch", "after_abort"), ("batch", "_recover"),
    ("core", "_adopt"), ("core", "_commit_sketch_edit"), ("core", "_dispatch"), ("core", "_native_history"),
    ("core", "_preserve_sketch_draft"), ("core", "_preview"), ("core", "_rollback_sketch_edit"),
    ("extrusion_preview", "evaluate"), ("sketch_tools", "prune_use_sources"), ("viewport_actions", "toggle_construction"),
}


class BatchBridgeTests(BatchFixture, unittest.TestCase):
    def test_slow_batch_outcome_unknown_reconciles_without_reexecution(self):
        from kurtshape.bridge import Bridge
        self.block()
        bridge = Bridge(self.core, self.folder, request_timeout=0.2)
        self.addCleanup(bridge.close)
        original = self.core._model_step
        runs = []

        def slow(doc, req, **kwargs):
            runs.append(req["op"])
            time.sleep(0.4)
            return original(doc, req, **kwargs)
        payload = {"op": "batch", "document_id": self.state["document_id"], "expected_revision": self.state["revision"],
                   "request_id": "slow-batch", "steps": [{"op": "sketch_circle", "id": "C1", "x": 5, "y": 5, "diameter": 2}]}

        def post(body):
            request = urllib.request.Request("http://127.0.0.1:%d/operation" % bridge.server.server_port,
                                             data=json.dumps(body).encode(), method="POST",
                                             headers={"Content-Type": "application/json", "Authorization": "Bearer " + bridge.token})
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=5) as response:
                return json.loads(response.read())
        undo = len(self.doc.UndoNames)
        results = []
        thread = threading.Thread(target=lambda: results.append(post(payload)))
        thread.start()
        deadline = time.monotonic() + 3
        while bridge.pending.empty() and time.monotonic() < deadline:
            time.sleep(0.005)
        with patch.object(self.core, "_model_step", side_effect=slow):
            bridge.tick()
        thread.join(5)
        self.assertEqual(results[0]["error"]["code"], "outcome_unknown")
        status = post({"op": "request_status", "request_id": "slow-batch"})["result"]
        self.assertEqual(status["status"], "completed")
        resent = []
        thread = threading.Thread(target=lambda: resent.append(post(payload)))
        thread.start()
        deadline = time.monotonic() + 3
        while not resent and time.monotonic() < deadline:
            bridge.tick()
            time.sleep(0.01)
        thread.join(5)
        self.assertEqual(resent[0], status["response"])
        self.assertEqual(runs, ["sketch_circle"])
        self.assertEqual(len(self.doc.UndoNames), undo + 1)


if __name__ == "__main__":
    unittest.main()
