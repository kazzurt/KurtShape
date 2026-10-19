"""Contract 3.2 F2 ``render_view``: the owner-thread render service.

``RenderService`` validates a request, picks the parts to draw, reads their
status (never computing geometry), keys the image, answers from its caches or
captures detached world BREPs and highlight compounds, and starts one private
render child (``render_worker.NativeRenderWorker``, which runs
``model_render``). It completes through ``Deferred`` handles: the bridge parks
them and polls from the Panel tick, a direct ``Controller.dispatch`` waits.
Ledger completion is a done-callback, so ``request_status`` reconciles a
render exactly as it does a mutation; there is no separate job system.

Only the owner (Qt) thread calls this module. It never imports ``model_render``
(numpy, Pillow imaging): the few renderer values the owner needs are mirrored below and
pinned equal by the tests, so the GUI process never loads numpy or its BLAS threads.

Isolation: capture reads native shapes (``countElement``, world copies,
``exportBrep``, selector resolution) and writes nothing to the document: no
recompute, transaction, metadata, view, camera or selection change.
"""
from __future__ import annotations

from collections import OrderedDict
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import threading
import time

import FreeCAD as App
import Part

from .core import OperationError, number

# Mirrors of model_render constants (pinned equal by RenderJobTests), kept here so
# capabilities and the schema registry need no numpy/Pillow import.
RENDERER = "kurtshape-soft"
RENDERER_VERSION = 1
VIEW_NAMES = ("iso", "front", "back", "right", "left", "top", "bottom", "section")
STANDARD_VIEWS = ("front", "back", "right", "left", "top", "bottom")
SECTION_PLANES = {"XY": (0.0, 0.0, 1.0), "XZ": (0.0, -1.0, 0.0), "YZ": (1.0, 0.0, 0.0)}
LAYOUTS = ("separate", "sheet")
QUALITIES = ("standard", "draft")
FRAMES = ("included", "model", "highlights")
DEFAULT_SIZE = (1024, 768)
DEFAULT_SHEET_SIZE = (1536, 1152)
SHEET_GAP_PX = 4
SHEET_FOOTER_PX = 22
LEGEND_ROW_PX = 16
PARALLEL_COS = 0.999
FONT_FILES = {False: "DejaVuSans.ttf", True: "DejaVuSans-Bold.ttf"}
HIGHLIGHT_COLORS = ((230, 110, 0), (0, 150, 210), (200, 30, 120), (40, 160, 60),
                    (150, 80, 220), (210, 170, 0), (0, 170, 160), (220, 50, 50))
CAPTION_NOTE = "display mesh, not a validity check"
RESPONSE_NOTE = ("Images show tessellated display meshes of the listed parts in the selector world frame. "
                 "They do not establish geometric validity; rely on build_status, validation, "
                 "geometry_check/check_geometry and result_report.")

# Request limits (owned here; F2 section 3).
PART_MODES = ("all", "visible")
SKETCH_MODES = ("auto", "none", "include")
MIN_SIDE, MAX_SIDE = 128, 2048
MAX_PIXELS = 3_145_728
MAX_VIEWS = 7
MIN_TILE = (320, 240)
MAX_HIGHLIGHTS = 8
MAX_LABEL = 12
MAX_NOTE = 48
MAX_VIEW_NAME = 24
MAX_ITEM_MATCHES = 256
MAX_MATCHES = 1024
HIGHLIGHT_KEYS = frozenset({"selector", "input", "label", "note"})

# Owner-side prescreen and capture limits, the worker limit and the caches.
MAX_FACES = 5000
MAX_EDGES = 20000
MAX_BREP_BYTES = 48 * 2**20
JOB_TIMEOUT_SECONDS = 25
CACHE_ENTRIES = 64
CACHE_BYTES = 96 * 2**20
NEGATIVE_TTL_SECONDS = 600
CAPTURE_SLOTS = 2
HIGHLIGHT_CACHE_ENTRIES = 128   # resolved highlights per capture, reused across settings-only changes
POLL_SECONDS = 0.02
WAIT_GRACE_SECONDS = 5
PUBLISH_RETRY_SECONDS = 2.0
OWNERLESS_SWEEP_SECONDS = 24 * 3600
DEFAULT_WORKER_MS = 2000

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_DATUM_TYPES = frozenset({"PartDesign::Plane", "App::Plane", "Part::DatumPlane"})


_FONT_ID = []


def font_id():
    """model_render.font_id() without importing numpy: the identity of the fonts the child draws with."""
    if not _FONT_ID:
        import importlib.util
        import sys
        candidates = []
        try:
            spec = importlib.util.find_spec("matplotlib")  # locates the package without importing it
            if spec is not None and spec.origin:
                candidates.append(Path(spec.origin).parent / "mpl-data" / "fonts" / "ttf")
        except (ImportError, ValueError):
            pass
        candidates.append(Path(sys.executable).resolve().parent / "Lib" / "site-packages" / "matplotlib"
                          / "mpl-data" / "fonts" / "ttf")
        folder = next((item for item in candidates if all((item / name).is_file() for name in FONT_FILES.values())), None)
        if folder is None:
            import PIL  # the package root only; no imaging module
            _FONT_ID.append("pil-default-" + PIL.__version__)
        else:
            digest = hashlib.sha256()
            for bold in (False, True):
                digest.update((folder / FONT_FILES[bold]).read_bytes())
            _FONT_ID.append("dejavu-sans-" + digest.hexdigest()[:16])
    return _FONT_ID[0]


def highlight_color(index):
    return HIGHLIGHT_COLORS[index % len(HIGHLIGHT_COLORS)]


def capabilities():
    """The ``capabilities.render`` block (integration C4)."""
    return {"operation": "render_view", "views": list(VIEW_NAMES), "layouts": list(LAYOUTS),
            "qualities": list(QUALITIES), "frames": list(FRAMES), "parts": list(PART_MODES), "sketches": list(SKETCH_MODES),
            "default_size": list(DEFAULT_SIZE), "default_sheet_size": list(DEFAULT_SHEET_SIZE),
            "min_side": MIN_SIDE, "max_side": MAX_SIDE, "max_pixels": MAX_PIXELS, "max_views": MAX_VIEWS,
            "max_highlights": MAX_HIGHLIGHTS, "max_highlight_matches": MAX_ITEM_MATCHES, "max_matches": MAX_MATCHES,
            "format": "png", "projection": "orthographic",
            "section_planes": {name: list(normal) for name, normal in SECTION_PLANES.items()},
            "renderer": RENDERER, "renderer_version": RENDERER_VERSION, "read_only": True, "tracked": True,
            "deferred": True, "job_timeout_seconds": JOB_TIMEOUT_SECONDS, "concurrency": 1,
            "prescreen": {"faces": MAX_FACES, "edges": MAX_EDGES, "brep_bytes": MAX_BREP_BYTES},
            "cache": {"entries": CACHE_ENTRIES, "bytes": CACHE_BYTES, "negative_ttl_seconds": NEGATIVE_TTL_SECONDS},
            "artifacts": "session"}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _invalid(field, message, reason="value", **details):
    return OperationError("invalid_argument", message, fields=[field], reason=reason, **details)


# --------------------------------------------------------------------------- request normalization

def _vector(value, field, label):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise _invalid(field, label + " must be three numbers", "type")
    result = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float, str)):
            raise _invalid(field, label + " must be three numbers", "type")
        try:
            result.append(float(number(item, label)))
        except OperationError as exc:
            raise _invalid(field, str(exc), "type") from None
    return result


def _direction(value, field, label):
    vector = _vector(value, field, label)
    length = math.sqrt(sum(c * c for c in vector))
    if length < 1e-12:
        raise _invalid(field, label + " must be nonzero", "zero_vector")
    return [c / length for c in vector]


