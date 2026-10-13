"""Controller and native consumers share persisted selector-backed references."""
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
import support
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
from kurtshape.core import Controller
from kurtshape import selectors, studio


class SelectorConsumerTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="selector-consumers-session-")
        self.core = Controller()
        self.state = self.call("new", name="Selector consumer acceptance")
        self.call("sketch_rectangle", id="Plate", width=20, height=12)
        self.call("pad", id="Pad", profile="Plate", length=6)

    def tearDown(self):
        self.core.close()
        for name in set(App.listDocuments()) - self.names:
            App.closeDocument(name)

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def call(self, op, **args):
        request = {"op": op, **args}
        if op not in {"new", "open"}:
            request.update(document_id=self.state["document_id"], expected_revision=self.state["revision"])
        response = self.core.dispatch(request)
        self.assertTrue(response["ok"], response)
        if "document_id" in response["result"]:
            self.state = response["result"]
        return response["result"]

    def cap(self, feature="Pad", side="end"):
        return {"kind": "created_by", "feature": feature, "cap": side}

    def edge(self, feature="Pad", point=(0, 0, 3)):
        return {"kind": "closest", "point": list(point),
                "query": {"kind": "geometry", "geometry": "line",
                          "query": {"kind": "created_by", "feature": feature, "entity_type": "edge"}}}

    def assert_healthy(self, feature):
        self.assertTrue(json.loads(feature.QueryInputs))
        self.assertTrue(all(entry["status"] == "healthy" for entry in json.loads(feature.QueryHealth)))
        self.assertFalse(selectors.reference_errors(self.doc))

    def test_support_follows_actual_face_rename_and_relocation(self):
        self.call("create_sketch", id="Supported", support=self.cap())
        before = self.doc.Supported.AttachmentSupport[0][1][0]
        self.call("add_circle", sketch="Plate", x=10, y=6, diameter=2)
        after = self.doc.Supported.AttachmentSupport[0][1][0]
        self.assertNotEqual(before, after)
        self.assertTrue(json.loads(self.doc.Supported.QueryResolutionLog))
        self.assert_healthy(self.doc.Supported)
        self.call("undo")
        self.assertEqual(self.doc.Supported.AttachmentSupport[0][1][0], before)
        self.call("redo")
        self.assertEqual(self.doc.Supported.AttachmentSupport[0][1][0], after)
        with tempfile.TemporaryDirectory(prefix="selector-reference-relocation-", dir=support.TEST_TMP, ignore_cleanup_errors=True) as temporary:
            path = Path(temporary) / "selector-backed-part.FCStd"
            self.call("save", path=str(path))
            App.closeDocument(self.doc.Name)
            self.call("open", path=str(path))
            self.assert_healthy(self.doc.Supported)
            self.assertEqual(self.doc.Supported.AttachmentSupport[0][1][0], after)

    def test_fillet_selector_rebuild_after_upstream_topology_edit(self):
        before = self.doc.UndoCount
        self.call("fillet", id="Round", edges=[self.edge()], radius=1)
        self.assertEqual(self.doc.UndoCount, before + 1)
        self.call("add_circle", sketch="Plate", x=10, y=6, diameter=2)
        self.assertTrue(self.doc.Body.Shape.isValid())
        self.assert_healthy(self.doc.Round)
        self.call("undo")
        self.assert_healthy(self.doc.Round)
        self.call("undo")
        self.assertIsNone(self.doc.getObject("Round"))
        self.call("redo")
        self.assert_healthy(self.doc.Round)

    def test_chamfer_and_shell_selector_native_consumers(self):
        self.call("chamfer", id="Chamfer", edges=[self.edge()], size=.5)
        self.assert_healthy(self.doc.Chamfer)
        self.call("undo")
        self.call("shell", id="Hollow", faces=[self.cap()], thickness=1, reversed=True)
        self.assert_healthy(self.doc.Hollow)
        self.call("set_parameter", feature="Pad", parameter="Length", value=8)
        self.assertAlmostEqual(self.doc.Body.Shape.BoundBox.ZLength, 8)
        self.assert_healthy(self.doc.Hollow)

    def test_up_to_face_selector_tracks_stop_part(self):
        self.call("create_body", id="StopBody")
        self.call("sketch_rectangle", id="StopProfile", body="StopBody", width=5, height=5, x=50)
        self.call("pad", id="StopPad", profile="StopProfile", body="StopBody", length=10)
        self.call("sketch_circle", id="Raised", body="Body", support=self.cap(), x=10, y=6, diameter=4)
        self.call("pad", id="ToFace", profile="Raised", body="Body", end_type="up_to_face", up_to_face=self.cap("StopPad"))
        self.assert_healthy(self.doc.ToFace)
        self.call("set_parameter", feature="StopPad", parameter="Length", value=12)
        self.assertAlmostEqual(self.doc.Body.Shape.BoundBox.ZMax, 12)
        self.assert_healthy(self.doc.ToFace)

    def test_pierce_selector_intersection_retains_intent_and_undo(self):
        self.call("create_sketch", id="Crossing", plane="XZ")
        self.call("add_line", sketch="Crossing", x1=2, y1=-5, x2=2, y2=5)
        self.call("create_sketch", id="Target")
        self.doc.Target.addGeometry(Part.Point(App.Vector(4, 0, 0)))
        self.doc.recompute()
        self.doc.commitTransaction()
        self.call("inspect")
        self.call("begin_sketch_edit", feature="Target")
        self.call("pierce", sketch="Target", geometry=0, point=1,
                  target={"kind": "closest", "point": [2, 0, 0],
                          "query": {"kind": "created_by", "feature": "Crossing", "entity_type": "edge"}})
        self.call("finish_sketch_edit")
        self.assertAlmostEqual(self.doc.Target.Geometry[0].X, 2)
        self.assert_healthy(self.doc.Target)
        self.call("set_parameter", feature="Crossing", parameter="StartX", value=3)
        self.call("set_parameter", feature="Crossing", parameter="EndX", value=3)
        self.assertAlmostEqual(self.doc.Target.Geometry[0].X, 3)
        self.assert_healthy(self.doc.Target)
        self.call("undo"); self.call("undo"); self.call("undo")
        self.assertEqual(len(self.doc.Target.ExternalGeometry), 0)

    def test_projected_use_selector_tracks_geometry_and_undo(self):
        self.call("create_sketch", id="UseSketch")
        self.call("project_geometry", sketch="UseSketch", references=[self.edge(point=(10, 0, 0))])
        self.assert_healthy(self.doc.UseSketch)
        baseline = max(geometry.length() for geometry in self.doc.UseSketch.ExternalGeo if hasattr(geometry, "length"))
        self.call("set_parameter", feature="Plate", parameter="Width", value=25)
        current = max(geometry.length() for geometry in self.doc.UseSketch.ExternalGeo if hasattr(geometry, "length"))
        self.assertAlmostEqual(current - baseline, 5)
        self.assert_healthy(self.doc.UseSketch)
        self.call("undo"); self.call("undo")
        self.assertEqual(len(self.doc.UseSketch.ExternalGeometry), 0)

    def test_owned_selector_rebinds_after_inserting_native_generation(self):
        self.call("transform_part", id="Copy", part="Body", translation=[30, 0, 0], copy=True)
        support = {"kind": "closest", "point": [10, 6, 6],
                   "query": {"kind": "parallel", "direction": [0, 0, 1],
                             "query": {"kind": "geometry", "geometry": "plane",
                                       "query": {"kind": "owned_by", "part": "Body"}}}}
        self.call("create_sketch", id="Supported", body="Body", support=support)
        original = self.doc.Supported.AttachmentSupport[0][0]
        boundary = self.state["studio"]["feature_order"].index("Supported")
        self.call("rollback", index=boundary)
        self.call("sketch_circle", id="InsertedHole", body="Body", x=10, y=6, diameter=2)
        self.call("pocket", id="InsertedPocket", profile="InsertedHole", operation="remove",
                  through_all=True, merge_scope=["Body"])
        self.call("rollback", index=len(self.state["studio"]["feature_order"]))
        current = self.doc.Supported.AttachmentSupport[0][0]
        self.assertNotEqual(original, current)
        self.assertIn(current, studio.results(self.doc, before=self.doc.Supported))
        self.assert_healthy(self.doc.Supported)
        self.call("set_parameter", feature="Pad", parameter="Length", value=8)
        self.assertAlmostEqual(self.doc.Supported.Placement.Base.z, 8)
        self.assert_healthy(self.doc.Supported)

    def test_whole_part_generated_instances_keep_creator_identity(self):
        self.call("transform_part", id="Copy", part="Body", translation=[30, 0, 0], copy=True)
        self.assertEqual(len(selectors.resolve(self.doc, {"kind": "created_by", "feature": "Copy"})), 6)
        self.call("transform_part", id="Move", part="CopyPart", translation=[0, 30, 0])
        self.assertEqual(len(selectors.resolve(self.doc, {"kind": "created_by", "feature": "Move"})), 0)
        self.assertEqual(len(selectors.resolve(self.doc, {"kind": "created_by", "feature": "Copy"})), 6)
        self.call("linear_pattern_parts", id="Linear", parts=["Body"], direction=[0, 1, 0], spacing=30, count=3)
        self.assertEqual(len(selectors.resolve(self.doc, {"kind": "created_by", "feature": "Linear"})), 12)
        self.call("circular_pattern_parts", id="Circular", parts=["Body"], angle="180 deg", count=2)
        self.assertEqual(len(selectors.resolve(self.doc, {"kind": "created_by", "feature": "Circular"})), 6)
        self.call("mirror_parts", id="Mirror", parts=["Body"], origin=[0, 0, 0], normal=[1, 0, 0])
        self.assertEqual(len(selectors.resolve(self.doc, {"kind": "created_by", "feature": "Mirror"})), 6)
        self.assertEqual(len(selectors.resolve(self.doc, {"kind": "created_by", "feature": "Pad"})), 36)
        destination = support.scratch(self, prefix="whole-part-creator-lineage-")
        path = destination / "whole-part-creator-lineage.FCStd"
        self.call("save", path=str(path))
        script = (
            "import sys,json;sys.path.insert(0," + repr(str(ROOT / "src")) + ");"
            "import FreeCAD as A;from kurtshape import selectors,studio;"
            "d=A.openDocument(" + repr(str(path)) + ");d.UseHasher=False;"
            "[o.touch() for o in d.Objects if o.TypeId.startswith(('Part::','PartDesign::','Sketcher::','App::Link'))];"
            "studio.prepare_recompute(d);d.recompute();"
            "expected={'Copy':6,'Move':0,'Linear':12,'Circular':6,'Mirror':6,'Pad':36};"
            "actual={name:len(selectors.resolve(d,{'kind':'created_by','feature':name})) for name in expected};"
            "assert actual==expected,(actual,expected);"
            "print(json.dumps({'freecad':A.Version(),'fresh_process':True,'forced_recompute':True,'creator_face_counts':actual}));"
            "A.closeDocument(d.Name)"
        )
        process = support.run_native_proof([sys.executable, "-B", "-c", script], capture_output=True, text=True,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=30)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        report = json.loads(process.stdout.strip().splitlines()[-1])
        report["recipe"] = "tests.test_selector_consumers.SelectorConsumerTests.test_whole_part_generated_instances_keep_creator_identity"
        (support.evidence_dir("u2-selector-consumers") / "fresh-native-creator-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    def test_pattern_add_preserves_source_and_generated_merge_creators(self):
        self.call("linear_pattern_parts", id="AddedPattern", parts=["Body"], direction=[1, 0, 0],
                  spacing=20, count=2, operation="add", merge_scope=["Body"])
        generated = selectors.resolve(self.doc, {"kind": "created_by", "feature": "AddedPattern"})
        original = selectors.resolve(self.doc, {"kind": "created_by", "feature": "Pad"})
        self.assertEqual(len(generated), 5)
        self.assertEqual(len(original), 6)
        self.assertTrue(all(row["summary"]["center_mm"][0] > 0 for row in generated))

    def test_native_input_divergence_blocks_export_until_managed_rebuild(self):
        self.call("create_sketch", id="Supported", support=self.cap())
        expected = self.doc.Supported.AttachmentSupport[0][1][0]
        self.doc.openTransaction("Native support cache edit")
        self.doc.Supported.AttachmentSupport = (self.doc.Pad, ["Face5"])
        with patch.object(selectors, "recompute", side_effect=AssertionError("Observer must not start a nested rebuild")):
            self.doc.recompute()
        self.doc.commitTransaction()
        self.call("inspect")
        self.assertEqual(self.state["build_status"], "failed")
        self.assertEqual(json.loads(self.doc.Supported.QueryHealth)[0]["status"], "missing")
        self.assertEqual(self.doc.Supported.AttachmentSupport[0][1][0], "Face5")
        with tempfile.TemporaryDirectory(prefix="native-input-divergence-", dir=support.TEST_TMP, ignore_cleanup_errors=True) as temporary:
            path = Path(temporary) / "incorrect-support.step"
            response = self.core.dispatch({"op": "export", "document_id": self.state["document_id"],
                                           "expected_revision": self.state["revision"], "path": str(path)})
            self.assertFalse(response["ok"], response)
            self.assertEqual(response["error"]["code"], "build_failed")
            self.assertFalse(path.exists())
        self.call("rebuild")
        self.assertEqual(self.doc.Supported.AttachmentSupport[0][1][0], expected)
        self.assertAlmostEqual(self.doc.Supported.Placement.Base.z, 6)
        self.assert_healthy(self.doc.Supported)

    def test_face_extrusion_selector_rebinds_after_cap_renumbering(self):
        self.call("extrude_face", id="SelectedRaise", face=self.cap(), length=2)
        binder = self.doc.SelectedRaiseTool.Base
        before = binder.Support[0][1][0]
        self.call("add_circle", sketch="Plate", x=10, y=6, diameter=2)
        after = binder.Support[0][1][0]
        self.assertNotEqual(before, after)
        self.assert_healthy(binder)
        self.assertTrue(studio.current_part(self.doc, "Body").Shape.isValid())
        self.assertAlmostEqual(studio.current_part(self.doc, "Body").Shape.BoundBox.ZMax, 8)
        self.call("set_parameter", feature="Pad", parameter="Length", value=9)
        self.assertAlmostEqual(studio.current_part(self.doc, "Body").Shape.BoundBox.ZMax, 11)

    def test_plane_and_mirror_selectors_keep_native_links_after_reopen(self):
        self.call("create_plane", id="TopDatum", support=self.cap(), offset=3)
        self.assert_healthy(self.doc.TopDatum)
        self.call("mirror_parts", id="PlaneMirror", parts=["Body"], plane={"feature": "TopDatum"})
        self.call("set_parameter", feature="Pad", parameter="Length", value=8)
        self.assertAlmostEqual(self.doc.TopDatum.Placement.Base.z, 11)
        self.assertAlmostEqual(studio.current_part(self.doc, "PlaneMirrorPart").Shape.BoundBox.ZMin, 14)
        destination = support.scratch(self, prefix="selected-plane-face-native-persistence-")
        path = destination / "selected-plane-mirror.FCStd"
        self.call("save", path=str(path))
        App.closeDocument(self.doc.Name)
        self.call("open", path=str(path))
        self.call("rebuild")
        self.assert_healthy(self.doc.TopDatum)
        self.assertEqual(self.doc.PlaneMirror.MirrorPlane[0].AttachmentSupport[0][0], self.doc.TopDatum)
        self.assertAlmostEqual(studio.current_part(self.doc, "PlaneMirrorPart").Shape.BoundBox.ZMin, 14)
        script = (
            "import sys,json;sys.path.insert(0," + repr(str(ROOT / "src")) + ");"
            "import FreeCAD as A;from kurtshape import studio;"
            "d=A.openDocument(" + repr(str(path)) + ");"
            "[o.touch() for o in d.Objects if o.TypeId.startswith(('Part::','PartDesign::','Sketcher::'))];"
            "studio.prepare_recompute(d);d.recompute();"
            "assert d.PlaneMirror.MirrorPlane[0].AttachmentSupport[0][0]==d.TopDatum;"
            "p=studio.current_part(d,'PlaneMirrorPart');"
            "assert p.Shape.isValid() and abs(p.Shape.BoundBox.ZMin-14)<1e-7;"
            "d.Pad.Length=10;d.recompute();"
            "assert abs(d.TopDatum.Placement.Base.z-13)<1e-7;"
            "assert abs(p.Shape.BoundBox.ZMin-16)<1e-7;"
            "print(json.dumps({'fresh_process':True,'forced_recompute':True,'native_plane_link':True}));"
            "A.closeDocument(d.Name)"
        )
        process = support.run_native_proof([sys.executable, "-B", "-c", script], capture_output=True, text=True,
                                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=30)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)


if __name__ == "__main__":
    unittest.main()
