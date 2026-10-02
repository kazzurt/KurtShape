"""Geometry checks for drawing on tilted sketch planes after camera orbit."""
import math
from pathlib import Path
import sys
import unittest
import FreeCAD as App

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from kurtshape.navigation import intersect_sketch_plane, sketch_plane_point


class SketchProjectionTests(unittest.TestCase):
    def assertPoint(self, point, expected):
        self.assertIsNotNone(point)
        self.assertLess((point-App.Vector(*expected)).Length, 1e-8)

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


if __name__ == '__main__':
    unittest.main()
