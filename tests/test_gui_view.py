"""set_view (GUI view operation, 2026-10-20): camera math, rejections and a document left untouched; bundled Python.

Headless there is no 3D view, so these tests cover the computed camera, the op class and the Inventor
camera text the app receives (round trip through parse_camera). The GUI application path is described in
docs/OPERATION_CONTRACT.md "Viewport camera".
"""
from pathlib import Path
import math
import sys
import unittest
import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
from kurtshape.core import Controller
from kurtshape import gui_view


class GuiViewTests(unittest.TestCase):
    def setUp(self):
        self.initial_names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="gui-view-session-")
        self.core = Controller()
        self.state = self.call("new", name="Set view")
        self.call("sketch_rectangle", id="PlateProfile", body="Body", plane="XY", x=0, y=0, width=60, height=40)
        self.call("pad", id="Plate", profile="PlateProfile", length=6)

    def tearDown(self):
        for name in set(App.listDocuments()) - self.initial_names:
            App.closeDocument(name)
        self.core.observer.close()

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def request(self, op, **args):
        request = {"op": op, **args}
        if op not in {"new", "open", "set_view"}:
            request.update(document_id=self.state["document_id"], expected_revision=self.state["revision"])
        elif op == "set_view":
            request["document_id"] = self.state["document_id"]
        return self.core.dispatch(request)

    def call(self, op, **args):
        response = self.request(op, **args)
        self.assertTrue(response["ok"], response)
        if op != "set_view":
            self.state = response["result"]
        return response["result"]

    def rejected(self, code, **args):
        response = self.request("set_view", **args)
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], code, response)
        return response["error"]

    def assertVector(self, actual, expected, places=7):
        for a, b in zip(actual, expected):
            self.assertAlmostEqual(a, b, places=places)

    def test_is_a_view_operation(self):
        self.assertIn("set_view", Controller.VIEW_OPS)
        self.assertIn("set_view", Controller.NON_MUTATING_OPS)
        self.assertIn("set_view", Controller.QUIET_OPS)
        self.assertNotIn("set_view", Controller.READ_OPS)  # ledger-tracked through the bridge
        self.assertEqual(Controller.ARGS["set_view"], {"view", "frame"})

    def test_explicit_frame_gives_that_window_and_leaves_the_document_alone(self):
        before = (self.state["revision"], self.doc.UndoCount, self.call("inspect")["modified"])
        result = self.call("set_view", view={"direction": [0, 2, -2], "up": [0, 0, 5]},
                           frame={"center_mm": [30, 0, 3], "width_mm": "20 mm"})
        self.assertFalse(result["applied"])
        self.assertEqual(result["reason"], "no_gui")
        self.assertEqual(result["view"], "custom")
        camera = result["camera"]
        s = 1 / math.sqrt(2)
        self.assertVector(camera["direction"], [0, s, -s])
        self.assertVector(camera["up"], [0, s, s])
        self.assertVector(camera["right"], [1, 0, 0])
        self.assertVector(camera["center_mm"], [30, 0, 3])
        self.assertEqual(camera["height_mm"], 20)
        # In front of the whole plate (box 0..60 x 0..40 x 0..6) as seen along the direction.
        ahead = max((x - 30) * 0 + (y - 0) * -s + (z - 3) * s for x in (0, 60) for y in (0, 40) for z in (0, 6))
        self.assertGreaterEqual(camera["distance_mm"], ahead)
        state = self.call("inspect")
        self.assertEqual((state["revision"], self.doc.UndoCount, state["modified"]), before)
        self.assertEqual(result["revision"], before[0])

    def test_model_frame_spans_the_shown_solids(self):
        result = self.call("set_view", view="top")
        camera = result["camera"]
        self.assertEqual(result["frame"], "model")
        self.assertVector(camera["direction"], [0, 0, -1])
        self.assertVector(camera["up"], [0, 1, 0])
        self.assertVector(camera["center_mm"], [30, 20, 3], places=6)
        self.assertAlmostEqual(camera["height_mm"], 60 * gui_view.MODEL_MARGIN, places=6)
        default = self.call("set_view")  # iso, model
        self.assertEqual(default["view"], "iso")
        self.assertVector(default["camera"]["direction"], [-1 / math.sqrt(3), 1 / math.sqrt(3), -1 / math.sqrt(3)])

    def test_rejections(self):
        self.rejected("invalid_argument", view="sideways")
        self.rejected("invalid_argument", view={"direction": [0, 0, 0]})
        self.rejected("invalid_argument", view={"direction": [0, 0, 1], "up": [0, 0, -3]})
        self.rejected("invalid_argument", view={"direction": [1, 0, 0], "name": "x"})
        self.rejected("invalid_argument", view=[1, 0, 0])
        self.rejected("invalid_argument", frame="included")
        self.rejected("invalid_argument", frame={"center_mm": [0, 0, 0]})
        self.rejected("invalid_argument", frame={"center_mm": [0, 0, 0], "width_mm": 0})
        self.rejected("invalid_argument", frame={"center_mm": [0, 0], "width_mm": 5})
        self.rejected("unknown_argument", zoom=2)
        self.rejected("stale_revision", expected_revision="not-the-revision")

    def test_camera_text_round_trips_through_parse(self):
        for direction, up in [((-1, 1, -1), (0, 0, 1)), ((0, 0, -1), (0, 1, 0)), ((0, 0, 1), (0, -1, 0)),
                              ((0.3, -0.9, 0.2), (0, 0, 1)), ((1, 0, 0), (0, 0, 1))]:
            with self.subTest(direction=direction):
                d, u, r = gui_view.basis(direction, up)
                camera = {"direction": d, "up": u, "right": r, "center_mm": [-348.0, -252.9, 8.2],
                          "height_mm": 14.0, "distance_mm": 120.0}
                rotation = gui_view.rotation(d, u)
                mapped = rotation.multVec(App.Vector(0, 0, -1))
                self.assertVector([mapped.x, mapped.y, mapped.z], d, places=9)
                mapped = rotation.multVec(App.Vector(0, 1, 0))
                self.assertVector([mapped.x, mapped.y, mapped.z], u, places=9)
                parsed = gui_view.parse_camera(gui_view.camera_text(camera))
                self.assertEqual(parsed["projection"], "orthographic")
                self.assertVector(parsed["direction"], d, places=8)
                self.assertVector(parsed["up"], u, places=8)
                self.assertVector(parsed["right"], r, places=8)
                self.assertVector(parsed["center_mm"], camera["center_mm"], places=5)
                self.assertAlmostEqual(parsed["height_mm"], 14.0, places=6)

    def test_parse_reads_freecad_camera_text(self):
        # The form View3DInventor.getCamera returns (double space before the angle, blank lines).
        text = ("#Inventor V2.1 ascii\n\n\nOrthographicCamera {\n  viewportMapping ADJUST_CAMERA\n"
                "  position 5 5 50\n  orientation 0 0 1  0\n  nearDistance 1\n  farDistance 100\n"
                "  aspectRatio 1\n  focalDistance 45\n  height 3\n\n}\n")
        parsed = gui_view.parse_camera(text)
        self.assertVector(parsed["direction"], [0, 0, -1])
        self.assertVector(parsed["up"], [0, 1, 0])
        self.assertVector(parsed["center_mm"], [5, 5, 5])
        self.assertEqual(parsed["height_mm"], 3)


if __name__ == "__main__":
    unittest.main()
