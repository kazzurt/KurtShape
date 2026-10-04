"""Native file facts and private fixture guards, independent of parked recovery work."""
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid
import xml.etree.ElementTree as ET
import zipfile

import support

sys.path.insert(0, str(support.ROOT / "src"))
import FreeCAD as App
import Part
from kurtshape.assembly import canonical_brep
from kurtshape.core import intent_signature
from kurtshape.recovery import RecoveryStore


class NativeFileBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.folder = support.isolated_session(self, prefix="native-file-behavior-")
        self.names = set(App.listDocuments())
        self.addCleanup(self._close_documents)
        self.evidence = support._native_fixture_path(os.environ["KURTSHAPE_EVIDENCE_DIR"], support.TEST_TMP)
        self.receipt_path = self.evidence / "native-fixtures" / (self.folder.name + ".json")
        self.receipt = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(self.receipt["fixture"], str(self.folder))
        self.assertEqual(self.receipt["test_id"], self.id())
        self.assertEqual(self.receipt["pid"], os.getpid())
        self.assertLessEqual(self.receipt["recovery_stage_path_length"], 197)
        self.assertEqual(Path(App.getHomePath()).resolve(), support.ROOT / "runtime" / "freecad-1.1.4"
                         / "FreeCAD_1.1.4-Windows-x86_64-py311")
        self.source_before = self._sources()

    def _close_documents(self):
        for name in set(App.listDocuments()) - self.names:
            App.closeDocument(name)

    @staticmethod
    def _sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _sources(self):
        paths = ("tests/support.py", "tests/test_native_files.py", "run-checks.ps1",
                 "tools/run_native_tests.py", "src/kurtshape/recovery.py", "src/kurtshape/core.py",
                 "src/kurtshape/assembly.py")
        return {name: self._sha(support.ROOT / name) for name in paths}

    def _publish(self, consequences, files=()):
        self.assertEqual(self._sources(), self.source_before)
        directory = support._native_fixture_path(self.evidence / "native-files", self.evidence)
        support._native_fixture_path(directory, self.evidence).mkdir(parents=True, exist_ok=True)
        output = support._native_fixture_path(directory / (self._testMethodName + ".json"), directory)
        record = {"schema_version": 1, "passed": True, "test_id": self.id(), "pid": os.getpid(),
                  "completed_utc": datetime.now(timezone.utc).isoformat(),
                  "method": "Actual native file consequences and point-in-time fixture guards",
                  "engine": {"FreeCAD": App.Version(), "OCCT": Part.OCC_VERSION,
                             "home": App.getHomePath()},
                  "environment": {name: os.environ[name] for name in support.ISOLATION_VARIABLES},
                  "fixture_receipt": self.receipt, "fixture_receipt_path": str(self.receipt_path),
                  "fixture_receipt_sha256": self._sha(self.receipt_path),
                  "source_sha256": self.source_before, "source_unchanged": True,
                  "files": [{"path": str(path), "sha256": self._sha(path), "bytes": path.stat().st_size}
                            for path in files], "checks": consequences,
                  "limits": ["GUI Modified is unavailable in this headless native proof.",
                             "Path and identity guards are point-in-time checks, not a race-free guarantee.",
                             "No performance or parked recovery implementation claim."]}
        with output.open("x", encoding="utf-8") as stream:
            json.dump(record, stream, indent=2, allow_nan=False)
            stream.write("\n")

    def _box(self):
        doc = App.newDocument("NativeFile" + uuid.uuid4().hex)
        solid = doc.addObject("Part::Feature", "Solid")
        solid.Shape = Part.makeBox(2, 2, 2)
        doc.recompute()
        return doc

    def _geometry(self, doc, volume):
        shape = doc.Solid.Shape
        self.assertFalse(shape.isNull())
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids), 1)
        self.assertAlmostEqual(shape.Volume, volume)
        return {"valid": True, "solid_count": len(shape.Solids), "volume_mm3": shape.Volume,
                "brep_sha256": hashlib.sha256(canonical_brep(shape.exportBrepToString()).encode()).hexdigest()}

    @staticmethod
    def _native_state(doc):
        return {"filename": doc.FileName, "label": doc.Label, "undo_mode": doc.UndoMode,
                "use_hasher": doc.UseHasher, "undo": list(doc.UndoNames), "redo": list(doc.RedoNames),
                "pending": doc.HasPendingTransaction, "intent": intent_signature(doc),
                "objects": [{"name": obj.Name, "type": obj.TypeId, "state": list(obj.State),
                             "status": obj.getStatusString(),
                             "shape_status": list(obj.getPropertyStatus("Shape")),
                             "brep_sha256": hashlib.sha256(canonical_brep(
                                 obj.Shape.exportBrepToString()).encode()).hexdigest()}
                            for obj in doc.Objects]}

    def _document_label(self, path):
        with zipfile.ZipFile(path) as archive:
            self.assertIsNone(archive.testzip())
            xml = archive.read("Document.xml")
        self.assertTrue(xml.endswith(b"\n"))
        root = ET.fromstring(xml)
        self.assertEqual(root.tag, "Document")
        properties = root.findall("./Properties/Property[@name='Label']")
        self.assertEqual(len(properties), 1)
        self.assertEqual(properties[0].get("type"), "App::PropertyString")
        strings = properties[0].findall("String")
        self.assertEqual(len(strings), 1)
        self.assertIn("value", strings[0].attrib)
        return {"label": strings[0].get("value"), "document_xml_sha256": hashlib.sha256(xml).hexdigest(),
                "document_xml_bytes": len(xml)}

    def test_first_saveas_and_persisted_copy_label_are_distinct_from_default_raw_open_label(self):
        doc = self._box()
        requested = "Custom native file label"
        doc.Label = requested
        original = self.folder / "first-save.FCStd"
        doc.saveAs(str(original))
        self.assertEqual(doc.Label, original.stem)
        self.assertNotEqual(doc.Label, requested)
        original_sha = self._sha(original)
        doc.Label = requested
        doc.UndoMode = 1
        doc.openTransaction("Edit owned native solid")
        doc.Solid.Shape = Part.makeBox(3, 3, 3)
        doc.recompute()
        doc.commitTransaction()
        self._geometry(doc, 27)
        before = self._native_state(doc)
        copy = self.folder / "post-save-label.FCStd"
        doc.saveCopy(str(copy))
        after = self._native_state(doc)
        self.assertEqual(after, before)
        self.assertEqual(self._sha(original), original_sha)
        copy_xml = self._document_label(copy)
        self.assertEqual(copy_xml["label"], requested)
        doc.undo()
        doc.recompute()
        undo_geometry = self._geometry(doc, 8)
        doc.redo()
        doc.recompute()
        redo_geometry = self._geometry(doc, 27)
        App.closeDocument(doc.Name)
        reopened = App.openDocument(str(copy))
        copy_reopened_label = reopened.Label
        self.assertEqual(copy_reopened_label, copy.stem)
        copy_geometry = self._geometry(reopened, 27)
        App.closeDocument(reopened.Name)
        saved = App.openDocument(str(original))
        self.assertEqual(saved.Label, original.stem)
        original_geometry = self._geometry(saved, 8)
        App.closeDocument(saved.Name)
        self.assertEqual(self._sha(original), original_sha)
        self._publish({"label_before_first_saveAs": requested, "label_after_first_saveAs": original.stem,
                       "first_saveAs_replaces_label": True, "post_save_label": requested,
                       "copy_saved_document_xml": copy_xml, "saved_copy_label_verified": True,
                       "copy_reopened_label": copy_reopened_label, "copy_reopened_filename_stem": copy.stem,
                       "default_raw_open_label_is_filename_stem": True, "saveCopy_native_state_unchanged": True,
                       "native_state_before_copy": before, "native_state_after_copy": after,
                       "copy_geometry": copy_geometry, "original_geometry": original_geometry,
                       "native_undo_geometry": undo_geometry, "native_redo_geometry": redo_geometry,
                       "original_file_unchanged": True}, (original, copy))

    def test_native_filename_preserves_exact_provenance_and_filesystem_identity(self):
        doc = self._box()
        original = self.folder / "native-provenance.FCStd"
        doc.saveAs(str(original))
        App.closeDocument(doc.Name)
        original_sha = self._sha(original)
        reopened = App.openDocument(str(original))
        raw_filename = reopened.FileName
        self.assertIsInstance(raw_filename, str)
        self.assertTrue(raw_filename)
        native_path = Path(raw_filename)
        self.assertEqual(native_path.resolve(strict=True), original.resolve(strict=True))
        self.assertTrue(native_path.samefile(original))
        before = self._native_state(reopened)
        # A directly owned transient identity exercises the existing store. It
        # neither registers foreign mutation authority nor changes native metadata.
        meta = SimpleNamespace(DocumentId=str(uuid.uuid4()), Revision=str(uuid.uuid4()))
        store = RecoveryStore(self.folder)
        manifest = store.capture(reopened, meta, force=True)
        snapshot, record = store.read(manifest)
        self.assertEqual(record["schema"], 1)
        self.assertEqual(record["source_file"], raw_filename)
        self.assertEqual(record["name"], before["label"])
        self.assertEqual(record["document_id"], meta.DocumentId)
        self.assertEqual(record["revision"], meta.Revision)
        self.assertEqual(record["sha256"], self._sha(snapshot))
        snapshot_xml = self._document_label(snapshot)
        self.assertEqual(snapshot_xml["label"], record["name"])
        after = self._native_state(reopened)
        self.assertEqual(after, before)
        self.assertEqual(self._sha(original), original_sha)
        App.closeDocument(reopened.Name)
        captured = App.openDocument(str(snapshot))
        snapshot_reopened_label = captured.Label
        self.assertEqual(snapshot_reopened_label, snapshot.stem)
        captured_geometry = self._geometry(captured, 8)
        App.closeDocument(captured.Name)
        self.assertEqual(self._sha(original), original_sha)
        self._publish({"captured_native_filename": raw_filename, "manifest_source_file": record["source_file"],
                       "exact_native_provenance_preserved": True,
                       "strict_resolved_path": str(native_path.resolve(strict=True)),
                       "filesystem_samefile": True, "native_state_before_capture": before,
                       "native_state_after_capture": after, "capture_native_state_unchanged": True,
                       "snapshot_saved_document_xml": snapshot_xml, "saved_snapshot_label_matches_capture_name": True,
                       "snapshot_reopened_label": snapshot_reopened_label, "snapshot_reopened_filename_stem": snapshot.stem,
                       "default_raw_open_label_is_filename_stem": True,
                       "checkpoint_record": record, "captured_geometry": captured_geometry,
                       "original_file_unchanged": True}, (original, manifest, snapshot))

    @staticmethod
    def _repack(entries):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, data in entries:
                info = zipfile.ZipInfo(name, (2000, 1, 1, 0, 0, 0))
                archive.writestr(info, data)
        return output.getvalue()

    def test_fcstd_end_record_comment_and_genuine_truncation(self):
        doc = self._box()
        original = self.folder / "native-archive.FCStd"
        doc.saveAs(str(original))
        App.closeDocument(doc.Name)
        raw = original.read_bytes()
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertIsNone(archive.testzip())
            xml = archive.read("Document.xml")
            entries = [(name, archive.read(name)) for name in archive.namelist()]
            comment = archive.comment
        self.assertTrue(xml.endswith(b"\n"))
        self.assertEqual(ET.fromstring(xml).tag, "Document")
        eocd = raw.rfind(b"PK\x05\x06")
        self.assertGreaterEqual(eocd, 0)
        self.assertGreaterEqual(len(raw) - eocd, 22)
        declared_comment = struct.unpack_from("<H", raw, eocd + 20)[0]
        self.assertEqual(eocd + 22 + declared_comment, len(raw))
        self.assertEqual(raw[eocd + 22:], comment)
        self.assertGreaterEqual(len(comment), 12)
        comment_only = self.folder / "shortened-comment.FCStd"
        comment_only.write_bytes(raw[:-12])
        with zipfile.ZipFile(comment_only) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(archive.read("Document.xml"), xml)
            self.assertEqual(archive.comment, comment[:-12])
        self.assertNotEqual(eocd + 22 + declared_comment, comment_only.stat().st_size)
        truncated = self.folder / "incomplete-end-record.FCStd"
        truncated.write_bytes(raw[:eocd + 10])
        with self.assertRaises(zipfile.BadZipFile):
            with zipfile.ZipFile(truncated):
                pass
        missing = self.folder / "missing-document-xml.FCStd"
        missing.write_bytes(self._repack([(name, data) for name, data in entries if name != "Document.xml"]))
        with zipfile.ZipFile(missing) as archive:
            self.assertIsNone(archive.testzip())
            with self.assertRaises(KeyError):
                archive.read("Document.xml")
        closing = xml.rfind(b"</Document>")
        self.assertGreater(closing, 0)
        incomplete = self.folder / "incomplete-document-xml.FCStd"
        incomplete.write_bytes(self._repack([(name, xml[:closing] if name == "Document.xml" else data)
                                            for name, data in entries]))
        with zipfile.ZipFile(incomplete) as archive:
            self.assertIsNone(archive.testzip())
            with self.assertRaises(ET.ParseError):
                ET.fromstring(archive.read("Document.xml"))
        crc_raw = bytearray(self._repack(entries))
        with zipfile.ZipFile(io.BytesIO(crc_raw)) as archive:
            header = archive.getinfo("Document.xml").header_offset
        filename_length, extra_length = struct.unpack_from("<HH", crc_raw, header + 26)
        payload = header + 30 + filename_length + extra_length
        self.assertEqual(bytes(crc_raw[payload:payload + len(xml)]), xml)
        crc_raw[payload] ^= 1
        crc_failure = self.folder / "document-crc-failure.FCStd"
        crc_failure.write_bytes(crc_raw)
        with zipfile.ZipFile(crc_failure) as archive:
            with self.assertRaises(zipfile.BadZipFile):
                archive.read("Document.xml")
        self.assertEqual(original.read_bytes(), raw)
        self._publish({"native_xml_sha256": hashlib.sha256(xml).hexdigest(), "native_xml_ends_newline": True,
                       "native_xml_complete": True, "native_zip_crc_verified": True,
                       "native_zip_members": [{"name": name, "bytes": len(data),
                                               "sha256": hashlib.sha256(data).hexdigest()} for name, data in entries],
                       "eocd_offset": eocd, "eocd_fixed_bytes": 22, "declared_comment_bytes": declared_comment,
                       "native_comment_hex": comment.hex(), "eocd_declared_end_matches_eof": True,
                       "comment_only_truncation_retains_readable_xml": True,
                       "comment_only_truncation_breaks_declared_end": True,
                       "incomplete_eocd_rejected": True, "missing_document_xml_rejected": True,
                       "incomplete_xml_rejected": True, "document_payload_crc_failure_rejected": True,
                       "original_file_unchanged": True},
                      (original, comment_only, truncated, missing, incomplete, crc_failure))

    def test_fixture_cleanup_rejects_redirected_or_replaced_directory(self):
        identity = (1, 2, 3)
        for failure in ("redirected", "replaced"):
            with self.subTest(failure=failure):
                temporary = SimpleNamespace(_finalizer=Mock(), cleanup=Mock())
                path_check = RuntimeError("Controlled redirect") if failure == "redirected" else self.folder
                with patch.object(support, "_native_fixture_path", side_effect=path_check if isinstance(
                        path_check, Exception) else None, return_value=self.folder), patch.object(
                        support, "_native_fixture_identity", return_value=(1, 999, 3)):
                    with self.assertRaises(RuntimeError):
                        support._cleanup_native_fixture(temporary, self.folder, self.folder.parent, identity)
                temporary._finalizer.detach.assert_called_once_with()
                temporary.cleanup.assert_not_called()
        temporary = SimpleNamespace(_finalizer=Mock(), cleanup=Mock())
        with patch.object(support, "_native_fixture_path", return_value=self.folder), patch.object(
                support, "_native_fixture_identity", return_value=identity):
            support._cleanup_native_fixture(temporary, self.folder, self.folder.parent, identity)
        temporary.cleanup.assert_called_once_with()
        temporary._finalizer.detach.assert_not_called()
        self._publish({"redirected_cleanup_rejected": True, "ordinary_replacement_cleanup_rejected": True,
                       "suspect_fixture_finalizer_detached": True, "suspect_fixture_not_deleted": True,
                       "same_identity_cleanup_control_passed": True, "controlled_doubles_only": True})

    def test_fixture_environment_and_dangling_redirect_guards(self):
        fake_path = Mock()
        fake_path.absolute.return_value = fake_path
        fake_path.parents = ()
        fake_path.is_symlink.return_value = True
        with patch.object(support, "Path", return_value=fake_path):
            with self.assertRaisesRegex(RuntimeError, "symbolic link or junction"):
                support._native_fixture_path("controlled-dangling-link")
        fake_path.exists.assert_not_called()
        fake_path.resolve.assert_not_called()
        fake_path.is_symlink.return_value = False
        fake_path.exists.return_value = True
        fake_path.lstat.return_value = SimpleNamespace(st_file_attributes=1024)
        with patch.object(support, "Path", return_value=fake_path), patch.object(
                support.stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024, create=True):
            with self.assertRaisesRegex(RuntimeError, "symbolic link or junction"):
                support._native_fixture_path("controlled-junction")
        fake_path.resolve.assert_not_called()
        with patch.dict(os.environ, self.receipt["environment"]):
            for name in support.ISOLATION_VARIABLES:
                with self.subTest(missing=name), patch.dict(os.environ, {name: ""}), patch.object(
                        support.tempfile, "TemporaryDirectory") as allocate:
                    with self.assertRaisesRegex(RuntimeError, "require isolated " + name):
                        support.isolated_session(self)
                    allocate.assert_not_called()
            with patch.dict(os.environ, {"KURTSHAPE_SESSION_DIR": str(support.ROOT / "runtime")}), patch.object(
                    support.tempfile, "TemporaryDirectory") as allocate:
                with self.assertRaisesRegex(RuntimeError, "escaped its private parent"):
                    support.isolated_session(self)
                allocate.assert_not_called()
        self._publish({"dangling_symbolic_link_rejected_before_resolution": True,
                       "existing_reparse_point_rejected_before_resolution": True,
                       "all_six_empty_environment_roots_rejected_before_allocation": True,
                       "live_runtime_environment_rejected_before_allocation": True,
                       "no_redirected_or_outside_write_or_delete": True})
