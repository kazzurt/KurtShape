"""Section View (Shift+X) geometry rules: which plane a face or plane asks for, and the cut faces."""
from pathlib import Path
import math
import sys
import unittest
import support  # noqa: F401 - isolated scratch and profile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
from kurtshape import section_view as sv

X, Y, Z = App.Vector(1, 0, 0), App.Vector(0, 1, 0), App.Vector(0, 0, 1)
# Camera view directions (from the camera into the scene) for the standard views.
FROM_RIGHT, FROM_TOP, FROM_FRONT = App.Vector(-1, 0, 0), App.Vector(0, 0, -1), App.Vector(0, 1, 0)


def lateral(shape, kind):
    return next(face for face in shape.Faces if isinstance(face.Surface, kind))


class SectionViewGeometryTests(unittest.TestCase):
    def assertVector(self, actual, expected, places=6):
        for a, b in zip(actual, expected):
            self.assertAlmostEqual(a, b, places=places)

    def test_closest_origin_plane_follows_the_view(self):
        self.assertEqual(sv.closest_origin_plane(FROM_RIGHT)[0], "Right")
        self.assertEqual(sv.closest_origin_plane(FROM_TOP)[0], "Top")
        self.assertEqual(sv.closest_origin_plane(FROM_FRONT)[0], "Front")
        # Roughly from the right (orbited 25 degrees up and a little to the front).
        self.assertEqual(sv.closest_origin_plane(App.Vector(-0.85, 0.3, -0.42))[0], "Right")
        self.assertEqual(sv.closest_origin_plane(App.Vector(-0.3, 0.4, -0.86))[0], "Top")
        # An exact isometric view ties; Top wins, deterministically.
        self.assertEqual(sv.closest_origin_plane(App.Vector(-1, -1, -1))[0], "Top")
        with self.assertRaises(ValueError):
            sv.closest_origin_plane(App.Vector(0, 0, 0))

    def test_normal_points_back_at_the_camera(self):
        self.assertVector(sv.facing_viewer(X, FROM_RIGHT), (1, 0, 0))
        self.assertVector(sv.facing_viewer(X, App.Vector(1, 0, 0)), (-1, 0, 0))
        self.assertVector(sv.facing_viewer(App.Vector(0, 0, 5), FROM_TOP), (0, 0, 1))

    def test_cylinder_cuts_through_the_middle_of_its_axis_on_the_facing_origin_plane(self):
        cylinder = Part.makeCylinder(5, 20, App.Vector(10, 20, 30), Z)
        target = sv.face_target(lateral(cylinder, Part.Cylinder))
        self.assertEqual(target["kind"], sv.CENTER)
        self.assertVector(target["center"], (10, 20, 40))
        cut = sv.section_plane(target, FROM_FRONT)
        self.assertEqual(cut["label"], "Front plane")
        self.assertVector(cut["normal"], (0, -1, 0))
        self.assertVector(cut["origin"], (10, 20, 40))
        cut = sv.section_plane(target, App.Vector(-0.9, 0.2, -0.3))
        self.assertEqual(cut["label"], "Right plane")
        self.assertVector(cut["normal"], (1, 0, 0))

    def test_partial_cylinder_projects_its_centre_onto_the_axis(self):
        quarter = Part.makeCylinder(4, 12, App.Vector(0, 0, -6), Z, 90)
        face = lateral(quarter, Part.Cylinder)
        self.assertGreater(App.Vector(face.CenterOfMass.x, face.CenterOfMass.y, 0).Length, 1.0)
        self.assertVector(sv.face_target(face)["center"], (0, 0, 0))

    def test_tilted_axis_keeps_an_origin_aligned_plane_through_the_centre(self):
        axis = App.Vector(1, 1, 1).normalize()
        base = App.Vector(3, -2, 7)
        cylinder = Part.makeCylinder(2, 30, base, axis)
        target = sv.face_target(lateral(cylinder, Part.Cylinder))
        center = base + axis * 15
        self.assertVector(target["center"], center)
        cut = sv.section_plane(target, App.Vector(-0.95, 0.1, -0.2))
        self.assertEqual(cut["label"], "Right plane")
        self.assertVector(cut["normal"], (1, 0, 0))
        self.assertAlmostEqual((cut["origin"] - center).dot(cut["normal"]), 0, places=9)

    def test_placed_shapes_report_world_centres(self):
        cylinder = Part.makeCylinder(5, 10)
        cylinder.Placement = App.Placement(App.Vector(100, 0, 0), App.Rotation(X, 90))
        target = sv.face_target(lateral(cylinder, Part.Cylinder))
        # Rotating +Z 90 degrees about +X points the axis along -Y.
        self.assertVector(target["center"], (100, -5, 0))

    def test_cone_torus_sphere_and_revolved_faces_cut_through_their_centre(self):
        cone = Part.makeCone(6, 2, 8, App.Vector(1, 2, 3), Z)
        self.assertVector(sv.face_target(lateral(cone, Part.Cone))["center"], (1, 2, 7), places=5)
        torus = Part.makeTorus(10, 2, App.Vector(-4, 5, 6), Y)
        self.assertVector(sv.face_target(torus.Faces[0])["center"], (-4, 5, 6))
        sphere = Part.makeSphere(3, App.Vector(7, 8, 9))
        self.assertVector(sv.face_target(sphere.Faces[0])["center"], (7, 8, 9))
        profile = Part.BSplineCurve([App.Vector(5, 0, 0), App.Vector(7, 0, 4), App.Vector(5, 0, 8)])
        revolved = profile.toShape().revolve(App.Vector(0, 0, 0), Z, 360)
        face = next(face for face in revolved.Faces if isinstance(face.Surface, Part.SurfaceOfRevolution))
        target = sv.face_target(face)
        self.assertEqual(target["kind"], sv.CENTER)
        self.assertVector((target["center"].x, target["center"].y), (0, 0))

    def test_round_flat_faces_cut_through_their_centre(self):
        disk = Part.makeCylinder(5, 4, App.Vector(2, 3, 4), Z)
        top = next(face for face in disk.Faces if isinstance(face.Surface, Part.Plane) and face.CenterOfMass.z > 7)
        target = sv.face_target(top)
        self.assertEqual(target["kind"], sv.CENTER)
        self.assertVector(target["center"], (2, 3, 8))
        washer = Part.makeCylinder(10, 5).cut(Part.makeCylinder(4, 5))
        ring = next(face for face in washer.Faces if isinstance(face.Surface, Part.Plane) and face.CenterOfMass.z > 4)
        self.assertVector(sv.face_target(ring)["center"], (0, 0, 5))
        halves = [Part.ArcOfCircle(Part.Circle(App.Vector(1, 1, 0), Z, 3), 0, math.pi).toShape(),
                  Part.ArcOfCircle(Part.Circle(App.Vector(1, 1, 0), Z, 3), math.pi, 2 * math.pi).toShape()]
        split = Part.Face(Part.Wire(halves))
        self.assertEqual(len(split.OuterWire.Edges), 2)
        self.assertVector(sv.face_target(split)["center"], (1, 1, 0))

    def test_other_flat_faces_cut_on_their_own_plane(self):
        box = Part.makeBox(10, 20, 30, App.Vector(1, 2, 3))
        side = next(face for face in box.Faces if abs(face.CenterOfMass.x - 11) < 1e-9)
        target = sv.face_target(side)
        self.assertEqual(target["kind"], sv.PLANE)
        self.assertVector(target["origin"], (11, 12, 18))
        self.assertAlmostEqual(abs(target["normal"].x), 1)
        cut = sv.section_plane(target, FROM_RIGHT)
        self.assertVector(cut["normal"], (1, 0, 0))
        cut = sv.section_plane(target, App.Vector(1, 0, 0))
        self.assertVector(cut["normal"], (-1, 0, 0))
        self.assertEqual(cut["label"], "face plane")
        # A "D" outline (an arc plus a line) is not round.
        arc = Part.ArcOfCircle(Part.Circle(App.Vector(0, 0, 0), Z, 5), 0, math.pi).toShape()
        line = Part.LineSegment(App.Vector(-5, 0, 0), App.Vector(5, 0, 0)).toShape()
        self.assertEqual(sv.face_target(Part.Face(Part.Wire([arc, line])))["kind"], sv.PLANE)

    def test_freeform_faces_cut_through_their_centre_of_mass(self):
        surface = Part.BSplineSurface()
        surface.interpolate([[App.Vector(x, y, 0.2 * x * y) for y in range(4)] for x in range(4)])
        face = surface.toShape()
        target = sv.face_target(face)
        self.assertEqual(target["kind"], sv.CENTER)
        self.assertFalse(target["round"])
        self.assertVector(target["center"], face.CenterOfMass)

    def test_planes_cut_on_themselves_with_the_arrow_over_the_model(self):
        placement = App.Placement(App.Vector(0, 0, 5), App.Rotation(X, 90))
        target = sv.plane_target(placement, "Datum")
        self.assertVector(target["normal"], (0, -1, 0))
        cut = sv.section_plane(target, FROM_FRONT)
        self.assertEqual(cut["label"], "Datum")
        self.assertVector(cut["normal"], (0, -1, 0))
        box = App.BoundBox(40, -10, 0, 60, 30, 20)
        point = sv.recentered(target["origin"], target["normal"], box)
        self.assertVector(point, (50, 0, 10))

    def test_plane_rectangle_covers_the_model(self):
        box = App.BoundBox(-5, -6, -7, 15, 26, 37)
        point, normal = App.Vector(5, 10, 15), App.Vector(1, 1, 0).normalize()
        corners = sv.plane_rectangle(box, point, normal)
        u, v = sv.plane_axes(normal)
        self.assertAlmostEqual(u.dot(normal), 0)
        self.assertAlmostEqual(u.cross(v).dot(normal), 1)
        us = [c.dot(u) for c in corners]
        vs = [c.dot(v) for c in corners]
        for x in (box.XMin, box.XMax):
            for y in (box.YMin, box.YMax):
                for z in (box.ZMin, box.ZMax):
                    relative = App.Vector(x, y, z) - point
                    self.assertTrue(min(us) < relative.dot(u) < max(us))
                    self.assertTrue(min(vs) < relative.dot(v) < max(vs))
        for corner in corners:
            self.assertAlmostEqual(corner.dot(normal), 0, places=9)

    @staticmethod
    def cut_area(shape, origin, normal, tolerance=0.02):
        """Total triangle area and outline count of the cut faces of each solid of ``shape``."""
        area, outlines, pieces = 0.0, 0, 0
        for solid in shape.Solids:
            points, triangles, lines = sv.cut_face(sv.SolidMesh(solid, tolerance), origin, normal, tolerance)
            pieces += bool(triangles)
            outlines += len(lines)
            for a, b, c in triangles:
                pa, pb, pc = (App.Vector(*points[i]) for i in (a, b, c))
                area += (pb - pa).cross(pc - pa).Length / 2
                for point in (pa, pb, pc):
                    assert abs((point - App.Vector(origin)).dot(normal)) < 1e-9
        return area, outlines, pieces

    def test_cut_faces_fill_each_solid_from_its_mesh(self):
        tube = Part.makeCylinder(10, 30).cut(Part.makeCylinder(6, 30))
        area, outlines, _ = self.cut_area(tube, App.Vector(0, 0, 0), X)
        self.assertAlmostEqual(area, 2 * 4 * 30, delta=0.01 * 240)
        self.assertEqual(outlines, 2)
        area, outlines, _ = self.cut_area(tube, App.Vector(0, 0, 10), Z)
        self.assertAlmostEqual(area, math.pi * (100 - 36), delta=0.01 * math.pi * 64)
        self.assertEqual(outlines, 2)  # the ring: one outer loop and its hole
        # Two overlapping solids: two full cut faces, never one solid's section as a hole in the other.
        pair = Part.makeCompound([Part.makeBox(10, 10, 10), Part.makeBox(4, 4, 10, App.Vector(3, 3, 0))])
        area, _, pieces = self.cut_area(pair, App.Vector(0, 0, 5), Z)
        self.assertEqual(pieces, 2)
        self.assertAlmostEqual(area, 100 + 16, places=6)
        self.assertEqual(self.cut_area(tube, App.Vector(0, 0, 50), Z), (0.0, 0, 0))
        # A plane through mesh vertices still closes its loop; one lying on a face cuts nothing.
        box = Part.makeBox(10, 20, 30)
        self.assertAlmostEqual(self.cut_area(box, App.Vector(5, 0, 0), X)[0], 600, places=6)
        self.assertAlmostEqual(self.cut_area(box, App.Vector(0, 0, 15), Z)[0], 200, places=6)
        self.assertEqual(self.cut_area(box, App.Vector(0, 0, 0), Z)[0], 0.0)

    def test_cut_faces_match_the_exact_section_of_a_freeform_part(self):
        solid = Part.makeCylinder(8, 20).fuse(Part.makeSphere(9, App.Vector(0, 0, 20))).removeSplitter()
        solid = solid.cut(Part.makeBox(4, 30, 60, App.Vector(-2, -15, -5)))
        for origin, normal in ((App.Vector(4, 0, 0), X), (App.Vector(0, 0, 21), Z), (App.Vector(0, 3, 0), Y)):
            wires = [wire for wire in solid.slice(normal, origin.dot(normal)) if wire.isClosed()]
            exact = Part.makeFace(wires, "Part::FaceMakerBullseye").Area
            area, _, _ = self.cut_area(solid, origin, normal, 0.01)
            self.assertAlmostEqual(area, exact, delta=0.005 * exact)

    def test_status_text_names_the_tool_and_offset(self):
        text = sv.status_text("Right plane", 12.4)
        self.assertTrue(text.startswith("Section View · Right plane · +12.40 mm"))
        self.assertIn("Shift+X or Esc exits", text)
        self.assertIn("-3.25 mm", sv.status_text("Top plane", -3.25))
        self.assertIn("+0.00 mm", sv.status_text("Top plane", -0.001))
        self.assertNotIn("lipping", sv.PICK_TEXT + text)


