"""Private one-shot render child: verified BREP captures in, verified PNGs out.

The parent (``render_jobs.RenderService`` on the owner thread) captures detached
world BREPs, writes ``scene.json`` and highlight compounds into this worker's
private folder, then submits one envelope. The child runs below normal priority
with single-threaded BLAS inside a Windows Job Object that caps its committed
memory and kills it when the last job handle closes, so neither a runaway
render nor a crashed or vanished owner can leave a child behind.

Parent protocol (one job per worker)::

    worker = NativeRenderWorker(executable, session_dir)
    # write worker.folder / SCENE_NAME and any highlight BREPs into worker.folder
    worker.submit(1, {"scene_sha256": ..., "settings_digest": ...,
                      "captures": [{"name", "path", "sha256", "bytes"}, ...],
                      "outputs": [{"view", "name", "width", "height"}, ...]})
    response = worker.poll()            # None while running; RenderWorkerError on failure
    images = worker.validated_images(response)  # verified PNGs inside worker.folder
    worker.close()                      # inherited reaper: delete folder after confirmed exit

``outputs`` names the PNGs the child must write (``view-<k>.png`` or one
``sheet.png``); the child's response echoes the whole envelope and reports the
sealed files as ``images`` (each output plus ``bytes`` and ``sha256``).

Every capture path must lie inside the ``parent_directory`` given to the
constructor (the session folder). The child verifies the scene and each capture
against its sha256 before any native import, never imports ``kurtshape.core``
and never opens a document.

Renderer seam (child side): the renderer named by ``renderer`` (default
``DEFAULT_RENDERER``) is called once as ``renderer(job)`` where ``job`` is a
``RenderInput`` with ``folder``, ``scene`` (parsed scene.json), ``shapes``
(capture name -> imported ``Part.Shape``), ``images`` (the envelope's outputs),
``settings_digest`` and ``phases`` (a dict the renderer may add millisecond
timings to; only finite numbers under string keys are published). It must
write exactly the expected PNGs into ``job.folder`` and may return
JSON-serializable metadata, published unchanged as ``render`` in the response.
``MemoryError`` maps to ``render_too_large`` with ``reason:"memory"``; an
exception carrying ``code == "render_too_large"`` (optional ``reason`` and
scalar ``details``) maps to ``render_too_large``; anything else to
``render_failed``.

The default renderer is :func:`render_scene`, an adapter onto
``kurtshape.model_render.render_job``. It builds the ``model_render.Scene``
from the verified ``shapes`` (never re-reading files) and takes the renderer
settings from scene.json, which uses ``Scene.from_capture``'s document format::

    {"title", "revision", "banners", "model_bounds",
     "parts": [{"brep": CAPTURE, "name", "id", "color", "solid"}],
     "sketches": [CAPTURE, ...],
     "highlights": [{"label", "note", "rendered": CAPTURE | null, "ghost": CAPTURE | null, "two_sided"}],
     "settings": {model_render.normalize_settings input},
     "metadata": {"document", "revision", "render_id", "note"},   # PNG tEXt (optional)
     "limits": {model_render.DEFAULT_LIMITS overrides}}           # tests (optional)

where CAPTURE is a capture ``name`` from the envelope, optionally with a
``.brep`` suffix. The images the settings produce (``view-<k>.png`` or
``sheet.png`` and their sizes) must equal the envelope's ``outputs``.

Determinism (``RenderWorkerError.deterministic``, which the owner uses for its
negative cache) means "identical inputs fail the same way". Load, render and
seal failures and ``render_too_large`` are deterministic, except failures that
say nothing about the inputs: the child marks real OS and file-system errors
(scanner locks, access denial, a full disk; not FreeCAD's errno-less
``OSError("Access violation")`` for a native fault), missing modules and a
renderer that cannot be called as ``renderer(job)`` with ``transient: true``,
and the parent
treats a memory failure as deterministic only with evidence of the Job cap
(the job's memory-limit notification or a peak commit within
``MEMORY_LIMIT_MARGIN_BYTES`` of the cap); a ``MemoryError`` without that
evidence is system-wide commit exhaustion. ``transient`` is consumed by the
parent and never appears in ``details``.
"""
from __future__ import annotations

import gc
import hashlib
import importlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import weakref

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kurtshape.preview_worker import NativePreviewWorker

JOB_TIMEOUT_SECONDS = 25
MEMORY_LIMIT_BYTES = 1536 * 2**20
# A child that dies with a committed peak this close to its cap is reported as
# a memory failure even when the native allocator could not raise MemoryError.
MEMORY_LIMIT_MARGIN_BYTES = 64 * 2**20
BELOW_NORMAL_PRIORITY_CLASS = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0x00004000)
MAX_JSON_BYTES = 8 * 2**20
MAX_WAKEUP_BYTES = 4096
MAX_IMAGES = 7
MIN_SIDE, MAX_SIDE = 128, 2048
MAX_PIXELS = 3_145_728
MAX_CAPTURES = 1024
MAX_INPUT_BYTES = 128 * 2**20
SCENE_NAME = "scene.json"
DEFAULT_RENDERER = "kurtshape.render_worker:render_scene"
ERROR_CODES = ("render_timeout", "render_failed", "render_too_large")
CHILD_ERROR_CODES = ("render_failed", "render_too_large")
TOO_LARGE_REASONS = ("faces", "edges", "brep_bytes", "triangles", "memory")
PHASES = ("request", "verify", "import", "load", "render", "seal", "write")
# Failures in these phases repeat for identical inputs; verification, import
# and transport failures do not establish anything about the inputs. A child
# error marked ``transient`` (an OS or file-system error, a missing module, a
# renderer that cannot be called) is never deterministic, whatever its phase.
DETERMINISTIC_PHASES = ("load", "render", "seal")
# Keys a child error may not use as details: they name the error itself, the
# RenderWorkerError keyword arguments, or the parent-consumed transient flag.
RESERVED_ERROR_KEYS = frozenset({"code", "message", "deterministic", "self", "transient"})
MAX_ERROR_DETAILS = 16
# A scanner may hold a freshly written PNG or result briefly; the child retries
# PermissionError for this long before reporting a transient failure.
FILE_RETRY_SECONDS = 2.0
# Reported once verification ends; none of these may be loaded by then.
NATIVE_MODULES = ("FreeCAD", "Part", "numpy", "PIL", "kurtshape.model_render")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
ENVELOPE_KEYS = frozenset({"scene_sha256", "settings_digest", "captures", "outputs"})
CAPTURE_KEYS = frozenset({"name", "path", "sha256", "bytes"})
IMAGE_KEYS = frozenset({"view", "name", "width", "height"})
IMAGE_REPORT_KEYS = IMAGE_KEYS | {"bytes", "sha256"}
_HEX64 = re.compile(r"[0-9a-f]{64}")
_CAPTURE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
_IMAGE_NAME = re.compile(r"view-[0-6]\.png|sheet\.png")


