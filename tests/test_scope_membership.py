"""Whole auto-scope membership must match the retained native traversal."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import FreeCAD as App
import Part
from kurtshape import document_index, studio
from test_part_studio import PartStudioTests


class ScopeMembershipTests(unittest.TestCase):
    # Explicit fixture aliases avoid inheriting the complete Part Studio suite.
    doc = PartStudioTests.doc
    request = PartStudioTests.request
    call = PartStudioTests.call
    part = PartStudioTests.part

    def setUp(self):
        PartStudioTests.setUp(self)
        self.part()
        self.part("Second", x=20)
        self.tool = self.doc.addObject("Part::Feature", "ScopeProbe")
        self.tool.Shape = Part.makeBox(14, 6, 6, App.Vector(8, 2, 2))
        self.before = len(studio.order(self.doc))
        self.index = document_index.get(self.doc)
        self.assertIsNotNone(self.index)

    def tearDown(self):
        self.core.close()
        for name in set(App.listDocuments()) - self.initial:
            App.closeDocument(name)

    def scope(self, operation="remove", tools=None, before=None, doc=None):
        return studio._scope_parts(doc or self.doc, operation,
                                   [self.tool] if tools is None else tools,
                                   self.before if before is None else before)

    def oracle(self, operation="remove", tools=None, before=None, doc=None):
        return studio._scope_parts_full(doc or self.doc, operation,
                                        [self.tool] if tools is None else tools,
                                        self.before if before is None else before)

    def assert_current_and_warm(self, operation="remove", tools=None, before=None, expected=None):
        oracle = self.oracle(operation, tools, before)
        if expected is not None:
            self.assertEqual(oracle, expected)
        with patch.object(studio, "_scope_parts_full", wraps=studio._scope_parts_full) as full:
            self.assertEqual(self.scope(operation, tools, before), oracle)
            first_reads = full.call_count
            self.assertEqual(self.scope(operation, tools, before), oracle)
            self.assertEqual(full.call_count, first_reads)
        return first_reads

    def test_operations_history_and_tools_match_oracle_with_no_repeat_traversal(self):
        for operation in ("add", "remove", "intersect"):
            with self.subTest(operation=operation):
                full = self.index.counts.get("scope_membership_full", 0)
                hits = self.index.counts.get("scope_membership_hits", 0)
                # Both parts overlap the probe; different operations still
                # require separate membership entries.
                first = self.scope(operation)
                self.assertEqual(first, ["Body", "Second"])
                self.assertEqual(self.scope(operation), first)
                self.assertEqual(self.index.counts["scope_membership_full"], full + 1)
                self.assertEqual(self.index.counts["scope_membership_hits"], hits + 1)
                self.assertEqual(first, self.oracle(operation))

        boundary = studio.order(self.doc).index(self.doc.SecondExtrude)
        self.assert_current_and_warm(before=boundary, expected=["Body"])
        other = self.doc.addObject("Part::Feature", "OtherScopeProbe")
        other.Shape = Part.makeBox(2, 2, 2, App.Vector(21, 2, 2))
        self.assert_current_and_warm(tools=[other], expected=["Second"])
        self.assert_current_and_warm(tools=[self.tool, other], expected=["Body", "Second"])
        self.assert_current_and_warm(tools=[], expected=[])

        # Contact without overlapping volume belongs only to Add.
        self.tool.Shape = Part.makeBox(10, 6, 6, App.Vector(10, 2, 2))
        self.assert_current_and_warm("add", expected=["Body", "Second"])
        self.assert_current_and_warm("remove", expected=[])
        self.assert_current_and_warm("intersect", expected=[])

    def test_returned_membership_lists_are_caller_owned(self):
        first = self.scope()
        first[:] = ["injected caller value"]
        second = self.scope()
        self.assertEqual(second, ["Body", "Second"])
        self.assertIsNot(first, second)
        second.clear()
        self.assertEqual(self.scope(), self.oracle())

    def test_native_placement_geometry_metadata_and_structure_invalidate_membership(self):
        self.assert_current_and_warm(expected=["Body", "Second"])
        changes = (
            ("tool placement", lambda: setattr(self.tool, "Placement", App.Placement(App.Vector(100, 0, 0), App.Rotation()))),
            ("tool geometry", lambda: setattr(self.tool, "Shape", Part.makeBox(3, 3, 3, App.Vector(2, 2, 2)))),
            ("body placement", lambda: setattr(self.doc.Body, "Placement", App.Placement(App.Vector(100, 0, 0), App.Rotation()))),
            ("result geometry", lambda: setattr(self.doc.SecondExtrude, "Shape", Part.makeBox(3, 3, 3, App.Vector(22, 2, 2)))),
            ("metadata", lambda: setattr(self.doc.Second, "Label", "Changed display name")),
            ("structure", lambda: self.doc.addObject("Part::Feature", "UnrelatedNativeObject")),
            ("part identity", lambda: setattr(self.doc.Second, "KurtShapePartId", "SecondRenamedIdentity")),
        )
        for label, change in changes:
            with self.subTest(change=label):
                self.scope()
                change()
                expected = self.oracle()
                full_count = self.index.counts.get("scope_membership_full", 0)
                with patch.object(studio, "_scope_parts_full", wraps=studio._scope_parts_full) as full:
                    self.assertEqual(self.scope(), expected)
                    self.assertEqual(full.call_count, 1)
                self.assertEqual(self.index.counts["scope_membership_full"], full_count + 1)
                self.assert_current_and_warm()

    def test_native_undo_redo_and_tool_name_replacement_cannot_reuse_stale_membership(self):
        baseline = self.scope()
        self.assertEqual(baseline, ["Body", "Second"])
        self.doc.openTransaction("Move scope probe")
        self.tool.Placement = App.Placement(App.Vector(100, 0, 0), App.Rotation())
        self.doc.commitTransaction()
        self.assert_current_and_warm(expected=[])
        self.doc.undo()
        self.assert_current_and_warm(expected=baseline)
        self.doc.redo()
        self.assert_current_and_warm(expected=[])
        self.doc.undo()
        self.assert_current_and_warm(expected=baseline)

        name = self.tool.Name
        self.doc.removeObject(name)
        replacement = self.doc.addObject("Part::Feature", name)
        self.assertEqual(replacement.Name, name)
        replacement.Shape = Part.makeBox(2, 2, 2, App.Vector(22, 2, 2))
        self.tool = replacement
        self.assert_current_and_warm(expected=["Second"])

        # Deleting a native result changes the candidate list itself.
        self.doc.removeObject(self.doc.SecondExtrude.Name)
        self.assert_current_and_warm(expected=[])

    @staticmethod
    def native_fixture(doc, x):
        body = doc.addObject("PartDesign::Body", "Body")
        tip = body.newObject("PartDesign::Feature", "BodyExtrude")
        tip.Shape = Part.makeBox(10, 10, 10, App.Vector(x, 0, 0))
        body.Tip = tip
        tool = doc.addObject("Part::Feature", "ScopeProbe")
        tool.Shape = Part.makeBox(2, 2, 2, App.Vector(2, 2, 2))
        return tool, len(studio.order(doc))

    def test_cross_document_and_reopened_name_have_separate_membership(self):
        self.assertEqual(self.scope(), ["Body", "Second"])
        other = App.newDocument("ScopeOtherDocument")
        tool, boundary = self.native_fixture(other, 100)
        other_index = document_index.get(other)
        self.assertIsNotNone(other_index)
        self.assertIsNot(other_index, self.index)
        self.assertEqual(self.scope(tools=[tool], before=boundary, doc=other), [])
        self.assertEqual(self.scope(tools=[tool], before=boundary, doc=other),
                         self.oracle(tools=[tool], before=boundary, doc=other))
        self.assertEqual(self.scope(), ["Body", "Second"])
        # A foreign tool's same Name cannot borrow the local tool's entry.
        with patch.object(studio, "_scope_parts_full", wraps=studio._scope_parts_full) as full:
            self.assertEqual(self.scope(tools=[tool]), ["Body"])
            self.assertEqual(self.scope(tools=[tool]), ["Body"])
            self.assertEqual(full.call_count, 2)

        name = other.Name
        App.closeDocument(name)
        reopened = App.newDocument(name)
        new_tool, new_boundary = self.native_fixture(reopened, 0)
        self.assertEqual(reopened.Name, name)
        self.assertIsNot(document_index.get(reopened), other_index)
        self.assertEqual(self.scope(tools=[new_tool], before=new_boundary, doc=reopened), ["Body"])
        self.assertEqual(self.scope(tools=[new_tool], before=new_boundary, doc=reopened),
                         self.oracle(tools=[new_tool], before=new_boundary, doc=reopened))

    def test_change_during_full_read_retries_current_state_without_caching_that_read(self):
        native_full = studio._scope_parts_full
        calls = []

        def changing_read(*args, **kwargs):
            result = native_full(*args, **kwargs)
            calls.append(result)
            if len(calls) == 1:
                self.tool.Placement = App.Placement(App.Vector(100, 0, 0), App.Rotation())
            return result

        with patch.object(studio, "_scope_parts_full", side_effect=changing_read):
            self.assertEqual(self.scope(), [])
        self.assertGreaterEqual(len(calls), 2)
        self.assertEqual(self.oracle(), [])
        with patch.object(studio, "_scope_parts_full", wraps=native_full) as full:
            self.assertEqual(self.scope(), [])
            self.assertEqual(full.call_count, 1, "A changed read must not populate membership cache")
            self.assertEqual(self.scope(), [])
            self.assertEqual(full.call_count, 1)

    def test_local_link_to_foreign_geometry_bypasses_membership_cache(self):
        external = App.newDocument("ExternalScopeSource")
        source = external.addObject("Part::Feature", "ExternalTool")
        source.Shape = Part.makeBox(5, 6, 6)
        external.saveAs(str(self.folder / "external-scope-source.FCStd"))
        self.doc.saveAs(str(self.folder / "scope-link-owner.FCStd"))
        link = self.doc.addObject("App::Link", "LinkedScopeProbe")
        link.setLink(source)
        link.Placement = App.Placement(App.Vector(2, 2, 2), App.Rotation())
        external.recompute()
        self.doc.recompute()
        self.assertEqual(link.Document, self.doc)
        self.assertEqual(link.LinkedObject.Document, external)
        self.assertEqual(self.oracle(tools=[link]), ["Body"])
        with patch.object(studio, "_scope_parts_full", wraps=studio._scope_parts_full) as full:
            self.assertEqual(self.scope(tools=[link]), ["Body"])
            self.assertEqual(self.scope(tools=[link]), ["Body"])
            self.assertEqual(full.call_count, 2)
        # Mutating the external native source must never be hidden by a hit
        # against only this document's previously observed geometry token.
        source.Shape = Part.makeBox(25, 6, 6)
        external.recompute()
        self.doc.recompute()
        expected = self.oracle(tools=[link])
        self.assertEqual(expected, ["Body", "Second"])
        with patch.object(studio, "_scope_parts_full", wraps=studio._scope_parts_full) as full:
            self.assertEqual(self.scope(tools=[link]), expected)
            self.assertEqual(self.scope(tools=[link]), expected)
            self.assertEqual(full.call_count, 2)

    def test_changed_read_exception_retries_but_stable_error_is_preserved(self):
        native_full = studio._scope_parts_full
        calls = []
        def changing_read(*args):
            calls.append(True)
            if len(calls) == 1:
                self.tool.Placement = App.Placement(App.Vector(100, 0, 0), App.Rotation())
                raise RuntimeError("Stale native wrapper")
            return native_full(*args)
        with patch.object(studio, "_scope_parts_full", side_effect=changing_read):
            self.assertEqual(self.scope(), [])
        self.assertEqual(len(calls), 2)
        with patch.object(studio, "_scope_parts_full", side_effect=RuntimeError("Stable native failure")) as full:
            with self.assertRaisesRegex(RuntimeError, "Stable native failure"):
                self.scope()
            self.assertEqual(full.call_count, 1)

    def test_unobserved_native_document_uses_uncached_full_fallback(self):
        # A standalone native client has neither an observer nor geometry cache.
        self.core.observer.close()
        unmanaged = App.newDocument("UnobservedScopeDocument")
        tool, boundary = self.native_fixture(unmanaged, 0)
        # Other full-suite fixtures may still observe global native events.
        # Explicitly remove their index to model this client's uncached read.
        observed = document_index.get(unmanaged)
        if observed is not None:
            document_index.unbind(observed)
        self.assertIsNone(document_index.get(unmanaged))
        with patch.object(studio, "_scope_parts_full", wraps=studio._scope_parts_full) as full:
            self.assertEqual(self.scope(tools=[tool], before=boundary, doc=unmanaged), ["Body"])
            self.assertEqual(self.scope(tools=[tool], before=boundary, doc=unmanaged), ["Body"])
            self.assertEqual(full.call_count, 2)
        tool.Placement = App.Placement(App.Vector(100, 0, 0), App.Rotation())
        observed = document_index.get(unmanaged)
        if observed is not None:
            document_index.unbind(observed)
        self.assertEqual(self.scope(tools=[tool], before=boundary, doc=unmanaged), [])
        self.assertIsNone(document_index.get(unmanaged))

    def test_membership_storage_is_bounded_and_keeps_only_immutable_ids(self):
        limit = studio._SCOPE_MEMBERSHIP_LIMIT
        # Beyond-end cutoffs are distinct keys but yield the same native state.
        for boundary in range(self.before, self.before + limit + 5):
            self.assertEqual(self.scope(before=boundary), ["Body", "Second"])
        cache = self.index.derived["scope_membership"]
        self.assertLessEqual(len(cache), limit)
        self.assertTrue(cache)
        for value in cache.values():
            self.assertIsInstance(value, tuple)
            self.assertTrue(all(isinstance(identity, str) for identity in value))
        with patch.object(studio, "_scope_parts_full", wraps=studio._scope_parts_full) as full:
            self.assertEqual(self.scope(before=self.before), ["Body", "Second"])
            self.assertEqual(full.call_count, 1, "Oldest membership must be evicted at the configured bound")