def _printable(text):
    return isinstance(text, str) and text.isprintable()


def _bool(request, field, default):
    value = request.get(field, default)
    if not isinstance(value, bool):
        raise _invalid(field, field + " must be true or false", "type")
    return value


def _views(request, section):
    raw = request.get("views")
    if raw is None:
        return ["section"] if section is not None else ["iso"]
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_VIEWS:
        raise _invalid("views", "views must be a list of 1 to %d views" % MAX_VIEWS, "count")
    views, seen = [], set()
    for item in raw:
        if isinstance(item, str):
            if item not in VIEW_NAMES:
                raise _invalid("views", "Unknown view " + repr(item)[:40], "value", allowed=list(VIEW_NAMES))
            if item == "section" and section is None:
                raise _invalid("views", 'view "section" needs a section', "requires_section")
            view, identity = item, item
        elif isinstance(item, dict):
            if "direction" not in item or set(item) - {"direction", "up", "name"}:
                raise _invalid("views", "A custom view is {direction, up?, name?}", "type")
            direction = _direction(item["direction"], "views", "view direction")
            view = {"direction": [round(c, 9) + 0.0 for c in direction]}
            if item.get("up") is not None:
                up = _direction(item["up"], "views", "view up")
                if abs(sum(a * b for a, b in zip(up, direction))) >= PARALLEL_COS:
                    raise _invalid("views", "view up must not be parallel to the view direction", "parallel_up")
                view["up"] = [round(c, 9) + 0.0 for c in up]
            name = item.get("name", "custom")
            if not _printable(name) or not 1 <= len(name) <= MAX_VIEW_NAME or name != name.strip():
                raise _invalid("views", "A view name has 1 to %d printable characters" % MAX_VIEW_NAME, "label")
            view["name"] = name
            identity = _canonical(view)
        else:
            raise _invalid("views", "A view is a view name or {direction, up?, name?}", "type")
        if identity in seen:
            raise _invalid("views", "views must be distinct", "duplicate")
        seen.add(identity)
        views.append(view)
    return views


def _section(request, doc):
    raw = request.get("section")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise _invalid("section", "section is {origin, normal}, {plane, offset} or {datum}", "type")
    keys = set(raw)
    if keys <= {"plane", "offset"} and "plane" in keys:
        plane = raw["plane"]
        if plane not in SECTION_PLANES:
            raise _invalid("section", "section plane must be XY, XZ or YZ", "value")
        try:
            offset = float(number(raw.get("offset", 0), "section offset"))
        except OperationError as exc:
            raise _invalid("section", str(exc), "type") from None
        normal = list(SECTION_PLANES[plane])
        origin = [offset * c + 0.0 for c in normal]
    elif keys == {"origin", "normal"}:
        origin = _vector(raw["origin"], "section", "section origin")
        normal = _direction(raw["normal"], "section", "section normal")
    elif keys == {"datum"}:
        datum = doc.getObject(raw["datum"]) if isinstance(raw["datum"], str) else None
        if datum is None or datum.TypeId not in _DATUM_TYPES:
            raise _invalid("section", "section datum must name a datum plane of the document", "unknown_datum")
        placement = datum.getGlobalPlacement()
        origin = [placement.Base.x, placement.Base.y, placement.Base.z]
        axis = placement.Rotation.multVec(App.Vector(0, 0, 1))
        normal = _direction([axis.x, axis.y, axis.z], "section", "datum normal")
    else:
        raise _invalid("section", "section is {origin, normal}, {plane, offset} or {datum}", "type")
    return {"origin": [round(c, 9) + 0.0 for c in origin], "normal": [round(c, 12) + 0.0 for c in normal]}


def _size(request, layout, view_count):
    raw = request.get("size")
    if raw is None:
        return list(DEFAULT_SHEET_SIZE if layout == "sheet" and view_count >= 5 else DEFAULT_SIZE)
    if (not isinstance(raw, list) or len(raw) != 2
            or any(isinstance(side, bool) or not isinstance(side, int) for side in raw)):
        raise _invalid("size", "size is [width, height] in whole pixels", "type")
    width, height = raw
    if not (MIN_SIDE <= width <= MAX_SIDE and MIN_SIDE <= height <= MAX_SIDE) or width * height > MAX_PIXELS:
        raise _invalid("size", "size sides must be %d to %d px with at most %d pixels" % (MIN_SIDE, MAX_SIDE, MAX_PIXELS),
                       "range")
    return [width, height]


