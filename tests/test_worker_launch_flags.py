"""Private worker children import the standard library, not same-named package modules.

Each worker (exact preview, geometry check, STEP export, render) runs its own
file in src/kurtshape as a script. Python then puts that folder first on
sys.path, where kurtshape/selectors.py stands in for the standard-library
selectors module that socketserver, asyncio and http.server import; the import
fails with "attempted relative import with no known parent package". Nothing
the workers import today reaches it, but the 2026-10-16 sweep work did. Since
2026-11-13 every worker child starts with -P (preview_worker.CHILD_PYTHON_FLAGS).
"""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import support  # noqa: F401  (isolated profile and paths)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
from kurtshape.preview_worker import CHILD_PYTHON_FLAGS

EXECUTABLE = Path(App.getHomePath()) / "bin" / ("python.exe" if os.name == "nt" else "python")
SOURCE = ROOT / "src" / "kurtshape"
PROBE = "import socketserver\nimport sys\nsys.stdout.write(socketserver.selectors.__file__)\n"
LAUNCH = re.compile(r"\[\s*self\.executable\s*,\s*([^,\]]+)")


class WorkerLaunchFlagTests(unittest.TestCase):
    def run_probe(self, flags):
        """Run a script that sits beside a package-style module named like a stdlib module."""
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / "selectors.py").write_text("from . import missing\n", encoding="utf-8")
            (folder / "probe.py").write_text(PROBE, encoding="utf-8")
            return subprocess.run([str(EXECUTABLE), *flags, str(folder / "probe.py")], cwd=folder,
                                  capture_output=True, text=True, timeout=120,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def test_worker_flags_keep_the_script_folder_off_sys_path(self):
        shadowed = self.run_probe(["-B"])
        self.assertNotEqual(shadowed.returncode, 0, "premise: without -P the folder's selectors.py is imported")
        self.assertIn("relative import", shadowed.stderr)
        clean = self.run_probe(CHILD_PYTHON_FLAGS)
        self.assertEqual(clean.returncode, 0, clean.stderr)
        self.assertEqual(Path(clean.stdout).parent.name.lower(), "lib", clean.stdout)

    def test_every_worker_launch_uses_the_shared_flags(self):
        launches = []
        for path in sorted(SOURCE.rglob("*.py")):
            for match in LAUNCH.finditer(path.read_text(encoding="utf-8")):
                launches.append((path.name, match.group(1).strip()))
        self.assertGreaterEqual(len(launches), 4, launches)
        self.assertEqual([item for item in launches if item[1] != "*CHILD_PYTHON_FLAGS"], [])
        self.assertEqual(CHILD_PYTHON_FLAGS[:2], ("-B", "-P"))


if __name__ == "__main__":
    unittest.main()
