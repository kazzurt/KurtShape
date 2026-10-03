"""Pinned runtime provenance and shared test isolation guarantees."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import support

sys.path.insert(0, str(support.ROOT / "src"))
import FreeCAD as App
import Part
from kurtshape import assembly, contract
from kurtshape.core import Controller


class RuntimeLayoutTests(unittest.TestCase):
    def setUp(self):
        self.folder = support.isolated_session(self, prefix="runtime-layout-session-")

    def test_pinned_engine_versions(self):
        self.assertEqual(tuple(App.Version()[:3]), ("1", "1", "4"))
        self.assertEqual(Part.OCC_VERSION, "7.8.1")

    def test_assembly_module_comes_from_running_runtime(self):
        home = Path(App.getHomePath()).resolve()
        self.assertEqual(assembly.NATIVE_PATH, home / "Mod" / "Assembly")
        native, _ = assembly._native()
        self.assertEqual(Path(native.__file__).resolve().parent, assembly.NATIVE_PATH.resolve())

    def test_other_runtime_version_is_rejected(self):
        with patch.object(App, "Version", return_value=["1", "2", "0", "x"]):
            with self.assertRaises(assembly.AssemblyError) as rejected:
                assembly._native()
        self.assertEqual(rejected.exception.code, "assembly_runtime")

    def test_scratch_never_targets_tracked_folders(self):
        folder = support.scratch(self, prefix="runtime-layout-fixture-")
        self.assertTrue(folder.is_relative_to(support.TEST_TMP))
        for name in ("src", "tests", "docs", "examples", "validation"):
            self.assertFalse(folder.is_relative_to(support.ROOT / name), name)
            self.assertFalse(self.folder.is_relative_to(support.ROOT / name), name)
        self.assertNotEqual(folder, support.ROOT / "runtime")
        self.assertNotEqual(self.folder, support.ROOT / "runtime")

    def test_capabilities_report_shared_contract_constant(self):
        core = Controller()
        self.addCleanup(core.close)
        response = core.dispatch({"op": "capabilities"})
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["result"]["contract"], contract.CONTRACT_VERSION)
        self.assertEqual(response["result"]["contract_revision"], contract.CONTRACT_REVISION)
