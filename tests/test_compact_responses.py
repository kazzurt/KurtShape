"""Slice A/B U6 (B1): compact mutation responses (detail:"compact"), the default without
operations/last_failed_attempt, detail:"full" unchanged; and preview as a true read op."""
import json
from pathlib import Path
import sys
import unittest

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
import FreeCAD as App
from kurtshape import operation_schemas as schemas
from kurtshape.core import Controller
import assistant_client

HEADER_KEYS = {"document_id", "revision", "name", "native_file", "modified", "modified_basis", "unsaved", "managed",
               "build_status", "rebuild_reason", "build_errors", "geometry_check", "active_sketch_edit", "detail", "studio",
               "result_checks", "feature_count", "part_count"}
REPORT_KEYS = {"created_feature", "batch_report", "result_check_report", "result_report", "repair_report",
               "parameter_report", "changed_inputs", "created_parameter", "operation_ms"}
DROPPED_BY_DEFAULT = {"operations", "last_failed_attempt"}


class CompactResponseTests(unittest.TestCase):
    def setUp(self):
        self.initial = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="compact-responses-")
        self.core = Controller()
        self.state = None
        response = self.core.dispatch({"op": "new", "name": "Compact responses"})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]

    def tearDown(self):
        self.core.close()
        for name in set(App.listDocuments()) - self.initial:
            App.closeDocument(name)

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

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
        response = self.request(op, **args)
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], code, response["error"])
        return response["error"]

    @staticmethod
    def size(value):
        return len(json.dumps(value, default=str).encode("utf-8"))

    def plate(self):
        self.call("sketch_rectangle", id="Base", width=40, height=30)
        self.call("pad", id="Plate", profile="Base", length=5)

    # 1. Compact mutation responses -------------------------------------------------

    def test_compact_mutation_response_is_the_header_and_the_reports(self):
        self.plate()
        full = self.size(self.call("inspect"))
        result = self.call("sketch_circle", id="Hole", x=10, y=10, diameter=6, detail="compact")
        self.assertEqual(result["detail"], "compact")
        self.assertLessEqual(set(result), HEADER_KEYS | REPORT_KEYS, sorted(result))
        self.assertTrue(HEADER_KEYS <= set(result), sorted(HEADER_KEYS - set(result)))
        self.assertEqual(result["created_feature"], "Hole")
        self.assertEqual(result["revision"], self.core._meta(self.doc).Revision)
        self.assertEqual(result["build_status"], "valid")
        self.assertEqual(result["feature_count"], 3)
        self.assertNotIn("features", result)
        self.assertNotIn("bodies", result)
        self.assertNotIn("operations", result)
        self.assertLess(self.size(result), 2048, self.size(result))
        self.assertLess(self.size(result) * 4, full, "the compact form is a fraction of the full inspection")
        pocket = self.call("pocket", id="Cut", profile="Hole", length=5, detail="compact")
        self.assertEqual(pocket["created_feature"], "Cut")
        self.assertLess(self.size(pocket), 2048)
        # The next mutation runs against the compact response's revision: the header is enough to continue.
        self.call("rename_feature", feature="Cut", name="Through hole", detail="compact")
        self.assertEqual(self.doc.getObject("Cut").Label, "Through hole")
        # A compact save response reports the saved state like the full one.
        path = str(self.folder / "compact.FCStd")
        saved = self.call("save", path=path, detail="compact")
        self.assertEqual((saved["modified"], saved["unsaved"], saved["native_file"]), (False, False, path))

    def test_compact_batch_response_carries_the_created_features(self):
        self.plate()
        # The XY sketch lies under the 5 mm plate: 8 mm reaches through it, so the Boss adds material
        # (a legacy pad that adds nothing rejects with empty_add since slice A/B U9).
        steps = [{"op": "sketch_circle", "id": "BossSketch", "as": "boss", "x": 10, "y": 10, "diameter": 6},
                 {"op": "pad", "id": "Boss", "profile": {"$ref": "boss"}, "length": 8}]
        result = self.call("batch", steps=steps, label="boss", detail="compact")
        self.assertLessEqual(set(result), HEADER_KEYS | REPORT_KEYS, sorted(result))
        self.assertEqual(result["batch_report"]["created_features"], ["BossSketch", "Boss"])
        self.assertEqual(result["batch_report"]["completed_steps"], 2)
        self.assertNotIn("features", result)
        self.assertLess(self.size(result), 4096, self.size(result))
        self.assertEqual(self.doc.UndoNames[0], "KurtShape: batch boss")
        # detail belongs to the request, not to a step or a proposal: there it is not an argument and is ignored.
        again = self.call("batch", steps=[{"op": "rename_feature", "feature": "Boss", "name": "Boss renamed", "detail": "compact"}])
        self.assertIn("features", again)
        self.assertEqual(self.doc.getObject("Boss").Label, "Boss renamed")
        preview = self.request("preview", proposal={"op": "rename_feature", "feature": "Boss", "name": "Again", "detail": "full"})
        self.assertTrue(preview["ok"] and preview["result"]["accepted"], preview)

    def test_default_mutation_response_drops_operations_and_last_failed_attempt(self):
        self.plate()
        self.reject("duplicate_feature", "sketch_rectangle", id="Base", width=4, height=4)
        default = self.call("sketch_circle", id="Hole", x=10, y=10, diameter=6)
        self.assertIn("features", default)
        self.assertIn("bodies", default)
        self.assertIn("parameters", default)
        self.assertFalse(DROPPED_BY_DEFAULT & set(default), sorted(DROPPED_BY_DEFAULT & set(default)))
        self.assertEqual(default["created_feature"], "Hole")
        full = self.call("rename_feature", feature="Hole", name="Named hole", detail="full")
        self.assertTrue(DROPPED_BY_DEFAULT <= set(full), sorted(set(full)))
        self.assertIn("sketch_circle", full["operations"])
        self.assertEqual(full["last_failed_attempt"]["error"]["code"], "duplicate_feature")
        self.assertEqual(set(full) - DROPPED_BY_DEFAULT, set(default) - {"created_feature"},
                         "full is the default plus the two blocks")
        # inspect keeps its full form (operations, last_failed_attempt) and its compact form.
        inspection = self.call("inspect")
        self.assertTrue(DROPPED_BY_DEFAULT <= set(inspection))
        compact = self.core.dispatch({"op": "inspect", "document_id": self.state["document_id"], "detail": "compact"})
        self.assertTrue(compact["ok"], compact)
        self.assertEqual(compact["result"]["detail"], "compact")
        self.assertIn("history", compact["result"])

    def test_detail_is_validated_and_read_ops_keep_their_argument_sets(self):
        self.plate()
        error = self.reject("invalid_argument", "sketch_circle", id="Hole", x=10, y=10, diameter=6, detail="tiny")
        self.assertEqual(error["fields"], ["detail"])
        self.assertIsNone(self.doc.getObject("Hole"), "a rejected detail changes nothing")
        self.reject("unknown_argument", "preview", proposal={"op": "create_body", "id": "Spare"}, detail="compact")
        self.reject("unknown_argument", "close_document", detail="compact")
        response = self.core.dispatch({"op": "capabilities", "detail": "compact"})
        self.assertEqual(response["error"]["code"], "unknown_argument")
        errors = self.request("pocket", id="Cut", profile="Base", length=50, detail="compact")
        self.assertFalse(errors["ok"], "a compact request fails exactly as a full one")
        self.assertIn("code", errors["error"])

    def test_schema_offers_detail_on_every_mutation_and_batch(self):
        built = schemas.build(Controller)
        takes_detail = {op for op, body in built["operations"].items() if "detail" in body["request"]["properties"]}
        expected = (Controller.OPS - Controller.READ_OPS - Controller.VIEW_OPS - {"close_document"}) | {"inspect", "list_documents"}
        self.assertEqual(takes_detail, expected)
        for op in sorted(expected - {"inspect", "list_documents"}):
            with self.subTest(op=op):
                field = built["operations"][op]["request"]["properties"]["detail"]
                self.assertEqual(field["enum"], ["full", "compact"])
                self.assertNotIn("default", field, "omitted is neither full nor compact")
                self.assertIn("detail", Controller.ARGS[op])
                self.assertNotIn("detail", built["operations"][op]["request"]["required"])
        self.assertEqual(built["operations"]["inspect"]["request"]["properties"]["detail"]["default"], "full")

    # 2. preview as a true read op --------------------------------------------------

    def test_preview_without_a_revision_evaluates_the_current_document(self):
        self.plate()
        revision = self.state["revision"]
        response = self.core.dispatch({"op": "preview", "document_id": self.state["document_id"],
                                       "proposal": {"op": "sketch_circle", "id": "Hole", "x": 10, "y": 10, "diameter": 6}})
        self.assertTrue(response["ok"], response)
        preview = response["result"]
        self.assertEqual(preview["base_revision"], revision)
        self.assertTrue(preview["accepted"] and preview["valid"], preview)
        self.assertTrue(preview["discarded"])
        self.assertIsNone(self.doc.getObject("Hole"))
        self.assertEqual(self.core._meta(self.doc).Revision, revision, "a preview does not move the revision")
        # With the current revision the result is the same; a stale one still rejects.
        same = self.request("preview", proposal={"op": "sketch_circle", "id": "Hole", "x": 10, "y": 10, "diameter": 6})
        self.assertTrue(same["ok"], same)
        self.assertEqual(same["result"]["base_revision"], revision)
        stale = self.core.dispatch({"op": "preview", "document_id": self.state["document_id"], "expected_revision": "r0",
                                    "proposal": {"op": "sketch_circle", "id": "Hole", "x": 10, "y": 10, "diameter": 6}})
        self.assertFalse(stale["ok"])
        self.assertEqual(stale["error"]["code"], "stale_revision")
        self.assertIsNone(self.core.last_failures.get(self.state["document_id"]), "a read records no failed attempt")
        # The clone-free replies carry the current revision too.
        missing = self.core.dispatch({"op": "preview", "document_id": self.state["document_id"],
                                      "proposal": {"op": "pad", "id": "Boss", "length": 3}})
        self.assertTrue(missing["ok"], missing)
        self.assertEqual((missing["result"]["base_revision"], missing["result"]["accepted"]), (revision, False))
        bad_batch = self.core.dispatch({"op": "preview", "document_id": self.state["document_id"],
                                        "proposal": {"op": "batch", "steps": [{"op": "pad", "id": "B", "profile": "Base", "length": 1,
                                                                               "document_id": "x"}]}})
        self.assertTrue(bad_batch["ok"], bad_batch)
        self.assertEqual((bad_batch["result"]["base_revision"], bad_batch["result"]["accepted"]), (revision, False))

    def test_preview_envelope_and_read_classes_say_it_is_a_read(self):
        built = schemas.build(Controller)
        request = built["operations"]["preview"]["request"]
        self.assertNotIn("expected_revision", request["required"])
        self.assertEqual(request["required"], ["op", "document_id", "proposal"])
        self.assertEqual(request["properties"]["expected_revision"].get("x-mismatch-code"), "stale_revision")
        self.assertNotIn("x-ignored", request["properties"]["expected_revision"])
        self.assertEqual(schemas.envelope_requirements("preview", schemas._classes(Controller)), (True, False, False))
        for example in built["operations"]["preview"]["examples"]:
            self.assertNotIn("expected_revision", example)
        capabilities = self.core.dispatch({"op": "capabilities"})["result"]
        self.assertIn("preview", capabilities["read_operations"])
        self.assertIn("preview", assistant_client.READ_OPS_FALLBACK)
        self.assertIn("preview", Controller.READ_OPS)


if __name__ == "__main__":
    unittest.main()