class RenderWorkerError(Exception):
    """A render worker failure carrying a contract error code and details."""

    def __init__(self, code, message, *, deterministic=False, **details):
        super().__init__(message)
        self.code, self.details, self.deterministic = code, details, deterministic

    def payload(self):
        return {"code": self.code, "message": str(self), **self.details}


class RenderTimeout(RenderWorkerError, TimeoutError):
    def __init__(self, message, **details):
        super().__init__("render_timeout", message, deterministic=False, **details)


def as_render_error(exc, timeout_seconds=None):
    """Map any exception from the worker transport to a ``RenderWorkerError``.

    Pass the worker's ``timeout`` so a bare ``TimeoutError`` reports
    ``timeout_seconds`` like the worker's own timeouts do.
    """
    if isinstance(exc, RenderWorkerError):
        return exc
    if isinstance(exc, TimeoutError):
        details = {} if timeout_seconds is None else {"timeout_seconds": timeout_seconds}
        return RenderTimeout("Render exceeded its time limit", **details)
    return RenderWorkerError("render_failed", "Render worker failed: " + str(exc)[:300])


# --- Windows Job Object (ctypes; a no-op elsewhere) -------------------------

JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x00000400
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_ASSOCIATE_COMPLETION_PORT_INFORMATION = 7
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
JOB_OBJECT_MSG_PROCESS_MEMORY_LIMIT = 9
JOB_OBJECT_MSG_JOB_MEMORY_LIMIT = 10
JOB_LIMIT_FLAGS = (JOB_OBJECT_LIMIT_PROCESS_MEMORY | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                   | JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION)
# UCRT _set_abort_behavior flags: _WRITE_ABORT_MSG | _CALL_REPORTFAULT.
_ABORT_REPORTING = 0x1 | 0x2
JOB_OBJECTS = os.name == "nt"
_WIN = None


def _win32():
    """Lazily bind the kernel32 entry points used by jobs and memory counters."""
    global _WIN
    if _WIN is None:
        import ctypes
        from ctypes import wintypes

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class BasicLimits(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        class MemoryCounters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        class CompletionPort(ctypes.Structure):
            _fields_ = [("CompletionKey", ctypes.c_void_p), ("CompletionPort", wintypes.HANDLE)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateIoCompletionPort.restype = wintypes.HANDLE
        kernel32.CreateIoCompletionPort.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.c_size_t, wintypes.DWORD]
        kernel32.GetQueuedCompletionStatus.restype = wintypes.BOOL
        kernel32.GetQueuedCompletionStatus.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD),
                                                       ctypes.POINTER(ctypes.c_size_t),
                                                       ctypes.POINTER(ctypes.c_void_p), wintypes.DWORD]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel32.QueryInformationJobObject.restype = wintypes.BOOL
        kernel32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                       wintypes.DWORD, ctypes.c_void_p]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
        kernel32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        _WIN = {"ctypes": ctypes, "wintypes": wintypes, "kernel32": kernel32, "ExtendedLimits": ExtendedLimits,
                "MemoryCounters": MemoryCounters, "CompletionPort": CompletionPort}
    return _WIN


def _close_job_handles(*handles):
    for handle in handles:
        if handle:
            try:
                _win32()["kernel32"].CloseHandle(handle)
            except Exception:
                pass


