"""Part patterns with include_source: Onshape feature-pattern tool semantics."""
from pathlib import Path
import math
import sys
import unittest

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
from kurtshape import studio
from kurtshape.core import Controller, intent_signature

BLOCK = 40 * 40 * 10
HOLE = math.pi * 2 ** 2 * 10  # D4 through the 10 mm block


class PatternToolTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="pattern-tool-tests-")
        self.core = Controller()
        self.state = self.core.dispatch({"op": "new", "name": "Pattern tools"})["result"]

    def tearDown(self):
        for name in set(App.listDocuments()) - self.names:
            App.closeDocument(name)
        self.core.observer.close()

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def request(self, op, **args):
        return self.core.dispatch({"op": op, "document_id": self.state["document_id"],
                                   "expected_revision": self.state["revision"], **args})

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
        self.assertEqual(self.invariant(), before)
        return response["error"]

    def volumes(self):
        return {studio.part_id(obj): obj.Shape.Volume for obj in studio.current_parts(self.doc)}

    def assert_volumes(self, expected):
        actual = self.volumes()
        self.assertEqual(set(actual), set(expected))
        for key, volume in expected.items():
            self.assertAlmostEqual(actual[key], volume, places=5)

    def block(self):
        self.call("sketch_rectangle", id="BodyProfile", body="Body", x=-20, y=-20, width=40, height=40)
        self.call("pad", id="BodyExtrude", profile="BodyProfile", body="Body", length=10, operation="new")

    def cutter(self, name="Cutter", x=12, y=0, length=20):
        self.call("create_body", id=name, name=name)
        self.call("sketch_circle", id=name + "Profile", body=name, x=x, y=y, diameter=4)
        self.call("pad", id=name + "Extrude", profile=name + "Profile", body=name, length=length, operation="new")
        return name

    def orphans(self):
        return self.request("orphan_helpers")["result"]["groups"]

    def hole_centers(self):
        shape = studio.current_part(self.doc, "Body").Shape
        return {(round(face.Surface.Center.x, 6) + 0.0, round(face.Surface.Center.y, 6) + 0.0)
                for face in shape.Faces if face.Surface.__class__.__name__ == "Cylinder"}

    def scope_errors(self):
        return [error for error in self.state["build_errors"] if "merge_scope" in str(error.get("code", ""))]

    def circular_holes(self, **extra):
        self.block()
        self.cutter()
        return self.call("circular_pattern_parts", id="Holes", parts=["Cutter"],
                         axis={"origin": [0, 0, 0], "direction": [0, 0, 1]}, angle="360 deg", count=3,
                         operation="remove", **extra)

    def test_omitted_include_source_keeps_the_source_tool(self):
        self.circular_holes()
        self.assert_volumes({"Body": BLOCK - 2 * HOLE, "Cutter": HOLE * 2})
        self.assertNotIn("KurtShapePatternSourceParts", self.doc.Holes.PropertiesList)
        self.assertNotIn("include_source", self.doc.Holes.KurtShapeStudioOperation)

    def test_circular_remove_with_source_cuts_three_holes_in_one_undo_step(self):
        self.block()
        self.cutter()
        undo_count = len(self.doc.UndoNames)
        revision = self.state["revision"]
        self.call("circular_pattern_parts", id="Holes", parts=["Cutter"],
                  axis={"origin": [0, 0, 0], "direction": [0, 0, 1]}, angle="360 deg", count=3,
                  operation="remove", include_source=True)
        self.assertEqual(len(self.doc.UndoNames), undo_count + 1)
        self.assertNotEqual(self.state["revision"], revision)
        self.assert_volumes({"Body": BLOCK - 3 * HOLE})
        self.assertEqual([part["id"] for part in self.state["studio"]["parts"]], ["Body"])
        self.assertEqual(self.hole_centers(), {(12.0, 0.0), (-6.0, 10.392305), (-6.0, -10.392305)})
        self.assertEqual(list(self.doc.Holes.KurtShapeMergePartIds), ["Body"])
        self.assertEqual(list(self.doc.Holes.KurtShapePatternSourceParts), ["Cutter"])
        self.assertEqual(set(self.doc.Holes.KurtShapeConsumedParts), {"Body", "Cutter"})
        self.assertEqual(self.scope_errors(), [])
        self.call("undo")
        self.assert_volumes({"Body": BLOCK, "Cutter": HOLE * 2})
        self.assertIsNone(self.doc.getObject("Holes"))
        self.call("redo")
        self.assert_volumes({"Body": BLOCK - 3 * HOLE})
        # The source tool stays live: shortening it shallows all three holes.
        self.call("set_parameter", feature="CutterExtrude", parameter="Length", value=5)
        self.assert_volumes({"Body": BLOCK - 3 * HOLE / 2})
        self.call("rebuild")
        self.assertEqual(self.scope_errors(), [])
        self.assertEqual(self.state["build_status"], "valid", self.state["build_errors"])
        self.assert_volumes({"Body": BLOCK - 3 * HOLE / 2})

    def test_linear_add_with_source_fuses_every_boss(self):
        self.block()
        self.call("create_body", id="Boss", name="Boss")
        self.call("sketch_rectangle", id="BossProfile", body="Boss", x=-18, y=-2, width=4, height=4)
        self.call("pad", id="BossExtrude", profile="BossProfile", body="Boss", length=15, operation="new")
        self.call("linear_pattern_parts", id="Bosses", parts=["Boss"], direction=[1, 0, 0], spacing=10,
                  count=3, operation="add", include_source=True)
        self.assert_volumes({"Body": BLOCK + 3 * 4 * 4 * 5})
        self.assertEqual(self.scope_errors(), [])
        # A source that would not touch the scope is never discarded.
        self.call("undo")
        self.call("create_body", id="Far", name="Far")
        self.call("sketch_rectangle", id="FarProfile", body="Far", x=-40, y=-2, width=4, height=4)
        self.call("pad", id="FarExtrude", profile="FarProfile", body="Far", length=15, operation="new")
        error = self.reject("empty_merge_scope", "linear_pattern_parts", id="FarBosses", parts=["Far"],
                            direction=[1, 0, 0], spacing=22, count=2, operation="add", include_source=True,
                            merge_scope=["Body"])
        self.assertEqual(error["parts"], ["Far"])

    def test_mirror_remove_with_source(self):
        self.block()
        self.cutter(x=10)
        self.call("mirror_parts", id="Mirrored", parts=["Cutter"], origin=[0, 0, 0], normal=[1, 0, 0],
                  operation="remove", merge_scope=["Body"], include_source=True)
        self.assert_volumes({"Body": BLOCK - 2 * HOLE})
        self.assertEqual(self.hole_centers(), {(-10.0, 0.0), (10.0, 0.0)})

    def test_delete_and_rollback_restore_the_source_part(self):
        self.circular_holes(include_source=True)
        position = self.state["studio"]["feature_order"].index("Holes")
        self.call("rollback", index=position)
        self.assert_volumes({"Body": BLOCK, "Cutter": HOLE * 2})
        self.call("rollback", index=len(self.state["studio"]["feature_order"]))
        self.assert_volumes({"Body": BLOCK - 3 * HOLE})
        before = {obj.Name for obj in self.doc.Objects}
        plan = self.core.delete_features_plan(self.doc, ["Holes"])
        self.assertEqual(plan["selected"], ["Holes"])
        self.assertEqual(plan["dependents"], [])
        self.call("delete_features", features=["Holes"])
        self.assertEqual(self.orphans(), [])
        self.assert_volumes({"Body": BLOCK, "Cutter": HOLE * 2})
        self.assertTrue(set(plan["removed"]) <= before)
        self.assertFalse({obj.Name for obj in self.doc.Objects} & set(plan["removed"]))
        self.call("undo")
        self.assert_volumes({"Body": BLOCK - 3 * HOLE})
        self.call("redo")
        self.assert_volumes({"Body": BLOCK, "Cutter": HOLE * 2})

    def test_consumed_copies_belong_to_their_pattern(self):
        # Remove without include_source: the copies were untagged and blocked deletion.
        self.circular_holes()
        self.assertEqual(self.doc.HolesPart.KurtShapeOperationOwner, "Holes")
        self.call("delete_features", features=["Holes"])
        self.assertEqual(self.orphans(), [])
        self.assert_volumes({"Body": BLOCK, "Cutter": HOLE * 2})
        # Files from before the tag still resolve their recorded copies.
        self.call("undo")
        for name in self.doc.Holes.KurtShapePatternToolParts:
            self.doc.getObject(name).removeProperty("KurtShapeOperationOwner")
        members = {obj.Name for obj in studio.operation_members(self.doc, "Holes")}
        self.assertTrue(set(self.doc.Holes.KurtShapePatternToolParts) <= members)

    def test_saved_include_source_pattern_reopens_rebuilds_and_deletes(self):
        import tempfile
        self.circular_holes(include_source=True)
        with tempfile.TemporaryDirectory(prefix="pattern-source-", dir=support.TEST_TMP, ignore_cleanup_errors=True) as temporary:
            path = Path(temporary) / "holes.FCStd"
            self.call("save", path=str(path))
            App.closeDocument(self.doc.Name)
            reopened = self.core.dispatch({"op": "open", "path": str(path)})
            self.assertTrue(reopened["ok"], reopened)
            self.state = reopened["result"]
            self.assert_volumes({"Body": BLOCK - 3 * HOLE})
            self.call("rebuild")
            self.assertEqual(self.state["build_status"], "valid", self.state["build_errors"])
            self.assertEqual(self.scope_errors(), [])
            self.assert_volumes({"Body": BLOCK - 3 * HOLE})
            self.call("delete_features", features=["Holes"])
            self.assertEqual(self.orphans(), [])
            self.assert_volumes({"Body": BLOCK, "Cutter": HOLE * 2})

    def test_add_with_source_rejects_copies_that_touch_nothing(self):
        self.block()
        self.call("create_body", id="Boss", name="Boss")
        self.call("sketch_rectangle", id="BossProfile", body="Boss", x=-18, y=-2, width=4, height=4)
        self.call("pad", id="BossExtrude", profile="BossProfile", body="Boss", length=15, operation="new")
        # Spacing 48: the source touches the block, both copies land beyond it.
        error = self.reject("empty_merge_scope", "linear_pattern_parts", id="Bosses", parts=["Boss"],
                            direction=[1, 0, 0], spacing=48, count=3, operation="add", include_source=True)
        self.assertEqual(len(error["copies"]), 2)

    def test_include_source_with_intersect_rejects(self):
        self.block()
        self.call("create_body", id="Slab", name="Slab")
        self.call("sketch_rectangle", id="SlabProfile", body="Slab", x=-5, y=-25, width=30, height=50)
        self.call("pad", id="SlabExtrude", profile="SlabProfile", body="Slab", length=5, operation="new")
        self.reject("invalid_argument", "mirror_parts", id="Trimmed", parts=["Slab"], origin=[0, 0, 0],
                    normal=[1, 0, 0], operation="intersect", merge_scope=["Body"], include_source=True)

    def test_rejections_leave_revision_and_history(self):
        self.block()
        self.cutter()
        common = dict(parts=["Cutter"], axis={"origin": [0, 0, 0], "direction": [0, 0, 1]},
                      angle="360 deg", count=3)
        self.reject("invalid_argument", "circular_pattern_parts", id="Holes", operation="remove",
                    include_source=True, merge_scope=["Body", "Cutter"], **common)
        # The source's current Body name names the same part.
        self.reject("invalid_argument", "circular_pattern_parts", id="Holes", operation="remove",
                    include_source=True, merge_scope=["CutterExtrudeToolBody"], **common)
        self.reject("invalid_argument", "circular_pattern_parts", id="Holes", operation="new",
                    include_source=True, **common)
        self.reject("invalid_argument", "circular_pattern_parts", id="Holes", include_source=True, **common)
        self.reject("invalid_argument", "circular_pattern_parts", id="Holes", operation="remove",
                    include_source="yes", **common)
        self.reject("invalid_argument", "mirror_parts", id="Mirrored", parts=["Cutter"], operation="new",
                    include_source=True)
        self.reject("unknown_argument", "transform_part", id="Moved", part="Cutter", include_source=True)
        # Auto scope without any part but the sources has no target.
        self.call("delete_features", features=["BodyExtrude"])
        self.reject("empty_merge_scope", "circular_pattern_parts", id="Holes", operation="remove",
                    include_source=True, **common)
        # include_source:false with New is the default behaviour.
        self.call("circular_pattern_parts", id="Copies", operation="new", include_source=False, **common)
        self.assertEqual(len(self.volumes()), 3)


if __name__ == "__main__":
    unittest.main()
