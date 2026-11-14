"""Result volume checks on parts whose OCCT volume depends on the integration reference point.

OCCT 7.8 integrates a solid's volume about the mean of its vertices. On faces
bounded by approximated (BSpline) intersection curves the integral carries an
error that moves with that point, so a Boolean's input and result, measured one
by one, are integrated about different points and the error of their shared
faces no longer cancels. On 13 Nov 2026 four Ø1.7 pilot cuts into the Birdcage
Pack V2 printed sled (a U-channel whose columns cut through its curved walls)
"removed" 0.037 mm3 more than their 72.63 mm3 tool against a 0.028 mm3 slack and
were rejected as `invalid_geometry`. A 30 mm section of that sled with pilots
in three bosses on one side reproduces it on FreeCAD 1.1.4 / OCCT 7.8.1.
"""
from pathlib import Path
import math
import sys
import unittest
from unittest.mock import patch

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
from kurtshape.core import Controller, OperationError
from kurtshape import geometry, studio

# The sled section (mm): deck y -12.5..-10.5, walls on the Ø34.4 / Ø30.4 bore up to y = 2.
OUT_R, IN_R, DECK_BOTTOM, DECK_TOP, WALL_TOP, LENGTH = 17.2, 15.2, -12.5, -10.5, 2.0, 30.0
POST_X, POST_Z = 12.25, (5.0, 15.0, 25.0)
COLUMN_D, COLUMN_TOP, BOSS_D, BOSS_TOP = 5.0, 1.5, 4.0, 4.5
PILOT_D, PILOT_DEPTH = 1.7, 8.0
PILOT_TOOL = 3 * math.pi * (PILOT_D / 2) ** 2 * PILOT_DEPTH


def chord(radius, y):
    return math.sqrt(radius * radius - y * y)


def own_volumes(shapes):
    """Each shape about its own reference point: what the contract 3.1 check compared."""
    return [geometry.scalar(shape, "volume") for shape in shapes]


def pilot_cylinders(side, radius=PILOT_D / 2, top=BOSS_TOP, length=PILOT_DEPTH):
    """The pilot tool as plain cylinders in the bosses on one side (x = side * POST_X), cutting toward -Y."""
    cylinders = [Part.makeCylinder(radius, length, App.Vector(side * POST_X, top, z), App.Vector(0, -1, 0))
                 for z in POST_Z]
    return cylinders[0].fuse(cylinders[1:])


