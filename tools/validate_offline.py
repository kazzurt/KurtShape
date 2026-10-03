"""Repeat native core+conversion checks with Python networking denied.

Does not change system networking; C++ socket calls are not instrumented.
"""
import hashlib
import json
from pathlib import Path
import socket
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(ROOT/"tests"))

def source_snapshot():
    files = sorted((ROOT / "src" / "kurtshape").glob("*.py"))
    files += sorted((ROOT / "tests").glob("test_*.py"))
    files.append(Path(__file__).resolve())
    return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files}

source_sha256 = source_snapshot()

def deny_network(*args,**kwargs):
    raise RuntimeError("Networking disabled for offline modeling validation")

socket.socket.connect=deny_network
socket.create_connection=deny_network
socket.getaddrinfo=deny_network
start=time.perf_counter()
from test_core import NativeCoreTests
from test_onshape import NativeConversionTests,PreflightTests
from test_core_safety import CoreSafetyTests
from test_sketch_planes import SketchPlaneTests
from test_navigation import SketchProjectionTests
from test_review_followup import ReviewFollowupTests
from test_step_import import StepImportTests
from test_assembly import AssemblyWorkflowTests
from test_extrusion_preview import ExtrusionPreviewTests
from test_reference_tools import ReferenceToolTests
from test_selectors import SelectorTests
from test_part_studio import PartStudioTests
from test_selector_consumers import SelectorConsumerTests
suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in [NativeCoreTests,NativeConversionTests,PreflightTests,CoreSafetyTests,SketchPlaneTests,SketchProjectionTests,ReviewFollowupTests,StepImportTests,AssemblyWorkflowTests,ExtrusionPreviewTests,ReferenceToolTests,SelectorTests,PartStudioTests,SelectorConsumerTests])
result=unittest.TextTestRunner(verbosity=2).run(suite)
source_unchanged = source_snapshot() == source_sha256
report={"passed":result.wasSuccessful() and source_unchanged,"tests":result.testsRun,"seconds":time.perf_counter()-start,
        "source_sha256":source_sha256,"source_unchanged":source_unchanged,
        "network":"Python connect/create_connection/DNS denied; commands also run in the restricted tool sandbox",
        "limits":"Physical network disconnection and native C++ socket interception not exercised; graphical startup tested separately"}
(ROOT/"validation"/"offline-test-result.json").write_text(json.dumps(report,indent=2))
raise SystemExit(0 if report["passed"] else 1)
