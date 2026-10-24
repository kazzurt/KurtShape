"""Assembly UX item 6: measurements of the selection in global coordinates."""
import math
import unittest

import FreeCAD as App
import Part

from test_assembly import AssemblyWorkflowTests
from kurtshape import measure_readout as measure


def box(x=10, y=20, z=30, at=(0, 0, 0)):
    return Part.makeBox(x, y, z, App.Vector(*at))


def cylinder(radius, height, at=(0, 0, 0), direction=(0, 0, 1)):
    return Part.makeCylinder(radius, height, App.Vector(*at), App.Vector(*direction))


def face(shape, predicate):
    return next(value for value in shape.Faces if predicate(value))


def lateral(shape):
    return face(shape, lambda value: isinstance(value.Surface, Part.Cylinder))


class MeasureReadoutTests(unittest.TestCase):
    def assertClose(self, actual, expected, places=6):
        self.assertAlmostEqual(actual, expected, places=places)

    def test_nothing_and_single_elements(self):
        self.assertEqual(measure.describe([]), {"kind": "none", "text": "", "values": {}})
        solid = box()
        vertex = measure.describe([Part.Vertex(App.Vector(1, 2.5, -3))])
        self.assertEqual(vertex["text"], "X 1.000 · Y 2.500 · Z -3.000 mm")
        edge = measure.describe([Part.LineSegment(App.Vector(), App.Vector(3, 4, 0)).toShape()])
        self.assertEqual(edge["text"], "Length 5.000 mm")
        circle = measure.describe([Part.makeCircle(2.5)])
        self.assertEqual(circle["kind"], "circle")
        self.assertEqual(circle["text"], "Ø 5.000 mm · R 2.500 mm")
        top = face(solid, lambda value: abs(value.CenterOfMass.z - 30) < 1e-9)
        plane = measure.describe([top])
        self.assertEqual(plane["text"], "Area 200.000 mm² · Normal (0.000, 0.000, 1.000)")
        side = measure.describe([lateral(cylinder(3, 12))])
        self.assertEqual(side["text"], "Ø 6.000 mm · R 3.000 mm · Axis length 12.000 mm")
        whole = measure.describe([solid])
        self.assertEqual(whole["kind"], "body")
        self.assertEqual(whole["text"], "ΔX 10.000 · ΔY 20.000 · ΔZ 30.000 mm · Volume 6000.000 mm³")
        sphere = measure.describe([Part.makeSphere(2).Faces[0]])
        self.assertEqual(sphere["kind"], "face")
        self.assertClose(sphere["values"]["area_mm2"], 16 * math.pi)

    def test_two_vertices_signed_delta(self):
        result = measure.describe([Part.Vertex(App.Vector(1, 1, 1)), Part.Vertex(App.Vector(4, -3, 1))])
        self.assertEqual(result["kind"], "distance")
        self.assertEqual(result["text"], "Distance 5.000 mm · ΔX 3.000 · ΔY -4.000 · ΔZ 0.000 mm")
        reverse = measure.describe([Part.Vertex(App.Vector(4, -3, 1)), Part.Vertex(App.Vector(1, 1, 1))])
        self.assertClose(reverse["values"]["dx_mm"], -3)

    def test_point_to_face_and_edge(self):
        top = face(box(), lambda value: abs(value.CenterOfMass.z - 30) < 1e-9)
        result = measure.describe([Part.Vertex(App.Vector(5, 5, 40)), top])
        self.assertEqual(result["kind"], "point_distance")
        self.assertEqual(result["text"], "Minimum distance 10.000 mm · ΔX 0.000 · ΔY 0.000 · ΔZ -10.000 mm")
        reverse = measure.describe([top, Part.Vertex(App.Vector(5, 5, 40))])
        self.assertClose(reverse["values"]["dz_mm"], 10)
        line = Part.LineSegment(App.Vector(0, 0, 0), App.Vector(10, 0, 0)).toShape()
        to_edge = measure.describe([Part.Vertex(App.Vector(3, 4, 0)), line])
        self.assertClose(to_edge["values"]["distance_mm"], 4)
        self.assertClose(to_edge["values"]["dy_mm"], -4)

    def test_planar_faces_parallel_overlap_and_angle(self):
        solid = box()
        top = face(solid, lambda value: abs(value.CenterOfMass.z - 30) < 1e-9)
        bottom = face(solid, lambda value: abs(value.CenterOfMass.z) < 1e-9)
        result = measure.describe([bottom, top])
        self.assertEqual(result["kind"], "parallel_planes")
        # The bottom face's outward normal is -Z, so the top lies at -30 along it.
        self.assertClose(result["values"]["distance_mm"], -30)
        self.assertTrue(result["values"]["overlap"])
        self.assertEqual(result["text"], "Parallel distance -30.000 mm · overlapping")
        far = face(box(at=(100, 0, 0)), lambda value: abs(value.CenterOfMass.z - 30) < 1e-9)
        apart = measure.describe([top, far])
        self.assertClose(apart["values"]["distance_mm"], 0)
        self.assertFalse(apart["values"]["overlap"])
        nearly = top.copy()
        nearly.rotate(App.Vector(5, 10, 30), App.Vector(1, 0, 0), 0.4)
        self.assertEqual(measure.describe([bottom, nearly])["kind"], "parallel_planes", "within 0.5° is parallel")
        side = face(solid, lambda value: abs(value.CenterOfMass.x - 10) < 1e-9)
        angled = measure.describe([top, side])
        self.assertEqual(angled["kind"], "plane_angle")
        self.assertEqual(angled["text"], "Angle 90.00° · Minimum distance 0.000 mm")
        tilted = top.copy()
        tilted.rotate(App.Vector(5, 10, 30), App.Vector(1, 0, 0), 120)
        self.assertClose(measure.describe([top, tilted])["values"]["angle_deg"], 60, 6)

    def test_axes_parallel_coaxial_and_skew(self):
        first = lateral(cylinder(2, 10))
        second = lateral(cylinder(3, 10, at=(6, 8, 5)))
        parallel = measure.describe([first, second])
        self.assertEqual(parallel["kind"], "parallel_axes")
        self.assertEqual(parallel["text"], "Axis distance 10.000 mm · ΔX 6.000 · ΔY 8.000 · ΔZ 0.000 mm · Ø 4.000 mm · Ø 6.000 mm")
        coaxial = measure.describe([first, lateral(cylinder(5, 4, at=(0, 0, 20)))])
        self.assertEqual(coaxial["text"], "Coaxial · Ø 4.000 mm · Ø 10.000 mm")
        almost = measure.describe([first, lateral(cylinder(5, 4, at=(0.0005, 0, 20)))])
        self.assertEqual(almost["kind"], "coaxial", "within 1 µm radial")
        off = measure.describe([first, lateral(cylinder(5, 4, at=(0.01, 0, 20)))])
        self.assertEqual(off["kind"], "parallel_axes")
        skew = measure.describe([first, lateral(cylinder(1, 10, at=(-5, 7, 3), direction=(1, 0, 0)))])
        self.assertEqual(skew["kind"], "axis_angle")
        self.assertEqual(skew["text"], "Axis angle 90.00° · Axis distance 7.000 mm · Ø 4.000 mm · Ø 2.000 mm")
        edge = next(value for value in cylinder(2, 10, at=(6, 8, 0)).Edges if isinstance(value.Curve, Part.Circle))
        with_edge = measure.describe([first, edge])
        self.assertEqual(with_edge["kind"], "parallel_axes")
        self.assertClose(with_edge["values"]["distance_mm"], 10)

    def test_tilted_cylinder_axis(self):
        direction = App.Vector(1, 1, 1).normalize()
        tilted = lateral(cylinder(1.5, 9, direction=tuple(direction)))
        single = measure.describe([tilted])
        self.assertClose(single["values"]["axis_length_mm"], 9)
        self.assertClose(single["values"]["diameter_mm"], 3)
        offset = App.Vector(1, -1, 0).normalize() * 4
        other = lateral(cylinder(2, 5, at=tuple(offset), direction=tuple(direction)))
        result = measure.describe([tilted, other])
        self.assertEqual(result["kind"], "parallel_axes")
        self.assertClose(result["values"]["distance_mm"], 4)

    def test_plane_and_cylinder(self):
        floor = face(box(50, 50, 1, at=(-25, -25, -1)), lambda value: abs(value.CenterOfMass.z) < 1e-9)
        lying = lateral(cylinder(2, 10, at=(0, 0, 5), direction=(1, 0, 0)))
        result = measure.describe([floor, lying])
        self.assertEqual(result["kind"], "axis_to_plane")
        self.assertEqual(result["text"], "Distance (axis to plane) 5.000 mm")
        standing = measure.describe([lateral(cylinder(2, 10)), floor])
        self.assertEqual(standing["kind"], "axis_plane_angle")
        self.assertEqual(standing["text"], "Angle 90.00°")

    def test_two_edges(self):
        a = Part.LineSegment(App.Vector(0, 0, 0), App.Vector(10, 0, 0)).toShape()
        b = Part.LineSegment(App.Vector(2, 3, 4), App.Vector(8, 3, 4)).toShape()
        self.assertEqual(measure.describe([a, b])["text"], "Parallel distance 5.000 mm")
        c = Part.LineSegment(App.Vector(0, 5, 0), App.Vector(5, 10, 0)).toShape()
        angled = measure.describe([a, c])
        self.assertEqual(angled["kind"], "line_angle")
        self.assertClose(angled["values"]["angle_deg"], 45)
        self.assertClose(angled["values"]["distance_mm"], 5)
        arc = Part.makeCircle(2, App.Vector(0, 0, 10), App.Vector(1, 0, 0), 0, 90)
        spline = Part.BSplineCurve([App.Vector(0, 0, 0), App.Vector(1, 2, 0), App.Vector(3, 3, 0)]).toShape()
        other = measure.describe([spline, a])
        self.assertEqual(other["kind"], "minimum_distance")
        self.assertEqual(measure.describe([arc, spline])["kind"], "minimum_distance")

    def test_three_or_more_report_minimum_distance_and_overall_box(self):
        shapes = [Part.Vertex(App.Vector(0, 0, 0)), Part.Vertex(App.Vector(3, 4, 0)), box(1, 1, 1, at=(9, 9, 9))]
        result = measure.describe(shapes)
        self.assertEqual(result["kind"], "selection")
        self.assertEqual(result["text"], "Minimum distance 5.000 mm (first two) · 3 selected · ΔX 10.000 · ΔY 10.000 · ΔZ 10.000 mm")


