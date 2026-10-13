"""Native edit preference lifetime without geometry changes or GUI polling."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from kurtshape.sketch_snapping import SketchSnapping


class Params:
    def __init__(self):
        self.values = {}

    def GetContents(self):
        return [("Boolean" if isinstance(v, bool) else "Float", k, v)
                for k, v in self.values.items()] or None

    def GetFloat(self, key, default=0.0): return self.values.get(key, default)
    def SetFloat(self, key, value): self.values[key] = value
    def RemFloat(self, key): self.values.pop(key, None)
    def GetBool(self, key, default=False): return self.values.get(key, default)
    def SetBool(self, key, value): self.values[key] = value
    def RemBool(self, key): self.values.pop(key, None)


class SketchSnappingTests(unittest.TestCase):
    def test_missing_origin_never_retries_scene_search_during_idle_ticks(self):
        with patch.object(self.snapping, "before_native") as search:
            for _ in range(100):
                self.snapping.sync_tool("Sketcher_CreateCircle")
            search.assert_not_called()

    def setUp(self):
        self.groups = {}
        def get(path):
            return self.groups.setdefault(path.rsplit("Preferences/", 1)[1], Params())
        self.snapping = SketchSnapping(get)
        self.sketch = SimpleNamespace(ViewObject=SimpleNamespace(Autoconstraints=False, AvoidRedundant=False))

    def test_native_edit_enables_point_snaps_and_restores_absent_preferences(self):
        self.snapping.begin(self.sketch)
        self.assertEqual(self.groups["View"].GetFloat("PickRadius"), 9.0)
        self.assertTrue(self.groups["Mod/Sketcher/Snap"].GetBool("SnapToObjects"))
        self.assertTrue(self.sketch.ViewObject.Autoconstraints)
        self.snapping.restore()
        self.assertTrue(all(not p.values for p in self.groups.values()))
        self.assertFalse(self.sketch.ViewObject.Autoconstraints)
        self.assertFalse(self.sketch.ViewObject.AvoidRedundant)

    def test_repeated_begin_keeps_original_lifetime_and_user_changes_survive(self):
        self.snapping.begin(self.sketch)
        self.snapping.begin(self.sketch)
        self.groups["View"].SetFloat("PickRadius", 14.0)
        self.snapping.restore()
        self.assertEqual(self.groups["View"].GetFloat("PickRadius"), 14.0)
        self.assertFalse(self.sketch.ViewObject.Autoconstraints)
        self.snapping.restore()

    def test_existing_larger_aperture_and_disabled_snap_are_restored(self):
        self.snapping._param_get("Preferences/View").SetFloat("PickRadius", 12.0)
        self.snapping._param_get("Preferences/Mod/Sketcher/Snap").SetBool("Snap", False)
        self.snapping.begin(self.sketch)
        self.assertEqual(self.groups["View"].GetFloat("PickRadius"), 12.0)
        self.assertTrue(self.groups["Mod/Sketcher/Snap"].GetBool("Snap"))
        self.snapping.restore()
        self.assertEqual(self.groups["View"].GetFloat("PickRadius"), 12.0)
        self.assertFalse(self.groups["Mod/Sketcher/Snap"].GetBool("Snap", True))

    def test_high_dpi_uses_physical_pixels_for_same_logical_capture_area(self):
        self.snapping.begin(self.sketch, pixel_ratio=1.5)
        self.assertEqual(self.groups["View"].GetFloat("PickRadius"), 13.5)
        self.snapping.restore()
        self.assertNotIn("PickRadius", self.groups["View"].values)

    def test_aperture_keeps_nearest_point_and_releases_outside_capture(self):
        radius = self.snapping._capture_radius([2.8, .2], 9)
        self.assertGreater(radius, .2)
        self.assertLess(radius, 2.8)
        self.assertEqual(self.snapping._capture_radius([], 9), 9)
        self.assertEqual(self.snapping._capture_radius([10, 11], 9), 9)
        self.assertEqual(self.snapping._capture_radius([3], 9), 9)
        self.assertEqual(self.snapping._capture_radius([3, 3], 9), 9)
        self.assertEqual(self.snapping._capture_radius([0, .0003], 9), 9)
        self.assertEqual(self.snapping._capture_radius([6, 6.001], 9), 9)

    def test_coincident_presentation_markers_stay_together(self):
        distances = [9.629960030, 9.631220285]
        keys = [(0., 0.), (0., 0.)]
        self.assertEqual(self.snapping._capture_radius(distances, 13.5, keys), 13.5)
        radius = self.snapping._capture_radius(distances + [12.], 13.5, keys + [(1., 0.)])
        self.assertGreater(radius, max(distances))
        self.assertLess(radius, 12.)

    def _coin_picker(self, same_array=False, translated=False):
        import FreeCAD  # noqa: F401 -- load bundled native libraries.
        from pivy import coin
        root = coin.SoSeparator()
        root.ref()
        camera = coin.SoOrthographicCamera()
        camera.position = (0, 0, 10)
        camera.height = 10
        camera.nearDistance = 1
        camera.farDistance = 20
        root.addChild(camera)
        transform = coin.SoTranslation()
        transform.translation = (1 if translated else 0, 0, 0)
        root.addChild(transform)
        edit = coin.SoSeparator()
        edit.setName("Sketch_EditRoot")
        root.addChild(edit)
        targets = [(-.2, .1, 0), (0, 0, 0)]
        marker_nodes = []
        for index, points in enumerate([targets] if same_array else [[p] for p in targets]):
            group = coin.SoSeparator()
            coordinates = coin.SoCoordinate3()
            coordinates.point.setValues(0, len(points), points)
            group.addChild(coordinates)
            style = coin.SoPickStyle()
            style.style = coin.SoPickStyle.SHAPE_ON_TOP
            group.addChild(style)
            marker = coin.SoMarkerSet()
            marker.setName("PointSet" + str(index))
            marker.markerIndex = coin.SoMarkerSet.CIRCLE_FILLED_9_9
            marker.numPoints = len(points)
            group.addChild(marker)
            edit.addChild(group)
            marker_nodes.append(marker)
        viewport = coin.SbViewportRegion(200, 100)
        renderer = SimpleNamespace(getViewportRegion=lambda: viewport,
                                   getCamera=lambda: camera, getSceneGraph=lambda: root)
        viewer = SimpleNamespace(radius=9, getSoRenderManager=lambda: renderer)
        viewer.getPickRadius = lambda: viewer.radius
        viewer.setPickRadius = lambda value: setattr(viewer, "radius", value)
        view = SimpleNamespace(getViewer=lambda: viewer, graphicsView=lambda: None)
        self.snapping._prepare_picker(view)
        self.addCleanup(root.unref)
        self.addCleanup(self.snapping._restore_markers)
        return coin, root, viewport, viewer, marker_nodes, (110 if translated else 100, 50)

    def test_native_coin_nearest_endpoint_overrides_first_hit_without_proxy_nodes(self):
        for same_array, translated in ((False, False), (True, False), (False, True)):
            with self.subTest(same_array=same_array, translated=translated):
                coin, root, viewport, viewer, markers, point = self._coin_picker(same_array, translated)
                pick = coin.SoRayPickAction(viewport)
                pick.setPoint(coin.SbVec2s(*point))
                pick.setRadius(9)
                pick.apply(root)
                old = pick.getPickedPoint()
                self.assertAlmostEqual(old.getPoint()[1], .1)
                if not same_array:
                    self.assertEqual(str(old.getPath().getTail().getName()), "PointSet0")
                radius = self.snapping._nearest_radius(point)
                self.assertGreater(radius, 0)
                self.assertLess(radius, 1)
                self.snapping._set_radius(radius)
                pick.setRadius(viewer.radius)
                pick.apply(root)
                nearest = pick.getPickedPoint()
                self.assertIsNotNone(nearest)
                self.assertEqual(str(nearest.getPath().getTail().getName()), "PointSet0" if same_array else "PointSet1")
                self.assertEqual(nearest.getDetail().getTypeId(), coin.SoPointDetail.getClassTypeId())
                self.assertAlmostEqual(nearest.getPoint()[0], 1 if translated else 0)
                self.assertAlmostEqual(nearest.getPoint()[1], 0)
                self.assertEqual(self.snapping._nearest_radius((180, 80)), 9)
                self.snapping._restore_markers()
                self.assertEqual(viewer.radius, 9)

    def test_local_aperture_cleanup_preserves_an_external_viewer_change(self):
        _, _, _, viewer, _, point = self._coin_picker()
        self.snapping._set_radius(self.snapping._nearest_radius(point))
        viewer.radius = 7
        self.snapping._restore_markers()
        self.assertEqual(viewer.radius, 7)

    def test_oblique_origin_and_circle_center_depths_do_not_compete(self):
        coin, root, viewport, viewer, markers, _ = self._coin_picker()
        camera = self.snapping._renderer.getCamera()
        rotation = coin.SbRotation(coin.SbVec3f(1, 0, 0), .6108652381980153)
        camera.orientation = rotation
        camera.position = rotation.multVec(coin.SbVec3f(0, 0, 10))
        search = coin.SoSearchAction()
        search.setType(coin.SoCoordinate3.getClassTypeId())
        search.setInterest(coin.SoSearchAction.ALL)
        search.apply(root)
        paths = search.getPaths()
        paths[0].getTail().point.set1Value(0, coin.SbVec3f(0, 0, .001))
        paths[1].getTail().point.set1Value(0, coin.SbVec3f(0, 0, 0))
        markers[1].setName("OriginPointSet")
        self.snapping._pick_radius = self.snapping._applied_radius = viewer.radius = 13.5
        radius = self.snapping._nearest_radius((90, 48))
        self.assertEqual(radius, 13.5)
        pick = coin.SoRayPickAction(viewport)
        pick.setPoint(coin.SbVec2s(90, 48))
        pick.setRadius(radius)
        pick.apply(root)
        self.assertIsNotNone(pick.getPickedPoint())
        local = pick.getPickedPoint().getObjectPoint()
        self.assertEqual((local[0], local[1]), (0., 0.))

    def test_near_bisector_preserves_a_native_point_hit(self):
        coin, root, viewport, _, _, _ = self._coin_picker()
        search = coin.SoSearchAction()
        search.setType(coin.SoCoordinate3.getClassTypeId())
        search.setInterest(coin.SoSearchAction.ALL)
        search.apply(root)
        paths = search.getPaths()
        paths[0].getTail().point.set1Value(0, coin.SbVec3f(-.45, 0, 0))
        paths[1].getTail().point.set1Value(0, coin.SbVec3f(.45001, 0, 0))
        radius = self.snapping._nearest_radius((100, 50))
        self.assertEqual(radius, 9)
        pick = coin.SoRayPickAction(viewport)
        pick.setPoint(coin.SbVec2s(100, 50))
        pick.setRadius(radius)
        pick.apply(root)
        self.assertIsNotNone(pick.getPickedPoint())
        self.assertEqual(pick.getPickedPoint().getDetail().getTypeId(), coin.SoPointDetail.getClassTypeId())


if __name__ == "__main__":
    unittest.main(verbosity=2)
