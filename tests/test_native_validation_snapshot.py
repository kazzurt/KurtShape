"""Intrinsic datum content and native placement validation consequences."""
from datetime import datetime, timezone
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import sys
import traceback
import unittest

import support
import FreeCAD as App
import Part
from kurtshape.core import Controller
from kurtshape.assembly import canonical_brep
from native_validation_snapshot import INTRINSIC_TYPES, snapshot_document


SOURCE_FILES = ("tools/native_validation_snapshot.py", "tests/test_native_validation_snapshot.py",
                "tests/support.py", "tools/perf/bench_core.py", "tools/perf/report.py",
                "tools/perf/budgets.json", "src/kurtshape/core.py", "src/kurtshape/assembly.py")


def source_hashes():
    return {name: hashlib.sha256((support.ROOT / name).read_bytes()).hexdigest() for name in SOURCE_FILES}


class NativeValidationSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.report = {"schema_version": 1, "passed": False, "pid": os.getpid(), "test_id": self.id(),
                       "started_utc": datetime.now(timezone.utc).isoformat(), "snapshots": {},
                       "consequences": {}, "limits": "Validation-only native consequence proof; "
                       "not a timing benchmark. GUI state is unavailable unless actually GuiUp."}
        evidence = Path(os.environ["KURTSHAPE_EVIDENCE_DIR"])
        if not evidence.is_absolute():
            raise RuntimeError("Native snapshot proof requires absolute suite evidence")
        self.evidence = support._native_fixture_path(evidence, support.TEST_TMP)
        self.output_directory = support._native_fixture_path(self.evidence / "native-validation-snapshot", self.evidence)
        self.output = support._native_fixture_path(self.output_directory / (self._testMethodName + ".json"),
                                                   self.output_directory)
        self.report["source_before"] = source_hashes()
        self.addCleanup(self.write_report)
        self.folder = support.isolated_session(self, prefix="native-validation-snapshot-")
        receipt_directory = support._native_fixture_path(self.evidence / "native-fixtures", self.evidence)
        receipt = support._native_fixture_path(receipt_directory / (self.folder.name + ".json"), receipt_directory)
        receipt_bytes = receipt.read_bytes()
        receipt_data = json.loads(receipt_bytes)
        self.assertEqual(receipt_data["test_id"], self.id())
        self.assertEqual(receipt_data["pid"], os.getpid())
        self.assertEqual(Path(receipt_data["fixture"]).resolve(), self.folder.resolve())
        self.report["fixture_receipt"] = {"path": str(receipt), "sha256": hashlib.sha256(receipt_bytes).hexdigest(),
                                          "fixture": str(self.folder), "pid": os.getpid(), "test_id": self.id()}
        self.core = Controller()
        answer = self.core.dispatch({"op": "new", "name": "Native validation snapshot"})
        self.assertTrue(answer["ok"], answer)
        self.state = answer["result"]

    def tearDown(self):
        try:
            self.core.close()
            for name in set(App.listDocuments()) - self.names:
                App.closeDocument(name)
        except Exception:
            self.report["passed"] = False
            self.report["cleanup_error"] = traceback.format_exc()
            raise

    def write_report(self):
        result = self._outcome.result
        failures = list(getattr(result, "failures", ())) + list(getattr(result, "errors", ()))
        if any(test is self or getattr(test, "test_case", None) is self for test, _ in failures):
            self.report["passed"] = False
        self.report["source_after"] = source_hashes()
        self.report["source_unchanged"] = self.report["source_before"] == self.report["source_after"]
        if not self.report["source_unchanged"]:
            self.report["passed"] = False
        self.report["checks"] = dict(self.report["consequences"])
        self.report["completed_utc"] = datetime.now(timezone.utc).isoformat()
        evidence = support._native_fixture_path(self.evidence, support.TEST_TMP)
        directory = support._native_fixture_path(self.output_directory, evidence)
        output = support._native_fixture_path(self.output, directory)
        stage = support._native_fixture_path(output.with_suffix(".saving"), directory)
        if output.exists() or stage.exists():
            raise FileExistsError("Preserve the earlier native snapshot proof: " + str(output))
        directory.mkdir(parents=True, exist_ok=True)
        output = support._native_fixture_path(output, directory)
        stage = support._native_fixture_path(stage, directory)
        with stage.open("x", encoding="utf-8") as stream:
            json.dump(self.report, stream, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(stage, output)

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def call(self, op, **arguments):
        answer = self.core.dispatch({"op": op, "document_id": self.state["document_id"],
                                    "expected_revision": self.state["revision"], **arguments})
        self.assertTrue(answer["ok"], answer)
        self.state = answer["result"]

    @staticmethod
    def row(snapshot, name):
        return next(obj for obj in snapshot["strict"]["objects"] if obj["name"] == name)

    def plate(self):
        self.call("sketch_rectangle", id="Profile", width=20, height=10)
        self.call("pad", profile="Profile", length=6)

    def test_owned_intrinsic_point_content_and_model_hashes_survive_reads_and_warm_inspection(self):
        foreign = App.newDocument("UnregisteredSnapshotRejection")
        foreign.UseHasher = False
        foreign.UndoMode = 1
        feature = foreign.addObject("Part::Feature", "ForeignSolid")
        feature.Shape = Part.makeBox(2, 3, 4)
        foreign.recompute()

        def foreign_state():
            shape = feature.Shape
            return {"objects": [(obj.Name, obj.TypeId, list(obj.PropertiesList)) for obj in foreign.Objects],
                    "label": foreign.Label, "filename": foreign.FileName,
                    "undo_mode": foreign.UndoMode, "use_hasher": foreign.UseHasher,
                    "undo_count": foreign.UndoCount, "redo_count": foreign.RedoCount,
                    "undo_names": list(foreign.UndoNames), "redo_names": list(foreign.RedoNames),
                    "pending_transaction": foreign.HasPendingTransaction,
                    "feature_label": feature.Label, "feature_state": list(feature.State),
                    "feature_status": feature.getStatusString(), "shape_null": shape.isNull(),
                    "shape_hash": shape.hashCode(), "shape_brep": shape.exportBrepToString(),
                    "placement": {"base": list(feature.Placement.Base), "rotation": list(feature.Placement.Rotation.Q)}}

        foreign_before = foreign_state()
        self.assertIsNone(foreign.getObject("KurtShapeProject"))
        self.assertNotIn(foreign.Name, self.core.unmanaged)
        with self.assertRaisesRegex(ValueError, "existing document registration"):
            snapshot_document(foreign, self.core)
        foreign_after = foreign_state()
        self.assertEqual(foreign_after, foreign_before)
        self.assertIsNone(foreign.getObject("KurtShapeProject"))
        self.assertNotIn(foreign.Name, self.core.unmanaged)

        self.plate()
        before = snapshot_document(self.doc, self.core)
        owned = [obj for obj in before["strict"]["objects"] if obj["intrinsic_origin_member"]]
        self.assertEqual({obj["type_id"] for obj in owned}, INTRINSIC_TYPES)
        point = next(obj for obj in owned if obj["type_id"] == "App::Point")
        self.assertEqual(point["origin_membership"]["owner"], "Body")
        self.assertIn(point["name"], [obj.Name for obj in self.doc.Body.Origin.OriginFeatures])
        self.assertFalse(point["shapes"]["Shape"]["null"])
        self.assertGreater(point["shapes"]["Shape"]["brep_bytes"], 0)
        self.assertEqual(len(point["shapes"]["Shape"]["brep_sha256"]), 64)
        self.assertNotIn("hash_code", point["shapes"]["Shape"])
        self.assertIn("hash_code", before["observations"][point["name"]]["Shape"])
        self.assertEqual(len(before["observations"][point["name"]]["Shape"]["raw_brep_sha256"]), 64)
        for name in ("Body", "Profile", "Pad"):
            self.assertIn("hash_code", self.row(before, name)["shapes"]["Shape"])
        reads = []
        for _ in range(3):
            after = snapshot_document(self.doc, self.core)
            self.assertEqual(after["strict"], before["strict"])
            reads.append(after)
        inspections = []
        for _ in range(2):
            inspected = self.core.inspect(self.doc)
            self.assertEqual(inspected["revision"], before["strict"]["revision"])
            after = snapshot_document(self.doc, self.core)
            self.assertEqual(after["strict"], before["strict"])
            inspections.append(after)
        raw = self.doc.getObject(point["name"]).Shape.exportBrepToString()
        header = re.search(r"(?m)^TShapes [0-9]+\r?$", raw)
        self.assertIsNotNone(header)
        flags = re.search(r"(?m)(\r?\n\r?\n)([01]{7})(\r?)$", raw[header.end():])
        self.assertIsNotNone(flags)
        start = header.end() + flags.start(2)
        for bit in range(7):
            with self.subTest(native_tshape_flag=bit):
                index = start + bit
                changed = raw[:index] + ("0" if raw[index] == "1" else "1") + raw[index + 1:]
                if bit == 2:
                    self.assertEqual(canonical_brep(changed), canonical_brep(raw))
                else:
                    self.assertNotEqual(canonical_brep(changed), canonical_brep(raw))
        if not App.GuiUp:
            self.assertIs(before["strict"]["gui"]["available"], False)
            self.assertIn("not observed", before["strict"]["gui"]["reason"])
        self.report.update(passed=True, snapshots={"before": before, "reads": reads, "warm_inspections": inspections,
                                                  "foreign_rejection": {"before": foreign_before, "after": foreign_after}},
                           consequences={"all_four_owned_intrinsic_types": True, "point_content_verified": True,
                                         "model_hashes_retained": True, "strict_read_and_inspect_equality": True,
                                         "checked_cache_only_mask": True, "unregistered_foreign_rejected_without_writes": True})

    def test_native_frame_and_equal_measurement_model_mutations_are_detected_and_undo_restores(self):
        self.plate()
        doc = self.doc
        doc.openTransaction("Native origin frame mutation")
        before = snapshot_document(doc, self.core)
        original_placement = doc.Body.Placement.copy()
        doc.Body.Placement = App.Placement(App.Vector(7, 11, 13), App.Rotation(App.Vector(0, 0, 1), 30))
        changed = snapshot_document(doc, self.core)
        self.assertNotEqual(changed["strict"], before["strict"])
        self.assertNotEqual(self.row(changed, "Body")["placement"], self.row(before, "Body")["placement"])
        doc.commitTransaction()
        doc.undo()
        self.assertTrue(doc.Body.Placement.isSame(original_placement, 1e-9))
        # F4: undo can retain Touched flags. Prove the restored frame directly;
        # do not pretend the complete status/history snapshot is unchanged.
        restored = snapshot_document(doc, self.core)
        self.assertEqual(self.row(restored, "Body")["placement"], self.row(before, "Body")["placement"])
        self.assertEqual(restored["strict"]["revision"], before["strict"]["revision"])
        frame_snapshots = {"before": before, "changed": changed, "after_undo": restored}

        solid = doc.addObject("Part::Feature", "SameMeasurements")
        box = Part.makeBox(20, 10, 6)
        first = box.cut(Part.makeCylinder(1, 6, App.Vector(5, 5, 0)))
        second = box.cut(Part.makeCylinder(1, 6, App.Vector(15, 5, 0)))
        solid.Shape = first
        doc.recompute()
        baseline = snapshot_document(doc, self.core)
        old = self.row(baseline, solid.Name)["shapes"]["Shape"]
        doc.openTransaction("Native model content mutation")
        solid.Shape = second
        doc.commitTransaction()
        changed = snapshot_document(doc, self.core)
        new = self.row(changed, solid.Name)["shapes"]["Shape"]
        self.assertAlmostEqual(first.Volume, second.Volume, places=7)
        self.assertEqual([first.BoundBox.XMin, first.BoundBox.YMin, first.BoundBox.ZMin,
                          first.BoundBox.XMax, first.BoundBox.YMax, first.BoundBox.ZMax],
                         [second.BoundBox.XMin, second.BoundBox.YMin, second.BoundBox.ZMin,
                          second.BoundBox.XMax, second.BoundBox.YMax, second.BoundBox.ZMax])
        self.assertNotEqual(old["brep_sha256"], new["brep_sha256"])
        self.assertNotEqual(changed["strict"], baseline["strict"])
        doc.undo()
        restored_snapshot = snapshot_document(doc, self.core)
        restored = self.row(restored_snapshot, solid.Name)["shapes"]["Shape"]
        self.assertEqual(restored["brep_sha256"], old["brep_sha256"])
        self.assertEqual(restored["hash_code"], old["hash_code"])
        self.assertAlmostEqual(solid.Shape.Volume, first.Volume, places=7)
        self.report.update(passed=True, snapshots={"frame": frame_snapshots, "model_before": baseline,
                                                  "model_changed": changed, "model_after_undo": restored_snapshot},
                           consequences={"native_translation_and_rotation_detected": True,
                                         "native_frame_undo_restored": True, "equal_bbox_and_volume": True,
                                         "model_content_change_detected": True, "native_model_undo_restored": True},
                           undo_limit="Native undo may retain Touched flags; frame/content restoration is asserted directly")

    def test_native_link_false_replaces_body_source_frame_in_rotated_world_geometry(self):
        doc = App.newDocument("NativePlacementObservation")
        doc.UseHasher = False
        assembly = doc.addObject("App::Part", "NativeAssemblyContainer")
        source = doc.addObject("PartDesign::Body", "SourceBody")
        feature = source.newObject("PartDesign::Feature", "SourceSolid")
        feature.Shape = Part.makeBox(2, 3, 4, App.Vector(1, 2, 3))
        doc.recompute()
        link = assembly.newObject("App::Link", "Occurrence")
        link.setLink(source)
        link.LinkTransform = False
        doc.recompute()
        baseline_history = (doc.UndoCount, doc.RedoCount, doc.HasPendingTransaction)
        source.Placement = App.Placement(App.Vector(7, 11, 13), App.Rotation(App.Vector(1, 0, 0), 20))
        occurrence = App.Placement(App.Vector(17, 19, 23), App.Rotation(App.Vector(0, 0, 1), 35))
        parent = App.Placement(App.Vector(29, 31, 37), App.Rotation(App.Vector(0, 1, 0), 25))
        link.Placement = occurrence
        assembly.Placement = parent
        doc.recompute()
        self.assertIs(link.LinkTransform, False)
        self.assertTrue(link.Placement.isSame(occurrence, 1e-9))
        world = Part.getShape(assembly, link.Name + ".", transform=True)
        self.assertEqual(len(world.Solids), 1)
        self.assertEqual(len(world.Vertexes), 8)
        self.assertAlmostEqual(world.Volume, 24, places=7)
        expected = [(parent * occurrence).multVec(App.Vector(x, y, z))
                    for x, y, z in itertools.product((1, 3), (2, 5), (3, 7))]
        remaining = [vertex.Point for vertex in world.Vertexes]
        for point in expected:
            index = min(range(len(remaining)), key=lambda item: (remaining[item] - point).Length)
            self.assertLess((remaining.pop(index) - point).Length, 1e-7)
        self.assertFalse(remaining)
        # Source frame is deliberately nonidentity and cannot be silently added
        # to occurrence geometry. Read it, then prove observation has no effect.
        self.assertTrue(source.Placement.isSame(
            App.Placement(App.Vector(7, 11, 13), App.Rotation(App.Vector(1, 0, 0), 20)), 1e-9))
        self.assertEqual((doc.UndoCount, doc.RedoCount, doc.HasPendingTransaction), baseline_history)
        self.report.update(passed=True,
                           placement={"source": {"base": list(source.Placement.Base), "rotation": list(source.Placement.Rotation.Q)},
                                      "occurrence": {"base": list(link.Placement.Base), "rotation": list(link.Placement.Rotation.Q)},
                                      "assembly": {"base": list(assembly.Placement.Base), "rotation": list(assembly.Placement.Rotation.Q)},
                                      "expected_world_corners": [list(point) for point in expected],
                                      "actual_world_corners": [list(vertex.Point) for vertex in world.Vertexes],
                                      "volume_mm3": world.Volume, "link_transform": link.LinkTransform},
                           consequences={"native_false_replaces_body_source_placement": True,
                                         "translated_rotated_world_corners_match": True, "native_history_unchanged": True},
                           gui={"available": False, "reason": "No GUI state was read in the native placement proof"})

    def test_original_studio_fixture_including_every_origin_point_survives_two_warm_inspections(self):
        original_path = list(sys.path)
        benchmark = None
        try:
            sys.path.insert(0, str(support.ROOT / "tools" / "perf"))
            from bench_core import Benchmark
            benchmark = Benchmark(self.folder / "native-validation-studio", fixture="studio", repeat=1)
            fixture = benchmark.build()
            self.assertEqual(fixture["base_features"], 30)
            self.assertEqual(fixture["base_parts"], 4)
            self.assertEqual(fixture["selector_consumers"], 11)
            before = snapshot_document(benchmark.doc, benchmark.core)
            points = [obj for obj in before["strict"]["objects"]
                      if obj["type_id"] == "App::Point" and obj["intrinsic_origin_member"]]
            native_points = [obj for obj in benchmark.doc.Objects if obj.TypeId == "App::Point"]
            self.assertEqual({obj["name"] for obj in points}, {obj.Name for obj in native_points})
            self.assertGreaterEqual(len(points), 11)
            for point in points:
                self.assertFalse(point["shapes"]["Shape"]["null"])
                self.assertGreater(point["shapes"]["Shape"]["brep_bytes"], 0)
                self.assertEqual(len(point["shapes"]["Shape"]["brep_sha256"]), 64)
            inspections = []
            for _ in range(2):
                benchmark.core.inspect(benchmark.doc)
                after = snapshot_document(benchmark.doc, benchmark.core)
                self.assertEqual(after["strict"], before["strict"])
                inspections.append(after)
            self.report.update(passed=True, fixture=fixture,
                               snapshots={"before": before, "warm_inspections": inspections},
                               consequences={"original_30_4_11_fixture": True, "every_origin_point_covered": True,
                                             "all_intrinsic_content_verified": True, "strict_warm_inspect_equality": True})
        finally:
            try:
                if benchmark is not None:
                    benchmark.core.close()
            except Exception:
                self.report["passed"] = False
                self.report["cleanup_error"] = traceback.format_exc()
                raise
            finally:
                sys.path[:] = original_path


if __name__ == "__main__":
    unittest.main()
