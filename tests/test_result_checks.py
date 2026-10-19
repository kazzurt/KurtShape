"""Studio result post-conditions, the refine option, typed helices and tight measurement boxes.

The helical fixture is the Zimmer step drill's own body (revolve only) with its
two U flutes on 30-degree helices, built from typed operations. On the pinned
FreeCAD 1.1.4 / OCCT 7.8.1 runtime it reproduces the two silent failures the
post-conditions exist for: an undivided multi-turn helix whose cut removes
nothing, and a refined second flute whose cut turns the part inside out
(it takes the whole tool volume, BRepCheck still reports a valid solid).
"""
from pathlib import Path
import math
import sys
import unittest
from unittest.mock import patch

import support
from perf_fixture import FLUTED_VOLUME, STEP_R, add_flute, build_drill

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
from kurtshape.core import Controller, OperationError
from kurtshape.extrusion_preview import ExtrusionEvaluator
from kurtshape import geometry, studio
from test_build_status import no_kernel_checks

BLOCK = 20 * 20 * 10
# The Zimmer 5978-14 drill fixture (body, flutes and their constants) lives in perf_fixture.


class ResultCheckTests(unittest.TestCase):
    def setUp(self):
        self.initial = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="result-check-session-")
        self.core = Controller()
        self.state = self.core.dispatch({"op": "new", "name": "Result checks"})["result"]

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

    def snapshot(self):
        return (self.core._meta(self.doc).Revision, self.doc.UndoCount, sorted(obj.Name for obj in self.doc.Objects),
                {studio.part_id(body): None if body.Shape.isNull() else body.Shape.Volume
                 for body in studio.current_parts(self.doc)})

    def reject(self, code, op, **kwargs):
        before = self.snapshot()
        response = self.request(op, **kwargs)
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], code, response["error"])
        after = self.snapshot()
        self.assertEqual(after, before, "a rejected request must leave the document unchanged")
        return response["error"]

    def new_document(self, name):
        self.state = self.core.dispatch({"op": "new", "name": name})["result"]

    def block(self):
        self.call("sketch_rectangle", id="Base", width=20, height=20)
        self.call("pad", id="Block", profile="Base", length=10, operation="new")
        return "Body"

    def report(self):
        return self.state["result_report"]

    def binder(self, operation):
        return getattr(self.doc.getObject(operation + "Input"), "KurtShapeGeometryBinder")

    # --- post-conditions ---------------------------------------------------------------

    def test_result_operations_report_volume_delta_and_a_checked_solid(self):
        part = self.block()
        self.call("sketch_circle", id="HoleSketch", x=10, y=10, diameter=4)
        self.call("pocket", id="Hole", profile="HoleSketch", operation="remove")
        report = self.report()
        self.assertEqual((report["feature"], report["operation"], report["geometry_check"]), ("Hole", "remove", "valid"))
        self.assertAlmostEqual(report["volume_delta_mm3"], -math.pi * 4 * 10, places=6)
        self.assertEqual(len(report["parts"]), 1)
        row = report["parts"][0]
        self.assertEqual((row["part"], row["body"]), (part, "HolePart"))
        self.assertAlmostEqual(row["volume_before_mm3"], BLOCK, places=6)
        self.assertAlmostEqual(row["volume_after_mm3"], BLOCK - math.pi * 40, places=6)
        self.assertGreater(report["tool_volume_mm3"], math.pi * 40)
        self.assertEqual(report["refine"], {"requested": True, "applied": True, "retried_unrefined": False})
        # The next response carries no stale report.
        self.call("create_sketch", id="Cap", plane="XY")
        self.assertNotIn("result_report", self.state)
        self.call("add_rectangle", sketch="Cap", width=20, height=20)
        self.call("pad", id="Raise", profile="Cap", length=15, operation="add", merge_scope=[part])
        self.assertEqual((self.report()["operation"], self.report()["parts"][0]["merged_parts"]), ("add", [part]))
        self.assertAlmostEqual(self.report()["volume_delta_mm3"], 20 * 20 * 15 - (BLOCK - math.pi * 40), places=6)
        self.call("sketch_rectangle", id="Keep", width=10, height=10)
        self.call("pad", id="Trim", profile="Keep", length=20, operation="intersect", merge_scope=[part])
        self.assertAlmostEqual(self.report()["volume_delta_mm3"], 10 * 10 * 15 - 20 * 20 * 15, places=6)
        bbox = self.state["measurements"]["bbox_mm"]
        for actual, wanted in zip(bbox["min"] + bbox["max"], [0, 0, 0, 10, 10, 15]):
            self.assertAlmostEqual(actual, wanted, places=6)
        # preview evaluates the same checks and returns the report.
        self.call("sketch_circle", id="Bore", x=5, y=5, diameter=2)
        preview = self.core.dispatch({"op": "preview", "document_id": self.state["document_id"],
                                      "expected_revision": self.state["revision"],
                                      "proposal": {"op": "pocket", "profile": "Bore", "operation": "remove"}})
        self.assertTrue(preview["ok"], preview)
        self.assertTrue(preview["result"]["valid"], preview["result"])
        self.assertAlmostEqual(preview["result"]["result_report"]["volume_delta_mm3"], -math.pi * 15, places=6)
        self.assertNotIn("_result_report", self.core.__dict__)

    def test_a_remove_or_add_that_changes_nothing_rejects_and_rolls_back(self):
        part = self.block()
        self.call("sketch_circle", id="Far", x=60, y=60, diameter=4)
        error = self.reject("empty_cut", "pocket", id="Miss", profile="Far", operation="remove", merge_scope=[part])
        self.assertEqual(error["feature"], "Miss")
        self.assertEqual(error["parts"][0]["part"], part)
        self.assertAlmostEqual(error["parts"][0]["volume_delta_mm3"], 0, places=9)
        # The refined attempt failed first, so the unrefined retry ran and failed too.
        self.assertEqual(error["refine"]["refined_failure"]["code"], "empty_cut")
        self.assertIsNone(self.doc.getObject("Miss"))
        # An unrefined request reports the same rejection without a retry.
        error = self.reject("empty_cut", "pocket", id="Miss", profile="Far", operation="remove", merge_scope=[part],
                            refine=False)
        self.assertNotIn("refine", error)
        # A preview of it is invalid with the same code.
        preview = self.core.dispatch({"op": "preview", "document_id": self.state["document_id"],
                                      "expected_revision": self.state["revision"],
                                      "proposal": {"op": "pocket", "profile": "Far", "operation": "remove",
                                                   "merge_scope": [part]}})["result"]
        self.assertFalse(preview["valid"])
        self.assertEqual((preview["error"]["code"], preview["error"]["feature"]), ("empty_cut", "Remove"))
        self.assertNotIn("result_report", preview)
        # A tool entirely inside the part adds nothing.
        self.call("sketch_rectangle", id="Inner", x=5, y=5, width=2, height=2)
        error = self.reject("empty_add", "pad", id="Filler", profile="Inner", length=5, operation="add",
                            merge_scope=[part])
        self.assertEqual(error["feature"], "Filler")
        self.assertAlmostEqual(error["parts"][0]["volume_delta_mm3"], 0, places=6)

    def test_the_result_checker_rejects_kernel_results_a_boolean_cannot_give(self):
        """The checker itself, on crafted native results with known faults."""
        def body(name, shape):
            feature = self.doc.addObject("Part::Feature", name + "Shape")
            feature.Shape = shape
            container = self.doc.addObject("PartDesign::Body", name)
            container.BaseFeature = feature
            return container
        box = Part.makeBox(20, 20, 10)
        tool = Part.makeCylinder(2, 30, App.Vector(10, 10, -10))
        cut = box.cut(tool)
        target, tool_body = body("Target", box), body("Tool", tool)
        self.doc.recompute()
        snapshots = [("Body", target)]

        def check(operation, shape, kernel=True, name="Crafted"):
            result = body(name, shape)
            self.doc.recompute()
            try:
                return studio._check_result(self.doc, "Op", operation, tool_body, snapshots, [result], kernel)
            except OperationError as exc:
                return exc
        report = check("remove", cut, name="Correct")
        self.assertAlmostEqual(report["volume_delta_mm3"], -math.pi * 4 * 10, places=6)
        self.assertEqual(report["geometry_check"], "valid")
        unchanged = check("remove", box.copy(), name="Unchanged")
        self.assertEqual((unchanged.code, unchanged.details["feature"]), ("empty_cut", "Op"))
        too_much = check("remove", Part.makeBox(20, 20, 5), name="TooMuch")
        self.assertEqual((too_much.code, too_much.details["check"]), ("invalid_geometry", "volume"))
        # Same volume as the correct cut, 3 mm outside the target (geometry, not a placement).
        moved = Part.makeBox(20, 20, 10, App.Vector(3, 0, 0)).cut(Part.makeCylinder(2, 30, App.Vector(13, 10, -10)))
        outside = check("remove", moved, name="Moved")
        self.assertEqual((outside.code, outside.details["check"]), ("invalid_geometry", "bounds"))
        self.assertAlmostEqual(outside.details["outside_mm"], 3, places=6)
        # Live GUI previews run the native and volume checks only.
        self.assertEqual(check("remove", moved, kernel=False, name="MovedLive")["geometry_check"], "not_checked")
        broken = Part.Solid(Part.Shell(cut.Faces[:-1]))
        invalid = check("remove", broken, name="Open")
        self.assertEqual((invalid.code, invalid.details["check"]), ("invalid_geometry", "brepcheck"))
        lost_tool = check("add", box.copy(), name="AddLost")
        self.assertEqual(lost_tool.code, "empty_add")
        # The live GUI preview shows such an Add's tool; acceptance rejects it.
        self.assertEqual(check("add", box.copy(), kernel=False, name="AddLive")["volume_delta_mm3"], 0)
        smaller = check("add", Part.makeBox(20, 20, 9), name="AddShrunk")
        self.assertEqual((smaller.code, smaller.details["check"]), ("invalid_geometry", "volume"))
        grown = check("intersect", Part.makeBox(20, 20, 12), name="IntersectGrown")
        self.assertEqual((grown.code, grown.details["check"]), ("invalid_geometry", "volume"))

    def test_gui_live_preview_skips_kernel_checks_and_acceptance_runs_them(self):
        part = self.block()
        self.call("sketch_circle", id="HoleSketch", x=10, y=10, diameter=4)
        proposal = {"op": "pocket", "profile": "HoleSketch", "operation": "remove", "merge_scope": [part]}
        preview = ExtrusionEvaluator(self.core, self.doc, self.state["revision"])
        try:
            with no_kernel_checks(self):
                result = preview.evaluate(dict(proposal))
            self.assertTrue(result.valid, result.error)
        finally:
            preview.close()
        self.assertNotIn("_result_report", self.core.__dict__)
        with patch.object(geometry, "check_shape", wraps=geometry.check_shape) as check:
            self.call("pocket", id="Hole", **{key: value for key, value in proposal.items() if key != "op"})
        self.assertEqual(check.call_count, 1)
        self.assertEqual(self.report()["geometry_check"], "valid")

    # --- refine ----------------------------------------------------------------------------

    def test_refine_option_sets_the_boolean_and_its_input_binders(self):
        part = self.block()
        self.call("create_sketch", id="Cap", plane="XY")
        self.call("add_rectangle", sketch="Cap", width=20, height=20)
        self.call("pad", id="Refined", profile="Cap", length=15, operation="add", merge_scope=[part])
        self.assertTrue(self.doc.Refined.Refine)
        self.assertTrue(self.binder("Refined").Refine)
        self.assertEqual(len(studio.current_part(self.doc, part).Shape.Faces), 6)
        self.call("undo")
        self.call("pad", id="Plain", profile="Cap", length=15, operation="add", merge_scope=[part], refine=False)
        self.assertFalse(self.doc.Plain.Refine)
        self.assertFalse(self.binder("Plain").Refine)
        self.assertEqual(self.report()["refine"], {"requested": False, "applied": False, "retried_unrefined": False})
        faces = len(studio.current_part(self.doc, part).Shape.Faces)
        self.assertGreater(faces, 6)
        self.call("rebuild")
        self.assertEqual(len(studio.current_part(self.doc, part).Shape.Faces), faces)
        self.assertFalse(self.doc.Plain.Refine)
        self.reject("invalid_argument", "pad", id="Bad", profile="Cap", length=1, operation="add", refine="no")
        self.reject("invalid_argument", "pad", id="Legacy", profile="Cap", length=1, refine=False)
        # No Boolean to refine for a new part; the option is accepted.
        self.call("sketch_rectangle", id="Apart", x=40, width=5, height=5)
        self.call("pad", id="Separate", profile="Apart", length=5, operation="new", refine=False)
        self.assertNotIn("result_report", self.state)

    def test_a_failed_refined_result_is_retried_unrefined(self):
        part = self.block()
        self.call("sketch_circle", id="HoleSketch", x=10, y=10, diameter=4)
        real = studio._check_result
        seen = []

        def refined_fails(doc, name, *args):
            seen.append(doc.getObject(name).Refine)
            if doc.getObject(name).Refine:
                raise OperationError("invalid_geometry", "simulated refine failure", feature=name, check="brepcheck",
                                     issues=["simulated"])
            return real(doc, name, *args)
        with patch.object(studio, "_check_result", side_effect=refined_fails):
            self.call("pocket", id="Hole", profile="HoleSketch", operation="remove")
        self.assertEqual(seen, [True, False])
        refine = self.report()["refine"]
        self.assertEqual((refine["requested"], refine["applied"], refine["retried_unrefined"]), (True, False, True))
        self.assertEqual(refine["refined_failure"], {"code": "invalid_geometry", "message": "simulated refine failure",
                                                     "check": "brepcheck", "issues": ["simulated"]})
        self.assertFalse(self.doc.Hole.Refine)
        self.assertFalse(self.binder("Hole").Refine)
        self.assertAlmostEqual(studio.current_part(self.doc, part).Shape.Volume, BLOCK - math.pi * 40, places=6)

    # --- helical flutes (the drill regression) ---------------------------------------------------

    def drill_body(self):
        self.state, part = build_drill(self.core, self.state)
        return part

    def flute(self, n, part, expect_ok=True, segment_length=None, **options):
        self.state, response = add_flute(self.core, self.state, n, part, segment_length=segment_length, **options)
        if expect_ok:
            self.assertTrue(response["ok"], response)
            self.state = response["result"]
            return self.state
        return response

    def test_undivided_helix_cut_that_removes_nothing_is_rejected(self):
        part = self.drill_body()
        response = self.flute(1, part, expect_ok=False, segment_length=100)
        self.assertFalse(response["ok"], response)
        self.assertEqual((response["error"]["code"], response["error"]["feature"]), ("empty_cut", "Flute1"))
        self.assertLess(abs(response["error"]["parts"][0]["volume_delta_mm3"]), 0.01)
        self.assertIsNone(self.doc.getObject("Flute1"))

    def test_inside_out_refined_flute_falls_back_unrefined_or_rejects(self):
        part = self.drill_body()
        self.flute(1, part, refine=False)
        self.assertAlmostEqual(self.report()["volume_delta_mm3"], -1824.389, places=2)
        # Refined, the second flute takes its whole tool volume and grows past the
        # Ø13 step; the unrefined retry is accepted and says so.
        self.flute(2, part)
        refine = self.report()["refine"]
        self.assertEqual((refine["applied"], refine["retried_unrefined"]), (False, True))
        self.assertEqual((refine["refined_failure"]["code"], refine["refined_failure"]["check"]),
                         ("invalid_geometry", "bounds"))
        self.assertFalse(self.doc.Flute2.Refine)
        self.assertFalse(self.binder("Flute2").Refine)
        self.assertAlmostEqual(studio.current_part(self.doc, part).Shape.Volume, FLUTED_VOLUME, places=2)
        bbox = self.state["measurements"]["bbox_mm"]
        for axis in (0, 2):
            self.assertAlmostEqual(bbox["min"][axis], -STEP_R, places=5)
            self.assertAlmostEqual(bbox["max"][axis], STEP_R, places=5)
        check = self.call("check_geometry")["geometry_check_report"]
        self.assertEqual(check["status"], "valid")
        # With the first flute refined, unrefining the second cannot help: reject.
        self.new_document("Refined flutes")
        part = self.drill_body()
        self.flute(1, part)
        response = self.flute(2, part, expect_ok=False)
        self.assertFalse(response["ok"], response)
        error = response["error"]
        self.assertEqual((error["code"], error["feature"], error["check"]), ("invalid_geometry", "Flute2", "bounds"))
        self.assertGreater(error["outside_mm"], 1)
        self.assertTrue(error["refine"]["retried_unrefined"])
        self.assertIn("refine:false", error["refine"]["hint"])
        self.assertIsNone(self.doc.getObject("Flute2"))

    # --- create_helix ----------------------------------------------------------------------------

    def helix_row(self, name):
        return next(row for row in self.state["features"] if row["id"] == name)

    def test_create_helix_builds_a_native_editable_sweep_path(self):
        self.call("create_helix", id="Coil", pitch=10, height=25, radius=3)
        helix = self.doc.Coil
        self.assertEqual(helix.TypeId, "Part::Helix")
        self.assertIsNone(helix.getParentGeoFeatureGroup())
        self.assertEqual(len(helix.Shape.Edges), 3)
        self.assertIn("Coil", self.state["studio"]["feature_order"])
        # Like a sketch, a helix leaves the document's Body defaults alone.
        self.assertFalse(studio.enabled(self.doc))
        self.call("create_sketch", id="AfterHelix")
        row = self.helix_row("Coil")["helix"]
        self.assertEqual((row["handedness"], row["edge_count"], row["turns"]), ("right", 3, 2.5))
        for actual, wanted in zip(row["start_point_mm"] + row["end_point_mm"], [3, 0, 0, -3, 0, 25]):
            self.assertAlmostEqual(actual, wanted, places=9)
        self.assertGreater(row["start_tangent"][1], 0.5)
        self.assertEqual(set(self.helix_row("Coil")["parameters"]), {"Pitch", "Height", "Radius"})
        # Left-handed, tilted, phased: start = origin + r (cos a x + sin a (axis × x)).
        self.call("create_helix", id="Phased", pitch=4, height=8, radius=2, handedness="left",
                  axis={"origin": [1, 2, 3], "direction": [0, -2, 0]}, start_angle="90 deg", segment_length=0.5)
        row = self.helix_row("Phased")["helix"]
        for actual, wanted in zip(row["start_point_mm"] + row["axis"]["direction"], [1, 2, 5, 0, -1, 0]):
            self.assertAlmostEqual(actual, wanted, places=9)
        self.assertEqual((row["handedness"], row["edge_count"], row["segment_length_turns"]), ("left", 4, 0.5))
        # axis × start = -X; a left-handed helix starts away from it.
        self.assertGreater(row["start_tangent"][0], 0.5)
        # Editable native dimensions, with the same size limit.
        self.call("set_parameter", feature="Coil", parameter="Pitch", value=5)
        self.assertEqual(self.helix_row("Coil")["helix"]["edge_count"], 5)
        self.reject("invalid_argument", "set_parameter", feature="Coil", parameter="Height", value=6000)
        for arguments, code in [({"pitch": 0, "height": 1, "radius": 1}, "invalid_argument"),
                                ({"pitch": 1, "height": 1, "radius": 1, "handedness": "ccw"}, "invalid_argument"),
                                ({"pitch": 1, "height": 1, "radius": 1, "segment_length": 0}, "invalid_argument"),
                                ({"pitch": 0.01, "height": 100, "radius": 1}, "invalid_argument"),
                                ({"pitch": 1, "height": 10, "radius": 1, "segment_length": 0.001}, "invalid_argument"),
                                ({"pitch": 1, "height": 1, "radius": 1, "x_direction": [0, 0, 5]}, "invalid_argument"),
                                ({"pitch": 1, "height": 1, "radius": 1, "axis": {"origin": [0, 0, 0], "up": [0, 0, 1]}},
                                 "invalid_argument"),
                                ({"pitch": 1, "height": 1, "radius": 1, "body": "Body"}, "unknown_argument")]:
            with self.subTest(arguments=arguments):
                self.reject(code, "create_helix", id="Rejected", **arguments)

    def test_helix_is_a_sweep_input_with_history_and_persistence(self):
        self.call("create_helix", id="Coil", pitch=10, height=25, radius=3)
        row = self.helix_row("Coil")["helix"]
        self.call("create_plane", id="CoilStart", origin=row["start_point_mm"], normal=row["start_tangent"])
        self.call("sketch_circle", id="Wire", support={"feature": "CoilStart"}, x=0, y=0, diameter=1)
        self.call("sweep", id="Spring", profile="Wire", path="Coil", frenet=True, operation="new")
        length = 2.5 * math.hypot(2 * math.pi * 3, 10)
        self.assertAlmostEqual(self.state["measurements"]["volume_mm3"], math.pi * 0.25 * length, delta=0.05)
        self.assertFalse(self.doc.Coil.KurtShapeInternal)
        self.assertNotEqual(getattr(self.doc.Coil, "KurtShapeOperationOwner", ""), "Spring")
        error = self.reject("external_dependency", "delete_features", features=["Coil"])
        self.assertTrue(error["feature"].startswith("Spring"), error)
        path = self.folder / "helix.FCStd"
        self.call("save", path=str(path))
        self.call("delete_features", features=["Spring"])
        self.assertIsNotNone(self.doc.getObject("Coil"))
        self.call("delete_features", features=["Coil"])
        self.assertIsNone(self.doc.getObject("Coil"))
        self.call("undo")
        self.assertIsNotNone(self.doc.getObject("Coil"))
        App.closeDocument(self.doc.Name)
        self.state = self.core.dispatch({"op": "open", "path": str(path)})["result"]
        self.assertEqual(self.state["build_status"], "valid")
        self.assertTrue(self.doc.Coil.KurtShapeCurve)
        self.assertEqual(self.helix_row("Coil")["helix"]["edge_count"], 3)
        self.assertLess(self.state["studio"]["feature_order"].index("Coil"),
                        self.state["studio"]["feature_order"].index("Spring"))

    # --- measurements ----------------------------------------------------------------------------

    def test_measurement_boxes_are_tight_on_curved_parts(self):
        self.call("sketch_circle", id="Ring", plane="XZ", x=10, y=0, diameter=4)
        self.call("revolve", id="Torus", profile="Ring", axis={"origin": [0, 0, 0], "direction": [0, 0, 1]},
                  angle="360 deg", operation="new")
        bbox = self.state["measurements"]["bbox_mm"]
        for actual, wanted in zip(bbox["min"] + bbox["max"], [-12, -12, -2, 12, 12, 2]):
            self.assertAlmostEqual(actual, wanted, places=5)
        shape = studio.current_parts(self.doc)[0].Shape
        # The native box (still used for conservative overlap pruning) is looser here.
        self.assertGreater(geometry.bounding_box(shape)["max"][0], 12.5)
        self.assertEqual(self.state["bodies"][0]["measurements"]["bbox_mm"], bbox)


if __name__ == "__main__":
    unittest.main()