class MeasureAssemblyTests(unittest.TestCase):
    for _name in ("setUp", "tearDown", "doc", "request", "call", "reject", "source_project", "insert", "fixture"):
        locals()[_name] = AssemblyWorkflowTests.__dict__[_name]

    def test_occurrence_faces_are_measured_where_they_sit(self):
        self.call("create_assembly", id="Asm")
        self.insert("Left")
        self.insert("Right")
        self.call("move_assembly_instance", instance="Right", position_mm=[40, 0, 0], rotation_xyzw=[0, 0, 0, 1])
        left, right = self.doc.getObject("Left"), self.doc.getObject("Right")
        source = left.LinkedObject.Shape
        top_name = "Face" + str(1 + next(i for i, value in enumerate(source.Faces)
                                         if abs(value.CenterOfMass.z - source.BoundBox.ZMax) < 1e-9))
        local = right.LinkedObject.Shape.getElement(top_name).CenterOfMass
        world = measure.element_shape(right, top_name).CenterOfMass
        self.assertLess((world - right.getParentGeoFeatureGroup().getGlobalPlacement().multVec(right.Placement.multVec(local))).Length, 1e-6)
        self.assertAlmostEqual(world.x - measure.element_shape(left, top_name).CenterOfMass.x, 40, 6)
        result = measure.measure_selection([(left, top_name), (right, top_name)])
        self.assertEqual(result["kind"], "parallel_planes")
        self.assertAlmostEqual(result["values"]["distance_mm"], 0, 6)
        vertex = measure.measure_selection([(left, "Vertex1"), (right, "Vertex1")])
        self.assertAlmostEqual(vertex["values"]["distance_mm"], 40, 6)
        self.assertAlmostEqual(vertex["values"]["dx_mm"], 40, 6)
        # Moving the assembly itself moves every occurrence in the world frame.
        self.doc.getObject("Asm").Placement.Base = App.Vector(0, 0, 100)
        self.doc.recompute()
        raised = measure.element_shape(left, top_name).CenterOfMass
        self.assertLess((raised - left.getParentGeoFeatureGroup().getGlobalPlacement().multVec(left.Placement.multVec(source.getElement(top_name).CenterOfMass))).Length, 1e-6)
        self.assertAlmostEqual(raised.z - world.z, 100, 6)

    def test_bridge_measure_with_native_references_and_selectors(self):
        self.call("create_assembly", id="Asm")
        self.insert("Left")
        self.insert("Right")
        self.call("move_assembly_instance", instance="Right", position_mm=[40, 0, 0], rotation_xyzw=[0, 0, 0, 1])
        revision = self.state["revision"]
        result = self.call("measure", references=[{"object": "Left", "subelement": "Vertex1"},
                                                   {"object": "Right", "subelement": "Vertex1"}])
        self.assertEqual(result["kind"], "distance")
        self.assertAlmostEqual(result["values"]["dx_mm"], 40, 6)
        self.assertEqual(self.state["revision"], revision)
        whole = self.call("measure", references=[{"object": "Left"}])
        self.assertEqual(whole["kind"], "body")
        self.reject("measure", "missing_reference", references=[{"object": "Ghost", "subelement": "Face1"}])
        self.reject("measure", "missing_reference", references=[{"object": "Left", "subelement": "Face99"}])
        self.reject("measure", "invalid_argument", references=[])

    def test_bridge_measure_with_selectors_in_a_part(self):
        self.call("new", name="Measured part")
        self.call("sketch_rectangle", id="Outline", width=20, height=12, body="Body")
        self.call("pad", id="Extrude", profile="Outline", length=8, body="Body")
        top = {"kind": "closest", "point": [10, 6, 8], "query": {"kind": "owned_by", "part": "Body", "entity_type": "face"}}
        bottom = {"kind": "closest", "point": [10, 6, 0], "query": {"kind": "owned_by", "part": "Body", "entity_type": "face"}}
        result = self.call("measure", references=[top, bottom])
        self.assertEqual(result["kind"], "parallel_planes")
        self.assertAlmostEqual(abs(result["values"]["distance_mm"]), 8, 6)


if __name__ == "__main__":
    unittest.main()
