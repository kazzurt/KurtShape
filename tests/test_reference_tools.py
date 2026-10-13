"""Native geometry, history and rebuild tests for typed reference consumers."""
from pathlib import Path
import json
import subprocess
import sys
import unittest
import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
from kurtshape.core import Controller
from kurtshape import modeling_geometry, studio


class ReferenceToolTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="reference-tools-session-")
        self.core = Controller()
        self.state = self.call("new", name="Typed reference consumers")
        self.call("sketch_rectangle", id="Plate", width=20, height=12)
        self.call("pad", id="Pad", profile="Plate", length=6)

    def tearDown(self):
        self.core.observer.close()
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
        if "document_id" in response["result"]:
            self.state = response["result"]
        return response["result"]

    def top_face(self, obj):
        return "Face" + str(next(index + 1 for index, face in enumerate(obj.Shape.Faces)
                                   if isinstance(face.Surface, Part.Plane) and face.normalAt(0, 0).z > .999))

    def test_fillet_actual_solid_one_step_undo_redo(self):
        baseline = self.doc.Body.Shape.Volume
        undo_before = self.doc.UndoCount
        self.call("fillet", id="EdgeRound", part="Body", edges=[{"feature": "Pad", "subelement": "Edge1"}], radius="1 mm")
        self.assertEqual(self.doc.UndoCount, undo_before + 1)
        self.assertTrue(self.doc.Body.Shape.isValid())
        self.assertLess(self.doc.Body.Shape.Volume, baseline)
        filleted = self.doc.Body.Shape.Volume
        self.call("undo")
        self.assertIsNone(self.doc.getObject("EdgeRound"))
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, baseline, places=6)
        self.call("redo")
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, filleted, places=6)

    def test_chamfer_and_failed_fillet_preserve_current_result(self):
        self.call("chamfer", id="EdgeBreak", edges=[{"feature": "Pad", "subelement": "Edge1"}], size="0.5 mm")
        baseline, revision = self.doc.Body.Shape.Volume, self.state["revision"]
        response = self.request("fillet", id="ImpossibleRound", edges=[{"feature": "EdgeBreak", "subelement": "Edge1"}], radius=1000)
        self.assertFalse(response["ok"], response)
        self.assertIsNone(self.doc.getObject("ImpossibleRound"))
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, baseline, places=6)
        self.assertEqual(self.core.inspect(self.doc)["revision"], revision)

    def test_through_all_never_silently_builds_a_finite_legacy_pad(self):
        baseline = self.doc.Body.Shape.Volume
        revision, undo_count = self.state["revision"], self.doc.UndoCount
        response = self.request("pad", id="MisleadingThroughAll", profile="Plate", length=30,
                                end_type="through_all")
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], "invalid_argument")
        self.assertIsNone(self.doc.getObject("MisleadingThroughAll"))
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, baseline)
        self.assertEqual(self.doc.UndoCount, undo_count)
        self.assertEqual(self.core.inspect(self.doc)["revision"], revision)

    def test_shell_removes_face_and_tracks_upstream_depth(self):
        baseline = self.doc.Body.Shape.Volume
        self.call("shell", id="Hollow", faces=[{"feature": "Pad", "subelement": self.top_face(self.doc.Pad)}],
                  thickness=1, reversed=True)
        self.assertTrue(self.doc.Body.Shape.isValid())
        self.assertEqual(len(self.doc.Body.Shape.Solids), 1)
        self.assertLess(self.doc.Body.Shape.Volume, baseline)
        self.call("set_parameter", feature="Pad", parameter="Length", value=8)
        self.assertAlmostEqual(self.doc.Body.Shape.BoundBox.ZLength, 8, places=6)
        self.assertTrue(self.doc.Body.Shape.isValid())

    def test_projected_geometry_tracks_source_and_undo_restores_slot(self):
        self.call("create_sketch", id="UseSketch")
        edge_name = "Edge" + str(next(i + 1 for i, edge in enumerate(self.doc.Pad.Shape.Edges)
                                    if abs(edge.BoundBox.ZMin) < 1e-7 and abs(edge.BoundBox.ZLength) < 1e-7
                                    and edge.BoundBox.XLength > 19))
        self.call("project_geometry", sketch="UseSketch", references=[{"feature": "Pad", "subelement": edge_name}])
        self.assertEqual(len(self.doc.UseSketch.ExternalGeometry), 1)
        before = max(geometry.length() for geometry in self.doc.UseSketch.ExternalGeo if hasattr(geometry, "length"))
        self.call("set_parameter", feature="Plate", parameter="Width", value=25)
        after = max(geometry.length() for geometry in self.doc.UseSketch.ExternalGeo if hasattr(geometry, "length"))
        self.assertAlmostEqual(after - before, 5, places=6)
        self.call("undo")
        self.call("undo")
        self.assertEqual(len(self.doc.UseSketch.ExternalGeometry), 0)

    def test_up_to_face_native_end_updates_with_other_part(self):
        self.call("create_body", id="StopBody")
        self.call("sketch_rectangle", id="StopProfile", body="StopBody", width=5, height=5, x=50)
        self.call("pad", id="StopPad", profile="StopProfile", body="StopBody", length=10)
        self.call("sketch_circle", id="RaisedProfile", body="Body", support={"feature": "Pad", "subelement": self.top_face(self.doc.Pad)},
                  x=10, y=6, diameter=4)
        self.call("pad", id="ToFace", profile="RaisedProfile", body="Body", end_type="up_to_face",
                  up_to_face={"feature": "StopPad", "subelement": self.top_face(self.doc.StopPad)})
        self.assertAlmostEqual(self.doc.Body.Shape.BoundBox.ZMax, 10, places=6)
        self.call("set_parameter", feature="StopPad", parameter="Length", value=12)
        self.assertAlmostEqual(self.doc.Body.Shape.BoundBox.ZMax, 12, places=6)

    def test_typed_preview_is_disposable_and_stale_commit_rejects(self):
        names, volume, count, revision = set(App.listDocuments()), self.doc.Body.Shape.Volume, self.doc.UndoCount, self.state["revision"]
        preview = self.call("preview", proposal={"op": "fillet", "edges": [{"feature": "Pad", "subelement": "Edge1"}], "radius": 1})
        self.assertTrue(preview["valid"], preview)
        self.assertLess(preview["measurements"]["volume_mm3"], volume)
        self.assertEqual(set(App.listDocuments()), names)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, volume, places=6)
        self.assertEqual(self.doc.UndoCount, count)
        current = self.core.inspect(self.doc)
        self.assertEqual(current["revision"], revision)
        self.assertFalse(self.doc.HasPendingTransaction)
        self.assertFalse(self.core.busy)
        self.call("set_parameter", feature="Pad", parameter="Length", value=7)
        response = self.core.dispatch({"op": "fillet", "document_id": self.state["document_id"], "expected_revision": revision,
                                       "edges": [{"feature": "Pad", "subelement": "Edge1"}], "radius": 1})
        self.assertEqual(response["error"]["code"], "stale_revision")

    def test_face_extrusion_follows_native_face_and_history(self):
        baseline = self.doc.Body.Shape.Volume
        undo_before = self.doc.UndoCount
        self.call("extrude_face", id="FaceRaise", face={"feature": "Pad", "subelement": self.top_face(self.doc.Pad)}, length=2)
        body = studio.current_part(self.doc, "Body")
        self.assertTrue(body.Shape.isValid())
        self.assertAlmostEqual(body.Shape.Volume, 20 * 12 * 8)
        self.assertEqual(self.doc.UndoCount, undo_before + 1)
        self.call("undo")
        self.assertIsNone(self.doc.getObject("FaceRaise"))
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, baseline)
        self.call("redo")
        self.call("set_parameter", feature="Pad", parameter="Length", value=9)
        self.assertAlmostEqual(studio.current_part(self.doc, "Body").Shape.BoundBox.ZMax, 11)
        self.assertEqual(self.doc.FaceRaiseTool.Base.TypeId, "PartDesign::ShapeBinder")

    def test_offset_plane_is_selectable_native_support_and_mirror_input(self):
        self.call("create_plane", id="MirrorPlane", name="Right offset", base_plane="YZ", offset=30)
        plane = self.doc.MirrorPlane
        self.assertEqual(plane.TypeId, "PartDesign::Plane")
        self.assertEqual(self.doc.Body.Tip, self.doc.Pad)
        self.assertIn({"feature": "MirrorPlane"}, [row["reference"] for row in modeling_geometry.named_plane_candidates(self.doc)])
        self.call("create_sketch", id="PlaneSketch", support={"feature": "MirrorPlane"})
        self.assertAlmostEqual(self.doc.PlaneSketch.Placement.Base.x, 30)
        self.call("mirror_parts", id="SelectedMirror", parts=["Body"], plane={"feature": "MirrorPlane"})
        self.assertEqual(self.doc.SelectedMirror.MirrorPlane[0].AttachmentSupport[0][0], plane)
        mirrored = studio.current_part(self.doc, "SelectedMirrorPart")
        self.assertAlmostEqual(mirrored.Shape.BoundBox.XMin, 40)
        plane.Offset = 40
        self.doc.recompute()
        self.assertAlmostEqual(mirrored.Shape.BoundBox.XMin, 60)
        self.assertAlmostEqual(self.doc.PlaneSketch.Placement.Base.x, 40)

    def test_revolve_selected_profile_line_has_native_axis_link(self):
        self.call("sketch_rectangle", id="TurnProfile", x=10, y=0, width=5, height=10)
        profile = self.doc.TurnProfile
        edge = "Edge" + str(next(i + 1 for i, shape in enumerate(profile.Shape.Edges)
                                if shape.BoundBox.YLength > 9 and abs(shape.BoundBox.XMin - 10) < 1e-7))
        self.call("revolve", id="SelectedRevolve", profile="TurnProfile", axis={"feature": "TurnProfile", "subelement": edge})
        axis = self.doc.SelectedRevolve.AxisLink[0]
        self.assertEqual(axis.TypeId, "Part::Line")
        self.assertEqual(axis.KurtShapeAxisDatum.AttachmentSupport, [(profile, (edge.lower(),))])
        self.assertTrue(self.doc.SelectedRevolve.Shape.isValid())
        import math
        self.assertAlmostEqual(self.doc.SelectedRevolve.Shape.Volume, math.pi * 5 ** 2 * 10, places=6)
        self.call("set_parameter", feature="TurnProfile", parameter="Width", value=7)
        self.assertAlmostEqual(self.doc.SelectedRevolve.Shape.Volume, math.pi * 7 ** 2 * 10, places=6)

    def test_revolve_profile_construction_axis_updates_native_geometry(self):
        self.doc.Body.Placement = App.Placement(App.Vector(30, 40, 0), App.Rotation(App.Vector(0, 0, 1), 90))
        self.doc.recompute()
        self.call("inspect")
        self.call("sketch_rectangle", id="TurnProfile", x=10, y=0, width=5, height=10)
        self.call("add_line", sketch="TurnProfile", x1=0, y1=0, x2=0, y2=10, construction=True)
        self.call("revolve", id="ConstructionRevolve", profile="TurnProfile", axis={"feature": "TurnProfile", "subelement": "Edge5"})
        feature = self.doc.ConstructionRevolve
        self.assertEqual(feature.AxisLink[0].KurtShapeAxisDatum.AttachmentSupport, [(self.doc.TurnProfile, ("edge5",))])
        import math
        self.assertTrue(feature.Shape.isValid())
        self.assertAlmostEqual(feature.Shape.Volume, math.pi * (15 ** 2 - 10 ** 2) * 10, places=6)
        self.call("set_parameter", feature="TurnProfile", parameter="Width", value=7)
        self.assertAlmostEqual(feature.Shape.Volume, math.pi * (17 ** 2 - 10 ** 2) * 10, places=6)
        self.doc.Body.Placement = App.Placement(App.Vector(70, 80, 0), App.Rotation(App.Vector(0, 0, 1), 180))
        self.doc.recompute()
        self.call("inspect")
        self.doc.openTransaction("Edit native construction axis")
        sketch = self.doc.TurnProfile
        for index in reversed(range(sketch.ConstraintCount)):
            if sketch.Constraints[index].First == 4:
                sketch.delConstraint(index)
        sketch.solve()
        sketch.moveGeometry(4, 1, App.Vector(2, 0, 0), False)
        sketch.moveGeometry(4, 2, App.Vector(2, 10, 0), False)
        self.doc.recompute()
        self.doc.commitTransaction()
        self.call("inspect")
        self.call("rebuild")
        self.assertAlmostEqual(feature.Shape.Volume, math.pi * (15 ** 2 - 8 ** 2) * 10, places=6)
        self.assertAlmostEqual(feature.AxisLink[0].Placement.Base.x, 68)
        self.assertAlmostEqual(feature.AxisLink[0].Placement.Base.y, 80)
        self.assertAlmostEqual(feature.Shape.BoundBox.YMin, 70)
        self.assertAlmostEqual(feature.Shape.BoundBox.YMax, 80)
        destination = support.scratch(self, prefix="construction-axis-native-persistence-")
        path = destination / "construction-axis-revolve.FCStd"
        self.call("save", path=str(path))
        script = (
            "import sys,math,json;sys.path.insert(0," + repr(str(ROOT / "src")) + ");"
            "import FreeCAD as A;from kurtshape import studio;"
            "d=A.openDocument(" + repr(str(path)) + ");"
            "[o.touch() for o in d.Objects if o.TypeId.startswith(('Part::','PartDesign::','Sketcher::'))];"
            "studio.prepare_recompute(d);d.recompute();"
            "assert d.ConstructionRevolve.AxisLink[0].KurtShapeAxisDatum.AttachmentSupport==[(d.TurnProfile,('edge5',))];"
            "assert d.ConstructionRevolve.Shape.isValid();"
            "assert abs(d.ConstructionRevolve.Shape.Volume-math.pi*(15**2-8**2)*10)<1e-6;"
            "assert abs(d.ConstructionRevolve.AxisLink[0].Placement.Base.x-68)<1e-7;"
            "print(json.dumps({'fresh_process':True,'native_construction_axis':True}));"
            "A.closeDocument(d.Name)"
        )
        process = support.run_native_proof([sys.executable, "-B", "-c", script], capture_output=True, text=True,
                                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=30)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)

    def test_zero_revolve_axis_rejects_without_helpers_or_history_change(self):
        self.call("sketch_rectangle", id="TurnProfile", x=10, y=0, width=5, height=10)
        baseline = set(obj.Name for obj in self.doc.Objects), self.doc.UndoCount, self.state["revision"]
        response = self.request("revolve", id="InvalidAxis", profile="TurnProfile",
                                axis={"origin": [0, 0, 0], "direction": [0, 0, 0]})
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], "invalid_argument")
        self.assertEqual((set(obj.Name for obj in self.doc.Objects), self.doc.UndoCount,
                          self.core.inspect(self.doc)["revision"]), baseline)

    def test_saved_internal_revolve_axis_migrates_native_query_without_undo(self):
        from kurtshape import selectors
        self.call("sketch_rectangle", id="TurnProfile", x=10, y=0, width=5, height=10)
        query = {"kind": "closest", "point": [10, 5, 0],
                 "query": {"kind": "created_by", "feature": "TurnProfile", "entity_type": "edge"}}
        self.call("revolve", id="AddRevolve", profile="TurnProfile", axis=query,
                  operation="add", merge_scope=["Body"])
        tool = self.doc.AddRevolve.KurtShapeTool
        self.assertEqual(tool.KurtShapeOperationOwner, "AddRevolve")
        expected = studio.current_part(self.doc, "Body").Shape.Volume
        line, datum = tool.AxisLink[0], tool.AxisLink[0].KurtShapeAxisDatum
        self.doc.openTransaction("Legacy direct native axis fixture")
        selectors.bind(tool, "axis", query, native_property="AxisLink")
        self.doc.removeObject(line.Name)
        self.doc.removeObject(datum.Name)
        private = self.doc.AddRevolve.Group[0]
        private_name, base_name = private.Name, private.Tip.Name
        source_name = private.Tip.BaseFeature.Name
        private.BaseFeature = private.Tip.BaseFeature
        self.doc.commitTransaction()
        destination = support.scratch(self, prefix="legacy-axis-native-migration-")
        path = destination / "legacy-axis.FCStd"
        self.doc.saveAs(str(path))
        App.closeDocument(self.doc.Name)
        response = self.core.dispatch({"op": "open", "path": str(path)})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        tool = self.doc.AddRevolve.KurtShapeTool
        line, datum = tool.AxisLink[0], tool.AxisLink[0].KurtShapeAxisDatum
        self.assertEqual(line.TypeId, "Part::Line")
        self.assertFalse(line.Shape.isNull())
        self.assertFalse({"Touched", "Invalid", "Error"} & set(line.State))
        self.assertEqual(line.KurtShapeOperationOwner, "AddRevolve")
        self.assertEqual(datum.KurtShapeOperationOwner, "AddRevolve")
        self.assertNotIn("QueryInputs", tool.PropertiesList)
        self.assertEqual(json.loads(datum.QueryInputs)["axis"]["native_property"], "AttachmentSupport")
        private = self.doc.getObject(private_name)
        self.assertIsNone(private.BaseFeature)
        self.assertEqual(private.Tip.Name, base_name)
        self.assertEqual(private.Tip.BaseFeature.Name, source_name)
        self.assertEqual(self.doc.AddRevolve.Group[0], private)
        self.assertTrue(private.Shape.isValid())
        self.assertEqual(self.doc.UndoCount, 0)
        self.call("rebuild")
        self.assertEqual(tool.AxisLink[0], line)
        self.assertFalse(selectors.reference_errors(self.doc))
        self.assertAlmostEqual(studio.current_part(self.doc, "Body").Shape.Volume, expected)
        self.call("set_parameter", feature="TurnProfile", parameter="Width", value=7)
        self.assertGreater(studio.current_part(self.doc, "Body").Shape.Volume, expected)
        self.call("undo")
        self.assertEqual(tool.AxisLink[0], line)
        self.assertAlmostEqual(studio.current_part(self.doc, "Body").Shape.Volume, expected)

    def test_mirror_datum_tracks_owning_body_world_placement(self):
        self.doc.Body.Placement = App.Placement(App.Vector(30, 20, 10), App.Rotation())
        self.doc.recompute()
        self.call("inspect")
        self.call("create_plane", id="RightDatum", base_plane="YZ", offset=5)
        self.call("mirror_parts", id="PlacedMirror", parts=["Body"], plane={"feature": "RightDatum"})
        self.assertAlmostEqual(self.doc.PlacedMirror.MirrorPlane[0].Placement.Base.x, 35)
        self.assertAlmostEqual(studio.current_part(self.doc, "PlacedMirrorPart").Shape.BoundBox.XMin, 20)
        self.call("set_parameter", feature="RightDatum", parameter="Offset", value=8)
        self.assertAlmostEqual(self.doc.PlacedMirror.MirrorPlane[0].Placement.Base.x, 38)
        self.assertAlmostEqual(studio.current_part(self.doc, "PlacedMirrorPart").Shape.BoundBox.XMin, 26)

    def test_move_face_rejects_tapered_wall_without_changing_part(self):
        body = self.doc.addObject("PartDesign::Body", "TaperBody")
        feature = body.newObject("PartDesign::Feature", "TaperedSolid")
        feature.Shape = Part.makeCone(10, 6, 8)
        self.doc.recompute()
        self.call("inspect")
        top = self.top_face(feature)
        baseline, revision, undo = body.Shape.Volume, self.state["revision"], self.doc.UndoCount
        response = self.request("move_face", id="RejectedTaper", part="TaperBody", faces=[{"feature": "TaperedSolid", "subelement": top}], distance=2)
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], "unsupported_face_move")
        self.assertIsNone(self.doc.getObject("RejectedTaper"))
        self.assertAlmostEqual(body.Shape.Volume, baseline)
        self.assertEqual(self.doc.UndoCount, undo)
        self.assertEqual(self.core.inspect(self.doc)["revision"], revision)

    def test_planar_move_face_offsets_outward_and_inward(self):
        self.call("move_face", id="RaiseFace", part="Body", faces=[{"feature": "Pad", "subelement": self.top_face(self.doc.Pad)}], distance=2)
        body = studio.current_part(self.doc, "Body")
        self.assertTrue(body.Shape.isValid())
        self.assertAlmostEqual(body.Shape.Volume, 20 * 12 * 8)
        self.call("move_face", id="LowerFace", part="Body", faces=[{"feature": body.Tip.Name, "subelement": self.top_face(body.Tip)}], distance=-1)
        body = studio.current_part(self.doc, "Body")
        self.assertTrue(body.Shape.isValid())
        self.assertAlmostEqual(body.Shape.Volume, 20 * 12 * 7)
        self.call("set_parameter", feature="Pad", parameter="Length", value=9)
        self.assertAlmostEqual(studio.current_part(self.doc, "Body").Shape.BoundBox.ZMax, 10)

    def test_invalid_face_tools_abort_without_creating_geometry(self):
        self.call("sketch_circle", id="RoundProfile", diameter=8, x=30, y=0)
        self.call("pad", id="RoundPart", profile="RoundProfile", operation="new", length=6)
        curved = "Face" + str(next(i + 1 for i, face in enumerate(self.doc.RoundPart.Shape.Faces)
                                  if not isinstance(face.Surface, Part.Plane)))
        baseline, revision, undo = self.doc.Body.Shape.Volume, self.state["revision"], self.doc.UndoCount
        response = self.request("extrude_face", id="RejectedFace", face={"feature": "RoundPart", "subelement": curved}, length=2)
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], "nonplanar_support")
        self.assertIsNone(self.doc.getObject("RejectedFace"))
        self.assertEqual(self.doc.UndoCount, undo)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, baseline)
        self.assertEqual(self.core.inspect(self.doc)["revision"], revision)


if __name__ == "__main__":
    unittest.main()
