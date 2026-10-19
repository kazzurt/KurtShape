"""Exact U2 queries with bounded, object-local native geometry work."""
from pathlib import Path
import json
import math
import sys
import unittest
from unittest.mock import patch

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
from kurtshape.core import Controller, OperationError
from kurtshape import geometry, selectors, studio
from native_validation_snapshot import snapshot_document
from test_build_status import no_kernel_checks


class GeometryQueryTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="geometry-query-session-")
        self.core = Controller()
        response = self.core.dispatch({"op": "new", "name": "Geometry query consequences", "measure": False})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]

    def tearDown(self):
        self.core.close()
        for name in set(App.listDocuments()) - self.names:
            App.closeDocument(name)

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def request(self, op, **args):
        return self.core.dispatch({"op": op, "document_id": self.state["document_id"],
                                   "expected_revision": self.state["revision"], "measure": False, **args})

    def call(self, op, **args):
        response = self.request(op, **args)
        self.assertTrue(response["ok"], response)
        if "document_id" in response["result"]:
            self.state = response["result"]
        return response["result"]

    def fresh(self):
        response = self.core.dispatch({"op": "inspect", "document_id": self.state["document_id"], "measure": False})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]

    def new_document(self):
        response = self.core.dispatch({"op": "new", "name": "Independent geometry query phase", "measure": False})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]

    def raw_box(self, name, x=0):
        obj = self.doc.addObject("Part::Feature", name)
        obj.Shape = Part.makeBox(2, 2, 2, App.Vector(x, 0, 0))
        return obj

    def pad(self, body="Body", x=0, studio_operation=False):
        if body != "Body":
            self.call("create_body", id=body)
        self.call("sketch_rectangle", id=body + "Profile", body=body, x=x, width=10, height=10)
        self.call("pad", id=body + "Pad", profile=body + "Profile", body=body, length=10,
                  **({"operation": "new"} if studio_operation else {}))

    def test_scope_boxes_touching_cache_and_local_change_undo(self):
        first, far = self.raw_box("First"), self.raw_box("Far", 20)
        near = self.raw_box("Near", 2 + 5e-8)
        third, fourth = self.raw_box("Third", 40), self.raw_box("Fourth", 41)
        self.doc.recompute()
        self.fresh()
        before = snapshot_document(self.doc, self.core)["strict"]
        with patch.object(geometry, "check_shape", side_effect=AssertionError("Scope queries must not check geometry")), \
                patch.object(geometry, "common_volume", wraps=geometry.common_volume) as common, \
                patch.object(geometry, "distance", wraps=geometry.distance) as distance:
            self.assertFalse(studio._pair_matches(self.doc, first, far, "add"))
            self.assertEqual((common.call_count, distance.call_count), (0, 0))
            self.assertTrue(studio._pair_matches(self.doc, first, near, "add"))
            self.assertFalse(studio._pair_matches(self.doc, first, near, "remove"))
            self.assertEqual((common.call_count, distance.call_count), (1, 1))
            self.assertTrue(studio._pair_matches(self.doc, third, fourth, "remove"))
            self.assertEqual((common.call_count, distance.call_count), (2, 1))
            for iteration in range(3):
                self.assertTrue(studio._pair_matches(self.doc, first, near, "add"))
                self.assertTrue(studio._pair_matches(self.doc, third, fourth, "remove"))
            self.assertEqual((common.call_count, distance.call_count), (2, 1))
            self.assertEqual(snapshot_document(self.doc, self.core)["strict"], before)
            self.doc.openTransaction("Move one query source")
            near.Placement = App.Placement(App.Vector(-1, 0, 0), App.Rotation())
            self.doc.recompute()
            self.doc.commitTransaction()
            self.assertTrue(studio._pair_matches(self.doc, first, near, "remove"))
            self.assertTrue(studio._pair_matches(self.doc, third, fourth, "remove"))
            self.assertEqual((common.call_count, distance.call_count), (3, 1))
            self.doc.undo()
            self.doc.recompute()
            self.assertFalse(studio._pair_matches(self.doc, first, near, "remove"))
            self.assertTrue(studio._pair_matches(self.doc, first, near, "add"))
            self.assertTrue(studio._pair_matches(self.doc, third, fourth, "remove"))
            self.assertEqual((common.call_count, distance.call_count), (4, 2))

    def test_closest_prunes_far_rows_preserves_ties_and_world_frames(self):
        self.pad()
        self.pad("Other", x=50)
        caps = {"kind": "parallel", "direction": [0, 0, 1],
                "query": {"kind": "geometry", "geometry": "plane",
                          "query": {"kind": "owned_by", "part": "Body"}}}
        query = {"kind": "closest", "point": [5, 5, 5], "query": caps}
        before = snapshot_document(self.doc, self.core)["strict"]
        with patch.object(geometry, "distance", wraps=geometry.distance) as distance:
            tied = selectors.resolve(self.doc, query)
            self.assertEqual(len(tied), 2)
            self.assertEqual(distance.call_count, 2)
            self.assertEqual(selectors.resolve(self.doc, query), tied)
            self.assertEqual(distance.call_count, 2)
            with self.assertRaises(OperationError) as caught:
                selectors.native_reference(self.doc, query)
            self.assertEqual(caught.exception.code, "ambiguous_reference")
            self.assertEqual(distance.call_count, 2)
            query["point"] = [5, 5, 12]
            top = selectors.resolve(self.doc, query)
            self.assertEqual(len(top), 1)
            self.assertAlmostEqual(top[0]["summary"]["center_mm"][2], 10)
            self.assertEqual(distance.call_count, 3)
            self.assertEqual(snapshot_document(self.doc, self.core)["strict"], before)
            self.doc.Body.Placement = App.Placement(App.Vector(30, 40, 0), App.Rotation(App.Vector(0, 0, 1), 90))
            self.doc.recompute()
            query["point"] = [25, 45, 12]
            moved = selectors.resolve(self.doc, query)
            self.assertEqual(len(moved), 1)
            self.assertEqual(moved[0]["feature"], top[0]["feature"])
            self.assertAlmostEqual(moved[0]["summary"]["center_mm"][0], 25)
            self.assertAlmostEqual(moved[0]["summary"]["center_mm"][1], 45)
            self.assertEqual(distance.call_count, 4)
            self.doc.OtherPad.Length = 12
            self.doc.recompute()
            self.assertEqual(selectors.resolve(self.doc, query), moved)
            self.assertEqual(distance.call_count, 4)

    def test_derived_caps_cache_exact_overlap_and_reject_disjoint_boxes(self):
        source = self.raw_box("CapSource")
        distant = self.raw_box("DistantCapSource", 20)
        self.doc.recompute()
        context = selectors._Context(self.doc)
        face = source.Shape.Faces[0]
        distant_face = distant.Shape.Faces[0]
        row = {"feature": source.Name, "subelement": "Face1", "entity_type": "face",
               "part": source.Name, "_object": source, "_shape": face}
        far_row = {**row, "feature": distant.Name, "_object": distant, "_shape": distant_face}
        before = snapshot_document(self.doc, self.core)["strict"]
        with patch.object(geometry, "scalar", wraps=geometry.scalar) as scalar:
            selected = selectors._on_cap_shapes(context, [row, far_row], face, distant_face, "start", (source, distant), ("derived fixture",))
            self.assertEqual(selected, [row])
            self.assertEqual(scalar.call_count, 2)
            self.assertEqual(selectors._on_cap_shapes(context, [row, far_row], face, distant_face, "start", (source, distant), ("derived fixture",)), selected)
            self.assertEqual(scalar.call_count, 2)
            self.assertEqual(selectors._on_cap_shapes(context, [row, far_row], face, distant_face, "side", (source, distant), ("derived fixture",)), [])
            self.assertEqual(scalar.call_count, 2)
            self.assertEqual(snapshot_document(self.doc, self.core)["strict"], before)
            source.Shape = Part.makeBox(3, 2, 2)
            self.doc.recompute()
            row["_shape"] = source.Shape.Faces[0]
            changed = selectors._on_cap_shapes(context, [row], row["_shape"], distant_face, "start", (source, distant), ("derived fixture",))
            self.assertEqual(changed, [row])
            self.assertEqual(scalar.call_count, 3)

    def test_idle_scope_and_native_reference_diagnostics_never_resolve_pairs(self):
        self.pad(studio_operation=True)
        self.call("sketch_rectangle", id="CutProfile", body="Body", x=8, y=4, width=5, height=2)
        self.call("pocket", id="AutoCut", profile="CutProfile", through_all=True,
                  operation="remove", merge_scope="auto")
        before = snapshot_document(self.doc, self.core)["strict"]
        with patch.object(geometry, "common_volume", side_effect=AssertionError("Idle must not intersect scopes")), \
                patch.object(geometry, "distance", side_effect=AssertionError("Idle must not measure pairs")), \
                patch.object(selectors, "resolve", side_effect=AssertionError("Idle must not evaluate queries")):
            for iteration in range(3):
                self.assertEqual(studio.validation_errors(self.doc), [])
                self.assertEqual(selectors.reference_errors(self.doc), [])
                self.call("inspect")
            self.assertEqual(snapshot_document(self.doc, self.core)["strict"], before)
            self.doc.CutProfile.MapMode = "Deactivated"
            self.doc.CutProfile.Placement = App.Placement(App.Vector(20, 0, 0), App.Rotation())
            pending = studio.validation_errors(self.doc)
            self.assertTrue(any(row.get("code") == "auto_merge_scope_pending" for row in pending), pending)
        self.doc.recompute()
        self.fresh()
        self.assertTrue(any(row.get("code") == "auto_merge_scope_changed" for row in studio.validation_errors(self.doc)))
        self.new_document()
        self.pad()
        self.call("create_sketch", id="Supported", support={"kind": "created_by", "feature": "BodyPad", "cap": "end"})
        self.doc.Supported.AttachmentSupport = (self.doc.BodyPad, ["Face5"])
        native_input = self.doc.Supported.AttachmentSupport
        health = self.doc.Supported.QueryHealth
        with patch.object(selectors, "resolve", side_effect=AssertionError("Cheap native divergence must not resolve")):
            errors = selectors.reference_errors(self.doc)
            self.assertTrue(any(row.get("code") == "pending_selector_resolution" for row in errors), errors)
            self.assertEqual(self.doc.Supported.AttachmentSupport, native_input)
            self.assertEqual(self.doc.Supported.QueryHealth, health)
        self.doc.recompute()
        self.fresh()
        self.assertEqual(self.state["build_status"], "failed")
        self.assertEqual(json.loads(self.doc.Supported.QueryHealth)[0]["status"], "missing")
        self.call("rebuild")
        self.assertEqual(self.state["build_status"], "valid")
        self.assertEqual(selectors.reference_errors(self.doc), [])

    def test_pair_name_reuse_and_standalone_exact_results(self):
        first, second = self.raw_box("First"), self.raw_box("Reusable", 1)
        self.doc.recompute()
        with patch.object(geometry, "common_volume", wraps=geometry.common_volume) as common:
            self.assertTrue(studio._pair_matches(self.doc, first, second, "remove"))
            self.assertTrue(studio._pair_matches(self.doc, first, second, "remove"))
            self.assertEqual(common.call_count, 1)
            old_version = self.core.observer.version(self.doc, second.Name)
            self.doc.removeObject(second.Name)
            recreated = self.raw_box("Reusable", 20)
            self.doc.recompute()
            self.assertEqual(recreated.Name, "Reusable")
            self.assertGreater(self.core.observer.version(self.doc, recreated.Name), old_version)
            self.assertFalse(studio._pair_matches(self.doc, first, recreated, "remove"))
            recreated.Shape = Part.makeBox(2, 2, 2, App.Vector(1, 0, 0))
            self.doc.recompute()
            self.assertTrue(studio._pair_matches(self.doc, first, recreated, "remove"))
            self.assertEqual(common.call_count, 2)
            with patch.object(geometry, "provider", return_value=None):
                self.assertTrue(studio._pair_matches(self.doc, first, recreated, "remove"))
                self.assertTrue(studio._pair_matches(self.doc, first, recreated, "remove"))
            self.assertEqual(common.call_count, 4)

    def test_interactive_reference_and_studio_operations_do_not_check(self):
        with no_kernel_checks(self) as check:
            self.pad()
            volume = self.doc.Body.Shape.Volume
            for op, field, size in (("fillet", "radius", .2), ("chamfer", "size", .2)):
                self.call(op, id="ReferenceTool", edges=[{"feature": "BodyPad", "subelement": "Edge1"}], **{field: size})
                self.assertLess(self.doc.Body.Shape.Volume, volume)
                self.call("undo")
                self.assertAlmostEqual(self.doc.Body.Shape.Volume, volume)
            top = next("Face" + str(index + 1) for index, face in enumerate(self.doc.BodyPad.Shape.Faces)
                       if face.normalAt(0, 0).z > .999)
            self.call("shell", id="Shell", faces=[{"feature": "BodyPad", "subelement": top}], thickness=1, reversed=True)
            self.assertLess(self.doc.Body.Shape.Volume, volume)
            self.call("undo")
            rejected = self.request("fillet", id="Impossible", edges=[{"feature": "BodyPad", "subelement": "Edge1"}], radius=1000)
            self.assertFalse(rejected["ok"], rejected)
            self.assertEqual(rejected["error"]["code"], "build_failed")
            self.assertIsNone(self.doc.getObject("Impossible"))
            self.assertAlmostEqual(self.doc.Body.Shape.Volume, volume)
            self.call("create_sketch", id="Projected")
            edge = next("Edge" + str(index + 1) for index, item in enumerate(self.doc.BodyPad.Shape.Edges)
                        if item.BoundBox.ZLength < 1e-7 and item.BoundBox.ZMin < 1e-7 and item.BoundBox.XLength > 9)
            self.call("project_geometry", sketch="Projected", references=[{"feature": "BodyPad", "subelement": edge}])
            self.assertEqual(len(self.doc.Projected.ExternalGeometry), 1)
            self.call("undo")
            self.assertEqual(len(self.doc.Projected.ExternalGeometry), 0)
            self.pad("Stop", x=50)
            self.call("set_parameter", feature="StopPad", parameter="Length", value=15)
            self.call("sketch_circle", id="Raised", body="Body", x=5, y=5, diameter=2,
                      support={"feature": "BodyPad", "subelement": top})
            self.call("pad", id="ToFace", profile="Raised", body="Body", end_type="up_to_face",
                      up_to_face={"feature": "StopPad", "subelement": top})
            self.assertAlmostEqual(self.doc.Body.Shape.BoundBox.ZMax, 15)
            self.new_document()
            self.pad()
            volume = self.doc.Body.Shape.Volume
            self.call("transform_part", id="Copy", part="Body", translation=[30, 0, 0], copy=True)
            self.call("linear_pattern_parts", id="Pattern", parts=["Body"], direction=[0, 1, 0], spacing=20, count=2)
            self.call("mirror_parts", id="Mirror", parts=["Body"], origin=[0, 0, 0], normal=[1, 0, 0])
            self.call("circular_pattern_parts", id="Circular", parts=["Body"], angle="180 deg", count=2)
            self.assertEqual(len(studio.current_parts(self.doc)), 5)
            self.call("delete_part", id="Delete", part="CopyPart")
            self.assertEqual(len(studio.current_parts(self.doc)), 4)
            self.call("undo")
            self.assertEqual(len(studio.current_parts(self.doc)), 5)
            self.call("split_part", id="Split", part="Body", plane={"origin": [5, 0, 0], "normal": [1, 0, 0]})
            self.assertEqual(len(studio.current_parts(self.doc)), 6)
            self.call("undo")
            self.assertEqual(len(studio.current_parts(self.doc)), 5)
            self.pad("Tool", x=8, studio_operation=True)
            self.call("boolean_parts", id="Remove", targets=["Body"], tools=["Tool"], kind="subtract", keep_tools=True)
            self.assertAlmostEqual(studio.current_part(self.doc, "Body").Shape.Volume, 800)
            self.call("undo")
            self.assertAlmostEqual(studio.current_part(self.doc, "Body").Shape.Volume, volume)
            self.call("sketch_rectangle", id="AddProfile", body="Body", x=8, width=5, height=10)
        # Contract 3.1: accepting a studio Add/Remove/Intersect checks each result once.
        with patch.object(geometry, "check_shape", wraps=geometry.check_shape) as result_check:
            self.call("pad", id="AutoAdd", profile="AddProfile", length=10, operation="add", merge_scope=["Body"])
        self.assertEqual(result_check.call_count, 1)
        self.assertEqual(self.state["result_report"]["geometry_check"], "valid")
        self.assertAlmostEqual(studio.current_part(self.doc, "Body").Shape.Volume, 1300)
        with no_kernel_checks(self) as check:
            self.call("undo")
            self.assertAlmostEqual(studio.current_part(self.doc, "Body").Shape.Volume, volume)
            self.new_document()
            self.call("sketch_rectangle", id="RevolveProfile", plane="XZ", x=3, width=2, height=5)
            self.call("revolve", id="Revolve", profile="RevolveProfile", angle="360 deg", operation="new")
            self.assertAlmostEqual(sum(body.Shape.Volume for body in studio.current_parts(self.doc)), 80 * math.pi)
            self.call("create_body", id="SweepBody")
            self.call("sketch_circle", id="SweepProfile", body="SweepBody", plane="YZ", x=0, y=0, diameter=2)
            self.call("create_sketch", id="SweepPath", body="SweepBody")
            self.call("add_line", sketch="SweepPath", x1=0, y1=0, x2=10, y2=0, body="SweepBody")
            self.call("sweep", id="Sweep", profile="SweepProfile", path="SweepPath", operation="new")
            self.assertAlmostEqual(studio.current_part(self.doc, "SweepBody").Shape.Volume, 10 * math.pi)
            self.call("create_body", id="LoftBody")
            self.call("sketch_circle", id="LoftStart", body="LoftBody", x=0, y=0, diameter=4)
            self.call("sketch_circle", id="LoftEnd", body="LoftBody", x=0, y=0, diameter=4)
            self.doc.LoftEnd.MapMode = "Deactivated"
            self.doc.LoftEnd.Placement.Base = App.Vector(0, 0, 10)
            self.doc.recompute()
            self.fresh()
            self.call("loft", id="Loft", sections=["LoftStart", "LoftEnd"], operation="new")
            self.assertAlmostEqual(studio.current_part(self.doc, "LoftBody").Shape.Volume, 40 * math.pi)
            self.assertEqual(check.call_count, 0)
        self.assertTrue(all(body.Shape.isValid() for doc in self.core.documents.values() for body in studio.current_parts(doc)))


if __name__ == "__main__":
    unittest.main()
