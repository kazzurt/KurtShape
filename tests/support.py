"""Shared test scratch, profile isolation and explicitly refreshed evidence."""
import os
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

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


OFFSCREEN_FONT_FILES = ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf")
_OFFSCREEN_FONTS_LOADED = set()


def offscreen_qt_fonts(testcase, family="Segoe UI", point_size=9):
    """Give offscreen Qt real glyphs for widget grabs; restore the app font afterwards.

    The offscreen platform has no system font database, so text renders as boxes
    unless fonts are registered explicitly. The native child shares one
    QApplication across classes, so the previous application font is restored in
    a cleanup. Returns False, leaving the application font unchanged, when the
    font files are missing or cannot be loaded; the caller then skips only its
    image assertions.
    """
    from PySide6 import QtGui, QtWidgets
    app = QtWidgets.QApplication.instance()
    if app is None:
        raise RuntimeError("offscreen_qt_fonts needs an existing QApplication")
    folder = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    paths = [folder / name for name in OFFSCREEN_FONT_FILES]
    if not all(path.is_file() for path in paths):
        return False
    for path in paths:
        if str(path) in _OFFSCREEN_FONTS_LOADED:
            continue
        if QtGui.QFontDatabase.addApplicationFont(str(path)) < 0:
            return False
        _OFFSCREEN_FONTS_LOADED.add(str(path))
    previous = QtGui.QFont(app.font())
    testcase.addCleanup(app.setFont, previous)
    app.setFont(QtGui.QFont(family, point_size))
    return True


def _scratch(testcase, directory, prefix):
    temporary = tempfile.TemporaryDirectory(dir=directory, prefix=prefix, ignore_cleanup_errors=True)
    testcase.addCleanup(temporary.cleanup)
    return Path(temporary.name).resolve()


def scratch(testcase, prefix="native-test-fixture-"):
    return _scratch(testcase, TEST_TMP, prefix)


ISOLATION_VARIABLES = ("KURTSHAPE_SESSION_DIR", "FREECAD_USER_HOME", "TEMP", "TMP", "APPDATA", "LOCALAPPDATA")


def _native_fixture_path(raw, parent=None):
    """Check present and dangling redirects before a private fixture mutation."""
    path = Path(raw).absolute()
    for item in (path, *path.parents):
        if item.is_symlink() or item.exists() and (getattr(item.lstat(), "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            raise RuntimeError("Native fixture path traverses a symbolic link or junction: " + str(item))
    path = path.resolve()
    if parent is not None and (path == parent or not path.is_relative_to(parent)):
        raise RuntimeError("Native fixture escaped its private parent: " + str(path))
    return path


def _native_fixture_identity(folder):
    info = folder.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise RuntimeError("Native fixture is no longer a directory: " + str(folder))
    birth = getattr(info, "st_birthtime_ns", None)
    if birth is None and sys.platform == "win32":
        birth = info.st_ctime_ns
    return info.st_dev, info.st_ino, birth


def _cleanup_native_fixture(temporary, folder, base, identity):
    """Preserve a redirected or replaced fixture instead of deleting its replacement."""
    try:
        _native_fixture_path(folder, base)
        if _native_fixture_identity(folder) != identity:
            raise RuntimeError("Native fixture directory identity changed: " + str(folder))
    except BaseException:
        temporary._finalizer.detach()
        raise
    temporary.cleanup()


def _native_suite_environment(base):
    suite = _native_fixture_path(os.environ.get("KURTSHAPE_TEST_RUN_DIR", ""), base)
    if suite != TEST_TMP or not suite.is_dir():
        raise RuntimeError("Native fixtures require the runner's exact private test profile")
    roots = {}
    for name in ISOLATION_VARIABLES:
        raw = os.environ.get(name)
        if not raw:
            raise RuntimeError("Native fixtures require isolated " + name)
        location = _native_fixture_path(raw, suite)
        if not location.is_dir():
            raise RuntimeError("Native fixture environment directory is missing: " + name)
        roots[name] = str(location)
    return suite, roots


def isolated_session(testcase, prefix="native-test-session-"):
    # Native serializers add internal filenames. A shallow exclusive fixture
    # keeps these paths short; profiles and retained receipts remain suite-owned.
    base = _native_fixture_path(ROOT / "runtime" / "test-tmp")
    if not base.is_dir():
        raise RuntimeError("Native fixtures require the runner's test-tmp directory")
    suite, suite_roots = _native_suite_environment(base)
    evidence_raw = os.environ.get("KURTSHAPE_EVIDENCE_DIR")
    if not evidence_raw:
        raise RuntimeError("Native fixture receipts require private suite evidence")
    evidence = _native_fixture_path(evidence_raw, suite)
    receipts = _native_fixture_path(evidence / "native-fixtures", evidence)
    ledger = _native_fixture_path(ROOT / "runtime" / "longrun" / "created.txt", ROOT / "runtime")
    _native_fixture_path(base)
    temporary = tempfile.TemporaryDirectory(dir=base, prefix="native-" + uuid.uuid4().hex + "-",
                                            ignore_cleanup_errors=True)
    folder = Path(temporary.name).absolute()
    # Capture the exclusively created directory before any file writes. These
    # are point-in-time guards; they do not claim protection against every race.
    try:
        folder = _native_fixture_path(folder, base)
        identity = _native_fixture_identity(folder)
    except BaseException:
        temporary._finalizer.detach()
        raise
    testcase.addCleanup(_cleanup_native_fixture, temporary, folder, base, identity)
    _native_fixture_path(ledger.parent, ROOT / "runtime").mkdir(parents=True, exist_ok=True)
    ledger = _native_fixture_path(ledger, ROOT / "runtime")
    with ledger.open("a", encoding="utf-8") as stream:
        stream.write(folder.relative_to(ROOT).as_posix() + "\n")
    stage = folder / "project-recovery" / ("00000000-0000-4000-8000-000000000000.0123456789ab.saving.FCStd")
    if len(str(stage)) > 197:
        raise RuntimeError("Native fixture recovery stage exceeds the validated short path")
    _native_fixture_path(receipts, evidence).mkdir(parents=True, exist_ok=True)
    receipt = _native_fixture_path(receipts / (folder.name + ".json"), receipts)
    with receipt.open("x", encoding="utf-8") as stream:
        json.dump({"schema_version": 1, "fixture": str(folder), "test_id": testcase.id(),
                   "requested_prefix": prefix, "pid": os.getpid(), "suite_session": suite_roots["KURTSHAPE_SESSION_DIR"],
                   "suite_run_dir": str(suite), "environment": suite_roots,
                   "directory_identity": list(identity), "recovery_stage_path_length": len(str(stage)),
                   "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, stream, indent=2)
        stream.write("\n")
    settings = _native_fixture_path(folder / "settings.json", folder)
    settings.write_text(json.dumps({"project_roots": [str(TEST_TMP), str(folder)]}), encoding="utf-8")
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