class JobObject:
    """Kill-on-close Windows job with a per-process commit limit.

    ``release()`` is the lease interface the inherited worker reaper calls once
    after it has confirmed child exit. Closing the last handle kills every
    process still in the job, so an owner that exits or crashes without
    ``close()`` still takes its render child with it.

    A private completion port receives the job's notifications. A denied commit
    posts ``JOB_OBJECT_MSG_PROCESS_MEMORY_LIMIT`` whichever way the child then
    fails (MemoryError, an access violation inside OCCT, or a native abort), so
    the parent can name memory as the cause. Delivery is best-effort; the peak
    commit heuristic remains the fallback.
    """

    def __init__(self, handle, memory_limit, port=None):
        self.handle = handle
        self.port = port
        self.memory_limit = int(memory_limit)
        self.assigned_pid = None
        self.peak_process_memory = None
        self.memory_limit_pids = set()
        self._lock = threading.Lock()
        self._finalizer = weakref.finalize(self, _close_job_handles, handle, port)

    @classmethod
    def create(cls, memory_limit=MEMORY_LIMIT_BYTES):
        """Return a configured job, or None where Job Objects do not exist."""
        if not JOB_OBJECTS:
            return None
        if type(memory_limit) is not int or memory_limit < 16 * 2**20:
            raise ValueError("Render memory limit must be an integer of at least 16 MiB")
        win = _win32()
        ctypes, kernel32 = win["ctypes"], win["kernel32"]
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = win["ExtendedLimits"]()
        info.BasicLimitInformation.LimitFlags = JOB_LIMIT_FLAGS
        info.ProcessMemoryLimit = memory_limit
        if not kernel32.SetInformationJobObject(handle, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                                                ctypes.byref(info), ctypes.sizeof(info)):
            error = ctypes.WinError(ctypes.get_last_error())
            kernel32.CloseHandle(handle)
            raise error
        # Notifications are diagnostic: a job without a port still confines the child.
        port = kernel32.CreateIoCompletionPort(win["wintypes"].HANDLE(-1), None, 0, 1)
        if port:
            association = win["CompletionPort"](None, port)
            if not kernel32.SetInformationJobObject(handle, JOB_OBJECT_ASSOCIATE_COMPLETION_PORT_INFORMATION,
                                                    ctypes.byref(association), ctypes.sizeof(association)):
                kernel32.CloseHandle(port)
                port = None
        return cls(handle, memory_limit, port or None)

    @property
    def closed(self):
        return not self._finalizer.alive

    def assign(self, process):
        win = _win32()
        ctypes = win["ctypes"]
        with self._lock:
            if self.closed:
                raise RuntimeError("Render job object is closed")
            if not win["kernel32"].AssignProcessToJobObject(self.handle, int(process._handle)):
                raise ctypes.WinError(ctypes.get_last_error())
            self.assigned_pid = process.pid

    def limits(self):
        """Read the extended limit and accounting record (diagnostics and tests)."""
        win = _win32()
        ctypes = win["ctypes"]
        info = win["ExtendedLimits"]()
        with self._lock:
            if self.closed:
                raise RuntimeError("Render job object is closed")
            if not win["kernel32"].QueryInformationJobObject(self.handle, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                                                             ctypes.byref(info), ctypes.sizeof(info), None):
                raise ctypes.WinError(ctypes.get_last_error())
        return {"limit_flags": int(info.BasicLimitInformation.LimitFlags),
                "process_memory_limit": int(info.ProcessMemoryLimit),
                "peak_process_memory_used": int(info.PeakProcessMemoryUsed),
                "peak_job_memory_used": int(info.PeakJobMemoryUsed)}

    def record_peak(self):
        """Remember the job's peak commit while the handle is still open."""
        try:
            self.peak_process_memory = self.limits()["peak_process_memory_used"]
        except Exception:
            pass
        return self.peak_process_memory

    def drain(self):
        """Read queued job notifications without waiting; returns (message, pid) pairs."""
        messages = []
        win = _win32() if self.port else None
        with self._lock:
            if win is None or self.closed:
                return messages
            ctypes, wintypes = win["ctypes"], win["wintypes"]
            for _ in range(256):
                number, key, overlapped = wintypes.DWORD(), ctypes.c_size_t(), ctypes.c_void_p()
                if not win["kernel32"].GetQueuedCompletionStatus(self.port, ctypes.byref(number), ctypes.byref(key),
                                                                 ctypes.byref(overlapped), 0):
                    break
                messages.append((int(number.value), overlapped.value))
        for message, pid in messages:
            if message in (JOB_OBJECT_MSG_PROCESS_MEMORY_LIMIT, JOB_OBJECT_MSG_JOB_MEMORY_LIMIT):
                self.memory_limit_pids.add(pid)
        return messages

    def memory_limit_hit(self, pid=None):
        """True once the job reported a denied commit (for ``pid`` when given)."""
        self.drain()
        return bool(self.memory_limit_pids) if pid is None else (
            pid in self.memory_limit_pids or None in self.memory_limit_pids)

    def close(self):
        with self._lock:
            self._finalizer()

    release = close


def process_memory():
    """Return (peak working set, peak commit) bytes of this process, or Nones."""
    if os.name != "nt":
        return None, None
    try:
        win = _win32()
        ctypes = win["ctypes"]
        counters = win["MemoryCounters"]()
        counters.cb = ctypes.sizeof(counters)
        if not win["kernel32"].K32GetProcessMemoryInfo(win["kernel32"].GetCurrentProcess(),
                                                       ctypes.byref(counters), counters.cb):
            return None, None
        return int(counters.PeakWorkingSetSize), int(counters.PeakPagefileUsage)
    except Exception:
        return None, None


def native_allocation_policy():
    """Make native allocation failures in the child reportable and prompt (child only).

    FreeCAD's initialisation calls ``_set_new_mode(1)``, routing every failed
    ``malloc`` to its throwing C++ new-handler. A failed allocation made from C
    (numpy buffers, Python objects) then terminates the process through
    ``abort()`` and Windows Error Reporting about 8 s later, without a result.
    Mode 0 lets those allocations raise ``MemoryError``; C++ ``operator new``
    still uses FreeCAD's handler. ``abort()`` exits at once (code 3) instead of
    waiting for fault reporting. Returns what was applied, or None off Windows.
    """
    if os.name != "nt":
        return None
    import ctypes
    ucrt = ctypes.CDLL("ucrtbase")
    ucrt._set_new_mode.argtypes = [ctypes.c_int]
    ucrt._set_new_mode.restype = ctypes.c_int
    ucrt._query_new_mode.restype = ctypes.c_int
    ucrt._set_abort_behavior.argtypes = [ctypes.c_uint, ctypes.c_uint]
    ucrt._set_abort_behavior.restype = ctypes.c_uint
    previous = ucrt._set_new_mode(0)
    ucrt._set_abort_behavior(0, _ABORT_REPORTING)
    return {"new_mode": ucrt._query_new_mode(), "previous_new_mode": previous, "abort_fault_reporting": False}


# --- Shared bounded file and envelope checks --------------------------------

def _json_bytes(value):
    payload = json.dumps(value, allow_nan=False).encode("utf-8")
    if len(payload) > MAX_JSON_BYTES:
        raise ValueError("Render job JSON exceeds the 8 MiB limit")
    return payload


def _json_copy(value):
    return json.loads(_json_bytes(value))


