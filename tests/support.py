"""Shared test scratch, profile isolation and explicitly refreshed evidence."""
import os
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from kurtshape_evidence import evidence_dir as evidence_dir, external_examples

EXTERNAL_SKIP_PREFIX = "external fixture:"
PERF_SKIP_PREFIX = "perf:"
WRITE_EVIDENCE = os.environ.get("KURTSHAPE_WRITE_EVIDENCE") == "1"
EXTERNAL_EXAMPLES = external_examples()
if os.environ.get("KURTSHAPE_TEST_RUN_DIR"):
    TEST_TMP = Path(os.environ["KURTSHAPE_TEST_RUN_DIR"]).resolve()
else:
    base = Path(os.environ.get("KURTSHAPE_TEST_TMP", str(Path(tempfile.gettempdir()) / "kurtshape-tests")))
    TEST_TMP = (base / ("run-" + time.strftime("%Y%m%d-%H%M%S") + "-" + str(os.getpid()))).resolve()
TEST_TMP.mkdir(parents=True, exist_ok=True)


def perf_only(testcase):
    if os.environ.get("KURTSHAPE_PERF") != "1":
        testcase.skipTest(PERF_SKIP_PREFIX + " set KURTSHAPE_PERF=1 to run performance checks")


def _scratch(testcase, directory, prefix):
    temporary = tempfile.TemporaryDirectory(dir=directory, prefix=prefix, ignore_cleanup_errors=True)
    testcase.addCleanup(temporary.cleanup)
    return Path(temporary.name).resolve()


def scratch(testcase, prefix="native-test-fixture-"):
    return _scratch(testcase, TEST_TMP, prefix)


def isolated_session(testcase, prefix="native-test-session-"):
    folder = scratch(testcase, prefix)
    (folder / "settings.json").write_text(json.dumps({"project_roots": [str(TEST_TMP)]}), encoding="utf-8")
    environment = patch.dict(os.environ, {"KURTSHAPE_SESSION_DIR": str(folder)})
    environment.start()
    testcase.addCleanup(environment.stop)
    return folder


def run_native_proof(args, *, capture_output, text, creationflags, timeout):
    """Capture an isolated native proof and record the exact child we own."""
    for name in ("KURTSHAPE_SESSION_DIR", "FREECAD_USER_HOME", "TEMP", "TMP", "APPDATA", "LOCALAPPDATA"):
        if not os.environ.get(name):
            raise RuntimeError("Native proof requires isolated " + name)
    session = Path(os.environ["KURTSHAPE_SESSION_DIR"]).resolve()
    if session == ROOT / "runtime":
        raise RuntimeError("Native proof cannot use the live session")
    if not capture_output:
        raise ValueError("Native proof output must be captured")
    log = ROOT / "runtime" / "longrun" / "pids.txt"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as stream, subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=text, creationflags=creationflags) as process:
        try:
            stream.write(json.dumps({"pid": process.pid, "command": subprocess.list2cmdline(args),
                                     "session": str(session), "kind": "fresh native test proof"}) + "\n")
            stream.flush()
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as expired:
            process.kill()
            expired.stdout, expired.stderr = process.communicate()
            raise
        except BaseException:
            if process.poll() is None:
                process.kill()
                process.wait()
            raise
        return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)


def ungranted_scratch(testcase, roots, prefix="ungranted-project-fixture-"):
    roots = [Path(root).resolve() for root in roots]
    candidates = [os.environ.get("KURTSHAPE_TEST_OUTSIDE"), tempfile.gettempdir(), ROOT.parents[1]]
    for candidate in candidates:
        if not candidate:
            continue
        directory = Path(candidate).resolve()
        if directory.is_dir() and not any(directory.is_relative_to(root) for root in roots):
            return _scratch(testcase, directory, prefix)
    testcase.skipTest("environment: no existing directory outside the granted project roots")


def external(*names):
    return EXTERNAL_EXAMPLES.joinpath(*names)


def requires_external(*filenames):
    missing = [filename for filename in filenames if not external(filename).is_file()]
    return unittest.skipIf(bool(missing), EXTERNAL_SKIP_PREFIX + " missing " + ", ".join(missing))
