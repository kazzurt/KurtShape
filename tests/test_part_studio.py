"""Native U2 studio fixtures: scope, parts, history and persistent dependencies."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
import Sketcher
from kurtshape.core import Controller
from kurtshape.core import OperationError
from kurtshape import studio
from kurtshape import selectors
from kurtshape import sketch_tools


class PartStudioTests(unittest.TestCase):
    def setUp(self):
        self.initial = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="part-studio-session-")
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

    def test_warm_inspection_reuses_native_ownership_and_history(self):
        from kurtshape import document_index
        from kurtshape.core import intent_signature
        self.part()
        self.part("Second", x=20)
        self.call("transform_part", id="Copy", part="Body", translation=[40, 0, 0], copy=True)
        expected = self.core.inspect(self.doc, measure=False)
        signature = intent_signature(self.doc)
        index = document_index.get(self.doc)
        counters = dict(index.counts)
        for _ in range(3):
            self.assertEqual(self.core.inspect(self.doc, measure=False), expected)
        self.assertEqual(index.counts, counters)
        self.assertEqual(intent_signature(self.doc), signature)

    def test_native_history_edits_invalidate_cached_parts_and_active_features(self):
        self.part()
        self.call("transform_part", id="Copy", part="Body", translation=[20, 0, 0], copy=True)
        doc = self.doc
        original = [body.Name for body in studio.current_parts(doc)]
        sequence = studio.order(doc)
        position = sequence.index(doc.Copy)
        self.assertEqual(len(original), 2)
        self.assertTrue(studio.is_active(doc.Copy))
        doc.openTransaction("Native rollback metadata")
        doc.KurtShapeProject.KurtShapeRollbackIndex = position
        self.assertEqual(len(studio.current_parts(doc)), 1)
        self.assertFalse(studio.is_active(doc.Copy))
        doc.commitTransaction()
        doc.undo()
        self.assertEqual([body.Name for body in studio.current_parts(doc)], original)
        self.assertTrue(studio.is_active(doc.Copy))
        doc.redo()
        self.assertEqual(len(studio.current_parts(doc)), 1)
        self.assertFalse(studio.is_active(doc.Copy))
        doc.undo()
        doc.openTransaction("Native operation part output edit")
        doc.Copy.KurtShapeOutputParts = []
        self.assertEqual(len(studio.current_parts(doc)), 1)
        doc.abortTransaction()
        self.assertEqual([body.Name for body in studio.current_parts(doc)], original)
        doc.Copy.removeProperty("KurtShapeStudioOperation")
        self.assertEqual(len(studio.current_parts(doc)), 1)

    def test_selector_context_reused_until_native_shape_or_history_changes(self):
        from unittest.mock import patch
        from kurtshape import document_index
        self.part()
        query = {"kind": "created_by", "feature": "BodyExtrude", "cap": "end"}
        with patch.object(selectors, "_Context", wraps=selectors._Context) as context:
            first = selectors.resolve(self.doc, query)
            self.assertEqual(len(first), 1)
            self.assertEqual(selectors.resolve(self.doc, query), first)
            self.assertEqual(context.call_count, 1)
            self.doc.BodyExtrude.LengthFwd = 15
            self.doc.recompute()
            changed = selectors.resolve(self.doc, query)
            self.assertEqual(context.call_count, 2)
            self.assertAlmostEqual(changed[0]["summary"]["center_mm"][2],
                                   first[0]["summary"]["center_mm"][2] + 5)
            self.doc.KurtShapeProject.KurtShapeRollbackIndex = 0
            self.assertEqual(selectors.resolve(self.doc, query), [])
            self.assertEqual(context.call_count, 3)
        # Distinct history consumers cannot retain unbounded native shapes.
        for boundary in [None, *[obj.Name for obj in self.doc.Objects]]:
            selectors.resolve(self.doc, {"kind": "all"}, before=boundary)
        contexts = document_index.get(self.doc).derived["selector_contexts"]
        self.assertLessEqual(len(contexts), selectors._CONTEXT_LIMIT)

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
        with tempfile.TemporaryDirectory(prefix="studio-relocation-", dir=support.TEST_TMP, ignore_cleanup_errors=True) as temporary:
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
            proc = support.run_native_proof([sys.executable, "-B", "-c", script], capture_output=True, text=True,
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
        with tempfile.TemporaryDirectory(prefix="studio-export-recovery-", dir=support.TEST_TMP, ignore_cleanup_errors=True) as temporary:
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
        self.assertEqual(sketch_tools.unconsumed_sketches(self.doc), [])

    def test_unconsumed_sketches_follow_native_profiles_not_reference_links(self):
        self.part()
        self.call("sketch_circle", id="Unused", body="Body", x=20, y=0, diameter=4)
        self.call("create_sketch", id="Reference", body="Body")
        self.call("project_geometry", sketch="Reference", references=[{"feature": "Unused", "subelement": "Edge1"}], defining=False)
        names = lambda: [obj.Name for obj in sketch_tools.unconsumed_sketches(self.doc)]
        self.assertEqual(names(), ["Unused", "Reference"])
        undo_names = list(self.doc.UndoNames)
        for unused in range(3):
            self.assertEqual(names(), ["Unused", "Reference"])
        self.assertEqual(list(self.doc.UndoNames), undo_names)
        self.call("pad", id="ConsumeUnused", profile="Unused", length=3, operation="new")
        self.assertEqual(names(), ["Reference"])
        self.assertEqual(self.doc.ConsumeUnused.Base.Support[0][0], self.doc.Unused)
        self.call("undo")
        self.assertEqual(names(), ["Unused", "Reference"])
        self.call("redo")
        self.assertEqual(names(), ["Reference"])
        order = self.state["studio"]["feature_order"]
        self.call("rollback", index=order.index("ConsumeUnused"))
        self.assertEqual(names(), ["Unused", "Reference"])
        self.call("rollback", index=len(order))
        self.assertEqual(names(), ["Reference"])
        project = self.folder / "unused-sketch-profile-links.FCStd"
        self.call("save", path=str(project))
        App.closeDocument(self.doc.Name)
        response = self.core.dispatch({"op": "open", "path": str(project)})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        self.assertEqual(names(), ["Reference"])

    def test_unconsumed_legacy_and_standalone_sketches_ignore_attachment_use(self):
        self.call("sketch_rectangle", id="Profile", width=10, height=10)
        self.call("pad", id="NativePad", profile="Profile", length=4)
        self.call("create_sketch", id="Unused", plane="XY")
        self.doc.Unused.addGeometry(Part.Circle(App.Vector(20, 0, 0), App.Vector(0, 0, 1), 2), False)
        root = self.doc.addObject("Sketcher::SketchObject", "Standalone")
        root.addGeometry(Part.Circle(App.Vector(30, 0, 0), App.Vector(0, 0, 1), 2), False)
        root.AttachmentSupport = [(self.doc.Unused, ["Edge1"])]
        self.doc.recompute()
        self.fresh()
        self.assertFalse(studio.enabled(self.doc))
        self.assertEqual([obj.Name for obj in sketch_tools.unconsumed_sketches(self.doc)], ["Unused", "Standalone"])
        self.assertEqual([obj.Name for obj in sketch_tools.unconsumed_sketches(self.doc, before=self.doc.Standalone)], ["Unused"])
        self.assertFalse(sketch_tools.show_unconsumed_sketch(None))

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
        with tempfile.TemporaryDirectory(prefix="studio-auto-scope-persistence-", dir=support.TEST_TMP, ignore_cleanup_errors=True) as temporary:
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
        with tempfile.TemporaryDirectory(prefix="kurtshape-posed-parts-", dir=support.TEST_TMP, ignore_cleanup_errors=True) as directory:
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
        self.doc.RaisedBody.Placement = App.Placement(App.Vector(30, 40, 5), App.Rotation(App.Vector(0, 0, 1), 90))
        self.doc.recompute()
        self.fresh()
        self.call("sketch_rectangle", id="RaisedProfile", body="RaisedBody", x=4, y=4, width=3, height=3)
        cap = {"kind": "created_by", "feature": "BodyExtrude", "entity_type": "face", "cap": "end"}
        self.call("pad", id="ToFace", profile="RaisedProfile", operation="new", end_type="up_to_face", up_to_face=cap)
        self.assertEqual(self.doc.ToFace.TypeId, "PartDesign::Pad")
        stop = self.doc.ToFace.UpToFace[0]
        self.assertIn("up_to_face", __import__("json").loads(stop.QueryInputs))
        self.assertAlmostEqual(self.volumes()["RaisedBody"], 90)
        raised = studio.current_part(self.doc, "RaisedBody")
        self.assertAlmostEqual(raised.Shape.BoundBox.XMin, 23)
        self.assertAlmostEqual(raised.Shape.BoundBox.YMin, 44)
        self.assertAlmostEqual(raised.Shape.BoundBox.ZMin, 5)
        self.assertAlmostEqual(raised.Shape.BoundBox.ZMax, 15)
        self.call("set_parameter", feature="BodyExtrude", parameter="Length", value=20)
        self.assertAlmostEqual(self.volumes()["RaisedBody"], 135)
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
        with tempfile.TemporaryDirectory(prefix="studio-posed-sweep-persistence-", dir=support.TEST_TMP, ignore_cleanup_errors=True) as temporary:
            saved = Path(temporary) / "posed-sweeps.FCStd"
            self.call("save", path=str(saved))
            App.closeDocument(self.doc.Name)
            response = self.core.dispatch({"op": "open", "path": str(saved)})
            self.assertTrue(response["ok"], response)
            self.state = response["result"]
            self.assertAlmostEqual(self.volumes()["RaisedBody"], 135)
            self.call("set_parameter", feature="BodyExtrude", parameter="Length", value=22)
            self.assertAlmostEqual(self.volumes()["RaisedBody"], 153)
            self.assertAlmostEqual(studio.current_part(self.doc, "RaisedBody").Shape.BoundBox.ZMax, 22)
            self.doc.SweepBody.Placement = App.Placement(App.Vector(50, 40, 0), App.Rotation(App.Vector(0, 0, 1), 90))
            self.doc.recompute()
            self.fresh()
            self.call("rebuild")
            for name in ["SweepLiteral", "SweepQuery"]:
                self.assertAlmostEqual(self.doc.getObject(name).Shape.BoundBox.XMin, 49)

    def profile_edges(self, feature):
        return [{"feature": feature.Name, "subelement": "Edge" + str(index + 1)}
                for index, edge in enumerate(feature.Shape.Edges)
                if abs(edge.BoundBox.ZMin) < 1e-7 and abs(edge.BoundBox.ZLength) < 1e-7]

    def test_up_to_face_legacy_carrier_scope_migration_preserves_native_pose_and_undo(self):
        self.call("create_body", id="StopBody")
        self.call("sketch_rectangle", id="StopProfile", body="StopBody", width=20, height=20)
        self.call("pad", id="StopPad", profile="StopProfile", body="StopBody", length=15)
        self.call("create_body", id="RaisedBody")
        self.doc.RaisedBody.Placement = App.Placement(App.Vector(30, 40, 5), App.Rotation(App.Vector(0, 0, 1), 90))
        self.doc.recompute()
        self.fresh()
        self.call("sketch_rectangle", id="RaisedProfile", body="RaisedBody", x=4, y=4, width=3, height=3)
        cap = {"kind": "created_by", "feature": "StopPad", "entity_type": "face", "cap": "end"}
        self.call("pad", id="ToFace", profile="RaisedProfile", operation="new", end_type="up_to_face", up_to_face=cap)
        output = studio.current_part(self.doc, "RaisedBody")
        self.assertAlmostEqual(output.Shape.Volume, 90)
        output_name, base_name = output.Name, output.Tip.Name
        carrier_name = studio._body_owner(self.doc.ToFace).Name
        profile = self.doc.ToFace.Profile[0]
        stop = self.doc.ToFace.UpToFace[0]
        self.doc.openTransaction("Legacy up-to-face scope fixture")
        self.doc.getObject(carrier_name).removeObject(profile)
        self.doc.RaisedBody.addObject(profile)
        selectors.bind(self.doc.ToFace, "up_to_face", cap, native_property="UpToFace")
        self.doc.removeObject(stop.Name)
        output.BaseFeature = self.doc.ToFace
        self.doc.commitTransaction()
        with tempfile.TemporaryDirectory(prefix="up-to-face-scope-migration-", dir=support.TEST_TMP,
                                         ignore_cleanup_errors=True) as temporary:
            path = Path(temporary) / "legacy-up-to-face.FCStd"
            self.doc.saveAs(str(path))
            App.closeDocument(self.doc.Name)
            response = self.core.dispatch({"op": "open", "path": str(path)})
            self.assertTrue(response["ok"], response)
            self.state = response["result"]
            pad = self.doc.ToFace
            carrier = self.doc.getObject(carrier_name)
            stop = pad.UpToFace[0]
            output = self.doc.getObject(output_name)
            self.assertEqual(carrier.Tip, pad)
            self.assertEqual(studio._body_owner(pad.Profile[0]), carrier)
            self.assertEqual(studio._body_owner(stop), carrier)
            self.assertEqual(stop.KurtShapeOperationOwner, "ToFace")
            self.assertNotIn("QueryInputs", pad.PropertiesList)
            self.assertEqual(__import__("json").loads(stop.QueryInputs)["up_to_face"]["native_property"], "Support")
            self.assertIsNone(output.BaseFeature)
            self.assertEqual(output.Tip.Name, base_name)
            self.assertEqual(output.Tip.BaseFeature, pad)
            self.assertEqual(self.doc.UndoCount, 0)
            self.assertFalse(selectors.reference_errors(self.doc))
            self.assertAlmostEqual(output.Shape.Volume, 90)
            self.assertAlmostEqual(output.Shape.BoundBox.XMin, 23)
            self.assertAlmostEqual(output.Shape.BoundBox.YMin, 44)
            self.assertAlmostEqual(output.Shape.BoundBox.ZMin, 5)
            self.call("set_parameter", feature="StopPad", parameter="Length", value=20)
            self.assertAlmostEqual(output.Shape.Volume, 135)
            self.assertAlmostEqual(output.Shape.BoundBox.ZMax, 20)
            self.call("undo")
            self.assertEqual(pad.UpToFace[0], stop)
            self.assertAlmostEqual(output.Shape.Volume, 90)
            self.assertFalse(selectors.reference_errors(self.doc))

    def test_project_order_and_sources_have_document_scope_and_migrate_on_reopen(self):
        self.part()
        self.part("Second", x=20)
        self.call("mirror_parts", id="Mirror", parts=["Body"], origin=[0, 0, 0], normal=[1, 0, 0])
        self.call("create_sketch", id="UseSketch", body="Second")
        query = {"kind": "closest", "point": [5, 0, 0],
                 "query": {"kind": "created_by", "feature": "BodyExtrude", "entity_type": "edge"}}
        self.call("project_geometry", sketch="UseSketch", references=[query])
        source = self.doc.UseSketch.ExternalGeometry[0][0]
        self.assertEqual(source.getTypeIdOfProperty("QuerySources"), "App::PropertyLinkListGlobal")
        meta = self.doc.KurtShapeProject
        self.assertEqual(meta.getTypeIdOfProperty("KurtShapeFeatureOrder"), "App::PropertyLinkListGlobal")
        names = [obj.Name for obj in meta.KurtShapeFeatureOrder]
        volumes = self.volumes()
        native_scopes = []
        for body in list(self.doc.Objects):
            binder = getattr(body, "KurtShapeGeometryBinder", None)
            if binder:
                native_scopes.append((body.Name, body.KurtShapeOperationOwner))
                body.BaseFeature = binder.Support[0][0]
                body.removeProperty("KurtShapeGeometryBinder")
                self.doc.removeObject(binder.Name)
        self.assertTrue(native_scopes)
        for obj, prop in [(meta, "KurtShapeFeatureOrder"), (source, "QuerySources")]:
            values = list(getattr(obj, prop))
            obj.removeProperty(prop)
            obj.addProperty("App::PropertyLinkList", prop, "Legacy scope fixture")
            setattr(obj, prop, values)
        with tempfile.TemporaryDirectory(prefix="studio-scope-migration-", dir=support.TEST_TMP,
                                         ignore_cleanup_errors=True) as temporary:
            path = Path(temporary) / "legacy-scopes.FCStd"
            self.doc.saveAs(str(path))
            App.closeDocument(self.doc.Name)
            response = self.core.dispatch({"op": "open", "path": str(path)})
            self.assertTrue(response["ok"], response)
            self.state = response["result"]
            self.assertEqual(self.doc.KurtShapeProject.getTypeIdOfProperty("KurtShapeFeatureOrder"),
                             "App::PropertyLinkListGlobal")
            self.assertEqual(self.doc.UseSketch.ExternalGeometry[0][0].getTypeIdOfProperty("QuerySources"),
                             "App::PropertyLinkListGlobal")
            self.assertEqual([obj.Name for obj in self.doc.KurtShapeProject.KurtShapeFeatureOrder], names)
            for name, operation in native_scopes:
                body = self.doc.getObject(name)
                self.assertEqual(body.BaseFeature.TypeId, "PartDesign::SubShapeBinder")
                self.assertEqual(body.BaseFeature, body.KurtShapeGeometryBinder)
                self.assertEqual(body.BaseFeature.KurtShapeOperationOwner, operation)
                self.assertFalse(body.BaseFeature.Shape.isNull())
                self.assertFalse({"Touched", "Invalid", "Error"} & set(body.BaseFeature.State))
            self.assertEqual(self.doc.UndoCount, 0)
            self.assert_volumes(volumes)
            self.call("rebuild")
            self.assertFalse(selectors.reference_errors(self.doc))
            self.call("save", path=str(path))
            self.assertEqual(self.doc.KurtShapeProject.getTypeIdOfProperty("KurtShapeFeatureOrder"),
                             "App::PropertyLinkListGlobal")

    def test_used_edges_form_associated_extrusion_profile_across_body_placements(self):
        self.doc.Body.Placement = App.Placement(App.Vector(11, 13, 0),
                                               App.Rotation(App.Vector(0, 0, 1), 90))
        self.doc.recompute()
        self.fresh()
        self.part(width=10, height=6, depth=4)
        self.call("create_body", id="UseBody")
        self.doc.UseBody.Placement = App.Placement(App.Vector(30, 40, 0),
                                                  App.Rotation(App.Vector(0, 0, 1), 90))
        self.doc.recompute()
        self.fresh()
        self.call("create_sketch", id="UsedProfile", body="UseBody")
        refs = self.profile_edges(self.doc.BodyExtrude)
        self.assertEqual(len(refs), 4)
        before = self.doc.UndoCount
        self.call("project_geometry", sketch="UsedProfile", references=refs)
        self.assertEqual(self.doc.UndoCount, before + 1)
        self.assertEqual(len(self.doc.UsedProfile.Shape.Edges), 4)
        self.assertTrue(self.doc.UsedProfile.Shape.Wires[0].isClosed())
        helpers = [obj.Name for obj in self.doc.Objects if getattr(obj, "KurtShapeUseOwner", "") == "UsedProfile"]
        self.assertEqual(len(helpers), 4)
        self.call("project_geometry", sketch="UsedProfile", references=refs)
        self.assertEqual(len(self.doc.UsedProfile.ExternalGeometry), 4)
        self.call("pad", id="UsedExtrude", body="UseBody", profile="UsedProfile", length=2, operation="new")
        self.assertAlmostEqual(self.volumes()["UseBody"], 120)
        box = studio.current_part(self.doc, "UseBody").Shape.BoundBox
        self.assertAlmostEqual(box.XMin, 5)
        self.assertAlmostEqual(box.YMin, 13)
        self.call("set_parameter", feature="BodyProfile", parameter="Width", value=12)
        self.assertAlmostEqual(self.volumes()["UseBody"], 144)
        with tempfile.TemporaryDirectory(prefix="studio-use-projection-", dir=support.TEST_TMP,
                                         ignore_cleanup_errors=True) as temporary:
            path = Path(temporary) / "associated-use.FCStd"
            self.call("save", path=str(path))
            App.closeDocument(self.doc.Name)
            response = self.core.dispatch({"op": "open", "path": str(path)})
            self.assertTrue(response["ok"], response)
            self.state = response["result"]
            self.call("set_parameter", feature="BodyProfile", parameter="Width", value=14)
            self.assertAlmostEqual(self.volumes()["UseBody"], 168)
            self.assertEqual(len(self.doc.UsedProfile.ExternalGeometry), 4)

    def test_use_sketch_edit_groups_helper_creation_and_restores_undo_redo(self):
        self.part(width=10, height=6, depth=4)
        self.call("create_body", id="UseBody")
        self.call("create_sketch", id="UsedProfile", body="UseBody")
        refs = self.profile_edges(self.doc.BodyExtrude)
        before = self.doc.UndoCount
        self.call("begin_sketch_edit", feature="UsedProfile")
        self.call("project_geometry", sketch="UsedProfile", references=refs[:2])
        self.call("undo")
        self.assertEqual(len(self.doc.UsedProfile.ExternalGeometry), 0)
        self.call("redo")
        self.assertEqual(len(self.doc.UsedProfile.ExternalGeometry), 2)
        # Native Sketcher commands can commit within the same managed lease.
        self.doc.commitTransaction()
        self.doc.openTransaction("Native projection continuation")
        self.call("project_geometry", sketch="UsedProfile", references=refs[2:])
        self.call("finish_sketch_edit")
        self.assertEqual(self.doc.UndoCount, before + 1)
        self.assertEqual(len(self.doc.UsedProfile.Shape.Edges), 4)
        helpers = [obj.Name for obj in self.doc.Objects if getattr(obj, "KurtShapeUseOwner", "") == "UsedProfile"]
        self.assertEqual(len(helpers), 4)
        # The first Finish of a new sketch is one step with its creation.
        self.call("undo")
        self.assertIsNone(self.doc.getObject("UsedProfile"))
        self.assertTrue(all(self.doc.getObject(name) is None for name in helpers))
        self.assertEqual(self.doc.UndoCount, before - 1)
        self.call("redo")
        self.assertEqual(len(self.doc.UsedProfile.Shape.Edges), 4)
        self.assertTrue(all(self.doc.getObject(name) is not None for name in helpers))

    def test_use_rejects_cycle_atomically_and_cancellation_removes_helpers(self):
        self.part(width=10, height=6, depth=4)
        self.call("create_body", id="UseBody")
        self.call("create_sketch", id="UsedProfile", body="UseBody")
        refs = self.profile_edges(self.doc.BodyExtrude)
        accepted = {obj.Name for obj in self.doc.Objects}
        self.call("begin_sketch_edit", feature="UsedProfile")
        self.call("project_geometry", sketch="UsedProfile", references=refs)
        self.call("finish_sketch_edit", cancel=True)
        self.assertEqual({obj.Name for obj in self.doc.Objects}, accepted)
        self.assertEqual(len(self.doc.UsedProfile.ExternalGeometry), 0)
        self.call("add_rectangle", sketch="UsedProfile", x=20, y=0, width=2, height=2)
        self.call("pad", id="Downstream", profile="UsedProfile", body="UseBody", length=2)
        before, names = self.doc.UndoCount, {obj.Name for obj in self.doc.Objects}
        response = self.request("project_geometry", sketch="UsedProfile", references=[refs[0],
                                {"feature": "Downstream", "subelement": "Edge1"}])
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], "cyclic_reference")
        self.assertEqual(self.doc.UndoCount, before)
        self.assertEqual({obj.Name for obj in self.doc.Objects}, names)
        self.assertEqual(len(self.doc.UsedProfile.ExternalGeometry), 0)

    def test_reference_selector_after_native_dimension_commit_groups_finish_and_cancel(self):
        self.part(width=10, height=6, depth=4)
        self.call("create_body", id="UseBody")
        self.call("create_sketch", id="DimensionedProfile", body="UseBody")
        sketch = self.doc.DimensionedProfile
        query = {"kind": "created_by", "feature": "BodyExtrude", "entity_type": "edge"}
        refs = [{"kind": "closest", "point": point, "query": query}
                for point in ([5, 0, 0], [10, 3, 0])]
        before = self.doc.UndoCount
        self.call("begin_sketch_edit", feature=sketch.Name)
        circle = sketch.addGeometry(Part.Circle(App.Vector(3, 3, 0), App.Vector(0, 0, 1), 1))
        sketch.addConstraint(Sketcher.Constraint("Diameter", circle, 2))
        # Native Dimension followed by Escape can commit without ending the
        # managed sketch lease. The next projection must reopen a transaction
        # before authoring its source selector binding.
        self.doc.commitTransaction()
        self.assertFalse(self.doc.HasPendingTransaction)
        self.fresh()
        self.call("project_geometry", sketch=sketch.Name, references=refs[:1], defining=False)
        self.assertTrue(self.doc.HasPendingTransaction)
        helper = sketch.ExternalGeometry[0][0]
        helper_name = helper.Name
        self.assertEqual(helper.TypeId, "PartDesign::ShapeBinder")
        self.assertIn("use_source", __import__("json").loads(helper.QueryInputs))
        self.call("finish_sketch_edit")
        self.assertEqual(self.doc.UndoCount, before + 1)
        self.assertEqual(sketch.GeometryCount, 1)
        self.assertEqual(len(sketch.Shape.Edges), 1)
        self.assertEqual(sketch.Constraints[0].Type, "Diameter")
        self.assertFalse(selectors.reference_errors(self.doc))
        self.call("undo")
        self.assertEqual(sketch.GeometryCount, 0)
        self.assertEqual(len(sketch_tools.external_links(sketch)), 0)
        self.assertIsNone(self.doc.getObject(helper_name))
        self.call("redo")
        self.assertEqual(sketch.GeometryCount, 1)
        self.assertEqual(len(sketch_tools.external_links(sketch)), 1)
        self.assertEqual(sketch.Constraints[0].Type, "Diameter")
        self.assertFalse(selectors.reference_errors(self.doc))
        accepted = {obj.Name for obj in self.doc.Objects}
        before = self.doc.UndoCount
        self.call("begin_sketch_edit", feature=sketch.Name)
        sketch.setDatum(0, App.Units.Quantity("3 mm"))
        self.doc.commitTransaction()
        self.assertFalse(self.doc.HasPendingTransaction)
        self.fresh()
        self.call("project_geometry", sketch=sketch.Name, references=refs[1:], defining=False)
        self.assertEqual(len(sketch_tools.external_links(sketch)), 2)
        self.call("finish_sketch_edit", cancel=True)
        # The existing metadata-only cancellation boundary retires native Redo
        # of the committed dimension; canceled reference helpers stay absent.
        self.assertEqual(self.doc.UndoCount, before + 1)
        self.assertEqual(self.doc.RedoCount, 0)
        self.assertEqual({obj.Name for obj in self.doc.Objects}, accepted)
        self.assertEqual(len(sketch_tools.external_links(sketch)), 1)
        self.assertEqual(sketch.GeometryCount, 1)
        self.assertAlmostEqual(sketch.Constraints[0].Value, 2)
        self.assertFalse(selectors.reference_errors(self.doc))

    def test_rejected_projection_restores_native_geometry_constraints_and_expressions(self):
        from unittest.mock import patch
        self.call("create_sketch", id="ReferenceSource")
        self.call("add_line", sketch="ReferenceSource", x1=0, y1=0, x2=10, y2=0)
        self.call("add_line", sketch="ReferenceSource", x1=0, y1=5, x2=10, y2=5)
        self.call("sketch_circle", id="Draft", x=2, y=3, diameter=4)
        sketch = self.doc.Draft
        sketch.setExpression("Constraints.Diameter", "2 mm + 2 mm")
        self.doc.recompute()
        self.fresh()
        constraints = [(c.Type, c.First, c.Second, c.Name, c.Value) for c in sketch.Constraints]
        expressions = list(sketch.ExpressionEngine)
        objects = {obj.Name for obj in self.doc.Objects}
        self.call("begin_sketch_edit", feature=sketch.Name)
        use_source = sketch_tools._use_source
        def reject_second(doc, target, source, reference, spec):
            if reference["subelement"] == "Edge2":
                raise OperationError("invalid_projection", "Rejected second native projection")
            return use_source(doc, target, source, reference, spec)
        with patch.object(sketch_tools, "_use_source", side_effect=reject_second):
            response = self.request("project_geometry", sketch=sketch.Name,
                                    references=[{"feature": "ReferenceSource", "subelement": "Edge1"},
                                                {"feature": "ReferenceSource", "subelement": "Edge2"}])
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "invalid_projection")
        self.fresh()
        self.assertEqual(self.state["active_sketch_edit"], sketch.Name)
        self.assertEqual({obj.Name for obj in self.doc.Objects}, objects)
        self.assertEqual(sketch.GeometryCount, 1)
        self.assertEqual(sketch_tools.external_links(sketch), [])
        self.assertEqual([(c.Type, c.First, c.Second, c.Name, c.Value) for c in sketch.Constraints], constraints)
        self.assertEqual(list(sketch.ExpressionEngine), expressions)
        self.assertEqual(sketch.solve(), 0)
        self.call("finish_sketch_edit", cancel=True)

    def test_native_sketch_snapshot_restore_has_no_embedded_cache_or_constraint_index_errors(self):
        script = """
