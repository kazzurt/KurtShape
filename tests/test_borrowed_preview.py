"""Borrowed immutable worker archives preserve exact native preview behavior."""
from pathlib import Path
import os
import sys
import time
import unittest
from unittest.mock import patch
import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
from kurtshape.core import Controller, OperationError, intent_signature, native_intent
from kurtshape.extrusion_preview import (ExtrusionEvaluator, ImmutablePreviewSnapshot,
                                         _normalize_preview_source, _load_preview_clone)
from kurtshape.preview_worker import (NativePreviewWorker, _attach_preview_document,
                                      _snapshot_equivalence_state)


class BorrowedPreviewTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="borrowed-preview-archive-")
        self.core = Controller()
        self.state = None
        self.previews = []
        self.call("new", name="Borrowed preview archive")

    def tearDown(self):
        for preview in self.previews:
            preview.close()
        self.core.close()
        for name in set(App.listDocuments()) - self.names:
            App.closeDocument(name)

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def call(self, op, **arguments):
        request = dict(op=op, **arguments)
        if op != "new":
            request.update(document_id=self.state["document_id"], expected_revision=self.state["revision"])
        response = self.core.dispatch(request)
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        return self.state

    def fixture(self):
        self.call("sketch_rectangle", id="Plate", width=20, height=10)
        self.call("pad", id="Pad", profile="Plate", length=6)
        top = "Face" + str(next(index + 1 for index, face in enumerate(self.doc.Pad.Shape.Faces)
                                 if abs(face.CenterOfMass.z - 6) < 1e-7))
        self.call("sketch_circle", id="Profile", x=10, y=5, diameter=4,
                  support={"feature": "Pad", "subelement": top})
        return dict(op="pad", profile="Profile", length=2)

    def preview(self, snapshot=None, core=None, document=None):
        core, document = core or self.core, document or self.doc
        evaluator = ExtrusionEvaluator(core, document, core._meta(document).Revision, snapshot_source=snapshot)
        self.previews.append(evaluator)
        return evaluator

    def archive(self, name="preview-source.FCStd"):
        path = self.folder / name
        self.doc.saveCopy(str(path))
        self.core.sync(self.doc)
        return path

    @staticmethod
    def native_shapes(document):
        rows = {}
        for obj in document.Objects:
            for name in obj.PropertiesList:
                if "Shape" not in obj.getTypeIdOfProperty(name):
                    continue
                shape = getattr(obj, name)
                rows[(obj.Name, name)] = {
                    "brep": None if shape.isNull() else shape.exportBrepToString(),
                    "version": shape.ElementMapVersion, "size": shape.ElementMapSize,
                    "native_version": obj.getElementMapVersion(name),
                    "map": dict(shape.ElementMap), "reverse_map": dict(shape.ElementReverseMap),
                    "mapped_identity": {mapped: shape.getElement(mapped).isSame(shape.getElement(legacy))
                                        for mapped, legacy in shape.ElementMap.items()}}
        return rows

    def test_borrowed_evaluator_matches_owned_brep_maps_and_never_recaptures(self):
        proposal = self.fixture()
        owned = self.preview()
        reference = owned.evaluate(proposal)
        self.assertTrue(reference.valid, reference.error)
        self.assertEqual(owned.snapshot_captures, 1)
        path = self.archive()
        snapshot = ImmutablePreviewSnapshot.bind(self.core, self.doc, path)
        before = (intent_signature(self.doc), self.doc.UndoCount, self.doc.RedoCount,
                  self.core._meta(self.doc).Revision, path.read_bytes())
        borrowed = self.preview(snapshot)
        result = borrowed.evaluate(proposal)
        self.assertTrue(result.valid, result.error)
        self.assertEqual(result.shape.exportBrepToString(), reference.shape.exportBrepToString())
        self.assertEqual(dict(result.shape.ElementMap), dict(reference.shape.ElementMap))
        self.assertEqual(dict(result.shape.ElementReverseMap), dict(reference.shape.ElementReverseMap))
        self.assertEqual(result.material_shape.exportBrepToString(), reference.material_shape.exportBrepToString())
        self.assertEqual(borrowed.snapshot_captures, 0)
        self.assertEqual(result.phase_milliseconds["snapshot"], 0)
        self.assertIsNone(borrowed._temporary)
        cached = borrowed.evaluate(dict(proposal, length="0.2 cm"))
        self.assertTrue(cached.valid, cached.error)
        self.assertTrue(cached.cached)
        self.assertEqual(borrowed.evaluations, 1)
        self.assertEqual(borrowed.snapshot_captures, 0)
        borrowed.close()
        self.assertEqual((intent_signature(self.doc), self.doc.UndoCount, self.doc.RedoCount,
                          self.core._meta(self.doc).Revision, path.read_bytes()), before)

    def test_borrowed_snapshot_tamper_rejected_before_cached_result(self):
        proposal = self.fixture()
        path = self.archive()
        borrowed = self.preview(ImmutablePreviewSnapshot.bind(self.core, self.doc, path))
        self.assertTrue(borrowed.evaluate(proposal).valid)
        with path.open("ab") as stream:
            stream.write(b"changed immutable archive")
        result = borrowed.evaluate(proposal)
        self.assertFalse(result.valid)
        self.assertEqual(result.error["code"], "invalid_preview_snapshot")
        self.assertEqual(borrowed.evaluations, 1)
        self.assertEqual(borrowed.snapshot_captures, 0)

    def test_lineage_fillet_borrowed_and_owned_preview_match_native_acceptance(self):
        self.call("sketch_rectangle", id="Plate", width=20, height=12)
        self.call("pad", id="Pad", profile="Plate", length=6)
        edge = {"kind": "closest", "point": [0, 0, 3],
                "query": {"kind": "geometry", "geometry": "line",
                          "query": {"kind": "created_by", "feature": "Pad", "entity_type": "edge"}}}
        proposal = dict(op="fillet", edges=[edge], radius=1)
        owned = self.preview().evaluate(proposal)
        self.assertTrue(owned.valid, owned.error)
        path = self.archive()
        evaluator = self.preview(ImmutablePreviewSnapshot.bind(self.core, self.doc, path))
        borrowed = evaluator.evaluate(proposal)
        self.assertTrue(borrowed.valid, borrowed.error)
        self.assertEqual(evaluator.snapshot_captures, 0)
        self.call("fillet", id="AcceptedRound", edges=[edge], radius=1)
        accepted = self.doc.Body.Shape
        self.assertTrue(accepted.isValid())
        for result in (owned, borrowed):
            self.assertAlmostEqual(result.shape.Volume, accepted.Volume, places=7)
            self.assertLess(result.shape.cut(accepted).Volume, 1e-7)
            self.assertLess(accepted.cut(result.shape).Volume, 1e-7)

    def test_borrowed_snapshot_rejects_wrong_document_revision_and_generation(self):
        self.fixture()
        snapshot = ImmutablePreviewSnapshot.bind(self.core, self.doc, self.archive())
        with self.assertRaises(OperationError):
            snapshot.validate(self.core, object(), snapshot.revision)
        with self.assertRaises(OperationError):
            snapshot.validate(self.core, self.doc, "foreign revision")
        self.doc.Pad.touch()
        self.doc.recompute()
        result = self.preview(snapshot).evaluate(dict(op="pad", profile="Profile", length=2))
        self.assertFalse(result.valid)
        self.assertEqual(result.error["code"], "stale_preview_snapshot")

    def test_source_and_operation_clone_normalization_preserve_complete_native_maps(self):
        proposal = self.fixture()
        path = self.archive()
        other = Controller()
        document = App.openDocument(str(path), True, True)
        try:
            before = self.native_shapes(document)
            flags = {obj.Name: tuple(obj.State) for obj in document.Objects}
            generation = other.observer.state(document)["generation"]
            self.assertEqual(document.Body._ElementMapVersion, "")
            _normalize_preview_source(other, document)
            self.assertEqual(self.native_shapes(document), before)
            self.assertEqual({obj.Name: tuple(obj.State) for obj in document.Objects}, flags)
            self.assertEqual(other.observer.state(document)["generation"], generation)
            self.assertTrue(document.Body._ElementMapVersion)
            self.assertEqual(document.Body._ElementMapVersion, document.Body.Shape.ElementMapVersion)
            expected_maps = self.native_shapes(document)
            phases = {}
            snapshot = _attach_preview_document(other, document, path,
                                                 ImmutablePreviewSnapshot._identity(path), phases)
            self.assertIsNotNone(snapshot)
            equivalence = _snapshot_equivalence_state(other, document)
            self.assertEqual(equivalence["maps"][("Body", "Shape")],
                             (document.Body.Shape.ElementMapVersion, document.Body.Shape.ElementMapSize))
            model_operation = other._model_operation
            captured = []
            def operation(clone, request):
                captured.append(self.native_shapes(clone))
                self.assertEqual(clone.Body._ElementMapVersion, document.Body._ElementMapVersion)
                return model_operation(clone, request)
            with patch.object(other, "_model_operation", side_effect=operation):
                result = self.preview(snapshot, other, document).evaluate(proposal)
            self.assertTrue(result.valid, result.error)
            self.assertEqual(captured, [expected_maps])
            self.assertEqual(self.native_shapes(document), expected_maps)
        finally:
            other.close()
            App.closeDocument(document.Name)
            App.setActiveDocument(self.doc.Name)

    def test_attachment_changes_and_uncertain_reads_use_owned_fallback(self):
        proposal = self.fixture()
        path = self.archive()
        def schema(core, document):
            core._meta(document).addProperty("App::PropertyString", "ExtraPreviewSchema")
        changes = {
            "intent": lambda core, doc: setattr(doc.Pad, "Label", "Changed during attach"),
            "metadata": lambda core, doc: setattr(core._meta(doc), "SourceMapping", '{"changed":true}'),
            "schema": schema,
            "generation": lambda core, doc: core.observer.state(doc).__setitem__("generation", 987654),
            "map_marker": lambda core, doc: setattr(doc.Body, "_ElementMapVersion", "changed-marker"),
        }
        for reason, change in changes.items():
            with self.subTest(reason=reason):
                other = Controller()
                document = App.openDocument(str(path), True, True)
                try:
                    attach = other.attach
                    def changed_attach(doc):
                        attach(doc)
                        change(other, doc)
                    with patch.object(other, "attach", side_effect=changed_attach):
                        snapshot = _attach_preview_document(other, document, path,
                                                             ImmutablePreviewSnapshot._identity(path), {})
                    self.assertIsNone(snapshot)
                finally:
                    other.close()
                    App.closeDocument(document.Name)
        other = Controller()
        document = App.openDocument(str(path), True, True)
        try:
            with patch("kurtshape.preview_worker._snapshot_equivalence_state", side_effect=RuntimeError("unknown field")):
                snapshot = _attach_preview_document(other, document, path,
                                                     ImmutablePreviewSnapshot._identity(path), {})
            self.assertIsNone(snapshot)
            evaluator = self.preview(snapshot, other, document)
            result = evaluator.evaluate(proposal)
            self.assertTrue(result.valid, result.error)
            self.assertEqual(evaluator.snapshot_captures, 1)
        finally:
            other.close()
            App.closeDocument(document.Name)
            App.setActiveDocument(self.doc.Name)

    def test_archive_changed_during_attach_cannot_be_borrowed(self):
        self.fixture()
        path = self.archive()
        identity = ImmutablePreviewSnapshot._identity(path)
        other = Controller()
        document = App.openDocument(str(path), True, True)
        try:
            attach = other.attach
            def changed_attach(doc):
                attach(doc)
                with path.open("ab") as stream:
                    stream.write(b"changed after opening")
            with patch.object(other, "attach", side_effect=changed_attach):
                with self.assertRaises(OperationError) as failed:
                    _attach_preview_document(other, document, path, identity, {})
            self.assertEqual(failed.exception.code, "invalid_preview_snapshot")
        finally:
            other.close()
            App.closeDocument(document.Name)
            App.setActiveDocument(self.doc.Name)

    def test_missing_project_metadata_uses_owned_capture_after_attachment(self):
        proposal = self.fixture()
        path = self.archive()
        other = Controller()
        document = App.openDocument(str(path), True, True)
        try:
            document.removeObject("KurtShapeProject")
            document.saveCopy(str(path))
            self.assertIsNone(document.getObject("KurtShapeProject"))
            snapshot = _attach_preview_document(other, document, path,
                                                 ImmutablePreviewSnapshot._identity(path), {})
            self.assertIsNone(snapshot)
            self.assertIsNotNone(document.getObject("KurtShapeProject"))
            evaluator = self.preview(snapshot, other, document)
            result = evaluator.evaluate(proposal)
            self.assertTrue(result.valid, result.error)
            self.assertEqual(evaluator.snapshot_captures, 1)
        finally:
            other.close()
            App.closeDocument(document.Name)
            App.setActiveDocument(self.doc.Name)

    def test_unreadable_authored_field_cannot_prove_attachment_equivalence(self):
        self.fixture()
        path = self.archive()
        other = Controller()
        document = App.openDocument(str(path), True, True)
        def incomplete_intent(doc, objects=None):
            rows = native_intent(doc, objects)
            for row in rows:
                if row["id"] == "Pad":
                    row["properties"].pop("Length")
            return rows
        try:
            with patch("kurtshape.core.native_intent", side_effect=incomplete_intent):
                snapshot = _attach_preview_document(other, document, path,
                                                     ImmutablePreviewSnapshot._identity(path), {})
            self.assertIsNone(snapshot)
        finally:
            other.close()
            App.closeDocument(document.Name)
            App.setActiveDocument(self.doc.Name)

    def test_archive_tampered_during_clone_open_is_rejected_before_modeling(self):
        proposal = self.fixture()
        path = self.archive()
        borrowed = self.preview(ImmutablePreviewSnapshot.bind(self.core, self.doc, path))
        def tampered_open(*arguments):
            clone = _load_preview_clone(*arguments)
            with path.open("ab") as stream:
                stream.write(b"changed during native open")
            return clone
        with patch("kurtshape.extrusion_preview._load_preview_clone", side_effect=tampered_open), \
                patch.object(self.core, "_model_operation") as model:
            result = borrowed.evaluate(proposal)
        self.assertFalse(result.valid)
        self.assertEqual(result.error["code"], "invalid_preview_snapshot")
        model.assert_not_called()
        self.assertEqual(borrowed.evaluations, 0)
        self.assertEqual(borrowed.snapshot_captures, 0)

    def test_native_loader_cannot_return_and_delete_the_source_document(self):
        proposal = self.fixture()
        path = self.archive()
        borrowed = self.preview(ImmutablePreviewSnapshot.bind(self.core, self.doc, path))
        before = (self.doc.Name, self.doc.FileName, intent_signature(self.doc), self.native_shapes(self.doc))
        with patch("kurtshape.extrusion_preview._load_preview_clone", return_value=self.doc), \
                patch.object(self.core, "_model_operation") as model:
            result = borrowed.evaluate(proposal)
        self.assertFalse(result.valid)
        self.assertEqual(result.error["code"], "invalid_preview_clone")
        model.assert_not_called()
        self.assertIs(App.getDocument(self.doc.Name), self.doc)
        self.assertEqual((self.doc.Name, self.doc.FileName, intent_signature(self.doc), self.native_shapes(self.doc)), before)

    def worker(self):
        executable = Path(App.getHomePath()) / "bin" / ("python.exe" if os.name == "nt" else "python")
        worker = NativePreviewWorker(executable, ROOT / "runtime", timeout=30)
        def cleanup():
            worker.close()
            if worker.process is not None:
                worker.process.wait(timeout=10)
        self.addCleanup(cleanup)
        return worker

    def response(self, worker):
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            response = worker.poll()
            if response is not None:
                return response
            time.sleep(.02)
        self.fail("Private preview worker exceeded its bounded test timeout")

    def test_actual_worker_reuses_received_archive_without_child_serialization(self):
        proposal = self.fixture()
        reference = self.preview().evaluate(proposal)
        self.assertTrue(reference.valid, reference.error)
        worker = self.worker()
        before = (intent_signature(self.doc), self.core._meta(self.doc).Revision,
                  self.doc.UndoCount, self.doc.RedoCount, self.native_shapes(self.doc))
        self.doc.saveCopy(str(worker.snapshot))
        archive = worker.snapshot.read_bytes()
        worker.submit(1, proposal)
        response = self.response(worker)
        self.assertTrue(response["valid"], response["error"])
        self.assertTrue(response["snapshot_reused"])
        self.assertEqual(response["snapshot_capture_delta"], 0)
        self.assertEqual(response["evaluation_delta"], 1)
        self.assertEqual(response["phase_milliseconds"]["snapshot"], 0)
        self.assertAlmostEqual(response["measurements"]["volume_mm3"], reference.shape.Volume, places=6)
        self.assertAlmostEqual(response["measurements"]["material_volume_mm3"], reference.material_shape.Volume, places=6)
        self.assertTrue(response["mesh"]["triangles"])
        for name in ("source_open", "source_normalize", "source_attach", "source_equivalence", "load",
                     "clone_normalize", "model", "recompute", "cleanup", "render"):
            self.assertGreaterEqual(response["phase_milliseconds"][name], 0)
        worker.submit(2, dict(proposal, length="0.2 cm"))
        cached = self.response(worker)
        self.assertTrue(cached["cached"])
        self.assertTrue(cached["snapshot_reused"])
        self.assertEqual(cached["evaluation_delta"], 0)
        self.assertEqual(cached["snapshot_capture_delta"], 0)
        self.assertNotIn("source_open", cached["phase_milliseconds"])
        worker.submit(3, dict(proposal, length=3))
        changed = self.response(worker)
        self.assertTrue(changed["valid"], changed["error"])
        self.assertEqual(changed["evaluation_delta"], 1)
        self.assertEqual(changed["snapshot_capture_delta"], 0)
        self.assertEqual(worker.snapshot.read_bytes(), archive)
        self.assertEqual((intent_signature(self.doc), self.core._meta(self.doc).Revision,
                          self.doc.UndoCount, self.doc.RedoCount, self.native_shapes(self.doc)), before)

    def test_actual_worker_hasher_migration_retains_owned_serialization_fallback(self):
        proposal = self.fixture()
        worker = self.worker()
        path = self.archive("legacy-hasher-source.FCStd")
        native = App.openDocument(str(path), True, True)
        try:
            native.UseHasher = True
            native.saveCopy(str(worker.snapshot))
        finally:
            App.closeDocument(native.Name)
            App.setActiveDocument(self.doc.Name)
        worker.submit(1, proposal)
        response = self.response(worker)
        self.assertTrue(response["valid"], response["error"])
        self.assertFalse(response["snapshot_reused"])
        self.assertEqual(response["snapshot_capture_delta"], 1)
        self.assertGreater(response["phase_milliseconds"]["snapshot"], 0)
        self.assertTrue(response["mesh"]["triangles"])
