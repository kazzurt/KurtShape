"""Exact embedded seals across serialization, without tolerance-based masking."""
import unittest
import zipfile
from unittest.mock import patch
import FreeCAD as App
import Part
import support
from kurtshape import assembly
from kurtshape.assembly_persistence import save_copy, _seal_archive


class AssemblyPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.folder = support.isolated_session(self, prefix="assembly-seal-")
        self.names = set(App.listDocuments())
        self.doc = App.newDocument("SealRegression", hidden=True)
        self.source = self.doc.addObject("Part::Feature", "EmbeddedPart")
        self.source.Shape = Part.makeTorus(50.479194424640504, 22,
            App.Vector(-338.98113751727601, -246.28421259793501, 22.8399742042516),
            App.Vector(.18735110628408988, -.95350077593135429, -.23608437744254279))
        self.source.addProperty("App::PropertyBool", "KurtShapeEmbeddedSource")
        self.source.KurtShapeEmbeddedSource = True
        self.source.addProperty("App::PropertyString", "SourceGeometryFingerprint")
        self.source.SourceGeometryFingerprint = assembly._geometry_fingerprint(self.source)

    def tearDown(self):
        for name in set(App.listDocuments()) - self.names:
            App.closeDocument(name)

    def reopen(self, path):
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(str(path), True)
        self.source = self.doc.EmbeddedPart

    def test_repeated_serialization_matches_exact_seal_and_preserves_shape_bytes(self):
        path = self.folder / "sealed.FCStd"
        for _ in range(4):
            old_hash = assembly._geometry_fingerprint(self.source)
            old_seal = self.source.SourceGeometryFingerprint
            raw = self.folder / "raw.FCStd"
            self.doc.saveCopy(str(raw))
            save_copy(self.doc, path)
            self.assertEqual(old_hash, assembly._geometry_fingerprint(self.source))
            self.assertEqual(old_seal, self.source.SourceGeometryFingerprint)
            with zipfile.ZipFile(raw) as before, zipfile.ZipFile(path) as after:
                self.assertEqual(before.namelist(), after.namelist())
                for name in before.namelist():
                    if name != "Document.xml":
                        self.assertEqual(before.read(name), after.read(name), name)
            self.reopen(path)
            self.assertEqual(assembly._geometry_fingerprint(self.source), self.source.SourceGeometryFingerprint)

    def test_genuine_change_is_not_resealed_even_for_recovery(self):
        path = self.folder / "changed.FCStd"
        prior = self.source.SourceGeometryFingerprint
        # Deliberately bypass managed modeling to emulate native tampering.
        self.source.Shape = Part.makeBox(4, 5, 6)
        self.assertNotEqual(assembly._geometry_fingerprint(self.source), prior)
        save_copy(self.doc, path)
        self.reopen(path)
        self.assertEqual(self.source.SourceGeometryFingerprint, prior)
        self.assertNotEqual(assembly._geometry_fingerprint(self.source), prior)

    def test_placement_and_small_geometric_changes_are_not_masked(self):
        seal = self.source.SourceGeometryFingerprint
        original = self.source.Shape.copy()
        self.source.Placement.Base.x += 1e-7
        self.assertNotEqual(assembly._geometry_fingerprint(self.source), seal)
        self.source.Shape = original
        changed = original.copy()
        changed.translate(App.Vector(0, 0, 1e-9))
        self.source.Shape = changed
        self.assertNotEqual(assembly._geometry_fingerprint(self.source), seal)

    def test_missing_brep_fails_without_replacing_archive(self):
        path = self.folder / "missing-brep.FCStd"
        self.doc.saveCopy(str(path))
        with zipfile.ZipFile(path) as archive:
            entries = [(entry, archive.read(entry.filename)) for entry in archive.infolist()
                       if not entry.filename.endswith(".brp")]
        with zipfile.ZipFile(path, "w") as archive:
            for entry, payload in entries:
                archive.writestr(entry, payload)
        before = path.read_bytes()
        with self.assertRaises(assembly.AssemblyError):
            _seal_archive(path, {self.source.Name: self.source.SourceGeometryFingerprint})
        self.assertEqual(path.read_bytes(), before)

    def test_managed_save_failure_preserves_existing_destination_and_live_file(self):
        from kurtshape.core import Controller
        core = Controller()
        path = self.folder / "existing.FCStd"
        path.write_bytes(b"existing destination")
        old_filename = self.doc.FileName
        try:
            with patch("kurtshape.assembly_persistence._seal_archive", side_effect=assembly.AssemblyError("assembly_runtime", "injected archive failure")):
                with self.assertRaises(assembly.AssemblyError):
                    # claude/slice-ab A8: replacing a non-project file needs overwrite to reach the seal.
                    core._save(self.doc, str(path), True)
            self.assertEqual(path.read_bytes(), b"existing destination")
            self.assertEqual(self.doc.FileName, old_filename)
        finally:
            core.close()
