"""Nominal envelope checks and fail-closed delivery verification."""
from pathlib import Path
import sys
import unittest
import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
from kurtshape.core import Controller, intent_signature
from kurtshape import clearance
from kurtshape.delivery_validation import compare_shapes, validate_delivery


class ClearanceTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="clearance-")
        self.core = Controller()
        self.state = self.core.dispatch({"op": "new", "name": "Envelope checks", "measure": False})["result"]
        self.doc = self.core.documents[self.state["document_id"]]

    def tearDown(self):
        self.core.close()
        for name in set(App.listDocuments()) - self.names:
            App.closeDocument(name)

    def part(self, name, shape):
        obj = self.doc.addObject("Part::Feature", name)
        obj.Shape = shape
        self.doc.recompute()
        self.core.dispatch({"op": "inspect", "document_id": self.state["document_id"], "measure": False})
        return obj

    def query(self, **args):
        return self.core.dispatch({"op": "check_clearance", "document_id": self.state["document_id"], **args})

    @staticmethod
    def cylinder(radius=1, length=5):
        return {"id": "tool", "kind": "cylinder", "origin_mm": [0, 0, 0], "axis": [0, 0, 1],
                "radius_mm": radius, "length_mm": length}

    def test_minimum_distance_limiting_component_and_no_mutation(self):
        self.part("HexHead", Part.makeBox(2, 2, 2, App.Vector(2.468, -1, 0)))
        self.part("FarAway", Part.makeBox(2, 2, 2, App.Vector(20, -1, 0)))
        before = intent_signature(self.doc), self.doc.UndoCount, self.core._meta(self.doc).Revision
        result = self.query(envelopes=[self.cylinder()], minimum_clearance_mm=1.4)
        self.assertTrue(result["ok"], result)
        report = result["result"]
        self.assertTrue(report["passed"])
        self.assertEqual(report["limiting"][0]["component"], "HexHead")
        self.assertAlmostEqual(report["limiting"][0]["distance_mm"], 1.468, places=6)
        self.assertEqual(before, (intent_signature(self.doc), self.doc.UndoCount, self.core._meta(self.doc).Revision))
        self.assertFalse(self.query(envelopes=[self.cylinder()], minimum_clearance_mm=1.5)["result"]["passed"])

    def test_continuous_annulus_detects_interference(self):
        self.part("Fixture", Part.makeBox(1, 1, 1, App.Vector(3, 3, 1)))
        spec = {"id": "sweep", "kind": "annulus", "origin_mm": [0, 0, 0], "axis": [0, 0, 1],
                "inner_radius_mm": 4, "outer_radius_mm": 6, "length_mm": 5}
        result = self.query(envelopes=[spec])["result"]
        self.assertFalse(result["passed"])
        self.assertGreater(result["pairs"][0]["overlap_mm3"], 0)

    def test_thread_allowance_is_pair_region_and_volume_bounded(self):
        self.part("TappedBody", Part.makeCylinder(3, 5).cut(Part.makeCylinder(0.8, 5)))
        self.part("Unintended", Part.makeBox(1, 1, 1, App.Vector(-0.5, -0.5, 2)))
        region = self.cylinder(radius=1.1)
        region.pop("id")
        allowance = {"envelope": "tool", "component": "TappedBody", "reason": "thread_envelope",
                     "region": region, "max_volume_mm3": 10}
        request = {"envelopes": [self.cylinder()], "allowed_overlaps": [allowance]}
        report = self.query(**request)["result"]
        self.assertFalse(report["passed"])
        self.assertEqual([row["status"] for row in report["pairs"]], ["intended_thread_overlap", "interference"])
        request["components"] = ["TappedBody"]
        self.assertTrue(self.query(**request)["result"]["passed"])
        allowance["region"]["length_mm"] = 2
        report = self.query(**request)["result"]
        self.assertFalse(report["passed"])
        self.assertGreater(report["pairs"][0]["outside_allowed_region_mm3"], 0)
        allowance["region"]["length_mm"] = 5
        allowance["max_volume_mm3"] = 1
        self.assertFalse(self.query(**request)["result"]["passed"])

    def test_pin_end_zero_four_mm_rotated_axis_and_finite_range(self):
        stop = self.part("SocketEnd", Part.makeBox(10, 10, 2, App.Vector(-5, -5, 8)))
        probe = {"tip_mm": [0, 0, 8], "axis": [0, 0, 1], "radius_mm": 3, "max_distance_mm": 10}
        report = self.query(axis_probe=probe, minimum_clearance_mm=1)["result"]
        self.assertFalse(report["passed"])
        self.assertAlmostEqual(report["axis_probe"]["distance_mm"], 0)
        probe["tip_mm"] = [0, 0, 4]
        report = self.query(axis_probe=probe, minimum_clearance_mm=1)["result"]
        self.assertTrue(report["passed"])
        self.assertAlmostEqual(report["axis_probe"]["distance_mm"], 4)
        probe["max_distance_mm"] = 0.5
        report = self.query(axis_probe=probe, minimum_clearance_mm=1)["result"]
        self.assertFalse(report["passed"])
        self.assertIsNone(report["axis_probe"]["distance_mm"])
        self.assertEqual(report["axis_probe"]["status"], "range_insufficient")
        stop.Placement = App.Placement(App.Vector(), App.Rotation(App.Vector(0, 0, 1), App.Vector(1, 0, 0)))
        self.doc.recompute()
        probe.update(tip_mm=[4, 0, 0], axis=[1, 0, 0], max_distance_mm=10)
        report = clearance.check(self.doc, {"axis_probe": probe, "components": ["SocketEnd"]})
        self.assertAlmostEqual(report["axis_probe"]["distance_mm"], 4)

    def test_invalid_envelopes_fail_closed(self):
        self.part("Block", Part.makeBox(2, 2, 2))
        self.assertFalse(self.query(envelopes=[])["ok"])
        self.assertFalse(self.query(envelopes=[self.cylinder()], components=["Missing"])["ok"])
        bad = self.cylinder()
        bad["axis"] = [0, 0, 0]
        self.assertEqual(self.query(envelopes=[bad])["error"]["code"], "invalid_clearance")
        bad["axis"] = [0, 0, 1]
        bad["ignore_collisions"] = True
        self.assertEqual(self.query(envelopes=[bad])["error"]["code"], "invalid_clearance")

    def test_nested_native_container_world_frame_for_targets_envelopes_and_probe(self):
        outer = self.doc.addObject("App::Part", "Outer")
        inner = self.doc.addObject("App::Part", "Inner")
        outer.addObject(inner)
        block = self.doc.addObject("PartDesign::Body", "Nested")
        feature = block.newObject("PartDesign::Feature", "NestedSolid")
        feature.Shape = Part.makeBox(2, 2, 2)
        inner.addObject(block)
        outer.Placement = App.Placement(App.Vector(10, 20, 30), App.Rotation(App.Vector(0, 0, 1), 90))
        inner.Placement = App.Placement(App.Vector(2, 0, 0), App.Rotation())
        block.Placement = App.Placement(App.Vector(0, 0, 1), App.Rotation())
        self.doc.recompute()
        envelope = self.cylinder(length=2)
        envelope["origin_mm"] = [12, 23, 31]
        report = self.query(envelopes=[envelope], components=["Nested"])
        self.assertTrue(report["ok"], report)
        self.assertAlmostEqual(report["result"]["pairs"][0]["distance_mm"], 1)
        self.part("Obstacle", Part.makeBox(2, 2, 2, App.Vector(13, 22, 31)))
        report = self.query(envelopes=[{"id": "nested", "kind": "component", "component": "Nested"}], components=["Obstacle"])
        self.assertTrue(report["ok"], report)
        self.assertAlmostEqual(report["result"]["pairs"][0]["distance_mm"], 3)
        report = self.query(components=["Nested"], axis_probe={"tip_mm": [9, 23, 27], "axis": [0, 0, 1],
                            "radius_mm": 0.5, "max_distance_mm": 10})
        self.assertTrue(report["ok"], report)
        self.assertAlmostEqual(report["result"]["axis_probe"]["distance_mm"], 4)

    def test_invalid_legacy_solid_rejects_targets_envelopes_and_boolean_results(self):
        broken = Part.makeSolid(Part.makeShell(Part.makeBox(10, 10, 10).Faces[:-1]))
        self.assertFalse(broken.isValid())
        self.part("Broken", broken)
        self.part("Good", Part.makeBox(2, 2, 2, App.Vector(100, 0, 0)))
        envelope = self.cylinder()
        envelope["origin_mm"] = [200, 0, 0]
        response = self.query(envelopes=[envelope], components=["Broken"])
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "invalid_clearance_geometry")
        response = self.query(envelopes=[{"id": "broken", "kind": "component", "component": "Broken"}], components=["Good"])
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "invalid_clearance_geometry")
        # Inject an invalid native Boolean result to ensure its validity gate is
        # independent of the valid-input preflight.
        class KernelResult:
            def common(self, other):
                return broken
        with self.assertRaisesRegex(Exception, "valid BRep"):
            clearance._boolean(KernelResult(), Part.makeBox(1, 1, 1), "common", "invalid-result regression")


class DeliveryValidationTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="delivery-validation-")
        self.core = Controller()
        self.state = None

    def tearDown(self):
        self.core.close()
        for name in set(App.listDocuments()) - self.names:
            App.closeDocument(name)

    def call(self, op, **args):
        request = {"op": op, "measure": False, **args}
        if self.state and op not in self.core.CREATE_OPS:
            request.update(document_id=self.state["document_id"], expected_revision=self.state["revision"])
        response = self.core.dispatch(request)
        self.assertTrue(response["ok"], response)
        if "document_id" in response["result"]:
            self.state = response["result"]
        return response["result"]

    def make_source(self):
        self.call("new", name="Delivery source")
        self.call("sketch_rectangle", id="Profile", width=4, height=6)
        self.call("pad", id="Pad", profile="Profile", length=8)
        source, step = self.folder / "source.FCStd", self.folder / "source.step"
        self.call("save", path=str(source))
        self.call("export", path=str(step))
        self.call("close_document")
        return source, step

    def test_native_roundtrip_and_sampled_step_consistency_preserve_inputs(self):
        source, step = self.make_source()
        report = validate_delivery(source, self.folder / "delivery-evidence", exports=[step], surface=True,
                                   session_root=self.folder / "delivery-session")
        self.assertTrue(report["passed"], report)
        self.assertTrue(report["inputs_unchanged"])
        self.assertEqual(len(report["reopens"]), 2)
        self.assertTrue(report["exports"][0]["surface"]["performed"])
        with self.assertRaises(ValueError):
            validate_delivery(source, self.folder / "delivery-evidence")

    def test_nested_rotated_translated_legacy_result_matches_world_step(self):
        self.call("new", name="Nested native delivery")
        doc = self.core.documents[self.state["document_id"]]
        outer = doc.addObject("App::Part", "Outer")
        inner = doc.addObject("App::Part", "Inner")
        outer.addObject(inner)
        block = doc.addObject("PartDesign::Body", "NestedBlock")
        inner.addObject(block)
        feature = block.newObject("PartDesign::Feature", "NestedSolid")
        feature.Shape = Part.makeBox(2, 2, 2)
        outer.Placement = App.Placement(App.Vector(10, 20, 30), App.Rotation(App.Vector(0, 0, 1), 90))
        inner.Placement = App.Placement(App.Vector(2, 0, 0), App.Rotation())
        block.Placement = App.Placement(App.Vector(0, 0, 1), App.Rotation())
        doc.recompute()
        self.call("inspect")
        source, step = self.folder / "nested.FCStd", self.folder / "world.step"
        self.call("save", path=str(source))
        self.call("close_document")
        # Analytic expected world box, independent of the placement helper.
        Part.makeBox(2, 2, 2, App.Vector(8, 22, 31)).exportStep(str(step))
        report = validate_delivery(source, self.folder / "nested-delivery", exports=[step], surface=True,
                                   session_root=self.folder / "nested-session")
        self.assertTrue(report["passed"], report)

    def test_valid_solids_with_failed_embedded_integrity_cannot_pass_delivery(self):
        source, _ = self.make_source()
        self.call("new", name="Assembly with invalid seal")
        self.call("create_assembly")
        self.call("insert_assembly_part", path=str(source), source_id="Body", id="Occurrence")
        doc = self.core.documents[self.state["document_id"]]
        doc.Occurrence.LinkedObject.SourceGeometryFingerprint = "wrong-seal"
        broken = self.folder / "broken.FCStd"
        doc.saveAs(str(broken))  # intentional test corruption bypasses the typed save gate
        App.closeDocument(doc.Name)
        report = validate_delivery(broken, self.folder / "rejected-evidence", session_root=self.folder / "reject-session")
        self.assertFalse(report["passed"], report)
        self.assertEqual(len(report["reopens"]), 1)
        self.assertEqual(report["reopens"][0]["geometry_check_report"]["status"], "valid")
        self.assertEqual(report["reopens"][0]["build_status"], "failed")
        self.assertFalse(report["reopens"][0]["embedded_references"]["valid"])

    def test_export_same_counts_bounds_volume_needs_surface_comparison(self):
        first = Part.makeBox(10, 10, 10).cut(Part.makeCylinder(1, 10, App.Vector(3, 5, 0)))
        second = Part.makeBox(10, 10, 10).cut(Part.makeCylinder(1, 10, App.Vector(7, 5, 0)))
        self.assertTrue(compare_shapes(first, second)["passed"])
        fine = compare_shapes(first, second, surface=True, tolerance_mm=0.01)
        self.assertFalse(fine["passed"])
        self.assertIn("Unsampled", fine["surface"]["limitation"])