class PolygonFillTests(unittest.TestCase):
    """Ear clipping with holes for the cut faces."""

    @staticmethod
    def area(rings, triangles):
        flat = [p for ring in rings for p in ring]
        return sum(abs((flat[b][0] - flat[a][0]) * (flat[c][1] - flat[a][1])
                       - (flat[c][0] - flat[a][0]) * (flat[b][1] - flat[a][1])) / 2 for a, b, c in triangles)

    def test_triangulates_convex_concave_and_holed_polygons(self):
        from kurtshape import polygon_fill as pf
        square = [(0, 0), (10, 0), (10, 10), (0, 10)]
        self.assertEqual(len(pf.triangulate([square])), 2)
        self.assertAlmostEqual(self.area([square], pf.triangulate([square])), 100)
        ell = [(0, 0), (6, 0), (6, 2), (2, 2), (2, 6), (0, 6)]
        self.assertAlmostEqual(self.area([ell], pf.triangulate([ell])), 20)
        flipped = list(reversed(ell))
        self.assertAlmostEqual(self.area([flipped], pf.triangulate([flipped])), 20)
        holes = [square, [(2, 2), (4, 2), (4, 4), (2, 4)], [(6, 6), (8, 6), (8, 8), (6, 8)]]
        triangles = pf.triangulate(holes)
        self.assertEqual(len(triangles), 12 + 2 * 2 - 2)
        self.assertAlmostEqual(self.area(holes, triangles), 100 - 8)
        circle = [(math.cos(a) * 20, math.sin(a) * 20) for a in (2 * math.pi * k / 400 for k in range(400))]
        ring = [(math.cos(a) * 9, math.sin(a) * 9) for a in (2 * math.pi * k / 150 for k in range(150))]
        triangles = pf.triangulate([circle, ring])
        expected = abs(pf.polygon_area(circle)) - abs(pf.polygon_area(ring))
        self.assertAlmostEqual(self.area([circle, ring], triangles), expected, places=6)

    def test_regions_nest_holes_and_islands(self):
        from kurtshape import polygon_fill as pf
        outer = [(0, 0), (30, 0), (30, 30), (0, 30)]
        hole = [(5, 5), (25, 5), (25, 25), (5, 25)]
        island = [(10, 10), (20, 10), (20, 20), (10, 20)]
        apart = [(40, 0), (50, 0), (50, 10), (40, 10)]
        groups = sorted(sorted(group) for group in pf.regions([outer, hole, island, apart]))
        self.assertEqual(groups, [[0, 1], [2], [3]])

    def test_simplify_keeps_corners_and_drops_collinear_points(self):
        from kurtshape import polygon_fill as pf
        dense = [(x, 0) for x in range(11)] + [(10, y) for y in range(1, 11)] + [(0, 10)]
        self.assertEqual(pf.simplify(dense, 0.01), [(0, 0), (10, 0), (10, 10), (0, 10)])


