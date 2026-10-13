"""Native attachments, sketch transactions and history safety; bundled Python."""
from pathlib import Path
import math
import shutil
import sys
import tempfile
import unittest
import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
import Sketcher
from kurtshape.core import Controller, OperationError, intent_signature
from kurtshape import studio


class SketchPlaneTests(unittest.TestCase):
    def setUp(self):
        self.initial_names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="sketch-plane-session-")
        self.core = Controller()
        self.state = self.call("new", name="Sketch plane acceptance")

    def tearDown(self):
        for name in set(App.listDocuments()) - self.initial_names:
            App.closeDocument(name)

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def request(self, op, **args):
        request = {"op": op, **args}
        if op not in {"new", "open"}:
            request.update(document_id=self.state["document_id"], expected_revision=self.state["revision"])
        return self.core.dispatch(request)

    def call(self, op, **args):
        response = self.request(op, **args)
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        return self.state

    def rejected(self, code, op, **args):
        response = self.request(op, **args)
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], code, response)
        return response

    def plate(self):
        self.call("sketch_rectangle", id="Plate", width=20, height=12)
        self.call("pad", id="Pad", profile="Plate", length=6)

    def top_face(self):
        return "Face" + str(next(i+1 for i, face in enumerate(self.doc.Pad.Shape.Faces)
                                  if abs(face.CenterOfMass.z-6) < 1e-7 and isinstance(face.Surface, Part.Plane)))

    def test_origin_plane_pads_use_native_rotated_coordinates(self):
        for plane, expected in [("XY", [20,12,6]), ("XZ", [20,6,12]), ("YZ", [6,20,12])]:
            with self.subTest(plane=plane):
                if plane != "XY":
                    App.closeDocument(self.doc.Name)
                    self.call("new", name=plane + " plane part")
                self.call("create_sketch", id="Profile", plane=plane)
                sk = self.doc.Profile
                self.assertEqual(sk.AttachmentSupport[0][0], self.doc.getObject(plane+"_Plane"))
                self.assertEqual(sk.MapMode, "FlatFace")
                self.call("add_rectangle", sketch="Profile", width=20, height=12)
                self.assertTrue(sk.FullyConstrained)
                self.call("pad", profile="Profile", length=6)
                self.assertAlmostEqual(self.state["measurements"]["volume_mm3"], 20*12*6, places=7)
                for actual, target in zip(self.state["measurements"]["bbox_mm"]["size"], expected):
                    self.assertAlmostEqual(actual, target, places=7)

    def test_face_attachment_follows_upstream_thickness_and_cuts_inward(self):
        self.plate()
        reference = self.top_face()
        self.call("create_sketch", id="TopHole", support={"feature":"Pad", "subelement":reference})
        sk = self.doc.TopHole
        self.assertEqual(sk.AttachmentSupport[0], (self.doc.Pad, (reference,)))
        self.assertAlmostEqual(sk.Placement.Base.z, 6, places=7)
        # FlatFace coordinates may have their origin/orientation on a corner.
        center = sk.Placement.inverse().multVec(App.Vector(10,6,6))
        self.call("add_circle", sketch="TopHole", x=center.x, y=center.y, diameter=4)
        self.call("pocket", id="Hole", profile="TopHole", length=2, through_all=False)
        self.assertFalse(self.doc.Hole.Reversed)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, 20*12*6-math.pi*2**2*2, places=6)
        self.call("set_parameter", feature="Pad", parameter="Length", value=9)
        self.assertAlmostEqual(sk.Placement.Base.z, 9, places=7)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, 20*12*9-math.pi*2**2*2, places=6)
        self.call("undo")
        self.assertAlmostEqual(sk.Placement.Base.z, 6, places=7)
        self.call("redo")
        with tempfile.TemporaryDirectory(prefix="face-attached-relocation-", dir=support.TEST_TMP, ignore_cleanup_errors=True) as temporary:
            working = Path(temporary)
            source = working/"face-part.FCStd"
            relocated = working/"relocated-face-part.FCStd"
            self.call("save", path=str(source))
            identifier = self.state["document_id"]
            App.closeDocument(self.doc.Name)
            shutil.copy2(source, relocated)
            self.call("open", path=str(relocated))
            self.assertEqual(self.state["document_id"], identifier)
            self.call("rebuild")
            self.assertEqual(self.doc.TopHole.AttachmentSupport[0], (self.doc.Pad, (reference,)))
            self.assertAlmostEqual(self.doc.TopHole.Placement.Base.z, 9, places=7)
            self.call("set_parameter", feature="Pad", parameter="Length", value=11)
            self.assertAlmostEqual(self.doc.TopHole.Placement.Base.z, 11, places=7)
            self.assertEqual(self.state["measurements"]["solid_count"], 1)

    def test_body_face_resolves_actual_tip_without_body_self_reference(self):
        self.plate()
        reference = self.top_face()
        self.call("create_sketch", id="BodyFaceSketch", support={"feature":"Body", "subelement":reference})
        self.assertEqual(self.doc.BodyFaceSketch.AttachmentSupport[0][0], self.doc.Pad)
        self.assertNotIn("Body", [item.Name for item in self.doc.BodyFaceSketch.OutList])

    def test_native_datum_plane_attachment_keeps_offset_link(self):
        datum = self.doc.Body.newObject("PartDesign::Plane", "OffsetPlane")
        datum.AttachmentSupport = (self.doc.XY_Plane, [""])
        datum.MapMode = "FlatFace"
        datum.AttachmentOffset.Base.z = 7
        self.doc.recompute()
        self.call("inspect")
        self.call("sketch_rectangle", id="DatumProfile", support={"feature":"OffsetPlane"}, width=8, height=4)
        self.call("pad", profile="DatumProfile", length=3)
        self.assertAlmostEqual(self.doc.Body.Shape.BoundBox.ZMin, 7, places=7)
        datum.AttachmentOffset.Base.z = 12
        self.doc.recompute()
        self.call("inspect")
        self.assertAlmostEqual(self.doc.DatumProfile.Placement.Base.z, 12, places=7)
        self.assertAlmostEqual(self.doc.Body.Shape.BoundBox.ZMin, 12, places=7)

    def test_ambiguous_nonplanar_missing_and_cross_body_support_reject(self):
        self.call("sketch_circle", id="Round", x=0, y=0, diameter=10)
        self.call("pad", profile="Round", length=6)
        curved = "Face" + str(next(i+1 for i,f in enumerate(self.doc.Pad.Shape.Faces) if not isinstance(f.Surface, Part.Plane)))
        self.rejected("nonplanar_support", "create_sketch", id="Rejected", support={"feature":"Pad", "subelement":curved})
        self.assertIsNone(self.doc.getObject("Rejected"))
        self.rejected("ambiguous_support", "create_sketch", support={"feature":"Pad"})
        self.rejected("missing_reference", "create_sketch", support={"feature":"Pad", "subelement":"Face999"})
        self.rejected("invalid_argument", "create_sketch", plane="XY", support={"feature":"XY_Plane"})
        self.rejected("unsupported_plane", "create_sketch", plane="ZX")
        other = self.doc.addObject("PartDesign::Body", "OtherBody")
        feature = other.newObject("PartDesign::Feature", "OtherSolid")
        feature.Shape = Part.makeBox(2,2,2)
        self.doc.recompute()
        self.call("inspect")
        self.rejected("cross_body_reference", "create_sketch", body="Body", support={"feature":"OtherSolid", "subelement":"Face1"})

    def test_explicit_pocket_direction_is_respected_and_auto_origin_cut_works(self):
        self.plate()
        self.call("sketch_circle", id="BottomHole", x=10, y=6, diameter=4)
        volume = self.doc.Body.Shape.Volume
        self.rejected("empty_cut", "pocket", id="RejectedCut", profile="BottomHole", reversed=False)
        self.assertIsNone(self.doc.getObject("RejectedCut"))
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, volume, places=7)
        self.call("pocket", id="AcceptedCut", profile="BottomHole")
        self.assertTrue(self.doc.AcceptedCut.Reversed)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, (20*12-math.pi*2**2)*6, places=6)

    def test_managed_sketch_edits_commit_as_one_undo_and_cancel_restore(self):
        self.call("create_sketch", id="Managed", plane="XZ")
        self.call("begin_sketch_edit", feature="Managed")
        self.assertEqual(self.state["active_sketch_edit"], "Managed")
        self.assertTrue(self.doc.HasPendingTransaction)
        self.call("add_rectangle", sketch="Managed", width=20, height=12)
        self.call("add_circle", sketch="Managed", x=8, y=6, diameter=4, construction=True)
        self.rejected("sketch_edit_active", "rebuild")
        self.rejected("managed_sketch_mismatch", "add_line", sketch="Unknown", x1=0,y1=0,x2=2,y2=2)
        self.call("finish_sketch_edit")
        self.assertIsNone(self.state["active_sketch_edit"])
        self.assertFalse(self.doc.HasPendingTransaction)
        self.assertEqual(self.doc.Managed.GeometryCount, 5)
        self.call("undo")
        self.assertEqual(self.doc.Managed.GeometryCount, 0)
        self.call("redo")
        self.assertEqual(self.doc.Managed.GeometryCount, 5)
        self.call("begin_sketch_edit", feature="Managed")
        self.call("add_line", sketch="Managed", x1=1,y1=2,x2=4,y2=5, construction=True)
        self.assertTrue(self.doc.Managed.FullyConstrained)
        self.call("finish_sketch_edit", cancel=True)
        self.assertEqual(self.doc.Managed.GeometryCount, 5)

    def test_native_constraint_conflict_finish_preserves_draft_until_explicit_cancel(self):
        self.call("sketch_circle", id="Managed", x=2, y=3, diameter=4)
        self.call("begin_sketch_edit", feature="Managed")
        self.doc.Managed.addConstraint(Sketcher.Constraint("Diameter", 0, 6.0))
        self.doc.recompute()
        self.call("inspect")
        self.rejected("constraint_conflict", "finish_sketch_edit")
        self.call("inspect")
        self.assertEqual(self.state["active_sketch_edit"], "Managed")
        self.assertEqual(self.doc.Managed.ConstraintCount, 4)
        self.call("finish_sketch_edit", cancel=True)
        self.assertIsNone(self.state["active_sketch_edit"])
        self.assertEqual(self.doc.Managed.ConstraintCount, 3)
        self.assertAlmostEqual(self.doc.Managed.Geometry[0].Radius, 2, places=7)

    def test_managed_undo_redo_tracks_typed_and_native_edits_keeps_transaction(self):
        self.call("create_sketch", id="Managed", plane="YZ")
        initial = self.state["revision"]
        self.call("begin_sketch_edit", feature="Managed")
        self.rejected("empty_history", "undo")
        self.call("add_rectangle", sketch="Managed", width=8, height=4)
        self.call("add_circle", sketch="Managed", x=3, y=2, diameter=1, construction=True)
        self.call("undo")
        self.assertEqual(self.doc.Managed.GeometryCount, 4)
        self.assertTrue(self.doc.HasPendingTransaction)
        self.assertEqual(self.doc.Managed.AttachmentSupport[0][0], self.doc.YZ_Plane)
        self.call("redo")
        self.assertEqual(self.doc.Managed.GeometryCount, 5)
        # Native Sketcher changes are detected without a parallel sketch model.
        width_index = next(i for i,c in enumerate(self.doc.Managed.Constraints) if c.Name=="Width")
        self.doc.Managed.setDatum(width_index, App.Units.Quantity("12 mm"))
        self.doc.recompute()
        self.call("inspect")
        self.call("undo")
        self.assertAlmostEqual(next(c.Value for c in self.doc.Managed.Constraints if c.Name=="Width"), 8, places=7)
        self.call("redo")
        self.assertAlmostEqual(next(c.Value for c in self.doc.Managed.Constraints if c.Name=="Width"), 12, places=7)
        self.call("finish_sketch_edit", cancel=True)
        self.assertEqual(self.doc.Managed.GeometryCount, 0)
        self.assertNotEqual(self.state["revision"], initial)

    def test_failed_managed_edit_does_not_reuse_pre_edit_revision(self):
        self.call("create_sketch", id="Managed")
        stale = dict(self.state)
        self.call("begin_sketch_edit", feature="Managed")
        self.call("add_circle", sketch="Managed", x=2,y=3,diameter=4)
        self.rejected("invalid_argument", "add_line", sketch="Managed", x1=0,y1=0,x2=0,y2=0)
        self.call("inspect")
        self.assertEqual(self.doc.Managed.GeometryCount, 1)
        self.assertEqual(self.state["active_sketch_edit"], "Managed")
        self.assertNotEqual(self.state["revision"], stale["revision"])
        response = self.core.dispatch({"op":"rename_feature", "feature":"Managed", "name":"Stale name",
                                      "document_id":stale["document_id"],"expected_revision":stale["revision"]})
        self.assertEqual(response["error"]["code"], "stale_revision")

    def test_cancel_after_native_auto_commit_preserves_prior_history_and_shape(self):
        self.plate()
        accepted = self.doc.Body.Shape.Volume
        self.call("begin_sketch_edit", feature="Plate")
        width_index = next(i for i,c in enumerate(self.doc.Plate.Constraints) if c.Name=="Width")
        self.doc.Plate.setDatum(width_index, App.Units.Quantity("30 mm"))
        self.doc.recompute()
        self.doc.commitTransaction()  # Native GUI resetEdit has this behavior.
        self.call("inspect")
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, 30*12*6, places=7)
        self.call("finish_sketch_edit", cancel=True)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, accepted, places=7)
        self.assertEqual(self.doc.RedoCount, 0)
        self.call("undo")
        self.assertIsNone(self.doc.getObject("Pad"))
        self.assertIsNotNone(self.doc.getObject("Plate"))
        self.call("redo")
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, accepted, places=7)
        self.assertEqual(self.doc.RedoCount, 0)

    def test_failed_finish_after_native_auto_commit_preserves_draft_and_can_repair(self):
        self.plate()
        accepted = self.doc.Body.Shape.Volume
        original_constraints = self.doc.Plate.ConstraintCount
        self.call("begin_sketch_edit", feature="Plate")
        self.doc.Plate.addConstraint(Sketcher.Constraint("Distance",0,30.0))
        self.doc.recompute()
        self.doc.commitTransaction()
        self.call("inspect")
        self.rejected("constraint_conflict", "finish_sketch_edit")
        self.call("inspect")
        self.assertEqual(self.state["active_sketch_edit"], "Plate")
        self.assertEqual(self.doc.Plate.ConstraintCount, original_constraints + 1)
        self.doc.Plate.delConstraint(original_constraints)
        self.doc.recompute()
        self.call("inspect")
        self.call("finish_sketch_edit")
        self.assertIsNone(self.state["active_sketch_edit"])
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, accepted, places=7)
        self.call("undo")
        self.assertIsNotNone(self.doc.getObject("Pad"))
        self.call("undo")
        self.assertIsNone(self.doc.getObject("Pad"))
        self.call("redo")
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, accepted, places=7)

    def test_external_native_history_change_rejects_without_undoing_prior_features(self):
        self.plate()
        self.call("begin_sketch_edit", feature="Plate")
        self.doc.abortTransaction()
        self.doc.undo()  # External bypass removed a prior accepted Pad.
        self.doc.recompute()
        self.call("inspect")
        self.rejected("sketch_history_changed", "finish_sketch_edit", cancel=True)
        self.assertIsNone(self.doc.getObject("Pad"))
        self.assertIsNotNone(self.doc.getObject("Plate"))
        # A compromised lease is released without replacing native history;
        # ordinary redo can recover the external undo before a fresh edit.
        self.call("inspect")
        self.assertIsNone(self.state["active_sketch_edit"])
        self.call("redo")
        self.assertIsNotNone(self.doc.getObject("Pad"))
        self.call("begin_sketch_edit", feature="Plate")
        self.call("finish_sketch_edit")

    def test_closed_native_document_lease_is_not_reused_on_same_uuid_reopen(self):
        self.plate()
        identifier = self.state["document_id"]
        with tempfile.TemporaryDirectory(prefix="closed-sketch-lease-reopen-", dir=support.TEST_TMP, ignore_cleanup_errors=True) as temporary:
            saved = Path(temporary)/"accepted-part.FCStd"
            self.call("save", path=str(saved))
            self.call("begin_sketch_edit", feature="Plate")
            width_index = next(i for i,c in enumerate(self.doc.Plate.Constraints) if c.Name=="Width")
            self.doc.Plate.setDatum(width_index, App.Units.Quantity("30 mm"))
            self.doc.recompute()
            self.call("inspect")
            self.assertIn(identifier, self.core.sketch_edits)
            App.closeDocument(self.doc.Name)
            listed = self.core.dispatch({"op":"list_documents"})
            self.assertTrue(listed["ok"], listed)
            self.assertEqual(listed["result"]["documents"], [])
            self.assertNotIn(identifier, self.core.sketch_edits)
            self.call("open", path=str(saved))
            self.assertEqual(self.state["document_id"], identifier)
            self.assertIsNone(self.state["active_sketch_edit"])
            self.assertAlmostEqual(self.doc.Body.Shape.Volume, 20*12*6, places=7)
            self.call("begin_sketch_edit", feature="Plate")
            self.call("finish_sketch_edit", cancel=True)
            self.assertAlmostEqual(self.doc.Body.Shape.Volume, 20*12*6, places=7)

    def test_direct_attach_clears_only_a_closed_document_edit_lease(self):
        self.call("create_sketch", id="Managed")
        self.call("begin_sketch_edit", feature="Managed")
        identifier = self.state["document_id"]
        live_lease = self.core.sketch_edits[identifier]
        # Re-attaching the same live native document retains its lease.
        self.core.attach(self.doc)
        self.assertIs(self.core.sketch_edits[identifier], live_lease)
        self.call("inspect")
        self.call("finish_sketch_edit", cancel=True)
        with tempfile.TemporaryDirectory(prefix="direct-attach-closed-lease-", dir=support.TEST_TMP, ignore_cleanup_errors=True) as temporary:
            saved = Path(temporary)/"accepted-sketch.FCStd"
            self.call("save", path=str(saved))
            self.call("begin_sketch_edit", feature="Managed")
            App.closeDocument(self.doc.Name)
            reopened = App.openDocument(str(saved))
            self.core.attach(reopened)
            self.assertNotIn(identifier, self.core.sketch_edits)
            self.state = self.core.inspect(reopened)
            self.assertIsNone(self.state["active_sketch_edit"])

    def test_finish_groups_multiple_native_command_transactions_without_prior_history_loss(self):
        self.call("create_sketch", id="Managed", plane="XZ")
        original_undo = self.doc.UndoCount
        self.call("begin_sketch_edit", feature="Managed")
        self.call("add_rectangle", sketch="Managed", width=20,height=12)
        self.doc.commitTransaction()
        # Native mouse tools may start/commit their own commands while editing.
        self.doc.openTransaction("Native circle command")
        self.doc.Managed.addGeometry(Part.Circle(App.Vector(8,6,0), App.Vector(0,0,1),2), True)
        self.doc.recompute()
        self.doc.commitTransaction()
        self.call("inspect")
        self.assertEqual(self.doc.UndoCount, original_undo+2)
        self.call("finish_sketch_edit")
        self.assertEqual(self.doc.UndoCount, original_undo+1)
        self.assertEqual(self.doc.Managed.GeometryCount, 5)
        self.assertEqual(self.doc.Managed.AttachmentSupport[0][0], self.doc.XZ_Plane)
        self.call("undo")
        self.assertEqual(self.doc.Managed.GeometryCount, 0)
        self.assertEqual(self.doc.UndoCount, original_undo)
        self.call("redo")
        self.assertEqual(self.doc.Managed.GeometryCount, 5)
        self.assertEqual(self.doc.UndoCount, original_undo+1)

    def test_unnamed_driving_dimensions_edit_by_native_constraint_index(self):
        self.call("create_sketch", id="NativeSketch")
        sk = self.doc.NativeSketch
        sk.addGeometry(Part.Circle(App.Vector(1,2,0), App.Vector(0,0,1), 3), False)
        index = sk.addConstraint(Sketcher.Constraint("Diameter", 0, 6.0))
        self.doc.recompute()
        self.call("inspect")
        feature = next(f for f in self.state["features"] if f["id"] == "NativeSketch")
        key = f"Constraints[{index}]"
        self.assertTrue(feature["parameters"][key]["editable"])
        self.call("set_parameter", feature="NativeSketch", parameter=key, value=10)
        self.assertAlmostEqual(sk.Geometry[0].Radius, 5, places=7)

    def test_arbitrary_spline_native_edits_and_construction_change_revision(self):
        self.call("create_sketch", id="SplineSketch")
        curve = Part.BSplineCurve()
        curve.buildFromPolesMultsKnots([App.Vector(0,0,0),App.Vector(1,2,0),App.Vector(3,2,0),App.Vector(4,0,0)], [4,4], [0.,1.], False, 3)
        sk = self.doc.SplineSketch
        sk.addGeometry(curve, False)
        self.doc.recompute()
        self.call("inspect")
        initial = self.state["revision"]
        signature = intent_signature(self.doc)
        replacement = sk.Geometry[0]
        replacement.setPole(2, App.Vector(1,4,0))
        sk.Geometry = [replacement]
        self.doc.recompute()
        self.call("inspect")
        self.assertNotEqual(self.state["revision"], initial)
        self.assertNotEqual(intent_signature(self.doc), signature)
        before_toggle = self.state["revision"]
        sk.toggleConstruction(0)
        self.call("inspect")
        self.assertNotEqual(self.state["revision"], before_toggle)
        unchanged = self.state["revision"]
        self.call("inspect")
        self.assertEqual(self.state["revision"], unchanged)

    def test_native_unnamed_angle_is_inspected_and_edited_in_radians(self):
        self.call("create_sketch", id="AngleSketch")
        sk = self.doc.AngleSketch
        sk.addGeometry(Part.LineSegment(App.Vector(0,0,0),App.Vector(2,2,0)), False)
        index = sk.addConstraint(Sketcher.Constraint("Angle", 0, math.pi/4))
        self.doc.recompute()
        self.call("inspect")
        key = f"Constraints[{index}]"
        feature = next(f for f in self.state["features"] if f["id"]=="AngleSketch")
        self.assertEqual(feature["parameters"][key]["unit"], "rad")
        self.call("set_parameter", feature="AngleSketch", parameter=key, value=math.pi/3)
        self.assertAlmostEqual(sk.Constraints[index].Value, math.pi/3, places=7)

    def test_rename_and_dependency_safe_delete_restore_native_tip_with_undo(self):
        self.plate()
        self.call("rename_feature", feature="Pad", name="Plate thickness")
        self.assertEqual(self.doc.Pad.Label, "Plate thickness")
        self.assertEqual(self.doc.Pad.Name, "Pad")
        self.rejected("dependent_features", "delete_feature", feature="Plate")
        self.call("create_sketch", id="FaceSketch", support={"feature":"Pad", "subelement":self.top_face()})
        self.rejected("dependent_features", "delete_feature", feature="Pad")
        self.call("delete_feature", feature="FaceSketch")
        self.assertEqual(self.doc.Body.Tip, self.doc.Pad)
        self.call("delete_feature", feature="Plate", cascade=True)
        self.assertIsNone(self.doc.getObject("Plate"))
        self.assertIsNone(self.doc.getObject("Pad"))
        self.call("undo")
        self.assertEqual(self.doc.Body.Tip, self.doc.Pad)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, 20*12*6, places=7)

    def test_body_part_label_rename_undo_preserves_native_id_and_blocks_delete(self):
        self.plate()
        initial = self.doc.Body.Label
        volume = self.doc.Body.Shape.Volume
        self.call("rename_feature", feature="Body", name="Part 1")
        self.assertEqual(self.doc.Body.Label, "Part 1")
        self.assertEqual(self.doc.Body.Name, "Body")
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, volume, places=7)
        self.call("undo")
        self.assertEqual(self.doc.Body.Label, initial)
        self.call("redo")
        self.assertEqual(self.doc.Body.Label, "Part 1")
        self.rejected("unsupported_feature", "delete_feature", feature="Body", cascade=True)
        self.assertIsNotNone(self.doc.getObject("Body"))
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, volume, places=7)

    def test_native_fillet_chamfer_deletion_dependencies_cascade_and_undo(self):
        self.plate()
        original = self.doc.Body.Shape.Volume
        self.doc.openTransaction("Native fillet and chamfer creation")
        fillet = self.doc.Body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (self.doc.Pad, ["Edge1"])
        fillet.Radius = 1
        self.doc.recompute()
        self.assertTrue(fillet.Shape.isValid())
        self.assertEqual(len(fillet.Shape.Solids), 1)
        original_edge_center = self.doc.Pad.Shape.Edges[0].CenterOfMass
        distant = max(((i,edge) for i,edge in enumerate(fillet.Shape.Edges) if isinstance(edge.Curve, Part.Line)),
                      key=lambda item:(item[1].CenterOfMass-original_edge_center).Length)
        chamfer = self.doc.Body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (fillet, ["Edge"+str(distant[0]+1)])
        chamfer.Size = .2
        self.doc.recompute()
        self.doc.commitTransaction()
        self.call("inspect")
        self.assertEqual(self.state["build_status"], "valid", self.state["build_errors"])
        self.assertEqual(self.doc.Body.Tip, chamfer)
        edited = self.doc.Body.Shape.Volume
        self.assertLess(edited, original)
        revision = self.state["revision"]
        self.rejected("dependent_features", "delete_feature", feature="Fillet")
        self.call("inspect")
        self.assertEqual(self.state["revision"], revision)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, edited, places=7)
        outside = self.doc.addObject("App::FeaturePython", "ExternalReference")
        outside.addProperty("App::PropertyLink", "ReferencedFeature")
        outside.ReferencedFeature = fillet
        self.doc.recompute()
        self.call("inspect")
        self.rejected("external_dependency", "delete_feature", feature="Fillet", cascade=True)
        self.assertIsNotNone(self.doc.getObject("Fillet"))
        self.assertIsNotNone(self.doc.getObject("Chamfer"))
        self.doc.removeObject(outside.Name)
        self.call("inspect")
        self.call("delete_feature", feature="Fillet", cascade=True)
        self.assertIsNone(self.doc.getObject("Fillet"))
        self.assertIsNone(self.doc.getObject("Chamfer"))
        self.assertEqual(self.doc.Body.Tip, self.doc.Pad)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, original, places=7)
        self.call("undo")
        self.assertEqual(self.doc.Body.Tip, self.doc.Chamfer)
        self.assertEqual(self.doc.Fillet.Base[0], self.doc.Pad)
        self.assertEqual(self.doc.Chamfer.Base[0], self.doc.Fillet)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, edited, places=7)
        self.call("redo")
        self.assertEqual(self.doc.Body.Tip, self.doc.Pad)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, original, places=7)

    def test_native_revolution_delete_keeps_profile_and_restores_tip_geometry_with_undo(self):
        self.call("sketch_rectangle", id="RevolveProfile", plane="XZ", x=2,y=0,width=3,height=6)
        self.doc.openTransaction("Native revolution creation")
        revolution = self.doc.Body.newObject("PartDesign::Revolution", "Revolution")
        revolution.Profile = self.doc.RevolveProfile
        revolution.ReferenceAxis = (self.doc.RevolveProfile, ["V_Axis"])
        revolution.Angle = 360
        self.doc.recompute()
        self.doc.commitTransaction()
        self.call("inspect")
        self.assertEqual(self.state["build_status"], "valid")
        expected = math.pi*(5**2-2**2)*6
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, expected, places=6)
        self.rejected("dependent_features", "delete_feature", feature="RevolveProfile")
        self.call("delete_feature", feature="Revolution")
        self.assertIsNone(self.doc.getObject("Revolution"))
        self.assertIsNone(self.doc.Body.Tip)
        self.assertIsNotNone(self.doc.getObject("RevolveProfile"))
        self.assertEqual(self.state["build_status"], "sketch_only")
        self.call("undo")
        self.assertEqual(self.doc.Body.Tip, self.doc.Revolution)
        self.assertEqual(self.doc.Revolution.Profile[0], self.doc.RevolveProfile)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, expected, places=6)
        self.call("redo")
        self.assertIsNone(self.doc.Body.Tip)

    def test_delete_rejects_script_owned_feature_and_its_cascade_dependency(self):
        self.plate()
        scripted = self.doc.Body.newObject("PartDesign::FeaturePython", "ScriptOwned")
        scripted.Shape = self.doc.Pad.Shape.copy()
        scripted.addProperty("App::PropertyLink", "Upstream")
        scripted.Upstream = self.doc.Pad
        self.doc.recompute()
        self.call("inspect")
        self.rejected("unsupported_feature", "delete_feature", feature="ScriptOwned")
        self.rejected("unsupported_dependency", "delete_feature", feature="Pad", cascade=True)
        self.assertIsNotNone(self.doc.getObject("Pad"))
        self.assertIsNotNone(self.doc.getObject("ScriptOwned"))

    def test_change_support_preserves_local_intent_draft_history_finish_and_reopen(self):
        self.plate()
        self.call("sketch_circle", id="Editable", support={"feature": "Pad", "subelement": self.top_face()}, x=2, y=3, diameter=4)
        self.call("set_expression", feature="Editable", parameter="Diameter", expression="Plate.Constraints.Height / 3")
        sketch = self.doc.Editable
        initial_support = sketch.AttachmentSupport
        initial_frame = tuple(sketch.Placement.Base) + tuple(sketch.Placement.Rotation.Q)
        local = (tuple(sketch.Geometry[0].Center), sketch.Geometry[0].Radius)
        constraints = [(c.Type, c.Name, c.Value, c.First, c.FirstPos) for c in sketch.Constraints]
        expressions = list(sketch.ExpressionEngine)
        undo_before = self.doc.UndoCount
        self.call("begin_sketch_edit", feature="Editable")
        self.call("set_sketch_support", sketch="Editable", plane="XZ")
        self.assertEqual(sketch.AttachmentSupport[0][0], self.doc.XZ_Plane)
        self.assertAlmostEqual(abs(sketch.Placement.Rotation.multVec(App.Vector(0, 0, 1)).y), 1)
        self.assertEqual((tuple(sketch.Geometry[0].Center), sketch.Geometry[0].Radius), local)
        self.assertEqual([(c.Type, c.Name, c.Value, c.First, c.FirstPos) for c in sketch.Constraints], constraints)
        self.assertEqual(list(sketch.ExpressionEngine), expressions)
        self.call("undo")
        self.assertEqual(sketch.AttachmentSupport, initial_support)
        self.assertEqual(tuple(sketch.Placement.Base) + tuple(sketch.Placement.Rotation.Q), initial_frame)
        self.call("redo")
        self.assertEqual(sketch.AttachmentSupport[0][0], self.doc.XZ_Plane)
        # Native resetEdit/Dimension can commit without ending the managed lease.
        self.doc.commitTransaction()
        side = "Face" + str(next(i + 1 for i, face in enumerate(self.doc.Pad.Shape.Faces)
                                 if abs(face.normalAt(0, 0).x) > .9))
        self.call("set_sketch_support", sketch="Editable", support={"feature": "Pad", "subelement": side})
        self.call("finish_sketch_edit")
        self.assertEqual(self.doc.UndoCount, undo_before + 1)
        self.assertAlmostEqual(abs(sketch.Placement.Rotation.multVec(App.Vector(0, 0, 1)).x), 1)
        final_frame = tuple(sketch.Placement.Base) + tuple(sketch.Placement.Rotation.Q)
        self.call("undo")
        self.assertEqual(sketch.AttachmentSupport, initial_support)
        self.call("redo")
        self.assertEqual(tuple(sketch.Placement.Base) + tuple(sketch.Placement.Rotation.Q), final_frame)
        path = self.folder / "changed-support.FCStd"
        self.call("save", path=str(path))
        App.closeDocument(self.doc.Name)
        self.call("open", path=str(path))
        self.assertEqual(self.doc.Editable.AttachmentSupport[0][0], self.doc.Pad)
        self.assertEqual(tuple(self.doc.Editable.Placement.Base) + tuple(self.doc.Editable.Placement.Rotation.Q), final_frame)
        self.assertEqual((tuple(self.doc.Editable.Geometry[0].Center), self.doc.Editable.Geometry[0].Radius), local)
        self.assertEqual(list(self.doc.Editable.ExpressionEngine), expressions)

    def test_change_support_cancel_and_invalid_targets_restore_accepted_sketch(self):
        self.plate()
        self.call("create_sketch", id="Editable")
        initial = self.doc.Editable.AttachmentSupport
        self.call("create_sketch", id="OtherSketch")
        self.call("add_line", sketch="OtherSketch", x1=0, y1=2, x2=5, y2=2)
        late = self.doc.Body.newObject("PartDesign::Plane", "LaterDatum")
        late.AttachmentSupport = (self.doc.XY_Plane, [""])
        late.MapMode = "FlatFace"
        self.doc.recompute()
        other = self.doc.addObject("PartDesign::Body", "OtherBody")
        foreign = other.newObject("PartDesign::Plane", "ForeignDatum")
        foreign.AttachmentSupport = (other.Origin.OriginFeatures[3], [""])
        foreign.MapMode = "FlatFace"
        self.doc.recompute()
        self.call("inspect")
        self.call("begin_sketch_edit", feature="Editable")
        for code, args in [
            ("invalid_argument", {}),
            ("invalid_argument", {"plane": "XY", "support": {"feature": "Pad", "subelement": self.top_face()}}),
            ("unsupported_plane", {"plane": "ZX"}),
            ("cyclic_reference", {"support": {"feature": "Editable"}}),
            ("future_reference", {"support": {"feature": "LaterDatum"}}),
            ("future_reference", {"support": {"feature": "ForeignDatum"}}),
            ("missing_reference", {"support": {"feature": "Absent"}}),
        ]:
            self.rejected(code, "set_sketch_support", sketch="Editable", **args)
            self.call("inspect")
            self.assertEqual(self.doc.Editable.AttachmentSupport, initial)
            self.assertIsNotNone(self.state["active_sketch_edit"])
        self.rejected("managed_sketch_mismatch", "set_sketch_support", sketch="OtherSketch", plane="XZ")
        self.rejected("future_reference", "project_geometry", sketch="Editable",
                      references=[{"feature": "OtherSketch", "subelement": "Edge1"}])
        self.call("inspect")
        self.assertEqual(self.doc.Editable.AttachmentSupport, initial)
        self.call("set_sketch_support", sketch="Editable", plane="YZ")
        self.doc.commitTransaction()
        self.call("finish_sketch_edit", cancel=True)
        self.assertEqual(self.doc.Editable.AttachmentSupport, initial)
        self.rejected("empty_history", "redo")
        self.assertEqual(self.doc.Editable.AttachmentSupport, initial)

    def test_replacing_selector_support_keeps_draft_binding_undo_and_redo_consistent(self):
        self.plate()
        self.call("create_sketch", id="Editable", support={"kind": "created_by", "feature": "Pad", "cap": "end"})
        self.assertIn("QueryInputs", self.doc.Editable.PropertiesList)
        initial = self.doc.Editable.AttachmentSupport
        self.call("begin_sketch_edit", feature="Editable")
        self.call("set_sketch_support", sketch="Editable", plane="XZ")
        self.assertNotIn("QueryInputs", self.doc.Editable.PropertiesList)
        self.call("undo")
        self.assertEqual(self.doc.Editable.AttachmentSupport, initial)
        self.assertIn("QueryInputs", self.doc.Editable.PropertiesList)
        self.call("redo")
        self.assertEqual(self.doc.Editable.AttachmentSupport[0][0], self.doc.XZ_Plane)
        self.assertNotIn("QueryInputs", self.doc.Editable.PropertiesList)
        self.call("set_sketch_support", sketch="Editable", support={"kind": "created_by", "feature": "Pad", "cap": "start"})
        self.assertIn("QueryInputs", self.doc.Editable.PropertiesList)
        self.call("finish_sketch_edit", cancel=True)
        self.assertEqual(self.doc.Editable.AttachmentSupport, initial)
        self.assertIn("QueryInputs", self.doc.Editable.PropertiesList)

    def test_multi_delete_selection_closure_is_atomic_and_one_undo_step(self):
        self.plate()
        self.call("sketch_circle", id="Hole", support={"feature": "Pad", "subelement": self.top_face()}, x=5, y=5, diameter=2)
        self.call("pocket", id="Pocket", profile="Hole")
        accepted = intent_signature(self.doc)
        volume = self.doc.Body.Shape.Volume
        count = self.doc.UndoCount
        chronology = [obj.Name for obj in studio.order(self.doc)]
        revision = self.state["revision"]
        plan = self.core.delete_features_plan(self.doc, ["Hole", "Plate"])
        self.assertEqual(plan, {"selected": ["Plate", "Hole"], "dependents": ["Pad", "Pocket"],
                                "removed": ["Plate", "Pad", "Hole", "Pocket"]})
        self.assertEqual(intent_signature(self.doc), accepted)
        self.assertEqual(self.doc.UndoCount, count)
        self.rejected("dependent_features", "delete_features", features=["Hole", "Plate"])
        self.rejected("missing_reference", "delete_features", features=["Pocket", "Absent"])
        self.rejected("invalid_argument", "delete_features", features=["Pocket", "Pocket"])
        self.call("inspect")
        self.assertEqual(intent_signature(self.doc), accepted)
        self.assertEqual(self.state["revision"], revision)
        self.assertEqual(self.doc.UndoCount, count)
        self.call("delete_features", features=["Pocket", "Hole"])
        self.assertIsNone(self.doc.getObject("Pocket"))
        self.assertIsNone(self.doc.getObject("Hole"))
        self.assertEqual(self.doc.Body.Tip, self.doc.Pad)
        self.assertEqual(self.doc.UndoCount, count + 1)
        self.call("undo")
        self.assertFalse(studio.enabled(self.doc))
        self.assertEqual([obj.Name for obj in studio.order(self.doc)], chronology)
        self.assertEqual(self.state["studio"]["feature_order"], chronology)
        self.assertEqual(self.doc.Pocket.Profile[0], self.doc.Hole)
        self.assertEqual(self.doc.Hole.AttachmentSupport[0][0], self.doc.Pad)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, volume)
        self.call("redo")
        self.assertIsNone(self.doc.getObject("Hole"))
        self.call("delete_features", features=["Plate"], cascade=True)
        self.assertIsNone(self.doc.getObject("Plate"))
        self.assertIsNone(self.doc.getObject("Pad"))
        self.assertIsNone(self.doc.Body.Tip)
        self.call("undo")
        self.assertEqual(self.doc.Pad.Profile[0], self.doc.Plate)

    def test_multi_delete_prevalidates_external_consumers_and_independent_bodies(self):
        self.plate()
        self.call("create_body", id="OtherBody")
        self.call("sketch_rectangle", id="OtherProfile", body="OtherBody", width=3, height=4)
        self.call("pad", id="OtherPad", profile="OtherProfile", body="OtherBody", length=5)
        external = self.doc.addObject("App::FeaturePython", "ExternalConsumer")
        external.addProperty("App::PropertyLink", "Source")
        external.Source = self.doc.Pad
        self.doc.recompute()
        self.call("inspect")
        accepted = intent_signature(self.doc)
        count = self.doc.UndoCount
        with self.assertRaises(OperationError) as caught:
            self.core.delete_features_plan(self.doc, ["OtherPad", "Pad"])
        self.assertEqual(caught.exception.code, "external_dependency")
        self.rejected("external_dependency", "delete_features", features=["OtherPad", "Pad"], cascade=True)
        self.assertEqual(intent_signature(self.doc), accepted)
        self.assertIsNotNone(self.doc.getObject("OtherPad"))
        self.assertEqual(self.doc.UndoCount, count)
        self.doc.removeObject(external.Name)
        self.call("inspect")
        self.call("delete_features", features=["OtherPad", "Pad"])
        self.assertIsNone(self.doc.Body.Tip)
        self.assertIsNone(self.doc.OtherBody.Tip)
        self.call("undo")
        self.assertEqual(self.doc.Body.Tip, self.doc.Pad)
        self.assertEqual(self.doc.OtherBody.Tip, self.doc.OtherPad)

    def test_direct_managed_attach_records_legacy_order_before_first_deletion(self):
        native = App.newDocument("NativeLegacyAttachment")
        body = native.addObject("PartDesign::Body", "Body")
        sketch = body.newObject("Sketcher::SketchObject", "Profile")
        corners = [(0, 0), (20, 0), (20, 12), (0, 12)]
        sketch.addGeometry([Part.LineSegment(App.Vector(*point, 0), App.Vector(*corners[(i + 1) % 4], 0))
                            for i, point in enumerate(corners)], False)
        pad = body.newObject("PartDesign::Pad", "Extrude")
        pad.Profile = sketch
        pad.Length = 6
        native.recompute()
        self.assertIsNone(native.getObject("KurtShapeProject"))
        self.core.attach(native, managed=True)
        self.state = self.core.inspect(native)
        self.assertIn("KurtShapeFeatureOrder", native.KurtShapeProject.PropertiesList)
        self.assertEqual(native.KurtShapeProject.getTypeIdOfProperty("KurtShapeFeatureOrder"), "App::PropertyLinkListGlobal")
        self.assertFalse(studio.enabled(native))
        self.assertEqual(self.state["studio"]["feature_order"], ["Profile", "Extrude"])
        self.call("delete_features", features=["Profile", "Extrude"])
        self.call("undo")
        self.assertEqual(self.state["studio"]["feature_order"], ["Profile", "Extrude"])
        self.assertEqual(native.Extrude.Profile[0], native.Profile)
        self.assertAlmostEqual(native.Body.Shape.Volume, 20 * 12 * 6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
