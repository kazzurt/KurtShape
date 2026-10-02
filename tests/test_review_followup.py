"""Native regression gates for the accepted Claude review follow-up."""
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
from kurtshape import core as module
from kurtshape.core import Controller, intent_signature, number
from kurtshape.request_ledger import RequestLedger


class ReviewFollowupTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.temporary = tempfile.TemporaryDirectory(prefix="review-followup-native-", dir=ROOT / "runtime")
        self.folder = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, {"KURTSHAPE_SESSION_DIR": str(self.folder)})
        self.environment.start()
        self.core = Controller()
        self.state = None
        self.call("new")

    def tearDown(self):
        self.core.close()
        for name in set(App.listDocuments()) - self.names:
            App.closeDocument(name)
        self.environment.stop()
        self.temporary.cleanup()

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def request(self, op, **args):
        req = {"op": op, **args}
        if op not in {"new", "open", "capabilities", "request_status", "list_documents"}:
            req.update(document_id=self.state["document_id"], expected_revision=self.state["revision"])
        return req

    def call(self, op, **args):
        response = self.core.dispatch(self.request(op, **args))
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        return self.state

    def reject(self, code, op, **args):
        response = self.core.dispatch(self.request(op, **args))
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], code, response)
        return response

    def plate(self):
        self.call("sketch_rectangle", id="Plate", width=20, height=10)
        self.call("pad", profile="Plate", length=6)

    def test_idle_inspection_uses_cached_intent_and_brep_then_native_edit_invalidates(self):
        self.plate()
        with patch.object(module, "intent_signature", wraps=module.intent_signature) as intent, patch.object(module, "measurements", wraps=module.measurements) as brep:
            for _ in range(25):
                self.core.inspect(self.doc)
            self.assertEqual(intent.call_count, 0)
            self.assertEqual(brep.call_count, 0)
            revision = self.state["revision"]
            self.doc.Pad.Length = 9
            pending = self.core.inspect(self.doc)
            self.assertNotEqual(pending["revision"], revision)
            self.assertEqual(pending["build_status"], "needs_rebuild")
            self.assertIsNone(pending["measurements"])
            self.doc.recompute()
            current = self.core.inspect(self.doc)
            self.assertAlmostEqual(current["measurements"]["volume_mm3"], 1800)
            self.assertGreater(brep.call_count, 0)

    def test_quantities_formulas_wrong_units_cycles_and_clear(self):
        self.plate()
        self.call("set_parameter", feature="Pad", parameter="Length", value="1/8 in")
        self.assertAlmostEqual(self.doc.Pad.Length.Value, 3.175)
        self.call("set_parameter", feature="Plate", parameter="Width", value="12.7/2")
        self.assertAlmostEqual(self.state["measurements"]["volume_mm3"], 6.35 * 10 * 3.175)
        signature = intent_signature(self.doc)
        self.reject("invalid_argument", "set_parameter", feature="Pad", parameter="Length", value="2 s")
        self.assertEqual(intent_signature(self.doc), signature)
        self.call("set_expression", feature="Pad", parameter="Length", expression="Plate.Constraints.Width / 2")
        self.assertAlmostEqual(self.doc.Pad.Length.Value, 3.175)
        self.call("set_parameter", feature="Plate", parameter="Width", value="1 in")
        self.assertAlmostEqual(self.doc.Pad.Length.Value, 12.7)
        self.reject("expression_driven", "set_parameter", feature="Pad", parameter="Length", value=4)
        signature = intent_signature(self.doc)
        result = self.core.dispatch(self.request("set_expression", feature="Plate", parameter="Width", expression="Pad.Length"))
        self.assertFalse(result["ok"], result)
        self.assertEqual(intent_signature(self.doc), signature)
        self.call("set_expression", feature="Pad", parameter="Length", expression=None)
        self.call("set_parameter", feature="Pad", parameter="Length", value=4)
        self.assertAlmostEqual(number("90 deg", "angle", unit="rad"), math.pi / 2)
        self.assertAlmostEqual(number("1 rad", "angle", unit="rad"), 1)

    def test_duplicate_is_native_editable_one_undo_and_fingerprint_guarded(self):
        self.plate()
        undo = self.doc.UndoCount
        fingerprint = hashlib.sha256(bytes(self.doc.Plate.dumpContent())).hexdigest()
        self.call("duplicate_feature", feature="Plate", fingerprint=fingerprint)
        name = self.state["created_feature"]
        self.assertEqual(self.doc.getObject(name).TypeId, "Sketcher::SketchObject")
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.call("set_parameter", feature=name, parameter="Width", value=8)
        self.assertAlmostEqual(self.doc.Plate.Constraints[-2].Value, 20)
        self.call("undo")
        self.call("undo")
        self.assertIsNone(self.doc.getObject(name))
        self.call("set_parameter", feature="Plate", parameter="Width", value=25)
        self.reject("changed_source", "duplicate_feature", feature="Plate", fingerprint=fingerprint)

    def test_request_replay_precedes_stale_revision_and_never_repeats_undo(self):
        self.plate()
        self.core.busy = True
        blocked = self.core.dispatch(self.request("set_parameter", feature="Pad", parameter="Length", value=99))
        self.assertEqual(blocked["error"]["code"], "busy")
        self.assertTrue(self.core.busy)
        self.core.dispatch(self.request("inspect"))
        self.assertTrue(self.core.busy)
        self.core.busy = False
        self.assertAlmostEqual(self.doc.Pad.Length.Value, 6)
        request = self.request("set_parameter", feature="Pad", parameter="Length", value=8, request_id=str(uuid.uuid4()))
        first = self.core.dispatch(request)
        self.assertTrue(first["ok"], first)
        self.state = first["result"]
        self.call("set_parameter", feature="Pad", parameter="Length", value=9)
        undo_count = self.doc.UndoCount
        self.assertEqual(self.core.dispatch(request), first)
        self.assertEqual(self.doc.UndoCount, undo_count)
        self.assertAlmostEqual(self.doc.Pad.Length.Value, 9)
        changed = dict(request, value=10)
        self.assertEqual(self.core.dispatch(changed)["error"]["code"], "request_id_reused")
        status = self.core.dispatch({"op": "request_status", "request_id": request["request_id"]})
        self.assertEqual(status["result"]["response"], first)
        request = self.request("undo", request_id=str(uuid.uuid4()))
        first = self.core.dispatch(request)
        self.assertTrue(first["ok"], first)
        self.assertEqual(self.core.dispatch(request), first)
        self.assertAlmostEqual(self.doc.Pad.Length.Value, 8)

    def test_ledger_eviction_is_explicit_and_missing_is_not_execution_proof(self):
        ledger = RequestLedger(limit=1)
        for identifier in ("one", "two"):
            self.assertIsNone(ledger.register({"op": "new", "request_id": identifier}, "started"))
            ledger.complete(identifier, {"ok": True, "result": {}})
        self.assertEqual(ledger.status("one")["status"], "expired")
        self.assertEqual(ledger.status("unseen")["status"], "not_recorded")
        self.assertEqual(ledger.register({"op": "new", "request_id": "one"}, "started")["error"]["code"], "request_expired")
        for index in range(6):
            identifier = "later" + str(index)
            self.assertIsNone(ledger.register({"op": "new", "request_id": identifier}, "started"))
            ledger.complete(identifier, {"ok": True, "result": {}})
        self.assertEqual(ledger.register({"op": "new", "request_id": "capacity"}, "started")["error"]["code"], "request_capacity_reached")
        self.assertEqual(ledger.register({"op": "new", "request_id": "one"}, "started")["error"]["code"], "request_expired")

    def test_preview_success_and_failure_preserve_live_intent_revision_and_history(self):
        self.plate()
        self.call("set_parameter", feature="Pad", parameter="Length", value=7)
        self.call("undo")
        doc = self.doc
        original = (intent_signature(doc), self.state["revision"], doc.UndoCount, doc.RedoCount, doc.FileName, dict(self.core.signatures))
        request = self.request("preview", proposal={"op": "set_parameter", "feature": "Pad", "parameter": "Length", "value": "1 in"})
        response = self.core.dispatch(request)
        self.assertTrue(response["ok"], response)
        self.assertTrue(response["result"]["valid"], response)
        self.assertAlmostEqual(response["result"]["measurements"]["volume_mm3"], 20 * 10 * 25.4)
        self.assertEqual((intent_signature(doc), self.core.inspect(doc)["revision"], doc.UndoCount, doc.RedoCount, doc.FileName, dict(self.core.signatures)), original)
        failed = self.core.dispatch(dict(request, proposal={"op": "set_expression", "feature": "Pad", "parameter": "Length", "expression": "Missing.Length"}))
        self.assertTrue(failed["ok"], failed)
        self.assertFalse(failed["result"]["valid"])
        self.assertEqual(intent_signature(doc), original[0])
        self.call("set_parameter", feature="Pad", parameter="Length", value=9)
        commit = dict(request["proposal"], document_id=self.state["document_id"], expected_revision=request["expected_revision"])
        self.assertEqual(self.core.dispatch(commit)["error"]["code"], "stale_revision")

    def test_three_solids_body_origins_target_inference_and_export_membership(self):
        self.plate()
        self.call("create_body", id="Housing")
        self.reject("ambiguous_body", "create_sketch", id="Ambiguous")
        self.call("sketch_rectangle", body="Housing", id="Second", plane="XZ", width=4, height=5)
        self.assertEqual(self.doc.Second.AttachmentSupport[0][0], next(obj for obj in self.doc.Housing.Origin.OriginFeatures if obj.Name.startswith("XZ_Plane")))
        self.call("pad", id="SecondPad", profile="Second", length=3)
        self.reject("cross_body_reference", "set_parameter", body="Body", feature="SecondPad", parameter="Length", value=4)
        loose = self.doc.addObject("Part::Feature", "ReferenceSolid")
        loose.Shape = Part.makeBox(2, 3, 4, App.Vector(50, 50, 50))
        self.doc.recompute()
        self.doc.commitTransaction()
        self.call("inspect")
        self.assertEqual(self.state["measurements"]["solid_count"], 3)
        self.assertAlmostEqual(self.state["measurements"]["volume_mm3"], 1200 + 60 + 24)
        path = self.folder / "all-solids.step"
        self.call("export", path=str(path))
        self.assertEqual(len(Part.read(str(path)).Solids), 3)
        manifest = json.loads(path.with_suffix(".step.json").read_text())
        self.assertEqual(manifest["included_body_ids"], ["Body", "Housing", "ReferenceSolid"])
        self.call("export", path=str(self.folder / "housing.step"), body="Housing")
        self.assertEqual(len(Part.read(str(self.folder / "housing.step")).Solids), 1)

    def test_unmanaged_inspection_and_adoption_preserve_original_and_native_ids(self):
        unmanaged = App.newDocument("NativeReference")
        body = unmanaged.addObject("PartDesign::Body", "MotorHousing")
        feature = body.newObject("PartDesign::Feature", "Solid")
        feature.Shape = Part.makeBox(2, 4, 6)
        unmanaged.recompute()
        source = self.folder / "source.FCStd"
        unmanaged.saveAs(str(source))
        App.closeDocument(unmanaged.Name)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        self.call("open", path=str(source))
        original_doc = self.doc
        signature = intent_signature(original_doc)
        self.assertFalse(self.state["managed"])
        self.assertIsNone(original_doc.getObject("KurtShapeProject"))
        self.reject("unmanaged_document", "rebuild")
        self.reject("adoption_destination_exists", "adopt", path=str(source))
        self.call("adopt", path=str(self.folder / "adopted.FCStd"))
        self.assertTrue(self.state["managed"])
        self.assertIsNotNone(self.doc.MotorHousing)
        self.assertAlmostEqual(self.state["measurements"]["volume_mm3"], 48)
        self.assertEqual(intent_signature(original_doc), signature)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), digest)
        self.assertIsNone(original_doc.getObject("KurtShapeProject"))
        self.call("create_sketch", id="Editable", plane="YZ")
        self.assertIn(self.doc.Editable, self.doc.MotorHousing.Group)

    def test_unmanaged_script_objects_are_inspectable_but_not_adoptable(self):
        doc = App.newDocument("UnmanagedProxy")
        doc.addObject("Part::FeaturePython", "CustomFeature")
        doc.recompute()
        path = self.folder / "custom.FCStd"
        doc.saveAs(str(path))
        App.closeDocument(doc.Name)
        self.call("open", path=str(path))
        self.assertIn("CustomFeature", self.state["unsupported_objects"])
        self.reject("unsupported_adoption", "adopt", path=str(self.folder / "copy.FCStd"))

    def test_user_granted_project_folder_persists_and_bridge_cannot_self_grant(self):
        with tempfile.TemporaryDirectory(prefix="review-project-folder-", dir=ROOT.parent.parent) as folder:
            path = Path(folder) / "user-part.FCStd"
            self.reject("path_outside_workspace", "save", path=str(path))
            self.core.settings.grant_destination(path)
            self.call("save", path=str(path))
            from kurtshape.settings import Settings
            reloaded = Settings(ROOT)
            self.assertIn(path.parent.resolve(), reloaded.roots)
            self.assertEqual(reloaded.last_directory, str(path.parent))

    def test_pierce_follows_crossing_curve_and_undo_removes_native_reference(self):
        self.call("create_sketch", id="Crossing", plane="XZ")
        self.call("add_line", sketch="Crossing", x1=2, y1=-5, x2=2, y2=5)
        self.call("create_sketch", id="Target")
        self.doc.Target.addGeometry(Part.Point(App.Vector(4, 0, 0)))
        self.doc.recompute()
        self.doc.commitTransaction()
        self.call("inspect")
        self.call("begin_sketch_edit", feature="Target")
        self.call("pierce", sketch="Target", geometry=0, point=1, target="Crossing", subelement="Edge1")
        self.assertAlmostEqual(self.doc.Target.Geometry[0].X, 2)
        self.call("finish_sketch_edit")
        self.call("set_parameter", feature="Crossing", parameter="StartX", value=3)
        self.call("set_parameter", feature="Crossing", parameter="EndX", value=3)
        self.assertAlmostEqual(self.doc.Target.Geometry[0].X, 3)
        self.call("undo")
        self.call("undo")
        self.call("undo")
        self.assertEqual(len(self.doc.Target.ExternalGeometry), 0)

    def test_pierce_coplanar_curve_rejects_without_partial_constraint_or_reference(self):
        self.call("create_sketch", id="Coplanar")
        self.call("add_line", sketch="Coplanar", x1=1, y1=0, x2=2, y2=0)
        self.call("create_sketch", id="Target")
        self.doc.Target.addGeometry(Part.Point(App.Vector(4, 0, 0)))
        self.doc.recompute()
        self.doc.commitTransaction()
        self.call("inspect")
        self.call("begin_sketch_edit", feature="Target")
        signature = intent_signature(self.doc)
        self.reject("ambiguous_intersection", "pierce", sketch="Target", geometry=0, target="Coplanar", subelement="Edge1")
        self.assertEqual(intent_signature(self.doc), signature)
        self.assertEqual(self.core.inspect(self.doc)["active_sketch_edit"], "Target")

    def test_checkpoint_restores_unfinished_draft_and_explicit_cancel_restores_accepted_sketch(self):
        self.call("create_sketch", id="Draft")
        self.call("begin_sketch_edit", feature="Draft")
        self.call("add_circle", sketch="Draft", x=0, y=0, diameter=4)
        path = self.core.checkpoint(self.doc, force=True)
        document_name = self.doc.Name
        App.closeDocument(document_name)
        response = self.core.dispatch({"op": "recover", "path": str(path)})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        self.assertEqual(self.state["active_sketch_edit"], "Draft")
        self.assertEqual(self.doc.Draft.GeometryCount, 1)
        self.assertEqual(self.doc.FileName, "")
        self.call("finish_sketch_edit", cancel=True)
        self.assertEqual(self.doc.Draft.GeometryCount, 0)

    def test_corrupt_checkpoint_is_rejected_and_previous_pair_remains_readable(self):
        self.plate()
        path = self.core.checkpoint(self.doc, force=True)
        self.call("set_parameter", feature="Pad", parameter="Length", value=9)
        self.core.checkpoint(self.doc, force=True)
        snapshot, _ = self.core.recovery.read(path)
        snapshot.write_bytes(b"incomplete")
        with self.assertRaises(ValueError):
            self.core.recovery.read(path)
        previous = path.with_suffix(".previous.json")
        data = json.loads(previous.read_text())
        previous_snapshot = snapshot.with_suffix(".previous.FCStd")
        self.assertEqual(hashlib.sha256(previous_snapshot.read_bytes()).hexdigest(), data["sha256"])
        self.assertEqual(self.core.recovery.read(previous)[0], previous_snapshot)


if __name__ == "__main__":
    unittest.main(verbosity=2)