class SectionViewSelectionTests(unittest.TestCase):
    """Selections resolve in world coordinates through Body paths, containers and links."""

    def setUp(self):
        self.doc = App.newDocument("SectionViewSelection")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def test_faces_planes_and_occurrences_resolve_in_world_coordinates(self):
        feature = self.doc.addObject("Part::Feature", "Rod")
        feature.Shape = Part.makeCylinder(3, 10)
        feature.Placement = App.Placement(App.Vector(0, 0, 5), App.Rotation())
        face = next(f"Face{i + 1}" for i, f in enumerate(feature.Shape.Faces) if isinstance(f.Surface, Part.Cylinder))
        target = sv.selection_target(feature, face)
        self.assertEqual(target["kind"], sv.CENTER)
        self.assertAlmostEqual(target["center"].z, 10)
        self.assertIsNone(sv.selection_target(feature, "Edge1"))
        container = self.doc.addObject("App::Part", "Occurrences")
        container.Placement = App.Placement(App.Vector(100, 0, 0), App.Rotation())
        link = self.doc.addObject("App::Link", "RodLink")
        link.LinkedObject = feature
        link.Placement = App.Placement(App.Vector(0, 50, 0), App.Rotation())
        container.addObject(link)
        self.doc.recompute()
        target = sv.selection_target(container, link.Name + "." + face)
        # A native link places the source's shape by the link alone (LinkTransform off), as drawn.
        self.assertFalse(link.LinkTransform)
        self.assertAlmostEqual(target["center"].x, 100, places=6)
        self.assertAlmostEqual(target["center"].y, 50, places=6)
        self.assertAlmostEqual(target["center"].z, 5, places=6)

    def test_origin_and_datum_planes_follow_their_body(self):
        body = self.doc.addObject("PartDesign::Body", "Body")
        body.Placement = App.Placement(App.Vector(0, 0, 25), App.Rotation())
        self.doc.recompute()
        xy = next(obj for obj in body.Origin.OriginFeatures if getattr(obj, "Role", "").startswith("XY_Plane"))
        target = sv.selection_target(body, body.Origin.Name + "." + xy.Name + ".")
        self.assertEqual(target["label"], "Top plane")
        self.assertAlmostEqual(target["origin"].z, 25)
        self.assertAlmostEqual(abs(target["normal"].z), 1)
        direct = sv.selection_target(xy, "")
        self.assertEqual(direct["label"], "Top plane")
        self.assertAlmostEqual(direct["origin"].z, 25)
        datum = body.newObject("PartDesign::Plane", "Datum")
        datum.Placement = App.Placement(App.Vector(0, 3, 0), App.Rotation(X, -90))
        self.doc.recompute()
        target = sv.selection_target(datum, "")
        self.assertEqual(target["label"], datum.Label)
        self.assertAlmostEqual(abs(target["normal"].y), 1, places=6)
        self.assertAlmostEqual(target["origin"].z, 25, places=6)
        through_body = sv.selection_target(body, datum.Name + ".")
        self.assertAlmostEqual((through_body["origin"] - target["origin"]).Length, 0, places=9)
        self.assertAlmostEqual(abs(through_body["normal"].dot(target["normal"])), 1, places=9)

    def test_cut_faces_take_the_colour_of_the_body_they_cut(self):
        self.assertEqual(sv.cap_color((0.2, 0.4, 0.6, 0.0)), (0.2, 0.4, 0.6))
        feature = self.doc.addObject("Part::Feature", "Painted")
        feature.Shape = Part.makeBox(1, 1, 1)
        feature.addProperty("App::PropertyColor", "KurtShapePartColor", "KurtShape")
        feature.KurtShapePartColor = (0.1, 0.5, 0.9)
        link = self.doc.addObject("App::Link", "PaintedLink")
        link.LinkedObject = feature
        self.doc.recompute()
        # Without a GUI there is no view object: the stored part colour, also through a link.
        for obj in (feature, link):
            self.assertEqual([round(c, 4) for c in sv.part_color(obj)], [0.1, 0.5, 0.9])
            self.assertEqual(sv.cap_color(sv.part_color(obj)), sv.part_color(obj))

    def test_section_shortcut_is_bound_to_the_panels_section_view(self):
        from kurtshape import viewport_actions

        class Owner:
            def __init__(self):
                self.section_view = sv.SectionView(self)

        owner = Owner()
        callbacks = viewport_actions.callbacks(owner)
        self.assertEqual(set(callbacks), {"view.construction", "view.named", "view.high_quality", "view.section"})
        self.assertIs(callbacks["view.section"].__self__, owner.section_view)
        self.assertFalse(hasattr(viewport_actions.ViewportActions, "section_view"))


if __name__ == "__main__":
    unittest.main()
