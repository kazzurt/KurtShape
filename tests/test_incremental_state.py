"""Native oracle parity for incremental intent, summaries and invalidation."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
from kurtshape import document_index, incremental_intent, inspection_cache, selectors, studio
from kurtshape.core import Controller, intent_signature, native_feature_summary, native_intent


class IncrementalDocumentStateTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="incremental-document-state-")
        self.core = Controller()
        response = self.core.dispatch({"op": "new", "name": "Incremental document state", "measure": False})
        self.assertTrue(response["ok"], response)
        self.current = response["result"]
        self.doc = self.core.documents[self.current["document_id"]]
        self.call("sketch_rectangle", id="Profile", width=20, height=10)
        self.call("pad", id="Pad", profile="Profile", length=6)
        self.cache = incremental_intent.IntentCache(self.doc)

    def tearDown(self):
        self.core.close()
        for name in set(App.listDocuments()) - self.names:
            App.closeDocument(name)

    def call(self, op, **arguments):
        response = self.core.dispatch({"op": op, "document_id": self.current["document_id"],
            "expected_revision": self.current["revision"], "measure": False, **arguments})
        self.assertTrue(response["ok"], response)
        self.current = response["result"]
        return self.current

    def assertIntentParity(self, doc=None, cache=None):
        doc = self.doc if doc is None else doc
        cache = self.cache if cache is None else cache
        actual = cache.signature(doc, self.core.observer.state(doc), native_intent)
        self.assertEqual(actual, intent_signature(doc))
        return actual

    def assertSummaryParity(self, obj):
        actual = inspection_cache.feature_summary(obj, self.core.observer, native_feature_summary)
        self.assertEqual(actual, native_feature_summary(obj))
        return actual

    def test_warm_reads_reuse_records_and_return_independent_summary_rows(self):
        original = self.assertIntentParity()
        self.assertSummaryParity(self.doc.Profile)
        expected = self.assertSummaryParity(self.doc.Pad)
        summaries = self.core.observer.state(self.doc)["feature_summary_cache"]
        reads, builds = self.cache.object_reads, summaries.builds
        for _ in range(20):
            self.assertEqual(self.assertIntentParity(), original)
            self.assertSummaryParity(self.doc.Profile)
            self.assertSummaryParity(self.doc.Pad)
        self.assertEqual(self.cache.object_reads, reads)
        self.assertEqual(self.cache.last_read_names, ())
        self.assertEqual(summaries.builds, builds)
        changed = inspection_cache.feature_summary(self.doc.Pad, self.core.observer, native_feature_summary)
        changed["name"] = "Caller-owned mutation"
        changed["parameters"].clear()
        self.assertEqual(self.assertSummaryParity(self.doc.Pad), expected)

    def test_native_dimensions_labels_and_document_label_match_full_oracle(self):
        original = self.assertIntentParity()
        self.assertSummaryParity(self.doc.Pad)
        self.doc.Pad.Length = 9
        self.assertNotEqual(self.assertIntentParity(), original)
        self.assertIn("Pad", self.cache.last_read_names)
        self.assertSummaryParity(self.doc.Pad)
        self.assertSummaryParity(self.doc.Profile)
        self.doc.recompute()
        self.assertIntentParity()
        self.assertSummaryParity(self.doc.Pad)
        self.doc.Pad.Label = 'Pad "quoted" — µ'
        self.assertIntentParity()
        self.assertEqual(self.cache.last_read_names, ("Pad",))
        self.assertSummaryParity(self.doc.Pad)
        self.doc.Label = 'Document "quoted" — µ\nsecond line'
        before_reads = self.cache.object_reads
        self.assertIntentParity()
        self.assertEqual(self.cache.object_reads, before_reads)

    def test_expression_and_constraint_changes_match_full_oracle(self):
        original = self.assertIntentParity()
        self.doc.Pad.setExpression("Length", "Profile.Constraints.Width / 2")
        self.assertNotEqual(self.assertIntentParity(), original)
        self.assertSummaryParity(self.doc.Pad)
        self.doc.recompute()
        self.assertIntentParity()
        self.assertSummaryParity(self.doc.Pad)
        self.assertAlmostEqual(self.doc.Pad.Length.Value, 10)
        width = next(i for i, constraint in enumerate(self.doc.Profile.Constraints) if constraint.Name == "Width")
        self.doc.Profile.setDatum(width, App.Units.Quantity("12 mm"))
        self.assertIntentParity()
        self.assertSummaryParity(self.doc.Profile)
        self.assertSummaryParity(self.doc.Pad)
        self.doc.recompute()
        self.assertIntentParity()
        self.assertSummaryParity(self.doc.Pad)
        self.assertAlmostEqual(self.doc.Pad.Length.Value, 6)
        self.doc.Pad.setExpression("Length", None)
        self.doc.Pad.Length = 7
        self.doc.recompute()
        self.assertIntentParity()
        self.assertSummaryParity(self.doc.Pad)

    def test_dynamic_properties_delete_and_same_name_recreation(self):
        self.assertIntentParity()
        self.doc.Pad.addProperty("App::PropertyString", "IncrementalNote")
        self.doc.Pad.IncrementalNote = 'α "quote" \\ slash\nnewline'
        with_property = self.assertIntentParity()
        self.assertSummaryParity(self.doc.Pad)
        self.doc.Pad.removeProperty("IncrementalNote")
        self.assertNotEqual(self.assertIntentParity(), with_property)
        self.assertSummaryParity(self.doc.Pad)
        marker = self.doc.addObject("Part::Feature", "CacheMarker")
        marker.addProperty("App::PropertyString", "Note")
        marker.Note = "First native object"
        marker.Shape = Part.makeBox(1, 2, 3)
        name = marker.Name
        self.assertIntentParity()
        self.assertSummaryParity(marker)
        self.doc.removeObject(name)
        self.assertIntentParity()
        self.assertNotIn(name, self.cache.records)
        replacement = self.doc.addObject("Part::Feature", name)
        self.assertEqual(replacement.Name, name)
        replacement.Shape = Part.makeBox(2, 3, 4)
        self.assertIntentParity()
        self.assertIn(name, self.cache.last_read_names)
        self.assertSummaryParity(replacement)

    def test_undo_redo_abort_and_restore_force_safe_oracle_parity(self):
        original = self.assertIntentParity()
        self.doc.openTransaction("Incremental dimensional edit")
        self.doc.Pad.Length = 11
        self.doc.recompute()
        self.doc.commitTransaction()
        edited = self.assertIntentParity()
        self.assertNotEqual(edited, original)
        self.assertSummaryParity(self.doc.Pad)
        observer = self.core.observer
        serial = observer.state(self.doc)["change_serial"]
        reads = self.cache.object_reads
        self.doc.undo()
        self.assertTrue(observer.changes_since(self.doc, serial)["full"])
        self.assertEqual(self.assertIntentParity(), original)
        self.assertGreater(self.cache.object_reads, reads)
        self.assertSummaryParity(self.doc.Pad)
        self.doc.redo()
        self.assertEqual(self.assertIntentParity(), edited)
        self.doc.openTransaction("Aborted incremental edit")
        self.doc.Pad.Label = "Discarded draft label"
        self.doc.Pad.Length = 13
        self.doc.recompute()
        self.assertIntentParity()
        self.doc.abortTransaction()
        self.assertEqual(self.assertIntentParity(), edited)
        self.assertSummaryParity(self.doc.Pad)
        path = self.folder / "incremental-state-roundtrip.FCStd"
        self.doc.saveAs(str(path))
        App.closeDocument(self.doc.Name)
        reopened = App.openDocument(str(path))
        restored_cache = incremental_intent.IntentCache(reopened)
        self.assertIntentParity(reopened, restored_cache)
        self.assertSummaryParity(reopened.getObject("Pad"))
        before = restored_cache.object_reads
        self.assertIntentParity(reopened, restored_cache)
        self.assertEqual(restored_cache.object_reads, before)

    def test_metadata_changes_preserve_geometry_contexts_and_history(self):
        self.doc.Pad.addProperty("App::PropertyString", "QueryHealth")
        self.doc.Pad.QueryHealth = "[]"
        query = {"kind": "all", "entity_type": "face"}
        expected = selectors.resolve(self.doc, query)
        self.assertTrue(expected)
        studio.order(self.doc)
        index = document_index.get(self.doc)
        cached = {name: index.derived[name] for name in ("selector_contexts", "order", "positions", "selector_topology")}
        self.doc.Pad.Label = "Only the displayed feature label changed"
        self.assertIntentParity()
        for name, value in cached.items():
            self.assertIs(index.derived[name], value)
        self.assertEqual(selectors.resolve(self.doc, query), expected)
        signature = self.assertIntentParity()
        self.doc.Pad.QueryHealth = '[{"input":"diagnostic_probe","status":"missing"}]'
        self.assertEqual(self.assertIntentParity(), signature)
        for name, value in cached.items():
            self.assertIs(index.derived[name], value)
        self.assertSummaryParity(self.doc.Pad)

    def test_shape_change_discards_topology_but_preserves_history_order(self):
        marker = self.doc.addObject("Part::Feature", "ShapeCacheProbe")
        marker.Shape = Part.makeBox(1, 2, 3)
        self.doc.recompute()
        sequence = studio.order(self.doc)
        studio._state(self.doc, len(sequence))
        selectors.resolve(self.doc, {"kind": "all", "entity_type": "face"})
        index = document_index.get(self.doc)
        order, positions = index.derived["order"], index.derived["positions"]
        self.assertIn("part_states", index.derived)
        self.assertIn("selector_contexts", index.derived)
        self.assertIn("selector_topology", index.derived)
        marker.Shape = Part.makeBox(2, 3, 4)
        self.assertIs(index.derived["order"], order)
        self.assertIs(index.derived["positions"], positions)
        for key in ("part_states", "selector_contexts", "selector_topology"):
            self.assertNotIn(key, index.derived)
        self.assertIntentParity()
        self.assertSummaryParity(marker)

    def test_change_journal_has_independent_cursors_and_overflow_fallback(self):
        observer = self.core.observer
        start = observer.state(self.doc)["change_serial"]
        self.doc.Pad.Label = "Journal first change"
        first = observer.changes_since(self.doc, start)
        saved = deepcopy(first)
        self.assertFalse(first["full"])
        self.assertIn("Label", first["objects"]["Pad"])
        self.assertIn("metadata", first["domains"])
        self.assertEqual(observer.changes_since(self.doc, start), saved)
        self.doc.Pad.Length = 8
        second = observer.changes_since(self.doc, first["serial"])
        self.assertIn("Length", second["objects"]["Pad"])
        self.assertNotIn("Label", second["objects"]["Pad"])
        self.assertTrue({"Label", "Length"} <= observer.changes_since(self.doc, start)["objects"]["Pad"])
        self.assertEqual(first, saved)
        cursor = observer.state(self.doc)["change_serial"]
        for _ in range(observer.state(self.doc)["change_log"].maxlen + 1):
            observer._record_change(self.doc, "Pad", "Label", domains={"metadata"})
        self.assertTrue(observer.changes_since(self.doc, cursor)["full"])
        latest = observer.state(self.doc)["change_serial"]
        empty = observer.changes_since(self.doc, latest)
        self.assertFalse(empty["full"])
        self.assertEqual(empty["objects"], {})
        self.assertEqual(empty["domains"], frozenset())
        self.assertTrue(observer.changes_since(self.doc, latest + 1)["full"])

    def test_shape_named_string_properties_remain_authored_intent(self):
        marker = self.doc.addObject("Part::Feature", "NamedStringProbe")
        for prop in ("AddSubShape", "SuppressedShape"):
            marker.addProperty("App::PropertyString", prop)
            setattr(marker, prop, "before")
            before = self.assertIntentParity()
            setattr(marker, prop, "after")
            self.assertNotEqual(self.assertIntentParity(), before)

    def test_signature_retries_changes_during_property_reads(self):
        altered = []
        def changing_reader(doc, objects):
            rows = native_intent(doc, objects)
            if objects[0].Name == "Pad" and not altered:
                altered.append(True)
                doc.Profile.Label = "Changed an already visited object"
                doc.Label = "Changed while reading"
            return rows
        actual = self.cache.signature(self.doc, self.core.observer.state(self.doc), changing_reader)
        self.assertTrue(altered)
        self.assertEqual(actual, intent_signature(self.doc))
        def unstable_reader(doc, objects):
            rows = native_intent(doc, objects)
            doc.Label += "!"
            self.core.observer.invalidate(doc)
            return rows
        self.core.observer.invalidate(self.doc)
        with self.assertRaisesRegex(RuntimeError, "changed while reading intent"):
            self.cache.signature(self.doc, self.core.observer.state(self.doc), unstable_reader)

    def test_sketch_content_restore_matches_oracle_before_recompute(self):
        from kurtshape.sketch_tools import restore_sketch_content
        raw = self.doc.Profile.dumpContent()
        original = self.assertIntentParity()
        width = next(i for i, constraint in enumerate(self.doc.Profile.Constraints) if constraint.Name == "Width")
        self.doc.Profile.setDatum(width, App.Units.Quantity("12 mm"))
        self.assertNotEqual(self.assertIntentParity(), original)
        restore_sketch_content(self.doc.Profile, raw)
        self.assertEqual(self.assertIntentParity(), original)
        self.assertSummaryParity(self.doc.Profile)


if __name__ == "__main__":
    unittest.main()
