"""Lazy native selector preparation retains the complete preparation oracle."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
from kurtshape import assembly, document_index, selectors, studio
from kurtshape.core import Controller, OperationError


class SelectorPreparationTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="lazy-selector-preparation-")
        self.core = Controller()
        self.state = self.core.dispatch({"op": "new", "name": "Selector preparation", "measure": False})["result"]
        self.call("sketch_rectangle", id="Profile", width=20, height=10)
        self.call("pad", id="Pad", profile="Profile", length=6)

    def tearDown(self):
        self.core.close()
        for name in set(App.listDocuments()) - self.names:
            App.closeDocument(name)

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def call(self, op, **arguments):
        response = self.core.dispatch({"op": op, "document_id": self.state["document_id"],
            "expected_revision": self.state["revision"], "measure": False, **arguments})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        return self.state

    def parity(self, selector, before=None):
        result = selectors.resolve(self.doc, selector, before)
        self.assertEqual(result, selectors._resolve_full(self.doc, selector, before))
        return result

    def test_literal_reads_only_requested_entities_and_reuses_membership(self):
        index = document_index.get(self.doc)
        index.invalidate(structure=True)
        before = dict(index.counts)
        for element in ("Face1", "Edge1"):
            query = {"feature": "Pad", "subelement": element}
            expected = self.parity(query)
            self.assertTrue(expected)
            self.assertEqual(selectors.resolve(self.doc, query), expected)
        self.assertEqual(index.counts.get("selector_row_builds", 0), before.get("selector_row_builds", 0))
        self.assertEqual(index.counts.get("selector_map_owner_builds", 0), before.get("selector_map_owner_builds", 0))
        self.assertEqual(index.counts["selector_membership_builds"] - before.get("selector_membership_builds", 0), 1)
        self.assertEqual(index.counts["selector_literal_reads"] - before.get("selector_literal_reads", 0), 2)

    def test_vertex_literal_preserves_existing_native_summary_error(self):
        query = {"feature": "Pad", "subelement": "Vertex1"}
        with self.assertRaises(AttributeError) as lazy:
            selectors.resolve(self.doc, query)
        with self.assertRaises(AttributeError) as full:
            selectors._resolve_full(self.doc, query)
        self.assertEqual(str(lazy.exception), str(full.exception))

    def test_global_rows_are_lazy_and_owner_maps_wait_for_creator_lineage(self):
        index = document_index.get(self.doc)
        index.invalidate(structure=True)
        before = dict(index.counts)
        self.assertEqual(len(self.parity({"kind": "all"})), 6)
        self.assertEqual(len(self.parity({"kind": "owned_by", "part": "Body"})), 6)
        self.assertEqual(index.counts["selector_row_builds"] - before.get("selector_row_builds", 0), 1)
        self.assertEqual(index.counts.get("selector_map_owner_builds", 0), before.get("selector_map_owner_builds", 0))
        query = {"kind": "created_by", "feature": "Pad", "cap": "end"}
        self.assertEqual(len(self.parity(query)), 1)
        self.assertEqual(index.counts["selector_map_owner_builds"] - before.get("selector_map_owner_builds", 0), 1)
        self.assertGreater(index.counts["selector_map_entries"] - before.get("selector_map_entries", 0), 0)
        counts = dict(index.counts)
        self.assertEqual(len(selectors.resolve(self.doc, query)), 1)
        self.assertEqual(index.counts, counts)

    def test_historical_body_and_sketch_literal_identity_match_full_rows(self):
        top = "Face" + str(next(i + 1 for i, face in enumerate(self.doc.Pad.Shape.Faces)
                                if abs(face.CenterOfMass.z - 6) < 1e-7))
        self.call("sketch_circle", id="Hole", x=10, y=5, diameter=4,
                  support={"feature": "Pad", "subelement": top})
        self.call("pocket", id="Pocket", profile="Hole", length=2, through_all=False)
        body = self.parity({"feature": "Body", "subelement": "Face1"}, before="Pocket")
        self.assertEqual(body[0]["feature"], "Pad")
        self.assertEqual(self.parity({"feature": "Body", "subelement": "Face1"}, before="Pad"), [])
        self.assertEqual(self.parity({"feature": "Hole", "subelement": "Edge1"})[0]["part"], "Hole")
        self.assertEqual(self.parity({"feature": "Hole", "subelement": "Edge1"}, before="Pad")[0]["part"], "Body")
        # A directly named prior feature remains valid even when absent from
        # the current result membership. Membership is not a rejection gate.
        self.assertEqual(self.parity({"feature": "Pad", "subelement": "Face1"})[0]["feature"], "Pad")
        self.assertEqual(self.parity({"feature": "Missing", "subelement": "Face1"}), [])
        self.assertEqual(self.parity({"feature": "Pad", "subelement": "Face9999"}), [])

    def test_invalid_literal_errors_match_complete_preparation(self):
        for query in ({"feature": "Pad", "subelement": "Face0"},
                      {"feature": "Pad", "subelement": "Edge-1"},
                      {"kind": "unknown"}, {"kind": "all", "extra": True}):
            with self.subTest(query=query):
                with self.assertRaises(OperationError) as lazy:
                    selectors.resolve(self.doc, query)
                with self.assertRaises(OperationError) as full:
                    selectors._resolve_full(self.doc, query)
                self.assertEqual((lazy.exception.code, str(lazy.exception)), (full.exception.code, str(full.exception)))

    def test_native_dimensions_and_body_world_placement_invalidate_literal_rows(self):
        query = {"feature": "Pad", "subelement": "Face1"}
        original = self.parity(query)
        self.doc.Pad.Length = 9
        self.doc.recompute()
        changed = self.parity(query)
        self.assertNotEqual(original, changed)
        self.doc.Body.Placement = App.Placement(App.Vector(30, 40, 5), App.Rotation(App.Vector(0, 0, 1), 90))
        self.doc.recompute()
        self.assertNotEqual(changed, self.parity(query))
        self.assertEqual(len(self.parity({"kind": "created_by", "feature": "Pad"})), 6)

    def test_structural_replacement_with_same_name_cannot_reuse_native_rows(self):
        first = self.doc.addObject("Part::Box", "Loose")
        first.Length = 2
        self.doc.recompute()
        query = {"feature": "Loose", "subelement": "Face1"}
        original = self.parity(query)
        self.doc.removeObject("Loose")
        replacement = self.doc.addObject("Part::Box", "Loose")
        replacement.Width = 7
        self.doc.recompute()
        self.assertNotEqual(original, self.parity(query))
        self.parity({"kind": "created_by", "feature": "Loose"})

    def test_undo_redo_abort_and_studio_history_preserve_complete_results(self):
        query = {"kind": "created_by", "feature": "Pad", "cap": "end"}
        original = self.parity(query)
        self.doc.openTransaction("Resize selector source")
        self.doc.Pad.Length = 9
        self.doc.recompute()
        self.doc.commitTransaction()
        changed = self.parity(query)
        self.assertNotEqual(original, changed)
        self.doc.undo(); self.doc.recompute()
        self.assertEqual(self.parity(query), original)
        self.doc.redo(); self.doc.recompute()
        self.assertEqual(self.parity(query), changed)
        self.doc.openTransaction("Abort source change")
        self.doc.Pad.Length = 12
        self.doc.recompute()
        self.parity(query)
        self.doc.abortTransaction(); self.doc.recompute()
        self.assertEqual(self.parity(query), changed)
        studio._enable(self.doc)
        cutoff = self.doc.KurtShapeProject.KurtShapeRollbackIndex
        self.doc.KurtShapeProject.KurtShapeRollbackIndex = 0
        self.assertEqual(self.parity({"kind": "all"}), [])
        self.assertEqual(self.parity(query), [])
        self.doc.KurtShapeProject.KurtShapeRollbackIndex = cutoff
        self.assertEqual(self.parity(query), changed)

    def test_change_during_native_read_uses_fresh_full_fallback(self):
        document_index.get(self.doc).invalidate(structure=True)
        native_world_shape = selectors._world_shape
        changed = []
        def read(obj):
            shape = native_world_shape(obj)
            if not changed:
                changed.append(True)
                self.doc.Body.Placement = App.Placement(App.Vector(30, 0, 0), App.Rotation())
                self.doc.recompute()
            return shape
        query = {"feature": "Pad", "subelement": "Face1"}
        with patch.object(selectors, "_world_shape", side_effect=read):
            result = selectors.resolve(self.doc, query)
        self.assertEqual(result, selectors._resolve_full(self.doc, query))
        self.assertNotIn("selector_contexts", document_index.get(self.doc).derived)

    def test_unobserved_document_uses_fresh_native_preparation(self):
        index = document_index.get(self.doc)
        document_index.unbind(index)
        try:
            query = {"feature": "Pad", "subelement": "Edge1"}
            self.assertIsNone(document_index.get(self.doc))
            self.parity(query)
        finally:
            document_index.bind(index)

    def test_dimension_change_during_read_cannot_poison_new_geometry_memos(self):
        document_index.get(self.doc).invalidate(structure=True)
        native_world_shape = selectors._world_shape
        changed = []
        def read(obj):
            shape = native_world_shape(obj)
            if not changed:
                changed.append(True)
                self.doc.Pad.Length = 9
                self.doc.recompute()
            return shape
        query = {"feature": "Pad", "subelement": "Face1"}
        with patch.object(selectors, "_world_shape", side_effect=read):
            result = selectors.resolve(self.doc, query)
        self.assertAlmostEqual(result[0]["summary"]["center_mm"][2], 4.5)
        self.assertEqual(result, selectors._resolve_full(self.doc, query))
        self.assertEqual(selectors.resolve(self.doc, query), result)

    def test_failed_native_read_after_mutation_retries_complete_preparation(self):
        document_index.get(self.doc).invalidate(structure=True)
        native_world_shape = selectors._world_shape
        changed = []
        def read(obj):
            if not changed:
                changed.append(True)
                self.doc.Pad.Length = 9
                self.doc.recompute()
                raise RuntimeError("Native row was invalidated during its read")
            return native_world_shape(obj)
        with patch.object(selectors, "_world_shape", side_effect=read):
            result = selectors.resolve(self.doc, {"kind": "all"})
        self.assertEqual(result, selectors._resolve_full(self.doc, {"kind": "all"}))
        self.assertNotIn("selector_contexts", document_index.get(self.doc).derived)

    def test_external_link_shape_changes_cannot_reuse_local_world_shapes(self):
        local = self.doc
        external = App.newDocument("SelectorExternalDependency")
        source = external.addObject("Part::Feature", "ExternalSolid")
        source.Shape = Part.makeBox(2, 3, 4)
        external.recompute()
        # Native cross-document links require persisted documents. Both files
        # belong to this private fixture and are created before linking them.
        external.saveAs(str(self.folder / "external-selector-source.FCStd"))
        local.saveAs(str(self.folder / "local-selector-consumer.FCStd"))
        # The supported occurrence path applies assembly and link placement.
        # Standalone native Links lack getGlobalPlacement in this runtime.
        parent = assembly.create(local, "ExternalSelectorAssembly")
        link = parent.newObject("App::Link", "ExternalOccurrence")
        link.setLink(source)
        local.recompute()
        self.assertEqual(assembly.assemblies(local), [parent])
        self.assertEqual(parent.KurtShapeAssembly, "1")
        self.assertIn(link, parent.Group)
        self.assertEqual(link.LinkedObject, source)
        self.assertEqual(source.Document, external)
        self.assertFalse(link.Shape.isNull())
        self.assertEqual((len(link.Shape.Solids), len(link.Shape.Faces)), (1, 6))
        self.assertFalse({"Error", "Invalid"} & set(link.State))
        query = {"feature": link.Name, "subelement": "Face1"}
        # Establish the independent positive control before testing reuse.
        original = selectors._resolve_full(local, query)
        self.assertEqual(len(original), 1)
        native_face = assembly.global_shape(link).getElement("Face1")
        self.assertEqual(original[0]["summary"]["center_mm"], list(native_face.CenterOfMass))
        self.assertAlmostEqual(original[0]["summary"]["area_mm2"], native_face.Area)
        self.assertAlmostEqual(native_face.Area, 12.0)
        for _ in range(2):
            self.assertEqual(self.parity(query), original)
            self.assertNotIn("selector_contexts", document_index.get(local).derived)
        index = document_index.get(local)
        token = index.token(*sorted(document_index.DOMAINS))
        source.Shape = Part.makeBox(2, 7, 4)
        external.recompute()
        # No local recompute, manual invalidation or observer suppression:
        # foreign geometry changed while the complete local key stayed equal.
        self.assertIs(document_index.get(local), index)
        self.assertEqual(index.token(*sorted(document_index.DOMAINS)), token)
        changed = selectors.resolve(local, query)
        self.assertEqual(changed, selectors._resolve_full(local, query))
        self.assertEqual(len(changed), 1)
        self.assertNotEqual(changed, original)
        changed_face = assembly.global_shape(link).getElement("Face1")
        self.assertEqual(changed[0]["summary"]["center_mm"], list(changed_face.CenterOfMass))
        self.assertAlmostEqual(changed[0]["summary"]["area_mm2"], changed_face.Area)
        self.assertAlmostEqual(changed_face.Area, 28.0)
        self.assertNotIn("selector_contexts", document_index.get(local).derived)
        App.setActiveDocument(local.Name)