def _regular_identity(path):
    info = Path(path).lstat()
    if (not stat.S_ISREG(info.st_mode) or Path(path).is_symlink()
            or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
        raise ValueError("Render job file must be a regular non-link file: " + Path(path).name)
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _reject_nonfinite(value):
    raise ValueError("Nonfinite render job JSON: " + value)


def _read_json(path):
    if _regular_identity(path)[2] > MAX_JSON_BYTES:
        raise ValueError("Render job JSON exceeds the 8 MiB limit")
    with Path(path).open("rb") as stream:
        payload = stream.read(MAX_JSON_BYTES + 1)
    if len(payload) > MAX_JSON_BYTES:
        raise ValueError("Render job JSON exceeds the 8 MiB limit")
    return json.loads(payload, parse_constant=_reject_nonfinite)


def _stable_bytes(path, limit):
    """Read one stable regular file completely, checking handle and pathname."""
    path = Path(path)
    identity = _regular_identity(path)
    if identity[2] > limit:
        raise ValueError("Render job file exceeds its size limit: " + path.name)
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != identity:
            raise ValueError("Render job file changed while opening: " + path.name)
        payload = stream.read(limit + 1)
        finished = os.fstat(stream.fileno())
    if (len(payload) != identity[2]
            or (finished.st_dev, finished.st_ino, finished.st_size, finished.st_mtime_ns) != identity
            or _regular_identity(path) != identity):
        raise ValueError("Render job file changed while reading: " + path.name)
    return payload


def png_info(path):
    """Size, sha256 and IHDR dimensions of one stable regular PNG file."""
    payload = _stable_bytes(path, 64 * 2**20)
    if (len(payload) < 33 or payload[:8] != PNG_SIGNATURE or payload[8:12] != b"\x00\x00\x00\x0d"
            or payload[12:16] != b"IHDR"):
        raise ValueError("Render image is not a PNG: " + Path(path).name)
    return {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
            "width": int.from_bytes(payload[16:20], "big"), "height": int.from_bytes(payload[20:24], "big")}


def _hex64(value):
    return isinstance(value, str) and _HEX64.fullmatch(value) is not None


def validate_envelope(envelope, root=None):
    """Return a detached copy of a well-formed job envelope or raise ValueError.

    ``root`` (parent side only) additionally requires every capture path to
    resolve inside the private session folder.
    """
    envelope = _json_copy(envelope)
    if not isinstance(envelope, dict) or set(envelope) != ENVELOPE_KEYS:
        raise ValueError("Invalid render job envelope")
    if not _hex64(envelope["scene_sha256"]) or not _hex64(envelope["settings_digest"]):
        raise ValueError("Invalid render scene or settings digest")
    captures = envelope["captures"]
    if not isinstance(captures, list) or len(captures) > MAX_CAPTURES:
        raise ValueError("Invalid render capture list")
    names, total = set(), 0
    for capture in captures:
        if (not isinstance(capture, dict) or set(capture) != CAPTURE_KEYS
                or not isinstance(capture["name"], str) or _CAPTURE_NAME.fullmatch(capture["name"]) is None
                or capture["name"] in names or not _hex64(capture["sha256"])
                or type(capture["bytes"]) is not int or not 0 < capture["bytes"] <= MAX_INPUT_BYTES
                or not isinstance(capture["path"], str) or len(capture["path"]) > 1024
                or not Path(capture["path"]).is_absolute() or Path(capture["path"]).suffix.lower() != ".brep"):
            raise ValueError("Invalid render capture description")
        names.add(capture["name"])
        total += capture["bytes"]
        if root is not None:
            resolved = Path(capture["path"]).resolve()
            if resolved == root or not resolved.is_relative_to(root):
                raise ValueError("Render capture is outside the private session folder")
    if total > MAX_INPUT_BYTES:
        raise ValueError("Render captures exceed the 128 MiB transport limit")
    images = envelope["outputs"]
    if not isinstance(images, list) or not 1 <= len(images) <= MAX_IMAGES:
        raise ValueError("Invalid render image list")
    image_names = set()
    for image in images:
        if (not isinstance(image, dict) or set(image) != IMAGE_KEYS
                or not isinstance(image["name"], str) or _IMAGE_NAME.fullmatch(image["name"]) is None
                or image["name"] in image_names
                or not isinstance(image["view"], str) or not 1 <= len(image["view"]) <= 24
                or not image["view"].isprintable()
                or any(type(image[side]) is not int or not MIN_SIDE <= image[side] <= MAX_SIDE
                       for side in ("width", "height"))
                or image["width"] * image["height"] > MAX_PIXELS):
            raise ValueError("Invalid render image description")
        image_names.add(image["name"])
    if "sheet.png" in image_names and len(images) != 1:
        raise ValueError("A render sheet is the job's only image")
    return envelope


def _child_error_from(response):
    """Validate a child-reported error; None for a successful response.

    Reserved keys other than ``code``, ``message`` and a literal
    ``transient: true`` make the error malformed, so they can never collide
    with ``RenderWorkerError``'s own arguments.
    """
    ok, error = response.get("ok"), response.get("error")
    if ok is True and error is None:
        return None
    if (ok is not False or not isinstance(error, dict) or error.get("code") not in CHILD_ERROR_CODES
            or not isinstance(error.get("message"), str) or len(error["message"]) > 600
            or error.get("phase") not in PHASES
            or ("reason" in error and (error["code"] != "render_too_large" or error["reason"] not in TOO_LARGE_REASONS))
            or ("transient" in error and error["transient"] is not True)
            or any(key in error for key in RESERVED_ERROR_KEYS - {"code", "message", "transient"})
            or len(error) > MAX_ERROR_DETAILS + 5
            or any(not isinstance(key, str) or (value is not None and type(value) not in (str, int, float, bool))
                   or (type(value) is float and not math.isfinite(value))
                   for key, value in error.items())):
        return RenderWorkerError("render_failed", "Render worker reported a malformed error")
    details = {key: value for key, value in error.items() if key not in RESERVED_ERROR_KEYS}
    deterministic = "transient" not in error and (
        error["code"] == "render_too_large" or error["phase"] in DETERMINISTIC_PHASES)
    return RenderWorkerError(error["code"], error["message"], deterministic=deterministic, **details)


# --- Parent transport -------------------------------------------------------

class NativeRenderWorker(NativePreviewWorker):
    """One render job in a private, memory-capped native child.

    Reuses the preview transport's nonblocking, confirmed-exit reaper. The Job
    Object is held as the worker's lease, so the reaper closes it exactly once
    and only after child exit has been confirmed.
    """

    def __init__(self, executable, parent_directory, timeout=JOB_TIMEOUT_SECONDS,
                 memory_limit=MEMORY_LIMIT_BYTES, renderer=None):
        renderer = renderer or DEFAULT_RENDERER
        if not isinstance(renderer, str) or ":" not in renderer.strip(":") or "\n" in renderer:
            raise ValueError("Render worker renderer must be 'module:function' or 'path.py:function'")
        self.root = Path(parent_directory).resolve()
        parent = self.root / "render-jobs"
        parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="render-", dir=parent, ignore_cleanup_errors=True)
        self.folder = Path(self.temporary.name)
        self.snapshot = None
        self.token = uuid.uuid4().hex
        self.executable = str(executable)
        self.timeout = timeout
        self.process = self.log = None
        self.active = None
        self.started = 0
        self.closed = False
        self._snapshot_lease = None
        self._snapshot_identity = None
        self.cleanup_complete = threading.Event()
        self._close_lock = threading.Lock()
        self.memory_limit = memory_limit
        self.renderer = renderer
        self.job = None
        self.exit_code = None
        self.memory_limit_hit = False
        self._submitted = False
        self._envelope = None
        self._completed_response = None

    @property
    def scene_path(self):
        return self.folder / SCENE_NAME

    def borrow_snapshot(self, lease):
        raise RuntimeError("Render workers take verified BREP captures, not FCStd snapshots")

    def _start(self):
        if self.closed or self.process is not None:
            raise RuntimeError("Render worker is closed or already started")
        environment = os.environ.copy()
        for name, child in (("KURTSHAPE_SESSION_DIR", "session"), ("FREECAD_USER_HOME", "user-data"),
                            ("APPDATA", "appdata"), ("LOCALAPPDATA", "localappdata"),
                            ("TEMP", "temporary"), ("TMP", "temporary")):
            path = self.folder / child
            path.mkdir(exist_ok=True)
            environment[name] = str(path)
        # Multi-threaded OpenBLAS commits about 4 GB at numpy import on this
        # machine class; one thread keeps the child far below its cap.
        environment.update(PYTHONDONTWRITEBYTECODE="1", QT_QPA_PLATFORM="offscreen", KURTSHAPE_WORKER="1",
                           OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
        job = JobObject.create(self.memory_limit)
        # Held as the lease: the inherited reaper releases it after confirmed
        # exit, including when launch or assignment below fails.
        self.job = self._snapshot_lease = job
        self.log = (self.folder / "native-worker.log").open("wb")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | (BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 0)
        self.process = subprocess.Popen(
            [self.executable, "-B", str(Path(__file__).resolve()), str(self.folder), self.token, self.renderer],
            stdin=subprocess.PIPE, stdout=self.log, stderr=subprocess.STDOUT,
            env=environment, cwd=self.folder, creationflags=flags)
        if job is not None:
            # The child only reads its wake-up line after this; all render work
            # therefore runs inside the job.
            job.assign(self.process)

    def submit(self, sequence, envelope):
        if self._submitted or self.closed or type(sequence) is not int or sequence < 0:
            raise RuntimeError("Render worker accepts one numbered job")
        envelope = validate_envelope(envelope, self.root)
        try:
            if _regular_identity(self.scene_path)[2] > MAX_JSON_BYTES:
                raise ValueError("Render scene exceeds the 8 MiB limit")
            for capture in envelope["captures"]:
                if _regular_identity(capture["path"])[2] != capture["bytes"]:
                    raise ValueError("Render capture size changed before launch: " + capture["name"])
            _json_bytes({"task": self.token, "sequence": sequence, "proposal": envelope})
        except (OSError, ValueError) as exc:
            raise RenderWorkerError("render_failed", "Render inputs are unavailable: " + str(exc)[:300]) from exc
        self._envelope = envelope
        self._submitted = True
        try:
            NativePreviewWorker.submit(self, sequence, envelope)
        except BaseException as exc:
            self.close()
            if isinstance(exc, Exception):
                raise RenderWorkerError("render_failed", "Render worker could not start: " + str(exc)[:300]) from exc
            raise

    def _memory_evidence(self):
        """(evidence, peak): did the job deny a commit or peak within the margin of its cap?

        The two signals are independent: the notification is best-effort, and a
        single large allocation that the cap refuses leaves the peak low.
        """
        peak = self.job.peak_process_memory if self.job is not None else None
        near_cap = peak is not None and peak >= self.memory_limit - MEMORY_LIMIT_MARGIN_BYTES
        return bool(self.memory_limit_hit or near_cap), peak

    def _memory_failure(self, cause=None, phase=None):
        """A memory failure when the job reported a denied commit or peaked at its cap.

        ``phase`` is the child's reported phase; a child that died without a
        result has none, and the detail is then omitted.
        """
        evidence, peak = self._memory_evidence()
        if not evidence:
            return None
        details = {"reason": "memory"}
        if phase is not None:
            details["phase"] = phase
        if peak is not None:
            details["peak_commit_mb"] = round(peak / 2**20, 1)
        if cause:
            details["cause"] = cause[:300]
        return RenderWorkerError("render_too_large", "The render worker reached its memory limit",
                                 deterministic=True, **details)

    def poll(self):
        if self.closed or self.active is None:
            return None
        # Read only after confirmed exit; this also closes the publish/exit race.
        exit_code = self.process.poll()
        expired = time.monotonic() - self.started > self.timeout
        if exit_code is None:
            if expired:
                raise RenderTimeout("Render exceeded its " + format(self.timeout, "g") + " s time limit",
                                    timeout_seconds=self.timeout)
            return None
        if self.exit_code is None:
            self.exit_code = exit_code
            if self.job is not None:
                self.job.record_peak()
                self.memory_limit_hit = self.job.memory_limit_hit(self.process.pid)
        if exit_code != 0:
            message = "Render worker stopped before completing (exit code " + str(exit_code) + ")"
            raise self._memory_failure(message) or RenderWorkerError("render_failed", message, exit_code=exit_code)
        try:
            response = _read_json(self.folder / ("result-" + str(self.active) + ".json"))
        except PermissionError:
            # A scanner may briefly hold the published file; retry until the deadline.
            if expired:
                raise RenderTimeout("Render result remained unavailable after the worker exited",
                                    timeout_seconds=self.timeout)
            return None
        except (OSError, ValueError) as exc:
            raise RenderWorkerError("render_failed", "Render worker exited without a valid result: "
                                    + str(exc)[:300]) from exc
        if (not isinstance(response, dict) or response.get("task") != self.token
                or type(response.get("sequence")) is not int or response["sequence"] != self.active
                or any(response.get(name) != value for name, value in self._envelope.items())):
            raise RenderWorkerError("render_failed", "Render response belongs to another job")
        self._completed_response = _json_copy(response)
        self.active = None
        return response

    def diagnostics(self):
        """Cheap owner-thread facts for ``diagnostics.renders`` (no process waits)."""
        running = self.process is not None and not self.closed and self.process.poll() is None
        peak = self.job.peak_process_memory if self.job is not None else None
        return {"pid": None if self.process is None else self.process.pid, "running": running,
                "elapsed_ms": round((time.monotonic() - self.started) * 1000, 1) if self.active is not None else None,
                "memory_limit_mb": round(self.memory_limit / 2**20, 1), "job_object": self.job is not None,
                "peak_commit_mb": None if peak is None else round(peak / 2**20, 1),
                "memory_limit_hit": self.memory_limit_hit}

    def child_error(self, response):
        """The child's own reported failure as a ``RenderWorkerError``, or None.

        A ``render_failed`` from a job that hit its commit limit is reported as
        ``render_too_large`` with ``reason:"memory"`` and the child's phase:
        under the cap native code fails in many shapes (an access violation
        inside OCCT, a library error), and memory is the cause the caller can
        act on. A reported memory failure is deterministic only with evidence
        of the cap; otherwise the system ran out of commit, and a retry may
        succeed.
        """
        if not isinstance(response, dict):
            return RenderWorkerError("render_failed", "Render worker reported a malformed result")
        error = _child_error_from(response)
        if error is None or "phase" not in error.details:  # success, or malformed
            return error
        if error.code == "render_failed":
            return self._memory_failure(str(error), phase=error.details["phase"]) or error
        if error.details.get("reason") == "memory":
            evidence, peak = self._memory_evidence()
            error.deterministic = error.deterministic and evidence
            if peak is not None and "peak_commit_mb" not in error.details:
                error.details["peak_commit_mb"] = round(peak / 2**20, 1)
        return error

    def validated_images(self, response):
        """Verify every expected PNG in this job's folder against the child's report.

        Pass the exact ``poll()`` result. Raises the child's reported error for
        an unsuccessful job and ``render_failed`` for any mismatch.
        """
        if (self.closed or self.process is None or self.process.poll() != 0
                or self._completed_response is None or response != self._completed_response):
            raise RenderWorkerError("render_failed", "Render images are not owned by a completed job")
        error = self.child_error(response)
        if error is not None:
            raise error
        expected, reported = self._envelope["outputs"], response.get("images")
        try:
            if not isinstance(reported, list) or len(reported) != len(expected):
                raise ValueError("Render image list does not match the job")
            info = self.folder.lstat()
            if (not stat.S_ISDIR(info.st_mode) or self.folder.is_symlink()
                    or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
                raise ValueError("Render job directory changed")
            rows = []
            for want, row in zip(expected, reported):
                if (not isinstance(row, dict) or set(row) != IMAGE_REPORT_KEYS
                        or any(row[key] != value for key, value in want.items())
                        or type(row["bytes"]) is not int or row["bytes"] <= 0 or not _hex64(row["sha256"])):
                    raise ValueError("Render image report does not match the job")
                path = self.folder / want["name"]
                actual = png_info(path)
                if (actual["width"], actual["height"]) != (want["width"], want["height"]):
                    raise ValueError("Render image dimensions differ from the request: " + want["name"])
                if (actual["bytes"], actual["sha256"]) != (row["bytes"], row["sha256"]):
                    raise ValueError("Render image bytes changed after the worker exited: " + want["name"])
                rows.append(dict(row, path=str(path)))
        except (OSError, ValueError) as exc:
            raise RenderWorkerError("render_failed", "Render image verification failed: " + str(exc)[:300]) from exc
        return rows


# --- Child ------------------------------------------------------------------

class RenderInput:
    """What the child hands to the renderer; see the module docstring."""

    __slots__ = ("folder", "scene", "shapes", "images", "settings_digest", "phases")

    def __init__(self, folder, scene, shapes, images, settings_digest, phases):
        self.folder, self.scene, self.shapes = folder, scene, shapes
        self.images, self.settings_digest, self.phases = images, settings_digest, phases


class RendererCallError(Exception):
    """The renderer could not be called as ``renderer(job)``: a wiring fault, not an input fault."""


def _load_renderer(spec):
    target, _, function = spec.rpartition(":")
    if not target or not function:
        raise ValueError("Invalid renderer reference")
    if target.lower().endswith(".py"):
        location = importlib.util.spec_from_file_location("kurtshape_render_plugin", target)
        if location is None or location.loader is None:
            raise ImportError("Renderer file cannot be loaded: " + target)
        module = importlib.util.module_from_spec(location)
        location.loader.exec_module(module)
    elif target == "kurtshape.render_worker":
        # The child runs this file as __main__; never import a second copy.
        module = sys.modules[__name__]
    else:
        module = importlib.import_module(target)
    renderer = getattr(module, function)
    if not callable(renderer):
        raise TypeError("Renderer is not callable: " + spec)
    return renderer


def _transient(exc):
    """True when a failure says nothing about the job's inputs, so it must not be cached.

    Real OS and file-system errors (a scanner's sharing violation or access
    denial, a full disk: an ``OSError`` subclass or one carrying an errno), a
    missing module and a renderer that cannot be called. FreeCAD reports
    geometry failures as RuntimeError/ValueError subclasses and a native fault
    inside OCCT as a bare ``OSError("Access violation")`` without an errno;
    those repeat for identical inputs and stay deterministic (under the Job
    cap the parent reports them as memory failures).
    """
    if isinstance(exc, (ImportError, RendererCallError)):
        return True
    return isinstance(exc, OSError) and (type(exc) is not OSError or exc.errno is not None
                                         or getattr(exc, "winerror", None) is not None)


def _scalar(value):
    return (type(value) in (str, int, bool)
            or (type(value) is float and math.isfinite(value)))


def _child_error(exc, phase):
    if isinstance(exc, MemoryError):
        return {"code": "render_too_large", "reason": "memory", "phase": phase,
                "message": "The render exceeded its memory limit"}
    if getattr(exc, "code", None) == "render_too_large":
        error = {"code": "render_too_large", "phase": phase, "message": str(exc)[:300]}
        details = getattr(exc, "details", None)
        reason = getattr(exc, "reason", None) or (details.get("reason") if isinstance(details, dict) else None)
        if reason in TOO_LARGE_REASONS:
            error["reason"] = reason
        if isinstance(details, dict):
            # Only scalar, unreserved details; an invalid reason is dropped above, never forwarded.
            for key, value in list(details.items())[:MAX_ERROR_DETAILS]:
                if (isinstance(key, str) and 0 < len(key) <= 64 and key not in error and key != "reason"
                        and key not in RESERVED_ERROR_KEYS and _scalar(value)):
                    error[key] = value[:100] if isinstance(value, str) else value
        return error
    error = {"code": "render_failed", "phase": phase, "message": (type(exc).__name__ + ": " + str(exc))[:300]}
    if _transient(exc):
        error["transient"] = True
    return error


def _retry_permission(action, seconds=FILE_RETRY_SECONDS):
    """Run ``action`` and retry PermissionError (a scanner's lock) for a bounded time."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            return action()
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.05)


def _seal_png(path, seconds=FILE_RETRY_SECONDS):
    """``png_info`` of a renderer output; a missing file is the renderer's (deterministic) fault."""
    try:
        return _retry_permission(lambda: png_info(path), seconds)
    except FileNotFoundError:
        raise ValueError("Renderer did not write " + Path(path).name) from None


def _native_modules():
    return sorted(name for name in NATIVE_MODULES if name in sys.modules)


def _clean_phases(phases, names=None):
    """Publishable phase timings: finite numbers under short string keys (renderers add their own)."""
    clean = {}
    for key, value in list(phases.items())[:64]:
        if (not isinstance(key, str) or not 0 < len(key) <= 64 or (names is not None and key not in names)
                or isinstance(value, (bool, str, bytes)) or not hasattr(value, "__float__")):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(number):
            clean[key] = number
    return clean


def _render(folder, envelope, renderer_spec, response, phases):
    """Verify, import, load, render and seal; raise with the failing phase."""
    phase = "verify"
    try:
        began = time.perf_counter()
        try:
            scene_bytes = _stable_bytes(folder / SCENE_NAME, MAX_JSON_BYTES)
            if hashlib.sha256(scene_bytes).hexdigest() != envelope["scene_sha256"]:
                raise ValueError("Render scene changed after capture")
            scene = json.loads(scene_bytes, parse_constant=_reject_nonfinite)
            payloads = {}
            for capture in envelope["captures"]:
                data = _stable_bytes(capture["path"], capture["bytes"])
                if len(data) != capture["bytes"] or hashlib.sha256(data).hexdigest() != capture["sha256"]:
                    raise ValueError("Render capture changed after capture: " + capture["name"])
                payloads[capture["name"]] = data
        finally:
            # Evidence that every input was verified before any native module loaded.
            response["native_modules_at_verify"] = _native_modules()
        phases["verify"] = (time.perf_counter() - began) * 1000
        phase = "import"
        began = time.perf_counter()
        import FreeCAD as App
        import Part
        import numpy  # noqa: F401  (imported under single-thread BLAS before rendering)
        import PIL  # noqa: F401
        response["engine"] = {"FreeCAD": App.Version(), "OCCT": Part.OCC_VERSION}
        renderer = _load_renderer(renderer_spec)
        if renderer is render_scene:
            importlib.import_module("kurtshape.model_render")  # fonts and renderer load in this phase
        # After every native import: FreeCAD set the allocation mode while loading.
        response["native_policy"] = native_allocation_policy()
        phases["import"] = (time.perf_counter() - began) * 1000
        phase = "load"
        began = time.perf_counter()
        shapes = {}
        for name in list(payloads):
            shape = Part.Shape()
            shape.importBrepFromString(payloads.pop(name).decode("ascii"))
            shapes[name] = shape
        phases["load"] = (time.perf_counter() - began) * 1000
        phase = "render"
        began = time.perf_counter()
        job = RenderInput(folder, scene, shapes, [dict(image) for image in envelope["outputs"]],
                          envelope["settings_digest"], phases)
        try:
            metadata = renderer(job)
        except TypeError as exc:
            # Raised by the call itself (no renderer frame entered): the seam is miswired.
            if exc.__traceback__ is not None and exc.__traceback__.tb_next is None:
                raise RendererCallError("Renderer cannot be called as renderer(job): " + str(exc)) from exc
            raise
        phases["render"] = (time.perf_counter() - began) * 1000
        del job, shapes
        phase = "seal"
        began = time.perf_counter()
        metadata = _json_copy(metadata)
        images = []
        for image in envelope["outputs"]:
            info = _seal_png(folder / image["name"])
            if (info["width"], info["height"]) != (image["width"], image["height"]):
                raise ValueError("Renderer wrote " + image["name"] + " at " + str(info["width"]) + "x"
                                 + str(info["height"]) + " instead of the requested size")
            images.append(dict(image, bytes=info["bytes"], sha256=info["sha256"]))
        phases["seal"] = (time.perf_counter() - began) * 1000
        response.update(ok=True, images=images, render=metadata)
    except Exception as exc:
        response["error"] = _child_error(exc, phase)


def run_worker(folder, token, renderer_spec):
    """Native child entry point: one job, one atomic JSON result, then exit."""
    began = time.perf_counter()
    line = sys.stdin.buffer.readline(MAX_WAKEUP_BYTES + 1)
    if len(line) > MAX_WAKEUP_BYTES:
        raise ValueError("Invalid render wake-up size")
    signal = json.loads(line)
    if signal.get("task") != token or type(signal.get("sequence")) is not int or signal["sequence"] < 0:
        raise ValueError("Invalid private render request")
    sequence = signal["sequence"]
    request_path = folder / ("request-" + str(sequence) + ".json")
    request = _read_json(request_path)
    request_path.unlink()
    if request.get("task") != token or type(request.get("sequence")) is not int or request["sequence"] != sequence:
        raise ValueError("Private render request identity changed")
    envelope = validate_envelope(request["proposal"])
    response = dict(envelope, task=token, sequence=sequence, ok=False, images=[], render=None, error=None,
                    engine=None, native_policy=None, native_modules_at_verify=None)
    phases = {}
    _render(folder, envelope, renderer_spec, response, phases)
    # Free whatever a failed render still referenced before sealing the result.
    gc.collect()
    peak_working_set, peak_commit = process_memory()
    response.update(phases=_clean_phases(phases), milliseconds=(time.perf_counter() - began) * 1000,
                    peak_working_set_mb=None if peak_working_set is None else round(peak_working_set / 2**20, 1),
                    peak_commit_mb=None if peak_commit is None else round(peak_commit / 2**20, 1),
                    core_imported="kurtshape.core" in sys.modules)
    try:
        payload = _json_bytes(response)
    except (TypeError, ValueError) as exc:
        # Drop everything the renderer supplied; keep only the worker's own facts.
        response.update(ok=False, images=[], render=None, phases=_clean_phases(phases, PHASES),
                        error={"code": "render_failed", "phase": "write", "message": str(exc)[:300]})
        payload = _json_bytes(response)
    destination = folder / ("result-" + str(sequence) + ".json")
    stage = destination.with_suffix(".writing")
    with stage.open("wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    _retry_permission(lambda: os.replace(stage, destination))


# --- Default renderer: model_render adapter (child side, never imports core) ---

def _expected_outputs(model_render, settings):
    """(name, width, height) of every PNG ``model_render.render_job`` writes for ``settings``."""
    normalized = model_render.normalize_settings(settings)
    width, height = normalized["size"]
    if normalized["layout"] == "sheet":
        return [("sheet.png", width, height)]
    return [("view-" + str(k) + ".png", width, height) for k in range(len(normalized["views"]))]


def render_scene(job):
    """Default renderer: build a ``model_render.Scene`` from the verified captures and render it.

    The scene document (job.scene) uses ``model_render.Scene.from_capture``'s
    format plus ``settings``, ``metadata`` and ``limits`` (module docstring);
    shapes come from ``job.shapes``, which the worker imported from verified
    bytes, so no capture file is read twice. Returns ``render_job``'s JSON-safe
    result, published as ``render``.
    """
    from kurtshape import model_render

    document, shapes = job.scene, job.shapes
    if not isinstance(document, dict):
        raise ValueError("Render scene must be a JSON object")
    options = {}
    for key in ("settings", "metadata", "limits"):
        value = document.get(key)
        if value is not None and not isinstance(value, dict):
            raise ValueError("Render scene field " + key + " must be an object")
        options[key] = value

    def capture(reference):
        if not isinstance(reference, str):
            raise ValueError("Render scene names a capture with a non-string reference")
        name = reference if reference in shapes or not reference.lower().endswith(".brep") else reference[:-5]
        if name not in shapes:
            raise ValueError("Render scene names an unknown capture: " + reference[:80])
        return shapes[name]

    def split(reference):
        if not reference:
            return []
        shape = capture(reference)
        if shape.isNull():
            return []
        return list(shape.SubShapes) if shape.ShapeType == "Compound" else [shape]

    def rows(key):
        value = document.get(key) or []
        if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
            raise ValueError("Render scene field " + key + " must be a list of objects")
        return value

    sketches = document.get("sketches") or []
    if not isinstance(sketches, list):
        raise ValueError("Render scene field sketches must be a list")
    wanted = [(image["name"], image["width"], image["height"]) for image in job.images]
    expected = _expected_outputs(model_render, options["settings"])
    if expected != wanted:
        raise ValueError("Render settings produce " + str(expected) + " but the job expects " + str(wanted))
    scene = model_render.Scene(
        [model_render.ScenePart(capture(part.get("brep")), name=part.get("name", ""), id=part.get("id"),
                                color=part.get("color"), solid=part.get("solid")) for part in rows("parts")],
        [model_render.SceneHighlight(item.get("label", chr(65 + index)), split(item.get("rendered")),
                                     note=item.get("note", ""), ghosts=split(item.get("ghost")),
                                     two_sided=item.get("two_sided", False))
         for index, item in enumerate(rows("highlights"))],
        [shape for reference in sketches for shape in split(reference)],
        title=document.get("title", ""), revision=document.get("revision", ""),
        banners=document.get("banners", ()), model_bounds=document.get("model_bounds"))
    result = model_render.render_job(scene, options["settings"], job.folder, metadata=options["metadata"],
                                     limits=options["limits"])
    written = [(row.get("file"), row.get("width"), row.get("height")) for row in result.get("images", ())]
    if written != wanted:
        raise ValueError("Renderer wrote " + str(written) + " instead of " + str(wanted))
    return result


if __name__ == "__main__":
    run_worker(Path(sys.argv[1]).resolve(), sys.argv[2], sys.argv[3])
