"""Private native correctness gates for one-shot STEP admission digest reuse.

Run only in the root-owned native harness. No child process is launched here.
The incumbent functions remain the independent fingerprint/fallback oracle.
"""
from contextlib import contextmanager
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for folder in (ROOT / "tests", ROOT / "tools", ROOT / "src"):
    sys.path.insert(0, str(folder))

import FreeCAD as App
import Part
from kurtshape import assembly, core as core_module, step_export_worker as worker_module
from kurtshape.core import OperationError
from test_step_export_jobs import StepExportJobTests
from kurtshape import step_capture as candidate

ORIGINAL_FINGERPRINTS = worker_module.world_fingerprints
ORIGINAL_ROUNDTRIP = worker_module.world_roundtrip_stable
MAP_FIELDS = ("ElementMap", "ElementReverseMap", "ElementMapVersion", "ElementMapSize")


def map_fields(shape):
    return {name: copy.deepcopy(getattr(shape, name)) for name in MAP_FIELDS}


class ShapeReadProbe:
    """Delegate all geometry to an actual detached native shape."""
    def __init__(self, shape, fail=None, calls=None):
        self.shape, self.fail = shape, fail
        self.calls = [] if calls is None else calls

    def copy(self):
        return ShapeReadProbe(self.shape.copy(), self.fail, self.calls)

    def __getattr__(self, name):
        if name in MAP_FIELDS:
            self.calls.append(name)
            if name == self.fail:
                raise RuntimeError("injected native map read failure: " + name)
        return getattr(self.shape, name)


