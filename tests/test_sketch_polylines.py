"""Native connected polylines: shared vertices, joins, edits, solids and rejection; bundled Python."""
from pathlib import Path
import math
import sys
import unittest
from unittest import mock
import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
from kurtshape.core import Controller, OperationError
from kurtshape import studio
from test_build_status import no_kernel_checks


def shoelace(points):
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]))) / 2


class SketchPolylineTests(unittest.TestCase):
    def setUp(self):
        self.initial_names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="sketch-polyline-session-")
        self.core = Controller()
        self.state = self.call("new", name="Sketch polyline acceptance")
        # Polylines are interactive sketch operations: no BRepCheck anywhere on these paths.
        self.enterContext(no_kernel_checks(self))

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

    def assert_one_closed_wire(self, sk):
        self.assertEqual(len(sk.Shape.Wires), 1)
        self.assertTrue(sk.Shape.Wires[0].isClosed())

    def assert_point(self, sk, geometry, pos, expected):
        self.assertLess(sk.getPoint(geometry, pos).distanceToPoint(App.Vector(*expected, 0)), 1e-9)

    def test_closed_hexagon_pads_and_one_vertex_edit_moves_the_shared_corner(self):
        r = 10
        hexagon = [(r * math.cos(math.radians(60 * k)), r * math.sin(math.radians(60 * k))) for k in range(6)]
        hexagon = [(round(x, 12) + 0.0, round(y, 12) + 0.0) for x, y in hexagon]
        self.call("create_sketch", id="Hex")
        self.call("add_polyline", sketch="Hex", points=[list(p) for p in hexagon], closed=True)
        sk = self.doc.Hex
        self.assert_fully_constrained(sk)
        self.assertEqual(sk.GeometryCount, 6)
        # One native Coincident per shared vertex, closing segment included.
        self.assertEqual(self.joined(sk), [(0, 1), (0, 5), (1, 2), (2, 3), (3, 4), (4, 5)])
        for k, point in enumerate(hexagon):
            self.assert_point(sk, k, 1, point)
            self.assert_point(sk, (k - 1) % 6, 2, point)
        parameters = self.parameters("Hex")
        # Vertices 1 and 4 lie on the X axis: an axis constraint replaces their Y dimension.
        self.assertEqual(sorted(parameters), ["P1X", "P2X", "P2Y", "P3X", "P3Y", "P4X", "P5X", "P5Y", "P6X", "P6Y"])
        for name, info in parameters.items():
            self.assertEqual(info["constraint_type"], "Distance" + name[-1])
            self.assertEqual(info["unit"], "mm")
            self.assertTrue(info["editable"])
        self.assertAlmostEqual(parameters["P2Y"]["value"], r * math.sqrt(3) / 2, places=9)
        self.assertEqual([c.Type for c in sk.Constraints].count("PointOnObject"), 2)
        self.assert_one_closed_wire(sk)
        self.call("pad", id="HexPad", profile="Hex", length=4)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, 3 * math.sqrt(3) / 2 * r ** 2 * 4, places=6)
        self.assertEqual(self.state["build_status"], "valid")
        # Editing one vertex moves the shared corner: both neighbours follow and the wire stays closed.
        self.call("set_parameter", feature="Hex", parameter="P2Y", value=12)
        self.assert_fully_constrained(sk)
        moved = [hexagon[0], (hexagon[1][0], 12)] + hexagon[2:]
        self.assert_point(sk, 0, 2, moved[1])
        self.assert_point(sk, 1, 1, moved[1])
        self.assert_one_closed_wire(sk)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, shoelace(moved) * 4, places=6)
        # Signed coordinate dimensions accept negative values.
        self.call("set_parameter", feature="Hex", parameter="P4X", value=-12)
        moved[3] = (-12, 0)
        self.assert_point(sk, 2, 2, moved[3])
        self.assert_point(sk, 3, 1, moved[3])
        self.assert_one_closed_wire(sk)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, shoelace(moved) * 4, places=6)

    def test_open_polyline_closed_by_an_arc_joined_at_both_ends_pads_and_edits(self):
        self.call("create_sketch", id="Tab")
        self.call("add_polyline", sketch="Tab", points=[[0, 10], [0, 0], [20, 0], [20, 10]])
        sk = self.doc.Tab
        self.assert_fully_constrained(sk)
        self.assertEqual(self.joined(sk), [(0, 1), (1, 2)])
        # The origin vertex is coincident with the sketch origin; zero coordinates use axis constraints.
        self.assertEqual(sorted(self.parameters("Tab")), ["P1Y", "P3X", "P4X", "P4Y"])
        self.assertEqual(len(sk.Shape.Wires), 1)
        self.assertFalse(sk.Shape.Wires[0].isClosed())
        # Counter-clockwise from (20, 10) over the top to (0, 10): both ends join the polyline.
        self.call("add_arc", sketch="Tab", x1=20, y1=10, x2=0, y2=10, cx=10, cy=10)
        self.assert_fully_constrained(sk)
        self.assertEqual(self.joined(sk), [(0, 1), (0, 3), (1, 2), (2, 3)])
        self.assertEqual(sorted(self.parameters("Tab")), ["P1Y", "P3X", "P4X", "P4Y", "Sweep"])
        self.assert_one_closed_wire(sk)
        self.call("pad", id="TabPad", profile="Tab", length=3)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, (20 * 10 + math.pi * 10 ** 2 / 2) * 3, places=6)
        # Widening the open side carries the joined arc: its ends follow and the semicircle grows.
        self.call("set_parameter", feature="Tab", parameter="P4X", value=30)
        self.call("set_parameter", feature="Tab", parameter="P3X", value=30)
        self.assert_fully_constrained(sk)
        self.assert_point(sk, 3, 1, (30, 10))
        self.assertAlmostEqual(sk.Geometry[3].Radius, 15, places=9)
        self.assert_one_closed_wire(sk)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, (30 * 10 + math.pi * 15 ** 2 / 2) * 3, places=6)

    def test_cup_revolve_profile_polylines_and_corner_arc_match_pappus_volume(self):
        self.call("create_sketch", id="Cup", plane="XZ")
        self.call("add_polyline", sketch="Cup", points=[[0, 0], [6, 0]])
        self.call("add_arc", sketch="Cup", cx=6, cy=4, radius=4, start_angle="-90 deg", end_angle="0 deg")
        # First vertex joins the fixed arc end, last vertex joins the floor line's origin start.
        self.call("add_polyline", sketch="Cup", points=[[10, 4], [10, 20], [0, 20], [0, 0]])
        sk = self.doc.Cup
        self.assert_fully_constrained(sk)
        self.assertEqual(self.joined(sk), [(0, 1), (0, 4), (1, 2), (2, 3), (3, 4)])
        # The wall polyline shares one suffix, because the floor polyline already took P2X.
        self.assertEqual(sorted(self.parameters("Cup")), ["CenterX", "CenterY", "P2X", "P2X_2", "P2Y_2", "P3Y_2", "Sweep"])
        self.assert_one_closed_wire(sk)
        self.call("revolve", id="CupSolid", profile="Cup", angle="360 deg", operation="new")
        self.assertEqual(self.doc.CupSolid.TypeId, "Part::Revolution")
        moment = 200 * 5 - 16 * 8 + 4 * math.pi * (6 + 4 * 4 / (3 * math.pi))
        volume = sum(obj.Shape.Volume for obj in studio.current_parts(self.doc))
        self.assertAlmostEqual(volume, 2 * math.pi * moment, places=5)
        # The cup corner is one shared vertex: moving the floor end carries the arc
        # and wall instead of opening a gap.
        self.call("set_parameter", feature="Cup", parameter="P2X", value=5)
        self.assert_fully_constrained(sk)
        self.assert_point(sk, 0, 2, (5, 0))
        self.assert_point(sk, 1, 1, (5, 0))
        self.assertLess(sk.getPoint(1, 2).distanceToPoint(sk.getPoint(2, 1)), 1e-9)
        self.assert_one_closed_wire(sk)
        self.assertNotAlmostEqual(sum(obj.Shape.Volume for obj in studio.current_parts(self.doc)), volume, places=3)

    def test_each_polyline_uses_one_suffix_for_all_its_vertices(self):
        # Zero coordinates take axis constraints (no name); names must still pair up per polyline.
        self.call("create_sketch", id="Names", plane="XY")
        self.call("add_polyline", sketch="Names", points=[[0, 5], [10, 5]])
        self.call("add_polyline", sketch="Names", points=[[3, 7], [8, 9]])
        self.call("add_polyline", sketch="Names", points=[[20, 0], [30, 4]])
        self.call("add_polyline", sketch="Names", points=[[1e-9, 40], [5, 40.0000000001]])
        sk = self.doc.Names
        self.assert_fully_constrained(sk)
        self.assertEqual(sorted(self.parameters("Names")),
                         ["P1X_2", "P1X_3", "P1Y", "P1Y_2", "P1Y_4", "P2X", "P2X_2", "P2X_3", "P2X_4",
                          "P2Y", "P2Y_2", "P2Y_3", "P2Y_4"])
        # P1X_2 moves the second polyline's start, never another polyline's vertex.
        self.call("set_parameter", feature="Names", parameter="P1X_2", value=4)
        self.assert_point(sk, 1, 1, (4, 7))
        self.assert_point(sk, 2, 1, (20, 0))
        # Coordinate noise within 1e-6 mm of an axis is an axis constraint, not a dimension.
        self.assert_point(sk, 3, 1, (0, 40))

    def test_polyline_joins_existing_line_ends_and_construction_never_joins(self):
        self.call("create_sketch", id="Mixed")
        self.call("add_line", sketch="Mixed", x1=2, y1=2, x2=12, y2=2)
        # Unlike add_line, a polyline vertex on a fixed line end joins it.
        self.call("add_polyline", sketch="Mixed", points=[[12, 2], [12, 8], [2, 8], [2, 2]])
        sk = self.doc.Mixed
        self.assert_fully_constrained(sk)
        self.assertEqual(self.joined(sk), [(0, 1), (0, 3), (1, 2), (2, 3)])
        self.assertEqual(sorted(name for name in self.parameters("Mixed") if name.startswith("P")),
                         ["P2X", "P2Y", "P3X", "P3Y"])
        self.assert_one_closed_wire(sk)
        # A vertex within the join tolerance takes the anchor's exact location.
        self.call("add_polyline", sketch="Mixed", points=[[12 + 4e-7, 8], [20, 8]])
        self.assert_fully_constrained(sk)
        self.assert_point(sk, 4, 1, (12, 8))
        self.assertIn((1, 4), self.joined(sk))
        # Construction polylines keep their own chain but never join profile geometry.
        previous = set(self.joined(sk))
        self.call("add_polyline", sketch="Mixed", points=[[20, 8], [20, 0], [30, 0]], construction=True)
        self.assertTrue(sk.getConstruction(5) and sk.getConstruction(6))
        self.assertEqual(sorted(set(self.joined(sk)) - previous), [(5, 6)])
        self.assertLess(sk.getPoint(5, 1).distanceToPoint(sk.getPoint(4, 2)), 1e-9)
        self.assert_fully_constrained(sk)

    def test_polyline_participates_in_managed_sketch_edit_undo_and_redo(self):
        self.call("create_sketch", id="Managed", plane="XZ")
        self.call("begin_sketch_edit", feature="Managed")
        self.call("add_polyline", sketch="Managed", points=[[0, 0], [10, 0], [5, 8]], closed=True)
        self.rejected("managed_sketch_mismatch", "add_polyline", sketch="Other", points=[[0, 0], [1, 1]])
        self.rejected("invalid_argument", "add_polyline", sketch="Managed", points=[[0, 0]])
        self.call("inspect")
        self.assertEqual(self.doc.Managed.GeometryCount, 3)
        self.assertEqual(self.state["active_sketch_edit"], "Managed")
        self.call("undo")
        self.assertEqual(self.doc.Managed.GeometryCount, 0)
        self.call("redo")
        self.assertEqual(self.doc.Managed.GeometryCount, 3)
        self.call("set_parameter", feature="Managed", parameter="P3Y", value=9)
        self.assert_point(self.doc.Managed, 1, 2, (5, 9))
        self.assert_point(self.doc.Managed, 2, 1, (5, 9))
        self.call("finish_sketch_edit")
        self.assertIsNone(self.state["active_sketch_edit"])
        sk = self.doc.Managed
        self.assert_fully_constrained(sk)
        self.assertEqual(self.joined(sk), [(0, 1), (0, 2), (1, 2)])
        self.assert_one_closed_wire(sk)
        self.call("pad", id="Prism", profile="Managed", length=2)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, 10 * 9 / 2 * 2, places=6)
        self.call("undo")
        self.call("undo")
        self.assertIsNone(self.doc.getObject("Managed"))
        self.call("redo")
        self.assertEqual(self.doc.Managed.GeometryCount, 3)

    def test_invalid_polyline_requests_reject_without_changing_the_sketch(self):
        self.call("create_sketch", id="Target")
        self.call("add_line", sketch="Target", x1=0, y1=0, x2=10, y2=0)
        base = {"sketch": "Target"}
        cases = [
            ("missing points", {}),
            ("points not a list", {"points": "0,0 1,1"}),
            ("no points", {"points": []}),
            ("one point", {"points": [[1, 1]]}),
            ("closed with two points", {"points": [[1, 1], [5, 5]], "closed": True}),
            ("repeated consecutive point", {"points": [[1, 1], [5, 1], [5, 1], [5, 5]]}),
            ("open loop repeats first point", {"points": [[1, 1], [5, 1], [5, 5], [1, 1]]}),
            ("closed loop repeats first point", {"points": [[1, 1], [5, 1], [5, 5], [1, 1]], "closed": True}),
            ("non-adjacent repeat", {"points": [[1, 1], [5, 1], [5, 5], [5, 1], [8, 8]]}),
            ("doubles back", {"points": [[1, 1], [5, 1], [3, 1]]}),
            ("closed collinear", {"points": [[1, 1], [3, 1], [5, 1]], "closed": True}),
            ("nan", {"points": [[1, 1], [float("nan"), 2]]}),
            ("infinity", {"points": [[1, 1], [float("inf"), 2]]}),
            ("not a number", {"points": [[1, 1], ["wide", 2]]}),
            ("angle quantity", {"points": [[1, 1], ["5 deg", 2]]}),
            ("boolean coordinate", {"points": [[1, 1], [True, 2]]}),
            ("triple", {"points": [[1, 1, 0], [2, 2, 0]]}),
            ("scalar point", {"points": [1, 2]}),
            ("too many points", {"points": [[k, k % 2] for k in range(1001)]}),
            ("non-boolean closed", {"points": [[1, 1], [5, 5]], "closed": 1}),
            ("non-boolean construction", {"points": [[1, 1], [5, 5]], "construction": "yes"}),
            # 1.5e-6 apart, both within the join tolerance of the line end: they would collapse.
            ("two points join one end", {"points": [[1, 5], [10 - 7.5e-7, 0], [10 + 7.5e-7, 0]]}),
        ]
        sk = self.doc.Target
        before = (sk.GeometryCount, sk.ConstraintCount, self.state["revision"])
        for label, args in cases:
            with self.subTest(label):
                self.rejected("invalid_argument", "add_polyline", **dict(base, **args))
                self.assertEqual((sk.GeometryCount, sk.ConstraintCount), before[:2])
        hint = self.rejected("invalid_argument", "add_polyline", sketch="Target",
                             points=[[1, 1], [5, 1], [5, 5], [1, 1]])["error"]
        self.assertIn("closed=true", hint["message"])
        self.assertEqual(hint["points"], [1, 4])
        self.rejected("unknown_argument", "add_polyline", sketch="Target", points=[[1, 1], [2, 2]], x1=0)
        # Preview evaluates in a disposable clone and reports invalid input without failing.
        for points, valid in (([[1, 1], [4, 1], [4, 3]], True), ([[1, 1]], False)):
            preview = self.request("preview", proposal={"op": "add_polyline", "sketch": "Target", "points": points,
                                                        "closed": valid})
            self.assertTrue(preview["ok"], preview)
            self.assertEqual(preview["result"]["valid"], valid, preview)
        # A late solver check failure rolls back the added segments and constraints.
        with mock.patch.object(Controller, "_require_fixed",
                               side_effect=OperationError("constraint_conflict", "forced late failure")):
            self.rejected("constraint_conflict", "add_polyline", sketch="Target", points=[[1, 1], [4, 1], [4, 3]])
        self.assertEqual(self.call("inspect")["revision"], before[2])
        self.assertEqual((sk.GeometryCount, sk.ConstraintCount), before[:2])
        # Quantity strings in millimetres are accepted.
        self.call("add_polyline", sketch="Target", points=[["10 mm", 0], ["1 cm", "5 mm"]])
        self.assert_fully_constrained(sk)
        self.assertEqual(self.joined(sk), [(0, 1)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