class VolumeReferencePointTests(unittest.TestCase):
    def setUp(self):
        self.initial = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="volume-reference-session-")
        self.core = Controller()
        self.state = self.core.dispatch({"op": "new", "name": "Volume reference"})["result"]

    def tearDown(self):
        for name in set(App.listDocuments()) - self.initial:
            App.closeDocument(name)
        self.core.observer.close()

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def request(self, op, **kwargs):
        return self.core.dispatch({"op": op, "document_id": self.state["document_id"],
                                   "expected_revision": self.state["revision"], **kwargs})

    def call(self, op, **kwargs):
        response = self.request(op, **kwargs)
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        return self.state

    def snapshot(self):
        return (self.core._meta(self.doc).Revision, self.doc.UndoCount, sorted(obj.Name for obj in self.doc.Objects),
                {studio.part_id(body): None if body.Shape.isNull() else body.Shape.Volume
                 for body in studio.current_parts(self.doc)})

    def reject(self, code, op, **kwargs):
        before = self.snapshot()
        response = self.request(op, **kwargs)
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], code, response["error"])
        self.assertEqual(self.snapshot(), before, "a rejected request must leave the document unchanged")
        return response["error"]

    def preview(self, proposal):
        response = self.core.dispatch({"op": "preview", "document_id": self.state["document_id"],
                                       "expected_revision": self.state["revision"], "proposal": proposal})
        self.assertTrue(response["ok"], response)
        return response["result"]

    def part_shape(self, part):
        return studio.current_part(self.doc, part).Shape.copy()

    def sled_section(self):
        """The sled's U-channel (arcs on the bore), three column pairs through its walls, a boss on each column."""
        xb, xo, xi, xd = (chord(OUT_R, DECK_BOTTOM), chord(OUT_R, WALL_TOP), chord(IN_R, WALL_TOP),
                          chord(IN_R, DECK_TOP))
        self.call("create_sketch", id="Section", plane="XY")
        self.call("add_polyline", sketch="Section", points=[[-xb, DECK_BOTTOM], [xb, DECK_BOTTOM]])
        self.call("add_arc", sketch="Section", cx=0, cy=0, x1=xb, y1=DECK_BOTTOM, x2=xo, y2=WALL_TOP)
        self.call("add_polyline", sketch="Section", points=[[xo, WALL_TOP], [xi, WALL_TOP]])
        self.call("add_arc", sketch="Section", cx=0, cy=0, x1=xd, y1=DECK_TOP, x2=xi, y2=WALL_TOP)
        self.call("add_polyline", sketch="Section", points=[[xd, DECK_TOP], [-xd, DECK_TOP]])
        self.call("add_arc", sketch="Section", cx=0, cy=0, x1=-xi, y1=WALL_TOP, x2=-xd, y2=DECK_TOP)
        self.call("add_polyline", sketch="Section", points=[[-xi, WALL_TOP], [-xo, WALL_TOP]])
        self.call("add_arc", sketch="Section", cx=0, cy=0, x1=-xo, y1=WALL_TOP, x2=-xb, y2=DECK_BOTTOM)
        self.call("pad", id="Channel", profile="Section", length=LENGTH, operation="new")
        part = self.state["studio"]["parts"][-1]["id"]
        # XZ planes at world y (their normal is -Y): sketch (x, y) is world (x, z), and an extrusion runs toward -Y.
        for name, y, diameter, length in (("Columns", COLUMN_TOP, COLUMN_D, COLUMN_TOP - DECK_TOP + 0.2),
                                          ("Bosses", BOSS_TOP, BOSS_D, BOSS_TOP - COLUMN_TOP + 0.1)):
            self.call("create_plane", id=name + "Plane", base_plane="XZ", offset=-y)
            self.call("create_sketch", id=name, support={"feature": name + "Plane"})
            for z in POST_Z:
                for x in (POST_X, -POST_X):
                    self.call("add_circle", sketch=name, x=x, y=z, diameter=diameter)
            self.call("pad", id=name + "Pad", profile=name, length=length, operation="add", merge_scope=[part])
        return part

    def pilot_request(self, part, side):
        self.call("create_sketch", id="PilotSketch", support={"feature": "BossesPlane"})
        for z in POST_Z:
            self.call("add_circle", sketch="PilotSketch", x=side * POST_X, y=z, diameter=PILOT_D)
        return {"id": "Pilots", "profile": "PilotSketch", "through_all": False, "length": PILOT_DEPTH,
                "reversed": False, "operation": "remove", "merge_scope": [part]}

    def test_pilot_cut_far_from_the_vertex_mean_is_accepted(self):
        part = self.sled_section()
        before = self.part_shape(part)
        request = self.pilot_request(part, side=-1)
        # The contract 3.1 check, which compared each shape's own volume, rejected this cut.
        with patch.object(studio, "_shared_point_volumes", side_effect=own_volumes):
            error = self.reject("invalid_geometry", "pocket", **request)
        self.assertEqual((error["check"], error["feature"]), ("volume", "Pilots"))
        self.assertTrue(error["refine"]["retried_unrefined"])
        # Measured about one reference point it is the exact cut it is.
        self.call("pocket", **request)
        report = self.state["result_report"]
        self.assertEqual(report["refine"], {"requested": True, "applied": True, "retried_unrefined": False})
        self.assertEqual(report["geometry_check"], "valid")
        self.assertAlmostEqual(report["tool_volume_mm3"], PILOT_TOOL, places=6)
        row = report["parts"][0]
        excess = row["volume_before_mm3"] - row["volume_after_mm3"] - report["tool_volume_mm3"]
        slack = 1e-6 * (row["volume_before_mm3"] + report["tool_volume_mm3"])
        self.assertGreater(excess, 3 * slack, "this fixture no longer reproduces the reference-point error "
                                              "(each part's own volume measurement)")
        tool = pilot_cylinders(side=-1)
        shared_before, shared_tool, shared_after = studio._shared_point_volumes([before, tool, self.part_shape(part)])
        self.assertAlmostEqual(shared_tool, PILOT_TOOL, places=9)
        self.assertAlmostEqual(shared_before - shared_after, PILOT_TOOL, delta=1e-8)

    def test_a_cut_that_only_touches_the_part_stays_empty(self):
        """The same pilots run the wrong way and only touch the boss tops.

        The refined result is the unchanged part. The unrefined retry keeps the
        boss tops split where the tool touched them; the extra vertices move the
        reference point, and the 3.1 check took the volume this "removed" for a cut.
        """
        part = self.sled_section()
        request = dict(self.pilot_request(part, side=-1), reversed=True)
        proposal = {"op": "pocket", **{key: value for key, value in request.items() if key != "id"}}
        with patch.object(studio, "_shared_point_volumes", side_effect=own_volumes):
            accepted = self.preview(proposal)
        self.assertTrue(accepted["valid"], accepted)
        self.assertTrue(accepted["result_report"]["refine"]["retried_unrefined"])
        row = accepted["result_report"]["parts"][0]
        removed = row["volume_before_mm3"] - row["volume_after_mm3"]
        self.assertGreater(removed, 10 * studio._negligible(row["volume_before_mm3"], PILOT_TOOL),
                           "this fixture no longer shows a touching cut measuring as removal")
        error = self.reject("empty_cut", "pocket", **request)
        self.assertEqual((error["feature"], error["refine"]["refined_failure"]["code"]), ("Pilots", "empty_cut"))
        self.assertIsNone(self.doc.getObject("Pilots"))

    def test_shared_point_comparison_still_rejects_real_errors_on_a_noisy_part(self):
        """The checker itself on crafted results: only the reference point changes, never the bar."""
        part = self.sled_section()
        before = self.part_shape(part)

        def body(name, shape):
            feature = self.doc.addObject("Part::Feature", name + "Shape")
            feature.Shape = shape
            container = self.doc.addObject("PartDesign::Body", name)
            container.BaseFeature = feature
            return container
        target = body("Target", before)

        def check(name, tool, result):
            tool_body, result_body = body(name + "Tool", tool), body(name, result)
            self.doc.recompute()
            try:
                return studio._check_result(self.doc, "Op", "remove", tool_body, [("Body", target)], [result_body])
            except OperationError as exc:
                return exc
        # A cut 0.0005 mm larger in diameter than its tool takes 0.064 mm3 too much: rejected.
        pilots = pilot_cylinders(side=-1)
        over = check("Over", pilots, before.cut(pilot_cylinders(side=-1, radius=0.8505)))
        self.assertEqual((over.code, over.details["check"]), ("invalid_geometry", "volume"))
        shared = over.details["shared_point_volumes_mm3"]
        extra = 3 * math.pi * (0.8505 ** 2 - (PILOT_D / 2) ** 2) * PILOT_DEPTH
        self.assertAlmostEqual(shared["before"] - shared["after"] - shared["tool"], extra, delta=1e-7)
        # A real 0.002 mm deep cut whose own volumes say the part grew: neither invalid nor empty.
        shallow = pilot_cylinders(side=1, top=BOSS_TOP + PILOT_DEPTH - 0.002)
        report = check("Shallow", shallow, before.cut(shallow))
        self.assertIsInstance(report, dict, report)
        self.assertGreater(report["volume_delta_mm3"], 1e-6 * before.Volume,
                           "this fixture no longer shows a real cut measuring as growth")
        shared_before, _, shared_after = studio._shared_point_volumes([before, shallow, before.cut(shallow)])
        self.assertAlmostEqual(shared_before - shared_after, 3 * math.pi * (PILOT_D / 2) ** 2 * 0.002, delta=1e-8)
        # A tool that misses the part still removes nothing.
        air = pilot_cylinders(side=1, top=BOSS_TOP + PILOT_DEPTH + 0.1)
        empty = check("Air", air, before.cut(air))
        self.assertEqual((empty.code, empty.details["feature"]), ("empty_cut", "Op"))

    def test_shared_point_volumes_leave_exact_volumes_unchanged(self):
        block = Part.makeBox(20, 20, 10)
        tool = Part.makeCylinder(2, 30, App.Vector(10, 10, -10))
        cut = block.cut(tool)
        volumes = studio._shared_point_volumes([block, tool, cut])
        for measured, exact in zip(volumes, (4000, math.pi * 4 * 30, 4000 - math.pi * 40)):
            self.assertAlmostEqual(measured, exact, places=9)


if __name__ == "__main__":
    unittest.main()
