"""Native preview results must match acceptance without changing live intent."""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
from kurtshape.core import Controller, OperationError, intent_signature
from kurtshape.extrusion_preview import ExtrusionEvaluator
from native_validation_snapshot import snapshot_document


LIFECYCLE_METHODS = frozenset({
    "test_lru_eight_real_results_units_and_eviction_preserve_source",
    "test_partial_native_model_failure_discards_clone_and_allows_retry",
    "test_partial_native_open_failure_preserves_unrelated_document",
    "test_native_dimension_and_placement_changes_reject_stale_preview",
    "test_closed_source_name_reuse_cannot_reuse_cached_preview",
})
LIFECYCLE_SOURCES = (
    "tests/test_extrusion_preview.py", "tests/support.py", "tools/run_native_tests.py",
    "tools/native_validation_snapshot.py", "src/kurtshape/extrusion_preview.py",
    "src/kurtshape/core.py", "src/kurtshape/document_state.py", "src/kurtshape/geometry.py", "src/kurtshape/bodies.py",
    "src/kurtshape/studio.py", "src/kurtshape/settings.py", "src/kurtshape/recovery.py",
)


class ExtrusionPreviewTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        if self._testMethodName in LIFECYCLE_METHODS:
            # Register first so proof publication follows environment/fixture
            # cleanup, including any cleanup failure recorded by unittest.
            self._begin_lifecycle_proof()
        self.folder = support.isolated_session(self, prefix="extrusion-preview-tests-")
        if self._testMethodName in LIFECYCLE_METHODS:
            self._bind_lifecycle_fixture()
        self.core = Controller()
        self.state = None
        self.previews = []
        self.call("new")

    def tearDown(self):
        for preview in self.previews:
            preview.close()
        self.core.close()
        for name in set(App.listDocuments()) - self.names:
            App.closeDocument(name)

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def call(self, op, **args):
        request = dict(op=op, **args)
        if op != "new":
            request.update(document_id=self.state["document_id"], expected_revision=self.state["revision"])
        response = self.core.dispatch(request)
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        return self.state

    def preview(self):
        preview = ExtrusionEvaluator(self.core, self.doc, self.state["revision"])
        self.previews.append(preview)
        return preview

    def invariant(self):
        return (intent_signature(self.doc), self.core.identifier(self.doc), self.core._meta(self.doc).Revision,
                self.doc.UndoCount, self.doc.RedoCount, self.doc.HasPendingTransaction, self.doc.FileName,
                tuple(App.listDocuments()), tuple(self.core.documents), tuple(self.core.observer.states),
                tuple(sorted(self.core.geometry.documents())), App.activeDocument().Name,
                json.dumps(self.core._meta(self.doc).SourceMapping))

    def plate(self):
        self.call("sketch_rectangle", id="BaseProfile", width=20, height=10)
        self.call("pad", profile="BaseProfile", length=6)

    def top(self):
        return "Face" + str(next(index + 1 for index, face in enumerate(self.doc.Pad.Shape.Faces)
                                 if abs(face.CenterOfMass.z - 6) < 1e-7))

    def test_initial_pad_quantity_reverse_cache_and_cancel_are_disposable(self):
        self.call("sketch_rectangle", id="Profile", width=20, height=10)
        baseline = self.invariant()
        preview = self.preview()
        first = preview.evaluate(dict(op="pad", profile="Profile", length="1/8 in", reversed=False))
        self.assertTrue(first.valid, first.error)
        self.assertAlmostEqual(first.shape.Volume, 20 * 10 * 3.175)
        self.assertAlmostEqual(first.material_shape.Volume, first.shape.Volume)
        self.assertAlmostEqual(first.shape.BoundBox.ZMin, 0)
        reverse = preview.evaluate(dict(op="pad", profile="Profile", length=3.175, reversed=True))
        self.assertTrue(reverse.valid, reverse.error)
        self.assertAlmostEqual(reverse.shape.BoundBox.ZMin, -3.175)
        cached = preview.evaluate(dict(op="pad", profile="Profile", length=3.175, reversed=False))
        self.assertTrue(cached.cached)
        self.assertEqual(preview.evaluations, 2)
        self.assertEqual(self.invariant(), baseline)
        folder = preview._snapshot.parent
        preview.close()
        self.assertFalse(folder.exists())
        self.assertEqual(self.invariant(), baseline)

    def test_attached_pad_and_blind_through_all_pockets_match_actual_acceptance(self):
        self.plate()
        self.call("sketch_circle", id="Attached", x=10, y=5, diameter=4,
                  support={"feature": "Pad", "subelement": self.top()})
        baseline = self.invariant()
        preview = self.preview()
        add = preview.evaluate(dict(op="pad", profile="Attached", length=2, reversed=False))
        self.assertTrue(add.valid, add.error)
        self.assertAlmostEqual(add.shape.Volume - 1200, 3.141592653589793 * 4 * 2)
        self.assertAlmostEqual(add.material_shape.Volume, add.shape.Volume - 1200)
        blind = preview.evaluate(dict(op="pocket", profile="Attached", length=2, through_all=False, reversed=False))
        self.assertTrue(blind.valid, blind.error)
        through = preview.evaluate(dict(op="pocket", profile="Attached", through_all=True, reversed=False, length="bad input"))
        self.assertTrue(through.valid, through.error)
        self.assertAlmostEqual(through.material_shape.Volume, 3.141592653589793 * 4 * 6)
        self.assertLess(through.shape.Volume, blind.shape.Volume)
        invalid_direction = preview.evaluate(dict(op="pocket", profile="Attached", through_all=True, reversed=True))
        self.assertFalse(invalid_direction.valid)
        self.assertEqual(invalid_direction.error["code"], "empty_cut")
        self.assertEqual(self.invariant(), baseline)
        preview.close()
        self.call("pocket", id="Accepted", **{key: value for key, value in blind.proposal.items() if key != "op"})
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, blind.shape.Volume)
        self.assertEqual(self.doc.UndoCount, baseline[3] + 1)
        self.assertAlmostEqual(self.doc.Accepted.Length.Value, 2)

    def test_origin_plane_pocket_follows_default_direction_and_reversed_changes(self):
        self.plate()
        self.call("sketch_circle", id="BottomCut", x=10, y=5, diameter=4)
        baseline = self.invariant()
        preview = self.preview()
        automatic = preview.evaluate(dict(op="pocket", profile="BottomCut", length=2, through_all=False))
        self.assertTrue(automatic.valid, automatic.error)
        explicit = preview.evaluate(dict(op="pocket", profile="BottomCut", length=2, through_all=False, reversed=True))
        self.assertTrue(explicit.valid, explicit.error)
        self.assertAlmostEqual(automatic.shape.Volume, explicit.shape.Volume)
        opposite = preview.evaluate(dict(op="pocket", profile="BottomCut", length=2, through_all=False, reversed=False))
        self.assertFalse(opposite.valid)
        self.assertEqual(self.invariant(), baseline)

    def test_second_body_preview_uses_profile_owner_and_world_placement(self):
        self.plate()
        self.call("create_body", id="Housing")
        self.call("sketch_rectangle", body="Housing", id="SecondProfile", width=4, height=5, plane="YZ")
        self.doc.Housing.Placement.Base = App.Vector(40, 0, 0)
        self.doc.recompute()
        self.call("inspect")
        baseline = self.invariant()
        preview = self.preview()
        result = preview.evaluate(dict(op="pad", profile="SecondProfile", length=3))
        self.assertTrue(result.valid, result.error)
        self.assertEqual(result.body_id, "Housing")
        self.assertAlmostEqual(result.shape.Volume, 60)
        self.assertAlmostEqual(result.shape.BoundBox.XMin, 40)
        self.assertAlmostEqual(result.shape.BoundBox.XMax, 43)
        self.assertEqual(self.invariant(), baseline)
        mismatch = preview.evaluate(dict(op="pad", body="Body", profile="SecondProfile", length=3))
        self.assertFalse(mismatch.valid)
        self.assertEqual(mismatch.error["code"], "cross_body_reference")
        self.assertEqual(self.invariant(), baseline)

    def test_bad_text_missing_profile_open_geometry_and_stale_task_keep_live_model(self):
        self.call("create_sketch", id="OpenProfile")
        self.call("add_line", sketch="OpenProfile", x1=0, y1=0, x2=10, y2=0)
        baseline = self.invariant()
        preview = self.preview()
        for proposal, code in [
            (dict(op="pad", profile="OpenProfile", length="2 s"), "invalid_argument"),
            (dict(op="pad", profile="OpenProfile", length=-2), "invalid_argument"),
            (dict(op="pad", profile="Missing", length=2), "missing_reference"),
            (dict(op="pad", profile="OpenProfile", length=2), "build_failed"),
            (dict(op="pad", profile="OpenProfile", length=2, reversed="yes"), "invalid_argument"),
        ]:
            result = preview.evaluate(proposal)
            self.assertFalse(result.valid, proposal)
            self.assertEqual(result.error["code"], code, result.error)
            self.assertEqual(self.invariant(), baseline)
        self.call("rename_feature", feature="OpenProfile", name="Changed")
        after_change = self.invariant()
        result = preview.evaluate(dict(op="pad", profile="OpenProfile", length=2))
        self.assertEqual(result.error["code"], "stale_revision")
        self.assertEqual(self.invariant(), after_change)

    @staticmethod
    def _lifecycle_sources():
        return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                for name in LIFECYCLE_SOURCES}

    def _begin_lifecycle_proof(self):
        raw = Path(os.environ["KURTSHAPE_EVIDENCE_DIR"])
        if not raw.is_absolute():
            raise RuntimeError("Preview lifecycle proof requires absolute private evidence")
        self._proof_evidence = support._native_fixture_path(raw, support.TEST_TMP)
        self._proof_directory = support._native_fixture_path(
            self._proof_evidence / "extrusion-preview-lifecycle", self._proof_evidence)
        self._proof_output = support._native_fixture_path(
            self._proof_directory / (self._testMethodName + ".json"), self._proof_directory)
        self._proof_suite_environment = {name: os.environ.get(name) for name in support.ISOLATION_VARIABLES}
        self._proof = {
            "schema_version": 1, "passed": False, "method_completed": False,
            "pid": os.getpid(), "test_id": self.id(),
            "started_utc": datetime.now(timezone.utc).isoformat(),
            "engine": {"FreeCAD": App.Version(), "OCCT": Part.OCC_VERSION, "home": App.getHomePath()},
            "suite_environment_before": self._proof_suite_environment,
            "environment": None, "fixture_receipt": None,
            "source_before": self._lifecycle_sources(), "steps": [], "checks": {},
            "limits": ["Native lifecycle consequences, not a timing benchmark or preview speed claim.",
                       "GUI state is unavailable unless actually observed with GuiUp.",
                       "Intrinsic datum raw hashes remain observations; complete modeled content stays strict.",
                       "Observer generation and read-cache changes are traced without changing their values.",
                       "Fixture/path identity checks are point-in-time guards, not race-free guarantees."],
        }
        self.addCleanup(self._write_lifecycle_proof)

    def _bind_lifecycle_fixture(self):
        receipts = support._native_fixture_path(self._proof_evidence / "native-fixtures", self._proof_evidence)
        path = support._native_fixture_path(receipts / (self.folder.name + ".json"), receipts)
        raw = path.read_bytes()
        data = json.loads(raw)
        self.assertEqual(data["test_id"], self.id())
        self.assertEqual(data["pid"], os.getpid())
        self.assertEqual(Path(data["fixture"]).resolve(), self.folder)
        self.assertEqual(data["environment"], self._proof_suite_environment)
        self._proof["fixture_receipt"] = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                                          "data": data}
        self._proof["environment"] = {name: os.environ.get(name) for name in support.ISOLATION_VARIABLES}
        self.assertEqual(self._proof["environment"]["KURTSHAPE_SESSION_DIR"], str(self.folder))
        for name in support.ISOLATION_VARIABLES[1:]:
            self.assertEqual(self._proof["environment"][name], self._proof_suite_environment[name])

    def _write_lifecycle_proof(self):
        result = self._outcome.result
        errors = list(getattr(result, "failures", ())) + list(getattr(result, "errors", ()))
        failed = any(test is self or getattr(test, "test_case", None) is self for test, _ in errors)
        self._proof["source_after"] = self._lifecycle_sources()
        self._proof["source_unchanged"] = self._proof["source_before"] == self._proof["source_after"]
        self._proof["suite_environment_after"] = {
            name: os.environ.get(name) for name in support.ISOLATION_VARIABLES}
        fixture = getattr(self, "folder", None)
        cleanup = {
            "environment_restored": self._proof["suite_environment_after"] == self._proof_suite_environment,
            "fixture_removed": fixture is not None and not fixture.exists(),
            "owned_documents_closed": set(App.listDocuments()) == self.names,
        }
        receipt = self._proof["fixture_receipt"]
        cleanup["fixture_receipt_unchanged"] = bool(receipt) and hashlib.sha256(
            Path(receipt["path"]).read_bytes()).hexdigest() == receipt["sha256"]
        self._proof["cleanup"] = cleanup
        self._proof["checks"].update({"cleanup_" + key: value for key, value in cleanup.items()})
        self._proof["passed"] = bool(self._proof["method_completed"] and not failed
                                     and self._proof["source_unchanged"] and all(cleanup.values())
                                     and all(value is True for value in self._proof["checks"].values()))
        self._proof["completed_utc"] = datetime.now(timezone.utc).isoformat()
        evidence = support._native_fixture_path(self._proof_evidence, support.TEST_TMP)
        directory = support._native_fixture_path(self._proof_directory, evidence)
        output = support._native_fixture_path(self._proof_output, directory)
        stage = support._native_fixture_path(output.with_suffix(".saving"), directory)
        if output.exists() or stage.exists():
            raise FileExistsError("Preserve the earlier preview lifecycle proof: " + str(output))
        directory.mkdir(parents=True, exist_ok=True)
        output = support._native_fixture_path(output, directory)
        stage = support._native_fixture_path(stage, directory)
        with stage.open("x", encoding="utf-8") as stream:
            json.dump(self._proof, stream, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(stage, output)
        self.assertTrue(self._proof["source_unchanged"], self._proof["source_after"])
        self.assertTrue(all(cleanup.values()), cleanup)

    @staticmethod
    def _result_geometry(shape):
        if shape is None:
            return None
        box = shape.BoundBox
        return {"null": shape.isNull(), "valid": shape.isValid(), "solids": len(shape.Solids),
                "volume_mm3": shape.Volume,
                "bounds_mm": [box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax],
                "brep_sha256": hashlib.sha256(shape.exportBrepToString().encode("utf-8")).hexdigest()}

    def _preview_trace(self, preview):
        if preview is None:
            return None
        path = preview._snapshot
        snapshot = None
        if path is not None:
            path = support._native_fixture_path(path, Path(os.environ["TEMP"]).resolve())
            snapshot = {"path": str(path), "exists": path.is_file(),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None}
        source_open = self.core._is_open(preview.document)
        state = self.core.observer.states.get(preview.document_name) if source_open else None
        return {"closed": preview.closed, "document_name": preview.document_name,
                "source_open": source_open, "expected_revision": preview.expected_revision,
                "observer_generation": state.get("generation") if state is not None else None,
                "captured_generation": preview._generation, "evaluations": preview.evaluations,
                "cache_keys": list(preview._cache),
                "cache_proposals": [entry.proposal for entry in preview._cache.values()], "snapshot": snapshot}

    def _lifecycle_step(self, label, doc, preview=None, files=(), result=None, **extra):
        snapshot = snapshot_document(doc, self.core)
        active = App.activeDocument()
        bindings = {}
        for identifier, native_doc in self.core.documents.items():
            opened = self.core._is_open(native_doc)
            bindings[identifier] = {"open": opened, "name": native_doc.Name if opened else None,
                                    "python_identity": id(native_doc)}
        inventory = {"native_documents": sorted(App.listDocuments()), "controller_documents": bindings,
                     "source_document_id": self.core.identifier(doc),
                     "source_mapping": self.core._meta(doc).SourceMapping,
                     "controller_signatures": dict(self.core.signatures),
                     "sketch_edit_documents": sorted(self.core.sketch_edits),
                     "observer_documents": sorted(self.core.observer.states),
                     "geometry_documents": sorted(self.core.geometry.documents()),
                     "unmanaged_documents": sorted(self.core.unmanaged),
                     "active_document": active.Name if active is not None else None,
                     "busy": self.core.busy,
                     "active_transaction": list(App.getActiveTransaction() or (None, None))}
        originals = []
        for path in files:
            path = support._native_fixture_path(path, self.folder)
            raw = path.read_bytes()
            originals.append({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
        step = {"label": label, "snapshot": snapshot, "inventory": inventory, "original_files": originals,
                "preview": self._preview_trace(preview), **extra}
        if result is not None:
            step["result"] = {"valid": result.valid, "cached": result.cached, "error": result.error,
                              "proposal": result.proposal, "body_id": result.body_id,
                              "base_revision": result.base_revision,
                              "shape": self._result_geometry(result.shape),
                              "material": self._result_geometry(result.material_shape)}
        self._proof["steps"].append(step)
        return {"strict": snapshot["strict"], "inventory": inventory, "original_files": originals}

    def _finish_lifecycle_proof(self, **checks):
        self.assertTrue(checks)
        self.assertTrue(all(value is True for value in checks.values()), checks)
        self._proof["checks"].update(checks)
        self._proof["method_completed"] = True

    def _saved_preview_plate(self):
        self.plate()
        self.call("sketch_circle", id="Attached", x=10, y=5, diameter=4,
                  support={"feature": "Pad", "subelement": self.top()})
        path = support._native_fixture_path(self.folder / "preview-source-original.FCStd", self.folder)
        self.call("save", path=str(path))
        return path

    def _assert_rectangular_preview(self, result, depth):
        self.assertTrue(result.valid, result.error)
        self.assertEqual(len(result.shape.Solids), 1)
        self.assertTrue(result.shape.isValid())
        self.assertAlmostEqual(result.shape.Volume, 200 * depth, places=7)
        self.assertAlmostEqual(result.material_shape.Volume, 200 * depth, places=7)
        for actual, expected in zip(self._result_geometry(result.shape)["bounds_mm"], [0, 0, 0, 20, 10, depth]):
            self.assertAlmostEqual(actual, expected, places=7)

    def _assert_attached_preview(self, result, source_depth=6, translation=(0, 0, 0)):
        self.assertTrue(result.valid, result.error)
        self.assertEqual(len(result.shape.Solids), 1)
        self.assertTrue(result.shape.isValid())
        self.assertAlmostEqual(result.shape.Volume, 200 * source_depth + math.pi * 8, places=7)
        self.assertAlmostEqual(result.material_shape.Volume, math.pi * 8, places=7)
        x, y, z = translation
        expected_shape = [x, y, z, x + 20, y + 10, z + source_depth + 2]
        expected_material = [x + 8, y + 3, z + source_depth, x + 12, y + 7, z + source_depth + 2]
        for shape, bounds in ((result.shape, expected_shape), (result.material_shape, expected_material)):
            for actual, expected in zip(self._result_geometry(shape)["bounds_mm"], bounds):
                self.assertAlmostEqual(actual, expected, places=7)

    def test_lru_eight_real_results_units_and_eviction_preserve_source(self):
        self.call("sketch_rectangle", id="Profile", width=20, height=10)
        source = support._native_fixture_path(self.folder / "preview-profile-original.FCStd", self.folder)
        self.call("save", path=str(source))
        preview = self.preview()
        self.assertEqual(list(preview._cache), [])
        self.assertEqual(preview.evaluations, 0)
        baseline = self._lifecycle_step("initial_empty_cache", self.doc, preview, (source,))
        held = []
        # A real first evaluation records saveCopy's observed generation edge;
        # no cache/generation reset is used to prepare the eight-result test.
        primer = preview.evaluate(dict(op="pad", profile="Profile", length=0.5))
        self._assert_rectangular_preview(primer, 0.5)
        self.assertFalse(primer.cached)
        held.append((primer, 0.5))
        self.assertEqual(self._lifecycle_step("first_snapshot_generation", self.doc, preview, (source,), primer), baseline)
        for depth in range(1, 9):
            with self.subTest(depth=depth):
                before = self._preview_trace(preview)
                result = preview.evaluate(dict(op="pad", profile="Profile", length=depth))
                self._assert_rectangular_preview(result, depth)
                self.assertFalse(result.cached)
                held.append((result, depth))
                self.assertEqual(self._lifecycle_step("fill_" + str(depth), self.doc, preview, (source,), result,
                                                     preview_before=before), baseline)
        self.assertEqual(preview.evaluations, 9)
        self.assertEqual([entry.proposal["length"] for entry in preview._cache.values()], list(range(1, 9)))
        for quantity in ("5 mm", "0.5 cm", 5.0):
            result = preview.evaluate(dict(op="pad", profile="Profile", length=quantity))
            self._assert_rectangular_preview(result, 5)
            self.assertTrue(result.cached)
            self.assertEqual(result.proposal["length"], 5.0)
            self.assertEqual(preview.evaluations, 9)
            self.assertEqual(self._lifecycle_step("unit_" + str(quantity), self.doc, preview, (source,), result), baseline)
        keys = list(preview._cache)
        rejected = preview.evaluate(dict(op="pad", profile="Profile", length="5 s"))
        self.assertFalse(rejected.valid)
        self.assertEqual(rejected.error["code"], "invalid_argument")
        self.assertEqual(list(preview._cache), keys)
        self.assertEqual(preview.evaluations, 9)
        self.assertEqual(self._lifecycle_step("wrong_dimension_rejected", self.doc, preview, (source,), rejected), baseline)
        promoted = preview.evaluate(dict(op="pad", profile="Profile", length=1))
        self.assertTrue(promoted.cached)
        self._assert_rectangular_preview(promoted, 1)
        ninth = preview.evaluate(dict(op="pad", profile="Profile", length=9))
        self._assert_rectangular_preview(ninth, 9)
        self.assertFalse(ninth.cached)
        self.assertEqual(preview.evaluations, 10)
        self.assertEqual([entry.proposal["length"] for entry in preview._cache.values()], [3, 4, 6, 7, 8, 5, 1, 9])
        self.assertEqual(self._lifecycle_step("least_recent_two_evicted", self.doc, preview, (source,), ninth), baseline)
        kept = preview.evaluate(dict(op="pad", profile="Profile", length=1))
        self.assertTrue(kept.cached)
        self.assertEqual(preview.evaluations, 10)
        recomputed = preview.evaluate(dict(op="pad", profile="Profile", length=2))
        self._assert_rectangular_preview(recomputed, 2)
        self.assertFalse(recomputed.cached)
        self.assertEqual(preview.evaluations, 11)
        self.assertEqual(len(preview._cache), 8)
        self.assertEqual([entry.proposal["length"] for entry in preview._cache.values()], [4, 6, 7, 8, 5, 9, 1, 2])
        self.assertEqual(self._lifecycle_step("evicted_two_recomputed", self.doc, preview, (source,), recomputed), baseline)
        folder = preview._snapshot.parent
        preview.close()
        preview.close()
        self.assertFalse(folder.exists())
        self.assertEqual(list(preview._cache), [])
        for result, depth in held:
            self._assert_rectangular_preview(result, depth)
        self.assertEqual(self._lifecycle_step("detached_results_survive_close", self.doc, preview, (source,)), baseline)
        self._finish_lifecycle_proof(real_lru_eight=True, equivalent_units_hit=True, wrong_dimension_rejected=True,
                                     real_eviction_recomputed=True, detached_solids_survive_close=True,
                                     strict_source_and_original_bytes_preserved=True)

    def test_partial_native_model_failure_discards_clone_and_allows_retry(self):
        source = self._saved_preview_plate()
        doc = self.doc
        preview = self.preview()
        proposal = dict(op="pad", profile="Attached", length=2, reversed=False)
        baseline = self._lifecycle_step("before_model_failure", doc, preview, (source,))
        original = self.core._model_operation
        injected = []

        def fail_after_native_model(clone, operation):
            self.assertIsNot(clone, doc)
            self.assertTrue(self.core.busy)
            self.assertNotIn(clone, self.core.documents.values())
            original(clone, operation)
            feature = clone.getObject(operation["id"])
            self.assertIsNotNone(feature)
            self.assertEqual(feature.TypeId, "PartDesign::Pad")
            self.assertAlmostEqual(clone.Body.Shape.Volume, 1200 + math.pi * 8, places=7)
            injected.append({"name": clone.Name, "feature": feature.Name, "request": dict(operation),
                             "snapshot": snapshot_document(clone, self.core)})
            raise OperationError("injected_preview_model_failure", "Injected after the real native Pad")

        with patch.object(self.core, "_model_operation", side_effect=fail_after_native_model) as model:
            failed = preview.evaluate(proposal)
            self.assertEqual(model.call_count, 1)
        self.assertFalse(failed.valid)
        self.assertEqual(failed.error["code"], "injected_preview_model_failure")
        self.assertEqual(len(injected), 1)
        self.assertNotIn(injected[0]["name"], App.listDocuments())
        self.assertEqual(preview.evaluations, 1)
        self.assertEqual(list(preview._cache), [])
        self.assertEqual(self._lifecycle_step("partial_model_discarded", doc, preview, (source,), failed,
                                             injection=injected), baseline)
        accepted = preview.evaluate(proposal)
        self._assert_attached_preview(accepted)
        self.assertFalse(accepted.cached)
        self.assertAlmostEqual(accepted.shape.Volume, 1200 + math.pi * 8, places=7)
        self.assertAlmostEqual(accepted.material_shape.Volume, math.pi * 8, places=7)
        self.assertEqual(preview.evaluations, 2)
        self.assertEqual(self._lifecycle_step("native_retry_succeeds", doc, preview, (source,), accepted), baseline)
        self._finish_lifecycle_proof(real_clone_pad_created_before_failure=True, failure_not_cached=True,
                                     owned_clone_and_transaction_released=True, native_retry_succeeds=True,
                                     strict_source_and_original_bytes_preserved=True)

    def test_partial_native_open_failure_preserves_unrelated_document(self):
        source = self._saved_preview_plate()
        doc = self.doc
        sentinel = App.newDocument("PreviewUnrelatedSentinel")
        self.core.attach(sentinel)
        solid = sentinel.addObject("Part::Feature", "SentinelSolid")
        solid.Shape = Part.makeBox(2, 3, 4)
        sentinel.recompute()
        self.core.sync(sentinel)
        sentinel_before = snapshot_document(sentinel, self.core)
        App.setActiveDocument(doc.Name)
        preview = self.preview()
        proposal = dict(op="pad", profile="Attached", length=2, reversed=False)
        baseline = self._lifecycle_step("before_partial_open", doc, preview, (source,),
                                        unrelated_snapshot=sentinel_before)
        native_open = App.openDocument
        opened = []

        def fail_after_native_open(*args, **kwargs):
            clone = native_open(*args, **kwargs)
            self.assertIsNot(clone, doc)
            self.assertIsNot(clone, sentinel)
            self.assertNotIn(clone.Name, baseline["inventory"]["native_documents"])
            opened.append({"name": clone.Name, "filename": clone.FileName,
                           "snapshot": snapshot_document(clone, self.core)})
            raise RuntimeError("Injected loader failure after actual native open")

        with patch.object(App, "openDocument", side_effect=fail_after_native_open) as loader:
            failed = preview.evaluate(proposal)
            self.assertEqual(loader.call_count, 1)
        self.assertFalse(failed.valid)
        self.assertEqual(failed.error["code"], "preview_failed")
        self.assertIn("Injected loader failure", failed.error["message"])
        self.assertEqual(len(opened), 1)
        self.assertNotIn(opened[0]["name"], App.listDocuments())
        self.assertTrue(self.core._is_open(sentinel))
        self.assertEqual(snapshot_document(sentinel, self.core)["strict"], sentinel_before["strict"])
        self.assertEqual(preview.evaluations, 0)
        self.assertEqual(list(preview._cache), [])
        self.assertEqual(self._lifecycle_step("partial_open_discarded_only_owned_clone", doc, preview, (source,), failed,
                                             opened=opened, unrelated_snapshot=snapshot_document(sentinel, self.core)), baseline)
        accepted = preview.evaluate(proposal)
        self._assert_attached_preview(accepted)
        self.assertFalse(accepted.cached)
        self.assertAlmostEqual(accepted.shape.Volume, 1200 + math.pi * 8, places=7)
        self.assertAlmostEqual(accepted.material_shape.Volume, math.pi * 8, places=7)
        self.assertEqual(preview.evaluations, 1)
        self.assertEqual(snapshot_document(sentinel, self.core)["strict"], sentinel_before["strict"])
        self.assertEqual(self._lifecycle_step("open_retry_preserves_sentinel", doc, preview, (source,), accepted,
                                             unrelated_snapshot=snapshot_document(sentinel, self.core)), baseline)
        self._finish_lifecycle_proof(real_native_open_precedes_failure=True, only_owned_clone_closed=True,
                                     unrelated_native_document_preserved=True, no_failed_native_model_evaluation=True,
                                     native_retry_succeeds=True, strict_source_and_original_bytes_preserved=True)

    def test_native_dimension_and_placement_changes_reject_stale_preview(self):
        source = self._saved_preview_plate()
        doc = self.doc
        proposal = dict(op="pad", profile="Attached", length=2, reversed=False)
        for kind in ("dimension", "placement"):
            with self.subTest(native_change=kind):
                preview = self.preview()
                before = self._lifecycle_step(kind + "_before_change", doc, preview, (source,))
                first = preview.evaluate(proposal)
                self._assert_attached_preview(first, 6 if kind == "dimension" else 8)
                self.assertFalse(first.cached)
                self.assertEqual(self._lifecycle_step(kind + "_initial_preview", doc, preview, (source,), first), before)
                old_revision = self.state["revision"]
                if kind == "dimension":
                    doc.Pad.Length = App.Units.Quantity("8 mm")
                else:
                    doc.Body.Placement.Base = App.Vector(13, 7, 4)
                doc.recompute()
                self.call("inspect")
                self.assertNotEqual(self.state["revision"], old_revision)
                self.assertAlmostEqual(doc.Body.Shape.Volume, 1600, places=7)
                changed = self._lifecycle_step(kind + "_native_change_reconciled", doc, preview, (source,))
                self.assertNotEqual(changed["strict"]["intent_sha256"], before["strict"]["intent_sha256"])
                cache_before = self._preview_trace(preview)
                with patch.object(App, "openDocument", wraps=App.openDocument) as loader:
                    rejected = preview.evaluate(proposal)
                    self.assertEqual(loader.call_count, 0)
                self.assertFalse(rejected.valid)
                self.assertFalse(rejected.cached)
                self.assertEqual(rejected.error["code"], "stale_revision")
                self.assertEqual(self._preview_trace(preview), cache_before)
                self.assertEqual(self._lifecycle_step(kind + "_stale_task_rejected", doc, preview, (source,), rejected), changed)
                fresh = self.preview()
                result = fresh.evaluate(proposal)
                self._assert_attached_preview(result, 8, (0, 0, 0) if kind == "dimension" else (13, 7, 4))
                self.assertFalse(result.cached)
                self.assertAlmostEqual(result.shape.Volume, 1600 + math.pi * 8, places=7)
                self.assertAlmostEqual(result.material_shape.Volume, math.pi * 8, places=7)
                self.assertAlmostEqual(result.shape.BoundBox.ZMax, 10 if kind == "dimension" else 14, places=7)
                if kind == "placement":
                    self.assertAlmostEqual(result.shape.BoundBox.XMin, 13, places=7)
                    self.assertAlmostEqual(result.shape.BoundBox.YMin, 7, places=7)
                    self.assertAlmostEqual(result.shape.BoundBox.ZMin, 4, places=7)
                self.assertEqual(self._lifecycle_step(kind + "_fresh_task_uses_changed_geometry", doc, fresh, (source,), result), changed)
                preview.close()
                fresh.close()
        self._finish_lifecycle_proof(real_dimension_change_rejects_stale=True, real_body_placement_change_rejects_stale=True,
                                     stale_rejection_opens_no_clone=True, stale_rejection_preserves_cache_and_snapshot=True,
                                     fresh_tasks_use_changed_native_geometry=True, original_saved_bytes_preserved=True)

    def test_closed_source_name_reuse_cannot_reuse_cached_preview(self):
        source_file = self._saved_preview_plate()
        source = self.doc
        source_name = source.Name
        source_identifier = self.state["document_id"]
        old = self.preview()
        proposal = dict(op="pad", profile="Attached", length=2, reversed=False)
        baseline = self._lifecycle_step("original_source", source, old, (source_file,))
        first = old.evaluate(proposal)
        self._assert_attached_preview(first)
        self.assertAlmostEqual(first.shape.Volume, 1200 + math.pi * 8, places=7)
        cached = old.evaluate(proposal)
        self.assertTrue(cached.valid, cached.error)
        self.assertTrue(cached.cached)
        self.assertEqual(old.evaluations, 1)
        self.assertEqual(self._lifecycle_step("original_cached_preview", source, old, (source_file,), cached), baseline)
        old_snapshot = self._preview_trace(old)["snapshot"]
        App.closeDocument(source_name)
        replacement = App.newDocument(source_name)
        self.assertEqual(replacement.Name, source_name)
        self.assertIsNot(replacement, source)
        self.core.attach(replacement)
        replacement.addObject("PartDesign::Body", "Body")
        self.core._recompute(replacement)
        self.state = self.core.inspect(replacement)
        self.assertNotEqual(self.state["document_id"], source_identifier)
        self.assertFalse(self.core._is_open(source))
        self.call("sketch_rectangle", id="ReplacementProfile", width=4, height=5)
        before = self._lifecycle_step("distinct_replacement_with_same_native_name", replacement, old, (source_file,),
                                      original_document_id=source_identifier, exact_reused_native_name=source_name)
        with patch.object(App, "openDocument", wraps=App.openDocument) as loader:
            rejected = old.evaluate(proposal)
            self.assertEqual(loader.call_count, 0)
        self.assertFalse(rejected.valid)
        self.assertEqual(rejected.error["code"], "unknown_document")
        self.assertFalse(rejected.cached)
        self.assertEqual(old.evaluations, 1)
        self.assertEqual(self._preview_trace(old)["snapshot"], old_snapshot)
        self.assertEqual(self._lifecycle_step("old_task_rejects_native_name_reuse", replacement, old, (source_file,), rejected), before)
        folder = old._snapshot.parent
        old.close()
        old.close()
        self.assertFalse(folder.exists())
        self.assertEqual(list(old._cache), [])
        closed = old.evaluate(proposal)
        self.assertFalse(closed.valid)
        self.assertEqual(closed.error["code"], "preview_closed")
        self.assertEqual(self._lifecycle_step("closed_task_rejects_without_touching_replacement", replacement, old,
                                             (source_file,), closed), before)
        fresh = self.preview()
        result = fresh.evaluate(dict(op="pad", profile="ReplacementProfile", length=3))
        self.assertTrue(result.valid, result.error)
        self.assertFalse(result.cached)
        self.assertAlmostEqual(result.shape.Volume, 60, places=7)
        self.assertAlmostEqual(result.material_shape.Volume, 60, places=7)
        self.assertEqual(result.body_id, "Body")
        self.assertEqual(self._lifecycle_step("fresh_task_evaluates_replacement_geometry", replacement, fresh,
                                             (source_file,), result), before)
        self.assertAlmostEqual(first.shape.Volume, 1200 + math.pi * 8, places=7)
        self._finish_lifecycle_proof(exact_native_name_reused_by_distinct_document=True, old_task_rejected_before_clone=True,
                                     closed_task_rejected=True, old_snapshot_and_cache_disposed=True,
                                     replacement_geometry_and_state_preserved=True, original_saved_bytes_preserved=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
