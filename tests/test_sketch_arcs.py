"""Native sketch arcs: constraint scheme, profile topology and solids; bundled Python."""
from pathlib import Path
import math
import sys
import unittest
import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
from kurtshape.core import Controller
from kurtshape import studio


class SketchArcTests(unittest.TestCase):
    def setUp(self):
        self.initial_names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="sketch-arc-session-")
        self.core = Controller()
        self.state = self.call("new", name="Sketch arc acceptance")

    def tearDown(self):
        for name in set(App.listDocuments()) - self.initial_names:
            App.closeDocument(name)
        self.core.observer.close()

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

    def parameters(self, sketch):
        return next(f for f in self.state["features"] if f["id"] == sketch)["parameters"]

    def assert_fully_constrained(self, sk):
        self.assertEqual(sk.solve(), 0)
        self.assertEqual(sk.DoF, 0)
        self.assertTrue(sk.FullyConstrained)
        for diagnostic in ("ConflictingConstraints", "RedundantConstraints", "PartiallyRedundantConstraints",
                           "MalformedConstraints"):
            self.assertEqual(list(getattr(sk, diagnostic)), [], diagnostic)
        self.assertEqual(sk.getGeometryWithDependentParameters(), [])

    def joined(self, sk):
        """Native coincidences between two sketch curves, as sorted geometry pairs."""
        return sorted(tuple(sorted((c.First, c.Second))) for c in sk.Constraints
                      if c.Type == "Coincident" and c.First >= 0 and c.Second >= 0)

    def assert_arc(self, curve, center, radius, start, end):
        self.assertIsInstance(curve, Part.ArcOfCircle)
        self.assertLess(curve.Center.distanceToPoint(App.Vector(*center, 0)), 1e-9)
        self.assertAlmostEqual(curve.Radius, radius, places=9)
        self.assertLess(curve.StartPoint.distanceToPoint(App.Vector(*start, 0)), 1e-9)
        self.assertLess(curve.EndPoint.distanceToPoint(App.Vector(*end, 0)), 1e-9)

    def test_obround_lines_and_semicircles_join_natively_and_pad_to_analytic_volume(self):
        self.call("create_sketch", id="Slot")
        self.call("add_line", sketch="Slot", x1=0, y1=0, x2=20, y2=0)
        # Center form; its start joins the line end, its end stays free.
        self.call("add_arc", sketch="Slot", cx=20, cy=5, radius=5, start_angle="-90 deg", end_angle="90 deg")
        # This line's start lands on the fixed arc end and joins it natively.
        self.call("add_line", sketch="Slot", x1=20, y1=10, x2=0, y2=10)
        # Endpoint form closing the loop: both ends join, Sweep alone fixes it.
        self.call("add_arc", sketch="Slot", x1=0, y1=10, x2=0, y2=0, cx=0, cy=5)
        sk = self.doc.Slot
        self.assert_fully_constrained(sk)
        self.assertEqual(self.joined(sk), [(0, 1), (0, 3), (1, 2), (2, 3)])
        self.assert_arc(sk.Geometry[1], (20, 5), 5, (20, 0), (20, 10))
        self.assert_arc(sk.Geometry[3], (0, 5), 5, (0, 10), (0, 0))
        self.assertEqual(len(sk.Shape.Wires), 1)
        self.assertTrue(sk.Shape.Wires[0].isClosed())
        parameters = self.parameters("Slot")
        self.assertAlmostEqual(parameters["CenterX"]["value"], 20, places=9)
        self.assertAlmostEqual(parameters["CenterY"]["value"], 5, places=9)
        for name in ("Sweep", "Sweep_2"):
            self.assertAlmostEqual(parameters[name]["value"], math.pi, places=9)
            self.assertEqual(parameters[name]["unit"], "rad")
            self.assertEqual(parameters[name]["constraint_type"], "Angle")
        self.assertNotIn("Radius", parameters)
        # The second line's joined start carries no coordinate dimensions.
        self.assertEqual(sorted(name for name in parameters if name.startswith(("Start", "End"))), ["EndX", "EndY"])
        self.call("pad", id="SlotPad", profile="Slot", length=3)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, (20 * 10 + math.pi * 5 ** 2) * 3, places=6)
        self.assertEqual(self.state["build_status"], "valid")

    def test_d_profile_free_arc_then_joined_line_stays_parametric(self):
        self.call("create_sketch", id="D")
        self.call("add_arc", sketch="D", cx=0, cy=0, radius=8, start_angle=-math.pi / 2, end_angle=math.pi / 2)
        sk = self.doc.D
        self.assert_fully_constrained(sk)
        parameters = self.parameters("D")
        # Center on the origin and start on the vertical axis need no dimensions.
        self.assertEqual(sorted(parameters), ["Radius", "Sweep"])
        self.assertEqual(parameters["Radius"]["unit"], "mm")
        self.call("add_line", sketch="D", x1=0, y1=8, x2=0, y2=-8)
        # Joined ends sit exactly on the arc's (8*cos(-pi/2) is not 0), so a native
        # re-solve rewrites nothing and the revision stays current.
        self.assertEqual(sk.getPoint(1, 1).distanceToPoint(sk.getPoint(0, 2)), 0)
        self.assertEqual(sk.getPoint(1, 2).distanceToPoint(sk.getPoint(0, 1)), 0)
        content = [g.Content for g in sk.Geometry]
        self.assert_fully_constrained(sk)
        self.assertEqual([g.Content for g in sk.Geometry], content)
        self.assertEqual(self.joined(sk), [(0, 1), (0, 1)])
        self.assertEqual(sorted(self.parameters("D")), ["Radius", "Sweep"])
        self.call("pad", id="DPad", profile="D", length=4)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, math.pi * 8 ** 2 / 2 * 4, places=6)
        # The joined closing line follows a radius edit.
        self.call("set_parameter", feature="D", parameter="Radius", value=10)
        self.assert_fully_constrained(sk)
        self.assertAlmostEqual(sk.getPoint(1, 1).distanceToPoint(sk.getPoint(1, 2)), 20, places=9)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, math.pi * 10 ** 2 / 2 * 4, places=6)

    def test_revolve_profile_with_quarter_arc_corner_matches_pappus_volume(self):
        self.call("create_sketch", id="Turn", plane="XZ")
        self.call("add_line", sketch="Turn", x1=0, y1=0, x2=10, y2=0)
        self.call("add_line", sketch="Turn", x1=10, y1=0, x2=10, y2=16)
        self.call("add_arc", sketch="Turn", cx=6, cy=16, radius=4, start_angle=0, end_angle="90 deg")
        self.call("add_line", sketch="Turn", x1=6, y1=20, x2=0, y2=20)
        self.call("add_line", sketch="Turn", x1=0, y1=20, x2=0, y2=0)
        sk = self.doc.Turn
        self.assert_fully_constrained(sk)
        self.assertEqual(self.joined(sk), [(1, 2), (2, 3)])
        self.assertEqual(len(sk.Shape.Wires), 1)
        self.assertTrue(sk.Shape.Wires[0].isClosed())
        self.call("revolve", id="Cup", profile="Turn", angle="360 deg", operation="new")
        self.assertEqual(self.doc.Cup.TypeId, "Part::Revolution")
        # Pappus: rectangle minus the 4 x 4 corner plus a quarter disc of radius 4.
        moment = 200 * 5 - 16 * 8 + 4 * math.pi * (6 + 4 * 4 / (3 * math.pi))
        self.assertAlmostEqual(sum(obj.Shape.Volume for obj in studio.current_parts(self.doc)),
                               2 * math.pi * moment, places=5)

    def test_rounded_rectangle_and_arc_to_arc_joins_pad_to_analytic_volumes(self):
        # Flats first, then R2 corner arcs: every corner arc joins at both ends.
        self.call("create_sketch", id="Rounded")
        for x1, y1, x2, y2 in ((2, 0, 28, 0), (30, 2, 30, 18), (28, 20, 2, 20), (0, 18, 0, 2)):
            self.call("add_line", sketch="Rounded", x1=x1, y1=y1, x2=x2, y2=y2)
        for cx, cy, start in ((28, 2, -90), (28, 18, 0), (2, 18, 90), (2, 2, 180)):
            self.call("add_arc", sketch="Rounded", cx=cx, cy=cy, radius=2,
                      start_angle=f"{start} deg", end_angle=f"{start + 90} deg")
        sk = self.doc.Rounded
        self.assert_fully_constrained(sk)
        self.assertEqual(self.joined(sk), [(0, 4), (0, 7), (1, 4), (1, 5), (2, 5), (2, 6), (3, 6), (3, 7)])
        self.assertEqual(sorted(name for name in self.parameters("Rounded") if name.startswith("Sweep")),
                         ["Sweep", "Sweep_2", "Sweep_3", "Sweep_4"])
        self.call("pad", id="RoundedPad", profile="Rounded", length=2)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, (30 * 20 - 4 * (4 - math.pi)) * 2, places=6)
        # Three arcs joined end to end close a circle with native arc-arc junctions:
        # free, joined at its start, then joined at both ends.
        self.call("create_body", id="Disc")
        self.call("create_sketch", id="Thirds", body="Disc")
        self.call("add_arc", sketch="Thirds", cx=0, cy=0, radius=5, start_angle=0, end_angle="120 deg")
        self.call("add_arc", sketch="Thirds", cx=0, cy=0, radius=5, start_angle="120 deg", end_angle="240 deg")
        end = (5 * math.cos(math.radians(240)), 5 * math.sin(math.radians(240)))
        self.call("add_arc", sketch="Thirds", x1=end[0], y1=end[1], x2=5, y2=0, cx=0, cy=0)
        thirds = self.doc.Thirds
        self.assert_fully_constrained(thirds)
        self.assertEqual(self.joined(thirds), [(0, 1), (0, 2), (1, 2)])
        self.assertEqual(sorted(self.parameters("Thirds")), ["Radius", "Sweep", "Sweep_2", "Sweep_3"])
        self.call("pad", id="DiscPad", profile="Thirds", length=3)
        self.assertAlmostEqual(self.doc.Disc.Shape.Volume, math.pi * 25 * 3, places=6)

    def test_endpoint_form_free_arc_wraps_angles_and_inspects(self):
        self.call("create_sketch", id="Free")
        r = 5
        start, end = math.radians(30), math.radians(130)
        first = (2 + r * math.cos(start), 3 + r * math.sin(start))
        last = (2 + r * math.cos(end), 3 + r * math.sin(end))
        self.call("add_arc", sketch="Free", x1=first[0], y1=first[1], x2=last[0], y2=last[1], cx=2, cy=3)
        sk = self.doc.Free
        self.assert_fully_constrained(sk)
        self.assert_arc(sk.Geometry[0], (2, 3), r, first, last)
        parameters = self.parameters("Free")
        # At 30 deg the start Y changes faster than X, so StartY fixes the start angle.
        self.assertEqual(sorted(parameters), ["CenterX", "CenterY", "Radius", "StartY", "Sweep"])
        self.assertAlmostEqual(parameters["Sweep"]["value"], math.radians(100), places=9)
        self.assertAlmostEqual(parameters["StartY"]["value"], first[1], places=9)
        # Counter-clockwise from 350 deg to 10 deg is a 20 deg arc through 0 deg.
        self.call("add_arc", sketch="Free", cx=-20, cy=0, radius=3, start_angle="350 deg", end_angle="10 deg",
                  construction=True)
        self.assert_fully_constrained(sk)
        arc = sk.Geometry[1]
        self.assertTrue(sk.getConstruction(1))
        self.assertAlmostEqual(arc.LastParameter - arc.FirstParameter, math.radians(20), places=9)
        self.assertAlmostEqual(arc.value((arc.FirstParameter + arc.LastParameter) / 2).x, -17, places=9)
        self.assertAlmostEqual(self.parameters("Free")["Sweep_2"]["value"], math.radians(20), places=9)
        # A construction arc starting on the profile arc's end does not join it.
        self.call("add_arc", sketch="Free", cx=last[0], cy=last[1] + 2, radius=2, start_angle="-90 deg",
                  end_angle="0 deg", construction=True)
        self.assertLess(sk.getPoint(2, 1).distanceToPoint(sk.getPoint(0, 2)), 1e-9)
        self.assertEqual(self.joined(sk), [])
        self.assert_fully_constrained(sk)

    def test_line_only_sketches_keep_coordinate_dimensions(self):
        self.call("create_sketch", id="Triangle")
        self.call("add_line", sketch="Triangle", x1=1, y1=1, x2=5, y2=1)
        self.call("add_line", sketch="Triangle", x1=5, y1=1, x2=5, y2=4)
        self.call("add_line", sketch="Triangle", x1=5, y1=4, x2=1, y2=1)
        sk = self.doc.Triangle
        self.assertEqual(self.joined(sk), [])
        self.assertEqual([c.Type for c in sk.Constraints].count("Coincident"), 0)
        self.assertEqual(len(self.parameters("Triangle")), 12)
        self.assert_fully_constrained(sk)

    def test_free_native_arc_is_not_an_anchor_and_construction_line_never_joins(self):
        self.call("create_sketch", id="Mixed")
        sk = self.doc.Mixed
        sk.addGeometry(Part.ArcOfCircle(Part.Circle(App.Vector(0, 0, 0), App.Vector(0, 0, 1), 4), 0, math.pi / 2), False)
        self.doc.recompute()
        self.call("inspect")
        self.call("add_line", sketch="Mixed", x1=4, y1=0, x2=10, y2=0)
        self.assertEqual(self.joined(sk), [])
        self.assertNotIn(1, {index for index, _ in sk.getGeometryWithDependentParameters()})
        self.call("create_sketch", id="Fixed")
        self.call("add_arc", sketch="Fixed", cx=0, cy=0, radius=4, start_angle=0, end_angle="90 deg")
        self.call("add_line", sketch="Fixed", x1=4, y1=0, x2=4, y2=-6, construction=True)
        self.assertEqual(self.joined(self.doc.Fixed), [])
        self.assert_fully_constrained(self.doc.Fixed)

    def test_arc_participates_in_managed_sketch_edit(self):
        self.call("create_sketch", id="Managed", plane="XZ")
        self.call("begin_sketch_edit", feature="Managed")
        self.call("add_line", sketch="Managed", x1=0, y1=0, x2=10, y2=0)
        self.call("add_arc", sketch="Managed", cx=10, cy=3, radius=3, start_angle="-90 deg", end_angle="90 deg")
        self.rejected("managed_sketch_mismatch", "add_arc", sketch="Other", cx=0, cy=0, radius=1,
                      start_angle=0, end_angle=1)
        self.rejected("invalid_argument", "add_arc", sketch="Managed", cx=0, cy=0, radius=0,
                      start_angle=0, end_angle=1)
        self.call("inspect")
        self.assertEqual(self.doc.Managed.GeometryCount, 2)
        self.assertEqual(self.state["active_sketch_edit"], "Managed")
        self.call("undo")
        self.assertEqual(self.doc.Managed.GeometryCount, 1)
        self.call("redo")
        self.assertEqual(self.doc.Managed.GeometryCount, 2)
        self.call("finish_sketch_edit")
        self.assertIsNone(self.state["active_sketch_edit"])
        self.assert_fully_constrained(self.doc.Managed)
        self.assertEqual(self.joined(self.doc.Managed), [(0, 1)])
        self.call("undo")
        self.assertIsNone(self.doc.getObject("Managed"))

    def test_invalid_arc_requests_reject_without_changing_the_sketch(self):
        self.call("create_sketch", id="Target")
        self.call("add_line", sketch="Target", x1=0, y1=0, x2=10, y2=0)
        base = {"sketch": "Target", "cx": 0, "cy": 0}
        cases = [
            ("mixed forms", {"radius": 2, "start_angle": 0, "end_angle": 1, "x1": 2, "y1": 0}),
            ("missing end_angle", {"radius": 2, "start_angle": 0}),
            ("missing y2", {"x1": 2, "y1": 0, "x2": 0}),
            ("no form", {}),
            ("zero radius", {"radius": 0, "start_angle": 0, "end_angle": 1}),
            ("negative radius", {"radius": -2, "start_angle": 0, "end_angle": 1}),
            ("zero sweep", {"radius": 2, "start_angle": "30 deg", "end_angle": "30 deg"}),
            ("full turn", {"radius": 2, "start_angle": 0, "end_angle": "360 deg"}),
            ("over a turn", {"radius": 2, "start_angle": 0, "end_angle": "400 deg"}),
            ("length angle", {"radius": 2, "start_angle": "5 mm", "end_angle": 1}),
            ("unequal radii", {"x1": 2, "y1": 0, "x2": 0, "y2": 2.00001}),
            ("start on center", {"x1": 0, "y1": 0, "x2": 0, "y2": 2}),
            ("coincident endpoints", {"x1": 2, "y1": 0, "x2": 2, "y2": 0}),
            ("non-boolean construction", {"radius": 2, "start_angle": 0, "end_angle": 1, "construction": 1}),
            ("missing center", {"cx": None, "radius": 2, "start_angle": 0, "end_angle": 1}),
        ]
        before = (self.doc.Target.GeometryCount, self.doc.Target.ConstraintCount)
        for label, args in cases:
            with self.subTest(label):
                request = {key: value for key, value in dict(base, **args).items() if value is not None}
                self.rejected("invalid_argument", "add_arc", **request)
                self.assertEqual((self.doc.Target.GeometryCount, self.doc.Target.ConstraintCount), before)
        self.rejected("unknown_argument", "add_arc", diameter=4, **base, radius=2, start_angle=0, end_angle=1)
        # Radii equal within 1e-6 are accepted in the endpoint form.
        self.call("add_arc", sketch="Target", x1=2, y1=5, x2=0, y2=7.0000005, cx=0, cy=5)
        self.assert_fully_constrained(self.doc.Target)


if __name__ == "__main__":
    unittest.main(verbosity=2)
