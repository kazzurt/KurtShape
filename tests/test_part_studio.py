"""Native U2 studio fixtures: scope, parts, history and persistent dependencies."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
from kurtshape.core import Controller
from kurtshape import studio


class PartStudioTests(unittest.TestCase):
    def setUp(self):
        self.initial = set(App.listDocuments())
        self.core = Controller()
        self.state = self.core.dispatch({"op": "new", "name": "Studio fixture"})["result"]

    def tearDown(self):
        for name in set(App.listDocuments()) - self.initial:
            App.closeDocument(name)
        self.core.observer.close()

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def request(self, op, **kwargs):
        return self.core.dispatch({"op": op, "document_id": self.state["document_id"],
                                   "expected_revision": self.state["revision"], **kwargs})

    def call(self, op, **kwargs):
        response = self.request(op, **kwargs)
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        return self.state

    def part(self, name="Body", x=0, width=10, height=10, depth=10):
        if name != "Body":
            self.call("create_body", id=name, name=name)
        self.call("sketch_rectangle", id=name + "Profile", body=name, x=x, width=width, height=height)
        self.call("pad", id=name + "Extrude", profile=name + "Profile", body=name,
                  length=depth, operation="new")
        return name

    def volumes(self):
        return {studio.part_id(obj): obj.Shape.Volume for obj in studio.current_parts(self.doc)}

    def assert_volumes(self, expected):
        actual = self.volumes()
        self.assertEqual(set(actual), set(expected))
        for key, volume in expected.items():
            self.assertAlmostEqual(actual[key], volume)

    def fresh(self):
        self.state = self.core.dispatch({"op": "inspect", "document_id": self.state["document_id"]})["result"]

    def test_new_parts_and_explicit_add_scope(self):
        self.part()
        self.part("Second", x=20)
        self.call("sketch_rectangle", id="AddProfile", body="Body", x=8, width=5, height=10)
        undo_count = len(self.doc.UndoNames)
        self.call("pad", id="ScopedAdd", profile="AddProfile", length=10,
                  operation="add", merge_scope=["Body"])
        self.assertEqual(len(self.doc.UndoNames), undo_count + 1)
        self.assertEqual(self.doc.ScopedAdd.TypeId, "PartDesign::Boolean")
        self.assertAlmostEqual(self.volumes()["Body"], 1300)
        self.assertAlmostEqual(self.volumes()["Second"], 1000)
        self.call("undo")
        self.assertAlmostEqual(self.volumes()["Body"], 1000)
        self.call("redo")
        self.assertAlmostEqual(self.volumes()["Body"], 1300)

    def test_remove_through_two_parts_and_intersect(self):
        self.part()
        self.part("Second", x=20)
        self.call("sketch_rectangle", id="CutProfile", body="Body", x=4, y=4, width=22, height=2)
        self.call("pocket", id="ThroughBoth", profile="CutProfile", operation="remove",
                  through_all=True, merge_scope="auto")
        self.assertAlmostEqual(self.volumes()["Body"], 880)
        self.assertAlmostEqual(self.volumes()["Second"], 880)
        self.call("set_parameter", feature="BodyExtrude", parameter="Length", value=20)
        self.assertAlmostEqual(self.volumes()["Body"], 1760)
        self.call("sketch_rectangle", id="IntersectProfile", body="Body", x=0, width=5, height=10)
        self.call("pad", id="Intersection", profile="IntersectProfile", length=20,
                  operation="intersect", merge_scope=["Body"])
        self.assertAlmostEqual(self.volumes()["Body"], 960)
        self.assertAlmostEqual(self.volumes()["Second"], 880)

    def test_boolean_subtract_keeps_tool_and_targets(self):
        self.part(width=10)
        self.part("Second", x=20)
        self.part("Tool", x=4, width=22, height=2)
        self.call("boolean_parts", id="Subtract", targets=["Body", "Second"], tools=["Tool"],
                  kind="subtract", keep_tools=True)
        self.assertEqual(set(self.volumes()), {"Body", "Second", "Tool"})
        self.assertAlmostEqual(self.volumes()["Body"], 880)
        self.assertAlmostEqual(self.volumes()["Second"], 880)

    def test_split_fillets_and_query_result_before_consumer(self):
        self.part()
        self.call("split_part", id="Split", part="Body", plane={"origin": [5, 0, 0], "normal": [1, 0, 0]})
        halves = self.state["studio"]["parts"]
        self.assertEqual(len(halves), 2)
        for i, item in enumerate(halves):
            body = studio.current_part(self.doc, item["id"])
            previous = body.Tip
            self.call("fillet", id="HalfFillet" + str(i), part=item["id"],
                      edges=[{"feature": previous.Name, "subelement": "Edge1"}], radius=.5)
            prior_results = studio.results(self.doc, before="HalfFillet" + str(i))
            self.assertNotIn(self.doc.getObject("HalfFillet" + str(i)), prior_results)
        self.call("set_parameter", feature="BodyExtrude", parameter="Length", value=12)
        self.assertEqual(len(self.volumes()), 2)
        self.assertTrue(all(value > 590 for value in self.volumes().values()))

    def test_native_sketch_split_attachment_reopen_and_relocation(self):
        self.part()
        self.call("sketch_circle", id="CuttingSketch", body="Body", x=0, y=0, diameter=2)
        self.doc.CuttingSketch.MapMode = "Deactivated"
        self.doc.CuttingSketch.Placement = App.Placement(App.Vector(5, 0, 0), App.Rotation(App.Vector(0, 1, 0), 90))
        self.doc.recompute()
        self.fresh()
        self.call("split_part", id="AttachedSplit", part="Body", sketch="CuttingSketch")
        self.assertAlmostEqual(self.volumes()["Body"], 500)
        self.doc.CuttingSketch.Placement.Base = App.Vector(7, 0, 0)
        self.doc.recompute()
        self.fresh()
        self.call("rebuild")
        self.assertAlmostEqual(self.volumes()["Body"], 700)
        self.assertFalse(any("Proxy" in prop for prop in self.doc.AttachedSplitHalfspace.PropertiesList))
        with tempfile.TemporaryDirectory(prefix="studio-relocation-", dir=ROOT / "validation") as temporary:
            source = Path(temporary) / "original.FCStd"
            relocated = Path(temporary) / "relocated.FCStd"
            self.call("save", path=str(source))
            shutil.copy2(source, relocated)
            App.closeDocument(self.doc.Name)
            reopened = self.core.dispatch({"op": "open", "path": str(relocated)})
            self.assertTrue(reopened["ok"], reopened)
            self.state = reopened["result"]
            self.assertAlmostEqual(self.volumes()["Body"], 700)
            self.doc.CuttingSketch.Placement.Base = App.Vector(6, 0, 0)
            self.doc.recompute()
            self.fresh()
            self.call("rebuild")
            self.assertAlmostEqual(self.volumes()["Body"], 600)
            # Verify the stored native extension in another runtime process.
            self.call("save", path=str(relocated))
            script = "import FreeCAD as A; d=A.openDocument(" + repr(str(relocated)) + "); d.CuttingSketch.Placement.Base=A.Vector(8,0,0); d.recompute(); assert abs(d.AttachedSplitNegativePart.Shape.Volume-800)<1e-5"
            proc = subprocess.run([sys.executable, "-B", "-c", script], capture_output=True, text=True,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_transform_patterns_mirror_and_delete_undo(self):
        self.part(x=2, width=4, height=3, depth=2)
        self.call("transform_part", id="Copy", part="Body", translation=[20, 0, 0], copy=True)
        self.assertEqual(self.doc.Copy.TypeId, "Part::Compound")
        copy = studio.current_part(self.doc, "CopyPart")
        self.assertAlmostEqual(copy.Shape.BoundBox.XMin, 22)
        self.call("linear_pattern_parts", id="Linear", parts=["Body"], direction=[0, 1, 0], spacing=10, count=3)
        self.call("circular_pattern_parts", id="Circular", parts=["Body"],
                  axis={"origin": [1, 0, 0], "direction": [0, 0, 1]}, angle="180 deg", count=2)
        self.call("mirror_parts", id="Mirror", parts=["Body"], origin=[0, 0, 0], normal=[1, 0, 0])
        self.assertEqual(len(self.volumes()), 6)
        self.assertAlmostEqual(studio.current_part(self.doc, "MirrorPart").Shape.BoundBox.XMin, -6)
        self.assertAlmostEqual(studio.current_part(self.doc, "CircularPart").Shape.BoundBox.XMin, -4)
        self.call("delete_part", id="Delete", part="CopyPart")
        self.assertEqual(len(self.volumes()), 5)
        self.call("undo")
        self.assertEqual(len(self.volumes()), 6)
        self.call("redo")
        self.assertEqual(len(self.volumes()), 5)

    def test_part_pattern_add_and_remove_scopes(self):
        self.part()
        self.call("linear_pattern_parts", id="PatternAdd", parts=["Body"], direction=[1, 0, 0],
                  spacing=10, count=2, operation="add", merge_scope=["Body"])
        self.assertEqual(set(self.volumes()), {"Body"})
        self.assertAlmostEqual(self.volumes()["Body"], 2000)
        self.part("Tool", x=-4, width=4, height=2)
        self.call("linear_pattern_parts", id="PatternRemove", parts=["Tool"], direction=[1, 0, 0],
                  spacing=5, count=2, operation="remove", merge_scope=["Body"])
        self.assertAlmostEqual(self.volumes()["Body"], 1920)
        self.assertIn("Tool", self.volumes())

    def test_rollback_insert_rewires_later_stable_part_inputs(self):
        self.part()
        self.call("transform_part", id="LaterCopy", part="Body", translation=[30, 0, 0], copy=True)
        before_copy = self.state["studio"]["feature_order"].index("LaterCopy")
        self.call("rollback", index=before_copy)
        self.call("sketch_rectangle", id="InsertedProfile", body="Body", x=8, width=5, height=10)
        self.call("pad", id="InsertedAdd", profile="InsertedProfile", length=10, operation="add", merge_scope=["Body"])
        self.assertAlmostEqual(self.volumes()["Body"], 1300)
        self.call("rollback", index=len(self.state["studio"]["feature_order"]))
        self.assertAlmostEqual(self.volumes()["LaterCopyPart"], 1300)
        self.call("rollback", index=0)
        self.assertEqual(self.volumes(), {})
        self.assertIsNone(self.doc.Body.Tip)
        self.call("rollback", index=len(self.state["studio"]["feature_order"]))
        self.assertEqual(len(self.volumes()), 2)

    def test_rejected_scope_and_transform_are_one_transaction_rollbacks(self):
        self.part()
        count = len(self.doc.UndoNames)
        revision = self.state["revision"]
        response = self.request("transform_part", id="BadTransform", part="Body",
                                coordinate_system={"origin": [0, 0, 0], "x": [1, 0, 0], "y": [1, 0, 0], "z": [0, 0, 1]})
        self.assertFalse(response["ok"], response)
        self.assertEqual(len(self.doc.UndoNames), count)
        self.assertEqual(self.state["revision"], revision)
        self.assertIsNone(self.doc.getObject("BadTransform"))
        self.assertAlmostEqual(self.volumes()["Body"], 1000)

    def test_current_parts_step_export_and_recovery_preserve_bar(self):
        self.part()
        self.call("split_part", id="Split", part="Body", plane={"origin": [5, 0, 0], "normal": [1, 0, 0]})
        self.call("transform_part", id="Copy", part="Body", translation=[20, 0, 0], copy=True)
        original_order = self.state["studio"]["feature_order"]
        with tempfile.TemporaryDirectory(prefix="studio-export-recovery-", dir=ROOT / "validation") as temporary:
            step = Path(temporary) / "current-parts.step"
            self.call("export", path=str(step))
            exported = Part.read(str(step))
            self.assertEqual(len(exported.Solids), 3)
            self.assertAlmostEqual(sum(solid.Volume for solid in exported.Solids), 1500)
            self.call("rollback", index=original_order.index("Copy"))
            checkpoint = self.core.checkpoint(self.doc, force=True)
            expected_bar = self.state["studio"]["rollback_index"]
            App.closeDocument(self.doc.Name)
            restored = self.core.dispatch({"op": "recover", "path": str(checkpoint)})
            self.assertTrue(restored["ok"], restored)
            self.state = restored["result"]
            self.assertEqual(self.state["studio"]["feature_order"], original_order)
            self.assertEqual(self.state["studio"]["rollback_index"], expected_bar)
            self.assertEqual(len(self.volumes()), 2)
            self.call("rollback", index=len(original_order))
            self.assertEqual(len(self.volumes()), 3)

    def test_part_appearance_survives_new_generation(self):
        self.part()
        self.call("set_part_appearance", part="Body", name="Plate", visible=False, color=[.1, .3, .8])
        self.call("sketch_rectangle", id="AddProfile", body="Body", x=8, width=5, height=10)
        self.call("pad", id="Add", profile="AddProfile", length=10, operation="add", merge_scope=["Body"])
        part = self.state["studio"]["parts"][0]
        self.assertEqual(part["name"], "Plate")
        self.assertFalse(part["visible"])
        for actual, expected in zip(part["color"], [.1, .3, .8]):
            self.assertAlmostEqual(actual, expected)

    def test_revolve_sweep_and_loft_are_native_editable_tools(self):
        self.call("sketch_rectangle", id="RevolveProfile", plane="XZ", x=3, width=2, height=5)
        self.call("revolve", id="Revolve", profile="RevolveProfile", angle="360 deg", operation="new")
        self.assertEqual(self.doc.Revolve.TypeId, "Part::Revolution")
        self.assertAlmostEqual(sum(self.volumes().values()), 80 * __import__("math").pi, places=6)
        self.call("create_body", id="SweepBody")
        self.call("sketch_circle", id="SweepProfile", body="SweepBody", plane="YZ", x=0, y=0, diameter=2)
        self.call("create_sketch", id="SweepPath", body="SweepBody")
        self.call("add_line", sketch="SweepPath", x1=0, y1=0, x2=10, y2=0, body="SweepBody")
        self.call("sweep", id="Sweep", profile="SweepProfile", path="SweepPath", operation="new")
        self.assertEqual(self.doc.Sweep.TypeId, "Part::Sweep")
        self.assertAlmostEqual(studio.current_part(self.doc, "SweepBody").Shape.Volume, 10 * __import__("math").pi, places=6)
        self.call("create_body", id="LoftBody")
        self.call("sketch_circle", id="LoftStart", body="LoftBody", x=0, y=0, diameter=4)
        self.call("sketch_circle", id="LoftEnd", body="LoftBody", x=0, y=0, diameter=4)
        self.doc.LoftEnd.MapMode = "Deactivated"
        self.doc.LoftEnd.Placement.Base = App.Vector(0, 0, 10)
        self.doc.recompute()
        self.fresh()
        self.call("loft", id="Loft", sections=["LoftStart", "LoftEnd"], operation="new")
        self.assertEqual(self.doc.Loft.TypeId, "Part::Loft")
        self.assertAlmostEqual(studio.current_part(self.doc, "LoftBody").Shape.Volume, 40 * __import__("math").pi, places=6)

    def test_auto_add_scope_grows_and_shrinks_in_one_transaction(self):
        self.part()
        self.part("Second", x=20)
        self.call("sketch_rectangle", id="AutoProfile", body="Body", x=8, width=5, height=10)
        self.call("pad", id="AutoAdd", profile="AutoProfile", length=10, operation="add", merge_scope="auto")
        undo_count = len(self.doc.UndoNames)
        self.call("set_parameter", feature="AutoProfile", parameter="Width", value=15)
        self.assertEqual(len(self.doc.UndoNames), undo_count + 1)
        self.assertEqual(set(self.volumes()), {"Body"})
        self.assertAlmostEqual(self.volumes()["Body"], 3000)
        self.assertEqual(self.doc.AutoAdd.KurtShapeTool.LengthFwd.Value, 10)
        self.call("undo")
        self.assert_volumes({"Body": 1300, "Second": 1000})
        self.call("redo")
        self.assertEqual(set(self.volumes()), {"Body"})
        self.call("set_parameter", feature="AutoProfile", parameter="Width", value=5)
        self.assert_volumes({"Body": 1300, "Second": 1000})

    def test_auto_remove_scope_grows_drops_and_retargets(self):
        self.part()
        self.part("Second", x=20)
        self.call("sketch_rectangle", id="AutoProfile", body="Body", x=8, y=4, width=5, height=2)
        self.call("pocket", id="AutoCut", profile="AutoProfile", through_all=True,
                  operation="remove", merge_scope="auto")
        self.call("set_parameter", feature="AutoProfile", parameter="Width", value=15)
        self.assertAlmostEqual(self.volumes()["Body"], 960)
        self.assertAlmostEqual(self.volumes()["Second"], 940)
        self.call("set_parameter", feature="AutoProfile", parameter="Width", value=5)
        self.assertAlmostEqual(self.volumes()["Body"], 960)
        self.assertAlmostEqual(self.volumes()["Second"], 1000)
        # An unmanaged native move reports pending geometry until the managed
        # rebuild atomically migrates the public Boolean to the other part.
        self.doc.AutoProfile.MapMode = "Deactivated"
        self.doc.AutoProfile.Placement = App.Placement(App.Vector(20, 0, 0), App.Rotation())
        self.doc.recompute()
        self.fresh()
        self.assertTrue(any(error.get("code") == "auto_merge_scope_changed"
                            for error in studio.validation_errors(self.doc)))
        self.call("rebuild")
        self.assertAlmostEqual(self.volumes()["Body"], 1000)
        self.assertAlmostEqual(self.volumes()["Second"], 960)
        self.assertEqual(self.doc.AutoCut.Name, "AutoCut")

    def test_auto_intersect_scope_grows_and_shrinks(self):
        self.part()
        self.part("Second", x=20)
        self.call("sketch_rectangle", id="AutoProfile", body="Body", width=5, height=10)
        self.call("pad", id="AutoCommon", profile="AutoProfile", length=10,
                  operation="intersect", merge_scope="auto")
        self.call("set_parameter", feature="AutoProfile", parameter="Width", value=25)
        self.assert_volumes({"Body": 1000, "Second": 500})
        with tempfile.TemporaryDirectory(prefix="studio-auto-scope-persistence-", dir=ROOT / "validation") as temporary:
            path = Path(temporary) / "auto-scope.FCStd"
            self.call("save", path=str(path))
            App.closeDocument(self.doc.Name)
            response = self.core.dispatch({"op": "open", "path": str(path)})
            self.assertTrue(response["ok"], response)
            self.state = response["result"]
            self.assert_volumes({"Body": 1000, "Second": 500})
        self.call("set_parameter", feature="AutoProfile", parameter="Width", value=5)
        self.assert_volumes({"Body": 500, "Second": 1000})

    def test_auto_scope_unsafe_native_consumer_migration_is_rejected(self):
        self.part()
        self.part("Second", x=20)
        self.call("sketch_rectangle", id="AutoProfile", body="Body", x=8, y=4, width=15, height=2)
        self.call("pocket", id="AutoCut", profile="AutoProfile", through_all=True,
                  operation="remove", merge_scope="auto")
        tip = studio.current_part(self.doc, "Second").Tip
        self.call("fillet", id="ScopedFillet", part="Second",
                  edges=[{"feature": tip.Name, "subelement": "Edge1"}], radius=.2)
        accepted, undo_count = self.volumes(), len(self.doc.UndoNames)
        response = self.request("set_parameter", feature="AutoProfile", parameter="Width", value=5)
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], "build_failed")
        self.assertTrue(any(error.get("code") == "auto_merge_scope_changed"
                            for error in response["error"].get("features", [])), response)
        self.assertEqual(self.volumes(), accepted)
        self.assertEqual(len(self.doc.UndoNames), undo_count)

    def test_body_placement_native_new_copy_add_and_export(self):
        self.doc.Body.Placement = App.Placement(App.Vector(30, 40, 0), App.Rotation(App.Vector(0, 0, 1), 90))
        self.doc.recompute()
        self.fresh()
        self.part()
        shape = studio.current_part(self.doc, "Body").Shape
        self.assertAlmostEqual(shape.BoundBox.XMin, 20)
        self.assertAlmostEqual(shape.BoundBox.YMin, 40)
        self.call("transform_part", id="Copy", part="Body", copy=True, translation=[20, 0, 0])
        copied = next(body for body in studio.current_parts(self.doc) if studio.part_id(body) != "Body")
        self.assertAlmostEqual(copied.Shape.BoundBox.XMin, 40)
        self.doc.Body.Placement = App.Placement(App.Vector(30, 40, 0), App.Rotation(App.Vector(1, 0, 0), 90))
        self.doc.recompute()
        self.fresh()
        self.call("rebuild")
        rotated = studio.current_part(self.doc, "Body").Shape.BoundBox
        self.assertAlmostEqual(rotated.XMin, 30)
        self.assertAlmostEqual(rotated.YMin, 30)
        self.assertAlmostEqual(rotated.ZMax, 10)
        self.doc.Body.Placement = App.Placement(App.Vector(30, 40, 0), App.Rotation(App.Vector(0, 0, 1), 90))
        self.doc.recompute()
        self.fresh()
        self.call("rebuild")
        self.call("create_body", id="ToolFrame")
        self.call("sketch_rectangle", id="AddProfile", body="ToolFrame", x=20, y=48, width=10, height=5)
        self.call("pad", id="Add", profile="AddProfile", length=10, operation="add", merge_scope=["Body"])
        self.assertAlmostEqual(self.volumes()["Body"], 1300)
        box = studio.current_part(self.doc, "Body").Shape.BoundBox
        self.assertAlmostEqual(box.XMin, 20)
        self.assertAlmostEqual(box.YMax, 53)
        with tempfile.TemporaryDirectory(prefix="kurtshape-posed-parts-", dir=ROOT / "validation") as directory:
            path = Path(directory) / "posed-parts.step"
            self.call("export", path=str(path))
            imported = Part.read(str(path))
            self.assertEqual(len(imported.Solids), 2)
            self.assertAlmostEqual(imported.Volume, 2300)
            self.assertAlmostEqual(imported.BoundBox.XMin, 20)
            self.assertAlmostEqual(imported.BoundBox.XMax, 50)

    def test_legacy_body_placement_auto_scope_and_transform_copy(self):
        self.doc.Body.Placement = App.Placement(App.Vector(30, 40, 0), App.Rotation(App.Vector(0, 0, 1), 90))
        self.doc.recompute()
        self.fresh()
        self.call("sketch_rectangle", id="LegacyProfile", body="Body", width=10, height=10)
        self.call("pad", id="LegacyPad", profile="LegacyProfile", body="Body", length=10)
        self.call("transform_part", id="Copy", part="Body", copy=True, translation=[20, 0, 0])
        copied = studio.current_part(self.doc, "CopyPart")
        self.assertAlmostEqual(copied.Shape.BoundBox.XMin, 40)
        self.call("create_body", id="ToolFrame")
        self.call("sketch_rectangle", id="AddProfile", body="ToolFrame", x=20, y=48, width=10, height=5)
        self.call("pad", id="AutoAdd", profile="AddProfile", length=10, operation="add", merge_scope="auto")
        self.assertAlmostEqual(self.volumes()["Body"], 1300)
        self.assertEqual(list(self.doc.AutoAdd.KurtShapeMergePartIds), ["Body"])
        self.call("set_parameter", feature="AutoAdd", parameter="Length", value=15)
        self.assertAlmostEqual(self.volumes()["Body"], 1550)
        self.assertAlmostEqual(studio.current_part(self.doc, "Body").Shape.BoundBox.YMax, 53)

    def test_studio_up_to_face_and_sweep_path_selectors(self):
        self.part("Body", width=20, height=20, depth=15)
        self.call("create_body", id="RaisedBody")
        self.call("sketch_rectangle", id="RaisedProfile", body="RaisedBody", x=4, y=4, width=3, height=3)
        cap = {"kind": "created_by", "feature": "BodyExtrude", "entity_type": "face", "cap": "end"}
        self.call("pad", id="ToFace", profile="RaisedProfile", operation="new", end_type="up_to_face", up_to_face=cap)
        self.assertEqual(self.doc.ToFace.TypeId, "PartDesign::Pad")
        self.assertIn("up_to_face", __import__("json").loads(self.doc.ToFace.QueryInputs))
        self.assertAlmostEqual(self.volumes()["RaisedBody"], 135)
        self.call("set_parameter", feature="BodyExtrude", parameter="Length", value=20)
        self.assertAlmostEqual(self.volumes()["RaisedBody"], 180)
        self.call("create_body", id="SweepBody")
        self.doc.SweepBody.Placement = App.Placement(App.Vector(30, 40, 0), App.Rotation(App.Vector(0, 0, 1), 90))
        self.doc.recompute()
        self.fresh()
        self.call("sketch_circle", id="SweepProfile", body="SweepBody", plane="YZ", x=0, y=0, diameter=2)
        self.call("create_sketch", id="SweepPath", body="SweepBody")
        self.call("add_line", sketch="SweepPath", x1=0, y1=0, x2=10, y2=0, body="SweepBody")
        self.call("sweep", id="SweepLiteral", profile="SweepProfile",
                  path={"feature": "SweepPath", "subelement": "Edge1"}, operation="new")
        path = {"kind": "created_by", "feature": "SweepPath", "entity_type": "edge"}
        self.call("sweep", id="SweepQuery", profile="SweepProfile", path=path, operation="new")
        self.assertIn("path", __import__("json").loads(self.doc.SweepQuery.Spine[0].QueryInputs))
        self.assertAlmostEqual(self.volumes()["SweepBody"], 10 * __import__("math").pi, places=6)
        for name in ["SweepLiteral", "SweepQuery"]:
            shape = self.doc.getObject(name).Shape
            self.assertAlmostEqual(shape.Volume, 10 * __import__("math").pi, places=6)
            self.assertAlmostEqual(shape.BoundBox.XMin, 29)
            self.assertAlmostEqual(shape.BoundBox.YMin, 40)
            self.assertEqual(self.doc.getObject(name).Spine[0].TraceSupport, True)
        with tempfile.TemporaryDirectory(prefix="studio-posed-sweep-persistence-", dir=ROOT / "validation") as temporary:
            saved = Path(temporary) / "posed-sweeps.FCStd"
            self.call("save", path=str(saved))
            App.closeDocument(self.doc.Name)
            response = self.core.dispatch({"op": "open", "path": str(saved)})
            self.assertTrue(response["ok"], response)
            self.state = response["result"]
            self.doc.SweepBody.Placement = App.Placement(App.Vector(50, 40, 0), App.Rotation(App.Vector(0, 0, 1), 90))
            self.doc.recompute()
            self.fresh()
            self.call("rebuild")
            for name in ["SweepLiteral", "SweepQuery"]:
                self.assertAlmostEqual(self.doc.getObject(name).Shape.BoundBox.XMin, 49)


if __name__ == "__main__":
    unittest.main()
