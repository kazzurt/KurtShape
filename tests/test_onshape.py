"""Source rejection and native-edit checks, including analytic geometry oracles.

Run with bundled FreeCAD bin/python.exe -B -m unittest discover -s tests -p
test_onshape.py. Stdlib Python runs preflight tests and explicitly skips native
checks when FreeCAD is unavailable.
"""
from copy import deepcopy
import json
import math
from pathlib import Path
import sys
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kurtshape.onshape import compile_document, convert_document, native_id

try:
    import FreeCAD as App
    import Part
    from kurtshape.core import Controller
    NATIVE = True
except ImportError:
    NATIVE = False


def fixture(name="centered-plate-with-hole.json"):
    return json.loads((ROOT / "examples" / "onshape-supported-subset" / name).read_text(encoding="utf-8"))


class MutationRecorder:
    def __init__(self):
        self.calls = []

    def dispatch(self, request):
        self.calls.append(request)
        raise AssertionError("Unsupported input must reject before dispatch")


class PreflightTests(unittest.TestCase):
    def assert_rejected(self, payload, code=None):
        controller = MutationRecorder()
        result = convert_document(payload, controller)
        self.assertFalse(result["ok"])
        self.assertEqual(result["phase"], "preflight")
        self.assertEqual(result["native_mutations"], 0)
        self.assertEqual(controller.calls, [])
        if code:
            self.assertEqual(result["error"]["code"], code)
        return result

    def test_supported_plan_units_and_mapping(self):
        plan = compile_document(fixture("circular-inch-pad.json"))
        self.assertEqual([op["op"] for op in plan.operations], ["sketch_circle", "pad"])
        self.assertEqual(plan.operations[0]["diameter"], 25.4)
        self.assertEqual(plan.operations[0]["y"], -6.35)
        self.assertEqual(plan.operations[1]["length"], 6.35)
        self.assertEqual(len(plan.source_mapping), 2)
        self.assertNotEqual(native_id("a-b"), native_id("a_b"))

    def test_unknown_late_feature_rejects_before_creation(self):
        payload = fixture()
        payload["features"][-1]["draftAngle"] = "5 deg"
        self.assert_rejected(payload, "unknown_field")

    def test_unknown_parameter_rejects_before_creation(self):
        payload = fixture()
        payload["features"][1]["parameters"].append({"btType": "BTMParameterQuantity-147", "parameterId": "secondDirectionDepth", "expression": "4 mm"})
        self.assert_rejected(payload, "unsupported_parameters")

    def test_unknown_nested_query_rejects(self):
        payload = fixture()
        payload["features"][-1]["entities"][0]["deterministicIds"] = ["guessed-face-id"]
        self.assert_rejected(payload, "unknown_field")

    def test_unsupported_constraints_references_units_expressions(self):
        variants = []
        for changes in [lambda p: p["features"][0].update(constraints=[{"constraintType": "TANGENT"}]),
                        lambda p: p["features"][0].update(plane="Front"),
                        lambda p: p["features"][0]["parameters"][2].update(expression="#Width / 2"),
                        lambda p: p["features"][0]["parameters"][2].update(expression="2 feet"),
                        lambda p: p["features"][0]["parameters"][2].update(expression="1e999 mm"),
                        lambda p: p["features"][2].update(centerOn="missing-sketch"),
                        lambda p: p["features"][0].update(suppressed=True),
                        lambda p: p["features"][0].update(featureType="fillet")]:
            payload = fixture()
            changes(payload)
            variants.append(payload)
        for payload in variants:
            with self.subTest(payload=payload["features"][0]):
                self.assert_rejected(payload)

    def test_shifted_rectangle_center_dependency_rejects(self):
        payload = fixture()
        payload["features"][0]["parameters"][0]["expression"] = "5 mm"
        self.assert_rejected(payload, "unsupported_reference")

    def test_feature_duplicates_missing_dependency_multi_body_reject(self):
        payload = fixture()
        payload["features"][-1]["featureId"] = payload["features"][0]["featureId"]
        self.assert_rejected(payload, "duplicate_feature")
        payload = fixture()
        payload["features"][1]["entities"][0]["featureId"] = "later-unresolved"
        self.assert_rejected(payload, "missing_dependency")
        payload = fixture()
        payload["features"][-1]["parameters"] = deepcopy(payload["features"][1]["parameters"])
        self.assert_rejected(payload, "unsupported_extrude")

    def test_raw_featurescript_and_raw_api_never_claimed_supported(self):
        self.assert_rejected("FeatureScript 3083; import(...)", "invalid_source")
        self.assert_rejected({"btType": "BTFeatureListResponse-2457", "features": []}, "unknown_field")
        payload = fixture()
        payload["provenance"]["kind"] = "onshape_api_capture"
        self.assert_rejected(payload, "uncaptured_provenance")


