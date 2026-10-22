"""Last geometric face modifier through real public native/studio operations."""
from pathlib import Path
import json
import sys
import time
import unittest
from unittest.mock import patch

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
from kurtshape import selectors, studio
from kurtshape.core import Controller, intent_signature
from kurtshape.face_provenance import FaceProvenance, _equivalent


class FaceProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="face-provenance-session-")
        self.core = Controller()
        self.resolver = FaceProvenance(self.core)
        self.state = None

    def tearDown(self):
        self.resolver.clear()
        self.core.close()
        for name in set(App.listDocuments()) - self.names:
            App.closeDocument(name)

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def call(self, op, **args):
        request = {"op": op, **args}
        if op not in {"new", "open", "import_step"}:
            request.update(document_id=self.state["document_id"], expected_revision=self.state["revision"])
        response = self.core.dispatch(request)
        self.assertTrue(response["ok"], response)
        if "document_id" in response["result"]:
            self.state = response["result"]
        return response["result"]

    def block(self, studio_mode=True):
        self.call("new", name="FaceProvenance")
        self.call("sketch_rectangle", id="Profile", width=20, height=12)
        self.call("pad", id="Extrude", profile="Profile", length=8,
                  **({"operation": "new"} if studio_mode else {}))

    def part(self, identifier="Body"):
        return studio.current_part(self.doc, identifier)

    def face(self, predicate, part="Body"):
        obj = self.part(part)
        shape = selectors.world_shape(obj)
        choices = [i + 1 for i, face in enumerate(shape.Faces) if predicate(face)]
        self.assertEqual(len(choices), 1, (choices, [(face.Area, tuple(face.CenterOfMass)) for face in shape.Faces]))
        return obj.Name, "Face" + str(choices[0])

    def assert_owner(self, pick, expected):
        result = self.resolver.resolve(self.doc, *pick)
        self.assertEqual((result["status"], result["feature"]), ("resolved", expected), result)
        return result

    def pocket(self, x=6, name="HoleCut", diameter=4):
        self.call("create_plane", id=name + "Plane", base_plane="XY", offset=8)
        self.call("sketch_circle", id=name + "Profile", support={"feature": name + "Plane"}, x=x, y=6, diameter=diameter)
        self.call("pocket", id=name, profile=name + "Profile", length=3,
                  operation="remove", merge_scope=["Body"], reversed=True, through_all=False)

    def snapshot(self):
        meta = self.core._meta(self.doc)
        return (intent_signature(self.doc), meta.Revision, self.doc.UndoCount, self.doc.RedoCount,
                self.doc.UseHasher, tuple((obj.Name, tuple(obj.State)) for obj in self.doc.Objects))

    def test_public_pocket_distinguishes_trim_new_face_untouched_and_remote_cut(self):
        self.block()
        self.pocket()
        bottom = self.face(lambda face: abs(face.CenterOfMass.z) < 1e-6)
        top = self.face(lambda face: abs(face.CenterOfMass.z - 8) < 1e-6)
        wall = self.face(lambda face: isinstance(face.Surface, Part.Cylinder))
        self.assert_owner(bottom, "Extrude")
        self.assert_owner(top, "HoleCut")
        self.assert_owner(wall, "HoleCut")
        self.pocket(x=15, name="Remote", diameter=2)
        self.assert_owner(self.face(lambda face: isinstance(face.Surface, Part.Cylinder) and face.Surface.Radius > 1.5), "HoleCut")
        self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.z - 8) < 1e-6), "Remote")
        self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.z) < 1e-6), "Extrude")

    def test_legacy_native_pocket_and_public_fillet(self):
        self.block(studio_mode=False)
        self.call("sketch_circle", id="Bore", x=6, y=6, diameter=4)
        self.call("pocket", id="Pocket", profile="Bore", length=3, reversed=True, through_all=False)
        self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.z - 8) < 1e-6), "Extrude")
        self.assert_owner(self.face(lambda face: isinstance(face.Surface, Part.Cylinder)), "Pocket")
        tip = self.part().Tip
        edge = next("Edge" + str(i + 1) for i, edge in enumerate(tip.Shape.Edges)
                    if edge.BoundBox.XLength > 19 and abs(edge.CenterOfMass.z - 8) < 1e-6)
        self.call("fillet", id="Round", edges=[{"feature": tip.Name, "subelement": edge}], radius=1)
        self.assert_owner(self.face(lambda face: isinstance(face.Surface, Part.Cylinder) and abs(face.Surface.Radius - 1) < 1e-6), "Round")
        self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.z - 8) < 1e-6), "Round")

    def test_studio_fillet_preserves_untouched_faces_and_earlier_cylinder(self):
        self.block()
        self.pocket()
        tip = self.part().Tip
        edge = next("Edge" + str(i + 1) for i, edge in enumerate(tip.Shape.Edges)
                    if edge.BoundBox.XLength > 19 and abs(edge.CenterOfMass.z - 8) < 1e-6)
        self.call("fillet", id="Round", edges=[{"feature": tip.Name, "subelement": edge}], radius=1)
        self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.z - 8) < 1e-6), "Round")
        self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.z) < 1e-6), "Extrude")
        self.assert_owner(self.face(lambda face: isinstance(face.Surface, Part.Cylinder) and abs(face.Surface.Radius - 2) < 1e-6), "HoleCut")

    def test_native_hole_adapter_ignores_unparseable_nested_names(self):
        self.block()
        self.call("create_plane", id="Top", base_plane="XY", offset=8)
        self.call("sketch_circle", id="Centres", support={"feature": "Top"}, x=6, y=6, diameter=2)
        self.call("hole", id="Drill", part="Body", sketch="Centres", diameter=2, depth=3)
        self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.z - 8) < 1e-6), "Drill")
        self.assert_owner(self.face(lambda face: isinstance(face.Surface, Part.Cylinder)), "Drill")
        self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.z) < 1e-6), "Extrude")

    def test_read_only_cache_parameter_edit_undo_and_reopen(self):
        self.block()
        self.pocket()
        pick = self.face(lambda face: abs(face.CenterOfMass.z - 8) < 1e-6)
        before = self.snapshot()
        with patch.object(self.core, "_recompute", side_effect=AssertionError("Click must never recompute")), \
                patch.object(selectors, "recompute", side_effect=AssertionError("Click must never rebuild references")):
            self.assert_owner(pick, "HoleCut")
            self.assert_owner(pick, "HoleCut")
        self.assertEqual(self.snapshot(), before)
        self.call("set_parameter", feature="Extrude", parameter="Length", value=9)
        self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.z - 9) < 1e-6), "Extrude")
        self.call("undo")
        self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.z - 8) < 1e-6), "HoleCut")
        self.call("redo")
        self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.z - 9) < 1e-6), "Extrude")
        self.call("undo")
        order = [feature.Name for feature in studio.order(self.doc)]
        self.call("rollback", index=order.index("HoleCut"))
        self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.z - 8) < 1e-6), "Extrude")
        self.call("rollback", index=len(order))
        self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.z - 8) < 1e-6), "HoleCut")
        path = self.folder / "face-provenance-reopen.FCStd"
        self.call("save", path=str(path))
        self.call("close_document")
        self.call("open", path=str(path))
        self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.z - 8) < 1e-6), "HoleCut")

    def test_transform_copy_pattern_mirror_and_original(self):
        self.block()
        self.call("transform_part", id="Copy", part="Body", translation=[30, 0, 0], copy=True)
        self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.z - 8) < 1e-6, "CopyPart"), "Copy")
        self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.z - 8) < 1e-6), "Extrude")
        self.call("transform_part", id="Move", part="CopyPart", translation=[0, 30, 0])
        self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.z - 8) < 1e-6, "CopyPart"), "Move")
        self.call("transform_part", id="Noop", part="Body", translation=[0, 0, 0])
        self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.z - 8) < 1e-6), "Extrude")
        self.call("linear_pattern_parts", id="Pattern", parts=["Body"], direction=[0, 1, 0], spacing=30, count=2)
        generated = next(part for part in studio.current_parts(self.doc) if getattr(part, "KurtShapeOperationOwner", "") == "Pattern")
        self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.z - 8) < 1e-6, studio.part_id(generated)), "Pattern")
        self.call("mirror_parts", id="Mirror", parts=["Body"], origin=[-5, 0, 0], normal=[1, 0, 0])
        generated = next(part for part in studio.current_parts(self.doc) if getattr(part, "KurtShapeOperationOwner", "") == "Mirror")
        self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.z - 8) < 1e-6, studio.part_id(generated)), "Mirror")

    def test_import_anchor_and_invalid_pick_are_honest(self):
        shape = Part.makeBox(20, 12, 8)
        path = self.folder / "face-provenance-import.step"
        shape.exportStep(str(path))
        self.call("import_step", path=str(path))
        answer = self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.z - 8) < 1e-6), "ImportedSolid")
        self.assertTrue(answer["earlier_history_unavailable"])
        self.assertEqual(self.resolver.resolve(self.doc, "Body", "Edge1")["status"], "unavailable")
        self.assertEqual(self.resolver.resolve(self.doc, "Body", "Face999")["status"], "unavailable")

    def test_complete_boundary_equivalence_rejects_equal_area_different_holes(self):
        outer = Part.makePolygon([App.Vector(0, 0, 0), App.Vector(10, 0, 0), App.Vector(10, 10, 0), App.Vector(0, 10, 0), App.Vector(0, 0, 0)])
        flat = Part.Face(outer)
        first = flat.cut(Part.Face(Part.Wire([Part.makeCircle(1, App.Vector(3, 5, 0))]))).Faces[0]
        second = flat.cut(Part.Face(Part.Wire([Part.makeCircle(1, App.Vector(7, 5, 0))]))).Faces[0]
        self.assertAlmostEqual(first.Area, second.Area)
        self.assertFalse(_equivalent(first, second))
        self.assertTrue(_equivalent(first, first.copy()))

    def test_periodic_seam_reparameterization_does_not_change_physical_face(self):
        first = next(face for face in Part.makeCylinder(3, 8).Faces if isinstance(face.Surface, Part.Cylinder))
        second = first.copy()
        second.rotate(App.Vector(), App.Vector(0, 0, 1), 37)
        self.assertFalse(first.isEqual(second))
        self.assertTrue(_equivalent(first, second))
        # Moving the physical rim still changes the bounded surface.
        shorter = next(face for face in Part.makeCylinder(3, 7).Faces if isinstance(face.Surface, Part.Cylinder))
        self.assertFalse(_equivalent(first, shorter))

    def test_boolean_merge_and_split_use_each_operations_actual_input_parts(self):
        self.block()
        self.call("create_body", id="Second")
        self.call("sketch_rectangle", id="SecondProfile", body="Second", x=20, width=20, height=12)
        self.call("pad", id="SecondExtrude", profile="SecondProfile", body="Second", length=8, operation="new")
        self.call("boolean_parts", id="Merge", targets=["Body"], tools=["Second"], kind="union")
        self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.z - 8) < 1e-6), "Merge")
        self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.x) < 1e-6), "Extrude")
        self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.x - 40) < 1e-6), "SecondExtrude")
        self.call("split_part", id="Split", part="Body", plane={"origin": [10, 0, 0], "normal": [1, 0, 0]})
        self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.z - 8) < 1e-6), "Split")
        self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.x) < 1e-6), "Extrude")

    def test_pattern_add_keeps_original_untouched_face_owner(self):
        self.block()
        self.call("linear_pattern_parts", id="AddedPattern", parts=["Body"], direction=[1, 0, 0],
                  spacing=20, count=2, operation="add", merge_scope=["Body"])
        self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.z - 8) < 1e-6), "AddedPattern")
        self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.x) < 1e-6), "Extrude")

    def test_include_source_pattern_keeps_each_unchanged_source_face(self):
        self.block()
        self.call("create_body", id="Second")
        self.call("sketch_rectangle", id="SecondProfile", body="Second", x=20, width=20, height=12)
        self.call("pad", id="SecondExtrude", profile="SecondProfile", body="Second", length=8, operation="new")
        self.call("linear_pattern_parts", id="CombinedPattern", parts=["Body"], direction=[1, 0, 0],
                  spacing=20, count=2, operation="add", include_source=True, merge_scope=["Second"])
        self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.z - 8) < 1e-6, "Second"), "CombinedPattern")
        self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.x) < 1e-6, "Second"), "Extrude")
        self.assert_owner(self.face(lambda face: abs(face.CenterOfMass.x - 40) < 1e-6, "Second"), "SecondExtrude")

    def test_unevaluated_edit_and_corrupt_metadata_fail_unavailable_read_only(self):
        self.block()
        pick = self.face(lambda face: abs(face.CenterOfMass.z - 8) < 1e-6)
        self.assert_owner(pick, "Extrude")
        self.doc.Extrude.LengthFwd = 9
        before = self.snapshot()
        result = self.resolver.resolve(self.doc, *pick)
        self.assertEqual(result["status"], "unavailable", result)
        self.assertEqual(self.snapshot(), before)
        self.call("inspect")
        self.call("rebuild")
        self.assert_owner(self.face(lambda face: face.normalAt(0, 0).z > .9), "Extrude")
        self.doc.Extrude.KurtShapeStudioOperation = "{invalid JSON"
        result = self.resolver.resolve(self.doc, *pick)
        self.assertEqual(result["status"], "unavailable", result)

    def test_coincident_actual_predecessors_return_ambiguous_without_guessing(self):
        self.block()
        self.call("create_body", id="Second")
        self.call("sketch_rectangle", id="SecondProfile", body="Second", width=20, height=12)
        self.call("pad", id="SecondExtrude", profile="SecondProfile", body="Second", length=8, operation="new")
        self.call("boolean_parts", id="Merge", targets=["Body"], tools=["Second"], kind="union")
        result = self.resolver.resolve(self.doc, *self.face(lambda face: abs(face.CenterOfMass.z - 8) < 1e-6))
        self.assertEqual(result["status"], "ambiguous", result)
        self.assertEqual(set(result["candidates"]), {"Extrude", "SecondExtrude"})
        self.assertIsNone(result["feature"])

    def test_failed_full_equivalence_proof_is_unavailable(self):
        self.block()
        self.pocket()
        pick = self.face(lambda face: abs(face.CenterOfMass.z) < 1e-6)
        with patch("kurtshape.face_provenance._equivalent", return_value=None):
            result = self.resolver.resolve(self.doc, *pick)
        self.assertEqual(result["status"], "unavailable", result)
        self.assertIsNone(result["feature"])

    def test_bounded_long_history_cold_and_cached_click_measurement(self):
        self.block()
        self.call("create_plane", id="Top", base_plane="XY", offset=8)
        for index in range(12):
            name = "Cut" + str(index)
            self.call("sketch_circle", id=name + "Profile", support={"feature": "Top"},
                      x=2 + index % 6 * 3, y=3 + index // 6 * 6, diameter=1)
            self.call("pocket", id=name, profile=name + "Profile", length=2,
                      operation="remove", merge_scope=["Body"], reversed=True, through_all=False)
        pick = self.face(lambda face: abs(face.CenterOfMass.x) < 1e-6)
        self.resolver.clear()
        before = self.snapshot()
        started = time.perf_counter()
        self.assert_owner(pick, "Extrude")
        cold_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        for _ in range(20):
            self.assert_owner(pick, "Extrude")
        warm_ms = (time.perf_counter() - started) * 1000 / 20
        self.assertEqual(self.snapshot(), before)
        measurement = {"history_features": len(studio.order(self.doc)), "solid_operations": 13,
                       "result_faces": len(self.part().Shape.Faces), "cold_ms": cold_ms,
                       "cached_mean_ms": warm_ms, "fixture": self.id()}
        print("FACE_PROVENANCE_PERFORMANCE " + json.dumps(measurement), flush=True)
        (support.evidence_dir("face-feature-selection") / "resolver-performance.json").write_text(
            json.dumps(measurement, indent=2), encoding="utf-8")