class StepDigestCandidateTests(unittest.TestCase):
    setUp = StepExportJobTests.setUp
    tearDown = StepExportJobTests.tearDown
    doc = StepExportJobTests.doc
    call = StepExportJobTests.call
    plate = StepExportJobTests.plate
    stable_result = StepExportJobTests.stable_result
    mutate_result = StepExportJobTests.mutate_result
    invariant = StepExportJobTests.invariant
    worker = StepExportJobTests.worker
    prepare = StepExportJobTests.prepare
    completed_transport = StepExportJobTests.completed_transport
    assert_unpublished = StepExportJobTests.assert_unpublished

    def admit(self, names):
        key = self.core.snapshot_key(self.doc)
        stable, ticket = candidate.roundtrip_digest(self.core, self.doc, names, key)
        return key, stable, ticket

    def rows(self, names, key, ticket):
        return candidate.initial_world_fingerprints(self.core, self.doc, names, key, ticket)

    @contextmanager
    def integrated(self, after_admission=None):
        """Exercise production admission/initial calls and independent final guard."""
        calls = []
        self.assertIn("roundtrip_digest", self.core.prepare_step_export.__code__.co_names)
        original_admission = candidate.roundtrip_digest
        original_initial = candidate.initial_world_fingerprints
        def capture_admission(*args, **kwargs):
            result = original_admission(*args, **kwargs)
            calls.append("admission")
            if result[0] and after_admission:
                after_admission()
            return result
        def capture_initial(*args, **kwargs):
            calls.append("initial")
            return original_initial(*args, **kwargs)
        def full_final(*args, **kwargs):
            calls.append("full-final")
            return ORIGINAL_FINGERPRINTS(*args, **kwargs)
        with patch.object(candidate, "roundtrip_digest", capture_admission), \
                patch.object(candidate, "initial_world_fingerprints", capture_initial), \
                patch.object(worker_module, "world_fingerprints", full_final):
            yield calls

    def test_single_native_fingerprint_exact_and_source_preserved(self):
        target = self.stable_result()
        target.Placement = App.Placement(App.Vector(7, 11, 13), App.Rotation())
        self.doc.recompute()
        self.core.sync(self.doc)
        names = [target.Name]
        before = self.invariant()
        key, stable, ticket = self.admit(names)
        self.assertTrue(stable)
        self.assertIsNotNone(ticket)
        actual = self.rows(names, key, ticket)
        self.assertEqual(actual, ORIGINAL_FINGERPRINTS(self.doc, names))
        self.assertTrue(ticket.consumed)
        self.assertEqual(ticket.sha256, actual[0]["brep_sha256"])
        self.assertEqual(self.invariant(), before)
        with self.assertRaises(OperationError):
            self.rows(names, key, ticket)

    def test_fresh_copy_map_properties_do_not_change_during_native_serialization(self):
        result = self.stable_result()
        body = self.plate()
        for target in (result, body):
            with self.subTest(target=target.Name):
                fresh = assembly.global_shape(target).copy()
                before = map_fields(fresh)
                raw = fresh.exportBrepToString()
                self.assertTrue(raw)
                self.assertEqual(map_fields(fresh), before)
                other = assembly.global_shape(target).copy()
                self.assertEqual(map_fields(other), before)
                self.assertEqual(map_fields(other), map_fields(fresh))

    def test_selected_and_multiple_native_results_match_original_order(self):
        first = self.stable_result()
        second = self.doc.addObject("Part::Feature", "SecondExportSolid")
        second.Shape = Part.makeBox(2, 3, 4, App.Vector(40, 10, 2))
        self.doc.recompute()
        self.core.sync(self.doc)
        before = self.invariant()
        for names in ([second.Name], [first.Name, second.Name], [second.Name, first.Name]):
            with self.subTest(names=names):
                key, stable, ticket = self.admit(names)
                self.assertEqual(stable, ORIGINAL_ROUNDTRIP(self.doc, names))
                self.assertTrue(stable)
                if len(names) > 1:
                    self.assertIsNone(ticket, "Multi-target work must use the incumbent path")
                self.assertEqual(self.rows(names, key, ticket), ORIGINAL_FINGERPRINTS(self.doc, names))
        selected = self.core._geometry_check_targets(self.doc, second.Name)
        self.assertEqual([obj.Name for obj in selected], [second.Name])
        self.assertEqual(self.invariant(), before)

    def test_real_unstable_pad_retains_signed_zero_fallback_without_field_reads(self):
        body = self.plate()
        names = [body.Name]
        before = self.invariant()
        raw = assembly.global_shape(body).copy().exportBrepToString()
        restored = Part.Shape()
        restored.importBrepFromString(raw)
        restored_raw = restored.exportBrepToString()
        self.assertFalse(ORIGINAL_ROUNDTRIP(self.doc, names), "Native unstable Pad is the positive control")
        self.assertNotEqual(assembly.canonical_brep(raw), assembly.canonical_brep(restored_raw))
        self.assertTrue("-0" in raw or "-0" in restored_raw)
        reads = []
        original_global = assembly.global_shape
        with patch.object(assembly, "global_shape", side_effect=lambda obj: ShapeReadProbe(original_global(obj), "ElementMap", reads)), \
                patch.object(core_module, "_native_value", side_effect=AssertionError("Unstable admission must not read metadata")):
            _key, stable, ticket = self.admit(names)
        self.assertFalse(stable)
        self.assertIsNone(ticket)
        self.assertEqual(reads, [])
        self.assertEqual(self.invariant(), before)

    def test_successful_admission_preserves_metadata_and_each_map_read_error(self):
        target = self.stable_result()
        names = [target.Name]
        before = self.invariant()
        key, stable, ticket = self.admit(names)
        self.assertTrue(stable)
        with patch.object(core_module, "_native_value", side_effect=RuntimeError("metadata unavailable")):
            with self.assertRaisesRegex(RuntimeError, "metadata unavailable"):
                ORIGINAL_FINGERPRINTS(self.doc, names)
            with self.assertRaisesRegex(RuntimeError, "metadata unavailable"):
                self.rows(names, key, ticket)
        original_global = assembly.global_shape
        for field in MAP_FIELDS:
            with self.subTest(field=field):
                key, stable, ticket = self.admit(names)
                self.assertTrue(stable)
                with patch.object(assembly, "global_shape", side_effect=lambda obj, field=field: ShapeReadProbe(original_global(obj), field)):
                    with self.assertRaisesRegex(RuntimeError, "injected native map read failure"):
                        ORIGINAL_FINGERPRINTS(self.doc, names)
                    with self.assertRaisesRegex(RuntimeError, "injected native map read failure"):
                        self.rows(names, key, ticket)
        self.assertEqual(self.invariant(), before)

    def test_mutation_after_admission_rejects_even_when_snapshot_key_is_forced_old(self):
        target = self.stable_result()
        names = [target.Name]
        key, stable, ticket = self.admit(names)
        self.assertTrue(stable)
        target.Shape = Part.makeBox(20, 10, 9)
        self.doc.recompute()
        changed = self.invariant()
        with patch.object(self.core, "snapshot_key", return_value=key):
            with self.assertRaises(OperationError) as failed:
                self.rows(names, key, ticket)
        self.assertEqual(failed.exception.code, "stale_step_export")
        self.assertEqual(self.invariant(), changed)

    def test_native_mutation_during_fingerprint_metadata_read_rejects(self):
        target = self.stable_result()
        names = [target.Name]
        key, stable, ticket = self.admit(names)
        self.assertTrue(stable)
        original = core_module._native_value
        changed = []
        def value(native):
            returned = original(native)
            if not changed:
                changed.append(True)
                target.Shape = Part.makeBox(20, 10, 9)
                self.doc.recompute()
            return returned
        with patch.object(core_module, "_native_value", side_effect=value), \
                patch.object(self.core, "snapshot_key", return_value=key):
            with self.assertRaises(OperationError) as failed:
                self.rows(names, key, ticket)
        self.assertEqual(changed, [True])
        self.assertEqual(failed.exception.code, "stale_step_export")
        self.assertAlmostEqual(target.Shape.Volume, 20 * 10 * 9)

    def test_actual_controller_prepare_keeps_full_final_guard_and_source(self):
        target = self.stable_result()
        before = self.invariant()
        with self.integrated() as calls:
            bundle = self.prepare()
        self.assertEqual(calls, ["admission", "initial", "full-final"])
        self.assertEqual(bundle["envelope"]["target_fingerprints"], ORIGINAL_FINGERPRINTS(self.doc, [target.Name]))
        self.assertEqual(self.invariant(), before)
        self.assertIsNone(bundle["worker"].process)

    def test_actual_controller_reentrant_admission_never_captures_stale_digest(self):
        target = self.stable_result()
        def mutate():
            target.Shape = Part.makeBox(20, 10, 9)
            self.doc.recompute()
        with self.integrated(after_admission=mutate):
            with self.assertRaises(OperationError) as failed:
                self.prepare()
        self.assertEqual(failed.exception.code, "stale_step_export")
        self.assertTrue(self.workers)
        for worker in self.workers:
            self.assertIsNone(worker.process)
            self.assertTrue(worker.closed)
        self.assertFalse((self.folder / "accepted.step").exists())

    def test_actual_final_topology_placement_membership_guards_with_forced_old_key(self):
        with self.integrated():
            StepExportJobTests.test_actual_topology_placement_and_membership_changes_reject_even_with_old_key(self)

    def test_actual_final_callback_mutation_cannot_publish(self):
        with self.integrated():
            StepExportJobTests.test_same_document_mutation_in_final_callback_cannot_publish(self)


    def test_metadata_revision_change_rejects_even_with_old_key(self):
        target = self.stable_result()
        names = [target.Name]
        key, stable, ticket = self.admit(names)
        self.assertTrue(stable)
        state = self.core.observer.state(self.doc)
        clock = (state["generation"], state["change_serial"])
        self.core._meta(self.doc).Revision = "explicit-revision-only-mutation"
        self.assertEqual((state["generation"], state["change_serial"]), clock)
        with patch.object(self.core, "snapshot_key", return_value=key):
            with self.assertRaises(OperationError) as failed:
                self.rows(names, key, ticket)
        self.assertEqual(failed.exception.code, "stale_step_export")
        self.assertEqual(self.core._meta(self.doc).Revision, "explicit-revision-only-mutation")

    def test_ticket_rejects_wrong_controller_document_target_and_key(self):
        from dataclasses import replace
        target = self.stable_result()
        names = [target.Name]
        other = App.newDocument("StepDigestOther")
        try:
            for kind in ("controller", "document", "target", "key"):
                with self.subTest(kind=kind):
                    key, stable, ticket = self.admit(names)
                    self.assertTrue(stable)
                    owner = object() if kind == "controller" else self.core
                    document = other if kind == "document" else self.doc
                    target_ids = ["WrongTarget"] if kind == "target" else names
                    supplied_key = replace(key, serial=key.serial + 1) if kind == "key" else key
                    with self.assertRaises(OperationError) as failed:
                        candidate.initial_world_fingerprints(owner, document, target_ids, supplied_key, ticket)
                    self.assertEqual(failed.exception.code, "stale_step_export")
                    self.assertTrue(ticket.consumed)
        finally:
            App.closeDocument(other.Name)

    def test_native_mutation_during_map_read_rejects_with_old_key(self):
        target = self.stable_result()
        names = [target.Name]
        key, stable, ticket = self.admit(names)
        self.assertTrue(stable)
        original_global = assembly.global_shape
        original_read = ShapeReadProbe.__getattr__
        changed = []
        def read(proxy, name):
            value = original_read(proxy, name)
            if name == "ElementMap" and not changed:
                changed.append(True)
                target.Shape = Part.makeBox(20, 10, 9)
                self.doc.recompute()
            return value
        with patch.object(assembly, "global_shape", side_effect=lambda obj: ShapeReadProbe(original_global(obj))), \
                patch.object(ShapeReadProbe, "__getattr__", read), \
                patch.object(self.core, "snapshot_key", return_value=key):
            with self.assertRaises(OperationError) as failed:
                self.rows(names, key, ticket)
        self.assertEqual(failed.exception.code, "stale_step_export")
        self.assertEqual(changed, [True])
        self.assertAlmostEqual(target.Shape.Volume, 20 * 10 * 9)

    def test_missing_key_uses_unchanged_fingerprint_oracle(self):
        target = self.stable_result()
        names = [target.Name]
        before = self.invariant()
        stable, ticket = candidate.roundtrip_digest(self.core, self.doc, names, None)
        self.assertTrue(stable)
        self.assertIsNone(ticket)
        with patch.object(worker_module, "world_fingerprints", wraps=ORIGINAL_FINGERPRINTS) as original:
            actual = candidate.initial_world_fingerprints(self.core, self.doc, names, None, ticket)
        original.assert_called_once_with(self.doc, names)
        self.assertEqual(actual, ORIGINAL_FINGERPRINTS(self.doc, names))
        self.assertEqual(self.invariant(), before)

    def test_ticket_holds_only_bounded_existing_references_and_digest(self):
        from dataclasses import fields
        target = self.stable_result()
        key, stable, ticket = self.admit([target.Name])
        self.assertTrue(stable)
        expected = {"controller", "document", "target", "metadata", "state", "index", "key",
                    "document_name", "document_id", "name", "sha256", "consumed"}
        self.assertEqual({field.name for field in fields(ticket)}, expected)
        self.assertIs(ticket.controller, self.core)
        self.assertIs(ticket.document, self.doc)
        self.assertIs(ticket.target, target)
        self.assertIs(ticket.metadata, self.core._meta(self.doc))
        self.assertIs(ticket.state, self.core.observer.states[self.doc.Name])
        self.assertIs(ticket.index, ticket.state["index"])
        self.assertIs(ticket.key, key)
        self.assertEqual(ticket.document_name, self.doc.Name)
        self.assertEqual(ticket.document_id, self.core.identifier(self.doc))
        self.assertEqual(ticket.name, target.Name)
        self.assertRegex(ticket.sha256, r"^[0-9a-f]{64}$")
        self.assertIs(ticket.consumed, False)

    def test_reopened_pad_nonempty_native_maps_preserve_successful_digest(self):
        target = self.plate()
        target.Placement = App.Placement(App.Vector(7, 11, 13), App.Rotation())
        self.doc.recompute()
        self.core.sync(self.doc)
        self.state = self.core.inspect(self.doc, measure=False)
        saved = self.folder / "mapped-admission-source.FCStd"
        self.call("save", path=str(saved))
        saved_bytes = saved.read_bytes()
        App.closeDocument(self.doc.Name)
        self.call("open", path=str(saved))
        target = self.doc.Body
        names = [target.Name]
        actual = assembly.global_shape(target).copy()
        self.assertTrue(dict(actual.ElementMap), "Reopened native Pad must provide a genuinely nonempty forward map")
        self.assertTrue(dict(actual.ElementReverseMap), "Reopened native Pad must provide a genuinely nonempty reverse map")
        self.assertTrue(ORIGINAL_ROUNDTRIP(self.doc, names), "A mapped fixture must satisfy unchanged native admission")
        before = self.invariant()
        key, stable, ticket = self.admit(names)
        self.assertTrue(stable)
        self.assertIsNotNone(ticket)
        optimized = self.rows(names, key, ticket)
        self.assertTrue(optimized[0]["element_map"])
        self.assertTrue(optimized[0]["element_reverse_map"])
        self.assertEqual(optimized, ORIGINAL_FINGERPRINTS(self.doc, names))
        self.assertEqual(self.invariant(), before)
        self.assertEqual(saved.read_bytes(), saved_bytes)

    def test_nonfinite_native_map_rejected_by_unchanged_json_boundary(self):
        target = self.stable_result()
        names = [target.Name]
        key, stable, ticket = self.admit(names)
        self.assertTrue(stable)
        original_global = assembly.global_shape
        original_read = ShapeReadProbe.__getattr__
        def read(proxy, name):
            if name == "ElementMap":
                return {"injected_nonfinite": float("nan")}
            return original_read(proxy, name)
        with patch.object(assembly, "global_shape", side_effect=lambda obj: ShapeReadProbe(original_global(obj))), \
                patch.object(ShapeReadProbe, "__getattr__", read):
            with self.assertRaises(ValueError) as oracle:
                ORIGINAL_FINGERPRINTS(self.doc, names)
            with self.assertRaises(ValueError) as optimized:
                self.rows(names, key, ticket)
        self.assertEqual(str(optimized.exception), str(oracle.exception))


if __name__ == "__main__":
    unittest.main()
