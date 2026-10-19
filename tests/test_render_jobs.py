"""Render jobs: private memory-capped child lifetime (RenderWorkerLifetimeTests, N3), the owner-thread
render_view service (RenderJobTests) and render artifact ownership (RenderOwnershipTests), contract 3.2 U4.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch
import zlib

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
import Sketcher
from kurtshape import render_worker
from kurtshape.render_worker import (JobObject, NativeRenderWorker, RenderTimeout, RenderWorkerError,
                                     as_render_error, validate_envelope)

EXECUTABLE = Path(App.getHomePath()) / "bin" / ("python.exe" if os.name == "nt" else "python")
WINDOWS_ONLY = unittest.skipUnless(os.name == "nt", "platform: Windows Job Objects")
SETTINGS_DIGEST = "ab" * 32


def png_bytes(width, height, shade=200):
    """A minimal valid RGB PNG (no Pillow needed in the parent)."""
    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    raw = (b"\x00" + bytes((shade, shade, shade)) * width) * height
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


# Child-side test renderers; the worker loads this file by path inside the child.
FIXTURE_RENDERER = r'''
import os, struct, sys, time, zlib

def _png(width, height, shade=200):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    raw = (b"\x00" + bytes((shade, shade, shade)) * width) * height
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))

def _write(job, scale=1):
    for image in job.images:
        (job.folder / image["name"]).write_bytes(_png(image["width"] * scale, image["height"]))

def ok(job):
    _write(job)
    job.phases["fixture"] = 1.0
    return {"shapes": {name: {"faces": len(shape.Faces), "volume": round(shape.Volume, 6)}
                       for name, shape in sorted(job.shapes.items())},
            "title": job.scene.get("title"), "settings_digest": job.settings_digest,
            "views": [image["view"] for image in job.images],
            "blas_threads": [os.environ.get("OPENBLAS_NUM_THREADS"), os.environ.get("OMP_NUM_THREADS")],
            "worker_marker": os.environ.get("KURTSHAPE_WORKER"),
            "session": os.environ.get("KURTSHAPE_SESSION_DIR"),
            "core_imported": "kurtshape.core" in sys.modules}

def sleep(job):
    (job.folder / "renderer-started").write_bytes(b"1")
    time.sleep(120)

def crash(job):
    os._exit(7)

def allocate(job):
    import numpy
    block = numpy.ones(job.scene["allocate_mb"] * 2**20 // 8)
    _write(job)
    return {"allocated": int(block.nbytes)}

def exhaust_then_crash(job):
    import numpy
    blocks = []
    try:
        while True:
            blocks.append(numpy.ones(8 * 2**20 // 8))
    except MemoryError:
        os._exit(9)

def exhaust(job):
    import numpy
    blocks = []
    while True:  # grows to the cap, then the MemoryError propagates to the worker
        blocks.append(numpy.ones(8 * 2**20 // 8))

def locked(job):
    raise PermissionError(13, "The process cannot access the file because it is being used by another process",
                          str(job.folder / "view-0.png"))

def two_arguments(job, extra):  # cannot be called as renderer(job)
    _write(job)

def inner_type_error(job):
    return len(5)

def odd_phases(job):
    import numpy
    _write(job)
    job.phases.update({"bad": float("nan"), "infinite": float("inf"), "text": "1.5", "flag": True,
                       "np": numpy.float32(1.5), "x" * 65: 1.0})
    job.phases[3] = 1.0
    return {"fine": True}

def huge_metadata(job):
    _write(job)
    job.phases["renderer_own"] = 2.0
    return {"blob": "x" * (8 * 2**20 - 200)}  # passes the seal copy; the whole result does not fit

class TooLarge(Exception):
    code = "render_too_large"
    def __init__(self):
        super().__init__("Tessellation exceeds 2.5M triangles")
        self.details = {"reason": "triangles", "triangles": 2600000, "limit": 2500000, "nested": [1]}

def too_large(job):
    raise TooLarge()

def wrong_size(job):
    _write(job, scale=2)

def tessellate(job):
    import Part
    Part.makeSphere(100).tessellate(0.00001)
    _write(job)

def abort(job):
    os.abort()

def gated(job):  # U4: holds the job until the test drops a release file into its folder
    deadline = time.monotonic() + 60
    while not (job.folder / "release").exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    _write(job)
    return {"gated": True}
'''

# U4: an owner process renders once (fixture renderer) and reports whether numpy or Pillow's imaging was loaded.
OWNER_NUMPY_SCRIPT = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
import FreeCAD as App
from kurtshape.core import Controller
core = Controller()
state = core.dispatch({"op": "new", "name": "Owner"})["result"]
for op, args in (("sketch_rectangle", {"id": "Base", "width": 10, "height": 10}),
                 ("pad", {"id": "Block", "profile": "Base", "length": 5, "operation": "new"})):
    state = core.dispatch({"op": op, "document_id": state["document_id"], "expected_revision": state["revision"], **args})["result"]
core.renders.renderer = sys.argv[2] + ":ok"
response = core.dispatch({"op": "render_view", "document_id": state["document_id"], "size": [320, 240], "quality": "draft"})
facts = {"ok": response["ok"], "numpy": "numpy" in sys.modules, "pil_image": "PIL.Image" in sys.modules,
         "model_render": "kurtshape.model_render" in sys.modules}
core.close()
print(json.dumps(facts))
'''

# A short-lived owner that starts a render and then dies without close().
OWNER_SCRIPT = r'''
import hashlib, json, os, sys
sys.path.insert(0, sys.argv[1])
from kurtshape.render_worker import NativeRenderWorker
worker = NativeRenderWorker(sys.argv[2], sys.argv[3], renderer=sys.argv[4])
worker.scene_path.write_bytes(b"{}")
worker.submit(1, {"scene_sha256": hashlib.sha256(b"{}").hexdigest(), "settings_digest": "0" * 64, "captures": [],
                  "outputs": [{"view": "iso", "name": "view-0.png", "width": 160, "height": 128}]})
print(json.dumps({"pid": worker.process.pid, "folder": str(worker.folder), "job": worker.job is not None}), flush=True)
sys.stdin.readline()
os._exit(0)
'''


class _Win32Process:
    """Synchronize on a pid without owning it (for orphan checks)."""

    def __init__(self, pid):
        import ctypes
        from ctypes import wintypes
        self.ctypes = ctypes
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel32.OpenProcess.restype = wintypes.HANDLE
        self.kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel32.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel32.OpenProcess(0x00100000 | 0x1000, False, pid)  # SYNCHRONIZE | QUERY_LIMITED
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def exited_within(self, seconds):
        return self.kernel32.WaitForSingleObject(self.handle, int(seconds * 1000)) == 0

    def close(self):
        self.kernel32.CloseHandle(self.handle)


class RenderWorkerLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.folder = support.scratch(self, prefix="render-worker-lifetime-")
        self.fixture = self.folder / "fixture_renderer.py"
        self.fixture.write_text(FIXTURE_RENDERER, encoding="utf-8")
        self.workers = []
        self.addCleanup(self.close_workers)

    def close_workers(self):
        for worker in self.workers:
            worker.close()
        for worker in self.workers:
            self.assertTrue(worker.cleanup_complete.wait(20), "Render child cleanup did not confirm exit")

    # --- helpers ---------------------------------------------------------

    def worker(self, renderer="ok", **options):
        worker = NativeRenderWorker(EXECUTABLE, self.folder, renderer=str(self.fixture) + ":" + renderer, **options)
        self.workers.append(worker)
        return worker

    def capture(self, name, shape, folder="cap-0123456789abcdef"):
        directory = self.folder / "renders" / "owner" / folder
        directory.mkdir(parents=True, exist_ok=True)
        payload = shape.exportBrepToString().encode("ascii")
        path = directory / (name + ".brep")
        path.write_bytes(payload)
        return {"name": name, "path": str(path), "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload)}

    def envelope(self, worker, scene=None, captures=(), images=None):
        payload = json.dumps({"title": "fixture"} if scene is None else scene).encode("utf-8")
        worker.scene_path.write_bytes(payload)
        return {"scene_sha256": hashlib.sha256(payload).hexdigest(), "settings_digest": SETTINGS_DIGEST,
                "captures": list(captures),
                "outputs": images or [{"view": "iso", "name": "view-0.png", "width": 160, "height": 128}]}

    def finish(self, worker, seconds=60):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            response = worker.poll()
            if response is not None:
                json.dumps(response, allow_nan=False)
                return response
            time.sleep(.02)
        self.fail("Render child did not finish within its bounded wait")

    def wait_for_file(self, path, seconds=30):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if Path(path).exists():
                return
            time.sleep(.02)
        self.fail("Render child never reached its renderer")

    def assert_reaped(self, worker, seconds=20):
        self.assertTrue(worker.cleanup_complete.wait(seconds), "Cleanup did not confirm child exit")
        if worker.process is not None and not isinstance(worker.process, Mock):
            self.assertIsNotNone(worker.process.poll())
        self.assertFalse(worker.folder.exists(), "The job folder must be removed after confirmed exit")
        if worker.job is not None and not isinstance(worker.job, Mock):
            self.assertTrue(worker.job.closed)

    def mock_completed(self, worker, envelope=None, exit_code=0, response=None, images=None):
        """Deterministic exited transport with real PNG bytes for parent-side fault injection."""
        envelope = validate_envelope(envelope or self.envelope(worker), worker.root)
        process = worker.process = Mock()
        process.stdin = io.BytesIO()
        process.pid = 4242
        process.poll.return_value = process.wait.return_value = exit_code
        worker.active, worker.started = 1, time.monotonic()
        worker._envelope, worker._submitted = envelope, True
        rows = []
        for image in envelope["outputs"]:
            payload = (images or {}).get(image["name"]) or png_bytes(image["width"], image["height"])
            (worker.folder / image["name"]).write_bytes(payload)
            rows.append(dict(image, bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest()))
        if response is None:
            response = dict(envelope, task=worker.token, sequence=1, ok=True, images=rows, render={"views": 1},
                            error=None, engine=None, phases={}, milliseconds=1.0, peak_working_set_mb=None,
                            peak_commit_mb=None, core_imported=False)
        (worker.folder / "result-1.json").write_text(json.dumps(response), encoding="utf-8")
        return response

    # --- real children ---------------------------------------------------

    @WINDOWS_ONLY
    def test_actual_child_verifies_captures_renders_and_publishes_verified_pngs(self):
        box = Part.makeBox(10, 20, 30)
        cylinder = Part.makeCylinder(4, 9)
        worker = self.worker()
        images = [{"view": "iso", "name": "view-0.png", "width": 160, "height": 128},
                  {"view": "section", "name": "view-1.png", "width": 200, "height": 150}]
        envelope = self.envelope(worker, {"title": "Two parts"},
                                 [self.capture("part-0", box), self.capture("part-1", cylinder)], images)
        began = time.perf_counter()
        worker.submit(1, envelope)
        submit_ms = (time.perf_counter() - began) * 1000
        self.assertLess(submit_ms, 2000, "Launching the child must stay cheap on the owner thread")
        self.assertEqual(worker.job.assigned_pid, worker.process.pid)
        limits = worker.job.limits()
        self.assertEqual(limits["process_memory_limit"], render_worker.MEMORY_LIMIT_BYTES)
        for flag in (render_worker.JOB_OBJECT_LIMIT_PROCESS_MEMORY, render_worker.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
                     render_worker.JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION):
            self.assertTrue(limits["limit_flags"] & flag)
        response = self.finish(worker)
        self.assertIsNone(worker.child_error(response))
        self.assertTrue(response["ok"], response)
        self.assertEqual(worker.process.poll(), 0)
        rows = worker.validated_images(response)
        self.assertEqual([row["name"] for row in rows], ["view-0.png", "view-1.png"])
        for row, want in zip(rows, images):
            path = Path(row["path"])
            self.assertEqual(path.parent, worker.folder)
            info = render_worker.png_info(path)
            self.assertEqual((info["width"], info["height"]), (want["width"], want["height"]))
            self.assertEqual((info["bytes"], info["sha256"]), (row["bytes"], row["sha256"]))
        render = response["render"]
        self.assertEqual(render["shapes"]["part-0"], {"faces": 6, "volume": 6000.0})
        self.assertEqual(render["shapes"]["part-1"]["faces"], 3)
        self.assertAlmostEqual(render["shapes"]["part-1"]["volume"], cylinder.Volume, places=4)
        self.assertEqual(render["title"], "Two parts")
        self.assertEqual(render["settings_digest"], SETTINGS_DIGEST)
        self.assertEqual(render["views"], ["iso", "section"])
        self.assertEqual(render["blas_threads"], ["1", "1"])
        self.assertEqual(render["worker_marker"], "1")
        self.assertTrue(Path(render["session"]).is_relative_to(worker.folder),
                        "The child must not share the owner's session folder")
        self.assertFalse(render["core_imported"])
        self.assertFalse(response["core_imported"])
        self.assertEqual(response["native_modules_at_verify"], [], "Inputs are verified before any native import")
        self.assertEqual(response["native_policy"], {"new_mode": 0, "previous_new_mode": 1,
                                                     "abort_fault_reporting": False})
        self.assertFalse(worker.memory_limit_hit)
        self.assertEqual(response["engine"]["OCCT"], Part.OCC_VERSION)
        for phase in ("verify", "import", "load", "render", "seal", "fixture"):
            self.assertIn(phase, response["phases"])
        self.assertLess(response["peak_commit_mb"], render_worker.MEMORY_LIMIT_BYTES / 2**20)
        self.assertIsNotNone(worker.diagnostics()["peak_commit_mb"])
        self.assertIsNone(worker.poll(), "A delivered job is not delivered twice")
        worker.close()
        self.assert_reaped(worker)
        with self.assertRaises(RenderWorkerError):
            worker.validated_images(response)

    @WINDOWS_ONLY
    def test_close_kills_child_and_removes_folder_after_exit(self):
        worker = self.worker("sleep")
        worker.submit(1, self.envelope(worker))
        self.wait_for_file(worker.folder / "renderer-started")
        self.assertIsNone(worker.poll())
        self.assertIsNone(worker.process.poll(), "The renderer is still running")
        began = time.monotonic()
        worker.close()
        self.assertLess(time.monotonic() - began, .5, "close() must not wait on the child")
        self.assert_reaped(worker, 15)
        self.assertIsNone(worker.poll())
        self.assertFalse(worker.diagnostics()["running"])

    @WINDOWS_ONLY
    def test_reaper_retains_folder_and_job_until_exit_is_confirmed(self):
        worker = self.worker()
        job = worker.job = worker._snapshot_lease = JobObject.create(render_worker.MEMORY_LIMIT_BYTES)
        self.mock_completed(worker)
        process = worker.process
        process.kill.side_effect = OSError("Busy native handle")
        waiting, release_exit = threading.Event(), threading.Event()
        self.addCleanup(release_exit.set)
        attempts = []

        def wait(timeout):
            attempts.append(timeout)
            if len(attempts) <= 2:
                raise subprocess.TimeoutExpired("owned render process", timeout)
            waiting.set()
            if not release_exit.wait(5):
                raise subprocess.TimeoutExpired("owned render process", timeout)
            return 0
        process.wait.side_effect = wait
        worker.close()
        self.assertTrue(waiting.wait(5))
        self.assertFalse(worker.cleanup_complete.is_set())
        self.assertTrue(worker.folder.is_dir(), "Files stay until exit is confirmed")
        self.assertFalse(job.closed, "The job handle stays open until exit is confirmed")
        release_exit.set()
        self.assert_reaped(worker)
        self.assertTrue(job.closed)
        self.assertTrue(process.stdin.closed)
        job.close()  # idempotent

    @WINDOWS_ONLY
    def test_tampered_capture_brep_rejected_by_child(self):
        for target in ("capture", "scene"):
            with self.subTest(target=target):
                worker = self.worker()
                capture = self.capture("part-0", Part.makeBox(10, 20, 30), folder="cap-" + target)
                envelope = self.envelope(worker, captures=[capture])
                path = Path(capture["path"]) if target == "capture" else worker.scene_path
                payload = bytearray(path.read_bytes())
                index = payload.index(b"1" if target == "capture" else b"f")
                payload[index:index + 1] = b"2" if target == "capture" else b"g"
                path.write_bytes(bytes(payload))  # same size, different digest
                worker.submit(1, envelope)
                response = self.finish(worker)
                self.assertFalse(response["ok"])
                self.assertEqual(response["error"]["code"], "render_failed")
                self.assertEqual(response["error"]["phase"], "verify")
                self.assertIn("changed after capture", response["error"]["message"])
                self.assertIsNone(response["engine"], "Native modules load only after verification")
                self.assertEqual(response["native_modules_at_verify"], [],
                                 "No native module was loaded while the inputs were verified")
                self.assertFalse((worker.folder / "view-0.png").exists(), "The renderer never ran")
                error = worker.child_error(response)
                self.assertEqual(error.code, "render_failed")
                self.assertFalse(error.deterministic)
                with self.assertRaises(RenderWorkerError) as raised:
                    worker.validated_images(response)
                self.assertEqual(raised.exception.code, "render_failed")

    @WINDOWS_ONLY
    def test_timeout_reports_render_timeout(self):
        worker = self.worker("sleep", timeout=3)
        worker.submit(1, self.envelope(worker))
        began = time.monotonic()
        with self.assertRaises(RenderTimeout) as raised:
            self.finish(worker, 30)
        self.assertGreaterEqual(time.monotonic() - began, 2.5)
        self.assertIsInstance(raised.exception, TimeoutError)
        self.assertEqual(raised.exception.code, "render_timeout")
        self.assertFalse(raised.exception.deterministic)
        self.assertIsNone(worker.process.poll(), "Timing out reports; close() does the killing")
        worker.close()
        self.assert_reaped(worker, 15)

        mocked = self.worker()
        self.mock_completed(mocked)
        mocked.process.poll.return_value = None
        mocked.started = time.monotonic() - render_worker.JOB_TIMEOUT_SECONDS - 1
        with self.assertRaises(RenderTimeout):
            mocked.poll()
        self.assertEqual(mocked.active, 1, "A result published by a still-running child is never delivered")
        self.assertIsNone(mocked._completed_response)
        self.assertIsInstance(as_render_error(TimeoutError("late")), RenderTimeout)

    @WINDOWS_ONLY
    def test_worker_crash_reports_render_failed(self):
        worker = self.worker("crash")
        worker.submit(1, self.envelope(worker))
        with self.assertRaises(RenderWorkerError) as raised:
            self.finish(worker)
        self.assertEqual(raised.exception.code, "render_failed")
        self.assertEqual(raised.exception.details["exit_code"], 7)
        self.assertFalse(raised.exception.deterministic)
        self.assertLess(worker.job.peak_process_memory, worker.memory_limit // 2)
        self.assertFalse(worker.memory_limit_hit)
        worker.close()
        self.assert_reaped(worker)

        for exit_code, publish in ((3, True), (0, False)):
            with self.subTest(exit_code=exit_code, published=publish):
                mocked = self.worker()
                self.mock_completed(mocked, exit_code=exit_code)
                if not publish:
                    (mocked.folder / "result-1.json").unlink()
                with self.assertRaises(RenderWorkerError) as raised:
                    mocked.poll()
                self.assertEqual(raised.exception.code, "render_failed")
                self.assertIsNone(mocked._completed_response)
        self.assertEqual(as_render_error(OSError("pipe")).code, "render_failed")

    @WINDOWS_ONLY
    def test_job_object_memory_limit_reports_render_too_large(self):
        limit = 200 * 2**20
        worker = self.worker("allocate", memory_limit=limit)
        worker.submit(1, self.envelope(worker, {"allocate_mb": 600}))
        response = self.finish(worker)
        self.assertEqual(worker.process.poll(), 0, "MemoryError is caught and reported by the child")
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"], {"code": "render_too_large", "reason": "memory", "phase": "render",
                                             "message": "The render exceeded its memory limit"})
        # FreeCAD's _set_new_mode(1) would otherwise turn this numpy failure into an abort.
        self.assertEqual(response["native_policy"]["new_mode"], 0)
        self.assertLess(response["peak_commit_mb"], 200)
        self.assertLessEqual(worker.job.peak_process_memory, limit)
        self.assertEqual(worker.job.limits()["process_memory_limit"], limit)
        self.assertEqual(worker.diagnostics()["memory_limit_hit"], worker.memory_limit_hit)
        error = worker.child_error(response)
        self.assertEqual((error.code, error.details["reason"], error.details["phase"]),
                         ("render_too_large", "memory", "render"))
        # One refused 600 MB block leaves the peak far below the cap, so only the
        # job's (best-effort) notification proves the cap; without it the failure
        # could be system commit exhaustion and is not negatively cacheable.
        self.assertLess(worker.job.peak_process_memory, limit - render_worker.MEMORY_LIMIT_MARGIN_BYTES)
        self.assertEqual(error.deterministic, worker.memory_limit_hit)
        with self.assertRaises(RenderWorkerError) as raised:
            worker.validated_images(response)
        self.assertEqual(raised.exception.payload()["reason"], "memory")
        worker.close()
        self.assert_reaped(worker)

        # Growing to the cap leaves its own evidence: deterministic with or without the notification.
        grown = self.worker("exhaust", memory_limit=limit)
        grown.submit(1, self.envelope(grown))
        response = self.finish(grown)
        self.assertEqual(grown.process.poll(), 0, "MemoryError is caught and reported by the child")
        self.assertEqual((response["error"]["code"], response["error"]["reason"]), ("render_too_large", "memory"))
        self.assertGreaterEqual(grown.job.peak_process_memory, limit - render_worker.MEMORY_LIMIT_MARGIN_BYTES)
        self.assertLessEqual(grown.job.peak_process_memory, limit)
        error = grown.child_error(response)
        self.assertEqual((error.code, error.details["reason"], error.deterministic), ("render_too_large", "memory", True))
        self.assertEqual(error.details["peak_commit_mb"], round(grown.job.peak_process_memory / 2**20, 1))

    @WINDOWS_ONLY
    def test_child_killed_at_memory_cap_reports_render_too_large(self):
        limit = 200 * 2**20
        worker = self.worker("exhaust_then_crash", memory_limit=limit)
        worker.submit(1, self.envelope(worker))
        with self.assertRaises(RenderWorkerError) as raised:
            self.finish(worker)
        self.assertEqual(raised.exception.code, "render_too_large")
        self.assertEqual(raised.exception.details["reason"], "memory")
        self.assertTrue(raised.exception.deterministic)
        self.assertGreaterEqual(worker.job.peak_process_memory, limit - render_worker.MEMORY_LIMIT_MARGIN_BYTES)
        self.assertLessEqual(worker.job.peak_process_memory, limit)
        self.assertIn("exit code 9", raised.exception.details["cause"])
        self.assertNotIn("phase", raised.exception.details, "A child that died reported no phase")

    @WINDOWS_ONLY
    def test_occt_allocation_failure_under_cap_reports_render_too_large(self):
        # Under the cap OCCT tessellation fails natively (an access violation or a
        # FreeCAD MemoryError, sometimes a dead child); memory is still the reported cause.
        worker = self.worker("tessellate", memory_limit=300 * 2**20)
        worker.submit(1, self.envelope(worker))
        try:
            response = self.finish(worker)
        except RenderWorkerError as exc:
            error = exc
        else:
            self.assertFalse(response["ok"])
            error = worker.child_error(response)
        self.assertEqual((error.code, error.details["reason"], error.deterministic), ("render_too_large", "memory", True))
        # Either signal establishes the cap; the notification alone is best-effort.
        self.assertTrue(worker.memory_limit_hit or worker.job.peak_process_memory
                        >= 300 * 2**20 - render_worker.MEMORY_LIMIT_MARGIN_BYTES)
        self.assertLessEqual(worker.job.peak_process_memory, 300 * 2**20)

    @WINDOWS_ONLY
    def test_native_abort_exits_promptly_without_fault_reporting(self):
        worker = self.worker("abort")
        began = time.monotonic()
        worker.submit(1, self.envelope(worker))
        with self.assertRaises(RenderWorkerError) as raised:
            self.finish(worker)
        # With fault reporting left on, abort() took 38 s here (0xC0000409 via WER).
        self.assertLess(time.monotonic() - began, 10)
        self.assertEqual((raised.exception.code, raised.exception.details["exit_code"]), ("render_failed", 3))
        self.assertFalse(worker.memory_limit_hit)

    @WINDOWS_ONLY
    def test_renderer_too_large_and_wrong_size_are_deterministic_child_errors(self):
        worker = self.worker("too_large")
        worker.submit(1, self.envelope(worker))
        error = worker.child_error(self.finish(worker))
        self.assertEqual(error.payload(), {"code": "render_too_large", "message": "Tessellation exceeds 2.5M triangles",
                                           "phase": "render", "reason": "triangles", "triangles": 2600000,
                                           "limit": 2500000})
        self.assertTrue(error.deterministic)

        worker = self.worker("wrong_size")
        worker.submit(1, self.envelope(worker))
        response = self.finish(worker)
        error = worker.child_error(response)
        self.assertEqual((error.code, error.details["phase"], error.deterministic), ("render_failed", "seal", True))
        self.assertIn("instead of the requested size", str(error))
        self.assertEqual(response["images"], [])

    @WINDOWS_ONLY
    def test_default_renderer_draws_captures_through_model_render(self):
        from PIL import Image
        worker = NativeRenderWorker(EXECUTABLE, self.folder)  # the production seam: no renderer injected
        self.workers.append(worker)
        self.assertEqual(worker.renderer, render_worker.DEFAULT_RENDERER)
        box = Part.makeBox(10, 20, 30)
        top = [face for face in box.Faces if abs(face.CenterOfMass.z - 30) < 1e-9]
        width, height = 192, 144
        images = [{"view": "iso", "name": "view-0.png", "width": width, "height": height},
                  {"view": "top", "name": "view-1.png", "width": width, "height": height}]
        scene = {"title": "Box", "revision": "r1",
                 "parts": [{"brep": "part-0.brep", "name": "Box", "id": "box", "color": [0.62, 0.70, 0.82],
                            "solid": True}],
                 "highlights": [{"label": "A", "note": "top face", "rendered": "hl-0-r", "ghost": None}],
                 "settings": {"views": ["iso", "top"], "size": [width, height], "quality": "draft"},
                 "metadata": {"document": "fixture", "revision": "r1", "render_id": "0123456789abcdef"}}
        captures = [self.capture("part-0", box), self.capture("hl-0-r", Part.makeCompound(top))]
        worker.submit(1, self.envelope(worker, scene, captures, images))
        response = self.finish(worker)
        self.assertIsNone(worker.child_error(response), response.get("error"))
        rows = worker.validated_images(response)
        render = response["render"]
        self.assertEqual((render["renderer"], render["renderer_version"]), ("kurtshape-soft", 1))
        self.assertEqual([(image["file"], image["view"], image["sha256"]) for image in render["images"]],
                         [(row["name"], row["view"], row["sha256"]) for row in rows])
        self.assertEqual(render["non_solid_parts"], [])
        self.assertEqual([item["label"] for item in render["highlights"]], ["A"])
        self.assertTrue(render["highlights"][0]["rendered"])
        iso_rows = render["images"][0]["highlights"]
        self.assertTrue(iso_rows[0]["visible"], "The top face is visible in the iso view")
        self.assertFalse(response["core_imported"])
        self.assertEqual(response["native_modules_at_verify"], [])
        for row in rows:
            with Image.open(row["path"]) as image:
                self.assertEqual(image.size, (width, height))
                self.assertEqual(image.text.get("render_id"), "0123456789abcdef")
                band = image.convert("RGB").crop((0, 30, width, height - 24))
                drawn = sum(1 for pixel in band.getdata() if pixel != (255, 255, 255))
            self.assertGreater(drawn, band.width * band.height // 20, "The box is drawn: " + row["name"])
        worker.close()
        self.assert_reaped(worker)

    @WINDOWS_ONLY
    def test_transient_failures_are_never_deterministic(self):
        cases = {"locked": (True, "PermissionError"), "two_arguments": (True, "cannot be called as renderer(job)"),
                 "inner_type_error": (False, "TypeError")}
        for renderer, (transient, text) in cases.items():
            with self.subTest(renderer=renderer):
                worker = self.worker(renderer)
                worker.submit(1, self.envelope(worker))
                response = self.finish(worker)
                self.assertEqual(worker.process.poll(), 0)
                self.assertEqual((response["error"]["code"], response["error"]["phase"]), ("render_failed", "render"))
                self.assertIn(text, response["error"]["message"])
                self.assertEqual(response["error"].get("transient"), True if transient else None)
                error = worker.child_error(response)
                self.assertEqual((error.code, error.deterministic), ("render_failed", not transient))
                self.assertNotIn("transient", error.payload(), "The flag is consumed by the parent")

    @WINDOWS_ONLY
    def test_child_publishes_clean_phases_and_drops_renderer_fields_it_cannot_write(self):
        worker = self.worker("odd_phases")
        worker.submit(1, self.envelope(worker))
        response = self.finish(worker)
        self.assertTrue(response["ok"], response.get("error"))
        phases = response["phases"]
        self.assertEqual(phases["np"], 1.5)
        for name in ("verify", "import", "load", "render", "seal"):
            self.assertIn(name, phases)
        for name in ("bad", "infinite", "text", "flag", "3", "x" * 65):
            self.assertNotIn(name, phases)
        self.assertEqual(len(worker.validated_images(response)), 1)

        worker = self.worker("huge_metadata")
        worker.submit(1, self.envelope(worker))
        response = self.finish(worker)
        self.assertFalse(response["ok"])
        self.assertEqual((response["error"]["code"], response["error"]["phase"]), ("render_failed", "write"))
        self.assertEqual((response["render"], response["images"]), (None, []))
        self.assertLessEqual(set(response["phases"]), set(render_worker.PHASES), "Renderer phases are dropped")
        self.assertIn("seal", response["phases"])
        error = worker.child_error(response)
        self.assertEqual((error.code, error.deterministic), ("render_failed", False))

    @WINDOWS_ONLY
    def test_job_kill_on_close_terminates_idle_child(self):
        worker = self.worker()
        worker.start()
        self.assertIsNone(worker.process.poll(), "The child waits for its wake-up line")
        self.assertEqual(worker.job.assigned_pid, worker.process.pid)
        time.sleep(.3)
        self.assertIsNone(worker.process.poll())
        began = time.monotonic()
        worker.job.close()  # what the OS does when the owning process ends
        worker.process.wait(timeout=10)
        self.assertLess(time.monotonic() - began, 5)
        self.assertFalse(worker.process.stdin.closed, "The pipe stayed open; only the job ended the child")
        worker.close()
        self.assert_reaped(worker)

    @WINDOWS_ONLY
    def test_owner_exit_without_close_kills_render_child(self):
        script = self.folder / "owner.py"
        script.write_text(OWNER_SCRIPT, encoding="utf-8")
        owner = subprocess.Popen(
            [str(EXECUTABLE), "-B", str(script), str(ROOT / "src"), str(EXECUTABLE), str(self.folder / "owner-session"),
             str(self.fixture) + ":sleep"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.addCleanup(lambda: owner.poll() is None and owner.kill())
        line = owner.stdout.readline()
        self.assertTrue(line, owner.stderr.read() if owner.poll() is not None else "owner produced no record")
        record = json.loads(line)
        self.assertTrue(record["job"])
        child = _Win32Process(record["pid"])
        self.addCleanup(child.close)
        self.wait_for_file(Path(record["folder"]) / "renderer-started")
        self.assertFalse(child.exited_within(0), "The render child is busy in its renderer")
        owner.stdin.write(b"exit\n")
        owner.stdin.flush()
        owner.wait(timeout=20)
        owner.stdout.close()
        owner.stderr.close()
        owner.stdin.close()
        self.assertTrue(child.exited_within(10), "An owner that vanishes must take its render child with it")

    # --- parent transport (no child) -------------------------------------

    def test_identity_mismatch_rejected(self):
        worker = self.worker()
        response = self.mock_completed(worker)
        self.assertEqual(worker.poll(), response)
        self.assertEqual(len(worker.validated_images(response)), 1)

        mutations = {
            "task": lambda response: response.update(task="0" * 32),
            "sequence": lambda response: response.update(sequence=2),
            "boolean sequence": lambda response: response.update(sequence=True),
            "scene digest": lambda response: response.update(scene_sha256="cd" * 32),
            "settings digest": lambda response: response.update(settings_digest="ef" * 32),
            "outputs echo": lambda response: response.update(outputs=[dict(response["outputs"][0], width=999)]),
            "captures echo": lambda response: response.pop("captures"),
            "not an object": None,
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                mocked = self.worker()
                envelope = self.envelope(mocked)
                bad = dict(validate_envelope(envelope, mocked.root), task=mocked.token, sequence=1, ok=True,
                           images=[], render=None, error=None)
                if mutate is None:
                    bad = [bad]
                else:
                    mutate(bad)
                self.mock_completed(mocked, envelope, response=bad)
                with self.assertRaises(RenderWorkerError) as raised:
                    mocked.poll()
                self.assertEqual(raised.exception.code, "render_failed")
                self.assertIsNone(mocked._completed_response)
                self.assertEqual(mocked.active, 1)
                with self.assertRaises(RenderWorkerError):
                    mocked.validated_images(bad)
        for label in ("nonfinite", "oversize"):
            with self.subTest(label=label):
                mocked = self.worker()
                self.mock_completed(mocked)
                result = mocked.folder / "result-1.json"
                if label == "nonfinite":
                    result.write_text(result.read_text(encoding="utf-8").replace('"milliseconds": 1.0',
                                                                                 '"milliseconds": NaN'), encoding="utf-8")
                else:
                    result.write_bytes(b" " * (render_worker.MAX_JSON_BYTES + 1))
                with self.assertRaises(RenderWorkerError) as raised:
                    mocked.poll()
                self.assertEqual(raised.exception.code, "render_failed")

    def test_tampered_png_rejected(self):
        def tamper_bytes(worker, rows):
            path = worker.folder / "view-0.png"
            payload = bytearray(path.read_bytes())
            payload[-20] ^= 0xFF
            path.write_bytes(bytes(payload))

        def replace_with_text(worker, rows):
            (worker.folder / "view-0.png").write_text("not an image", encoding="utf-8")

        def remove(worker, rows):
            (worker.folder / "view-0.png").unlink()

        for label, action in (("bytes", tamper_bytes), ("not png", replace_with_text), ("missing", remove)):
            with self.subTest(label=label):
                worker = self.worker()
                response = self.mock_completed(worker)
                self.assertEqual(worker.poll(), response)
                action(worker, response["images"])
                with self.assertRaises(RenderWorkerError) as raised:
                    worker.validated_images(response)
                self.assertEqual(raised.exception.code, "render_failed")
                self.assertFalse(raised.exception.deterministic)

        with self.subTest(label="dimensions"):
            worker = self.worker()
            response = self.mock_completed(worker, images={"view-0.png": png_bytes(161, 128)})
            self.assertEqual(worker.poll(), response)
            with self.assertRaisesRegex(RenderWorkerError, "dimensions"):
                worker.validated_images(response)
        for label, change in (("report view", {"view": "top"}), ("report size", {"width": 161}),
                              ("report extra key", {"path": "C:/elsewhere.png"}), ("report bytes", {"bytes": 0})):
            with self.subTest(label=label):
                worker = self.worker()
                response = self.mock_completed(worker)
                response["images"][0].update(change)
                self.mock_completed(worker, response=response)
                self.assertEqual(worker.poll(), response)
                with self.assertRaisesRegex(RenderWorkerError, "does not match"):
                    worker.validated_images(response)
        with self.subTest(label="missing report"):
            worker = self.worker()
            response = self.mock_completed(worker)
            response["images"] = []
            self.mock_completed(worker, response=response)
            self.assertEqual(worker.poll(), response)
            with self.assertRaisesRegex(RenderWorkerError, "does not match"):
                worker.validated_images(response)
        with self.subTest(label="caller copy"):
            worker = self.worker()
            response = self.mock_completed(worker)
            delivered = worker.poll()
            altered = dict(delivered, render={"views": 2})
            with self.assertRaisesRegex(RenderWorkerError, "not owned"):
                worker.validated_images(altered)
            self.assertEqual(len(worker.validated_images(delivered)), 1)
        with self.subTest(label="before exit"):
            worker = self.worker()
            response = self.mock_completed(worker)
            worker.process.poll.return_value = None
            self.assertIsNone(worker.poll(), "A result file is not proof of child exit")
            with self.assertRaises(RenderWorkerError):
                worker.validated_images(response)

    def test_launch_isolation_priority_blas_and_job_before_wakeup(self):
        events = []
        launched = {}
        job = Mock(name="job")
        job.assign.side_effect = lambda process: events.append("assign")

        class Pipe(io.BytesIO):
            def write(self, data):
                events.append("wake")
                return super().write(data)

        def popen(command, **options):
            events.append("popen")
            launched.update(command=command, **options)
            process = Mock()
            process.stdin = Pipe()
            process.pid = 4343
            process.poll.return_value = None
            process.wait.return_value = 0
            return process

        def create(limit):
            events.append(("create", limit))
            return job
        worker = self.worker(memory_limit=300 * 2**20)
        envelope = self.envelope(worker, captures=[self.capture("part-0", Part.makeBox(1, 2, 3))])
        with patch.object(render_worker.subprocess, "Popen", side_effect=popen), \
                patch.object(render_worker.JobObject, "create", side_effect=create):
            worker.submit(1, envelope)
        self.assertEqual(events, [("create", 300 * 2**20), "popen", "assign", "wake"])
        command, environment = launched["command"], launched["env"]
        self.assertEqual(command[:2], [str(EXECUTABLE), "-B"])
        self.assertEqual(Path(command[2]), Path(render_worker.__file__).resolve())
        self.assertEqual(command[3:], [str(worker.folder), worker.token, str(self.fixture) + ":ok"])
        self.assertEqual(launched["cwd"], worker.folder)
        if os.name == "nt":
            self.assertEqual(launched["creationflags"], subprocess.CREATE_NO_WINDOW | 0x00004000)
        for name in ("KURTSHAPE_SESSION_DIR", "FREECAD_USER_HOME", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"):
            self.assertTrue(Path(environment[name]).is_relative_to(worker.folder), name)
        for name, value in (("OPENBLAS_NUM_THREADS", "1"), ("OMP_NUM_THREADS", "1"), ("KURTSHAPE_WORKER", "1"),
                            ("QT_QPA_PLATFORM", "offscreen"), ("PYTHONDONTWRITEBYTECODE", "1")):
            self.assertEqual(environment[name], value)
        request = json.loads((worker.folder / "request-1.json").read_text(encoding="utf-8"))
        self.assertEqual(request, {"task": worker.token, "sequence": 1,
                                   "proposal": validate_envelope(envelope, worker.root)})
        wake = json.loads(worker.process.stdin.getvalue())
        self.assertEqual(wake, {"task": worker.token, "sequence": 1})
        self.assertIs(worker._snapshot_lease, job)
        with self.assertRaisesRegex(RuntimeError, "one numbered job"):
            worker.submit(2, envelope)
        worker.close()
        self.assertTrue(worker.cleanup_complete.wait(5))
        job.release.assert_called_once_with()

    @WINDOWS_ONLY
    def test_launch_and_assignment_failures_close_job_and_folder(self):
        worker = self.worker()
        envelope = self.envelope(worker)
        with patch.object(render_worker.subprocess, "Popen", side_effect=OSError("Cannot launch render worker")):
            with self.assertRaisesRegex(RenderWorkerError, "could not start") as raised:
                worker.submit(1, envelope)
        self.assertEqual(raised.exception.code, "render_failed")
        self.assertIsNone(worker.process)
        self.assert_reaped(worker, 5)

        worker = self.worker()
        envelope = self.envelope(worker)
        with patch.object(render_worker.JobObject, "assign", side_effect=OSError("Access is denied")):
            with self.assertRaises(RenderWorkerError) as raised:
                worker.submit(1, envelope)
        self.assertEqual(raised.exception.code, "render_failed")
        self.assertIsNotNone(worker.process, "The child had launched before assignment failed")
        self.assertIsNone(worker.active, "No wake-up line is sent to an unconfined child")
        self.assert_reaped(worker)

    def test_envelope_and_submit_validation(self):
        worker = self.worker()
        base = self.envelope(worker, captures=[self.capture("part-0", Part.makeBox(1, 2, 3))])
        outside = support.scratch(self, prefix="render-outside-")
        stray = outside / "part.brep"
        stray.write_bytes(b"x")
        image = base["outputs"][0]
        invalid = {
            "missing key": {key: value for key, value in base.items() if key != "settings_digest"},
            "extra key": dict(base, destination="C:/out.png"),
            "scene digest": dict(base, scene_sha256="AB" * 32),
            "capture outside session": dict(base, captures=[dict(base["captures"][0], path=str(stray), bytes=1)]),
            "relative capture": dict(base, captures=[dict(base["captures"][0], path="part.brep")]),
            "capture suffix": dict(base, captures=[dict(base["captures"][0], path=base["captures"][0]["path"] + ".txt")]),
            "capture name": dict(base, captures=[dict(base["captures"][0], name="../part")]),
            "duplicate capture": dict(base, captures=base["captures"] * 2),
            "image traversal": dict(base, outputs=[dict(image, name="../view-0.png")]),
            "image name": dict(base, outputs=[dict(image, name="view-7.png")]),
            "too small": dict(base, outputs=[dict(image, width=127)]),
            "too many pixels": dict(base, outputs=[dict(image, width=2048, height=2048)]),
            "duplicate image": dict(base, outputs=[image, image]),
            "too many images": dict(base, outputs=[dict(image, name="view-" + str(i) + ".png") for i in range(7)]
                                    + [dict(image, name="sheet.png")]),
            "sheet plus view": dict(base, outputs=[image, dict(image, name="sheet.png")]),
            "nonprintable view": dict(base, outputs=[dict(image, view="iso\n")]),
            "boolean size": dict(base, outputs=[dict(image, width=True)]),
            "nonfinite": dict(base, captures=[dict(base["captures"][0], bytes=float("nan"))]),
        }
        with patch.object(render_worker.subprocess, "Popen") as launch:
            for label, envelope in invalid.items():
                with self.subTest(label=label):
                    with self.assertRaises(ValueError):
                        worker.submit(1, envelope)
            mismatched = dict(base, captures=[dict(base["captures"][0], bytes=base["captures"][0]["bytes"] + 1)])
            with self.assertRaisesRegex(RenderWorkerError, "size changed"):
                worker.submit(1, mismatched)
            worker.scene_path.unlink()
            with self.assertRaisesRegex(RenderWorkerError, "unavailable") as raised:
                worker.submit(1, base)
            self.assertEqual(raised.exception.code, "render_failed")
            with self.assertRaisesRegex(RuntimeError, "one numbered job"):
                worker.submit(-1, base)
            with self.assertRaises(RuntimeError):
                worker.borrow_snapshot(object())
            launch.assert_not_called()
        self.assertIsNone(worker.process)
        with self.assertRaises(ValueError):
            NativeRenderWorker(EXECUTABLE, self.folder, renderer="no-function")

    def test_child_error_validation_and_determinism(self):
        worker = self.worker()
        cases = [
            ({"code": "render_failed", "phase": "render", "message": "boom"}, ("render_failed", True)),
            ({"code": "render_failed", "phase": "verify", "message": "changed"}, ("render_failed", False)),
            ({"code": "render_failed", "phase": "import", "message": "missing"}, ("render_failed", False)),
            ({"code": "render_too_large", "phase": "render", "reason": "edges", "message": "big", "edges": 3},
             ("render_too_large", True)),
        ]
        for error, (code, deterministic) in cases:
            with self.subTest(error=error):
                result = worker.child_error({"ok": False, "error": error})
                self.assertEqual((result.code, result.deterministic), (code, deterministic))
                self.assertEqual(result.payload(), error)
        malformed = [
            {"ok": False, "error": None},
            {"ok": True, "error": {"code": "render_failed", "phase": "render", "message": "x"}},
            {"ok": False, "error": {"code": "render_timeout", "phase": "render", "message": "x"}},
            {"ok": False, "error": {"code": "render_failed", "phase": "elsewhere", "message": "x"}},
            {"ok": False, "error": {"code": "render_failed", "phase": "render", "reason": "memory", "message": "x"}},
            {"ok": False, "error": {"code": "render_too_large", "phase": "render", "reason": "planets", "message": "x"}},
            {"ok": False, "error": {"code": "render_failed", "phase": "render", "message": "x", "nested": {"a": 1}}},
            {"ok": "yes", "error": None},
        ]
        for response in malformed:
            with self.subTest(response=response):
                result = worker.child_error(response)
                self.assertEqual(result.code, "render_failed")
                self.assertIn("malformed", str(result))
                self.assertFalse(result.deterministic)
        self.assertIsNone(worker.child_error({"ok": True, "error": None}))
        self.assertEqual(worker.child_error(None).code, "render_failed")

        # A job that hit its commit limit names memory as the cause of a native failure.
        worker.memory_limit_hit = True
        crashed = worker.child_error({"ok": False, "error": {"code": "render_failed", "phase": "render",
                                                             "message": "OSError: Access violation"}})
        self.assertEqual((crashed.code, crashed.details["reason"], crashed.deterministic),
                         ("render_too_large", "memory", True))
        self.assertEqual(crashed.details["cause"], "OSError: Access violation")
        too_large = {"code": "render_too_large", "phase": "render", "reason": "triangles", "message": "big"}
        self.assertEqual(worker.child_error({"ok": False, "error": too_large}).payload(), too_large)
        self.assertIn("malformed", str(worker.child_error({"ok": False, "error": None})))
        self.assertIsNone(worker.child_error({"ok": True, "error": None}))
        # Escalation keeps the phase the child reported.
        loading = worker.child_error({"ok": False, "error": {"code": "render_failed", "phase": "load",
                                                             "message": "OSError: Access violation"}})
        self.assertEqual((loading.code, loading.details["phase"], loading.deterministic),
                         ("render_too_large", "load", True))
        worker.memory_limit_hit = False

        # Reserved keys can never reach RenderWorkerError's keyword arguments.
        for key, value in (("deterministic", False), ("self", 1), ("transient", "yes"), ("transient", False)):
            with self.subTest(reserved=key, value=value):
                error = {"code": "render_too_large", "phase": "render", "reason": "triangles", "message": "big",
                         key: value}
                result = worker.child_error({"ok": False, "error": error})
                self.assertEqual(result.code, "render_failed")
                self.assertIn("malformed", str(result))
        transient = {"code": "render_failed", "phase": "seal", "message": "PermissionError: locked", "transient": True}
        result = worker.child_error({"ok": False, "error": transient})
        self.assertEqual((result.code, result.deterministic), ("render_failed", False))
        self.assertEqual(result.payload(), {"code": "render_failed", "phase": "seal",
                                            "message": "PermissionError: locked"})

        # Every timeout reports timeout_seconds.
        running = self.worker(timeout=7)
        self.mock_completed(running)
        running.process.poll.return_value = None
        running.started = time.monotonic() - 8
        with self.assertRaises(RenderTimeout) as raised:
            running.poll()
        self.assertEqual(raised.exception.payload(), {"code": "render_timeout", "timeout_seconds": 7,
                                                      "message": "Render exceeded its 7 s time limit"})
        held = self.worker(timeout=7)
        self.mock_completed(held)
        with patch.object(render_worker, "_read_json", side_effect=PermissionError("scanner")):
            self.assertIsNone(held.poll(), "A held result is retried before the deadline")
            held.started = time.monotonic() - 8
            with self.assertRaises(RenderTimeout) as raised:
                held.poll()
        self.assertEqual(raised.exception.details, {"timeout_seconds": 7})
        self.assertEqual(as_render_error(TimeoutError("late"), timeout_seconds=7).details, {"timeout_seconds": 7})

    def test_child_error_mapping_marks_transient_and_drops_reserved_details(self):
        child, parent = render_worker._child_error, render_worker._child_error_from

        class TooLarge(Exception):
            code = "render_too_large"

            def __init__(self, details, reason=None):
                super().__init__("Too large")
                self.details, self.reason = details, reason

        error = child(TooLarge({"reason": "planets", "deterministic": False, "self": 1, "code": "x", "message": "y",
                                "transient": True, "phase": "seal", "faces": 7, "nested": [1], "ratio": float("nan")}),
                      "render")
        self.assertEqual(error, {"code": "render_too_large", "phase": "render", "message": "Too large", "faces": 7})
        accepted = parent({"ok": False, "error": error})
        self.assertEqual((accepted.code, accepted.deterministic, accepted.details), ("render_too_large", True,
                                                                                   {"phase": "render", "faces": 7}))
        self.assertEqual(child(TooLarge({"reason": "edges"}, reason="triangles"), "render")["reason"], "triangles")
        cases = [
            (PermissionError(13, "Sharing violation", "view-0.png"), "seal", True),
            (PermissionError("denied"), "render", True),
            (OSError(28, "No space left on device"), "render", True),
            (FileNotFoundError(2, "No such file", "DejaVuSans.ttf"), "render", True),
            (ModuleNotFoundError("No module named 'kurtshape.model_render'"), "render", True),
            (render_worker.RendererCallError("Renderer cannot be called as renderer(job): x"), "render", True),
            (OSError("Access violation"), "render", False),  # FreeCAD's native fault: repeats for these inputs
            (Part.OCCError("BRep_API: command not done"), "load", False),
            (RuntimeError("FreeCAD exception thrown (Wire is not closed.)"), "render", False),
            (ValueError("Renderer did not write view-0.png"), "seal", False),
        ]
        for exc, phase, transient in cases:
            with self.subTest(exc=repr(exc)):
                error = child(exc, phase)
                self.assertEqual((error["code"], error["phase"], error.get("transient")),
                                 ("render_failed", phase, True if transient else None))
                self.assertEqual(parent({"ok": False, "error": error}).deterministic, not transient)
        # MemoryError keeps its code; the parent weighs the cap evidence (test below).
        self.assertEqual(child(MemoryError(), "load"), {"code": "render_too_large", "reason": "memory", "phase": "load",
                                                        "message": "The render exceeded its memory limit"})

    def test_memory_classification_signals_are_independent(self):
        limit, margin = 256 * 2**20, render_worker.MEMORY_LIMIT_MARGIN_BYTES
        reported_memory = {"code": "render_too_large", "reason": "memory", "phase": "render",
                           "message": "The render exceeded its memory limit"}
        reported_fault = {"code": "render_failed", "phase": "load", "message": "OSError: Access violation"}
        reported_lock = {"code": "render_failed", "phase": "seal", "message": "PermissionError: x", "transient": True}
        for label, notified, peak, evidence in (("notification, low peak", True, 40 * 2**20, True),
                                                ("no notification, peak at cap", False, limit - 2**20, True),
                                                ("neither", False, limit - margin - 2**20, False)):
            with self.subTest(label=label):
                worker = self.worker(memory_limit=limit)
                self.mock_completed(worker, exit_code=9)
                worker.job = Mock(name="job", peak_process_memory=peak)
                worker.job.memory_limit_hit.return_value = notified
                with self.assertRaises(RenderWorkerError) as raised:
                    worker.poll()
                worker.job.record_peak.assert_called_once_with()
                worker.job.memory_limit_hit.assert_called_once_with(4242)
                self.assertEqual(worker.memory_limit_hit, notified)
                died = raised.exception
                if evidence:
                    self.assertEqual((died.code, died.details["reason"], died.deterministic),
                                     ("render_too_large", "memory", True))
                    self.assertEqual(died.details["peak_commit_mb"], round(peak / 2**20, 1))
                    self.assertNotIn("phase", died.details)
                else:
                    self.assertEqual((died.code, died.details, died.deterministic),
                                     ("render_failed", {"exit_code": 9}, False))
                memory = worker.child_error({"ok": False, "error": reported_memory})
                self.assertEqual((memory.code, memory.details["reason"], memory.deterministic),
                                 ("render_too_large", "memory", evidence),
                                 "A MemoryError without cap evidence is system commit exhaustion")
                self.assertEqual(memory.details["peak_commit_mb"], round(peak / 2**20, 1))
                fault = worker.child_error({"ok": False, "error": reported_fault})
                lock = worker.child_error({"ok": False, "error": reported_lock})
                if evidence:
                    self.assertEqual((fault.code, fault.details["phase"], fault.deterministic),
                                     ("render_too_large", "load", True))
                    self.assertEqual((lock.code, lock.details["phase"]), ("render_too_large", "seal"))
                else:
                    self.assertEqual((fault.code, fault.deterministic), ("render_failed", True))
                    self.assertEqual((lock.code, lock.deterministic), ("render_failed", False))
        bare = self.worker()  # no Job Object (e.g. off Windows): no cap evidence at all
        self.assertIsNone(bare.job)
        self.assertFalse(bare.child_error({"ok": False, "error": reported_memory}).deterministic)

    @WINDOWS_ONLY
    def test_seal_retries_a_scanner_lock_then_reports_it_transient(self):
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                         wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        folder = support.scratch(self, prefix="render-seal-")
        path = folder / "view-0.png"
        path.write_bytes(png_bytes(160, 128))

        def hold():  # GENERIC_READ, no sharing, OPEN_EXISTING: what a scanner's exclusive open does
            handle = kernel32.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)
            if handle in (None, wintypes.HANDLE(-1).value):
                raise ctypes.WinError(ctypes.get_last_error())
            return handle
        handle = hold()
        with self.assertRaises(PermissionError):
            render_worker.png_info(path)
        release = threading.Timer(.4, kernel32.CloseHandle, (handle,))
        release.start()
        self.addCleanup(release.cancel)
        began = time.monotonic()
        info = render_worker._seal_png(path, seconds=10)
        self.assertGreaterEqual(time.monotonic() - began, .3, "The seal waited for the lock")
        self.assertEqual((info["width"], info["height"]), (160, 128))

        handle = hold()
        self.addCleanup(kernel32.CloseHandle, handle)
        with self.assertRaises(PermissionError) as raised:
            render_worker._seal_png(path, seconds=.3)
        error = render_worker._child_error(raised.exception, "seal")
        self.assertTrue(error["transient"])
        self.assertFalse(render_worker._child_error_from({"ok": False, "error": error}).deterministic)
        with self.assertRaisesRegex(ValueError, "did not write view-1.png"):
            render_worker._seal_png(folder / "view-1.png")

    def test_default_renderer_adapter_refuses_miswired_scenes_before_rendering(self):
        self.assertIs(render_worker._load_renderer(render_worker.DEFAULT_RENDERER), render_worker.render_scene)
        folder = support.scratch(self, prefix="render-adapter-")
        image = {"view": "iso", "name": "view-0.png", "width": 160, "height": 128}
        settings = {"views": ["iso"], "size": [160, 128], "quality": "draft"}
        part = [{"brep": "part-0"}]
        cases = {
            "not an object": ([], "JSON object"),
            "settings type": ({"settings": ["iso"]}, "settings must be an object"),
            "metadata type": ({"settings": settings, "metadata": "r1"}, "metadata must be an object"),
            "view count": ({"settings": dict(settings, views=["iso", "top"]), "parts": part}, "job expects"),
            "image size": ({"settings": dict(settings, size=[200, 128]), "parts": part}, "job expects"),
            "sheet": ({"settings": dict(settings, views=["iso", "top"], layout="sheet"), "parts": part}, "job expects"),
            "default size": ({"parts": part}, "job expects"),
            "unknown capture": ({"settings": settings, "parts": [{"brep": "part-9.brep"}]}, "unknown capture"),
            "unknown highlight": ({"settings": settings, "parts": part, "highlights": [{"rendered": "hl-0-r"}]},
                                  "unknown capture"),
            "parts type": ({"settings": settings, "parts": {"brep": "part-0"}}, "list of objects"),
        }
        for label, (scene, text) in cases.items():
            with self.subTest(label=label):
                job = render_worker.RenderInput(folder, scene, {"part-0": Part.makeBox(1, 2, 3)}, [dict(image)],
                                                SETTINGS_DIGEST, {})
                with self.assertRaisesRegex(ValueError, text):
                    render_worker.render_scene(job)
        self.assertEqual(list(folder.iterdir()), [], "A refused scene renders nothing")

    @WINDOWS_ONLY
    def test_job_object_limits_and_idempotent_close(self):
        with self.assertRaises(ValueError):
            JobObject.create(1024)
        job = JobObject.create(256 * 2**20)
        limits = job.limits()
        self.assertEqual(limits["process_memory_limit"], 256 * 2**20)
        self.assertEqual(limits["limit_flags"], render_worker.JOB_LIMIT_FLAGS)
        self.assertFalse(job.closed)
        self.assertIsNotNone(job.port, "Memory-limit notifications need the job's completion port")
        self.assertEqual(job.drain(), [])
        self.assertFalse(job.memory_limit_hit())
        job.release()
        job.close()
        self.assertTrue(job.closed)
        with self.assertRaises(RuntimeError):
            job.limits()
        with self.assertRaises(RuntimeError):
            job.assign(Mock(_handle=0, pid=1))
        self.assertIsNone(job.record_peak())


# --- U4: the owner-thread render_view service ---------------------------------

import uuid  # noqa: E402

from kurtshape import render_jobs, model_render, selectors as native_selectors  # noqa: E402
from kurtshape.core import Controller  # noqa: E402

SMALL = {"size": [320, 240], "quality": "draft"}


def top_face(part="Body", point=(10, 10, 10)):
    """A studio part's face by its closest point (part ids do not name the native result object)."""
    return {"kind": "closest", "point": list(point), "query": {"kind": "owned_by", "part": part, "entity_type": "face"}}
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class RenderFixture:
    """A real Controller in an isolated session; documents are built through dispatch.

    Real renders use the production child at 320x240 draft; job-mechanics tests swap the
    child's renderer for FIXTURE_RENDERER functions (``fake``), which still run in a real child.
    """

    def setUp(self):
        self.initial = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="render-jobs-")
        self.core = Controller()
        self.core.settings.roots.add(self.folder)
        self.fixture = self.folder / "fixture_renderer.py"
        self.fixture.write_text(FIXTURE_RENDERER, encoding="utf-8")
        self.state = None
        self.workers = 0
        self.addCleanup(self.close_all)

    def close_all(self):
        self.core.close()
        for name in set(App.listDocuments()) - self.initial:
            App.closeDocument(name)

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def new(self, name="Render"):
        response = self.core.dispatch({"op": "new", "name": name})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        return self.state

    def request(self, op, **args):
        return self.core.dispatch({"op": op, "document_id": self.state["document_id"],
                                   "expected_revision": self.state["revision"], **args})

    def call(self, op, **args):
        response = self.request(op, **args)
        self.assertTrue(response["ok"], response)
        if "revision" in response["result"]:
            self.state = response["result"]
        return response["result"]

    def render(self, begin=False, **args):
        request = {"op": "render_view", "document_id": self.state["document_id"], **SMALL, **args}
        return (self.core.begin if begin else self.core.dispatch)(request)

    def rendered(self, **args):
        response = self.render(**args)
        self.assertTrue(response["ok"], response)
        return response["result"]

    def refused(self, code, **args):
        response = self.render(**args)
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], code, response["error"])
        return response["error"]

    def fake(self, renderer):
        self.core.renders.renderer = str(self.fixture) + ":" + renderer

    def count_workers(self):
        service = self.core.renders
        original = service._new_worker

        def counted():
            self.workers += 1
            return original()
        service._new_worker = counted

    def release(self):
        (self.core.renders.active.worker.folder / "release").write_bytes(b"1")

    def block(self, width=20, length=10):
        self.new()
        self.call("sketch_rectangle", id="Base", width=width, height=20)
        self.call("pad", id="Block", profile="Base", length=length, operation="new")

    def invariant(self):
        doc = self.doc
        meta = self.core._meta(doc)
        state = self.core.observer.state(doc)
        return {"revision": meta.Revision, "undo": doc.UndoCount, "redo": doc.RedoCount,
                "change_serial": state["change_serial"], "generation": state["generation"],
                "labels": sorted((obj.Name, obj.Label) for obj in doc.Objects),
                "visibility": sorted((obj.Name, bool(getattr(obj, "Visibility", True))) for obj in doc.Objects),
                "last_failure": meta.LastFailure, "last_failed_attempt": self.core.last_failures.get(meta.DocumentId),
                "active": App.ActiveDocument.Name if App.ActiveDocument else None,
                "modified": self.core.document_modified(doc)}


