"""Repeat native core+conversion checks with Python networking denied.

Does not change system networking; C++ socket calls are not instrumented.
"""
import json
from pathlib import Path
import socket
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(ROOT/"tests"))

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
suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in [NativeCoreTests,NativeConversionTests,PreflightTests,CoreSafetyTests,SketchPlaneTests,SketchProjectionTests,ReviewFollowupTests,StepImportTests])
result=unittest.TextTestRunner(verbosity=2).run(suite)
report={"passed":result.wasSuccessful(),"tests":result.testsRun,"seconds":time.perf_counter()-start,
        "network":"Python connect/create_connection/DNS denied; commands also run in the restricted tool sandbox",
        "limits":"Physical network disconnection and native C++ socket interception not exercised; graphical startup tested separately"}
(ROOT/"validation"/"offline-test-result.json").write_text(json.dumps(report,indent=2))
raise SystemExit(0 if result.wasSuccessful() else 1)
