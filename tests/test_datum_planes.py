"""Arbitrary-orientation native datum planes: point-normal, three-point, line-angle."""
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
from kurtshape.core import Controller
from kurtshape import modeling_geometry, studio

X, Y, Z = App.Vector(1, 0, 0), App.Vector(0, 1, 0), App.Vector(0, 0, 1)


def unit(*components):
    vector = App.Vector(*components)
    return vector.normalize()


def spherical(tilt, azimuth):
    """Unit vector tilted from +Z by `tilt` degrees toward azimuth `azimuth`."""
    tilt, azimuth = math.radians(tilt), math.radians(azimuth)
    return App.Vector(math.sin(tilt) * math.cos(azimuth), math.sin(tilt) * math.sin(azimuth), math.cos(tilt))


def listed(vector):
    return [vector.x, vector.y, vector.z]


# Dodecahedron-vertex hub geometry: an axis tilted 20.905 deg from +Z at 108 deg.
HUB_AXIS = spherical(20.905, 108)


class DatumPlaneFrameTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="datum-plane-session-")
        self.core = Controller()
        self.state = self.call("new", name="Arbitrary datum planes")
        self.call("sketch_rectangle", id="Plate", width=20, height=12)
        self.call("pad", id="Pad", profile="Plate", length=6)

    def tearDown(self):
        self.core.observer.close()
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

    def assertVector(self, actual, expected, places=1e-6, message=None):
        actual, expected = App.Vector(*actual), App.Vector(*expected)
        self.assertLess((actual - expected).Length, places, message or f"{actual} != {expected}")

    def feature(self, name):
        return next(row for row in self.call("inspect")["features"] if row["id"] == name)

    def assertFrame(self, plane, origin, x, normal):
        """Plane frame, inspection frame and sketch frame all agree."""
        y = normal.cross(x)
        placement = self.doc.getObject(plane).getGlobalPlacement()
        self.assertVector(placement.Base, origin)
        self.assertVector(placement.Rotation.multVec(X), x)
        self.assertVector(placement.Rotation.multVec(Y), y)
        self.assertVector(placement.Rotation.multVec(Z), normal)
        frame = self.feature(plane)["plane"]["frame"]
        self.assertVector(frame["origin_mm"], origin)
        self.assertVector(frame["x_direction"], x)
        self.assertVector(frame["y_direction"], y)
        self.assertVector(frame["normal"], normal)

    def sketch_circle_on(self, plane, sketch):
        """A sketch on the plane; a circle at sketch (10, 5); returns its world centre."""
        self.call("create_sketch", id=sketch, support={"feature": plane})
        self.call("add_circle", sketch=sketch, x=10, y=5, diameter=6)
        self.assertTrue(self.doc.Body.Placement.isIdentity())
        circles = [edge for edge in self.doc.getObject(sketch).Shape.Edges if isinstance(edge.Curve, Part.Circle)]
        self.assertEqual(len(circles), 1)
        return circles[0].Curve.Center

    def new_part(self, feature):
        representative = self.doc.getObject(feature)
        return self.doc.getObject(representative.KurtShapeOutputParts[0])

    def assertCylinder(self, shape, base, axis, radius, length):
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids), 1)
        self.assertAlmostEqual(shape.Volume, math.pi * radius ** 2 * length, places=5)
        self.assertVector(shape.Solids[0].CenterOfMass, base + axis * (length / 2), 1e-5)
        cylinders = [face.Surface for face in shape.Faces if isinstance(face.Surface, Part.Cylinder)]
        self.assertEqual(len(cylinders), 1)
        self.assertAlmostEqual(abs(cylinders[0].Axis.dot(axis)), 1, places=9)
        self.assertAlmostEqual(cylinders[0].Radius, radius, places=9)
        offset = cylinders[0].Center - base
        self.assertLess((offset - axis * offset.dot(axis)).Length, 1e-6, "Cylinder axis passes through the circle centre")

    def test_point_normal_plane_frames_sketch_and_studio_pad(self):
        origin = App.Vector(12.5, -7, 30)
        authored_x = App.Vector(1, 0.3, -0.2)
        x = unit(*(authored_x - HUB_AXIS * authored_x.dot(HUB_AXIS)))
        undo_before, tip = self.doc.UndoCount, self.doc.Body.Tip
        self.call("create_plane", id="HubPlane", name="Hub axis plane", origin=listed(origin), normal=listed(HUB_AXIS * 3),
                  x_direction=listed(authored_x), offset=4)
        plane = self.doc.HubPlane
        self.assertEqual(self.doc.UndoCount, undo_before + 1)
        self.assertEqual(plane.TypeId, "PartDesign::Plane")
        self.assertEqual(plane.Label, "Hub axis plane")
        self.assertEqual(self.doc.Body.Tip, tip)
        self.assertEqual(plane.AttachmentSupport[0][0].Role, "XY_Plane")
        self.assertEqual(plane.MapMode, "FlatFace")
        self.assertEqual(plane.PlaneMode, "point_normal")
        self.assertEqual([path.lstrip(".") for path, _ in plane.ExpressionEngine], ["AttachmentOffset"])
        top = origin + HUB_AXIS * 4
        self.assertFrame("HubPlane", top, x, HUB_AXIS)
        summary = self.feature("HubPlane")
        self.assertEqual(summary["plane"]["mode"], "point_normal")
        self.assertVector(summary["plane"]["definition"]["origin"], origin)
        self.assertVector(summary["plane"]["definition"]["normal"], HUB_AXIS)
        self.assertVector(summary["plane"]["definition"]["x_direction"], x)
        self.assertAlmostEqual(summary["plane"]["definition"]["offset"], 4)
        self.assertEqual(summary["parameters"]["Offset"]["value"], 4)
        self.assertTrue(summary["parameters"]["Offset"]["editable"])
        self.assertIn({"feature": "HubPlane"}, [row["reference"] for row in modeling_geometry.named_plane_candidates(self.doc)])

        centre = self.sketch_circle_on("HubPlane", "HubSketch")
        expected = top + x * 10 + HUB_AXIS.cross(x) * 5
        self.assertVector(centre, expected)
        sketch = self.doc.HubSketch.getGlobalPlacement()
        self.assertVector(sketch.Base, top)
        self.assertVector(sketch.Rotation.multVec(X), x)
        self.assertVector(sketch.Rotation.multVec(Z), HUB_AXIS)

        self.call("pad", id="HubBoss", profile="HubSketch", length=15, operation="new")
        part = self.new_part("HubBoss")
        self.assertCylinder(part.Shape, expected, HUB_AXIS, 3, 15)

        # The native Offset convention is retained: it slides along the normal.
        self.call("set_parameter", feature="HubPlane", parameter="Offset", value=-2)
        moved = origin - HUB_AXIS * 2
        self.assertFrame("HubPlane", moved, x, HUB_AXIS)
        self.assertCylinder(self.new_part("HubBoss").Shape, moved + x * 10 + HUB_AXIS.cross(x) * 5, HUB_AXIS, 3, 15)

    def test_three_point_plane_frames_sketch_and_studio_pad(self):
        p1, p2, p3 = App.Vector(5, 40, -3), App.Vector(14, 43, 8), App.Vector(-2, 47, 6)
        x = unit(*(p2 - p1))
        normal = unit(*(p2 - p1).cross(p3 - p1))
        self.call("create_plane", id="Facet", points=[listed(p1), listed(p2), listed(p3)])
        self.assertEqual(self.doc.Facet.PlaneMode, "three_points")
        self.assertFrame("Facet", p1, x, normal)
        definition = self.feature("Facet")["plane"]["definition"]
        for actual, expected in zip(definition["points"], (p1, p2, p3)):
            self.assertVector(actual, expected)
        centre = self.sketch_circle_on("Facet", "FacetSketch")
        expected = p1 + x * 10 + normal.cross(x) * 5
        self.assertVector(centre, expected)
        self.call("pad", id="FacetBoss", profile="FacetSketch", length=7, operation="new")
        self.assertCylinder(self.new_part("FacetBoss").Shape, expected, normal, 3, 7)
        # The authored points drive the native attachment.
        plane = self.doc.Facet
        self.doc.openTransaction("Native point edit")
        plane.PlanePoint2 = p1 + (p2 - p1) * 2
        self.doc.commitTransaction()
        self.call("inspect")
        self.call("rebuild")
        self.assertFrame("Facet", p1, x, normal)
        plane = self.doc.Facet
        self.doc.openTransaction("Native point edit")
        plane.PlanePoint1 = p1 + normal * 3
        plane.PlanePoint2 = p2 + normal * 3
        plane.PlanePoint3 = p3 + normal * 3
        self.doc.commitTransaction()
        self.call("inspect")
        self.call("rebuild")
        self.assertFrame("Facet", p1 + normal * 3, x, normal)
        self.assertCylinder(self.new_part("FacetBoss").Shape, expected + normal * 3, normal, 3, 7)

    def test_line_angle_plane_contains_tilted_axis_for_revolve(self):
        axis_origin = App.Vector(3, -4, 10)
        reference = unit(*(Z - HUB_AXIS * Z.dot(HUB_AXIS)))
        angle = math.radians(108)
        normal = App.Rotation(HUB_AXIS, 108).multVec(reference)
        self.call("create_plane", id="AxisPlane", axis={"origin": listed(axis_origin), "direction": listed(HUB_AXIS)},
                  reference_normal=[0, 0, 1], angle="108 deg")
        plane = self.doc.AxisPlane
        self.assertEqual(plane.PlaneMode, "line_angle")
        self.assertFrame("AxisPlane", axis_origin, HUB_AXIS, normal)
        self.assertAlmostEqual(normal.dot(HUB_AXIS), 0, places=12)
        summary = self.feature("AxisPlane")
        self.assertAlmostEqual(summary["plane"]["definition"]["angle"], angle, places=9)
        self.assertVector(summary["plane"]["definition"]["reference_normal"], reference)
        self.assertAlmostEqual(summary["parameters"]["Angle"]["value"], angle, places=9)
        self.assertEqual(summary["parameters"]["Angle"]["unit"], "rad")

        # Sketch x is the axis and sketch y is radial: a tube profile.
        self.call("sketch_rectangle", id="TubeProfile", support={"feature": "AxisPlane"}, x=2, y=4, width=10, height=3)
        self.call("revolve", id="Tube", profile="TubeProfile", axis={"origin": listed(axis_origin), "direction": listed(HUB_AXIS)},
                  angle=2 * math.pi, operation="new")
        tube = self.new_part("Tube").Shape
        self.assertTrue(tube.isValid())
        self.assertEqual(len(tube.Solids), 1)
        self.assertAlmostEqual(tube.Volume, math.pi * (7 ** 2 - 4 ** 2) * 10, places=4)
        self.assertVector(tube.Solids[0].CenterOfMass, axis_origin + HUB_AXIS * 7, 1e-5)
        radii = sorted(face.Surface.Radius for face in tube.Faces if isinstance(face.Surface, Part.Cylinder))
        self.assertEqual(len(radii), 2)
        self.assertAlmostEqual(radii[0], 4, places=7)
        self.assertAlmostEqual(radii[1], 7, places=7)
        for face in tube.Faces:
            if isinstance(face.Surface, Part.Cylinder):
                self.assertAlmostEqual(abs(face.Surface.Axis.dot(HUB_AXIS)), 1, places=9)

        # Signed native Angle is a set_parameter target; the plane turns about the line.
        self.call("set_parameter", feature="AxisPlane", parameter="Angle", value=-0.25)
        self.assertFrame("AxisPlane", axis_origin, HUB_AXIS, App.Rotation(HUB_AXIS, math.degrees(-0.25)).multVec(reference))
        self.assertAlmostEqual(self.new_part("Tube").Shape.Volume, math.pi * (7 ** 2 - 4 ** 2) * 10, places=4)
        self.call("undo")
        self.assertFrame("AxisPlane", axis_origin, HUB_AXIS, normal)

    def test_line_angle_plane_from_edge_reference_and_offset(self):
        edge = next("Edge" + str(index + 1) for index, item in enumerate(self.doc.Pad.Shape.Edges)
                    if item.BoundBox.XLength > 19 and abs(item.BoundBox.ZMax - 6) < 1e-7 and abs(item.BoundBox.YMin) < 1e-7)
        shape = self.doc.Pad.Shape.getElement(edge)
        start = shape.valueAt(shape.FirstParameter)
        direction = unit(*(shape.valueAt(shape.LastParameter) - start))
        self.call("create_plane", id="EdgePlane", axis={"feature": "Pad", "subelement": edge}, reference_normal=[0, 0, 1],
                  angle="90 deg", offset=2)
        normal = App.Rotation(direction, 90).multVec(Z)
        self.assertFrame("EdgePlane", start + normal * 2, direction, normal)
        self.assertEqual(json.loads(self.doc.EdgePlane.PlaneAxisReference), {"feature": "Pad", "subelement": edge})
        self.assertEqual(self.feature("EdgePlane")["plane"]["definition"]["axis_reference"], {"feature": "Pad", "subelement": edge})

    def test_default_x_direction_is_deterministic(self):
        self.assertVector(modeling_geometry.default_x_direction(Z), X, 1e-12)
        self.assertVector(modeling_geometry.default_x_direction(Z * -1), X, 1e-12)
        self.assertVector(modeling_geometry.default_x_direction(X), Y, 1e-12)
        self.assertVector(modeling_geometry.default_x_direction(Y), X, 1e-12)
        self.call("create_plane", id="DefaultFrame", origin=[1, 2, 3], normal=listed(HUB_AXIS))
        expected = unit(*(X - HUB_AXIS * X.dot(HUB_AXIS)))
        self.assertFrame("DefaultFrame", App.Vector(1, 2, 3), expected, HUB_AXIS)

    def test_world_request_is_stored_in_moved_body_frame(self):
        body = App.Placement(App.Vector(30, -20, 5), App.Rotation(App.Vector(0, 0, 1), 90))
        self.doc.Body.Placement = body
        self.doc.recompute()
        self.call("inspect")
        origin, x = App.Vector(40, -10, 8), unit(*(X - HUB_AXIS * X.dot(HUB_AXIS)))
        self.call("create_plane", id="PlacedPlane", origin=listed(origin), normal=listed(HUB_AXIS), x_direction=[1, 0, 0])
        self.assertFrame("PlacedPlane", origin, x, HUB_AXIS)
        definition = self.feature("PlacedPlane")["plane"]["definition"]
        self.assertVector(definition["origin"], body.inverse().multVec(origin))
        self.assertVector(definition["normal"], body.Rotation.inverted().multVec(HUB_AXIS))
        self.call("create_sketch", id="PlacedSketch", support={"feature": "PlacedPlane"})
        self.call("add_circle", sketch="PlacedSketch", x=10, y=5, diameter=6)
        sketch = self.doc.PlacedSketch.getGlobalPlacement()
        self.assertVector(sketch.multVec(App.Vector(10, 5, 0)), origin + x * 10 + HUB_AXIS.cross(x) * 5)

    def test_legacy_offset_planes_are_unchanged(self):
        self.call("create_plane", id="RightOffset", base_plane="YZ", offset=30)
        plane = self.doc.RightOffset
        self.assertNotIn("PlaneMode", plane.PropertiesList)
        self.assertEqual([(path, value) for path, value in plane.ExpressionEngine], [(".AttachmentOffset.Base.z", "Offset")])
        self.assertEqual(self.feature("RightOffset")["plane"]["mode"], "offset")
        self.assertAlmostEqual(self.feature("RightOffset")["plane"]["frame"]["origin_mm"][0], 30)
        self.assertEqual(self.feature("RightOffset")["plane"]["definition"], {"offset": 30})

    def test_invalid_plane_definitions_reject_without_change(self):
        baseline = ({obj.Name for obj in self.doc.Objects}, self.doc.UndoCount, self.state["revision"])
        cases = [
            ("invalid_argument", dict(base_plane="XY", origin=[0, 0, 0], normal=[0, 0, 1])),
            ("invalid_argument", dict(support={"feature": "XY_Plane"}, points=[[0, 0, 0], [1, 0, 0], [0, 1, 0]])),
            ("invalid_argument", dict(origin=[0, 0, 0], normal=[0, 0, 1], points=[[0, 0, 0], [1, 0, 0], [0, 1, 0]])),
            ("invalid_argument", dict(origin=[0, 0, 0], normal=[0, 0, 1], axis={"origin": [0, 0, 0], "direction": [1, 0, 0]})),
            ("invalid_argument", dict(normal=[0, 0, 1])),
            ("invalid_argument", dict(origin=[0, 0, 0], x_direction=[1, 0, 0])),
            ("invalid_argument", dict(origin=[0, 0, 0], normal=[0, 0, 0])),
            ("invalid_argument", dict(origin=[0, 0, float("nan")], normal=[0, 0, 1])),
            ("invalid_argument", dict(origin=[0, 0, 0], normal=[0, float("inf"), 1])),
            ("invalid_argument", dict(origin=[0, 0, 0], normal=[True, 0, 1])),
            ("invalid_argument", dict(origin=[0, 0], normal=[0, 0, 1])),
            ("invalid_argument", dict(origin=[0, 0, 0], normal=[0, 0, 1], x_direction=[0, 0, -2])),
            ("invalid_argument", dict(origin=[0, 0, 0], normal=[0, 0, 1], x_direction=[0, 0, 0])),
            ("invalid_argument", dict(origin=[0, 0, 0], normal=[0, 0, 1], offset=float("nan"))),
            ("invalid_argument", dict(points=[[0, 0, 0], [1, 1, 1], [3, 3, 3]])),
            ("invalid_argument", dict(points=[[0, 0, 0], [0, 0, 0], [0, 1, 0]])),
            ("invalid_argument", dict(points=[[0, 0, 0], [1, 0, 0]])),
            ("invalid_argument", dict(points="XY")),
            ("invalid_argument", dict(axis={"origin": [0, 0, 0], "direction": [1, 0, 0]}, reference_normal=[-3, 0, 0])),
            ("invalid_argument", dict(axis={"origin": [0, 0, 0]}, reference_normal=[0, 0, 1])),
            ("invalid_argument", dict(axis={"origin": [0, 0, 0], "direction": [0, 0, 0]}, reference_normal=[0, 0, 1])),
            ("invalid_argument", dict(axis={"origin": [0, 0, 0], "direction": [1, 0, 0]})),
            ("invalid_argument", dict(axis={"origin": [0, 0, 0], "direction": [1, 0, 0]}, reference_normal=[0, 0, 1], angle="5 mm")),
            ("invalid_argument", dict(reference_normal=[0, 0, 1], angle=1)),
            ("invalid_argument", dict(axis="Edge1", reference_normal=[0, 0, 1])),
            ("unknown_argument", dict(origin=[0, 0, 0], normal=[0, 0, 1], y_direction=[0, 1, 0])),
        ]
        for code, args in cases:
            with self.subTest(args=args):
                response = self.request("create_plane", id="Rejected", **args)
                self.assertFalse(response["ok"], response)
                self.assertEqual(response["error"]["code"], code, response)
                self.assertEqual(({obj.Name for obj in self.doc.Objects}, self.doc.UndoCount,
                                  self.core.inspect(self.doc)["revision"]), baseline)

    def test_preview_of_arbitrary_plane_is_disposable(self):
        names, revision = set(App.listDocuments()), self.state["revision"]
        preview = self.call("preview", proposal={"op": "create_plane", "points": [[0, 0, 5], [10, 0, 6], [0, 10, 7]]})
        self.assertTrue(preview["valid"], preview)
        preview = self.call("preview", proposal={"op": "create_plane", "axis": {"origin": [0, 0, 0], "direction": [0, 0, 1]},
                                                "reference_normal": [1, 0, 0], "angle": -0.5})
        self.assertTrue(preview["valid"], preview)
        self.assertEqual(set(App.listDocuments()), names)
        self.assertIsNone(self.doc.getObject("Plane"))
        self.assertEqual(self.core.inspect(self.doc)["revision"], revision)

    def test_undo_redo_and_reopen_keep_plane_frame(self):
        origin, normal = App.Vector(-6, 9, 14), spherical(108, 20.905)
        x = modeling_geometry.default_x_direction(normal)
        self.call("create_plane", id="Tangent", origin=listed(origin), normal=listed(normal), offset=1.5)
        top = origin + normal * 1.5
        self.assertFrame("Tangent", top, x, normal)
        self.call("undo")
        self.assertIsNone(self.doc.getObject("Tangent"))
        self.call("redo")
        self.assertFrame("Tangent", top, x, normal)
        self.assertEqual(self.doc.Tangent.PlaneMode, "point_normal")
        centre = self.sketch_circle_on("Tangent", "TangentSketch")
        self.assertVector(centre, top + x * 10 + normal.cross(x) * 5)
        self.call("set_parameter", feature="Tangent", parameter="Offset", value=6)
        self.assertFrame("Tangent", origin + normal * 6, x, normal)
        self.call("undo")
        self.assertFrame("Tangent", top, x, normal)
        self.call("redo")
        self.call("undo")
        destination = support.scratch(self, prefix="arbitrary-datum-plane-persistence-")
        path = destination / "arbitrary-datum-plane.FCStd"
        self.call("save", path=str(path))
        App.closeDocument(self.doc.Name)
        self.call("open", path=str(path))
        self.assertFrame("Tangent", top, x, normal)
        self.call("rebuild")
        self.assertFrame("Tangent", top, x, normal)
        reopened = [edge for edge in self.doc.TangentSketch.Shape.Edges if isinstance(edge.Curve, Part.Circle)]
        self.assertVector(reopened[0].Curve.Center, top + x * 10 + normal.cross(x) * 5)
        # A plain FreeCAD process rebuilds the native expression-driven attachment.
        script = (
            "import json;import FreeCAD as A;"
            "d=A.openDocument(" + repr(str(path)) + ");"
            "p=d.Tangent;p.Offset=4;[o.touch() for o in d.Objects if o.TypeId.startswith(('PartDesign::','Sketcher::'))];"
            "d.recompute();g=d.TangentSketch.getGlobalPlacement();"
            "print(json.dumps({'plane':list(p.getGlobalPlacement().Base),'sketch':list(g.Base),"
            "'normal':list(g.Rotation.multVec(A.Vector(0,0,1))),'state':list(p.State)+list(d.TangentSketch.State)}));"
            "A.closeDocument(d.Name)"
        )
        process = support.run_native_proof([sys.executable, "-B", "-c", script], capture_output=True, text=True,
                                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=60)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        proof = json.loads(process.stdout.strip().splitlines()[-1])
        self.assertVector(proof["plane"], origin + normal * 4)
        self.assertVector(proof["sketch"], origin + normal * 4)
        self.assertVector(proof["normal"], normal)
        self.assertFalse({"Invalid", "Error"} & set(proof["state"]), proof)


if __name__ == "__main__":
    unittest.main()
