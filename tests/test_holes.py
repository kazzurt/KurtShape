"""Native PartDesign Hole: depth convention, profiles, history, persistence, rejections.

Depth convention under test: ``depth`` is the full-diameter (cylindrical)
depth from the sketch plane to the start of the drill point; an angled point
adds a cone of height r / tan(point_angle / 2) beyond it.
"""
from pathlib import Path
import json
import math
import subprocess
import sys
import unittest

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
from kurtshape.core import Controller, intent_signature
from kurtshape import studio
from kurtshape.sketch_tools import unconsumed_sketches
from test_build_status import no_kernel_checks

BLOCK = 20 * 20 * 10


def cylinder(radius, depth):
    return math.pi * radius * radius * depth


def cone(radius, point_angle_deg=118.0):
    tip = radius / math.tan(math.radians(point_angle_deg) / 2)
    return math.pi * radius * radius * tip / 3, tip


class HoleTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="hole-session-")
        self.core = Controller()
        self.state = None

    def tearDown(self):
        self.core.close()
        for name in set(App.listDocuments()) - self.names:
            App.closeDocument(name)

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def request(self, op, **args):
        request = dict(op=op, **args)
        if op not in {"new", "open"}:
            request.update(document_id=self.state["document_id"], expected_revision=self.state["revision"])
        return self.core.dispatch(request)

    def call(self, op, **args):
        response = self.request(op, **args)
        self.assertTrue(response["ok"], response)
        if "document_id" in response["result"]:
            self.state = response["result"]
        return response["result"]

    def block(self):
        """20 x 20 x 10 studio part 'Body' (z 0..10) and an empty authoring Body 'Sketches'."""
        self.call("new", name="Holes")
        self.call("sketch_rectangle", id="Plate", width=20, height=20, x=-10, y=-10)
        self.call("pad", id="Block", profile="Plate", length=10, operation="new")
        self.call("create_body", id="Sketches")
        self.call("create_plane", id="Top", body="Sketches", base_plane="XY", offset=10)

    def hole_sketch(self, sid="HS", circles=((3, 2),), diameter=1.6, body="Sketches", support_plane="Top"):
        self.call("create_sketch", id=sid, support={"feature": support_plane}, body=body)
        for x, y in circles:
            self.call("add_circle", sketch=sid, body=body, x=x, y=y, diameter=diameter)

    def native_points(self, sketch, points):
        """Sketch points have no typed operation yet; add them natively, then refresh."""
        sk = self.doc.getObject(sketch)
        for x, y in points:
            sk.addGeometry(Part.Point(App.Vector(x, y, 0)))
        self.doc.recompute()
        self.call("inspect")

    def part_volume(self):
        return studio.current_part(self.doc, "Body").Shape.Volume

    def removed(self, before):
        return before - self.part_volume()

    def snapshot(self):
        return (intent_signature(self.doc), self.doc.UndoCount, self.core.inspect(self.doc)["revision"],
                sorted(obj.Name for obj in self.doc.Objects))

    def assertVector(self, actual, expected, tolerance=1e-6):
        actual, expected = App.Vector(*actual), App.Vector(*expected)
        self.assertLess((actual - expected).Length, tolerance, f"{actual} != {expected}")

    def apexes(self, feature):
        return sorted(tuple(round(c, 6) for c in face.Surface.Apex) for face in self.doc.getObject(feature).Shape.Faces
                      if isinstance(face.Surface, Part.Cone))

    def expected_apexes(self, centres, top=10, depth=4, radius=0.8):
        _, tip = cone(radius)
        return sorted(tuple(round(c, 6) for c in (x, y, top - depth - tip)) for x, y in centres)

    def helpers(self):
        return sorted(obj.Name for obj in self.doc.Objects if getattr(obj, "KurtShapeHoleHelper", False))

    def bound_elements(self, hole):
        """Sketch elements the centre binder currently resolves (natively re-resolved on renumbering)."""
        profile = self.doc.getObject(hole).Profile[0]
        binder = profile.ExternalGeometry[0][0]
        return list(binder.Support[0][1])

    def delete_geometry(self, sketch, index):
        """Sketches have no typed geometry delete yet; delete natively, then refresh."""
        sk = self.doc.getObject(sketch)
        sk.delGeometry(index)
        self.doc.recompute()
        self.call("inspect")

    def build_errors(self):
        return self.call("inspect")["build_errors"]

    # ------------------------------------------------------------------ geometry

    def test_blind_118_hole_is_cylinder_plus_cone_and_drills_against_the_normal(self):
        self.block()
        self.hole_sketch()
        undo = self.doc.UndoCount
        self.call("hole", id="Drill", part="Body", sketch="HS", diameter=1.6, depth=4)
        self.assertEqual(self.doc.UndoCount, undo + 1)
        point, tip = cone(0.8)
        self.assertAlmostEqual(self.removed(BLOCK), cylinder(0.8, 4) + point, places=6)
        hole = self.doc.Drill
        self.assertEqual(hole.TypeId, "PartDesign::Hole")
        self.assertEqual((str(hole.DrillPoint), hole.DrillForDepth, str(hole.DepthType)), ("Angled", False, "Dimension"))
        self.assertAlmostEqual(hole.DrillPointAngle.Value, 118)
        cones = [face.Surface for face in hole.Shape.Faces if isinstance(face.Surface, Part.Cone)]
        self.assertEqual(len(cones), 1)
        self.assertVector(cones[0].Apex, (3, 2, 10 - 4 - tip))
        # The sketch lives in another Body: an in-Body binder and internal sketch carry it.
        body = studio.current_part(self.doc, "Body")
        self.assertIn(hole, body.Group)
        self.assertEqual(body.Tip, hole)
        profile = hole.Profile[0]
        self.assertEqual(profile.TypeId, "Sketcher::SketchObject")
        self.assertTrue(profile.KurtShapeInternal and profile.KurtShapeHoleHelper)
        self.assertEqual(profile.AttachmentSupport[0][0].TypeId, "PartDesign::ShapeBinder")
        self.assertIn(profile.AttachmentSupport[0][0], body.Group)
        inspected = self.call("inspect")
        self.assertEqual(inspected["build_status"], "valid")
        self.assertIn("Drill", inspected["studio"]["feature_order"])
        self.assertNotIn(profile.Name, inspected["studio"]["feature_order"])
        self.assertEqual(next(part for part in inspected["studio"]["parts"] if part["id"] == "Body")["feature"], "Drill")
        row = next(feature for feature in inspected["features"] if feature["id"] == "Drill")
        self.assertEqual(row["type"], "PartDesign::Hole")
        self.assertNotIn("HS", [sketch.Name for sketch in unconsumed_sketches(self.doc)])

    def test_hole_diameter_depth_and_point_angle_are_editable_parameters(self):
        self.block()
        self.hole_sketch()
        self.call("hole", id="Drill", part="Body", sketch="HS", diameter=1.6, depth=4)
        params = next(f for f in self.call("inspect")["features"] if f["id"] == "Drill")["parameters"]
        self.assertEqual(sorted(params), ["Depth", "Diameter", "PointAngle"])
        self.assertAlmostEqual(params["PointAngle"]["value"], math.radians(118))
        self.call("set_parameter", feature="Drill", parameter="Depth", value=6)
        self.call("set_parameter", feature="Drill", parameter="Diameter", value=2)
        self.call("set_parameter", feature="Drill", parameter="PointAngle", value="90 deg")
        point, _ = cone(1.0, 90.0)
        self.assertAlmostEqual(self.removed(BLOCK), cylinder(1.0, 6) + point, places=6)
        self.call("undo")
        point, _ = cone(1.0)
        self.assertAlmostEqual(self.removed(BLOCK), cylinder(1.0, 6) + point, places=6)
        # Through-all holes have no depth or point to edit.
        self.hole_sketch(sid="HS2", circles=((-4, -4),))
        self.call("hole", id="Through", part="Body", sketch="HS2", diameter=2, end_type="through_all")
        params = next(f for f in self.call("inspect")["features"] if f["id"] == "Through")["parameters"]
        self.assertEqual(sorted(params), ["Diameter"])

    def test_sketch_in_the_part_body_is_the_native_profile(self):
        self.block()
        self.call("create_plane", id="PartTop", body="Body", base_plane="XY", offset=10)
        self.hole_sketch("Own", circles=((-4, 5),), diameter=2, body="Body", support_plane="PartTop")
        self.call("hole", id="Direct", part="Body", sketch="Own", diameter=2, depth=3, point_angle="90 deg")
        hole = self.doc.Direct
        self.assertEqual(hole.Profile[0].Name, "Own")
        self.assertEqual([obj.Name for obj in self.doc.Objects if getattr(obj, "KurtShapeHoleHelper", False)], [])
        point, _ = cone(1.0, 90)
        self.assertAlmostEqual(self.removed(BLOCK), cylinder(1.0, 3) + point, places=6)

    def test_flat_bottom_blind_hole(self):
        self.block()
        self.hole_sketch()
        self.call("hole", id="Flat", part="Body", sketch="HS", diameter=1.6, depth=4, point_angle="flat")
        self.assertEqual(str(self.doc.Flat.DrillPoint), "Flat")
        self.assertAlmostEqual(self.removed(BLOCK), cylinder(0.8, 4), places=6)
        self.call("undo")
        self.call("hole", id="Zero", part="Body", sketch="HS", diameter=1.6, depth=4, point_angle=0)
        self.assertAlmostEqual(self.removed(BLOCK), cylinder(0.8, 4), places=6)
        cut = studio.current_part(self.doc, "Body").Shape
        floor = [face for face in cut.Faces if isinstance(face.Surface, Part.Plane) and abs(face.Area - math.pi * .64) < 1e-6]
        self.assertEqual(len(floor), 1)
        self.assertAlmostEqual(floor[0].BoundBox.ZMin, 6, places=9)

    def test_through_all_hole(self):
        self.block()
        self.hole_sketch()
        self.call("hole", id="Through", part="Body", sketch="HS", diameter=1.6, end_type="through_all")
        self.assertEqual(str(self.doc.Through.DepthType), "ThroughAll")
        self.assertAlmostEqual(self.removed(BLOCK), cylinder(0.8, 10), places=6)
        rejected = self.request("hole", id="Mixed", part="Body", sketch="HS", diameter=1.6, end_type="through_all", depth=3)
        self.assertEqual(rejected["error"]["code"], "invalid_argument", rejected)

    def test_counterbore_and_countersink(self):
        self.block()
        self.hole_sketch()
        self.call("hole", id="Bore", part="Body", sketch="HS", diameter=1.6, depth=4,
                  counterbore={"diameter": 3, "depth": "1.5 mm"})
        point, _ = cone(0.8)
        expected = cylinder(1.5, 1.5) + cylinder(0.8, 4 - 1.5) + point
        self.assertAlmostEqual(self.removed(BLOCK), expected, places=6)
        self.assertEqual(str(self.doc.Bore.HoleCutType), "Counterbore")
        self.call("undo")
        self.call("hole", id="Sink", part="Body", sketch="HS", diameter=1.6, depth=4,
                  countersink={"diameter": 3, "angle": "90 deg"})
        height = (1.5 - 0.8) / math.tan(math.radians(45))
        frustum = math.pi * height / 3 * (1.5 ** 2 + 1.5 * 0.8 + 0.8 ** 2)
        self.assertAlmostEqual(self.removed(BLOCK), cylinder(0.8, 4) + point + frustum - cylinder(0.8, height), places=6)
        self.assertEqual(str(self.doc.Sink.HoleCutType), "Countersink")

    def test_several_holes_from_one_sketch_use_only_circles_and_points(self):
        self.block()
        self.hole_sketch(circles=((3, 2), (-5, -4)))
        self.call("add_circle", sketch="HS", body="Sketches", x=6, y=-6, diameter=1, construction=True)
        self.call("add_line", sketch="HS", body="Sketches", x1=-8, y1=7, x2=-2, y2=7)
        self.native_points("HS", [(5, 6)])
        self.call("hole", id="Pattern", part="Body", sketch="HS", diameter=1.6, depth=4)
        point, tip = cone(0.8)
        self.assertAlmostEqual(self.removed(BLOCK), 3 * (cylinder(0.8, 4) + point), places=6)
        apexes = sorted(tuple(round(c, 6) for c in face.Surface.Apex) for face in self.doc.Pattern.Shape.Faces
                        if isinstance(face.Surface, Part.Cone))
        self.assertEqual(apexes, sorted(tuple(round(c, 6) for c in (x, y, 10 - 4 - tip)) for x, y in ((3, 2), (-5, -4), (5, 6))))
        # The authored circles stay associative through the binder.
        self.call("set_parameter", feature="HS", parameter="CenterX", value=4)
        apexes = [face.Surface.Apex for face in self.doc.Pattern.Shape.Faces if isinstance(face.Surface, Part.Cone)]
        self.assertTrue(any((apex - App.Vector(4, 2, 10 - 4 - tip)).Length < 1e-6 for apex in apexes))
        self.assertAlmostEqual(self.removed(BLOCK), 3 * (cylinder(0.8, 4) + point), places=6)

    def test_holes_on_a_tilted_point_normal_plane_follow_the_plane_normal(self):
        self.block()
        normal = App.Vector(0.3, -0.8, 1.0).normalize()
        self.call("create_plane", id="Tilt", body="Sketches", origin=[0, 0, 10], normal=list(normal))
        frame = next(row for row in self.call("inspect")["features"] if row["id"] == "Tilt")["plane"]["frame"]
        origin, x, y = (App.Vector(*frame[key]) for key in ("origin_mm", "x_direction", "y_direction"))
        self.call("create_sketch", id="TS", support={"feature": "Tilt"}, body="Sketches")
        self.call("add_circle", sketch="TS", body="Sketches", x=2, y=1, diameter=1.2)
        self.native_points("TS", [(-3, -2)])
        with no_kernel_checks(self):
            self.call("hole", id="Tilted", part="Body", sketch="TS", diameter=1.2, depth=3)
        _, tip = cone(0.6)
        centres = [origin + x * 2 + y * 1, origin + x * -3 + y * -2]
        faces = self.doc.Tilted.Shape.Faces
        for centre in centres:
            self.assertTrue(any(isinstance(face.Surface, Part.Cone) and (face.Surface.Apex - (centre - normal * (3 + tip))).Length < 1e-6
                                for face in faces), centre)
            axes = [face.Surface for face in faces if isinstance(face.Surface, Part.Cylinder) and abs(face.Surface.Radius - .6) < 1e-9
                    and (face.Surface.Center - centre).cross(normal).Length < 1e-6]
            self.assertEqual(len(axes), 1, centre)
            self.assertLess(abs(abs(axes[0].Axis.dot(normal)) - 1), 1e-9)
        # Independent kernel tools give the same removed volume.
        block = Part.makeBox(20, 20, 10, App.Vector(-10, -10, 0))
        expected = 0.0
        for centre in centres:
            tool = Part.makeCylinder(0.6, 3, centre, -normal).fuse(Part.makeCone(0.6, 0, tip, centre - normal * 3, -normal))
            expected += tool.common(block).Volume
        self.assertAlmostEqual(self.removed(BLOCK), expected, places=6)

    def test_holes_on_a_moved_part_use_world_sketch_positions(self):
        self.block()
        self.call("transform_part", id="Move", part="Body", translation=[30, 5, 2],
                  rotation={"axis": [0, 0, 1], "angle": "30 deg"})
        self.call("create_plane", id="Lifted", body="Sketches", origin=[30, 5, 12], normal=[0, 0, 1], x_direction=[1, 0, 0])
        self.hole_sketch("Far", circles=((3, 2),), support_plane="Lifted")
        self.call("create_plane", id="PartTop", body="Body", origin=[30, 5, 12], normal=[0, 0, 1], x_direction=[1, 0, 0])
        self.hole_sketch("Near", circles=((-3, -2),), body="Body", support_plane="PartTop")
        self.call("hole", id="FarHole", part="Body", sketch="Far", diameter=1.6, depth=4)
        self.call("hole", id="NearHole", part="Body", sketch="Near", diameter=1.6, depth=4)
        self.assertEqual(self.doc.NearHole.Profile[0].Name, "Near")
        self.assertNotEqual(self.doc.FarHole.Profile[0].Name, "Far")
        point, tip = cone(0.8)
        self.assertAlmostEqual(self.removed(BLOCK), 2 * (cylinder(0.8, 4) + point), places=6)
        apexes = sorted(tuple(round(c, 6) for c in face.Surface.Apex)
                        for face in studio.current_part(self.doc, "Body").Shape.Faces if isinstance(face.Surface, Part.Cone))
        self.assertEqual(apexes, sorted(tuple(round(c, 6) for c in (x, y, 12 - 4 - tip)) for x, y in ((33, 7), (27, 3))))

    # ------------------------------------------------------------------ bridge associativity

    def test_centres_are_bound_by_geometry_id_after_earlier_geometry_was_deleted(self):
        # Geometry ids no longer equal list index + 1 once geometry is deleted:
        # the line is g1, the circles g2 and g3, the point g4.
        self.block()
        self.call("create_sketch", id="HS", support={"feature": "Top"}, body="Sketches")
        self.call("add_line", sketch="HS", body="Sketches", x1=-8, y1=7, x2=-2, y2=7)
        self.call("add_circle", sketch="HS", body="Sketches", x=3, y=2, diameter=1.6)
        self.call("add_circle", sketch="HS", body="Sketches", x=-5, y=-4, diameter=1.6)
        self.native_points("HS", [(5, 6)])
        self.delete_geometry("HS", 0)
        sketch = self.doc.HS
        self.assertEqual([sketch.getGeometryId(index) for index in range(sketch.GeometryCount)], [2, 3, 4])
        self.call("hole", id="Drill", part="Body", sketch="HS", diameter=1.6, depth=4)
        centres = ((3, 2), (-5, -4), (5, 6))
        self.assertEqual(self.apexes("Drill"), self.expected_apexes(centres))
        point, _ = cone(0.8)
        self.assertAlmostEqual(self.removed(BLOCK), 3 * (cylinder(0.8, 4) + point), places=6)
        profile = self.doc.Drill.Profile[0]
        self.assertEqual(list(profile.KurtShapeHoleCentres), ["point:4", "circle:2", "circle:3"])
        self.assertEqual(self.call("inspect")["build_status"], "valid")

    def test_holes_stay_on_their_centres_when_sketch_edits_renumber_the_shape(self):
        self.block()
        self.call("create_sketch", id="HS", support={"feature": "Top"}, body="Sketches")
        self.call("add_polyline", sketch="HS", body="Sketches", points=[[-9, -9], [-6, -9], [-6, -6]])
        self.call("add_line", sketch="HS", body="Sketches", x1=-8, y1=7, x2=-2, y2=7)
        self.call("add_circle", sketch="HS", body="Sketches", x=3, y=2, diameter=1.6)
        self.call("add_circle", sketch="HS", body="Sketches", x=-5, y=-4, diameter=1.6)
        self.native_points("HS", [(5, 6)])
        self.call("hole", id="Drill", part="Body", sketch="HS", diameter=1.6, depth=4)
        centres = [(3, 2), (-5, -4), (5, 6)]
        point, _ = cone(0.8)
        drilled = 3 * (cylinder(0.8, 4) + point)
        elements = [self.bound_elements("Drill")]

        def same_holes(label):
            self.assertEqual(self.call("rebuild")["build_status"], "valid", label)
            self.assertEqual(self.apexes("Drill"), self.expected_apexes(centres), label)
            self.assertAlmostEqual(self.removed(BLOCK), drilled, places=6, msg=label)
            self.assertEqual(self.build_errors(), [], label)
            elements.append(self.bound_elements("Drill"))

        # Closing the polyline joins its ends into one wire and adds vertices.
        self.call("add_line", sketch="HS", body="Sketches", x1=-6, y1=-6, x2=-9, y2=-9)
        same_holes("closed polyline")
        # A new closed polyline and a line add edges and vertices to the shape.
        self.call("add_polyline", sketch="HS", body="Sketches", points=[[6, -9], [9, -9], [9, -6]], closed=True)
        self.call("add_line", sketch="HS", body="Sketches", x1=-9, y1=0, x2=-7, y2=0)
        same_holes("added lines")
        # Deleting geometry listed before the circles renumbers every circle edge.
        sketch = self.doc.HS
        lines = [index for index, geometry in enumerate(sketch.Geometry) if isinstance(geometry, Part.LineSegment)]
        self.delete_geometry("HS", lines[0])
        same_holes("deleted the first polyline segment")
        self.delete_geometry("HS", next(index for index, geometry in enumerate(self.doc.HS.Geometry)
                                        if isinstance(geometry, Part.LineSegment) and abs(geometry.StartPoint.y - 7) < 1e-9))
        same_holes("deleted the standalone line")
        # The native element references were re-resolved, not left positional.
        self.assertGreater(len({tuple(item) for item in elements}), 2, elements)
        self.assertNotEqual(elements[0][1:], elements[-1][1:], elements)
        # The bound circles and the sketch plane still drive the holes.
        self.call("set_parameter", feature="HS", parameter="CenterX", value=4)
        centres[0] = (4, 2)
        same_holes("moved circle")
        self.call("set_parameter", feature="Top", parameter="Offset", value=9)
        self.assertEqual(self.apexes("Drill"), self.expected_apexes(centres, top=9))
        self.call("set_parameter", feature="Top", parameter="Offset", value=10)
        # Saved element references keep re-resolving after reopen.
        path = support.scratch(self, prefix="hole-renumber-") / "renumber.FCStd"
        self.call("save", path=str(path))
        App.closeDocument(self.doc.Name)
        self.call("open", path=str(path))
        self.delete_geometry("HS", next(index for index, geometry in enumerate(self.doc.HS.Geometry)
                                        if isinstance(geometry, Part.LineSegment)))
        self.call("add_line", sketch="HS", body="Sketches", x1=-9, y1=3, x2=-7, y2=3)
        same_holes("reopened and edited")
        # Circles added later are not hole centres of this hole.
        self.call("add_circle", sketch="HS", body="Sketches", x=-2, y=6, diameter=1.6)
        same_holes("unrelated circle added")

    def test_changed_or_removed_bound_centres_fail_the_build_visibly(self):
        self.block()
        self.call("create_sketch", id="HS", support={"feature": "Top"}, body="Sketches")
        self.call("add_line", sketch="HS", body="Sketches", x1=-8, y1=7, x2=-2, y2=7)
        self.call("add_circle", sketch="HS", body="Sketches", x=3, y=2, diameter=1.6)
        self.call("add_circle", sketch="HS", body="Sketches", x=-5, y=-4, diameter=1.6)
        self.call("hole", id="Drill", part="Body", sketch="HS", diameter=1.6, depth=4)
        path = support.scratch(self, prefix="hole-centre-loss-") / "centres.FCStd"
        self.call("save", path=str(path))

        def fails(label):
            errors = [error for error in self.build_errors() if error.get("feature") == "Drill"]
            self.assertTrue(errors, label)
            self.assertEqual(self.state["build_status"], "failed", label)
            rejected = self.request("rebuild")
            self.assertEqual(rejected["error"]["code"], "build_failed", (label, rejected))
            self.assertIn("Drill", [error.get("feature") for error in rejected["error"]["features"]], label)
            return " ".join(error["message"] for error in errors)

        def reopen():
            App.closeDocument(self.doc.Name)
            self.call("open", path=str(path))
            self.assertEqual(self.call("rebuild")["build_status"], "valid")
            return self.doc.HS

        self.delete_geometry("HS", 2)
        self.assertIn("was deleted", fails("deleted circle"))
        sketch = reopen()
        sketch.toggleConstruction(1)
        self.doc.recompute()
        self.assertIn("construction", fails("construction circle"))
        # A geometry that keeps its id but is no longer a full circle (as a trim does).
        sketch = reopen()
        geometry_id = sketch.getGeometryId(1)
        arc = Part.ArcOfCircle(Part.Circle(App.Vector(3, 2, 0), App.Vector(0, 0, 1), 0.8), 0, 3)
        sketch.delGeometry(1)
        index = sketch.addGeometry(arc)
        sketch.setGeometryId(index, geometry_id)
        self.doc.recompute()
        self.assertIn("no longer a circle", fails("circle became an arc"))

    def test_orphaned_hole_helpers_after_a_native_delete_are_repairable(self):
        self.block()
        self.hole_sketch()
        self.call("hole", id="Drill", part="Body", sketch="HS", diameter=1.6, depth=4)
        helpers = self.helpers()
        # A native (non-KurtShape) delete of the Hole leaves its helpers behind.
        self.doc.openTransaction("native hole delete")
        self.doc.removeObject("Drill")
        self.doc.commitTransaction()
        self.doc.recompute()
        self.call("inspect")
        groups = self.call("orphan_helpers")["groups"]
        self.assertEqual([group["owner"] for group in groups], ["Drill"])
        self.assertTrue(groups[0]["repairable"], groups)
        self.assertEqual(groups[0]["objects"], helpers)
        self.assertIn("HS", groups[0]["inputs"])
        rejected = self.request("delete_features", features=["HS"])
        self.assertEqual((rejected["error"]["code"], rejected["error"].get("owner")), ("orphan_helpers", "Drill"), rejected)
        rejected = self.request("delete_features", features=["DrillProfile"])
        self.assertEqual(rejected["error"]["code"], "orphan_helpers", rejected)
        report = self.call("repair_orphan_helpers")["repair_report"]
        self.assertEqual(report["removed_groups"], ["Drill"])
        self.assertEqual(sorted(report["removed_objects"]), helpers)
        self.assertEqual(self.helpers(), [])
        self.assertAlmostEqual(self.part_volume(), BLOCK, places=6)
        self.call("delete_features", features=["HS"])
        self.assertIsNone(self.doc.getObject("HS"))

    # ------------------------------------------------------------------ history and persistence

    def test_save_reopen_rebuild_and_plain_freecad(self):
        self.block()
        self.hole_sketch(circles=((3, 2), (-4, -3)))
        self.call("hole", id="Drill", part="Body", sketch="HS", diameter=1.6, depth=4,
                  counterbore={"diameter": 2.5, "depth": 1})
        volume = self.part_volume()
        path = support.scratch(self, prefix="hole-persistence-") / "holes.FCStd"
        self.call("save", path=str(path))
        App.closeDocument(self.doc.Name)
        self.call("open", path=str(path))
        self.assertAlmostEqual(self.part_volume(), volume, places=6)
        self.assertEqual(self.doc.Drill.TypeId, "PartDesign::Hole")
        self.call("rebuild")
        self.assertEqual(self.state["build_status"], "valid")
        self.assertAlmostEqual(self.part_volume(), volume, places=6)
        self.call("set_parameter", feature="HS", parameter="CenterX", value=5)
        self.assertAlmostEqual(self.part_volume(), volume, places=6)
        script = (
            "import json;import FreeCAD as A;"
            "d=A.openDocument(" + repr(str(path)) + ");"
            "[o.touch() for o in d.Objects if o.TypeId.startswith(('PartDesign::','Sketcher::'))];"
            "d.recompute();h=d.Drill;"
            "print(json.dumps({'volume':h.Shape.Volume,'state':list(h.State)+list(h.Profile[0].State),"
            "'solids':len(h.Shape.Solids)}));A.closeDocument(d.Name)"
        )
        process = support.run_native_proof([sys.executable, "-B", "-c", script], capture_output=True, text=True,
                                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=60)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        proof = json.loads(process.stdout.strip().splitlines()[-1])
        self.assertAlmostEqual(proof["volume"], volume, places=6)
        self.assertEqual(proof["solids"], 1)
        self.assertFalse({"Invalid", "Error", "Touched"} & set(proof["state"]), proof)

    def test_undo_delete_and_fillet_on_the_hole_rim(self):
        self.block()
        self.hole_sketch()
        self.call("hole", id="Drill", part="Body", sketch="HS", diameter=1.6, depth=4)
        drilled = self.part_volume()
        helpers = self.helpers()
        self.assertEqual(helpers, ["DrillCentres", "DrillProfile", "DrillSource"])
        self.call("undo")
        self.assertIsNone(self.doc.getObject("Drill"))
        self.assertEqual([obj.Name for obj in self.doc.Objects if getattr(obj, "KurtShapeHoleHelper", False)], [])
        self.assertAlmostEqual(self.part_volume(), BLOCK, places=6)
        self.call("redo")
        self.assertAlmostEqual(self.part_volume(), drilled, places=6)
        rim = {"kind": "closest", "point": [3, 2.8, 10], "query": {"kind": "owned_by", "part": "Body", "entity_type": "edge"}}
        self.call("fillet", id="Rim", part="Body", edges=[rim], radius=0.2)
        filleted = self.part_volume()
        self.assertLess(filleted, drilled)
        # The authored sketch cannot go while the hole uses it; the hole is reported.
        rejected = self.request("delete_features", features=["HS"])
        self.assertEqual((rejected["error"]["code"], rejected["error"].get("feature")), ("external_dependency", "Drill"), rejected)
        plan = self.core.delete_features_plan(self.doc, ["Drill"])
        self.assertEqual(plan["dependents"], ["Rim"])
        self.assertEqual(sorted(plan["helpers"]), helpers)
        rejected = self.request("delete_features", features=["Drill"])
        self.assertEqual(rejected["error"]["code"], "dependent_features", rejected)
        undo = self.doc.UndoCount
        self.call("delete_features", features=["Drill"], cascade=True)
        self.assertEqual(self.doc.UndoCount, undo + 1)
        for name in ["Drill", "Rim"] + helpers:
            self.assertIsNone(self.doc.getObject(name), name)
        self.assertEqual(self.call("orphan_helpers")["groups"], [])
        self.assertAlmostEqual(self.part_volume(), BLOCK, places=6)
        self.call("undo")
        self.assertAlmostEqual(self.part_volume(), filleted, places=6)
        self.call("delete_features", features=["Rim", "Drill", "HS"])
        for name in ["Drill", "Rim", "HS"] + helpers:
            self.assertIsNone(self.doc.getObject(name), name)

    def test_cascade_from_upstream_feature_removes_private_helpers(self):
        self.call("new", name="Legacy holes")
        self.call("sketch_rectangle", id="Plate", width=20, height=20, x=-10, y=-10)
        self.call("pad", id="Pad", profile="Plate", length=10)
        self.call("create_body", id="Sketches")
        self.call("create_plane", id="Top", body="Sketches", base_plane="XY", offset=10)
        self.hole_sketch()
        self.call("hole", id="Drill", part="Body", sketch="HS", diameter=1.6, depth=4)
        point, _ = cone(0.8)
        self.assertAlmostEqual(BLOCK - self.doc.Body.Shape.Volume, cylinder(0.8, 4) + point, places=6)
        helpers = sorted(obj.Name for obj in self.doc.Objects if getattr(obj, "KurtShapeHoleHelper", False))
        plan = self.core.delete_features_plan(self.doc, ["Pad"])
        self.assertIn("Drill", plan["dependents"])
        self.assertEqual(sorted(plan["helpers"]), helpers)
        self.call("delete_features", features=["Pad"], cascade=True)
        for name in ["Pad", "Drill"] + helpers:
            self.assertIsNone(self.doc.getObject(name), name)
        self.assertIsNotNone(self.doc.getObject("HS"))
        self.call("undo")
        self.assertAlmostEqual(BLOCK - self.doc.Body.Shape.Volume, cylinder(0.8, 4) + point, places=6)

    def test_preview_is_disposable_and_matches_confirm(self):
        self.block()
        self.hole_sketch()
        before = self.snapshot()
        preview = self.call("preview", proposal={"op": "hole", "id": "Drill", "part": "Body", "sketch": "HS",
                                                "diameter": 1.6, "depth": 4})
        self.assertTrue(preview["valid"], preview)
        self.assertTrue(preview["discarded"])
        self.assertEqual(self.snapshot(), before)
        self.call("hole", id="Drill", part="Body", sketch="HS", diameter=1.6, depth=4)
        self.assertAlmostEqual(preview["measurements"]["volume_mm3"], self.call("inspect")["measurements"]["volume_mm3"], places=6)

    # ------------------------------------------------------------------ rejections

    def test_rejections_roll_back_without_kernel_checks(self):
        self.block()
        self.hole_sketch()
        self.call("create_sketch", id="Empty", support={"feature": "Top"}, body="Sketches")
        self.call("add_line", sketch="Empty", body="Sketches", x1=-3, y1=0, x2=3, y2=0)
        self.call("add_circle", sketch="Empty", body="Sketches", x=0, y=4, diameter=1, construction=True)
        base = {"part": "Body", "sketch": "HS", "diameter": 1.6, "depth": 4}
        cases = [
            ("missing_reference", dict(base, sketch="Nope")),
            ("missing_reference", dict(base, sketch="Block")),
            ("empty_profile", dict(base, sketch="Empty")),
            ("invalid_argument", dict(base, diameter=0)),
            ("invalid_argument", dict(base, diameter=-1)),
            ("invalid_argument", dict(base, depth=0)),
            ("invalid_argument", dict(base, depth="-2 mm")),
            ("invalid_argument", dict(base, point_angle="180 deg")),
            ("invalid_argument", dict(base, point_angle="179.5 deg")),
            ("invalid_argument", dict(base, point_angle="0.5 deg")),
            ("invalid_argument", dict(base, point_angle=1e-9)),
            ("invalid_argument", dict(base, countersink={"diameter": 3, "angle": "0.5 deg"})),
            # A 3 mm, 90 deg countersink on a 1.6 mm hole is 0.7 mm deep.
            ("invalid_argument", dict(base, depth=0.5, countersink={"diameter": 3, "angle": "90 deg"})),
            # Native Hole clamps blind depth to its through-all length (60.6 mm here).
            ("invalid_argument", dict(base, depth=70)),
            ("invalid_argument", dict(base, end_type="up_to_face")),
            ("invalid_argument", dict(base, reversed="yes")),
            ("invalid_argument", dict(base, counterbore={"diameter": 1.2, "depth": 1})),
            ("invalid_argument", dict(base, counterbore={"diameter": 3, "depth": 4})),
            ("invalid_argument", dict(base, countersink={"diameter": 1.6})),
            ("invalid_argument", dict(base, counterbore={"diameter": 3, "depth": 1}, countersink={"diameter": 3})),
            ("unknown_argument", dict(base, counterbore={"diameter": 3, "depth": 1, "angle": 1})),
            ("unknown_argument", dict(base, colour="red")),
            ("empty_cut", dict(base, reversed=True)),
        ]
        with no_kernel_checks(self):
            for code, args in cases:
                before = self.snapshot()
                response = self.request("hole", id="Rejected", **args)
                self.assertFalse(response["ok"], args)
                self.assertEqual(response["error"]["code"], code, (args, response))
                self.assertEqual(self.snapshot(), before, args)
        self.assertAlmostEqual(self.part_volume(), BLOCK, places=6)

    def test_depth_beyond_the_native_maximum_reports_the_limit(self):
        self.block()
        self.hole_sketch()
        response = self.request("hole", id="Deep", part="Body", sketch="HS", diameter=1.6, depth=70)
        self.assertEqual(response["error"]["code"], "invalid_argument", response)
        # The native limit is the through-all length, 2.02 x the 30 mm bounding-box diagonal.
        self.assertAlmostEqual(response["error"]["maximum_depth"], 2.02 * 30, places=3)
        self.call("hole", id="Drill", part="Body", sketch="HS", diameter=1.6, depth=60)
        point, _ = cone(0.8)
        # Through the 10 mm block: the whole column is removed.
        self.assertAlmostEqual(self.removed(BLOCK), cylinder(0.8, 10), places=6)
        before = self.snapshot()
        with no_kernel_checks(self):
            for op, args in (("set_parameter", {"value": 70}), ("set_expression", {"expression": "7 mm * 10"})):
                rejected = self.request(op, feature="Drill", parameter="Depth", **args)
                self.assertEqual(rejected["error"]["code"], "invalid_argument", rejected)
                self.assertAlmostEqual(rejected["error"]["maximum_depth"], response["error"]["maximum_depth"], places=9)
                self.assertEqual(self.snapshot(), before)
            self.call("set_parameter", feature="Drill", parameter="Depth", value=4)
        self.assertAlmostEqual(self.removed(BLOCK), cylinder(0.8, 4) + point, places=6)

    def test_parameter_edits_run_the_hole_checks_without_kernel_checks(self):
        self.block()
        self.hole_sketch()
        self.call("hole", id="Bore", part="Body", sketch="HS", diameter=1.6, depth=4,
                  counterbore={"diameter": 3, "depth": 1.5})
        self.hole_sketch(sid="HS2", circles=((-5, -5),))
        self.call("hole", id="Sink", part="Body", sketch="HS2", diameter=1.6, depth=4,
                  countersink={"diameter": 3, "angle": "90 deg"})
        self.hole_sketch(sid="HS3", circles=((0, 0),), diameter=2)
        self.call("hole", id="Through", part="Body", sketch="HS3", diameter=2, end_type="through_all")
        cases = [
            ("invalid_argument", "Bore", "Depth", 1.5),           # counterbore as deep as the hole
            ("invalid_argument", "Bore", "Diameter", 3),          # counterbore no wider than the hole
            ("invalid_argument", "Sink", "Depth", 0.6),           # 0.7 mm countersink deeper than the hole
            ("invalid_argument", "Sink", "PointAngle", "0.5 deg"),
            ("invalid_argument", "Sink", "PointAngle", "179.5 deg"),
            ("build_failed", "Through", "Diameter", 24),          # leaves four separate corner solids
        ]
        with no_kernel_checks(self):
            for code, feature, parameter, value in cases:
                before = self.snapshot()
                rejected = self.request("set_parameter", feature=feature, parameter=parameter, value=value)
                self.assertFalse(rejected["ok"], (feature, parameter, value))
                self.assertEqual(rejected["error"]["code"], code, (feature, parameter, value, rejected))
                self.assertEqual(self.snapshot(), before, (feature, parameter, value))
            self.call("set_parameter", feature="Bore", parameter="Depth", value=3)
            self.call("set_parameter", feature="Sink", parameter="PointAngle", value="90 deg")

    def test_hole_helpers_are_not_profiles_or_deletion_targets(self):
        self.block()
        self.hole_sketch()
        self.call("hole", id="Drill", part="Body", sketch="HS", diameter=1.6, depth=4)
        before = self.snapshot()
        cases = [
            ("missing_reference", "pad", dict(id="Reuse", profile="DrillProfile", length=2, operation="new")),
            ("missing_reference", "pocket", dict(id="Reuse", profile="DrillProfile", length=2)),
            ("missing_reference", "revolve", dict(id="Reuse", profile="DrillProfile", operation="new",
                                                  axis={"origin": [0, 0, 0], "direction": [1, 0, 0]})),
            ("missing_reference", "add_circle", dict(sketch="DrillProfile", x=0, y=0, diameter=1)),
            ("unsupported_feature", "delete_features", dict(features=["DrillProfile"])),
            ("unsupported_feature", "delete_features", dict(features=["DrillCentres"])),
        ]
        for code, op, args in cases:
            rejected = self.request(op, **args)
            self.assertFalse(rejected["ok"], (op, args))
            self.assertEqual(rejected["error"]["code"], code, (op, args, rejected))
            self.assertEqual(rejected["error"].get("hole"), "Drill", (op, rejected))
            self.assertEqual(self.snapshot(), before, op)

    def test_hole_that_splits_the_part_is_rejected(self):
        self.call("new", name="Thin bar")
        self.call("sketch_rectangle", id="Bar", width=20, height=2, x=-10, y=-1)
        self.call("pad", id="BarPad", profile="Bar", length=2, operation="new")
        self.call("create_body", id="Sketches")
        self.call("create_plane", id="BarTop", body="Sketches", base_plane="XY", offset=2)
        self.call("create_sketch", id="Cutter", support={"feature": "BarTop"}, body="Sketches")
        self.call("add_circle", sketch="Cutter", body="Sketches", x=0, y=0, diameter=3)
        before = self.snapshot()
        response = self.request("hole", id="Split", part="Body", sketch="Cutter", diameter=3, end_type="through_all")
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], "build_failed", response)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