import sys
sys.path.insert(0, SRC)
sys.path.insert(0, TESTS)
import FreeCAD as App
import Part
import Sketcher
from kurtshape.sketch_tools import restore_sketch_content
App.Console.SetStatus('Console', 'Err', True)
doc = App.newDocument('NativeSnapshotProof')
sketch = doc.addObject('Sketcher::SketchObject', 'Sketch')
blank = bytes(sketch.dumpContent())
circle = sketch.addGeometry(Part.Circle(App.Vector(2,3,0), App.Vector(0,0,1), 2))
sketch.addConstraint(Sketcher.Constraint('Diameter', circle, 4))
sketch.renameConstraint(0, 'Diameter')
sketch.setExpression('Constraints.Diameter', '2 mm + 2 mm')
doc.recompute()
small = bytes(sketch.dumpContent())
line = sketch.addGeometry(Part.LineSegment(App.Vector(1,0,0), App.Vector(4,0,0)))
sketch.addConstraint(Sketcher.Constraint('Horizontal', line))
doc.recompute()
large = bytes(sketch.dumpContent())
for raw, count in [(blank,0), (large,2), (small,1), (large,2), (blank,0)]:
    restore_sketch_content(sketch, raw)
    doc.recompute()
    assert sketch.GeometryCount == count
    assert sketch.ConstraintCount == count
    assert sketch.solve() == 0
    if count:
        assert sketch.Constraints[0].Name == 'Diameter'
        assert abs(sketch.Constraints[0].Value - 4) < 1e-7
        assert sketch.ExpressionEngine == [('.Constraints.Diameter', '2 mm + 2 mm')]
    else:
        assert sketch.Shape.isNull() and sketch.ExpressionEngine == []