@unittest.skipUnless(NATIVE, "Bundled FreeCAD Python is required for native rebuild/edit verification")
class NativeConversionTests(unittest.TestCase):
    def setUp(self):
        self.controller = Controller()
        self.created = []

    def tearDown(self):
        for name in self.created:
            if name in App.listDocuments():
                App.closeDocument(name)

    def converted(self, name="centered-plate-with-hole.json"):
        result = convert_document(fixture(name), self.controller)
        self.assertTrue(result["ok"], result)
        state = result["result"]
        doc = self.controller.documents[state["document_id"]]
        self.created.append(doc.Name)
        self.assertFalse(result["real_example_migration"])
        return result, state, doc

    def change(self, state, **operation):
        result = self.controller.dispatch({"document_id": state["document_id"], "expected_revision": state["revision"], **operation})
        self.assertTrue(result["ok"], result)
        return result["result"]

    def assert_volume(self, state, expected):
        self.assertEqual(state["build_status"], "valid")
        self.assertTrue(state["measurements"]["valid"])
        self.assertEqual(state["measurements"]["solid_count"], 1)
        self.assertAlmostEqual(state["measurements"]["volume_mm3"], expected, places=6)

    def test_native_baseline_critical_dimensions_and_shape_difference(self):
        result, state, doc = self.converted()
        self.assert_volume(state, 60 * 40 * 6 - math.pi * 4 ** 2 * 6)
        self.assertEqual(len(result["source_mapping"]), 4)
        for mapping in result["source_mapping"]:
            self.assertEqual(doc.getObject(mapping["native_id"]).SourceFeatureId, mapping["source_feature_id"])
        sketches = [f for f in state["features"] if f["type"] == "Sketcher::SketchObject"]
        self.assertEqual(len(sketches), 2)
        self.assertTrue(all(f["fully_constrained"] for f in sketches))
        reference = Part.makeBox(60, 40, 6).cut(Part.makeCylinder(4, 6, App.Vector(30, 20, 0)))
        missing = reference.cut(doc.Body.Shape)
        extra = doc.Body.Shape.cut(reference)
        self.assertTrue(missing.isNull() or missing.isValid())
        self.assertTrue(extra.isNull() or extra.isValid())
        self.assertLess(missing.Volume + extra.Volume, 1e-6)

    def test_two_native_edits_and_upstream_center_dependency(self):
        _, state, doc = self.converted()
        state = self.change(state, op="set_parameter", feature=native_id("fixture-plate-profile"), parameter="Width", value=72)
        self.assert_volume(state, 72 * 40 * 6 - math.pi * 4 ** 2 * 6)
        circle = doc.getObject(native_id("fixture-hole-profile"))
        self.assertAlmostEqual(circle.Geometry[0].Center.x, 36, places=7)
        self.assertAlmostEqual(circle.Geometry[0].Center.y, 20, places=7)
        state = self.change(state, op="set_parameter", feature=native_id("fixture-hole-profile"), parameter="Diameter", value=10)
        self.assert_volume(state, 72 * 40 * 6 - math.pi * 5 ** 2 * 6)
        self.assertAlmostEqual(circle.Geometry[0].Radius, 5, places=7)
        state = self.change(state, op="rebuild")
        self.assert_volume(state, 72 * 40 * 6 - math.pi * 5 ** 2 * 6)

    def test_inch_native_geometry_placement(self):
        _, state, doc = self.converted("circular-inch-pad.json")
        self.assert_volume(state, math.pi * 12.7 ** 2 * 6.35)
        bounds = doc.Body.Shape.BoundBox
        self.assertAlmostEqual(bounds.XMin, 0, places=7)
        self.assertAlmostEqual(bounds.XMax, 25.4, places=7)
        self.assertAlmostEqual(bounds.YMin, -19.05, places=7)
        self.assertAlmostEqual(bounds.YMax, 6.35, places=7)
        self.assertAlmostEqual(bounds.ZMax, 6.35, places=7)

    def test_save_reopen_relocate_preserves_native_mapping_and_dependencies(self):
        _, state, doc = self.converted()
        with tempfile.TemporaryDirectory(prefix="onshape-fixture-persistence-", dir=ROOT / "validation") as directory:
            working = Path(directory).resolve()
            self.assertTrue(working.is_relative_to(ROOT.resolve()))
            path = working / "fixture.FCStd"
            state = self.change(state, op="save", path=str(path))
            relocated = working / "relocated-fixture.FCStd"
            shutil.copy2(path, relocated)
            App.closeDocument(doc.Name)
            opened = self.controller.dispatch({"op": "open", "path": str(relocated)})
            self.assertTrue(opened["ok"], opened)
            state = opened["result"]
            doc = self.controller.documents[state["document_id"]]
            self.created.append(doc.Name)
            state = self.change(state, op="rebuild")
            self.assert_volume(state, 60 * 40 * 6 - math.pi * 4 ** 2 * 6)
            mapping = json.loads(doc.KurtShapeProject.SourceMapping)
            self.assertEqual(mapping["fixture-hole-profile"], native_id("fixture-hole-profile"))
            state = self.change(state, op="set_parameter", feature=native_id("fixture-plate-profile"), parameter="Width", value=72)
            self.assert_volume(state, 72 * 40 * 6 - math.pi * 4 ** 2 * 6)
            self.assertAlmostEqual(doc.getObject(native_id("fixture-hole-profile")).Geometry[0].Center.x, 36, places=7)
            App.closeDocument(doc.Name)

    def test_runtime_build_failure_is_explicit_and_retains_partial_document(self):
        payload = fixture()
        payload["features"][2].pop("centerOn")
        payload["features"][2]["parameters"].extend([
            {"btType": "BTMParameterQuantity-147", "parameterId": "x", "expression": "900 mm"},
            {"btType": "BTMParameterQuantity-147", "parameterId": "y", "expression": "900 mm"}])
        result = convert_document(payload, self.controller)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["phase"], "native_build")
        self.assertFalse(result["saved"])
        self.assertEqual(result["failed_source_feature_id"], "fixture-hole-cut")
        doc = self.controller.documents[result["partial_document"]["document_id"]]
        self.created.append(doc.Name)
        state = self.controller.dispatch({"op": "inspect", "document_id": result["partial_document"]["document_id"]})["result"]
        self.assert_volume(state, 60 * 40 * 6)
        self.assertEqual(len(result["applied_source_mapping"]), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