def sheet_tile(view_count, size, legend_rows):
    """(tile_w, tile_h) of a sheet (model_render.sheet_geometry's arithmetic)."""
    columns = 2 if view_count <= 4 else 3
    rows = -(-view_count // columns)
    footer = SHEET_FOOTER_PX + LEGEND_ROW_PX * legend_rows
    return ((size[0] - (columns - 1) * SHEET_GAP_PX) // columns,
            (size[1] - footer - (rows - 1) * SHEET_GAP_PX) // rows)


def _highlights(request):
    raw = request.get("highlights")
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_HIGHLIGHTS:
        raise _invalid("highlights", "highlights is a list of at most %d items" % MAX_HIGHLIGHTS, "count")
    items, labels = [], set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or set(item) - HIGHLIGHT_KEYS or ("selector" in item) == ("input" in item):
            raise _invalid("highlights", "A highlight is {selector | input, label?, note?}", "type", highlight=index)
        label = item.get("label", chr(65 + index))
        if not _printable(label) or not 1 <= len(label) <= MAX_LABEL or label != label.strip():
            raise _invalid("highlights", "A highlight label has 1 to %d printable characters without outer spaces"
                           % MAX_LABEL, "label", highlight=index)
        if label in labels:
            raise _invalid("highlights", "Highlight labels must be unique", "duplicate", highlight=index)
        labels.add(label)
        note = item.get("note", "")
        if not _printable(note) or len(note) > MAX_NOTE:
            raise _invalid("highlights", "A highlight note has at most %d printable characters" % MAX_NOTE, "note",
                           highlight=index)
        row = {"label": label, "note": note}
        if "selector" in item:
            if not isinstance(item["selector"], dict):
                raise _invalid("highlights", "A highlight selector is a resolve_selector object", "type", highlight=index)
            row["selector"] = copy.deepcopy(item["selector"])
        else:
            source = item["input"]
            if (not isinstance(source, dict) or set(source) != {"feature", "name"}
                    or not all(isinstance(source[key], str) and source[key] for key in ("feature", "name"))):
                raise _invalid("highlights", "A stored-input highlight is {input: {feature, name}}", "type", highlight=index)
            row["input"] = {"feature": source["feature"], "name": source["name"]}
        items.append(row)
    return items


def normalize(request, doc):
    """Validated, default-filled settings of a render_view request (invalid_argument {fields, reason})."""
    section = _section(request, doc)
    views = _views(request, section)
    layout = request.get("layout", "separate")
    if layout not in LAYOUTS:
        raise _invalid("layout", "layout must be separate or sheet", "value")
    if layout == "sheet" and len(views) < 2:
        raise _invalid("layout", "A sheet needs at least two views", "count")
    size = _size(request, layout, len(views))
    parts = request.get("parts", "all")
    if isinstance(parts, list):
        if not parts or len(set(map(str, parts))) != len(parts) or not all(isinstance(p, str) and p for p in parts):
            raise _invalid("parts", "parts is all, visible or a list of distinct part ids", "type")
    elif parts not in PART_MODES:
        raise _invalid("parts", "parts is all, visible or a list of distinct part ids", "value")
    frame = request.get("frame", "included")
    if isinstance(frame, dict):
        if set(frame) != {"center_mm", "width_mm"}:
            raise _invalid("frame", "An explicit frame is {center_mm, width_mm}", "type")
        center = _vector(frame["center_mm"], "frame", "frame center_mm")
        try:
            width = float(number(frame["width_mm"], "frame width_mm"))
        except OperationError as exc:
            raise _invalid("frame", str(exc), "type") from None
        if not width > 0:
            raise _invalid("frame", "frame width_mm must be > 0", "range")
        frame = {"center_mm": center, "width_mm": width}
    elif frame not in FRAMES:
        raise _invalid("frame", "frame is included, model, highlights or {center_mm, width_mm}", "value")
    sketches = request.get("sketches", "auto")
    if sketches not in SKETCH_MODES:
        raise _invalid("sketches", "sketches is auto, none or include", "value")
    quality = request.get("quality", "standard")
    if quality not in QUALITIES:
        raise _invalid("quality", "quality is standard or draft", "value")
    highlights = _highlights(request)
    labels = _bool(request, "labels", True)
    if layout == "sheet":
        tile = sheet_tile(len(views), size, min(len(highlights), MAX_HIGHLIGHTS) if labels and highlights else 0)
        if tile[0] < MIN_TILE[0] or tile[1] < MIN_TILE[1]:
            raise _invalid("size", "Sheet tiles would be smaller than %d x %d px" % MIN_TILE, "range", tile_px=list(tile))
    return {"views": views, "layout": layout, "size": size, "parts": parts, "frame": frame, "highlights": highlights,
            "labels": labels, "part_labels": _bool(request, "part_labels", False), "sketches": sketches,
            "section": section, "edges": _bool(request, "edges", True), "quality": quality}


def view_label(view):
    return view if isinstance(view, str) else view["name"]


def renderer_settings(settings):
    """The model_render settings part of a normalized request."""
    return {key: settings[key] for key in ("views", "layout", "size", "frame", "labels", "part_labels", "section",
                                           "edges", "quality")}


def outputs(settings):
    """The worker envelope's ``outputs`` (render_worker / render_scene contract)."""
    width, height = settings["size"]
    if settings["layout"] == "sheet":
        return [{"view": "sheet", "name": "sheet.png", "width": width, "height": height}]
    return [{"view": view_label(view), "name": "view-%d.png" % k, "width": width, "height": height}
            for k, view in enumerate(settings["views"])]


# --------------------------------------------------------------------------- owner folders

def _process_identity(pid):
    """("alive", creation_time_100ns), ("dead", None) or ("unknown", None) for a process id."""
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return "dead", None
        except OSError:
            return "unknown", None
        return "alive", None
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    handle = kernel.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ("dead", None) if ctypes.get_last_error() == 87 else ("unknown", None)  # ERROR_INVALID_PARAMETER
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *[ctypes.byref(item) for item in times]):
            return "unknown", None
        exit_code = wintypes.DWORD()
        if kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)) and exit_code.value != 259:  # STILL_ACTIVE
            return "dead", None
        return "alive", (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    finally:
        kernel.CloseHandle(handle)


def sweep_owner_folders(parent, keep):
    """Remove sibling owner folders whose owner process provably ended; returns the removed names."""
    removed = []
    try:
        entries = list(Path(parent).iterdir())
    except OSError:
        return removed
    for folder in entries:
        if folder.name == keep or not folder.is_dir() or not _UUID.fullmatch(folder.name):
            continue
        try:
            record = json.loads((folder / "owner.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            try:
                stale = time.time() - folder.stat().st_mtime > OWNERLESS_SWEEP_SECONDS
            except OSError:
                continue
            if stale:
                shutil.rmtree(folder, ignore_errors=True)
                removed.append(folder.name)
            continue
        except (OSError, ValueError):
            continue
        pid = record.get("pid") if isinstance(record, dict) else None
        if type(pid) is not int:
            continue
        state, created = _process_identity(pid)
        if state == "dead" or (state == "alive" and created is not None
                               and record.get("creation_time_100ns") not in (None, created)):
            shutil.rmtree(folder, ignore_errors=True)
            removed.append(folder.name)
    return removed


# --------------------------------------------------------------------------- handles and caches

class Deferred:
    """One request's pending render. ``poll()`` returns None until the response exists."""

    def __init__(self, service, job):
        self._service, self.job = service, job
        self._callbacks = []
        self.response = None

    def add_done_callback(self, callback):
        if self.response is not None:
            callback(copy.deepcopy(self.response))
        else:
            self._callbacks.append(callback)

    def done(self):
        return self.response is not None

    def poll(self):
        if self.response is None:
            self._service.poll()
        return None if self.response is None else copy.deepcopy(self.response)

    def wait(self, timeout=None):
        """Poll until done (headless ``dispatch``): at most the job timeout plus a grace period."""
        limit = (timeout if timeout is not None
                 else getattr(self.job.worker, "timeout", JOB_TIMEOUT_SECONDS) + WAIT_GRACE_SECONDS)
        deadline = time.monotonic() + limit
        while True:
            try:
                if self.poll() is not None:
                    break
            except Exception as exc:
                self._service.controller._log_exception()
                self.cancel(_failure(OperationError("render_failed", "Render poll failed: " + str(exc)[:300])))
                break
            if time.monotonic() > deadline:
                self.cancel(_failure(OperationError("render_timeout", "Render did not complete in time",
                                                    timeout_seconds=limit)))
                break
            time.sleep(POLL_SECONDS)
        return copy.deepcopy(self.response)

    def cancel(self, response):
        """Complete this request with ``response``; the job stops when nobody waits for it."""
        if self.response is None:
            self._service._detach(self)
            self._resolve(response)

    def _resolve(self, response):
        if self.response is not None:
            return
        self.response = response
        callbacks, self._callbacks = self._callbacks, []
        for callback in callbacks:
            try:
                callback(copy.deepcopy(response))
            except Exception:
                self._service.controller._log_exception()


class RenderJob:
    def __init__(self, key, worker, context):
        self.key, self.worker = key, worker
        self.context = context
        self.deferreds = []
        self.started = time.perf_counter()
        self.response = self.rows = None   # the child's verified answer, kept while PNGs are published
        self.published = []
        self.publish_deadline = None

    def attach(self, service):
        handle = Deferred(service, self)
        self.deferreds.append(handle)
        return handle


def _failure(error):
    return {"ok": False, "error": {"code": error.code, "message": str(error), **error.details}}


def worker_error(exc):
    """A worker failure as an OperationError with a whitelisted render code."""
    if isinstance(exc, OperationError) and exc.code in {"render_timeout", "render_too_large", "render_failed"}:
        return exc
    if not isinstance(exc, OperationError):
        from .render_worker import as_render_error
        exc = as_render_error(exc)  # a plain TimeoutError is a render_timeout, anything else render_failed
    details = {key: value for key, value in getattr(exc, "details", {}).items()
               if key not in {"code", "message"}}
    message = str(exc)[:600]
    code = getattr(exc, "code", None)
    if code == "render_timeout":
        return OperationError("render_timeout", message, **details)
    if code == "render_too_large":
        return OperationError("render_too_large", message, **details)
    return OperationError("render_failed", message, **details)


class RenderCache:
    """Image entries (LRU, own files only) plus negative entries for deterministic failures."""

    def __init__(self, max_entries=CACHE_ENTRIES, max_bytes=CACHE_BYTES, negative_ttl=NEGATIVE_TTL_SECONDS):
        self.max_entries, self.max_bytes, self.negative_ttl = max_entries, max_bytes, negative_ttl
        self.entries = OrderedDict()

    @property
    def bytes(self):
        return sum(entry.get("bytes", 0) for entry in self.entries.values())

    @property
    def negative_entries(self):
        return sum(1 for entry in self.entries.values() if "error" in entry)

    def get(self, key):
        entry = self.entries.get(key)
        if entry is None or "error" in entry:
            return None
        for path, size, mtime in entry["files"]:
            try:
                info = os.stat(path)
            except OSError:
                info = None
            if info is None or info.st_size != size or info.st_mtime_ns != mtime:
                self.evict(key)
                return None
        self.entries.move_to_end(key)
        return entry

    def negative(self, key):
        entry = self.entries.get(key)
        if entry is None or "error" not in entry:
            return None
        if time.monotonic() > entry["expires"]:
            self.entries.pop(key, None)
            return None
        return entry["error"]

    def put(self, key, files, result):
        self.evict(key)
        rows = [(str(path), os.stat(path).st_size, os.stat(path).st_mtime_ns) for path in files]
        self.entries[key] = {"files": rows, "result": result, "bytes": sum(size for _, size, _ in rows)}
        self._trim()

    def put_negative(self, key, error):
        self.evict(key)
        self.entries[key] = {"error": error, "expires": time.monotonic() + self.negative_ttl, "bytes": 0}
        self._trim()

    def evict(self, key):
        entry = self.entries.pop(key, None)
        for path, _, _ in (entry or {}).get("files", ()):
            try:
                os.unlink(path)
            except OSError:
                pass

    def _trim(self):
        while self.entries and (len(self.entries) > self.max_entries or self.bytes > self.max_bytes):
            self.evict(next(iter(self.entries)))

    def clear(self):
        for key in list(self.entries):
            self.evict(key)


# --------------------------------------------------------------------------- service

class RenderService:
    """Lazy per-Controller render service (F2 section 2.2-2.6); owner thread only."""

    def __init__(self, controller, session_dir):
        self.controller = controller
        self.session_dir = Path(session_dir).resolve()
        self.owner = self.session_dir / "renders" / controller.ledger.session_id
        self.worker_factory = None          # tests: callable(executable, session_dir, timeout=) -> worker
        self.worker_timeout = JOB_TIMEOUT_SECONDS
        self.renderer = None                # tests: render_worker renderer spec
        self.renderer_limits = None         # tests: model_render limit overrides (in the image key)
        self.limits = {"faces": MAX_FACES, "edges": MAX_EDGES, "brep_bytes": MAX_BREP_BYTES}
        self.cache = RenderCache()
        self.captures = OrderedDict()       # geometry key -> {"folder", "captures", "instance_id", "pinned"}
        # (capture key, highlight source) -> {"capture", "matches", "files"}: resolved once per captured
        # geometry, so a view, size, section, label or note change neither resolves nor exports again.
        self.highlight_cache = OrderedDict()
        self.counters = {"highlight_resolutions": 0, "highlight_cache_hits": 0, "highlight_exports": 0}
        self.active = None
        self.last_worker_ms = None
        self.last_peak_commit_mb = None
        self.closed = False
        self.swept = []
        self._create_owner()

    # ----------------------------------------------------------------- ownership
    def _create_owner(self):
        self.owner.mkdir(parents=True, exist_ok=True)
        state, created = _process_identity(os.getpid())
        record = {"pid": os.getpid(), "creation_time_100ns": created if state == "alive" else None,
                  "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        (self.owner / "owner.json").write_text(json.dumps(record), encoding="utf-8")
        self.swept = sweep_owner_folders(self.owner.parent, self.owner.name)

    # ----------------------------------------------------------------- request
    def request(self, doc, request, retry=True):
        began = time.perf_counter()
        controller = self.controller
        if self.closed:
            raise OperationError("render_cancelled", "The render service is closed")
        identifier = controller.identifier(doc)
        if (identifier in controller.sketch_edits or doc.HasPendingTransaction
                or getattr(App, "GuiUp", False) and controller._native_edit_active()):
            raise OperationError("sketch_edit_active", "Finish or cancel the active edit before rendering")
        meta = controller._meta(doc)
        if "expected_revision" in request and request["expected_revision"] != meta.Revision:
            raise OperationError("stale_revision", "Inspect the current document before rendering",
                                 expected=request["expected_revision"], actual=meta.Revision)
        settings = normalize(request, doc)
        scene = self._targets(doc, settings)
        if settings["section"] is not None:
            self._check_section(settings["section"], scene)
        status = self._status(doc, scene)
        state = controller.observer.state(doc)
        fence = (meta.Revision, state["instance_id"], state["generation"], state["change_serial"])
        key = self._image_key(doc, settings, scene, status, fence)
        entry = self.cache.get(key)
        if entry is not None:
            result = copy.deepcopy(entry["result"])
            elapsed = round((time.perf_counter() - began) * 1000, 2)
            result.update(cached=True, stale=False, timing_ms={"owner": elapsed, "total": elapsed})
            controller.timings.record("render_cache_hit", elapsed)
            return {"ok": True, "result": result}
        negative = self.cache.negative(key)
        if negative is not None:
            return {"ok": False, "error": dict(copy.deepcopy(negative), cached=True)}
        if self.active is not None:
            if self.active.key == key:
                return self.active.attach(self)
            elapsed = (time.perf_counter() - self.active.started) * 1000
            retry = min(max((self.last_worker_ms or DEFAULT_WORKER_MS) - elapsed, 250), 5000)
            raise OperationError("render_busy", "Another render is running; retry shortly",
                                 retry_after_ms=int(retry), active_render_id=self.active.key[:16])
        self._prescreen(scene)
        previous_busy = controller.busy
        controller.busy = True
        changed = False
        try:
            highlights_began = time.perf_counter()
            capture_key = self._capture_key(scene, fence)
            matches = self._resolve_highlights(doc, settings, scene, capture_key)
            highlights_ms = (time.perf_counter() - highlights_began) * 1000
            capture = self._capture(doc, scene, fence)
            state = controller.observer.state(doc)
            # Fence (F2 §2.2 step 10): a re-entrant native callback changed the document during capture.
            changed = (controller._meta(doc).Revision, state["instance_id"], state["generation"],
                       state["change_serial"]) != fence
            if changed:
                self._drop_capture(capture["key"])
            else:
                job = self._start(doc, settings, scene, status, matches, capture, key, fence)
        finally:
            controller.busy = previous_busy
        if changed:
            if not retry:
                raise OperationError("render_capture_changed", "The document changed while it was captured; retry")
            # Start over once from a fresh sync: new revision, status, keys and capture.
            controller.sync(doc)
            return self.request(doc, request, retry=False)
        owner_ms = (time.perf_counter() - began) * 1000
        controller.timings.record("render_capture_gui", round(owner_ms - highlights_ms, 2))
        if settings["highlights"]:
            controller.timings.record("render_highlights_gui", round(highlights_ms, 2))
        job.context.update(owner_ms=owner_ms, highlights_ms=highlights_ms, began=began)
        return job.attach(self)

    # ----------------------------------------------------------------- targets and status
    def _targets(self, doc, settings):
        from .bodies import results as native_results, owner
        from . import selectors
        mode = settings["parts"]
        wanted = set(mode) if isinstance(mode, list) else set()
        matched = set()
        targets, omitted, every = [], [], []
        for obj in native_results(doc):
            source = selectors.result_source(obj)
            part = selectors._part_id(doc, obj)
            shape = getattr(source, "Shape", None)
            names = {obj.Name, part, source.Name}
            if "KurtShapePartVisible" in obj.PropertiesList:
                visible, visibility_source = bool(obj.KurtShapePartVisible), "part_flag"
            else:
                visible, visibility_source = bool(getattr(obj, "Visibility", True)), "object"
            if shape is None or shape.isNull():
                # A sketch-only Body: never a target, but the parts filter still governs its sketches.
                omitted.append({"part": part, "body": obj.Name, "reason": "no_shape",
                                "filtered": bool(names & wanted) is False if isinstance(mode, list)
                                else mode == "visible" and not visible})
                continue
            row = {"obj": obj, "source": source, "part": part, "visible": visible,
                   "visibility_source": visibility_source}
            every.append(row)
            if isinstance(mode, list):
                hit = names & wanted
                matched |= hit
                include = bool(hit)
            else:
                include = mode == "all" or visible
            (targets if include else omitted).append(row if include else {"part": part, "body": obj.Name,
                                                                         "reason": "filtered"})
        sketches_all = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject"
                        and selectors._active(obj) and not obj.Shape.isNull() and obj.Shape.Edges]
        if isinstance(mode, list):
            matched |= wanted & {sketch.Name for sketch in sketches_all}
            missing = sorted(wanted - matched)
            if missing:
                raise OperationError("missing_part", "Unknown part, result or sketch: " + ", ".join(missing),
                                     parts=missing)
        included_bodies = {row["obj"].Name for row in targets}
        for row in targets:
            # Response-facing metadata is frozen here: the scene the child draws and the completion
            # response must both describe the captured revision, never live objects (they may be renamed,
            # recoloured or deleted while the job runs).
            row.update(body=row["obj"].Name, name=self._name(row["obj"]), color=self._color(row["obj"]))
        filtered_bodies = {row["body"] for row in omitted if row["reason"] == "filtered" or row.pop("filtered", False)}
        for row in targets:
            row["faces"] = row["source"].Shape.countElement("Face")
            row["edges"] = row["source"].Shape.countElement("Edge")
            row["solid"] = bool(row["source"].Shape.Solids)
        sketches = []
        if settings["sketches"] != "none":
            faces = any(row["faces"] for row in targets)
            if settings["sketches"] == "include" or not faces:
                for sketch in sketches_all:
                    body = owner(doc, sketch)
                    # A listed sketch, a sketch of an included part, or (all/visible) any sketch whose
                    # Body was not filtered out: a sketch-only Body has no shape and is never a target.
                    if (sketch.Name in wanted or (body is not None and body.Name in included_bodies)
                            or (not isinstance(mode, list) and (body is None or body.Name not in filtered_bodies))):
                        sketches.append(sketch)
        if not any(row["faces"] for row in targets) and not sketches:
            raise OperationError("no_geometry", "Nothing to draw: the selected parts have no faces and no sketch is shown",
                                 omitted_parts=[{"part": row["part"], "reason": row["reason"]} for row in omitted])
        return {"targets": targets, "omitted": omitted, "every": every, "sketches": sketches,
                "sketch_names": [sketch.Name for sketch in sketches]}

    def _status(self, doc, scene):
        controller = self.controller
        from . import studio
        meta = controller._meta(doc)
        managed = controller.is_managed(doc)
        for row in scene["targets"]:
            status = controller._result_row(doc, row["obj"], meta, None)
            row["build_status"] = status["build_status"]
            row["geometry"] = status["geometry_state"]
            row["geometry_check"] = status["geometry_check"]
            row["result_check"] = status["result_check"]
            # Assembly occurrences (App::Link) are placed by inspect's global_shape as well; only a result
            # nested in a placed container differs between the selector world frame and inspect's bbox.
            try:
                row["in_container"] = (row["obj"].TypeId != "App::Link"
                                       and not row["obj"].getGlobalPlacement().isSame(row["obj"].Placement, 1e-9))
            except Exception:
                row["in_container"] = False
        native = controller.observer.state(doc).get("native_status") or meta.BuildStatus
        summary = controller.result_checks.summary(doc) if managed else None
        validation = None
        if summary and summary.get("status") not in (None, "not_applicable"):
            validation = {"status": summary["status"], "failed": sorted(row.get("feature") for row in summary["failed"]),
                          "pending": list(summary["pending"])}
        banners = []
        if native == "failed":
            banners.append({"kind": "build_failed"})
        elif native == "needs_rebuild":
            banners.append({"kind": "needs_rebuild"})
        if validation and validation["status"] == "failed":
            banners.append({"kind": "validation_failed"})
        elif validation and validation["status"] == "pending":
            banners.append({"kind": "validation_pending"})
        if any(row["geometry_check"] == "invalid" for row in scene["targets"]):
            banners.append({"kind": "check_invalid"})
        non_solid = [row["part"] for row in scene["targets"] if row["faces"] and not row["solid"]]
        if non_solid:
            banners.append({"kind": "non_solid", "count": len(non_solid)})
        rollback = None
        if managed and studio.enabled(doc):
            history = studio.inspect(doc)
            if history["rollback_index"] < len(history["feature_order"]):
                rollback = {"index": history["rollback_index"], "length": len(history["feature_order"])}
                banners.append({"kind": "rolled_back", **rollback})
        if not managed:
            banners.append({"kind": "unmanaged"})
        # Native failure or a pending rebuild leaves every result at its last recompute (retained), even
        # when the failing feature is upstream of a result whose own row reads current; a result-check
        # failure is current geometry (validation.md D7, integration C20).
        states = {row["geometry"] for row in scene["targets"] if row["faces"]}
        if native in {"failed", "needs_rebuild"}:
            geometry = "retained"
        else:
            geometry = "current" if states <= {"current"} else ("retained" if states == {"retained"} else "mixed")
        return {"build_status": meta.BuildStatus, "native_status": native, "geometry": geometry,
                "geometry_check": controller._check_status([row["obj"] for row in scene["targets"]]),
                "validation": validation, "rollback": rollback, "non_solid_parts": non_solid, "banners": banners}

    def _image_key(self, doc, settings, scene, status, fence):
        meta = self.controller._meta(doc)
        targets = [[row["body"], row["part"], row["name"], row["color"], row["build_status"],
                    row["geometry"], row["geometry_check"], row["result_check"], row["solid"], row["visible"]]
                   for row in scene["targets"]]
        return _digest({"renderer": [RENDERER, RENDERER_VERSION, font_id()],
                        "engine": [list(App.Version()[:4]), Part.OCC_VERSION],
                        "document": [meta.DocumentId, fence[1], fence[0], fence[2]], "title": doc.Label[:60],
                        "targets": targets, "sketches": scene["sketch_names"],
                        "status": {key: status[key] for key in ("build_status", "native_status", "validation",
                                                                "rollback", "banners")},
                        "settings": settings, "limits": self.renderer_limits})

    @staticmethod
    def _name(obj):
        """The part name inspect shows (studio.parts[].name), else the object's label."""
        return str(getattr(obj, "KurtShapePartName", "") or obj.Label)

    @staticmethod
    def _color(obj):
        if "KurtShapePartColor" in getattr(obj, "PropertiesList", ()):
            return [round(float(c), 4) for c in obj.KurtShapePartColor[:3]]
        return None

    def _prescreen(self, scene):
        faces = sum(row["faces"] for row in scene["targets"])
        edges = sum(row["edges"] for row in scene["targets"])
        if faces > self.limits["faces"]:
            raise OperationError("render_too_large", "The selected parts have too many faces to render",
                                 reason="faces", faces=faces, edges=edges, limit=self.limits["faces"])
        if edges > self.limits["edges"]:
            raise OperationError("render_too_large", "The selected parts have too many edges to render",
                                 reason="edges", faces=faces, edges=edges, limit=self.limits["edges"])

    def _check_section(self, section, scene):
        """Reject a plane with every corner of the drawn parts' world box strictly on one side."""
        boxes = [self._world_box(row["source"]) for row in scene["targets"] if row["faces"]]
        boxes += [self._world_box(sketch) for sketch in scene["sketches"]]
        boxes = [box for box in boxes if box is not None]
        if not boxes:
            return
        lo = [min(box.XMin for box in boxes), min(box.YMin for box in boxes), min(box.ZMin for box in boxes)]
        hi = [max(box.XMax for box in boxes), max(box.YMax for box in boxes), max(box.ZMax for box in boxes)]
        origin, normal = section["origin"], section["normal"]
        distances = [sum((corner[i] - origin[i]) * normal[i] for i in range(3))
                     for corner in ([x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2]))]
        if all(d > 1e-9 for d in distances) or all(d < -1e-9 for d in distances):
            raise OperationError("section_misses_parts", "The section plane does not cut the shown parts",
                                 side="removed" if distances[0] > 0 else "kept",
                                 bbox_mm=[[round(c, 6) for c in lo], [round(c, 6) for c in hi]])

    @staticmethod
    def _world_box(obj):
        """World bounding box of an object's shape without copying it, or None."""
        box = obj.Shape.BoundBox
        if not box.isValid():
            return None
        try:
            transform = obj.getGlobalPlacement() * obj.Placement.inverse()
            if not transform.isIdentity():
                box = box.transformed(transform.toMatrix())
        except Exception:
            pass
        return box

    # ----------------------------------------------------------------- highlights
    def _input_refs(self, doc, source, index):
        from . import selectors
        feature = doc.getObject(source["feature"])
        if feature is None:
            raise OperationError("missing_input", "Unknown highlight input feature", highlight=index, **source)
        name = source["name"]
        candidates = [feature] + [obj for obj in doc.Objects
                                  if getattr(obj, "KurtShapeOperationOwner", "") == feature.Name and obj is not feature]
        available = []
        for obj in candidates:
            names = selectors.stored_input_names(obj)
            if name in names:
                return selectors.stored_input_refs(obj, name)
            prefix = "" if obj is feature else obj.Name + "."
            available.extend(prefix + item for item in names)
            if prefix and name.startswith(prefix) and name[len(prefix):] in names:
                return selectors.stored_input_refs(obj, name[len(prefix):])
        raise OperationError("missing_input", "The feature has no stored input of that name", highlight=index,
                             available=sorted(available), **source)

    def _resolve_highlights(self, doc, settings, scene, capture_key):
        """One entry per highlight: {key, matches (scalar rows), files (cached BREP rows) or shapes (fresh)}."""
        from . import selectors
        if not settings["highlights"]:
            if settings["frame"] == "highlights":
                raise OperationError("highlight_not_rendered", 'frame "highlights" needs at least one highlight')
            return []
        included = {row["source"].Name: row for row in scene["targets"]}
        excluded = {selectors.result_source(row["obj"]).Name for row in scene["every"]} - set(included)
        drawn_sketches = set(scene["sketch_names"])
        result, total = [], 0
        for index, item in enumerate(settings["highlights"]):
            source = {"selector": item["selector"]} if "selector" in item else {"input": item["input"]}
            # The matches and their classes depend only on the source and the captured scene (the capture key
            # covers the revision, generation, drawn targets and sketches); labels and notes do not.
            key = _digest([capture_key, source])
            cached = self.highlight_cache.get(key)
            if (cached is not None and self._capture_valid(capture_key)
                    and all(row is None or os.path.isfile(row["path"]) for row in cached["files"].values())):
                self.highlight_cache.move_to_end(key)
                self.counters["highlight_cache_hits"] += 1
                total += len(cached["matches"])
                if len(cached["matches"]) > MAX_ITEM_MATCHES or total > MAX_MATCHES:
                    raise OperationError("too_many_highlight_matches", "Highlights match too many elements",
                                         highlight=index, count=len(cached["matches"]), total=total,
                                         limit=MAX_ITEM_MATCHES, total_limit=MAX_MATCHES)
                result.append({"key": key, "matches": cached["matches"], "files": cached["files"], "shapes": None})
                continue
            self.counters["highlight_resolutions"] += 1
            try:
                if "selector" in item:
                    rows = selectors.resolve(doc, item["selector"], shapes=True)
                else:
                    rows = [row for reference in self._input_refs(doc, item["input"], index)
                            for row in selectors.resolve(doc, reference, shapes=True)]
            except OperationError as exc:
                exc.details.setdefault("highlight", index)
                raise
            unique = OrderedDict()
            for row in rows:
                unique.setdefault((row["feature"], row["subelement"]), row)
            rows = list(unique.values())
            if not rows:
                raise OperationError("highlight_no_match", "Highlight %d matches nothing" % index, highlight=index)
            total += len(rows)
            if len(rows) > MAX_ITEM_MATCHES or total > MAX_MATCHES:
                raise OperationError("too_many_highlight_matches", "Highlights match too many elements", highlight=index,
                                     count=len(rows), total=total, limit=MAX_ITEM_MATCHES, total_limit=MAX_MATCHES)
            matches, shapes = [], {"r": [], "g": []}
            for row in rows:
                feature = row["feature"]
                obj = doc.getObject(feature)
                if feature in included:
                    reason = None
                elif obj is not None and obj.TypeId == "Sketcher::SketchObject":
                    reason = None if feature in drawn_sketches else "sketch"
                elif feature in excluded:
                    reason = "filtered_part"
                else:
                    reason = "history"
                box = row["shape"].BoundBox
                matches.append({"feature": feature, "subelement": row["subelement"], "entity_type": row["entity_type"],
                                "part": row.get("part"), "rendered": reason is None, "reason": reason,
                                "bbox": [box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax]
                                if box.isValid() else None,
                                "two_sided": feature in included and not included[feature]["solid"]})
                shapes["r" if reason is None else "g"].append(row["shape"])
            result.append({"key": key, "matches": matches, "files": None, "shapes": shapes})
        if settings["frame"] == "highlights" and not any(match["rendered"] and self._kept(match["bbox"], settings["section"])
                                                         for entry in result for match in entry["matches"]):
            raise OperationError("highlight_not_rendered",
                                 'frame "highlights" needs at least one highlight match in the shown geometry')
        return result

    @staticmethod
    def _kept(box, section):
        """Whether any part of a world box [xmin, ymin, zmin, xmax, ymax, zmax] lies on the kept side of the section."""
        if section is None:
            return True
        if box is None:
            return False
        origin, normal = section["origin"], section["normal"]
        return any(sum((corner[i] - origin[i]) * normal[i] for i in range(3)) <= 1e-9
                   for corner in ([x, y, z] for x in (box[0], box[3]) for y in (box[1], box[4]) for z in (box[2], box[5])))

    # ----------------------------------------------------------------- capture
    @staticmethod
    def _capture_key(scene, fence):
        return _digest([fence[1], fence[0], fence[2],
                        [[row["body"], row["part"], row["source"].Name] for row in scene["targets"]],
                        scene["sketch_names"]])

    def _capture_valid(self, key):
        entry = self.captures.get(key)
        return entry is not None and all(os.path.isfile(row["path"]) and os.path.getsize(row["path"]) == row["bytes"]
                                         for row in entry["captures"])

    def _capture(self, doc, scene, fence):
        from . import selectors
        key = self._capture_key(scene, fence)
        entry = self.captures.get(key)
        if entry is not None and self._capture_valid(key):
            self.captures.move_to_end(key)
            return entry
        if entry is not None:
            self._drop_capture(key)
        folder = self.owner / ("cap-" + key[:16])
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
        rows, total = [], 0
        try:
            for index, row in enumerate(scene["targets"]):
                if not row["faces"]:
                    continue
                path = folder / ("part-%d.brep" % index)
                selectors.world_shape(row["source"]).exportBrep(str(path))
                total += path.stat().st_size
                if total > self.limits["brep_bytes"]:
                    raise OperationError("render_too_large", "The selected parts' BREP capture is too large to render",
                                         reason="brep_bytes", bytes=total, limit=self.limits["brep_bytes"])
                rows.append(self._capture_row("part-%d" % index, path))
            if scene["sketches"]:
                path = folder / "sketches.brep"
                Part.makeCompound([selectors.world_shape(sketch) for sketch in scene["sketches"]]).exportBrep(str(path))
                rows.append(self._capture_row("sketches", path))
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        (folder / "capture.json").write_text(_canonical({"captures": rows}), encoding="utf-8")
        entry = {"key": key, "folder": folder, "captures": rows, "instance_id": fence[1], "pinned": False}
        self.captures[key] = entry
        for old in [name for name, item in self.captures.items() if name != key and not item["pinned"]]:
            if len(self.captures) <= CAPTURE_SLOTS:
                break
            self._drop_capture(old)
        return entry

    @staticmethod
    def _capture_row(name, path):
        data = Path(path).read_bytes()
        return {"name": name, "path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}

    def _drop_capture(self, key):
        entry = self.captures.pop(key, None)
        for name in [name for name, item in self.highlight_cache.items() if item["capture"] == key]:
            del self.highlight_cache[name]
        if entry is not None:
            shutil.rmtree(entry["folder"], ignore_errors=True)

    def _highlight_files(self, capture, entry):
        """BREP capture rows of one highlight: cached, or written once per distinct match set into the capture."""
        if entry["files"] is not None:
            return entry["files"]
        files = {}
        for cls in ("r", "g"):
            shapes = entry["shapes"][cls]
            if not shapes:
                files[cls] = None
                continue
            wanted = cls == "r"
            identity = sorted((row["feature"], row["subelement"]) for row in entry["matches"] if row["rendered"] == wanted)
            name = "hl-%s-%s" % (_digest([cls, identity])[:16], cls)
            path = capture["folder"] / (name + ".brep")
            if not path.is_file():
                Part.makeCompound(shapes).exportBrep(str(path))
                self.counters["highlight_exports"] += 1
            files[cls] = self._capture_row(name, path)
        entry["files"], entry["shapes"] = files, None
        self.highlight_cache[entry["key"]] = {"capture": capture["key"], "matches": entry["matches"], "files": files}
        self.highlight_cache.move_to_end(entry["key"])
        while len(self.highlight_cache) > HIGHLIGHT_CACHE_ENTRIES:
            self.highlight_cache.popitem(last=False)
        return files

    # ----------------------------------------------------------------- job start
    def _new_worker(self):
        executable = Path(App.getHomePath()) / "bin" / ("python.exe" if os.name == "nt" else "python")
        if self.worker_factory is not None:
            return self.worker_factory(executable, self.session_dir, timeout=self.worker_timeout)
        from .render_worker import NativeRenderWorker
        return NativeRenderWorker(executable, self.session_dir, timeout=self.worker_timeout, renderer=self.renderer)

    def _start(self, doc, settings, scene, status, matches, capture, key, fence):
        controller = self.controller
        meta = controller._meta(doc)
        worker = self._new_worker()
        try:
            captures = [dict(row) for row in capture["captures"]]
            names = {row["name"] for row in captures}
            highlights = []
            for item, resolved in zip(settings["highlights"], matches):
                files = self._highlight_files(capture, resolved)
                for row in files.values():
                    if row is not None and row["name"] not in names:  # identical match sets share one file
                        names.add(row["name"])
                        captures.append(dict(row))
                highlights.append({"label": item["label"], "note": item["note"],
                                   "rendered": files["r"]["name"] if files["r"] else None,
                                   "ghost": files["g"]["name"] if files["g"] else None,
                                   "two_sided": any(row["two_sided"] for row in resolved["matches"] if row["rendered"])})
            boxes = [box for box in (self._world_box(row["source"]) for row in scene["every"]) if box is not None]
            bounds = None
            if boxes:
                bounds = [[min(b.XMin for b in boxes), min(b.YMin for b in boxes), min(b.ZMin for b in boxes)],
                          [max(b.XMax for b in boxes), max(b.YMax for b in boxes), max(b.ZMax for b in boxes)]]
            parts, index_of = [], {}
            for index, row in enumerate(scene["targets"]):
                if row["faces"]:
                    index_of[index] = len(parts)
                    parts.append({"brep": "part-%d" % index, "name": row["name"], "id": row["part"],
                                  "color": row["color"], "solid": row["solid"]})
            document = {"title": doc.Label[:60], "revision": meta.Revision[:8], "banners": status["banners"],
                        "model_bounds": bounds, "parts": parts,
                        "sketches": ["sketches"] if scene["sketches"] else [], "highlights": highlights,
                        "settings": renderer_settings(settings),
                        "metadata": {"document": meta.DocumentId, "revision": meta.Revision, "render_id": key[:16],
                                     "note": CAPTION_NOTE}}
            if self.renderer_limits:
                document["limits"] = dict(self.renderer_limits)
            raw = _canonical(document).encode()
            worker.scene_path.write_bytes(raw)
            envelope = {"scene_sha256": hashlib.sha256(raw).hexdigest(), "settings_digest": _digest(settings),
                        "captures": [{key_: row[key_] for key_ in ("name", "path", "sha256", "bytes")} for row in captures],
                        "outputs": outputs(settings)}
            worker.submit(1, envelope)
        except OperationError:
            worker.close()
            raise
        except Exception as exc:
            worker.close()
            raise worker_error(exc) from exc
        capture["pinned"] = True
        context = {"doc": doc, "doc_name": doc.Name, "settings": settings, "scene": scene, "status": status,
                   "matches": matches, "capture_key": capture["key"], "fence": fence, "document_id": meta.DocumentId,
                   "part_index": index_of}
        self.active = RenderJob(key, worker, context)
        return self.active

    # ----------------------------------------------------------------- completion
    def poll(self):
        """Advance the active job (owner thread, cheap); every outcome completes all of its waiters."""
        job = self.active
        if job is None:
            return
        try:
            self._advance(job)
        except Exception as exc:
            # Anything after the child answered (verification, publishing, the response, the cache) must
            # still complete the job: otherwise its waiters and ledger records stay started forever.
            if not isinstance(exc, OperationError) and not hasattr(exc, "deterministic"):
                self.controller._log_exception()
            if self.active is job:
                self._finish(job, error=worker_error(exc), deterministic=bool(getattr(exc, "deterministic", False)))

    def _advance(self, job):
        if job.response is None:
            timeout = getattr(job.worker, "timeout", JOB_TIMEOUT_SECONDS)
            response = job.worker.poll()
            if response is None:
                # Watchdog: the worker enforces its own limit while it runs; this bounds anything else.
                if time.perf_counter() - job.started > timeout + WAIT_GRACE_SECONDS:
                    raise OperationError("render_timeout", "Render did not complete in time", timeout_seconds=timeout)
                return
            job.response = response
            job.rows = job.worker.validated_images(response)
            job.publish_deadline = time.monotonic() + PUBLISH_RETRY_SECONDS
        if not self._publish(job):
            return
        result = self._result(job, job.response, job.published)
        stored = copy.deepcopy(result)
        for transient in ("stale", "cached", "timing_ms"):
            stored.pop(transient, None)
        try:
            self.cache.put(job.key, [path for path, _ in job.published], stored)
        except OSError:
            self.controller._log_exception()  # the response stands; the image is simply not cached
        self._finish(job, response={"ok": True, "result": result})

    def _publish(self, job):
        """Move the verified PNGs into the owner folder; False to retry on the next tick (scanner lock)."""
        for index, row in enumerate(job.rows):
            if index < len(job.published):
                continue
            target = self.owner / ("img-%s-%s.png" % (job.key[:16], "sheet" if row["name"] == "sheet.png" else index))
            try:
                os.replace(row["path"], target)
            except PermissionError:
                if time.monotonic() <= job.publish_deadline:
                    return False
                self._unpublish(job)
                raise
            except OSError:
                self._unpublish(job)
                raise
            job.published.append((target, row))
        return True

    @staticmethod
    def _unpublish(job):
        for path, _ in job.published:
            try:
                os.unlink(path)
            except OSError:
                pass
        job.published = []

    def _result(self, job, response, files):
        controller = self.controller
        context = job.context
        doc, fence = context["doc"], context["fence"]
        render = response.get("render") or {}
        stale = True
        if controller._is_open(doc):
            state = controller.observer.state(doc)
            stale = ((controller._meta(doc).Revision, state["instance_id"], state["generation"], state["change_serial"])
                     != fence or bool(state.get("intent_dirty")))
        images = []
        drawn = render.get("images") or []
        for index, (path, verified) in enumerate(files):
            # Size, bytes and sha256 come from the verified file; cameras and overlays from the renderer.
            row = drawn[index] if index < len(drawn) and isinstance(drawn[index], dict) else {}
            images.append({"view": verified["view"], "path": str(path), "media_type": "image/png",
                           "width": verified["width"], "height": verified["height"], "bytes": verified["bytes"],
                           "sha256": verified["sha256"], "camera": row.get("camera"), "tiles": row.get("tiles"),
                           "highlights": row.get("highlights"), "section": row.get("section")})
        triangles = {info.get("index"): info for info in render.get("parts") or []}
        parts = []
        for index, row in enumerate(context["scene"]["targets"]):
            info = triangles.get(context["part_index"].get(index), {})
            parts.append({"part": row["part"], "body": row["body"], "name": row["name"],
                          "color": row["color"], "visible": row["visible"],
                          "visibility_source": row["visibility_source"], "build_status": row["build_status"],
                          "geometry": row["geometry"], "geometry_check": row["geometry_check"],
                          "result_check": row["result_check"], "solid": row["solid"],
                          "in_container": row["in_container"], "faces": row["faces"],
                          "triangles": info.get("triangles", 0)})
        highlights = []
        for index, (item, resolved) in enumerate(zip(context["settings"]["highlights"], context["matches"])):
            matches = resolved["matches"]
            source = {"selector": item["selector"]} if "selector" in item else {"input": item["input"]}
            highlights.append({"label": item["label"], "note": item["note"],
                               "color": list(highlight_color(index)), "source": source,
                               "count": len(matches), "rendered_count": sum(1 for match in matches if match["rendered"]),
                               "matches": [{key: match[key] for key in ("feature", "subelement", "entity_type", "part",
                                                                         "rendered", "reason")} for match in matches]})
        status = context["status"]
        geometry_status = {key: status[key] for key in ("build_status", "geometry", "geometry_check", "validation",
                                                         "rollback", "non_solid_parts")}
        geometry_status.update(banners=render.get("banners", status["banners"]), note=RESPONSE_NOTE)
        worker_ms = (time.perf_counter() - job.started) * 1000
        result = {"document_id": context["document_id"], "revision": fence[0], "generation": fence[2], "stale": stale,
                  "render_id": job.key[:16], "cached": False, "images": images,
                  "settings": copy.deepcopy(context["settings"]), "parts": parts,
                  "sketches": list(context["scene"]["sketch_names"]),
                  "omitted_parts": copy.deepcopy(context["scene"]["omitted"]), "highlights": highlights,
                  "geometry_status": geometry_status, "tessellation": render.get("tessellation"),
                  "timing_ms": {"owner": round(context.get("owner_ms", 0.0), 2),
                                "highlights": round(context.get("highlights_ms", 0.0), 2),
                                "worker": round(worker_ms, 2),
                                "total": round((time.perf_counter() - context.get("began", job.started)) * 1000, 2)},
                  "engine": {"FreeCAD": list(App.Version()[:4]), "OCCT": Part.OCC_VERSION, "renderer": RENDERER,
                             "renderer_version": RENDERER_VERSION, "font": render.get("font")}}
        if any(row["in_container"] for row in context["scene"]["targets"]):
            result["frame_note"] = ("Parts inside a placed container are drawn in the selector world frame; inspect's "
                                    "bbox_mm (assembly.global_shape) is container-local for nested Bodies.")
        return result

    def _finish(self, job, response=None, error=None, deterministic=False):
        if self.active is job:
            self.active = None
        self.last_worker_ms = (time.perf_counter() - job.started) * 1000
        try:
            self.controller.timings.record("render_worker", round(self.last_worker_ms, 2))
            peak = job.worker.diagnostics().get("peak_commit_mb")
            if peak is not None:
                self.last_peak_commit_mb = peak
        except Exception:
            pass
        if error is not None:
            response = _failure(error)
            # A budget overrun depends on machine load; only input-determined failures are remembered.
            if deterministic and "budget_seconds" not in error.details:
                self.cache.put_negative(job.key, copy.deepcopy(response["error"]))
        try:
            job.worker.close()
        except Exception:
            self.controller._log_exception()
        capture = self.captures.get(job.context.get("capture_key"))
        if capture is not None:
            capture["pinned"] = False
        handles, job.deferreds = job.deferreds, []
        for handle in handles:
            handle._resolve(copy.deepcopy(response))

    def _detach(self, handle):
        job = handle.job
        if handle in job.deferreds:
            job.deferreds.remove(handle)
        if not job.deferreds and self.active is job:
            self._finish(job, error=OperationError("render_cancelled", "Render cancelled"))

    def _cancel_active(self, error):
        if self.active is not None:
            self._finish(self.active, error=error)

    # ----------------------------------------------------------------- lifecycle
    def retire_document(self, instance_id):
        """The document was closed (DocumentState.slotDeletedDocument): cancel its job, drop its captures."""
        job = self.active
        if job is not None and job.context["fence"][1] == instance_id:
            self._cancel_active(OperationError("document_closed", "The document was closed during the render"))
        stale = [key for key, entry in self.captures.items() if entry["instance_id"] == instance_id]
        if job is not None and job.context["fence"][1] == instance_id and stale:
            # The cancelled child may still hold its capture files open: remove them once it exited.
            folders = [self.captures.pop(key)["folder"] for key in stale]
            complete = getattr(job.worker, "cleanup_complete", None)

            def remove():
                if complete is not None:
                    complete.wait(30)
                for folder in folders:
                    shutil.rmtree(folder, ignore_errors=True)
            threading.Thread(target=remove, name="kurtshape-render-retire", daemon=True).start()
            return
        for key in stale:
            self._drop_capture(key)

    def diagnostics(self):
        job = self.active
        return {"active": job is not None, "active_render_id": job.key[:16] if job else None,
                "waiting": len(job.deferreds) if job else 0,
                "cache_entries": len(self.cache.entries), "cache_bytes": self.cache.bytes,
                "negative_entries": self.cache.negative_entries, "captures": len(self.captures),
                "highlight_cache_entries": len(self.highlight_cache), "counters": dict(self.counters),
                "directory": str(self.owner), "last_worker_ms": self.last_worker_ms and round(self.last_worker_ms, 1),
                "last_peak_commit_mb": self.last_peak_commit_mb,
                "worker": job.worker.diagnostics() if job and hasattr(job.worker, "diagnostics") else None}

    def close(self):
        """Cancel the job, unlink images now, remove captures and the owner folder once the child exited."""
        if self.closed:
            return
        self.closed = True
        worker = self.active.worker if self.active is not None else None
        self._cancel_active(OperationError("render_cancelled", "The render service closed"))
        self.cache.clear()
        folders = [entry["folder"] for entry in self.captures.values()]
        self.captures.clear()
        owner = self.owner

        def remove():
            complete = getattr(worker, "cleanup_complete", None)
            if complete is not None:
                complete.wait(30)
            for folder in folders:
                shutil.rmtree(folder, ignore_errors=True)
            try:
                (owner / "owner.json").unlink()
            except OSError:
                pass
            try:
                owner.rmdir()
            except OSError:
                pass
        if worker is None:
            remove()
        else:
            threading.Thread(target=remove, name="kurtshape-render-cleanup", daemon=True).start()
