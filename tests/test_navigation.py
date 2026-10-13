"""Geometry checks for drawing on tilted sketch planes after camera orbit."""
import math
from pathlib import Path
import sys
import unittest
import FreeCAD as App

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from kurtshape.navigation import intersect_sketch_plane, sketch_plane_point, reset_new_document_view
from kurtshape.hover_outline import boundary_polylines, is_face_reference


class SketchProjectionTests(unittest.TestCase):
    def assertPoint(self, point, expected):
        self.assertIsNotNone(point)
        self.assertLess((point-App.Vector(*expected)).Length, 1e-8)

    def test_new_document_camera_clears_previous_pan_and_zoom(self):
        from pivy import coin

        class View:
            def __init__(self):
                self.camera = coin.SoOrthographicCamera()
                self.camera.position.setValue(500, -800, 1200)
                self.camera.focalDistance.setValue(10)
                self.camera.height.setValue(25000)
                self.redrawn = False

            def setCameraType(self, kind):
                self.kind = kind

            def getCameraNode(self):
                return self.camera

            def getCameraOrientation(self):
                return App.Rotation(*self.camera.orientation.getValue().getValue())

            def redraw(self):
                self.redrawn = True

        view = View()
        self.assertTrue(reset_new_document_view(view))
        camera = view.camera
        position = App.Vector(*camera.position.getValue().getValue())
        focus = position - view.getCameraOrientation().multVec(
            App.Vector(0, 0, camera.focalDistance.getValue()))
        self.assertLess(focus.Length, 1e-5)
        self.assertEqual(camera.height.getValue(), 100)
        self.assertEqual(view.kind, 'Orthographic')
        self.assertTrue(view.redrawn)

    def test_oblique_ray_hits_translated_xy_plane(self):
        placement = App.Placement(App.Vector(12, 15, 7), App.Rotation())
        self.assertPoint(intersect_sketch_plane(App.Vector(20, 24, 30),
                                              App.Vector(1, 2, -23), placement), (9, 11, 0))

    def test_tilted_plane_returns_local_coordinates(self):
        placement = App.Placement(App.Vector(20, -8, 4), App.Rotation(App.Vector(1, 1, 0), 38))
        target = placement.multVec(App.Vector(7.5, -2.25, 0))
        direction = App.Vector(0.3, -0.6, -1)
        origin = target-direction*75
        self.assertPoint(intersect_sketch_plane(origin, direction, placement), (7.5, -2.25, 0))

    def test_direction_scale_does_not_change_intersection(self):
        placement = App.Placement()
        origin, direction = App.Vector(8, 3, 30), App.Vector(0.2, -0.1, -0.6)
        expected = intersect_sketch_plane(origin, direction, placement)
        for scale in (1e-6, 1, 1e8):
            actual = intersect_sketch_plane(origin, direction*scale, placement)
            self.assertLess((actual-expected).Length, 1e-8)

    def test_edge_on_or_invalid_ray_is_rejected(self):
        placement = App.Placement()
        for direction in (App.Vector(1, 0, 0), App.Vector(1, 0, 1e-9), App.Vector(0, 0, 0),
                          App.Vector(math.nan, 0, -1)):
            self.assertIsNone(intersect_sketch_plane(App.Vector(0, 0, 10), direction, placement))

    def test_pixel_projection_uses_native_ray_not_focal_plane(self):
        class View:
            def projectPointToLine(self, x, y):
                self.received = (x, y)
                return App.Vector(3, 2, 9), App.Vector(5, 4, 5)
        view = View()
        result = sketch_plane_point(view, (102.8, 93.3), App.Placement(App.Vector(0,0,1), App.Rotation()))
        self.assertPoint(result, (7, 6, 0))
        self.assertEqual(view.received, (102, 93))

    def test_face_hover_boundary_includes_inner_hole_and_outer_wire(self):
        import Part
        face = Part.makePlane(20, 15).cut(Part.Face(Part.Wire(Part.makeCircle(3, App.Vector(10, 7.5, 0))))).Faces[0]
        lines = boundary_polylines(face)
        self.assertEqual(len(lines), 5)
        circle = next(line for line in lines if len(line) > 2)
        self.assertLess((App.Vector(*circle[0]) - App.Vector(*circle[-1])).Length, 1e-8)
        for point in circle:
            self.assertAlmostEqual((App.Vector(*point) - App.Vector(10, 7.5, 0)).Length, 3, places=7)

    def test_face_hover_boundary_retains_shape_placement(self):
        import Part
        face = Part.makePlane(10, 8)
        face.Placement = App.Placement(App.Vector(4, 5, 12), App.Rotation(App.Vector(1, 0, 0), 30))
        lines = boundary_polylines(face)
        points = [App.Vector(*point) for line in lines for point in line]
        self.assertEqual(len(lines), 4)
        normal = face.Placement.Rotation.multVec(App.Vector(0, 0, 1))
        self.assertTrue(all(abs(normal.dot(point - face.Placement.Base)) < 1e-7 for point in points))

    def test_face_hover_only_accepts_native_faces(self):
        for element in ['Face1', 'Face204', 'Body.Pad.Face3']:
            self.assertTrue(is_face_reference(element))
        for element in ['', None, 'Edge1', 'Vertex2', 'Face0', 'SomeFace1', 'Face3.extra']:
            self.assertFalse(is_face_reference(element))


if __name__ == '__main__':
    unittest.main()