App.closeDocument(doc.Name)
import os
from pathlib import Path
sys.path.insert(0, str(Path(SRC).parent / 'tools'))
from run_native_tests import isolated_environment
os.environ.update(isolated_environment(Path(os.environ['KURTSHAPE_TEST_RUN_DIR'])))
import unittest
suite = unittest.defaultTestLoader.loadTestsFromNames([
    'test_part_studio.PartStudioTests.test_rejected_projection_restores_native_geometry_constraints_and_expressions',
    'test_part_studio.PartStudioTests.test_use_sketch_edit_groups_helper_creation_and_restores_undo_redo',
])
assert unittest.TextTestRunner().run(suite).wasSuccessful()
print('Native sketch snapshot and projection rollback proof passed')
""".replace("SRC", repr(str(ROOT / "src"))).replace("TESTS", repr(str(ROOT / "tests")))
        proc = support.run_native_proof([sys.executable, "-B", "-c", script], capture_output=True, text=True,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=30)
        output = proc.stdout + proc.stderr
        self.assertEqual(proc.returncode, 0, output)
        self.assertNotIn("Reading failed from embedded file", output)
        self.assertNotIn("invalid constraint indices", output)
        self.assertNotIn("Unmanaged change of Geometry", output)

    def test_used_edge_follows_source_identity_and_deleted_edge_reports_missing_until_undo(self):
        self.call("create_sketch", id="ReferenceSource")
        self.call("add_line", sketch="ReferenceSource", x1=0, y1=0, x2=10, y2=0)
        self.call("add_line", sketch="ReferenceSource", x1=0, y1=5, x2=10, y2=5)
        source = self.doc.ReferenceSource
        self.call("create_sketch", id="UsedEdge")
        sketch = self.doc.UsedEdge
        self.call("project_geometry", sketch=sketch.Name,
                  references=[{"feature": source.Name, "subelement": "Edge1"}])
        self.call("rename_feature", feature=source.Name, name="Renamed reference source")
        self.call("set_parameter", feature=source.Name, parameter="EndX", value=14)
        self.assertAlmostEqual(sketch.Shape.Length, 14)
        self.assertEqual(sketch_tools.external_source(sketch, "ExternalEdge1"), (source, "Edge1"))
        self.doc.openTransaction("Delete original source edge while keeping another edge")
        source.delGeometry(0)
        self.doc.recompute()
        self.doc.commitTransaction()
        self.fresh()
        self.assertEqual(self.state["build_status"], "failed")
        errors = sketch_tools.reference_errors(sketch)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["code"], "missing_reference")
        row = next(feature for feature in self.state["features"] if feature["id"] == sketch.Name)
        self.assertEqual(row["reference_health"][0]["status"], "missing")
        self.assertAlmostEqual(source.Shape.Edges[0].BoundBox.YMin, 5)
        self.assertAlmostEqual(sketch.Shape.Length, 14)  # Native retained wire must be reported as unusable.
        response = self.request("rebuild")
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "build_failed")
        self.assertTrue(any(error.get("code") == "missing_reference" for error in response["error"]["features"]))
        self.fresh()
        self.call("undo")
        self.assertEqual(sketch_tools.reference_errors(sketch), [])
        self.assertNotEqual(self.state["build_status"], "failed")
        self.assertAlmostEqual(sketch.Shape.Length, 14)
        self.assertEqual(sketch_tools.external_source(sketch, "ExternalEdge1"), (source, "Edge1"))

    def test_face_edge_reference_dimensions_follow_source_and_keep_circle_profile(self):
        self.call("sketch_rectangle", id="Plate", width=20, height=12)
        self.call("pad", id="PlatePad", profile="Plate", length=6)
        pad = self.doc.PlatePad
        top = "Face" + str(next(i + 1 for i, face in enumerate(pad.Shape.Faces)
                                  if abs(face.CenterOfMass.z - 6) < 1e-7))
        refs = [{"feature": pad.Name, "subelement": "Edge" + str(i + 1)}
                for i, edge in enumerate(pad.Shape.Edges)
                if abs(edge.BoundBox.ZMin - 6) < 1e-7 and abs(edge.BoundBox.ZLength) < 1e-7
                and (abs(edge.BoundBox.XMin - 20) < 1e-7 or abs(edge.BoundBox.YMin - 12) < 1e-7)]
        self.assertEqual(len(refs), 2)
        self.call("create_sketch", id="HoleProfile", support={"feature": pad.Name, "subelement": top})
        self.call("begin_sketch_edit", feature="HoleProfile")
        self.call("project_geometry", sketch="HoleProfile", references=refs, defining=False)
        sketch = self.doc.HoleProfile
        self.assertEqual(len(sketch.ExternalGeometry), 1)  # Native Python groups the two source edges.
        circle = sketch.addGeometry(Part.Circle(App.Vector(17, 8, 0), App.Vector(0, 0, 1), 1))
        sketch.addConstraint(Sketcher.Constraint("Radius", circle, 1))
        for reference in refs:
            selection = sketch_tools.external_selection(sketch, pad, reference["subelement"])
            self.assertIsNotNone(selection)
            geoid = -int(selection[len("ExternalEdge"):]) - 2
            edge = pad.Shape.getElement(reference["subelement"])
            offset = 3 if abs(edge.BoundBox.XMin - 20) < 1e-7 else 4
            sketch.addConstraint(Sketcher.Constraint("Distance", circle, 3, geoid, offset))
        self.assertEqual(sketch.solve(), 0)
        self.assertTrue(sketch.FullyConstrained)
        self.fresh()
        self.call("finish_sketch_edit")
        self.assertEqual(len(sketch.Shape.Edges), 1)
        self.assertTrue(sketch.Shape.Wires[0].isClosed())
        self.assertAlmostEqual(sketch.Geometry[circle].Center.x, 17)
        self.assertAlmostEqual(sketch.Geometry[circle].Center.y, 8)
        self.call("pocket", id="ReferenceHole", profile=sketch.Name, length=2, through_all=False)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, 20 * 12 * 6 - 2 * __import__("math").pi)
        self.call("set_parameter", feature="Plate", parameter="Width", value=24)
        self.assertAlmostEqual(sketch.Geometry[circle].Center.x, 21)
        self.assertAlmostEqual(sketch.Geometry[circle].Center.y, 8)
        with tempfile.TemporaryDirectory(prefix="face-edge-reference-dimensions-", dir=support.TEST_TMP,
                                         ignore_cleanup_errors=True) as temporary:
            path = Path(temporary) / "face-edge-dimensions.FCStd"
            self.call("save", path=str(path))
            App.closeDocument(self.doc.Name)
            response = self.core.dispatch({"op": "open", "path": str(path)})
            self.assertTrue(response["ok"], response)
            self.state = response["result"]
            self.call("set_parameter", feature="Plate", parameter="Height", value=16)
            self.assertAlmostEqual(self.doc.HoleProfile.Geometry[circle].Center.x, 21)
            self.assertAlmostEqual(self.doc.HoleProfile.Geometry[circle].Center.y, 12)
            self.assertEqual(len(self.doc.HoleProfile.Shape.Edges), 1)

    def test_use_promotes_reference_edge_without_losing_constraints_or_ids(self):
        self.call("sketch_rectangle", id="Plate", width=20, height=12)
        self.call("pad", id="PlatePad", profile="Plate", length=6)
        self.call("create_sketch", id="ReferencedSketch")
        reference = self.profile_edges(self.doc.PlatePad)[0]
        self.call("project_geometry", sketch="ReferencedSketch", references=[reference], defining=False)
        sketch = self.doc.ReferencedSketch
        selection = sketch_tools.external_selection(sketch, self.doc.PlatePad, reference["subelement"])
        self.assertEqual(selection, "ExternalEdge1")
        self.assertEqual(sketch_tools.external_source(sketch, selection),
                         (self.doc.PlatePad, reference["subelement"]))
        self.call("begin_sketch_edit", feature=sketch.Name)
        line = sketch.addGeometry(Part.LineSegment(App.Vector(0, 0, 0), App.Vector(0, 3, 0)), True)
        sketch.addConstraint(Sketcher.Constraint("Coincident", line, 1, -3, 1))
        self.fresh()
        self.call("finish_sketch_edit")
        before = bytes(sketch.dumpContent())
        self.assertEqual(len(sketch.Shape.Edges), 0)
        self.call("project_geometry", sketch=sketch.Name, references=[reference])
        self.assertEqual(len(sketch_tools.external_links(sketch)), 1)
        self.assertEqual(len(sketch.Shape.Edges), 1)
        self.assertEqual(sketch.Constraints[0].Second, -3)
        self.assertEqual(sketch.Constraints[0].SecondPos, 1)
        self.assertEqual(sketch_tools.external_selection(sketch, self.doc.PlatePad, reference["subelement"]), selection)
        self.call("undo")
        self.assertEqual(len(sketch.Shape.Edges), 0)
        self.assertEqual(sketch.Constraints[0].Second, -3)
        self.call("redo")
        self.assertEqual(len(sketch.Shape.Edges), 1)
        self.call("project_geometry", sketch=sketch.Name, references=[reference], defining=False)
        self.assertEqual(len(sketch.Shape.Edges), 1)  # Dimension references cannot demote an explicit Use.
        self.assertNotEqual(bytes(sketch.dumpContent()), before)
        response = self.request("project_geometry", sketch=sketch.Name, references=[reference], defining="false")
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "invalid_argument")

    def test_out_of_plane_use_projects_onto_oblique_plane_and_resolves_binder_sources(self):
        self.call("sketch_rectangle", id="Plate", width=20, height=12)
        self.call("pad", id="PlatePad", profile="Plate", length=6)
        self.call("create_body", id="ProjectionBody")
        self.call("create_sketch", id="ObliqueSketch", body="ProjectionBody")
        sketch = self.doc.ObliqueSketch
        sketch.AttachmentOffset = App.Placement(App.Vector(0, 0, 2), App.Rotation(App.Vector(1, 0, 0), 45))
        self.doc.recompute()
        self.fresh()
        reference = next({"feature": "PlatePad", "subelement": "Edge" + str(i + 1)}
                         for i, edge in enumerate(self.doc.PlatePad.Shape.Edges)
                         if abs(edge.BoundBox.ZMin - 6) < 1e-7 and abs(edge.BoundBox.ZLength) < 1e-7
                         and abs(edge.BoundBox.YMin - 12) < 1e-7 and edge.BoundBox.XLength > 1)
        self.call("project_geometry", sketch=sketch.Name, references=[reference])
        selection = sketch_tools.external_selection(sketch, self.doc.PlatePad, reference["subelement"])
        self.assertEqual(selection, "ExternalEdge1")
        self.assertEqual(sketch_tools.external_source(sketch, selection),
                         (self.doc.PlatePad, reference["subelement"]))
        self.assertEqual(sketch.ExternalGeometry[0][0].TypeId, "PartDesign::ShapeBinder")
        source_edge = self.doc.PlatePad.Shape.getElement(reference["subelement"])
        expected = [sketch.getGlobalPlacement().inverse().multVec(vertex.Point) for vertex in source_edge.Vertexes]
        projected = sketch.ExternalGeo[2]
        for actual, point in zip((projected.StartPoint, projected.EndPoint), expected):
            self.assertAlmostEqual(actual.x, point.x)
            self.assertAlmostEqual(actual.y, point.y)
            self.assertAlmostEqual(actual.z, 0)
        self.call("set_parameter", feature="Plate", parameter="Width", value=24)
        self.assertAlmostEqual(sketch.ExternalGeo[2].length(), 24)

    def test_grouped_same_body_use_selector_slots_remain_distinct_on_rebuild(self):
        self.call("sketch_rectangle", id="Plate", width=20, height=12)
        self.call("pad", id="PlatePad", profile="Plate", length=6)
        self.call("create_sketch", id="SelectedSketch")
        query = {"kind": "created_by", "feature": "PlatePad", "entity_type": "edge"}
        refs = [{"kind": "closest", "point": point, "query": query}
                for point in ([10, 0, 0], [20, 6, 0], [10, 12, 0])]
        self.call("project_geometry", sketch="SelectedSketch", references=refs, defining=False)
        sketch = self.doc.SelectedSketch
        self.assertEqual(len(sketch.ExternalGeometry), 1)
        self.assertEqual(len(sketch_tools.external_links(sketch)), 3)
        inputs = __import__("json").loads(sketch.QueryInputs)
        self.assertEqual([inputs["use_" + str(i)]["index"] for i in range(3)], [0, 1, 2])
        self.call("set_parameter", feature="Plate", parameter="Width", value=24)
        self.call("rebuild")
        self.assertFalse(selectors.reference_errors(self.doc))
        for i, reference in enumerate(sketch_tools.external_links(sketch), 1):
            self.assertEqual(sketch_tools.external_selection(sketch, *reference), "ExternalEdge" + str(i))
        self.assertAlmostEqual(sketch.ExternalGeo[2].length(), 24)
        self.assertAlmostEqual(sketch.ExternalGeo[3].StartPoint.x, 24)
        self.assertAlmostEqual(sketch.ExternalGeo[4].length(), 24)

    def test_collapsed_projection_does_not_select_a_different_external_edge(self):
        self.call("sketch_rectangle", id="Plate", width=20, height=12)
        self.call("pad", id="PlatePad", profile="Plate", length=6)
        self.call("create_sketch", id="PointProjection")
        vertical = next({"feature": "PlatePad", "subelement": "Edge" + str(i + 1)}
                        for i, edge in enumerate(self.doc.PlatePad.Shape.Edges)
                        if edge.BoundBox.ZLength > 1)
        horizontal = self.profile_edges(self.doc.PlatePad)[0]
        self.call("project_geometry", sketch="PointProjection", references=[vertical, horizontal], defining=False)
        sketch = self.doc.PointProjection
        self.assertIsInstance(sketch.ExternalGeo[2], Part.Point)
        self.assertIsNone(sketch_tools.external_selection(sketch, self.doc.PlatePad, vertical["subelement"]))
        self.assertEqual(sketch_tools.external_selection(sketch, self.doc.PlatePad, horizontal["subelement"]),
                         "ExternalEdge2")

    def test_finishing_undone_use_and_deleting_sketch_prune_only_unused_helpers(self):
        self.part(width=10, height=6, depth=4)
        self.call("create_body", id="UseBody")
        self.call("create_sketch", id="UsedProfile", body="UseBody")
        refs = self.profile_edges(self.doc.BodyExtrude)
        self.call("begin_sketch_edit", feature="UsedProfile")
        self.call("project_geometry", sketch="UsedProfile", references=refs)
        helpers = [obj.Name for obj in self.doc.Objects if getattr(obj, "KurtShapeUseOwner", "") == "UsedProfile"]
        self.call("undo")
        self.assertTrue(all(self.doc.getObject(name) is not None for name in helpers))
        # Finish retires draft Redo. Sources created only by that undone Use
        # must leave the accepted document, in the same grouped undo step.
        self.doc.commitTransaction()
        self.call("finish_sketch_edit")
        self.assertTrue(all(self.doc.getObject(name) is None for name in helpers))
        self.assertIsNotNone(self.doc.getObject("BodyExtrude"))
        self.call("project_geometry", sketch="UsedProfile", references=refs)
        helpers = [obj.Name for obj in self.doc.Objects if getattr(obj, "KurtShapeUseOwner", "") == "UsedProfile"]
        self.call("begin_sketch_edit", feature="UsedProfile")
        for _ in refs:
            self.doc.UsedProfile.delExternal(0)
        self.doc.recompute()
        self.fresh()
        self.doc.commitTransaction()
        self.doc.openTransaction("Native construction command after removing accepted Use")
        self.call("add_line", sketch="UsedProfile", x1=0, y1=0, x2=2, y2=0, construction=True)
        self.call("finish_sketch_edit")
        self.assertEqual(len(self.doc.UsedProfile.ExternalGeometry), 0)
        self.assertTrue(all(self.doc.getObject(name) is None for name in helpers))
        self.call("undo")
        self.assertEqual(len(self.doc.UsedProfile.Shape.Edges), 4)
        self.assertTrue(all(self.doc.getObject(name) is not None for name in helpers))
        count = self.doc.UndoCount
        self.call("delete_feature", feature="UsedProfile")
        self.assertEqual(self.doc.UndoCount, count + 1)
        self.assertIsNone(self.doc.getObject("UsedProfile"))
        self.assertTrue(all(self.doc.getObject(name) is None for name in helpers))
        self.assertAlmostEqual(self.volumes()["Body"], 240)
        self.call("undo")
        self.assertEqual(len(self.doc.UsedProfile.Shape.Edges), 4)
        self.assertTrue(all(self.doc.getObject(name) is not None for name in helpers))
        self.call("redo")
        self.assertTrue(all(self.doc.getObject(name) is None for name in helpers))
        self.assertAlmostEqual(self.volumes()["Body"], 240)


if __name__ == "__main__":
    unittest.main()
