"""Geometry selectors filter by native radii and report usable element geometry."""
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
from kurtshape import geometry, selectors
from kurtshape.core import Controller, OperationError


class SelectorParameterTests(unittest.TestCase):
    """Plate 40x20x6 with a central through hole (r=2) and two bosses (r=3, r=5) of height 4."""

    def setUp(self):
        self.names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="selector-parameters-session-")
        self.core = Controller()
        self.state = self.call("new", name="Selector parameter acceptance")
        self.call("sketch_rectangle", id="Plate", width=40, height=20)
        self.call("pad", id="Pad", profile="Plate", length=6)
        self.call("sketch_circle", id="Bosses", body="Body", support=self.top(), x=10, y=10, diameter=6)
        self.call("add_circle", sketch="Bosses", x=28, y=10, diameter=10)
        self.call("pad", id="BossPad", profile="Bosses", body="Body", length=4)
        self.call("sketch_circle", id="Hole", body="Body", x=20, y=10, diameter=4)
        self.call("pocket", id="HolePocket", profile="Hole", body="Body", through_all=True)

    def tearDown(self):
        self.core.close()
        for name in set(App.listDocuments()) - self.names:
            App.closeDocument(name)

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def request(self, op, **args):
        request = {"op": op, "measure": False, **args}
        if op not in {"new", "open"}:
            request.update(document_id=self.state["document_id"], expected_revision=self.state["revision"])
        return self.core.dispatch(request)

    def call(self, op, **args):
        response = self.request(op, **args)
        self.assertTrue(response["ok"], response)
        if "document_id" in response["result"]:
            self.state = response["result"]
        return response["result"]

    def top(self):
        return {"kind": "created_by", "feature": "Pad", "cap": "end"}

    def owned(self, entity_type="face"):
        return {"kind": "owned_by", "part": "Body", "entity_type": entity_type}

    def shape(self, row):
        return self.doc.getObject(row["feature"]).Shape.getElement(row["subelement"])

    def matches(self, selector):
        return self.call("resolve_selector", selector=selector)["matches"]

    def filtered(self, geometry_name, entity_type="face", **parameters):
        return {"kind": "geometry", "geometry": geometry_name, "query": self.owned(entity_type), **parameters}

    def test_radius_filters_select_cylinders_and_circles_with_usable_geometry(self):
        self.assertEqual(len(self.matches(self.filtered("cylinder"))), 3)
        for radius, x in ((2, 20), (3, 10), (5, 28)):
            faces = self.matches(self.filtered("cylinder", radius=radius))
            self.assertEqual(len(faces), 1, (radius, faces))
            summary = faces[0]["summary"]
            self.assertAlmostEqual(summary["radius_mm"], radius)
            self.assertAlmostEqual(abs(summary["axis"][2]), 1)
            self.assertAlmostEqual(summary["axis_point_mm"][0], x)
            self.assertAlmostEqual(summary["axis_point_mm"][1], 10)
            self.assertIn("center_mm", summary)
            self.assertIn("area_mm2", summary)
            self.assertNotIn("normal", summary)
        circles = self.matches(self.filtered("circle", "edge", radius=5))
        self.assertEqual(sorted(round(row["summary"]["geometric_center_mm"][2], 9) for row in circles), [6, 10])
        for row in circles:
            self.assertAlmostEqual(row["summary"]["radius_mm"], 5)
            self.assertEqual([round(value, 9) for value in row["summary"]["geometric_center_mm"][:2]], [28, 10])
            self.assertAlmostEqual(abs(row["summary"]["axis"][2]), 1)
        self.assertEqual(len(self.matches(self.filtered("circle", "edge", radius=2))), 2)
        self.assertEqual(self.matches(self.filtered("circle", "edge", radius=5.0005)), [])
        self.assertEqual(len(self.matches(self.filtered("circle", "edge", radius=5.0005, tolerance=1e-3))), 2)
        self.assertEqual(len(self.matches(self.filtered("cylinder", radius=4, tolerance=1.5))), 2)
        lines = self.matches(self.filtered("line", "edge"))
        self.assertTrue(lines)
        for row in lines:
            edge = self.shape(row)
            direction = App.Vector(*row["summary"]["direction"])
            self.assertAlmostEqual(direction.Length, 1)
            expected = edge.valueAt(edge.LastParameter) - edge.valueAt(edge.FirstParameter)
            self.assertLess((direction - expected.normalize()).Length, 1e-9)
        planes = self.matches(self.filtered("plane"))
        self.assertTrue(all(len(row["summary"]["normal"]) == 3 for row in planes))
        self.assertTrue(all("radius_mm" not in row["summary"] for row in planes))
        # Ordinary internal resolution keeps the cheap summary and its parity oracle.
        plain = selectors.resolve(self.doc, self.filtered("cylinder", radius=5))
        self.assertNotIn("point_mm", plain[0]["summary"])
        self.assertEqual(plain, selectors._resolve_full(self.doc, self.filtered("cylinder", radius=5)))
        detailed = selectors.resolve(self.doc, self.filtered("circle", "edge", radius=5), detail=True)
        self.assertEqual(detailed, selectors._resolve_full(self.doc, self.filtered("circle", "edge", radius=5), detail=True))

    def test_point_mm_lies_on_every_edge_and_face_and_picks_it_back(self):
        for entity_type in ("face", "edge"):
            rows = self.matches(self.owned(entity_type))
            self.assertTrue(rows)
            for row in rows:
                element = self.shape(row)
                point = App.Vector(*row["summary"]["point_mm"])
                self.assertLess(element.distToShape(Part.Vertex(point))[0], 1e-7, row)
                picked = selectors.resolve(self.doc, {"kind": "closest", "point": row["summary"]["point_mm"],
                                                      "query": self.owned(entity_type)})
                self.assertEqual([(value["feature"], value["subelement"]) for value in picked],
                                 [(row["feature"], row["subelement"])], row)
        # The plate's bottom face is trimmed by the central hole: its parametric
        # centre lies in the hole, so the reported point comes from a fallback.
        bottom = [row for row in self.matches(self.filtered("plane"))
                  if abs(row["summary"]["center_mm"][2]) < 1e-9]
        self.assertEqual(len(bottom), 1)
        face = self.shape(bottom[0])
        u0, u1, v0, v1 = face.ParameterRange
        self.assertFalse(face.isPartOfDomain((u0 + u1) / 2, (v0 + v1) / 2))
        point = App.Vector(*bottom[0]["summary"]["point_mm"])
        self.assertLess(face.distToShape(Part.Vertex(point))[0], 1e-9)
        self.assertGreater(Part.Compound(face.Edges).distToShape(Part.Vertex(point))[0], 1e-6)

    def test_face_point_fallbacks_for_thin_and_holed_faces(self):
        disk = Part.Face(Part.Wire(Part.makeCircle(10)))
        ring = disk.cut(Part.Face(Part.Wire(Part.makeCircle(9.9)))).Faces[0]
        slot = Part.makeBox(30, 0.02, 1).Faces
        tube = Part.makeCylinder(5, 8).cut(Part.makeBox(20, 20, 20, App.Vector(-10, -10, 2)))
        for face in [ring, *slot, *tube.Faces]:
            point = selectors._face_point(face, list(face.CenterOfMass))
            self.assertLess(face.distToShape(Part.Vertex(point))[0], 1e-9)
            if face.Area > 1e-3:
                self.assertGreater(Part.Compound(face.Edges).distToShape(Part.Vertex(point))[0], 1e-6, face.Area)

    def test_sphere_cone_and_ellipse_parameters_on_native_primitives(self):
        doc = App.newDocument("SelectorPrimitiveParameters")
        doc.addObject("Part::Sphere", "Ball").Radius = 4
        doc.Ball.Placement.Base = App.Vector(50, 0, 0)
        cone = doc.addObject("Part::Cone", "Taper")
        cone.Radius1, cone.Radius2, cone.Height = 5, 2, 10
        cone.Placement.Base = App.Vector(0, 50, 0)
        ellipse = doc.addObject("Part::Ellipse", "Oval")
        ellipse.MajorRadius, ellipse.MinorRadius = 6, 2
        ellipse.Placement = App.Placement(App.Vector(-50, 0, 3), App.Rotation(App.Vector(1, 0, 0), 90))
        doc.recompute()

        def faces(name, **parameters):
            return selectors.resolve(doc, {"kind": "geometry", "geometry": name, "query": {"kind": "all"}, **parameters}, detail=True)

        def edges(name, **parameters):
            return selectors.resolve(doc, {"kind": "geometry", "geometry": name,
                                           "query": {"kind": "all", "entity_type": "edge"}, **parameters}, detail=True)

        def on_element(row):
            element = doc.getObject(row["feature"]).Shape.getElement(row["subelement"])
            return element.distToShape(Part.Vertex(App.Vector(*row["summary"]["point_mm"])))[0] < 1e-7

        ball = faces("sphere", radius=4)
        self.assertEqual(len(ball), 1)
        self.assertEqual([round(value, 9) for value in ball[0]["summary"]["geometric_center_mm"]], [50, 0, 0])
        self.assertAlmostEqual(ball[0]["summary"]["radius_mm"], 4)
        self.assertTrue(on_element(ball[0]))
        self.assertEqual(faces("sphere", radius=5), [])
        taper = faces("cone", radius=5)
        self.assertEqual(len(taper), 1)
        summary = taper[0]["summary"]
        self.assertEqual([round(value, 9) for value in summary["axis_point_mm"]], [0, 50, 0])
        self.assertEqual([round(value, 9) for value in summary["axis"]], [0, 0, 1])
        self.assertAlmostEqual(summary["semi_angle_rad"], -math.atan2(3, 10))
        self.assertEqual([round(value, 9) for value in summary["apex_mm"]], [0, 50, round(50 / 3, 9)])
        self.assertTrue(on_element(taper[0]))
        self.assertEqual(faces("cone", radius=2), [])
        self.assertEqual(len(edges("circle", radius=2)), 1)
        oval = edges("ellipse", major_radius=6, minor_radius=2)
        self.assertEqual(len(oval), 1)
        self.assertEqual([round(value, 9) for value in oval[0]["summary"]["geometric_center_mm"]], [-50, 0, 3])
        self.assertEqual([round(abs(value), 9) for value in oval[0]["summary"]["axis"]], [0, 1, 0])
        self.assertTrue(on_element(oval[0]))
        self.assertEqual(edges("ellipse", major_radius=2), [])
        with self.assertRaises(OperationError):
            edges("ellipse", radius=6)
        # Sphere poles are degenerated native edges without a 3D curve: they
        # no longer break edge geometry filters and still report a point.
        everything = selectors.resolve(doc, {"kind": "all", "entity_type": "edge"}, detail=True)
        poles = [row for row in everything if row["summary"]["geometry"] == "degenerate"]
        self.assertEqual(len(poles), 2)
        self.assertEqual(sorted(round(row["summary"]["point_mm"][2], 9) for row in poles), [-4, 4])
        self.assertEqual(len(edges("circle", radius=4)), 1)
        self.assertTrue(all(on_element(row) for row in everything + faces("plane")))

    def test_torus_major_and_minor_radius_filters(self):
        self.call("fillet", id="Round", edges=[self.filtered("circle", "edge", radius=5) | {
            "query": {"kind": "created_by", "feature": "BossPad", "entity_type": "edge", "cap": "end"}}], radius=1)
        tori = self.matches(self.filtered("torus"))
        self.assertEqual(len(tori), 1)
        summary = tori[0]["summary"]
        self.assertAlmostEqual(summary["major_radius_mm"], 4)
        self.assertAlmostEqual(summary["minor_radius_mm"], 1)
        self.assertEqual([round(value, 9) for value in summary["geometric_center_mm"]], [28, 10, 9])
        self.assertAlmostEqual(abs(summary["axis"][2]), 1)
        self.assertLess(self.shape(tori[0]).distToShape(Part.Vertex(App.Vector(*summary["point_mm"])))[0], 1e-7)
        self.assertEqual(len(self.matches(self.filtered("torus", major_radius=4))), 1)
        self.assertEqual(len(self.matches(self.filtered("torus", minor_radius=1))), 1)
        self.assertEqual(len(self.matches(self.filtered("torus", major_radius=4, minor_radius=1))), 1)
        self.assertEqual(self.matches(self.filtered("torus", major_radius=4, minor_radius=2)), [])
        self.assertEqual(self.matches(self.filtered("torus", major_radius=5)), [])
        self.assertEqual(len(self.matches(self.filtered("torus", major_radius=4.01, tolerance=0.02))), 1)

    def test_fillet_from_radius_selector_follows_parameter_edit_and_rebuild(self):
        edge = {"kind": "geometry", "geometry": "circle", "radius": 5,
                "query": {"kind": "created_by", "feature": "BossPad", "entity_type": "edge", "cap": "end"}}
        with patch.object(selectors, "_detail", side_effect=AssertionError("Consumers must not build detailed summaries")):
            self.call("fillet", id="Round", edges=[edge], radius=1)
        stored = json.loads(self.doc.Round.QueryInputs)["edges_0"]["selector"]
        self.assertEqual(stored, edge)

        def rounded_edge():
            base, names = self.doc.Round.Base
            curve = base.Shape.getElement(names[0]).Curve
            self.assertIsInstance(curve, Part.Circle)
            return round(curve.Radius, 9), [round(value, 9) for value in curve.Center]

        def assert_healthy():
            self.assertTrue(all(entry["status"] == "healthy" for entry in json.loads(self.doc.Round.QueryHealth)))
            self.assertFalse(selectors.reference_errors(self.doc))

        self.assertEqual(rounded_edge(), (5, [28, 10, 10]))
        assert_healthy()
        volume = self.doc.Body.Shape.Volume
        # Raise the bosses and add a third one: the r=5 top circle moves and
        # the native edges are renumbered.
        names = self.doc.Round.Base[1]
        self.call("set_parameter", feature="BossPad", parameter="Length", value=7)
        self.call("add_circle", sketch="Bosses", x=4, y=4, diameter=2)
        with patch.object(selectors, "_detail", side_effect=AssertionError("Rebuild must not build detailed summaries")):
            self.call("rebuild")
        self.assertEqual(rounded_edge(), (5, [28, 10, 13]))
        assert_healthy()
        tori = self.matches(self.filtered("torus", major_radius=4, minor_radius=1))
        self.assertEqual(len(tori), 1)
        self.assertAlmostEqual(tori[0]["summary"]["geometric_center_mm"][2], 12)
        self.assertGreater(self.doc.Body.Shape.Volume, volume)
        self.assertNotEqual(self.doc.Round.Base[1], names)
        # An edit that leaves no r=5 circle cannot substitute another edge.
        revision = self.state["revision"]
        rejected = self.request("set_parameter", feature="Bosses", parameter="Diameter_2", value=12)
        self.assertFalse(rejected["ok"], rejected)
        self.assertEqual(rejected["error"]["code"], "build_failed")
        self.assertIn("edges_0", json.dumps(rejected["error"]))
        self.assertEqual(self.call("inspect")["revision"], revision)
        self.assertEqual(rounded_edge(), (5, [28, 10, 13]))
        assert_healthy()

    def test_ambiguous_radius_selector_reports_detailed_matches(self):
        response = self.request("fillet", id="Round", edges=[self.filtered("circle", "edge", radius=5)], radius=1)
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], "ambiguous_reference")
        self.assertIsNone(self.doc.getObject("Round"))
        matches = response["error"]["matches"]
        self.assertEqual(len(matches), 2)
        self.assertTrue(all(row["summary"]["radius_mm"] == 5 and len(row["summary"]["point_mm"]) == 3 for row in matches))

    def test_radius_filter_reuses_cached_scalars(self):
        provider = geometry.provider(self.doc)
        self.assertIsNotNone(provider)
        selector = self.filtered("circle", "edge", radius=5)
        first = selectors.resolve(self.doc, selector)
        before = provider.stats["memo"]["selector_scalar"]
        self.assertEqual(selectors.resolve(self.doc, selector), first)
        self.assertEqual(len(selectors.resolve(self.doc, dict(selector, tolerance=1e-3))), 2)
        self.assertEqual(provider.stats["memo"]["selector_scalar"], before)
        self.matches(selector)
        detailed = provider.stats["memo"]["selector_scalar"]
        self.assertGreater(detailed, before)
        self.matches(selector)
        self.assertEqual(provider.stats["memo"]["selector_scalar"], detailed)

    def test_vertex_rows_summarize_and_huge_numbers_reject_cleanly(self):
        # Part.Vertex has no CenterOfMass; vertex rows used to fail with operation_failed.
        rows = self.matches(self.owned("vertex"))
        self.assertTrue(rows)
        for row in rows[:4]:
            point = self.shape(row).Point
            self.assertAlmostEqual(App.Vector(*row["summary"]["center_mm"]).distanceToPoint(point), 0, places=9)
            self.assertAlmostEqual(App.Vector(*row["summary"]["point_mm"]).distanceToPoint(point), 0, places=9)
        self.assertTrue(self.matches({"kind": "geometry", "geometry": "point", "query": self.owned("vertex")}))
        # A JSON integer too large for a float is invalid input, not an internal failure.
        huge = 10 ** 400
        for selector in (self.filtered("cylinder", radius=huge),
                         {"kind": "closest", "point": [huge, 0, 0], "query": self.owned()}):
            response = self.request("resolve_selector", selector=selector)
            self.assertFalse(response["ok"], response)
            self.assertEqual(response["error"]["code"], "invalid_selector", response["error"])

    def test_schema_rejects_parameters_without_meaning(self):
        invalid = [
            self.filtered("plane", radius=5),
            self.filtered("line", "edge", radius=5),
            self.filtered("torus", radius=4),
            self.filtered("cylinder", major_radius=5),
            self.filtered("circle", "edge", minor_radius=1),
            self.filtered("cylinder", radius=0),
            self.filtered("cylinder", radius=-5),
            self.filtered("cylinder", radius="5 mm"),
            self.filtered("cylinder", radius=True),
            self.filtered("cylinder", radius=math.nan),
            self.filtered("cylinder", radius=math.inf),
            self.filtered("cylinder", tolerance=1e-3),
            self.filtered("cylinder", radius=5, tolerance=-1),
            self.filtered("cylinder", radius=5, tolerance=None),
            self.filtered("cylinder", radius=5, radii=[5]),
            {"kind": "closest", "point": [0, 0, 0], "radius": 5, "query": self.owned()},
            {"kind": "owned_by", "part": "Body", "radius": 5},
        ]
        revision = self.state["revision"]
        for selector in invalid:
            with self.assertRaises(OperationError) as raised:
                selectors.resolve(self.doc, selector)
            self.assertEqual(raised.exception.code, "invalid_selector", selector)
            response = self.request("resolve_selector", selector=selector)
            self.assertFalse(response["ok"], selector)
            self.assertEqual(response["error"]["code"], "invalid_selector", selector)
        unknown = self.request("resolve_selector", selector=self.filtered("cylinder", radius=5, radii=[5]))
        self.assertEqual(unknown["error"]["fields"], ["radii"])
        rejected = self.request("fillet", id="Round", edges=[self.filtered("line", "edge", radius=5)], radius=1)
        self.assertFalse(rejected["ok"], rejected)
        self.assertEqual(rejected["error"]["code"], "invalid_selector")
        self.assertIsNone(self.doc.getObject("Round"))
        self.assertEqual(self.call("inspect")["revision"], revision)


if __name__ == "__main__":
    unittest.main()
