"""Native cheap status, explicit checks, stored-shape open and measured costs."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch
import uuid
import xml.etree.ElementTree as ET
import zipfile

import support
import perf_fixture

sys.path.insert(0, str(support.ROOT / "src"))
sys.path.insert(0, str(support.ROOT / "tools"))
import FreeCAD as App
import Part
from kurtshape import geometry
from kurtshape.core import Controller, METADATA, intent_signature
from native_validation_snapshot import snapshot_document


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@contextmanager
def no_kernel_checks(testcase):
    """Cover the public gate and Python-visible direct native check calls."""
    previous = sys.getprofile()
    native_calls = []

    def observe(frame, event, argument):
        if event == "c_call" and getattr(argument, "__name__", "") in {"isValid", "check"}:
            bound = getattr(argument, "__self__", None)
            if bound is not None and type(bound).__module__.startswith("Part"):
                native_calls.append(getattr(argument, "__name__", ""))
        if previous is not None:
            previous(frame, event, argument)

    with patch.object(geometry, "check_shape", wraps=geometry.check_shape) as check:
        sys.setprofile(observe)
        try:
            yield check
        finally:
            sys.setprofile(previous)
        testcase.assertEqual(check.call_count, 0)
        testcase.assertEqual(native_calls, [], "Interactive path invoked a direct native BRepCheck")


def rewrite_archive(source, target, transform_xml=None, omit=()):
    """Rewrite only explicit private fixture seams; preserve all other payloads."""
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(target, "x") as rewritten:
        assert original.namelist().count("Document.xml") == 1
        assert original.testzip() is None
        rewritten.comment = original.comment
        for info in original.infolist():
            if info.filename in omit:
                continue
            raw = original.read(info)
            if info.filename == "Document.xml" and transform_xml is not None:
                raw = transform_xml(raw)
            rewritten.writestr(info, raw)
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        ET.fromstring(archive.read("Document.xml"))


def set_program_version(raw):
    root = ET.fromstring(raw)
    assert root.tag == "Document" and "ProgramVersion" in root.attrib
    assert root.attrib["ProgramVersion"] != "0.0R1"
    root.set("ProgramVersion", "0.0R1")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


@contextmanager
def recompute_observations():
    """Observe actual native boundaries independently of the timing labels."""
    events = {"documents": [], "objects": []}

    class Observer:
        def slotRecomputedDocument(self, doc):
            events["documents"].append(doc.Name)

        def slotRecomputedObject(self, obj):
            events["objects"].append({"document": obj.Document.Name, "name": obj.Name, "type": obj.TypeId})

    observer = Observer()
    App.addDocumentObserver(observer)
    try:
        yield events
    finally:
        App.removeDocumentObserver(observer)


class BuildStatusTests(unittest.TestCase):
    def test_native_ownership_index_tracks_move_undo_and_deletion(self):
        from kurtshape import bodies, document_index
        doc = self.core.documents[self.state["document_id"]]
        first = doc.getObject("Body")
        second = doc.addObject("PartDesign::Body", "Second")
        feature = first.newObject("PartDesign::Feature", "NativeFeature")
        feature.Shape = Part.makeBox(2, 3, 4)
        doc.recompute()
        index = document_index.get(doc)
        self.assertEqual(bodies.owner(doc, feature), first)
        self.assertEqual(bodies.owner(doc, first.Origin.OriginFeatures[0]), first)
        before = dict(index.counts)
        for _ in range(5):
            self.assertEqual(bodies.owner(doc, feature), first)
            self.assertEqual(bodies.bodies(doc), [first, second])
        self.assertEqual(index.counts, before)
        doc.openTransaction("Move native feature")
        first.removeObject(feature)
        second.addObject(feature)
        doc.commitTransaction()
        self.assertEqual(bodies.owner(doc, feature), second)
        doc.undo()
        self.assertEqual(bodies.owner(doc, doc.NativeFeature), first)
        doc.redo()
        self.assertEqual(bodies.owner(doc, doc.NativeFeature), second)
        doc.removeObject("NativeFeature")
        replacement = first.newObject("PartDesign::Feature", "NativeFeature")
        self.assertEqual(bodies.owner(doc, replacement), first)

    def test_document_index_released_when_observer_closes_and_name_reused(self):
        from kurtshape import bodies, document_index
        doc = self.core.documents[self.state["document_id"]]
        name = doc.Name
        index = document_index.get(doc)
        self.assertTrue(bodies.bodies(doc))
        App.closeDocument(name)
        replacement = App.newDocument(name)
        body = replacement.addObject("PartDesign::Body", "DifferentBody")
        self.assertEqual(bodies.bodies(replacement), [body])
        replacement_index = document_index.get(replacement)
        self.assertIsNotNone(replacement_index)
        self.assertIsNot(replacement_index, index)
        # Delayed cleanup must tolerate a deleted wrapper and retain a new
        # document registered under the same native name.
        document_index.unbind(index)
        self.assertIs(document_index.get(replacement), replacement_index)
        self.core.observer.close()
        self.assertIsNone(document_index.get(replacement))
        # Restore an observer for the ordinary fixture cleanup.
        from kurtshape.document_state import DocumentState
        self.core.observer = DocumentState(self.core)

    def setUp(self):
        self.folder = support.isolated_session(self, prefix="build-status-native-")
        self.names = set(App.listDocuments())
        self.core = Controller()
        self.addCleanup(self._close)
        self.state = None
        self.call("new", name="Build status fixture")

    def _close(self):
        errors = []
        try:
            self.core.close()
        except Exception as exc:
            errors.append(exc)
        for name in set(App.listDocuments()) - self.names:
            try:
                App.closeDocument(name)
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise errors[0]

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def request(self, op, **args):
        result = {"op": op, **args}
        if op not in self.core.CREATE_OPS | {"capabilities", "list_documents", "request_status"}:
            result.update(document_id=self.state["document_id"], expected_revision=self.state["revision"])
        return result

    def call(self, op, **args):
        response = self.core.dispatch(self.request(op, **args))
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        return self.state

    def reject(self, op, code=None, **args):
        response = self.core.dispatch(self.request(op, **args))
        self.assertFalse(response["ok"], response)
        if code is not None:
            self.assertEqual(response["error"]["code"], code, response)
        return response

    def plate(self):
        self.call("sketch_rectangle", id="Plate", width=20, height=10)
        self.call("pad", id="Pad", profile="Plate", length=6)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, 1200)

    def invariant(self):
        return snapshot_document(self.doc, self.core)["strict"]

    def publish(self, checks, **extra):
        return perf_fixture.write_report(self, {}, checks, extra=extra)

    def stored(self, filename="stored.FCStd"):
        self.plate()
        self.assertIs(self.doc.UseHasher, False)
        path = self.folder / filename
        self.call("save", path=str(path))
        self.assertIs(self.doc.UseHasher, False)
        return path

    def reopen(self, path, expected_recomputes=0, measure=True):
        if self.state and self.state.get("document_id") in self.core.documents:
            old = self.core.documents[self.state["document_id"]]
            if self.core._is_open(old):
                App.closeDocument(old.Name)
        before = digest(path)
        with perf_fixture.timing_events(self.core) as events, recompute_observations() as native:
            self.call("open", path=str(path), measure=measure)
        self.assertEqual(len(events["native_recompute"]), expected_recomputes)
        self.assertEqual(len(native["documents"]), expected_recomputes)
        if expected_recomputes == 0:
            self.assertEqual(native["objects"], [])
        self.assertEqual(digest(path), before)
        return self.doc

    def absent_export(self, path):
        for candidate in (path, path.with_suffix(path.suffix + ".json"),
                          path.with_name(path.stem + ".exporting" + path.suffix),
                          path.with_suffix(path.suffix + ".json.saving")):
            self.assertFalse(candidate.exists(), candidate)

    def bow_tie(self):
        shape = Part.Face(Part.makePolygon([App.Vector(0, 0, 0), App.Vector(10, 10, 0),
                                           App.Vector(0, 10, 0), App.Vector(10, 0, 0),
                                           App.Vector(0, 0, 0)])).extrude(App.Vector(0, 0, 5))
        self.assertFalse(shape.isNull())
        self.assertEqual(len(shape.Solids), 1)
        self.assertFalse(shape.isValid(), "The invalid fixture must actually be invalid")
        obj = self.doc.addObject("Part::Feature", "BowTie")
        obj.Shape = shape
        self.doc.recompute()
        self.state = self.core.inspect(self.doc, measure=False)
        self.assertEqual(self.state["geometry_check"], "not_checked")
        self.assertEqual(self.state["build_status"], "valid")
        return obj

    def test_interactive_operations_never_run_brepcheck(self):
        with no_kernel_checks(self):
            self.plate()
            self.call("sketch_circle", id="Hole", x=10, y=5, diameter=2, measure=False)
            self.call("pocket", id="Pocket", profile="Hole", length=2, through_all=False, measure=False)
            self.call("set_parameter", feature="Pad", parameter="Length", value=7, measure=False)
            self.call("set_expression", feature="Pad", parameter="Length", expression="Plate.Constraints.Width / 4", measure=False)
            self.call("set_expression", feature="Pad", parameter="Length", expression=None, measure=False)
            self.call("undo", measure=False)
            self.call("redo", measure=False)
            self.call("create_sketch", id="Draft", measure=False)
            self.call("begin_sketch_edit", feature="Draft", measure=False)
            self.call("add_circle", sketch="Draft", x=2, y=2, diameter=1, construction=True, measure=False)
            self.call("finish_sketch_edit", cancel=True, measure=False)
            self.assertEqual(self.doc.Draft.GeometryCount, 0)
            self.call("begin_sketch_edit", feature="Draft", measure=False)
            self.call("add_circle", sketch="Draft", x=2, y=2, diameter=1, construction=True, measure=False)
            self.call("finish_sketch_edit", cancel=False, measure=False)
            self.assertEqual(self.doc.Draft.GeometryCount, 1)
            for level in (False, True):
                before = self.invariant()
                self.core.inspect(self.doc, measure=level)
                self.assertEqual(self.invariant(), before)
            before = self.invariant()
            self.assertIsNotNone(self.core.checkpoint(self.doc, force=True))
            self.assertEqual(self.invariant(), before)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, 1000 - 2 * math.pi)
        self.publish(["All real interactive operations performed zero Python-visible BRepChecks",
                      "Sketch Cancel/Finish and checkpoint preserve native geometry/history"])

    def test_check_geometry_reports_invalid_solid_and_export_rejects_it(self):
        self.bow_tie()
        before = self.invariant()
        with patch.object(geometry, "check_shape", wraps=geometry.check_shape) as check:
            self.call("check_geometry", body="BowTie", measure=False)
            self.assertEqual(check.call_count, 1)
            report = self.state["geometry_check_report"]
            self.assertEqual(report["status"], "invalid")
            self.assertEqual(report["revision"], before["revision"])
            self.assertEqual([entry["id"] for entry in report["bodies"]], ["BowTie"])
            self.assertTrue(any("Self-intersecting wire" in issue for entry in report["bodies"] for issue in entry["issues"]))
            self.assertEqual(self.state["build_status"], "failed")
            self.assertEqual(self.state["geometry_check"], "invalid")
            self.call("check_geometry", body="BowTie", measure=False)
            self.assertEqual(check.call_count, 1)
            path = self.folder / "invalid.step"
            self.reject("export", path=str(path))
            self.assertEqual(check.call_count, 1)
            self.absent_export(path)
        after = self.invariant()
        self.assertEqual(after["revision"], before["revision"])
        self.assertEqual(after["intent_sha256"], before["intent_sha256"])
        self.assertEqual(after["undo_names"], before["undo_names"])
        self.assertEqual([row for row in after["objects"] if row["name"] != METADATA],
                         [row for row in before["objects"] if row["name"] != METADATA])
        self.publish(["Invalid native bow-tie reports useful explicit cached issues", "Failed export writes no pair or stage"],
                     geometry_check_report=report)

    def test_export_checks_once_per_shape_and_rechecks_after_change(self):
        self.plate()
        with patch.object(geometry, "check_shape", wraps=geometry.check_shape) as check:
            for extension in ("step", "stl"):
                path = self.folder / ("solid." + extension)
                before = self.invariant()
                self.call("export", path=str(path), measure=False)
                self.assertEqual(self.invariant(), before)
                self.assertEqual(check.call_count, 1)
                provenance = json.loads(path.with_suffix(path.suffix + ".json").read_text(encoding="utf-8"))
                self.assertEqual(provenance["geometry_check"]["status"], "valid")
                self.assertIs(provenance["shape"]["valid"], True)
                self.assertEqual(provenance["shape"]["solid_count"], 1)
                self.assertAlmostEqual(provenance["shape"]["volume_mm3"], 1200)
                for actual, expected in zip(provenance["shape"]["center_of_mass_mm"], (10, 5, 3)):
                    self.assertAlmostEqual(actual, expected)
                self.assertEqual(provenance["sha256"], digest(path))
            self.doc.openTransaction("Move checked native Body")
            self.doc.Body.Placement = App.Placement(App.Vector(7, 11, 13), App.Rotation())
            self.doc.recompute()
            self.doc.commitTransaction()
            self.state = self.core.inspect(self.doc, measure=False)
            moved = self.folder / "moved.step"
            self.call("export", path=str(moved), measure=False)
            self.assertEqual(check.call_count, 1, "Placement changes cannot recheck unchanged source topology")
            moved_shape = json.loads(moved.with_suffix(".step.json").read_text(encoding="utf-8"))["shape"]
            for actual, expected in zip(moved_shape["center_of_mass_mm"], (17, 16, 16)):
                self.assertAlmostEqual(actual, expected)
            self.call("set_parameter", feature="Pad", parameter="Length", value=7, measure=False)
            self.call("export", path=str(self.folder / "changed.step"), measure=False)
            self.assertEqual(check.call_count, 2)
            self.call("export", path=str(self.folder / "changed.stl"), measure=False)
            self.assertEqual(check.call_count, 2)
        self.publish(["STEP/STL share one check until native shape changes", "Export carries full measured geometry and hash evidence"])

    def test_export_rejects_invalid_geometry_before_writing(self):
        self.bow_tie()
        before = self.invariant()
        with patch.object(geometry, "check_shape", wraps=geometry.check_shape) as check:
            path = self.folder / "unchecked.step"
            response = self.reject("export", code="invalid_geometry", path=str(path), measure=False)
            self.assertEqual(check.call_count, 1)
            self.absent_export(path)
        self.assertEqual(self.core._meta(self.doc).Revision, before["revision"])
        self.assertEqual(intent_signature(self.doc), before["intent_sha256"])
        self.assertEqual(self.doc.UndoNames, before["undo_names"])
        self.assertEqual(self.doc.RedoNames, before["redo_names"])
        self.publish(["First unchecked invalid export checks before either stage", "Rejection preserves native revision and undo"],
                     rejection=response["error"])

    def test_measure_levels_and_per_object_cache(self):
        self.plate()
        self.call("create_body", id="SecondBody", measure=False)
        self.call("sketch_rectangle", body="SecondBody", id="SecondProfile", width=3, height=4, measure=False)
        self.call("pad", body="SecondBody", id="SecondPad", profile="SecondProfile", length=5, measure=False)
        before = self.invariant()
        cheap = self.core.inspect(self.doc, measure=False)
        self.assertEqual(cheap["measurements"]["solid_count"], 2)
        for field in ("valid", "volume_mm3", "area_mm2", "bbox_mm", "center_of_mass_mm"):
            self.assertIsNone(cheap["measurements"][field])
        measured = self.core.inspect(self.doc)
        self.assertAlmostEqual(measured["measurements"]["volume_mm3"], 1260)
        self.assertIsNotNone(measured["measurements"]["bbox_mm"])
        self.assertIsNone(measured["measurements"]["center_of_mass_mm"])
        full = self.core.inspect(self.doc, measure="full")
        expected = [(1200 * a + 60 * b) / 1260 for a, b in zip((10, 5, 3), (1.5, 2, 2.5))]
        for actual, wanted in zip(full["measurements"]["center_of_mass_mm"], expected):
            self.assertAlmostEqual(actual, wanted)
        self.assertEqual(self.invariant(), before)
        cached = deepcopy(self.core.geometry.stats["computed"])
        for _ in range(5):
            self.core.inspect(self.doc, measure="full")
        self.assertEqual(self.core.geometry.stats["computed"], cached)
        second = deepcopy(self.core.geometry.facts(self.doc.SecondBody, geometry.LEVELS["full"]))
        self.doc.Pad.Length = 9
        pending = self.core.inspect(self.doc, measure=False)
        self.assertEqual(pending["build_status"], "needs_rebuild")
        self.assertEqual(self.core.geometry.stats["computed"], cached)
        self.doc.recompute()
        self.state = self.core.inspect(self.doc)
        self.assertAlmostEqual(self.state["measurements"]["volume_mm3"], 1860)
        self.assertEqual(self.core.geometry.stats["computed"].get("volume", 0), cached.get("volume", 0) + 1)
        self.assertEqual(self.core.geometry.facts(self.doc.SecondBody, geometry.LEVELS["full"]), second)
        self.doc.openTransaction("Abort cached geometry edit")
        self.doc.Pad.Length = 11
        self.doc.recompute()
        self.assertAlmostEqual(self.core.inspect(self.doc)["measurements"]["volume_mm3"], 2260)
        self.doc.abortTransaction()
        self.doc.recompute()
        self.state = self.core.inspect(self.doc)
        self.assertAlmostEqual(self.state["measurements"]["volume_mm3"], 1860)
        undo_volume = self.doc.Body.Shape.Volume
        self.call("set_parameter", feature="Pad", parameter="Length", value=10, measure=False)
        self.call("undo")
        self.assertAlmostEqual(self.state["measurements"]["volume_mm3"], 1860)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, undo_volume)
        self.call("redo")
        self.assertAlmostEqual(self.state["measurements"]["volume_mm3"], 2060)
        shape = self.doc.addObject("Part::Feature", "CacheNameReuse")
        shape.Shape = Part.makeBox(1, 2, 3)
        self.doc.recompute()
        self.assertAlmostEqual(self.core.geometry.facts(shape, ("volume",))["volume"], 6)
        name = shape.Name
        self.doc.removeObject(name)
        replacement = self.doc.addObject("Part::Feature", name)
        replacement.Shape = Part.makeBox(2, 2, 2)
        self.doc.recompute()
        self.assertEqual(replacement.Name, name, "Pinned native name-reuse fixture must exercise the deleted cache key")
        self.assertAlmostEqual(self.core.geometry.facts(replacement, ("volume",))["volume"], 8)
        sources = (self.doc.Body, self.doc.SecondBody, replacement)
        before_reads = self.invariant()
        kind = "q03_test_real_volume"
        checks_before = self.core.geometry.stats["computed"]["check"]
        pairs_before = self.core.geometry.stats["memo"].get(kind, 0)
        with patch.object(self.core.geometry, "CHECK_LIMIT", 2), patch.object(self.core.geometry, "PAIR_LIMIT", 2):
            for source, expected_volume in zip(sources, (2000, 60, 8)):
                verdict = self.core.geometry.check(source, compute=True)
                self.assertTrue(verdict["valid"], verdict)
                value = self.core.geometry.memo(kind, (source,), (),
                                                lambda source=source: geometry.scalar(source.Shape, "volume"))
                self.assertAlmostEqual(value, expected_volume)
            self.assertEqual(self.core.geometry.stats["computed"]["check"], checks_before + 3)
            self.assertEqual(self.core.geometry.stats["memo"][kind], pairs_before + 3)
            self.assertIsNone(self.core.geometry.check(sources[0]), "Oldest real shape verdict must be evicted")
            self.assertTrue(self.core.geometry.check(sources[0], compute=True)["valid"])
            self.assertAlmostEqual(self.core.geometry.memo(kind, (sources[0],), (),
                                   lambda: geometry.scalar(sources[0].Shape, "volume")), 2000)
            self.assertEqual(self.core.geometry.stats["computed"]["check"], checks_before + 4)
            self.assertEqual(self.core.geometry.stats["memo"][kind], pairs_before + 4)
            self.assertEqual(self.invariant(), before_reads)
            replacement.Shape = Part.makeBox(3, 3, 3)
            self.doc.recompute()
            self.state = self.core.inspect(self.doc, measure=False)
            changed_before_reads = self.invariant()
            self.assertTrue(self.core.geometry.check(replacement, compute=True)["valid"])
            self.assertAlmostEqual(self.core.geometry.memo(kind, (replacement,), (),
                                   lambda: geometry.scalar(replacement.Shape, "volume")), 27)
            self.assertAlmostEqual(self.core.geometry.facts(replacement, ("volume",))["volume"], 27)
            self.assertEqual(self.core.geometry.stats["memo"][kind], pairs_before + 5)
            self.assertEqual(self.invariant(), changed_before_reads)
        self.publish(["False/true/full have exact nullable measurement levels", "One changed Body integrates volume exactly once",
                      "Abort and native name reuse cannot expose stale cached facts",
                      "Bounded real shape/pair eviction recomputes truthfully without changing native state"])

    def test_open_trusts_stored_shapes_without_recompute(self):
        def native_maps(doc):
            before = snapshot_document(doc, self.core)["strict"]
            rows = {}
            for name in ("Body", "Pad", "Plate"):
                obj = doc.getObject(name)
                shape = obj.Shape
                mapping = dict(shape.ElementMap)
                self.assertTrue(mapping, name)
                version = obj.getElementMapVersion("Shape")
                self.assertTrue(version, name)
                self.assertEqual(shape.ElementMapVersion, version)
                self.assertEqual(obj.ElementMapVersion, version)
                for mapped, legacy in mapping.items():
                    self.assertTrue(shape.getElement(mapped).isSame(shape.getElement(legacy)),
                                    (name, mapped, legacy))
                rows[name] = {"version": version, "size": shape.ElementMapSize,
                              "map": mapping, "reverse_map": dict(shape.ElementReverseMap)}
            self.assertEqual(snapshot_document(doc, self.core)["strict"], before,
                             "Native map reads must preserve every modeled state field")
            return rows

        saved = self.stored()
        original = digest(saved)
        saved_maps = native_maps(self.doc)
        self.assertEqual(self.doc.Body._ElementMapVersion, saved_maps["Body"]["version"])
        with zipfile.ZipFile(saved) as archive:
            document = ET.fromstring(archive.read("Document.xml"))
            for name, mapping in saved_maps.items():
                shape = document.find("./ObjectData/Object[@name='" + name +
                                      "']/Properties/Property[@name='Shape']/Part")
                self.assertIsNotNone(shape, name)
                self.assertEqual(shape.get("ElementMap"), mapping["version"])
                self.assertTrue(archive.read(name + ".Shape.Map.txt"), name)
        original_name = self.doc.Name
        App.closeDocument(original_name)
        self.assertNotIn(original_name, App.listDocuments(), "Close the source before capturing stored native output")
        native_names_before = set(App.listDocuments())
        native = App.openDocument(str(saved))
        raw = {obj.Name: obj.Shape.exportBrepToString() for obj in (native.Body, native.Pad, native.Plate)}
        self.assertNotIn(native.Name, native_names_before, "Stored baseline must come from a fresh owned native document")
        flags = {obj.Name: list(obj.State) for obj in (native.Body, native.Pad, native.Plate)}
        raw_maps = native_maps(native)
        self.assertEqual(raw_maps, saved_maps)
        App.closeDocument(native.Name)
        self.reopen(saved)
        self.assertEqual(self.state["build_status"], "valid")
        self.assertIsNone(self.state["rebuild_reason"])
        self.assertEqual(self.state["geometry_check"], "not_checked")
        for name in raw:
            self.assertEqual(self.doc.getObject(name).Shape.exportBrepToString(), raw[name])
            self.assertEqual(list(self.doc.getObject(name).State), flags[name])
        managed_maps = native_maps(self.doc)
        self.assertEqual(managed_maps, raw_maps)
        self.assertEqual(self.doc.Body._ElementMapVersion, managed_maps["Body"]["version"])
        self.assertEqual(self.doc.Body.Tip.Name, "Pad")
        self.assertAlmostEqual(self.state["measurements"]["volume_mm3"], 1200)
        App.closeDocument(self.doc.Name)
        native = App.openDocument(str(saved))
        native.UseHasher = True
        native.recompute()
        migration = self.folder / "hasher.FCStd"
        native.saveCopy(str(migration))
        App.closeDocument(native.Name)
        self.reopen(migration, expected_recomputes=1)
        self.assertIs(self.doc.UseHasher, False)
        self.assertEqual(self.state["build_status"], "valid")
        self.assertIsNone(self.state["rebuild_reason"])
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, 1200)
        self.assertEqual(self.doc.KurtShapeProject.EngineOCCT, Part.OCC_VERSION)
        self.assertEqual(digest(saved), original)
        self.publish(["False-hasher open trusts exact native stored shapes and flags",
                      "Saved, raw-open and managed-open native maps and mapped element identities are exact",
                      "Managed Body display version agrees with its measured native map version",
                      "True-hasher migration rebuilds exactly once and stamps"],
                     stored_native_maps=saved_maps, raw_open_native_maps=raw_maps,
                     managed_open_native_maps=managed_maps)

    def test_open_with_different_engine_offers_rebuild_and_blocks_export(self):
        saved = self.stored()
        original_sha = digest(saved)
        self.doc.KurtShapeProject.EngineOCCT = "Q03 deliberately different OCCT"
        altered = self.folder / "engine.FCStd"
        self.doc.saveCopy(str(altered))
        self.reopen(altered)
        self.assertEqual(self.state["build_status"], "needs_rebuild")
        self.assertEqual(self.state["rebuild_reason"], "engine_changed")
        self.assertIsNone(self.state["measurements"])
        self.assertAlmostEqual(self.state["retained_geometry_measurements"]["volume_mm3"], 1200)
        path = self.folder / "blocked.step"
        self.reject("export", path=str(path))
        self.absent_export(path)
        undo = self.doc.UndoCount
        self.call("rebuild")
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.assertEqual(self.state["build_status"], "valid")
        self.assertIsNone(self.state["rebuild_reason"])
        self.assertEqual(self.doc.KurtShapeProject.EngineOCCT, Part.OCC_VERSION)
        self.call("undo")
        self.assertEqual(self.state["rebuild_reason"], "engine_changed")
        self.assertEqual(self.doc.KurtShapeProject.EngineOCCT, "Q03 deliberately different OCCT")
        self.assertEqual(digest(saved), original_sha)
        self.publish(["Engine mismatch retains geometry but blocks export", "One Rebuild undo restores the prior engine stamp/reason"],
                     original_sha256=digest(saved))

    def test_open_legacy_project_without_engine_stamp_is_unrecorded(self):
        saved = self.stored()
        original_sha = digest(saved)
        self.doc.KurtShapeProject.removeProperty("EngineFreeCAD")
        self.doc.KurtShapeProject.removeProperty("EngineOCCT")
        legacy = self.folder / "legacy.FCStd"
        self.doc.saveCopy(str(legacy))
        self.reopen(legacy)
        self.assertEqual(self.state["rebuild_reason"], "engine_unrecorded")
        self.assertEqual(self.state["build_status"], "needs_rebuild")
        self.assertAlmostEqual(self.state["retained_geometry_measurements"]["volume_mm3"], 1200)
        self.call("rebuild")
        self.assertIsNone(self.state["rebuild_reason"])
        self.assertEqual(self.state["build_status"], "valid")
        self.assertEqual(self.doc.KurtShapeProject.EngineFreeCAD, ".".join(App.Version()[:3]))
        self.call("export", path=str(self.folder / "legacy.step"))
        self.assertEqual(digest(saved), original_sha)
        self.publish(["Missing stamps require an explicit rebuild without open recompute", "Rebuilt legacy geometry is stamped and exportable"],
                     original_sha256=digest(saved))

    def test_open_persisted_touched_and_failed_states_without_rebuilding(self):
        saved = self.stored()
        original_sha = digest(saved)
        self.call("sketch_circle", id="Hole", x=10, y=5, diameter=2)
        self.call("pocket", id="Pocket", profile="Hole", length=2, through_all=False)
        self.doc.Pocket.Length = 0
        self.doc.recompute()
        self.assertTrue(set(self.doc.Pocket.State) & {"Invalid", "Error"})
        failed = self.folder / "failed.FCStd"
        self.doc.saveCopy(str(failed))
        self.reopen(failed)
        self.assertTrue(set(self.doc.Pocket.State) & {"Invalid", "Error"})
        self.assertFalse(self.doc.Pocket.Shape.isNull(), "Pinned Windows failed feature retains its actual stored shape")
        self.assertEqual(self.state["build_status"], "failed")
        self.assertIsNone(self.state["rebuild_reason"])
        self.call("set_parameter", feature="Pocket", parameter="Length", value=2)
        self.assertEqual(self.state["build_status"], "valid")
        self.assertAlmostEqual(self.state["measurements"]["volume_mm3"], 1200 - 2 * math.pi)
        App.closeDocument(self.doc.Name)
        native = App.openDocument(str(saved))
        native.Pad.Length = 7
        self.assertIn("Touched", native.Pad.State)
        touched = self.folder / "touched.FCStd"
        native.saveCopy(str(touched))
        App.closeDocument(native.Name)
        self.reopen(touched)
        self.assertIn("Touched", self.doc.Pad.State)
        self.assertEqual(self.state["build_status"], "needs_rebuild")
        self.assertIsNone(self.state["rebuild_reason"])
        self.assertAlmostEqual(self.state["retained_geometry_measurements"]["volume_mm3"], 1200)
        self.call("rebuild")
        self.assertAlmostEqual(self.state["measurements"]["volume_mm3"], 1400)
        self.assertEqual(digest(saved), original_sha)
        self.publish(["Saved failed nonnull Pocket remains failed and repairs without Rebuild", "Stored Touched flags retain geometry until explicit Rebuild"])

    def test_open_missing_stored_shape_offers_rebuild(self):
        saved = self.stored()
        before = digest(saved)
        missing = self.folder / "missing.FCStd"
        with zipfile.ZipFile(saved) as archive:
            self.assertEqual(archive.namelist().count("Pad.Shape.brp"), 1)
        rewrite_archive(saved, missing, omit=("Pad.Shape.brp",))
        self.reopen(missing)
        self.assertTrue(self.doc.Pad.Shape.isNull())
        self.assertNotIn("Touched", self.doc.Pad.State)
        self.assertEqual(self.state["rebuild_reason"], "missing_shapes")
        self.assertEqual(self.doc.KurtShapeProject.RebuildReason, "")
        self.call("rebuild")
        self.assertIsNone(self.state["rebuild_reason"])
        self.assertEqual(self.state["build_status"], "valid")
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, 1200)
        repaired = self.folder / "repaired.FCStd"
        self.call("save", path=str(repaired))
        self.reopen(repaired)
        self.assertIsNone(self.state["rebuild_reason"])
        self.assertEqual(self.state["build_status"], "valid")
        self.assertEqual(digest(saved), before)
        self.publish(["Exact missing stored Pad BRep produces only a live rebuild reason", "Rebuilt save/reopen restores geometry without modifying the original"])

    def test_open_saved_by_other_program_build_offers_rebuild(self):
        saved = self.stored()
        before = digest(saved)
        other = self.folder / "other.FCStd"
        rewrite_archive(saved, other, transform_xml=set_program_version)
        self.reopen(other)
        self.assertEqual(self.doc.getProgramVersion(), "0.0R1")
        self.assertEqual(self.state["rebuild_reason"], "saved_by_other_build")
        self.assertEqual(self.state["build_status"], "needs_rebuild")
        self.assertAlmostEqual(self.state["retained_geometry_measurements"]["volume_mm3"], 1200)
        path = self.folder / "other.step"
        self.reject("export", path=str(path))
        self.absent_export(path)
        self.call("rebuild")
        self.assertEqual(self.state["build_status"], "valid")
        self.assertIsNone(self.state["rebuild_reason"])
        self.assertEqual(digest(saved), before)
        self.publish(["Different native ProgramVersion opens stored geometry but requires Rebuild", "Original source archive remains byte-identical"])

    def test_adopt_of_file_saved_by_other_build_requires_rebuild(self):
        App.closeDocument(self.doc.Name)
        native = App.newDocument("ForeignBuild" + uuid.uuid4().hex)
        native.UseHasher = False
        shape = native.addObject("Part::Feature", "Solid")
        shape.Shape = Part.makeBox(2, 3, 4)
        native.recompute()
        original = self.folder / "foreign.FCStd"
        native.saveAs(str(original))
        App.closeDocument(native.Name)
        other = self.folder / "foreign-other.FCStd"
        rewrite_archive(original, other, transform_xml=set_program_version)
        self.call("open", path=str(other))
        self.assertFalse(self.state["managed"])
        original_sha = digest(original)
        source_sha = digest(other)
        foreign_id = self.state["document_id"]
        native_names = {obj.Name for obj in self.doc.Objects}
        shape_brep = self.doc.Solid.Shape.exportBrepToString()
        adopted = self.folder / "adopted.FCStd"
        with perf_fixture.timing_events(self.core) as events, recompute_observations() as native_events:
            self.call("adopt", path=str(adopted))
        # Metadata recomputation may occur, but no modeled native feature may be
        # rebuilt by the adoption of an already-false-hasher stored file.
        self.assertIs(self.doc.UseHasher, False)
        self.assertTrue(self.state["managed"])
        self.assertNotEqual(self.state["document_id"], foreign_id)
        self.assertTrue(native_names <= {obj.Name for obj in self.doc.Objects})
        self.assertEqual(self.state["rebuild_reason"], "saved_by_other_build")
        self.assertAlmostEqual(self.state["retained_geometry_measurements"]["volume_mm3"], 24)
        self.assertEqual(self.doc.Solid.Shape.exportBrepToString(), shape_brep)
        self.assertFalse([event for event in native_events["objects"] if event["type"].startswith(
            ("Part::", "PartDesign::", "Sketcher::"))], "Adoption cannot rebuild stored modeled features")
        path = self.folder / "adopted.step"
        self.reject("export", path=str(path))
        self.absent_export(path)
        self.call("rebuild")
        self.assertEqual(self.state["build_status"], "valid")
        self.assertIsNone(self.state["rebuild_reason"])
        self.call("export", path=str(path))
        self.assertEqual(digest(original), original_sha)
        self.assertEqual(digest(other), source_sha)
        self.publish(["Foreign different-build adoption retains native IDs and new managed authority", "Explicit Rebuild required before export; both original inputs remain unchanged"],
                     adoption_native_recompute_events=events["native_recompute"])

    def test_capabilities_contract_3_reports_measurement_and_check_policy(self):
        capabilities = self.core.dispatch({"op": "capabilities"})
        self.assertTrue(capabilities["ok"], capabilities)
        result = capabilities["result"]
        self.assertEqual(result["contract"], 3)
        self.assertEqual(result["contract_revision"], 0)
        self.assertEqual(result["measurement"]["levels"], [False, True, "full"])
        self.assertIs(result["measurement"]["default"], True)
        self.assertEqual(result["geometry_check"]["operation"], "check_geometry")
        self.assertEqual(result["geometry_check"]["export"], "required")
        self.assertIn("check_geometry", result["operations"])
        self.plate()
        before = self.invariant()
        for value in (None, 0, 1, 0.0, 1.0, "true", "false", "FULL", [], {}, float("nan")):
            with self.subTest(measure=repr(value)):
                self.reject("inspect", code="invalid_argument", measure=value)
                self.assertEqual(self.invariant(), before)
        for level in (False, True, "full"):
            state = self.call("inspect", measure=level)
            self.assertEqual(state["revision"], before["revision"])
            self.assertEqual(state["measurements"]["volume_mm3"] is not None, level is not False)
            self.assertEqual(state["measurements"]["center_of_mass_mm"] is not None, level == "full")
        self.assertIsNotNone(self.core.inspect(self.doc, measure=None)["measurements"]["volume_mm3"])
        listed = self.core.dispatch({"op": "list_documents", "measure": False})
        self.assertTrue(listed["ok"], listed)
        self.assertTrue(all(entry["measurements"]["volume_mm3"] is None for entry in listed["result"]["documents"]))
        request = self.request("set_parameter", feature="Pad", parameter="Length", value=7,
                               measure=False, request_id="Q03-measure-replay")
        undo = self.doc.UndoCount
        first = self.core.dispatch(request)
        self.assertTrue(first["ok"], first)
        self.assertIsNone(first["result"]["measurements"]["volume_mm3"])
        self.assertEqual(self.core.dispatch(deepcopy(request)), first)
        self.assertEqual(self.doc.UndoCount, undo + 1)
        for level in (True, "full", None):
            changed = self.core.dispatch({**request, "measure": level})
            self.assertFalse(changed["ok"], changed)
            self.assertEqual(changed["error"]["code"], "request_id_reused")
        omitted = deepcopy(request)
        omitted.pop("measure")
        self.assertEqual(self.core.dispatch(omitted)["error"]["code"], "request_id_reused")
        bad = {**request, "expected_revision": first["result"]["revision"], "value": 8,
               "measure": None, "request_id": "Q03-null-replay"}
        rejected = self.core.dispatch(bad)
        self.assertFalse(rejected["ok"], rejected)
        self.assertEqual(rejected["error"]["code"], "invalid_argument")
        self.assertEqual(self.core.dispatch(deepcopy(bad)), rejected)
        self.assertEqual(self.core.dispatch({**bad, "measure": False})["error"]["code"], "request_id_reused")
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.state = self.core.inspect(self.doc)
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, 1400)
        self.publish(["Contract3 exposes exact measurement/check policies and rejects explicit invalid levels",
                      "Measure participates in canonical retry identity; successful/rejected replay is unchanged"])


class StatusPerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owner = None
        if os.environ.get("KURTSHAPE_PERF") != "1":
            return
        cls.owner = perf_fixture.FixtureOwner(cls.__module__ + "." + cls.__name__ + ".shared_plate_fixture")
        cls.addClassCleanup(cls.owner.close)
        with perf_fixture.preserved_environment():
            cls.fixture_folder = support.isolated_session(cls.owner, prefix="status-performance-plate-")
            cls.original, cls.fixture = perf_fixture.build_plate(cls.fixture_folder)
            cls.original_sha = digest(cls.original)

    def setUp(self):
        support.perf_only(self)
        self.folder = support.isolated_session(self, prefix="status-performance-native-")
        self.names = set(App.listDocuments())
        self.core = Controller()
        self.core.default_measure = False
        self.addCleanup(self._close)
        self.copy = self.folder / "plate.FCStd"
        shutil.copy2(self.original, self.copy)
        response = self.core.dispatch({"op": "open", "path": str(self.copy), "measure": False})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        self.doc = self.core.documents[self.state["document_id"]]
        self.assertIs(self.doc.UseHasher, False)
        self.assertEqual(self.state["build_status"], "valid")
        self.assertIsNone(self.state["rebuild_reason"])
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, self.fixture["expected_volume_mm3"], delta=1e-5)

    def _close(self):
        errors = []
        try:
            self.core.close()
        except Exception as exc:
            errors.append(exc)
        for name in set(App.listDocuments()) - self.names:
            try:
                App.closeDocument(name)
            except Exception as exc:
                errors.append(exc)
        self.assertEqual(digest(self.original), self.original_sha)
        if errors:
            raise errors[0]

    def call(self, op, **args):
        request = {"op": op, "document_id": self.state["document_id"],
                   "expected_revision": self.state["revision"], "measure": False, **args}
        response = self.core.dispatch(request)
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        return self.state

    def publish(self, metrics, checks, budgets=None, extra=None):
        self.assertTrue(all(len(values) == 5 for values in metrics.values()))
        return perf_fixture.write_report(self, metrics, checks, fixture=self.fixture,
                                         budgets=budgets, extra=extra)

    def test_open_does_not_rebuild(self):
        App.closeDocument(self.doc.Name)
        native_ms, managed_ms = [], []
        with no_kernel_checks(self):
            for _ in range(5):
                native, elapsed = perf_fixture.measured(lambda: App.openDocument(str(self.copy)))
                native_ms.append(elapsed)
                try:
                    self.assertIs(native.UseHasher, False)
                    self.assertAlmostEqual(native.Body.Shape.Volume, self.fixture["expected_volume_mm3"], delta=1e-5)
                finally:
                    App.closeDocument(native.Name)
                with perf_fixture.timing_events(self.core) as events, recompute_observations() as native_events:
                    response, elapsed = perf_fixture.measured(lambda: self.core.dispatch(
                        {"op": "open", "path": str(self.copy), "measure": False}))
                managed_ms.append(elapsed)
                self.assertTrue(response["ok"], response)
                self.assertEqual(events["native_recompute"], [])
                self.assertEqual(native_events, {"documents": [], "objects": []})
                self.state = response["result"]
                self.doc = self.core.documents[self.state["document_id"]]
                self.assertEqual(self.state["build_status"], "valid")
                self.assertIsNone(self.state["measurements"]["volume_mm3"])
                App.closeDocument(self.doc.Name)
        native_median = perf_fixture.summary(native_ms)["median_ms"]
        managed_median = perf_fixture.summary(managed_ms)["median_ms"]
        limit = max(300, native_median * .1)
        self.publish({"native_open_ms": native_ms, "managed_open_ms": managed_ms},
                     ["Five managed opens contain zero native_recompute/check events", "Stored 60-hole geometry and original bytes preserved"],
                     extra={"open_overhead": {"median_ms": managed_median - native_median, "limit_ms": limit,
                                               "budget_met": managed_median - native_median <= limit,
                                               "open": managed_median - native_median > limit}})

    def test_idle_and_post_change_inspection_budget(self):
        idle, changed = [], []
        diameter = [index for index, constraint in enumerate(self.doc.H59.Constraints)
                    if constraint.Name == "Diameter"]
        self.assertEqual(len(diameter), 1)
        self.assertEqual(self.doc.H59.Constraints[diameter[0]].Type, "Diameter")
        before = snapshot_document(self.doc, self.core)["strict"]
        computed = deepcopy(self.core.geometry.stats["computed"])
        with no_kernel_checks(self):
            for _ in range(5):
                state, elapsed = perf_fixture.measured(lambda: self.core.inspect(self.doc, measure=False))
                idle.append(elapsed)
                self.assertIsNone(state["measurements"]["volume_mm3"])
            self.assertEqual(snapshot_document(self.doc, self.core)["strict"], before)
            self.assertEqual(self.core.geometry.stats["computed"], computed)
            for index in range(5):
                self.doc.H59.setDatum(diameter[0], App.Units.Quantity(31 + index))
                self.doc.recompute()
                state, elapsed = perf_fixture.measured(lambda: self.core.inspect(self.doc, measure=False))
                changed.append(elapsed)
                self.assertEqual(state["build_status"], "valid")
                self.assertIsNone(state["measurements"]["volume_mm3"])
            self.assertEqual(self.core.geometry.stats["computed"], computed)
        expected = self.fixture["expected_volume_mm3"] - math.pi * ((35 / 2) ** 2 - 15 ** 2) * 12
        self.assertAlmostEqual(self.doc.Body.Shape.Volume, expected, delta=1e-5)
        self.publish({"idle_inspect_ms": idle, "inspect_after_change_ms": changed},
                     ["Idle strict native state is unchanged", "Five real shape changes inspected without check or mass integration"],
                     {"idle_inspect_ms": 20, "inspect_after_change_ms": 20})

    def test_tip_edit_overhead_budget(self):
        total, native, overhead = [], [], []
        with no_kernel_checks(self):
            for index in range(5):
                undo = self.doc.UndoCount
                with perf_fixture.timing_events(self.core) as events:
                    _, elapsed = perf_fixture.measured(lambda: self.call("set_parameter", feature="H59", parameter="Diameter", value=31 + index))
                recompute = sum(events["native_recompute"])
                self.assertGreater(len(events["native_recompute"]), 0)
                self.assertGreaterEqual(elapsed, recompute)
                self.assertEqual(self.doc.UndoCount, undo + 1)
                self.assertAlmostEqual(self.doc.H59.Geometry[0].Radius, (31 + index) / 2)
                total.append(elapsed)
                native.append(recompute)
                overhead.append(elapsed - recompute)
        self.publish({"tip_edit_total_ms": total, "tip_edit_native_recompute_ms": native,
                      "tip_edit_overhead_ms": overhead},
                     ["Five non-noop tip edits have one undo and exact actual native timing", "Interactive edits perform zero BRepChecks"],
                     {"tip_edit_overhead_ms": 150})

    def test_explicit_check_and_measure_cost_reported(self):
        checks, true_ms, full_ms = [], [], []
        for _ in range(5):
            # A fresh Controller/native reopen gives every explicit sample the
            # same complete shape and empty fact/check cache, without rebuilding.
            App.closeDocument(self.doc.Name)
            self.core.close()
            self.core = Controller()
            self.core.default_measure = False
            response = self.core.dispatch({"op": "open", "path": str(self.copy), "measure": False})
            self.assertTrue(response["ok"], response)
            self.state = response["result"]
            self.doc = self.core.documents[self.state["document_id"]]
            before = snapshot_document(self.doc, self.core)["strict"]
            with patch.object(geometry, "check_shape", wraps=geometry.check_shape) as check:
                _, elapsed = perf_fixture.measured(lambda: self.call("check_geometry", body="Body"))
                checks.append(elapsed)
                self.assertEqual(check.call_count, 1)
                self.assertEqual(self.state["geometry_check"], "valid")
                measured, elapsed = perf_fixture.measured(lambda: self.core.inspect(self.doc, measure=True))
                true_ms.append(elapsed)
                full, elapsed = perf_fixture.measured(lambda: self.core.inspect(self.doc, measure="full"))
                full_ms.append(elapsed)
                self.assertAlmostEqual(measured["measurements"]["volume_mm3"], self.fixture["expected_volume_mm3"], delta=1e-5)
                self.assertIsNone(measured["measurements"]["center_of_mass_mm"])
                self.assertIsNotNone(full["measurements"]["center_of_mass_mm"])
                cached = deepcopy(self.core.geometry.stats["computed"])
                self.call("check_geometry", body="Body")
                self.core.inspect(self.doc, measure="full")
                self.assertEqual(check.call_count, 1)
                self.assertEqual(self.core.geometry.stats["computed"], cached)
                self.assertEqual(snapshot_document(self.doc, self.core)["strict"], before)
        self.publish({"explicit_check_ms": checks, "explicit_true_measure_ms": true_ms,
                      "explicit_full_measure_ms": full_ms},
                     ["Explicit check/mass cost is separately measured", "Cached repeated reads preserve full native state and do no repeated work"],
                     extra={"measure": None, "measurement_levels": [False, True, "full"]})
