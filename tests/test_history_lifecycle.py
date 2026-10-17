"""Predictable sketch history, operation helper lifecycle and rolled-back modeling."""
import os
from pathlib import Path
import sys
import time
import unittest

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
from kurtshape import studio
from kurtshape.core import Controller, intent_signature
from kurtshape.extrusion_preview import ExtrusionEvaluator
from kurtshape.preview_worker import NativePreviewWorker


class HistoryLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="history-lifecycle-tests-")
        self.core = Controller()
        self.state = None
        self.call("new")

    def tearDown(self):
        self.core.close()
        for name in set(App.listDocuments()) - self.names:
            App.closeDocument(name)

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def request(self, op, **args):
        request = dict(op=op, **args)
        if op not in {"new", "open"}:
            request.update(document_id=self.state["document_id"], expected_revision=self.state["revision"])
        return self.core.dispatch(request)

    def call(self, op, **args):
        response = self.request(op, **args)
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        return self.state

    def invariant(self):
        return (intent_signature(self.doc), self.core._meta(self.doc).Revision, self.doc.UndoCount,
                self.doc.RedoCount, sorted(obj.Name for obj in self.doc.Objects))

    def reject(self, code, op, **args):
        before = self.invariant()
        response = self.request(op, **args)
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], code, response["error"])
        after = self.invariant()
        self.assertEqual(after[1:], before[1:])
        self.assertEqual(after[0], before[0], self._intent_diff())
        return response["error"]

    def _intent_diff(self):
        return "native intent changed"

    def normalize(self):
        """A legacy representative-only delete leaves derived Body Tips stale
        until the next rebuild; settle them before taking invariants."""
        self.core._recompute(self.doc)
        self.call("inspect")

    def volume(self):
        return sum(part.Shape.Volume for part in studio.current_parts(self.doc))

    def top(self, feature, z):
        shape = self.doc.getObject(feature).Shape
        return "Face" + str(next(index + 1 for index, face in enumerate(shape.Faces)
                                 if abs(face.CenterOfMass.z - z) < 1e-7 and face.normalAt(0, 0).z > 0.999))

    def new_sketch(self, name, **attachment):
        """The GUI's sequence: create, then immediately lease the sketch."""
        self.call("create_sketch", id=name, **attachment)
        self.call("begin_sketch_edit", feature=name)

    def orphans(self):
        return self.request("orphan_helpers")["result"]["groups"]

    # 1. Sketch history -------------------------------------------------

    def test_finished_new_sketch_is_one_undo_and_one_redo_step(self):
        self.call("sketch_rectangle", id="Base", width=20, height=10)
        self.call("pad", id="Pad", profile="Base", length=6)
        face = self.top("Pad", 6)
        self.new_sketch("Detail", support={"feature": "Pad", "subelement": face})
        self.call("add_line", sketch="Detail", x1=1, y1=1, x2=5, y2=1)
        self.call("add_line", sketch="Detail", x1=5, y1=1, x2=5, y2=4)
        self.call("finish_sketch_edit")
        self.call("undo")
        self.assertIsNone(self.doc.getObject("Detail"))
        self.assertIsNotNone(self.doc.getObject("Pad"))
        self.call("redo")
        detail = self.doc.getObject("Detail")
        self.assertEqual(detail.GeometryCount, 2)
        self.assertEqual((detail.AttachmentSupport[0][0].Name, tuple(detail.AttachmentSupport[0][1])), ("Pad", (face,)))
        self.assertAlmostEqual(detail.getGlobalPlacement().Base.z, 6)
        # Editing an existing sketch is an ordinary undoable edit.
        self.call("begin_sketch_edit", feature="Detail")
        self.call("add_line", sketch="Detail", x1=5, y1=4, x2=1, y2=1)
        self.call("finish_sketch_edit")
        self.call("undo")
        self.assertEqual(self.doc.Detail.GeometryCount, 2)
        self.call("redo")
        self.assertEqual(self.doc.Detail.GeometryCount, 3)
        self.call("undo")
        self.call("undo")
        self.assertIsNone(self.doc.getObject("Detail"))
        self.call("undo")
        self.assertIsNone(self.doc.getObject("Pad"))

    def test_extrude_after_new_sketch_and_unchanged_cancel_paths(self):
        self.new_sketch("Profile", plane="XY")
        self.call("add_rectangle", sketch="Profile", width=10, height=5)
        self.call("finish_sketch_edit")
        self.call("pad", id="Pad", profile="Profile", length=3)
        self.call("undo")
        self.assertIsNone(self.doc.getObject("Pad"))
        self.assertIsNotNone(self.doc.getObject("Profile"))
        self.call("undo")
        self.assertIsNone(self.doc.getObject("Profile"))
        # Finishing a new sketch without edits remains one creation step.
        self.new_sketch("Empty", plane="XY")
        self.call("finish_sketch_edit")
        self.call("undo")
        self.assertIsNone(self.doc.getObject("Empty"))
        # Cancel keeps its existing meaning: the accepted (empty) sketch stays.
        self.new_sketch("Canceled", plane="XY")
        self.call("add_line", sketch="Canceled", x1=0, y1=0, x2=3, y2=0)
        self.call("finish_sketch_edit", cancel=True)
        self.assertEqual(self.doc.Canceled.GeometryCount, 0)
        self.call("undo")
        self.assertIsNone(self.doc.getObject("Canceled"))

    def test_intervening_change_keeps_creation_and_edit_separate(self):
        self.call("create_sketch", id="Named", plane="XY")
        self.call("rename_feature", feature="Named", name="Renamed sketch")
        self.call("begin_sketch_edit", feature="Named")
        self.call("add_line", sketch="Named", x1=0, y1=0, x2=3, y2=0)
        self.call("finish_sketch_edit")
        self.call("undo")
        self.assertEqual(self.doc.Named.GeometryCount, 0)
        self.assertEqual(self.doc.Named.Label, "Renamed sketch")

    # 2. Operation helper lifecycle --------------------------------------

    def studio_cut(self):
        self.call("sketch_rectangle", id="Base", width=20, height=10)
        self.call("pad", id="Plate", profile="Base", length=6, operation="new")
        self.plate_volume = self.volume()
        self.objects_before_cut = {obj.Name for obj in self.doc.Objects}
        self.call("sketch_circle", id="Hole", x=5, y=5, diameter=2, plane="XY")
        self.call("pocket", id="Cut", profile="Hole", length=2, through_all=False, reversed=False, operation="remove")
        self.cut_volume = self.volume()

    def test_deleting_studio_operation_removes_its_helpers_and_undo_restores_them(self):
        self.studio_cut()
        tagged = {obj.Name for obj in studio.operation_members(self.doc, "Cut")}
        helpers = studio.native_closure(self.doc, tagged)  # with generated Bodies' origins
        self.assertGreater(len(helpers), len(tagged))
        self.assertIn("CutToolProfile", helpers)
        self.assertNotIn("BaseFeature", helpers)  # Plate's own FeatureBase is a shared input
        plan = self.core.delete_features_plan(self.doc, ["Cut"])
        self.assertEqual(set(plan["helpers"]), helpers)
        self.call("delete_features", features=["Cut"])
        self.assertEqual(self.orphans(), [])
        self.assertEqual({obj.Name for obj in self.doc.Objects}, self.objects_before_cut | {"Hole"})
        self.assertAlmostEqual(self.volume(), self.plate_volume)
        self.call("delete_features", features=["Hole"])
        self.call("undo")
        self.call("undo")
        self.assertTrue(helpers <= {obj.Name for obj in self.doc.Objects})
        self.assertAlmostEqual(self.volume(), self.cut_volume)
        self.call("redo")
        self.assertEqual(self.orphans(), [])
        self.assertAlmostEqual(self.volume(), self.plate_volume)

    def studio_turned_part(self):
        """A New revolve (a Part tool outside every Body) consumed by a scoped Intersect."""
        self.objects_before_turn = {obj.Name for obj in self.doc.Objects}
        self.call("sketch_rectangle", id="TurnProfile", plane="XZ", x=3, width=2, height=5)
        self.call("revolve", id="Turn", profile="TurnProfile", angle="360 deg", operation="new")
        part = self.state["studio"]["parts"][-1]["id"]
        self.call("sketch_rectangle", id="TrimProfile", plane="XY", x=-10, y=-4, width=20, height=8)
        self.call("pad", id="Trim", profile="TrimProfile", length=10, operation="intersect", merge_scope=[part])
        self.trimmed_volume = self.volume()

    def test_new_part_tool_operation_is_deletable_with_its_consumers(self):
        self.studio_turned_part()
        self.assertEqual(self.doc.Turn.TypeId, "Part::Revolution")
        self.reject("external_dependency", "delete_features", features=["Turn"])
        plan = self.core.delete_features_plan(self.doc, ["Trim", "TrimProfile", "Turn", "TurnProfile"])
        self.assertIn("Turn", plan["selected"])
        self.call("delete_features", features=["Trim", "TrimProfile", "Turn", "TurnProfile"])
        self.assertEqual(self.orphans(), [])
        self.assertEqual(studio.order(self.doc), [])
        self.assertEqual({obj.Name for obj in self.doc.Objects}, self.objects_before_turn)
        self.call("undo")
        self.assertAlmostEqual(self.volume(), self.trimmed_volume)

    def test_new_part_tool_operation_is_deletable_alone(self):
        self.objects_before_turn = {obj.Name for obj in self.doc.Objects}
        self.call("sketch_rectangle", id="TurnProfile", plane="XZ", x=3, width=2, height=5)
        self.call("revolve", id="Turn", profile="TurnProfile", angle="360 deg", operation="new")
        self.call("delete_features", features=["Turn"])
        self.assertEqual(self.orphans(), [])
        self.assertEqual({obj.Name for obj in self.doc.Objects}, self.objects_before_turn | {"TurnProfile"})
        self.assertAlmostEqual(self.volume(), 0)

    def test_operation_with_a_surviving_consumer_is_kept(self):
        self.studio_cut()
        self.call("sketch_circle", id="Second", x=15, y=5, diameter=2, plane="XY")
        self.call("pocket", id="Later", profile="Second", length=2, through_all=False, reversed=False, operation="remove")
        self.reject("external_dependency", "delete_features", features=["Cut"])
        self.assertEqual(self.orphans(), [])

    def test_existing_orphans_are_reported_and_repaired_only_explicitly(self):
        self.studio_cut()
        # Reproduce a file saved by the earlier deletion path: only the
        # representative was removed, leaving its tagged helpers behind.
        self.doc.openTransaction("legacy representative-only delete")
        self.doc.removeObject("Cut")
        self.doc.commitTransaction()
        self.doc.recompute()
        self.call("inspect")
        path = self.folder / "legacy-orphans.FCStd"
        self.call("save", path=str(path))
        App.closeDocument(self.doc.Name)
        response = self.core.dispatch({"op": "open", "path": str(path)})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        self.normalize()
        objects = {obj.Name for obj in self.doc.Objects}
        groups = self.orphans()
        self.assertEqual([group["owner"] for group in groups], ["Cut"])
        self.assertTrue(groups[0]["repairable"])
        self.assertIn("Hole", groups[0]["inputs"])
        self.assertEqual({obj.Name for obj in self.doc.Objects}, objects)  # opening never removes
        error = self.reject("orphan_helpers", "delete_features", features=["Hole"])
        self.assertEqual(error["owner"], "Cut")
        self.reject("missing_reference", "repair_orphan_helpers", owners=["Unknown"])
        result = self.call("repair_orphan_helpers")
        report = result["repair_report"]
        self.assertEqual(report["removed_groups"], ["Cut"])
        self.assertEqual(set(report["removed_objects"]), set(groups[0]["objects"]))
        self.assertIn("Hole", report["kept_inputs"])
        self.assertEqual(self.orphans(), [])
        self.assertAlmostEqual(self.volume(), self.plate_volume)
        self.call("undo")
        self.assertEqual({obj.Name for obj in self.doc.Objects}, objects)
        self.call("redo")
        self.call("delete_features", features=["Hole"])
        self.reject("no_orphans", "repair_orphan_helpers")

    def test_orphans_with_surviving_consumers_are_never_repaired(self):
        self.studio_cut()
        self.doc.openTransaction("legacy representative-only delete")
        self.doc.removeObject("Cut")
        consumer = self.doc.addObject("Part::Feature", "UsesHelper")
        consumer.addProperty("App::PropertyLink", "Source")
        consumer.Source = self.doc.CutTool
        self.doc.commitTransaction()
        self.normalize()
        groups = self.orphans()
        self.assertFalse(groups[0]["repairable"])
        self.assertEqual(groups[0]["consumers"], ["UsesHelper"])
        error = self.reject("orphan_has_consumers", "repair_orphan_helpers", owners=["Cut"])
        self.assertEqual(error["owners"], ["Cut"])
        self.reject("no_orphans", "repair_orphan_helpers")

    def legacy_orphan_with_origin_consumer(self):
        self.studio_cut()
        plane = self.doc.CutPart.Origin.OriginFeatures[3]  # implicit child of a generated Body
        self.doc.openTransaction("legacy representative-only delete")
        self.doc.removeObject("Cut")
        survivor = self.doc.addObject("Part::Feature", "Survivor")
        survivor.Shape = __import__("Part").makeBox(1, 1, 1)
        survivor.addProperty("App::PropertyLinkGlobal", "Source")
        survivor.Source = plane
        self.doc.commitTransaction()
        self.normalize()
        return plane.Name

    def test_repair_counts_native_body_children_and_keeps_their_consumers(self):
        self.studio_cut()
        self.doc.openTransaction("legacy representative-only delete")
        self.doc.removeObject("Cut")
        self.doc.commitTransaction()
        self.normalize()
        group = self.orphans()[0]
        origins = {self.doc.CutPart.Origin.Name, *(f.Name for f in self.doc.CutPart.Origin.OriginFeatures)}
        self.assertTrue(origins <= set(group["objects"]))
        self.assertFalse(origins & set(group["inputs"]))
        before = {obj.Name for obj in self.doc.Objects}
        report = self.call("repair_orphan_helpers")["repair_report"]
        vanished = before - {obj.Name for obj in self.doc.Objects}
        self.assertEqual(vanished, set(group["objects"]))
        self.assertFalse(vanished & set(report["kept_inputs"]))

    def test_surviving_consumer_of_an_implicit_child_blocks_repair_and_deletion(self):
        plane = self.legacy_orphan_with_origin_consumer()
        group = self.orphans()[0]
        self.assertFalse(group["repairable"])
        self.assertEqual(group["consumers"], ["Survivor"])
        self.reject("orphan_has_consumers", "repair_orphan_helpers", owners=["Cut"])
        self.reject("no_orphans", "repair_orphan_helpers")
        self.assertEqual(self.doc.Survivor.Source.Name, plane)
        # Ordinary operation deletion counts the same implicit children.
        self.call("new")
        self.studio_cut()
        self.doc.openTransaction("survivor")
        survivor = self.doc.addObject("Part::Feature", "Survivor")
        survivor.Shape = __import__("Part").makeBox(1, 1, 1)
        survivor.addProperty("App::PropertyLinkGlobal", "Source")
        survivor.Source = self.doc.CutPart.Origin.OriginFeatures[3]
        self.doc.commitTransaction()
        self.normalize()
        error = self.reject("external_dependency", "delete_features", features=["Cut"])
        self.assertEqual(error["feature"], "Survivor")
        self.assertIsNotNone(self.doc.Survivor.Source)

    def test_zero_current_solid_history_allows_original_body_sketches(self):
        # Legacy native Pad in the original Body, rolled back before it.
        self.call("sketch_rectangle", id="Base", width=20, height=10)
        self.call("pad", id="Plate", profile="Base", length=6)
        self.call("rollback", index=0)
        self.assertEqual(studio.held_bodies(self.doc), set())
        self.call("create_sketch", id="Inserted", body="Body", plane="XY")
        self.assertEqual(self.state["studio"]["feature_order"][0], "Inserted")
        self.call("rollback", index=self.state["studio"]["feature_order"].index("Base") + 1)
        self.call("begin_sketch_edit", feature="Base", body="Body")
        self.call("finish_sketch_edit", cancel=True)
        self.call("rollback", index=len(self.state["studio"]["feature_order"]))
        self.assertEqual(self.state["build_status"], "valid")
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, 1200)

    def test_zero_current_solid_studio_insertion_keeps_future_identity(self):
        self.call("sketch_rectangle", id="Base", width=20, height=10)
        self.call("pad", id="Plate", profile="Base", length=6, operation="new")
        plate_part = studio.part_id(self.doc.getObject(self.doc.Plate.KurtShapeOutputParts[0]))
        self.call("rollback", index=0)
        self.assertIn(plate_part, studio.held_part_ids(self.doc))
        self.call("create_sketch", id="Inserted", body="Body", plane="XY")
        self.call("add_rectangle", sketch="Inserted", width=5, height=5, x=40, y=0)
        self.call("pad", id="Early", profile="Inserted", length=2, operation="new")
        early_part = studio.part_id(self.doc.getObject(self.doc.Early.KurtShapeOutputParts[0]))
        self.assertNotEqual(early_part, plate_part)
        order = self.state["studio"]["feature_order"]
        self.assertLess(order.index("Early"), order.index("Base"))
        self.call("rollback", index=len(order))
        self.assertEqual(self.state["build_status"], "valid")
        parts = {studio.part_id(body): round(body.Shape.Volume, 6) for body in studio.current_parts(self.doc)}
        self.assertEqual(parts, {early_part: 50.0, plate_part: 1200.0})

    # 3. Rolled-back modeling --------------------------------------------

    def rolled_back(self):
        self.call("sketch_rectangle", id="Base", width=20, height=10)
        self.call("pad", id="Plate", profile="Base", length=6, operation="new")
        self.call("create_body", id="FarBody")
        self.call("sketch_rectangle", body="FarBody", id="FarProfile", width=10, height=10, x=40, y=0, plane="XY")
        self.call("pad", id="Far", profile="FarProfile", length=6, operation="new")
        order = self.state["studio"]["feature_order"]
        self.call("rollback", index=order.index("FarProfile"))
        # Only the generated future result is held; FarBody stays an authoring Body.
        self.assertEqual(studio.held_bodies(self.doc), {"FarToolBody"})

    def bridge(self):
        self.call("create_sketch", id="Bridge", plane="XY")
        self.call("add_rectangle", sketch="Bridge", width=30, height=4, x=15, y=3)
        return {"op": "pad", "profile": "Bridge", "length": 3, "operation": "add", "merge_scope": "auto", "reversed": False}

    def test_held_future_parts_reject_new_work_and_lineage(self):
        self.rolled_back()
        self.reject("held_part", "create_sketch", id="Inside", body="FarToolBody", plane="XY")
        # A New result from the current part never adopts a held part's identity.
        self.bridge()
        self.call("pad", id="Bridged", profile="Bridge", length=3, operation="new")
        new_part = self.doc.getObject("Bridged").KurtShapeOutputParts[0]
        self.assertNotEqual(studio.part_id(self.doc.getObject(new_part)), "FarBody")
        self.call("rollback", index=len(self.state["studio"]["feature_order"]))
        self.assertEqual(self.state["build_status"], "valid")
        self.assertEqual(len(studio.current_parts(self.doc)), 3)

    def test_rolled_back_preview_paths_model_only_the_active_state(self):
        self.rolled_back()
        proposal = self.bridge()
        expected = 20 * 10 * 6 + 25 * 4 * 3  # Plate plus the overhang; Far stays held
        evaluator = ExtrusionEvaluator(self.core, self.doc, self.state["revision"])
        self.addCleanup(evaluator.close)
        local = evaluator.evaluate(proposal)
        self.assertTrue(local.valid, local.error)
        self.assertAlmostEqual(local.shape.Volume, expected)
        self.assertLess(local.shape.BoundBox.XMax, 45 + 1e-7)
        worker = NativePreviewWorker(Path(App.getHomePath()) / "bin" / ("python.exe" if os.name == "nt" else "python"),
                                     self.folder)
        self.addCleanup(worker.close)
        self.doc.saveCopy(str(worker.snapshot))
        worker.submit(1, proposal)
        deadline = time.monotonic() + 120
        response = None
        while response is None and time.monotonic() < deadline:
            time.sleep(0.05)
            response = worker.poll()
        self.assertTrue(response and response["valid"], response)
        self.assertAlmostEqual(response["measurements"]["volume_mm3"], expected)
        # A rollback change makes the earlier task stale; it never models.
        stale = self.state["revision"]
        self.call("rollback", index=len(self.state["studio"]["feature_order"]))
        self.assertEqual(evaluator.evaluate(proposal).error["code"], "stale_revision")
        self.call("rollback", index=self.state["studio"]["feature_order"].index("FarProfile"))
        self.assertNotEqual(self.state["revision"], stale)
        self.call("pad", id="BridgePad", **{key: value for key, value in proposal.items() if key != "op"})
        order = self.state["studio"]["feature_order"]
        self.assertLess(order.index("BridgePad"), order.index("FarProfile"))
        self.assertEqual(list(self.doc.BridgePad.KurtShapeMergePartIds), ["Body"])
        self.assertAlmostEqual(self.volume(), expected)
        self.call("rollback", index=len(order))
        self.assertEqual(self.state["build_status"], "valid")
        self.assertAlmostEqual(self.volume(), expected + 600)


if __name__ == "__main__":
    unittest.main()
