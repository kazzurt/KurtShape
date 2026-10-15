"""Associative pattern references and cross-body Mirror planes in a Part Studio."""
from pathlib import Path
import math
import subprocess
import shutil
import sys
import unittest

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
from kurtshape.core import Controller, intent_signature
from kurtshape import studio

SAVED_EXAMPLE = ROOT.parent / "test-261014.FCStd"
SCOPE_WARNING = "go out of the allowed scope"


def reopen_output(path):
    """Fresh native process: open, touch everything, recompute; return console text."""
    script = ("import FreeCAD as A\n"
              "[A.Console.SetStatus('Console', k, True) for k in ('Err', 'Wrn', 'Msg')]\n"
              "d = A.openDocument(" + repr(str(path)) + ")\n"
              "[o.touch() for o in d.Objects]\n"
              "d.recompute()\n"
              "print('REOPENED', len([o for o in d.Objects if 'Invalid' in o.State]))\n")
    process = support.run_native_proof([sys.executable, "-B", "-c", script], capture_output=True, text=True,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=120)
    return process.returncode, process.stdout + process.stderr


class PatternMirrorReferenceTests(unittest.TestCase):
    def setUp(self):
        self.initial = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="pattern-mirror-")
        self.core = Controller()
        self.state = self.core.dispatch({"op": "new", "name": "Pattern references"})["result"]

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

    def reject(self, op, code, **kwargs):
        before = intent_signature(self.doc), self.doc.UndoCount, self.core.inspect(self.doc)["revision"]
        response = self.request(op, **kwargs)
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], code, response)
        self.assertTrue(response["error"]["message"])
        self.assertEqual((intent_signature(self.doc), self.doc.UndoCount,
                          self.core.inspect(self.doc)["revision"]), before)
        return response

    def part(self, name, x=0, y=0, width=4, height=3, depth=2):
        if name != "Body":
            self.call("create_body", id=name, name=name)
        self.call("sketch_rectangle", id=name + "Profile", body=name, x=x, y=y, width=width, height=height)
        self.call("pad", id=name + "Extrude", profile=name + "Profile", body=name, length=depth, operation="new")
        return studio.current_part(self.doc, name)

    def hub(self, x=20, y=0, diameter=6):
        self.call("create_body", id="Hub", name="Hub")
        self.call("sketch_circle", id="HubProfile", body="Hub", x=x, y=y, diameter=diameter)
        self.call("pad", id="HubExtrude", profile="HubProfile", body="Hub", length=2, operation="new")
        return studio.current_part(self.doc, "Hub")

    def edge(self, body, test):
        tip = body.Tip
        index = next(i for i, edge in enumerate(tip.Shape.Edges) if test(edge))
        return {"feature": tip.Name, "subelement": "Edge%d" % (index + 1)}

    def face(self, body, test):
        tip = body.Tip
        index = next(i for i, face in enumerate(tip.Shape.Faces) if test(face))
        return {"feature": tip.Name, "subelement": "Face%d" % (index + 1)}

    def outputs(self, operation):
        return [self.doc.getObject(name) for name in self.doc.getObject(operation).KurtShapeOutputParts]

    def boxes(self, operation):
        return [body.Shape.BoundBox for body in self.outputs(operation)]

    def x_edge(self, body, length):
        return self.edge(body, lambda e: isinstance(e.Curve, Part.Line) and abs(e.Length - length) < 1e-6
                         and abs(e.Curve.Direction.y) < 1e-9 and abs(e.Curve.Direction.z) < 1e-9)

    def circle_edge(self, body):
        return self.edge(body, lambda e: isinstance(e.Curve, Part.Circle) and e.BoundBox.ZMax < 1e-6)

    def move(self, body, placement):
        """Place a part's own Body (its sketch owner), as a user moves a part."""
        body.Placement = placement
        self.doc.recompute()
        self.state = self.core.inspect(self.doc)

    def free_move(self, sketch, geometry, point, position):
        """Upstream sketch edit: release positional constraints, move a point."""
        for index in reversed(range(sketch.ConstraintCount)):
            constraint = sketch.Constraints[index]
            if constraint.First == geometry and constraint.Type not in {"Diameter", "Radius"}:
                sketch.delConstraint(index)
        sketch.solve()
        sketch.moveGeometry(geometry, point, position, False)
        sketch.recompute()
        assert (sketch.getPoint(geometry, point) - position).Length < 1e-7, 'fixture edit did not move the sketch'

    def driver_axis(self, name):
        driver = self.doc.getObject(name)
        return driver.Placement.Base, driver.Placement.Rotation.multVec(App.Vector(0, 0, 1))

    def world_edge(self, body, element):
        from kurtshape.assembly import global_shape
        return global_shape(body.Tip).getElement(element)

    def assert_collinear(self, name, edge):
        base, direction = self.driver_axis(name)
        self.assertLess(direction.cross(edge.Curve.Direction).Length, 1e-7)
        self.assertLess(edge.Curve.toShape().distToShape(Part.Vertex(base))[0], 1e-6)

    def assert_translated(self, actual, source, vector):
        moved = source.copy()
        moved.translate(vector)
        self.assert_box(actual, moved.BoundBox)

    def expected_rotation(self, center, axis, degrees, shape):
        result = shape.copy()
        result.rotate(center, axis, degrees)
        return result.BoundBox

    def assert_box(self, actual, expected):
        for key in ("XMin", "XMax", "YMin", "YMax", "ZMin", "ZMax"):
            self.assertAlmostEqual(getattr(actual, key), getattr(expected, key), places=5, msg=key)

    # Linear patterns ---------------------------------------------------------

    def test_linear_pattern_follows_edge_on_rotated_other_body(self):
        body = self.part("Body")
        rail = self.part("Rail", x=30, y=10, width=20, height=2, depth=1)
        source = body.Shape.copy()
        reference = self.x_edge(rail, 20)
        before = intent_signature(self.doc), self.doc.UndoCount
        preview = self.request("preview", proposal={"op": "linear_pattern_parts", "parts": ["Body"],
                                                    "direction": reference, "spacing": 10, "count": 3})
        self.assertTrue(preview["ok"] and preview["result"]["valid"], preview)
        self.assertEqual((intent_signature(self.doc), self.doc.UndoCount), before)
        self.call("linear_pattern_parts", id="Linear", parts=["Body"], direction=reference, spacing=10, count=3)
        self.assertEqual(self.doc.UndoCount, before[1] + 1)
        self.assertEqual(len(self.boxes("Linear")), 2)
        driver = self.doc.LinearDirection
        self.assertEqual(driver.TypeId, "Part::Line")
        self.assertEqual(driver.KurtShapeReferenceDatum.AttachmentSupport[0][0].Name, reference["feature"])
        self.assertEqual(driver.KurtShapeOperationOwner, "Linear")
        self.assert_collinear("LinearDirection", self.world_edge(rail, reference["subelement"]))
        _, direction = self.driver_axis("LinearDirection")
        self.assertLess(direction.cross(App.Vector(1, 0, 0)).Length, 1e-7)
        offsets = sorted(round((box.XMin - source.BoundBox.XMin) * direction.x, 6) for box in self.boxes("Linear"))
        self.assertEqual(offsets, [10, 20])
        # Rotating the referenced part's Body turns the pattern direction with it.
        self.move(self.doc.Rail, App.Placement(App.Vector(), App.Rotation(App.Vector(0, 0, 1), 90)))
        self.assert_collinear("LinearDirection", self.world_edge(rail, reference["subelement"]))
        _, turned = self.driver_axis("LinearDirection")
        self.assertLess(turned.cross(App.Vector(0, 1, 0)).Length, 1e-7)
        for box in self.boxes("Linear"):
            self.assertAlmostEqual(box.XMin, source.BoundBox.XMin, places=6)
        self.assertEqual(sorted(round(abs(box.YMin - source.BoundBox.YMin), 6) for box in self.boxes("Linear")), [10, 20])
        self.call("undo")
        self.assertIsNone(self.doc.getObject("Linear"))
        self.assertIsNone(self.doc.getObject("LinearDirection"))
        self.call("redo")
        self.assertEqual(sorted(round(abs(box.YMin - source.BoundBox.YMin), 6) for box in self.boxes("Linear")), [10, 20])

    def test_linear_pattern_reverse_and_sketch_line_upstream_edit(self):
        body = self.part("Body")
        source = body.Shape.copy()
        self.call("create_sketch", id="Guide", plane="XY")
        self.call("add_line", sketch="Guide", x1=0, y1=-10, x2=10, y2=-10)
        guide = {"feature": "Guide", "subelement": "Edge1"}
        self.call("linear_pattern_parts", id="Forward", parts=["Body"], direction=guide, spacing=10, count=2)
        self.call("linear_pattern_parts", id="Back", parts=["Body"], direction=guide, spacing=10, count=2, reversed=True)
        _, direction = self.driver_axis("ForwardDirection")
        self.assert_translated(self.boxes("Forward")[0], source, direction * 10)
        self.assert_translated(self.boxes("Back")[0], source, direction * -10)
        # Upstream edit: turn the guide line toward +Y; both patterns follow.
        self.doc.openTransaction("Edit guide line")
        self.free_move(self.doc.Guide, 0, 2, App.Vector(0, 0, 0))
        self.doc.recompute()
        self.doc.commitTransaction()
        self.state = self.core.inspect(self.doc)
        _, direction = self.driver_axis("ForwardDirection")
        self.assertLess(direction.cross(App.Vector(0, 1, 0)).Length, 1e-7)
        self.assert_translated(self.boxes("Forward")[0], source, direction * 10)
        self.assert_translated(self.boxes("Back")[0], source, direction * -10)

    def test_manual_patterns_still_work_and_reverse(self):
        self.part("Body")
        self.call("linear_pattern_parts", id="Linear", parts=["Body"], direction=[1, 0, 0], spacing=10, count=2,
                  reversed=True)
        self.assertAlmostEqual(self.boxes("Linear")[0].XMin, -10)
        self.call("circular_pattern_parts", id="Circular", parts=["Body"],
                  axis={"origin": [0, 0, 0], "direction": [0, 0, 1]}, angle="90 deg", count=2)
        box = self.boxes("Circular")[0]
        for actual, expected in zip((box.XMin, box.XMax, box.YMin, box.YMax), (-3, 0, 0, 4)):
            self.assertAlmostEqual(actual, expected, places=6)
        self.assertFalse(any(obj.Name.startswith(("LinearDirection", "CircularAxis")) for obj in self.doc.Objects))

    # Circular patterns -------------------------------------------------------

    def test_circular_pattern_circle_axis_follows_position_and_orientation(self):
        body = self.part("Body")
        hub = self.hub(x=20)
        source = body.Shape.copy()
        self.call("circular_pattern_parts", id="Circular", parts=["Body"], axis=self.circle_edge(hub),
                  angle="90 deg", count=2)

        def check(center, normal):
            base, direction = self.driver_axis("CircularAxis")
            self.assertLess(direction.cross(normal).Length, 1e-7)
            self.assertLess((base - center).Length, 1e-6)
            self.assert_box(self.boxes("Circular")[0], self.expected_rotation(base, direction, 90, source))
        check(App.Vector(20, 0, 0), App.Vector(0, 0, 1))
        # Translate the referenced part's Body: the axis position follows.
        self.move(self.doc.Hub, App.Placement(App.Vector(5, 0, 0), App.Rotation()))
        check(App.Vector(25, 0, 0), App.Vector(0, 0, 1))
        # Rotate it: the axis orientation follows too.
        turn = App.Placement(App.Vector(5, 0, 0), App.Rotation(App.Vector(1, 0, 0), 90))
        self.move(self.doc.Hub, turn)
        check(turn.multVec(App.Vector(20, 0, 0)), turn.Rotation.multVec(App.Vector(0, 0, 1)))
        # An upstream edit of the referenced circle moves the axis.
        self.move(self.doc.Hub, App.Placement())
        self.doc.openTransaction("Move hub circle")
        self.free_move(self.doc.HubProfile, 0, 3, App.Vector(12, 4, 0))
        self.doc.recompute()
        self.doc.commitTransaction()
        self.state = self.core.inspect(self.doc)
        check(App.Vector(12, 4, 0), App.Vector(0, 0, 1))

    def test_circular_pattern_straight_edge_axis_reversed_and_persisted(self):
        body = self.part("Body")
        rail = self.part("Rail", x=30, y=10, width=20, height=2, depth=1)
        source = body.Shape.copy()
        reference = self.edge(rail, lambda e: isinstance(e.Curve, Part.Line) and abs(e.Length - 2) < 1e-6
                              and abs(e.Curve.Direction.y) > .99 and e.BoundBox.ZMax < 1e-6 and e.BoundBox.XMin < 31)
        self.call("circular_pattern_parts", id="Forward", parts=["Body"], axis=reference, angle="90 deg", count=2)
        self.call("circular_pattern_parts", id="Back", parts=["Body"], axis=reference, angle="90 deg", count=2,
                  reversed=True)
        self.assert_collinear("ForwardAxis", self.world_edge(rail, reference["subelement"]))
        base, direction = self.driver_axis("ForwardAxis")
        self.assert_box(self.boxes("Forward")[0], self.expected_rotation(base, direction, 90, source))
        self.assert_box(self.boxes("Back")[0], self.expected_rotation(base, direction, -90, source))
        path = support.scratch(self, prefix="pattern-reference-save-") / "pattern-references.FCStd"
        self.call("save", path=str(path))
        expected = self.boxes("Back")[0]
        App.closeDocument(self.doc.Name)
        response = self.core.dispatch({"op": "open", "path": str(path)})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        self.assert_box(self.boxes("Back")[0], expected)
        self.move(self.doc.Rail, App.Placement(App.Vector(0, 0, 5), App.Rotation()))
        base, direction = self.driver_axis("BackAxis")
        self.assertAlmostEqual(base.z, 5, places=6)
        self.assert_box(self.boxes("Back")[0], self.expected_rotation(base, direction, -90, source))
        code, output = reopen_output(path)
        self.assertEqual(code, 0, output)
        self.assertIn("REOPENED 0", output)
        self.assertNotIn(SCOPE_WARNING, output)

    def test_pattern_reference_on_same_patterned_body(self):
        body = self.part("Body", width=4, height=3)
        source = body.Shape.copy()
        reference = self.x_edge(body, 4)
        self.call("linear_pattern_parts", id="Linear", parts=["Body"], direction=reference, spacing=6, count=2)
        _, direction = self.driver_axis("LinearDirection")
        self.assertLess(direction.cross(App.Vector(1, 0, 0)).Length, 1e-7)
        self.assert_translated(self.boxes("Linear")[0], source, direction * 6)

    def test_invalid_pattern_references_explain_and_change_nothing(self):
        self.part("Body")
        hub = self.hub()
        rail = self.part("Rail", x=30, y=10, width=20, height=2, depth=1)
        self.reject("linear_pattern_parts", "unsupported_reference", parts=["Body"], spacing=5, count=2,
                    direction=self.circle_edge(hub))
        self.reject("linear_pattern_parts", "unsupported_reference", parts=["Body"], spacing=5, count=2,
                    direction=self.face(rail, lambda f: True))
        self.reject("circular_pattern_parts", "missing_reference", parts=["Body"], count=2,
                    axis={"feature": rail.Tip.Name, "subelement": "Edge999"})
        self.reject("circular_pattern_parts", "missing_reference", parts=["Body"], count=2,
                    axis={"feature": "NoSuchFeature", "subelement": "Edge1"})
        cylinder = self.edge(hub, lambda e: isinstance(e.Curve, Part.Line))  # seam is straight: allowed
        self.assertTrue(self.request("preview", proposal={"op": "circular_pattern_parts", "parts": ["Body"],
                                                          "axis": cylinder, "count": 2})["ok"])
        # Future geometry is not an active reference.
        future = self.x_edge(rail, 20)
        index = [obj.Name for obj in studio.order(self.doc)].index("RailExtrude")
        self.call("rollback", index=index)
        self.reject("linear_pattern_parts", "missing_reference", parts=["Body"], spacing=5, count=2, direction=future)

    # Mirror ------------------------------------------------------------------

    def test_mirror_about_other_body_face_is_associative_without_scope_warning(self):
        body = self.part("Body")
        rail = self.part("Rail", x=30, y=10, width=20, height=2, depth=1)
        plane = self.face(rail, lambda f: isinstance(f.Surface, Part.Plane) and abs(f.normalAt(0, 0).x + 1) < 1e-9)
        before = intent_signature(self.doc), self.doc.UndoCount
        preview = self.request("preview", proposal={"op": "mirror_parts", "parts": ["Body"], "plane": plane})
        self.assertTrue(preview["ok"], preview)
        preview = preview["result"]
        self.assertTrue(preview["valid"], preview)
        self.assertEqual((intent_signature(self.doc), self.doc.UndoCount), before)
        self.call("mirror_parts", id="Mirror", parts=["Body"], plane=plane)
        self.assertEqual(self.doc.UndoCount, before[1] + 1)
        mirrored = self.outputs("Mirror")[0]
        self.assertAlmostEqual(mirrored.Shape.Volume, preview["measurements"]["volume_mm3"] - body.Shape.Volume - rail.Shape.Volume, places=6)
        self.assertAlmostEqual(mirrored.Shape.BoundBox.XMin, 56)
        driver = self.doc.Mirror.MirrorPlane[0]
        self.assertIsNone(driver.getParentGeoFeatureGroup())
        self.assertIn("Plane", driver.Name)
        self.assertEqual(driver.KurtShapeReferenceDatum.AttachmentSupport[0][0], rail.Tip)
        # Live plane: moving the referenced Body moves the mirror.
        self.move(self.doc.Rail, App.Placement(App.Vector(5, 0, 0), App.Rotation()))
        self.assertAlmostEqual(mirrored.Shape.BoundBox.XMin, 66)
        # Live source: an upstream edit of the mirrored part updates it.
        self.call("set_parameter", feature="BodyProfile", parameter="Width", value=6)
        self.assertAlmostEqual(mirrored.Shape.BoundBox.XMin, 64)
        self.call("undo")
        self.assertAlmostEqual(mirrored.Shape.BoundBox.XMin, 66)
        path = support.scratch(self, prefix="mirror-face-save-") / "mirror-face.FCStd"
        self.call("save", path=str(path))
        code, output = reopen_output(path)
        self.assertEqual(code, 0, output)
        self.assertIn("REOPENED 0", output)
        self.assertNotIn(SCOPE_WARNING, output)

    def test_mirror_rejects_nonplanar_and_broken_faces(self):
        self.part("Body")
        hub = self.hub()
        side = self.face(hub, lambda f: not isinstance(f.Surface, Part.Plane))
        self.reject("mirror_parts", "nonplanar_support", parts=["Body"], plane=side)
        self.reject("mirror_parts", "missing_reference", parts=["Body"], plane={"feature": hub.Tip.Name, "subelement": "Face99"})

    def legacy_direct_mirror(self):
        """A saved studio Mirror whose MirrorPlane links straight into a Body."""
        self.part("Body")
        rail = self.part("Rail", x=30, y=10, width=20, height=2, depth=1)
        plane = self.face(rail, lambda f: isinstance(f.Surface, Part.Plane) and abs(f.normalAt(0, 0).x + 1) < 1e-9)
        self.call("mirror_parts", id="Mirror", parts=["Body"], plane=plane)
        driver = self.doc.Mirror.MirrorPlane[0]
        datum = driver.KurtShapeReferenceDatum
        self.doc.openTransaction("Legacy direct mirror fixture")
        self.doc.Mirror.MirrorPlane = (rail.Tip, [plane["subelement"]])
        self.doc.removeObject(driver.Name)
        self.doc.removeObject(datum.Name)
        self.doc.commitTransaction()
        self.doc.recompute()
        path = support.scratch(self, prefix="legacy-mirror-") / "legacy-mirror.FCStd"
        self.doc.saveAs(str(path))
        code, output = reopen_output(path)
        self.assertIn(SCOPE_WARNING, output, "fixture must reproduce the legacy warning")
        return path

    def test_saved_direct_mirror_migrates_without_changing_geometry_or_identity(self):
        path = self.legacy_direct_mirror()
        expected = self.outputs("Mirror")[0].Shape.copy()
        downstream = self.doc.Mirror.KurtShapeOutputParts
        App.closeDocument(self.doc.Name)
        response = self.core.dispatch({"op": "open", "path": str(path)})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        mirror = self.doc.Mirror
        driver = mirror.MirrorPlane[0]
        self.assertEqual(driver.TypeId, "PartDesign::Plane")
        self.assertIsNone(driver.getParentGeoFeatureGroup())
        self.assertEqual(mirror.KurtShapeOutputParts, downstream)
        self.assertEqual(self.doc.UndoCount, 0)
        mirrored = self.outputs("Mirror")[0]
        self.assertAlmostEqual(mirrored.Shape.Volume, expected.Volume, places=6)
        self.assertLess(mirrored.Shape.BoundBox.XMin - expected.BoundBox.XMin, 1e-7)
        self.assertEqual(self.state["build_status"], "valid")
        self.move(self.doc.Rail, App.Placement(App.Vector(5, 0, 0), App.Rotation()))
        self.assertAlmostEqual(mirrored.Shape.BoundBox.XMin, 66)
        migrated = path.with_name("migrated-mirror.FCStd")
        self.call("save", path=str(migrated))
        code, output = reopen_output(migrated)
        self.assertEqual(code, 0, output)
        self.assertNotIn(SCOPE_WARNING, output)

    def test_saved_example_mirror_migrates_and_follows_shell_face(self):
        if not SAVED_EXAMPLE.is_file():
            self.skipTest(support.EXTERNAL_SKIP_PREFIX + " missing " + SAVED_EXAMPLE.name)
        copy = support.scratch(self, prefix="saved-example-mirror-") / "example-copy.FCStd"
        shutil.copyfile(SAVED_EXAMPLE, copy)
        code, output = reopen_output(copy)
        self.assertIn(SCOPE_WARNING, output, "the saved example reproduces the reported warning")
        response = self.core.dispatch({"op": "open", "path": str(copy)})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        mirror = self.doc.Mirror
        self.assertEqual(mirror.Source.Name, "MirrorInput")
        driver = mirror.MirrorPlane[0]
        self.assertEqual(driver.KurtShapeReferenceDatum.AttachmentSupport, [(self.doc.Shell, ("Face11",))])
        self.assertAlmostEqual(mirror.Shape.Volume, 1373.672113, places=5)
        self.assertEqual(self.state["build_status"], "valid")
        # Expected mirror: the source part reflected about Shell.Face11 in world space.
        face = self.doc.Shell.Shape.getElement("Face11").copy()
        face.Placement = self.doc.Body.Placement * face.Placement
        normal = face.normalAt(0, 0)
        source = mirror.Source.Shape.copy()
        expected = source.mirror(face.CenterOfMass, normal).BoundBox
        self.assert_box(mirror.Shape.BoundBox, expected)
        self.move(self.doc.Body, App.Placement(App.Vector(0, 7, 0), App.Rotation()))
        face = self.doc.Shell.Shape.getElement("Face11").copy()
        face.Placement = self.doc.Body.Placement * face.Placement
        expected = mirror.Source.Shape.copy().mirror(face.CenterOfMass, face.normalAt(0, 0)).BoundBox
        self.assert_box(mirror.Shape.BoundBox, expected)
        migrated = copy.with_name("example-migrated.FCStd")
        self.move(self.doc.Body, App.Placement())
        self.call("save", path=str(migrated))
        code, output = reopen_output(migrated)
        self.assertEqual(code, 0, output)
        self.assertNotIn(SCOPE_WARNING, output)


if __name__ == "__main__":
    unittest.main()