class RenderJobTests(RenderFixture, unittest.TestCase):
    # --- contract and registry ------------------------------------------------
    def test_mirrored_constants_match_model_render(self):
        for name in ("RENDERER", "RENDERER_VERSION", "VIEW_NAMES", "STANDARD_VIEWS", "LAYOUTS", "QUALITIES", "FRAMES",
                     "DEFAULT_SIZE", "DEFAULT_SHEET_SIZE", "SHEET_GAP_PX", "SHEET_FOOTER_PX", "LEGEND_ROW_PX", "PARALLEL_COS",
                     "FONT_FILES", "HIGHLIGHT_COLORS", "CAPTION_NOTE", "RESPONSE_NOTE"):
            self.assertEqual(getattr(render_jobs, name), getattr(model_render, name), name)
        self.assertEqual(render_jobs.font_id(), model_render.font_id())
        self.assertEqual([render_jobs.highlight_color(i) for i in range(10)], [model_render.highlight_color(i) for i in range(10)])
        self.assertEqual({k: tuple(v) for k, v in render_jobs.SECTION_PLANES.items()},
                         {k: tuple(v) for k, v in model_render.SECTION_PLANES.items()})
        self.assertEqual((render_jobs.MIN_SIDE, render_jobs.MAX_SIDE, render_jobs.MAX_PIXELS, render_jobs.MAX_VIEWS),
                         (render_worker.MIN_SIDE, render_worker.MAX_SIDE, render_worker.MAX_PIXELS, render_worker.MAX_IMAGES))
        self.assertEqual(render_jobs.JOB_TIMEOUT_SECONDS, render_worker.JOB_TIMEOUT_SECONDS)
        for views, size, legend in ((2, [1024, 768], 0), (5, [1536, 1152], 8), (7, [900, 800], 3)):
            self.assertEqual(render_jobs.sheet_tile(views, size, legend),
                             tuple(model_render.sheet_geometry(views, size, legend)[2:4]))

    def test_capabilities_and_diagnostics_blocks(self):
        capabilities = self.core.dispatch({"op": "capabilities"})["result"]
        self.assertEqual(capabilities["render"], render_jobs.capabilities())
        self.assertIn("render_view", capabilities["non_mutating_operations"])
        self.assertNotIn("render_view", capabilities["read_operations"])
        self.assertNotIn("render_view", capabilities["preview_operations"])
        self.assertEqual(self.core.dispatch({"op": "diagnostics"})["result"]["renders"], {"active": False})
        self.assertIsNone(self.core._renders, "capabilities and diagnostics create no render service")

    def test_invalid_arguments_are_rejected_before_any_capture(self):
        self.block()
        self.count_workers()
        everything = {"kind": "owned_by", "part": "Body", "entity_type": "face"}
        cases = [({"views": ["iso", "iso"]}, "views", "duplicate"),
                 ({"views": [{"direction": [0, 0, 1], "up": [0, 0, 2]}]}, "views", "parallel_up"),
                 ({"views": [{"direction": [0, 0, 0]}]}, "views", "zero_vector"),
                 ({"views": ["section"]}, "views", "requires_section"),
                 ({"views": ["iso", "front", "back", "right", "left", "top", "bottom", "iso"]}, "views", "count"),
                 ({"layout": "sheet"}, "layout", "count"),
                 ({"size": [100, 240]}, "size", "range"), ({"size": [2048, 2048]}, "size", "range"),
                 ({"size": [320.0, 240]}, "size", "type"),
                 ({"layout": "sheet", "views": ["iso", "front", "top", "right", "left"], "size": [700, 600]}, "size", "range"),
                 ({"highlights": [{"selector": everything, "label": "A\x07"}]}, "highlights", "label"),
                 ({"highlights": [{"selector": everything, "label": " A"}]}, "highlights", "label"),
                 ({"highlights": [{"selector": everything, "label": "A"}, {"selector": everything, "label": "A"}]},
                  "highlights", "duplicate"),
                 ({"highlights": [{"selector": everything}] * 9}, "highlights", "count"),
                 ({"highlights": [{"selector": everything, "input": {"feature": "Block", "name": "x"}}]}, "highlights", "type"),
                 ({"labels": 1}, "labels", "type"), ({"frame": {"center_mm": [0, 0, 0], "width_mm": 0}}, "frame", "range"),
                 ({"section": {"plane": "XW"}}, "section", "value"), ({"section": {"datum": "Base"}}, "section", "unknown_datum"),
                 ({"parts": []}, "parts", "type"), ({"sketches": "always"}, "sketches", "value")]
        for args, field, reason in cases:
            with self.subTest(args=args):
                error = self.refused("invalid_argument", **args)
                self.assertEqual((error["fields"], error["reason"]), ([field], reason))
        self.assertEqual(self.workers, 0)
        self.assertFalse(list(self.core.renders.owner.glob("cap-*")), "no capture for a rejected request")
        self.assertEqual(self.refused("unknown_argument", camera="iso")["fields"], ["camera"])

    # --- the real renderer ------------------------------------------------------
    def test_render_view_png_is_revision_bound_and_document_untouched(self):
        self.block()
        self.call("sketch_circle", id="Hole", x=10, y=10, diameter=6)
        self.call("pocket", id="Bore", profile="Hole", through_all=True, operation="remove", merge_scope=["Body"])
        before = self.invariant()
        response = self.core.dispatch({"op": "render_view", "document_id": self.state["document_id"],
                                       "request_id": "render-untouched", **SMALL})
        self.assertTrue(response["ok"], response)
        result = response["result"]
        self.assertEqual(self.invariant(), before)
        self.assertEqual((result["revision"], result["stale"], result["cached"]), (self.state["revision"], False, False))
        image = result["images"][0]
        path = Path(image["path"])
        self.assertEqual(path.parent, Path(self.core.settings.path.parent).resolve() / "renders" / self.core.ledger.session_id)
        data = path.read_bytes()
        self.assertEqual(data[:8], PNG_MAGIC)
        self.assertEqual(struct.unpack(">II", data[16:24]), (320, 240))
        self.assertEqual((len(data), hashlib.sha256(data).hexdigest()), (image["bytes"], image["sha256"]))
        self.assertEqual(result["parts"][0]["part"], "Body")
        self.assertGreater(result["parts"][0]["triangles"], 0)
        self.assertEqual(result["geometry_status"]["banners"], [])
        self.assertEqual(result["geometry_status"]["note"], model_render.RESPONSE_NOTE)
        self.assertEqual(self.core.ledger.status("render-untouched")["response"], response)

    def test_failing_render_writes_no_failure_metadata(self):
        self.block()
        rejected = self.request("pad", id="Ghost", profile="Missing", length=3, operation="new")
        self.assertFalse(rejected["ok"])
        before = self.invariant()
        self.assertIsNotNone(before["last_failed_attempt"])
        self.refused("highlight_no_match", highlights=[{"selector": {"feature": "Block", "subelement": "Face99"}}])
        self.refused("section_misses_parts", section={"plane": "XY", "offset": 100})
        self.refused("invalid_argument", views=[{"direction": [1, 0, 0], "up": [1, 0, 0]}])
        self.refused("missing_part", parts=["Nope"])
        self.refused("invalid_selector", highlights=[{"selector": {"kind": "nonsense"}}])
        self.core.renders.limits["faces"] = 1
        self.refused("render_too_large")
        self.assertEqual(self.invariant(), before)

    def test_highlights_match_resolve_selector_and_errors_carry_the_index(self):
        self.block()
        selector = {"kind": "owned_by", "part": "Body", "entity_type": "edge"}
        expected = self.call("resolve_selector", selector=selector)["matches"]
        result = self.rendered(highlights=[{"selector": selector, "label": "E", "note": "all edges"}])
        row = result["highlights"][0]
        self.assertEqual([(m["feature"], m["subelement"]) for m in row["matches"]],
                         [(m["feature"], m["subelement"]) for m in expected])
        self.assertEqual((row["label"], row["note"], row["count"], row["rendered_count"]), ("E", "all edges", 12, 12))
        self.assertTrue(result["images"][0]["highlights"][0]["visible"])
        error = self.refused("invalid_selector", highlights=[{"selector": selector}, {"selector": {"kind": "bogus"}}])
        self.assertEqual(error["highlight"], 1)
        with patch.object(render_jobs, "MAX_ITEM_MATCHES", 5):
            error = self.refused("too_many_highlight_matches", highlights=[{"selector": selector}])
        self.assertEqual((error["highlight"], error["count"]), (0, 12))

    def test_highlight_classification_sketch_filtered_history(self):
        self.block()
        self.call("create_body", id="Tool", name="Tool")
        self.call("sketch_rectangle", id="ToolProfile", body="Tool", x=40, y=0, width=10, height=10)
        self.call("pad", id="ToolBlock", profile="ToolProfile", body="Tool", length=5, operation="new")
        self.call("sketch_circle", id="Loose", body="Body", x=10, y=10, diameter=4)
        self.call("sketch_circle", id="Hole", body="Body", x=5, y=5, diameter=3)
        self.call("pocket", id="Bore", profile="Hole", through_all=True, operation="remove", merge_scope=["Body"])
        ghosts = [{"selector": {"feature": "Loose", "subelement": "Edge1"}, "label": "S"},
                  {"selector": top_face("Tool", (45, 5, 5)), "label": "F"},
                  {"selector": {"feature": "Block", "subelement": "Face1"}, "label": "H"}]
        result = self.rendered(parts=["Body"], highlights=ghosts + [{"selector": top_face(), "label": "R"}])
        reasons = {row["label"]: [match["reason"] for match in row["matches"]] for row in result["highlights"]}
        self.assertEqual(reasons, {"S": ["sketch"], "F": ["filtered_part"], "H": ["history"], "R": [None]})
        image = {row["label"]: row for row in result["images"][0]["highlights"]}
        for label in "SFH":
            self.assertFalse(image[label]["visible"], label)
            self.assertEqual(image[label]["visible_px"], 0, label)
        self.assertTrue(image["R"]["visible"])
        self.assertEqual([row["part"] for row in result["omitted_parts"]], ["Tool"])
        self.refused("highlight_not_rendered", parts=["Body"], frame="highlights", highlights=ghosts)

    def test_stored_input_highlight_matches_native_references(self):
        self.block()
        edge = {"kind": "closest", "point": [20, 10, 10], "query": {"kind": "owned_by", "part": "Body", "entity_type": "edge"}}
        self.call("fillet", id="Round", edges=[edge], radius=2)
        refs = native_selectors.stored_input_refs(self.doc.getObject("Round"), "edges_0")
        result = self.rendered(highlights=[{"input": {"feature": "Round", "name": "edges_0"}, "label": "In"}])
        row = result["highlights"][0]
        self.assertEqual(row["source"], {"input": {"feature": "Round", "name": "edges_0"}})
        self.assertEqual([{"feature": m["feature"], "subelement": m["subelement"]} for m in row["matches"]], refs)
        self.assertEqual([m["reason"] for m in row["matches"]], ["history"], "the fillet's input edge is consumed")
        error = self.refused("missing_input", highlights=[{"input": {"feature": "Round", "name": "nope"}}])
        self.assertEqual((error["highlight"], error["available"]), (0, ["edges_0"]))

    def test_nested_container_parts_and_highlights_align_in_an_unmanaged_file(self):
        native = App.newDocument("Nested")
        container = native.addObject("App::Part", "Assy")
        container.Placement.Base = App.Vector(100, 0, 0)
        body = native.addObject("PartDesign::Body", "Body")
        container.addObject(body)
        box = native.addObject("Part::Feature", "Stock")
        box.Shape = Part.makeBox(10, 10, 10)
        body.BaseFeature = box
        native.recompute()
        path = self.folder / "nested.FCStd"
        native.saveAs(str(path))
        App.closeDocument(native.Name)
        response = self.core.dispatch({"op": "open", "path": str(path)})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        self.assertFalse(self.state["managed"])
        face = {"feature": "Body", "subelement": "Face6"}
        center = self.call("resolve_selector", selector=face)["matches"][0]["summary"]["center_mm"]
        result = self.rendered(parts=["Body"], frame="highlights", highlights=[{"selector": face}])
        part = result["parts"][0]
        self.assertEqual((part["in_container"], part["visibility_source"]), (True, "object"))
        self.assertIn("frame_note", result)
        self.assertGreaterEqual(center[0], 100)
        camera = result["images"][0]["camera"]
        self.assertAlmostEqual(camera["center_mm"][0], center[0], delta=1.0)
        self.assertTrue(result["images"][0]["highlights"][0]["visible"])
        self.assertIn("unmanaged", [row["kind"] for row in result["geometry_status"]["banners"]])

    def assembly_source(self):
        """test_assembly's asymmetric source: one Body holding a 4 x 6 x 8 box at (1, 2, 0)."""
        source = App.newDocument("RenderAssemblySource")
        try:
            body = source.addObject("PartDesign::Body", "SourceBody")
            body.newObject("PartDesign::Feature", "SourceSolid").Shape = Part.makeBox(4, 6, 8, App.Vector(1, 2, 0))
            source.recompute()
            path = self.folder / "render-assembly-source.FCStd"
            source.saveAs(str(path))
            return path
        finally:
            App.closeDocument(source.Name)
            App.setActiveDocument(self.doc.Name)

    def test_assembly_occurrences_render_in_world(self):
        self.new("Render assembly")
        path = self.assembly_source()
        self.call("create_assembly", id="RenderAssembly", name="Render assembly")
        for identity in ("Base", "Fastened", "Spare"):  # three occurrences of one source
            self.call("insert_assembly_part", path=str(path), source_id="SourceBody", id=identity, name=identity)
        self.call("ground_assembly_instance", instance="Base")
        quarter = [0, 0, 0.7071067811865475, 0.7071067811865476]  # 90 degrees about +Z
        self.call("move_assembly_instance", instance="Fastened", position_mm=[30, 4, 5], rotation_xyzw=quarter)
        state = self.call("inspect")
        self.assertEqual(state["build_status"], "valid", state["build_errors"])
        top = {"feature": "Fastened", "subelement": "Face6"}
        center = self.call("resolve_selector", selector=top)["matches"][0]["summary"]["center_mm"]
        # The source's top face centre (3, 5, 8) turned about +Z to (-5, 3, 8), then moved by (30, 4, 5).
        for actual, expected in zip(center, (25, 7, 13)):
            self.assertAlmostEqual(actual, expected, places=6)
        result = self.rendered(parts=["Base", "Fastened"], highlights=[{"selector": top, "label": "T"}],
                               frame="highlights", views=["top"])
        self.assertEqual(result["geometry_status"]["build_status"], "valid")
        self.assertEqual(sorted(row["part"] for row in result["parts"]), ["Base", "Fastened"])
        self.assertEqual([(row["part"], row["reason"]) for row in result["omitted_parts"]], [("Spare", "filtered")])
        self.assertFalse(any(row["in_container"] for row in result["parts"]), "occurrences are placed like inspect")
        self.assertNotIn("frame_note", result)
        self.assertEqual([m["reason"] for m in result["highlights"][0]["matches"]], [None])
        image = result["images"][0]
        self.assertTrue(image["highlights"][0]["visible"])
        for actual, expected in zip(image["camera"]["center_mm"][:2], center[:2]):
            self.assertAlmostEqual(actual, expected, delta=0.5)
        framed = self.rendered(parts=["Fastened"], views=["iso"])["images"][0]["camera"]["center_mm"]
        for actual, expected in zip(framed, (25, 7, 9)):  # the turned occurrence's world box centre
            self.assertAlmostEqual(actual, expected, delta=0.5)
        # Moving the assembly natively (outside any managed operation) fails the native build; the image is
        # retained geometry and stays aligned with the selector world frame.
        self.doc.getObject("RenderAssembly").Placement.Base = App.Vector(100, 20, 0)
        self.doc.recompute()
        self.call("inspect")
        moved = self.call("resolve_selector", selector=top)["matches"][0]["summary"]["center_mm"]
        for actual, expected in zip(moved, (125, 27, 13)):
            self.assertAlmostEqual(actual, expected, places=6)
        result = self.rendered(parts=["Fastened"], highlights=[{"selector": top}], frame="highlights", views=["top"])
        status = result["geometry_status"]
        self.assertEqual((status["build_status"], status["geometry"], status["banners"][0]["kind"]),
                         ("failed", "retained", "build_failed"))
        for actual, expected in zip(result["images"][0]["camera"]["center_mm"][:2], moved[:2]):
            self.assertAlmostEqual(actual, expected, delta=0.5)

    def test_non_solid_result_flagged_and_visible_parts_fall_back_to_object_visibility(self):
        native = App.newDocument("Sheets")
        body = native.addObject("PartDesign::Body", "Body")
        sheet = native.addObject("Part::Feature", "Sheet")
        sheet.Shape = Part.makePlane(10, 10)
        body.BaseFeature = sheet
        native.recompute()
        path = self.folder / "sheets.FCStd"
        native.saveAs(str(path))
        App.closeDocument(native.Name)
        response = self.core.dispatch({"op": "open", "path": str(path)})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        result = self.rendered()
        self.assertEqual(sorted(result["geometry_status"]["non_solid_parts"]), ["Body", "Sheet"])
        self.assertEqual([row["solid"] for row in result["parts"]], [False, False])
        self.assertEqual(result["geometry_status"]["banners"][0]["text"], "NOT A SOLID: 2 PARTS")
        self.doc.getObject("Sheet").Visibility = False
        result = self.rendered(parts="visible")
        self.assertEqual([row["part"] for row in result["parts"]], ["Body"])
        self.assertEqual(result["omitted_parts"], [{"part": "Sheet", "body": "Sheet", "reason": "filtered"}])

    def test_failed_build_renders_retained_geometry(self):
        self.block()
        # A native edit outside any managed operation over-constrains the profile: the build fails and
        # the part keeps its last recomputed shape.
        self.doc.getObject("Base").addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, 50.0))
        self.doc.recompute()
        result = self.rendered()
        status = result["geometry_status"]
        self.assertEqual((status["build_status"], status["geometry"]), ("failed", "retained"))
        self.assertEqual(status["banners"][0], {"kind": "build_failed", "text": "RETAINED GEOMETRY · BUILD FAILED",
                                                "color": "red"})
        self.assertGreater(result["parts"][0]["triangles"], 0, "the retained shape is drawn")
        self.doc.getObject("Base").delConstraint(self.doc.getObject("Base").ConstraintCount - 1)
        self.doc.recompute()
        self.doc.getObject("Block").touch()
        result = self.rendered()
        self.assertEqual((result["geometry_status"]["geometry"], result["geometry_status"]["banners"][0]["kind"]),
                         ("retained", "needs_rebuild"))

    def test_validation_pending_and_failed_banners_keep_geometry_current(self):
        self.block()
        self.call("create_sketch", id="Cap", plane="XY")
        self.call("add_rectangle", sketch="Cap", width=20, height=20)
        self.call("pad", id="Raise", profile="Cap", length=15, operation="add", merge_scope=["Body"])
        self.call("create_plane", id="TopPlane", origin=[0, 0, 15], normal=[0, 0, 1])
        self.call("create_sketch", id="TopSketch", support={"feature": "TopPlane"})
        self.call("add_rectangle", sketch="TopSketch", x=8, y=8, width=4, height=4)
        self.call("pocket", id="TopCut", profile="TopSketch", length=3, through_all=False, reversed=True,
                  operation="remove", merge_scope=["Body"])
        self.doc.getObject("Raise").KurtShapeTool.LengthFwd = 11
        self.doc.recompute()
        self.call("inspect")
        result = self.rendered()
        self.assertEqual(result["geometry_status"]["validation"]["status"], "pending")
        self.assertIn("validation_pending", [row["kind"] for row in result["geometry_status"]["banners"]])
        self.call("check_geometry")
        result = self.rendered()
        status = result["geometry_status"]
        self.assertEqual((status["build_status"], status["validation"]["status"], status["validation"]["failed"]),
                         ("failed", "failed", ["TopCut"]))
        kinds = [row["kind"] for row in status["banners"]]
        self.assertIn("validation_failed", kinds)
        self.assertNotIn("build_failed", kinds, "a result-check failure is current geometry, not retained")
        self.assertEqual((status["geometry"], result["parts"][0]["geometry"]), ("current", "current"))

    def test_named_section_plane_matches_create_plane_datum(self):
        self.block()
        self.call("create_plane", id="Cut", body="Body", base_plane="XZ", offset=-5)
        named = self.rendered(section={"plane": "XZ", "offset": -5}, views=["section", "iso"])
        datum = self.rendered(section={"datum": "Cut"}, views=["section", "iso"])
        for result in (named, datum):
            section = result["settings"]["section"]
            self.assertEqual([round(c, 9) + 0.0 for c in section["normal"]], [0.0, -1.0, 0.0])
            self.assertAlmostEqual(sum(o * n for o, n in zip(section["origin"], section["normal"])), -5, places=6)
            self.assertEqual(len(result["images"]), 2)
            for image in result["images"]:
                self.assertIsNotNone(image["section"], "the cut applies to every view")
                self.assertGreater(image["section"]["cap_faces"], 0)
        self.assertEqual(named["settings"]["section"]["origin"], [0.0, 5.0, 0.0], "XZ offset -5 is the plane y = 5")
        self.assertEqual(named["images"][0]["camera"]["direction"], [0.0, 1.0, 0.0], "the section view looks along -normal")

    def test_frame_highlights_needs_a_shown_match_on_the_kept_side(self):
        self.block()
        self.count_workers()
        self.refused("highlight_not_rendered", frame="highlights")
        # The face exists and is rendered, but the section removes all of it (top face z = 10, cut above z = 5).
        self.refused("highlight_not_rendered", frame="highlights", highlights=[{"selector": top_face()}],
                     section={"origin": [0, 0, 5], "normal": [0, 0, 1]})
        self.assertEqual(self.workers, 0, "refused on the owner thread, never as a remembered render_failed")

    def test_a_failure_after_the_child_answered_completes_every_joined_request(self):
        self.block()
        self.fake("gated")
        first = self.render(begin=True, request_id="after-a")
        joined = self.render(begin=True, request_id="after-b")
        service = self.core.renders
        with patch.object(service, "_result", side_effect=RuntimeError("response builder broke")):
            self.release()
            response = first.wait()
        self.assertEqual(response["error"]["code"], "render_failed")
        self.assertEqual(joined.poll(), response)
        self.assertIsNone(service.active, "the service is free for the next render")
        for rid in ("after-a", "after-b"):
            self.assertEqual(self.core.ledger.status(rid)["status"], "failed")
        self.fake("ok")
        self.assertTrue(self.render(views=["front"])["ok"])

    def test_owner_process_never_imports_numpy(self):
        child = self.folder / "owner-child"
        child.mkdir()
        script = self.folder / "owner_child.py"
        script.write_text(OWNER_NUMPY_SCRIPT, encoding="utf-8")
        environment = dict(os.environ, KURTSHAPE_SESSION_DIR=str(child))
        completed = subprocess.run([str(EXECUTABLE), "-B", str(script), str(ROOT / "src"), str(self.fixture)],
                                   capture_output=True, text=True, timeout=120, env=environment,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        facts = json.loads(completed.stdout.strip().splitlines()[-1])
        self.assertTrue(facts["ok"], facts)
        self.assertEqual((facts["numpy"], facts["pil_image"], facts["model_render"]), (False, False, False), facts)

    def test_section_misses_parts_rejected_on_owner_thread(self):
        self.block()
        self.count_workers()
        error = self.refused("section_misses_parts", section={"origin": [0, 0, -1], "normal": [0, 0, 1]})
        self.assertEqual(error["side"], "removed")
        self.refused("section_misses_parts", section={"plane": "YZ", "offset": 50})
        self.assertEqual(self.workers, 0)

    def test_sketch_only_model_renders_sketch_wires_and_none_gives_no_geometry(self):
        self.new()
        self.call("sketch_rectangle", id="Outline", width=30, height=10)
        result = self.rendered()
        self.assertEqual(result["sketches"], ["Outline"])
        self.assertEqual([row["faces"] for row in result["parts"]], [0] * len(result["parts"]))
        self.refused("no_geometry", sketches="none")
        body = self.doc.getObject("Body")
        if "KurtShapePartVisible" in body.PropertiesList:
            body.KurtShapePartVisible = False
        else:
            body.Visibility = False
        self.refused("no_geometry", parts="visible")  # a hidden sketch-only Body's sketches are filtered out too

    # --- caches, capture reuse and job mechanics (fixture renderers) ---------------
    def test_cache_hit_reuses_path_without_worker(self):
        self.block()
        self.fake("ok")
        self.count_workers()
        first = self.rendered()
        second = self.rendered()
        self.assertEqual(self.workers, 1)
        self.assertEqual((second["cached"], second["stale"]), (True, False))
        self.assertEqual(second["images"], first["images"])
        self.assertEqual(second["render_id"], first["render_id"])

    def test_capture_reused_across_settings_only_change_and_missed_after_an_edit(self):
        self.block()
        self.fake("ok")
        self.count_workers()
        face = top_face()
        with patch.object(native_selectors, "world_shape", wraps=native_selectors.world_shape) as spy:
            iso = self.rendered()
            section = self.rendered(section={"plane": "XZ", "offset": -5})
            labelled = self.rendered(highlights=[{"selector": face, "label": "A"}])
            relabelled = self.rendered(highlights=[{"selector": face, "label": "B"}])
            self.assertEqual(spy.call_count, 1, "one part exported once; presentation changes reuse the capture")
            self.assertEqual(self.workers, 4)
            self.assertEqual(len({iso["render_id"], section["render_id"], labelled["render_id"], relabelled["render_id"]}), 4)
            self.doc.Label = "Retitled"
            retitled = self.rendered()
            self.assertNotEqual(retitled["render_id"], iso["render_id"], "the drawn title is part of the image key")
            calls = spy.call_count
            self.call("inspect")  # the native title change rotated the revision at the render's sync
            self.call("edit_extrusion", feature="Block", length=12)
            edited = self.rendered()
            self.assertNotEqual(edited["revision"], iso["revision"])
            self.assertEqual(spy.call_count, calls + 1, "a model edit captures again")

    def test_render_busy_for_distinct_request_and_identical_joins(self):
        self.block()
        self.fake("gated")
        self.count_workers()
        first = self.render(begin=True, request_id="busy-a")
        joined = self.render(begin=True, request_id="busy-b")
        self.assertIsInstance(first, render_jobs.Deferred)
        self.assertIs(joined.job, first.job)
        self.assertEqual(self.core.ledger.status("busy-a")["status"], "started")
        busy = self.render(begin=True, request_id="busy-c", views=["front"])
        self.assertEqual(busy["error"]["code"], "render_busy")
        self.assertTrue(250 <= busy["error"]["retry_after_ms"] <= 5000)
        self.assertEqual(busy["error"]["active_render_id"], first.job.key[:16])
        self.release()
        response = first.wait()
        self.assertTrue(response["ok"], response)
        self.assertEqual(joined.wait(), response)
        self.assertEqual(self.workers, 1)
        for rid in ("busy-a", "busy-b"):
            self.assertEqual(self.core.ledger.status(rid)["status"], "completed")
        self.assertEqual(self.core.ledger.status("busy-c")["status"], "failed")

    def test_deterministic_failure_negative_cache_no_second_worker(self):
        self.block()
        self.fake("too_large")
        self.count_workers()
        first = self.refused("render_too_large")
        self.assertEqual((first["reason"], first["triangles"]), ("triangles", 2600000))
        second = self.refused("render_too_large")
        self.assertTrue(second["cached"])
        self.assertEqual(self.workers, 1)
        self.assertEqual(self.core.dispatch({"op": "diagnostics"})["result"]["renders"]["negative_entries"], 1)

    def test_budget_overrun_is_not_negatively_cached(self):
        self.block()
        self.count_workers()
        self.core.renders.renderer_limits = {"deadline_seconds": 0}
        error = self.refused("render_too_large")
        self.assertEqual(error.get("budget_seconds"), 0)
        self.refused("render_too_large")
        self.assertEqual(self.workers, 2, "a load-dependent budget overrun is retried, not cached")

    def test_stale_flag_on_property_write_during_the_job(self):
        self.block()
        self.fake("gated")
        handle = self.render(begin=True)
        self.doc.getObject("Base").Label = "Renamed profile"
        self.release()
        result = handle.wait()["result"]
        self.assertTrue(result["stale"])
        self.assertEqual(result["revision"], self.state["revision"], "the image depicts the captured revision")

    def test_response_metadata_describes_the_captured_scene(self):
        self.block()
        self.fake("gated")
        handle = self.render(begin=True, request_id="frozen-1")
        scene = json.loads(self.core.renders.active.worker.scene_path.read_text())
        self.call("set_part_appearance", part="Body", name="Changed after capture", color=[1, 0, 0])
        self.release()
        result = handle.wait()["result"]
        self.assertTrue(result["stale"])
        part = result["parts"][0]
        self.assertEqual((part["name"], part["color"]), (scene["parts"][0]["name"], scene["parts"][0]["color"]),
                         "the response describes the image, not the live document")
        self.assertNotEqual(part["name"], "Changed after capture")
        # Deleting the drawn feature while the job runs: the job completes from frozen metadata.
        self.fake("gated")
        handle = self.render(begin=True, request_id="frozen-2", views=["front"])
        body = self.core.renders.active.context["scene"]["targets"][0]["body"]
        self.assertTrue(self.request("delete_features", features=["Block"])["ok"])
        self.release()
        response = handle.wait()
        self.assertTrue(response["ok"], response)
        self.assertEqual((response["result"]["parts"][0]["body"], response["result"]["stale"]), (body, True))
        self.assertEqual(self.core.ledger.status("frozen-2")["status"], "completed")

    def test_highlights_resolve_once_per_capture_and_share_identical_exports(self):
        self.block()
        self.fake("ok")
        counters = self.core.renders.counters
        same = [{"selector": top_face(), "label": "A"}, {"selector": top_face(point=(5, 5, 10)), "label": "B"}]
        self.rendered(highlights=same)
        self.assertEqual((counters["highlight_resolutions"], counters["highlight_exports"]), (2, 1),
                         "two highlights matching the same face share one exported compound")
        for extra in ({"views": ["top"]}, {"size": [400, 300]}, {"section": {"plane": "XZ", "offset": -5}},
                      {"highlights": [dict(same[0], label="Z", note="relabelled"), same[1]]}):
            self.rendered(**{"highlights": same, **extra})
        self.assertEqual((counters["highlight_resolutions"], counters["highlight_exports"]), (2, 1),
                         "settings-only changes reuse resolved highlights and their files")
        self.assertEqual(counters["highlight_cache_hits"], 8)
        self.call("edit_extrusion", feature="Block", length=12)
        self.rendered(highlights=same)
        self.assertEqual(counters["highlight_resolutions"], 4, "a model edit resolves again")

    def test_document_close_cancels_jobs(self):
        self.block()
        self.fake("gated")
        handle = self.render(begin=True, request_id="close-a")
        worker = self.core.renders.active.worker
        App.closeDocument(self.doc.Name)
        response = handle.poll()
        self.assertEqual(response["error"]["code"], "document_closed")
        self.assertIsNone(self.core.renders.active)
        self.assertEqual(self.core.ledger.status("close-a")["status"], "failed")
        self.assertTrue(worker.cleanup_complete.wait(20))
        # Captures of a cancelled job are removed once its child exited (the child may hold them open).
        deadline = time.monotonic() + 10
        while list(self.core.renders.owner.glob("cap-*")) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(list(self.core.renders.owner.glob("cap-*")))
        self.assertEqual(self.core.renders.captures, {}, "nothing left for close() to retry")

    def test_cache_eviction_unlinks_files(self):
        self.block()
        self.fake("ok")
        self.core.renders.cache.max_entries = 1
        first = self.rendered()
        second = self.rendered(views=["front"])
        self.assertFalse(Path(first["images"][0]["path"]).exists())
        self.assertTrue(Path(second["images"][0]["path"]).exists())
        self.assertFalse(self.rendered()["cached"], "an evicted image renders again")

    def test_prescreen_rejects_before_export(self):
        self.block()
        self.core.renders.limits["faces"] = 3
        self.count_workers()
        with patch.object(native_selectors, "world_shape", wraps=native_selectors.world_shape) as spy:
            error = self.refused("render_too_large")
        self.assertEqual((error["reason"], error["faces"], error["limit"]), ("faces", 6, 3))
        self.assertEqual((spy.call_count, self.workers), (0, 0))
        self.core.renders.limits.update(faces=5000, brep_bytes=100)
        error = self.refused("render_too_large")
        self.assertEqual((error["reason"], error["limit"]), ("brep_bytes", 100))
        self.assertEqual(self.workers, 0)
        self.assertFalse(list(self.core.renders.owner.glob("cap-*")))

    def test_rejects_during_sketch_edit_pending_transaction_and_busy(self):
        self.block()
        self.core.busy = True
        try:
            self.refused("busy")
        finally:
            self.core.busy = False
        self.doc.openTransaction("probe")
        try:
            self.doc.getObject("Base").Label = "Pending"  # a native transaction is pending once it records a change
            self.assertTrue(self.doc.HasPendingTransaction)
            self.refused("sketch_edit_active")
        finally:
            self.doc.abortTransaction()
        self.call("inspect")
        self.call("begin_sketch_edit", feature="Base")
        self.refused("sketch_edit_active")
        self.call("finish_sketch_edit", cancel=True)

    def test_expected_revision_mismatch_rejects(self):
        self.block()
        self.fake("ok")
        error = self.refused("stale_revision", expected_revision="not-current")
        self.assertEqual(error["actual"], self.state["revision"])
        self.assertTrue(self.render(expected_revision=self.state["revision"])["ok"])

    def test_tracked_render_records_ledger_and_request_status(self):
        self.block()
        self.fake("gated")
        handle = self.render(begin=True, request_id="tracked-1")
        self.assertEqual(self.core.dispatch({"op": "request_status", "request_id": "tracked-1"})["result"]["status"], "started")
        self.release()
        response = handle.wait()
        status = self.core.dispatch({"op": "request_status", "request_id": "tracked-1"})["result"]
        self.assertEqual((status["status"], status["response"]), ("completed", response))
        self.assertEqual(self.render(request_id="tracked-1"), response, "an identical retry replays the stored response")


class RenderOwnershipTests(RenderFixture, unittest.TestCase):
    def test_service_is_lazy(self):
        self.block()
        self.call("inspect")
        self.core.dispatch({"op": "capabilities"})
        self.assertIsNone(self.core._renders)
        self.assertFalse((self.folder / "renders").exists())
        self.fake("ok")
        self.rendered()
        owner = self.core.renders.owner
        self.assertTrue((owner / "owner.json").is_file())
        self.core.close()
        self.assertFalse(owner.exists(), "closing the controller removes its images and owner folder")

    def test_two_controllers_share_session_folder_without_cross_deletion(self):
        self.block()
        self.fake("ok")
        first = self.rendered()
        other = Controller()
        try:
            state = other.dispatch({"op": "new", "name": "Other"})["result"]
            other.dispatch({"op": "sketch_rectangle", "document_id": state["document_id"],
                            "expected_revision": state["revision"], "id": "Plate", "width": 5, "height": 5})
            other.renders.renderer = str(self.fixture) + ":ok"
            response = other.dispatch({"op": "render_view", "document_id": state["document_id"], **SMALL})
            self.assertTrue(response["ok"], response)
            self.assertNotEqual(other.renders.owner, self.core.renders.owner)
            self.assertEqual(other.renders.swept, [])
            self.assertTrue(Path(first["images"][0]["path"]).exists())
        finally:
            for name in [d.Name for d in other.documents.values() if other._is_open(d)]:
                App.closeDocument(name)
            other.close()
        self.assertTrue(Path(first["images"][0]["path"]).exists())

    def test_dead_owner_folder_swept_live_owner_kept(self):
        parent = self.folder / "renders"
        parent.mkdir()
        finished = subprocess.Popen([str(EXECUTABLE), "-c", "pass"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        finished.wait(30)
        state, created = render_jobs._process_identity(os.getpid())
        self.assertEqual(state, "alive")

        def owner(pid, creation, age=None, record=True):
            folder = parent / str(uuid.uuid4())
            folder.mkdir()
            if record:
                (folder / "owner.json").write_text(json.dumps({"pid": pid, "creation_time_100ns": creation}))
            if age is not None:
                os.utime(folder, (time.time() - age, time.time() - age))
            return folder
        dead = owner(finished.pid, None)
        alive = owner(os.getpid(), created)
        reused = owner(os.getpid(), (created or 0) + 1)
        old = owner(None, None, age=25 * 3600, record=False)
        young = owner(None, None, record=False)
        system = owner(4, 1) if os.name == "nt" else None  # the System process: access denied, kept
        other = parent / "not-a-uuid"
        other.mkdir()
        removed = render_jobs.sweep_owner_folders(parent, keep="none")
        self.assertEqual(sorted(removed), sorted(folder.name for folder in (dead, reused, old)))
        for folder in (alive, young, other) + ((system,) if system else ()):
            self.assertTrue(folder.exists(), folder)


if __name__ == "__main__":
    unittest.main()
