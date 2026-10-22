"""Session SDK: one import gives an agent a tracked KurtShape session, headless or over the bridge.

Every agent project used to rewrite the same harness: an isolated environment, a ``call``
that stamps ``document_id`` and ``expected_revision`` and keeps the returned state, part
lookup by name, a request ledger and sketch / pad / finish helpers. This module is that
harness, written once, for both transports::

    import sys; sys.path.insert(0, r"...\\kurtshape\\src")
    from kurtshape.session import Session

    with Session.headless(root=r"...\\my-scratch", project_roots=[r"...\\my-project"]) as s:
        s.call("new", name="Bracket")
        sk = s.sketch("Base", origin=(0, 0, 0))            # create_plane + create_sketch
        s.call("add_polyline", sketch=sk, body="Body", points=[[0, 0], [40, 0], [40, 20], [0, 20]], closed=True)
        s.call("pad", id="Base", profile=sk, body="Body", length=10, operation="new", name="Bracket")
        part = s.part_named("Bracket")
        edge = s.edge_at((40, 10, 10), part=part)           # a selector for fillet / chamfer
        s.call("fillet", id="Round", part=part, edges=[{"selector": edge}], radius=2)
        s.finish(part, r"...\\my-project\\out", "bracket", "Bracket", color=[0.4, 0.45, 0.5])

    s = Session.bridge(session_path=r"...\\assistant-session.json", root=r"...\\ledger")  # same API

Run headless scripts under the bundled interpreter
(``runtime\\freecad-1.1.4\\FreeCAD_1.1.4-Windows-x86_64-py311\\bin\\pythonw.exe``), output
redirected to a file. Importing this module imports neither FreeCAD nor ``kurtshape.core``:
the headless constructor imports them after it has set the environment, and the bridge
transport never imports them (it runs in any plain Python 3).

Constructors
------------
``Session.headless(root, project_roots=())``
    A private in-process ``Controller`` under ``root``. ``root`` gets ``session/`` (with
    ``settings.json``: ``workspace_layout: "portable"`` and ``project_roots`` = ``root`` plus
    ``project_roots``; KurtShape saves and exports only inside these), ``user-data``,
    ``appdata``, ``localappdata`` and ``temporary``. When FreeCAD is not imported yet
    (``isolation["mode"] == "fresh"``) the six variables ``KURTSHAPE_SESSION_DIR``,
    ``FREECAD_USER_HOME``, ``APPDATA``, ``LOCALAPPDATA``, ``TEMP`` and ``TMP`` are pointed
    into ``root`` before FreeCAD loads, and stay so for the life of the process (FreeCAD's
    profile cannot change after import). In this mode ``root\\temporary`` must be at most 104
    characters (previews save document clones under TEMP); a longer root raises
    ``IsolationError`` before anything is created. When FreeCAD is already imported
    (``"inherited"``: a test runner, or a second Session in one process) only
    ``KURTSHAPE_SESSION_DIR`` is set (and restored on ``close``). Inherited mode checks only
    the FreeCAD profile: ``FREECAD_USER_HOME`` must be set, must lie outside the live
    ``runtime\\user-data``, and must contain the profile FreeCAD actually loaded; otherwise
    ``IsolationError``. It does not check or change ``APPDATA``, ``LOCALAPPDATA``, ``TEMP`` or
    ``TMP`` (all stay the process's own, recorded in ``s.isolation["environment"]``) and does
    not enforce the 104-character TEMP limit; an inherited TEMP longer than that is recorded in
    ``s.isolation["warnings"]``. The live ``runtime`` folder, ``runtime\\user-data`` and anything
    inside it are refused as ``root`` in both modes.
``Session.bridge(session_path=None, *, root=None, wait=300.0, close_documents=False, send=None)``
    Requests go through ``tools/assistant_client.py`` ``send(request, session_path, wait=...)``
    (loaded by file path from this checkout, not copied). ``session_path`` defaults to the
    client's own default (``KURTSHAPE_SESSION_DIR`` or ``runtime``) ``assistant-session.json``.
    ``root`` holds the ledger; by default the ``sdk-ledger`` folder beside the session file.
    ``send`` replaces the client function (tests). A bridge Session closes no documents
    unless ``close_documents=True`` (then only the ones it created, without discarding).

Both constructors send ``capabilities`` (written to ``root/capabilities.json``, kept as
``s.capabilities``) and ``operation_schema`` (the envelope table, below).

``call(op, **args) -> result``
------------------------------
Builds ``{"op": op, "request_id": <uuid4>, "measure": False, **args}`` (arguments you
pass win, including ``measure``), round-trips it through JSON (tuples become lists, so
the headless Controller sees exactly what the bridge would), then stamps the envelope:

* ``document_id`` (the tracked current document) when the operation's schema requires
  one and you did not pass it;
* ``expected_revision`` (the tracked revision of that document) when the schema requires
  it and you did not pass it. The envelope comes from the server's own ``operation_schema``
  (``request.required``, computed by ``operation_schemas.envelope_requirements``): model,
  assembly, history and lifecycle operations and ``preview`` carry the revision; reads
  (``inspect``, ``check_geometry``, ``resolve_selector``, ...) and creates (``new``,
  ``open``, ``import_step``, ``recover``) do not; view operations (``render_view``,
  ``set_view``) take it optionally and are sent without it. A server without
  ``operation_schema`` falls back to ``envelope_requirements`` with the classes read from
  ``capabilities``.
* ``preview`` always carries the revision: ``core.py`` lists it in ``READ_OPS`` but
  ``Controller._preview`` rejects a missing revision with ``stale_revision``; harnesses that
  skip the revision for reads failed on it. The published schema already requires it
  (``operation_schemas.envelope_requirements`` special-cases ``preview``), so
  ``REVISION_ALWAYS`` is belt-and-braces for a server whose schema omits it.

On ``ok: true`` the result is returned (headless responses are JSON round-tripped too, so
both transports return the same shapes and a result never aliases Controller state). Every
result carrying ``document_id`` and
``revision`` updates the tracked revision of that document; a full inspection (every
document-bound mutation, ``new``/``open``/``import_step``, full ``inspect``) also becomes
``s.state`` and makes its document current. Compact results (``detail: "compact"``) update
only the revision; ``close_document`` forgets the document.

On ``ok: false`` ``OperationFailed`` is raised carrying ``op``, ``code``, ``error`` (the
error payload), ``request``, ``response`` and, through the bridge, ``reconciliation``
(``assistant_client``'s block: ``pending``, ``unknown``, ``not_executed``). The SDK never
resends after a transport failure: follow the reconciliation outcome.

``stale_revision`` recovery: when the SDK stamped the revision itself and the server
answers ``stale_revision``, the SDK re-inspects the document (a logged ``inspect``),
takes the new revision and resends the same request once with a new ``request_id``. That
is safe because a stale rejection is raised before the operation changes anything (the
revision check precedes every modelling step, and the ledger records the first id as a
completed rejection, so the resend needs a fresh id). A second ``stale_revision`` raises
``StaleRevision``. A revision you passed yourself is an assertion and is never replaced.

State and lookup
----------------
``s.state`` the last full inspection (``{}`` before the first). ``s.document_id``,
``s.revision`` the current document and its tracked revision. ``s.revisions`` maps every
document seen to its revision. Lookups refresh ``state`` with an ``inspect`` first when the
tracked revision moved past it.

``refresh(document_id=None) -> state``    full ``inspect`` of the (current) document.
``parts`` (property)                      the studio part rows (``state.studio.parts``).
``part_named(name=None) -> part id``      the studio part with that name (``None``: the first);
                                          when the document has no studio parts, the single Body
                                          whose inspection row has geometry (build status other
                                          than ``sketch_only``), as the Rev B harness did.
                                          Raises ``PartNotFound`` otherwise.
``part(name=None)``                       alias of ``part_named`` (the Rev B helper name).
``feature(id_or_name) -> row or None``    a row of ``state.features`` by id or name.
``edge_at(point, part=None, radius=None, geometry=None, tolerance=None, resolve=False)``
    ``{"kind": "closest", "point": [...], "query": {"kind": "owned_by", "part": part,
    "entity_type": "edge"}}``. Only ``geometry`` ("circle", "line", ...) and/or ``radius``
    wrap the owned_by query in a ``{"kind": "geometry", ...}`` filter (``radius`` alone
    implies ``"circle"``); ``tolerance`` is added to that filter and is ignored when neither
    is given (it never creates the filter by itself). ``part`` defaults to ``part_named()``.
    ``resolve=True`` sends ``resolve_selector`` and raises ``SelectorError`` unless exactly
    one edge matches.
``face_at(point, part=None, geometry=None, radius=None, tolerance=None, resolve=False)``
    The same for faces (``geometry`` "plane", "cylinder", ...; ``radius`` alone implies
    ``"cylinder"``).
``resolve(selector) -> matches``          ``resolve_selector`` with ``detail`` rows.

Modelling helpers (the Rev B fixture harness, same requests, so its recipes replay)
----------------------------------------------------------------------------------
``sketch(stem, origin=(0,0,0), normal=(0,0,1), x_direction=(1,0,0), body="Body")``
    ``create_plane`` id ``stem+"Plane"`` then ``create_sketch`` id ``stem+"Sketch"`` on it;
    returns the sketch id.
``circle(stem, origin, diameter, length, operation="new", part=None, name=None, body="Body")``
    A circle of ``diameter`` centred on a plane at ``origin`` (normal +Z), padded ``length``
    as feature ``stem``; ``part`` becomes ``merge_scope=[part]``. Returns
    ``part_named(name)`` for ``operation="new"``, else ``part``.
``polygon(stem, points, z, length, operation="new", part=None, name=None, body="Body")``
    A closed polyline on a plane at height ``z``; otherwise as ``circle``.
``finish(part, folder, stem, name, color) -> manifest row``
    ``set_part_appearance`` (name, colour), ``check_geometry``, ``save`` to
    ``folder/stem.FCStd``, ``export`` the part to ``folder/stem.step``, ``inspect``
    ``measure: "full"`` written to ``folder/stem-inspection.json``. ``folder`` is created and
    must be inside the project roots. Returns ``{"id": stem, "name", "path": <step>,
    "native": <FCStd>, "color", "inspection": <json>, "geometry_check": <status>}``.

Ledger and lifecycle
--------------------
``s.ledger_path`` (``root/requests.jsonl``): per attempt, a ``{"event": "sent", seq,
request, ...}`` line before the request goes out (so a crash still shows what was in
flight) and a ``{"event": "done", seq, request_id, op, ok, error_code, error_message,
document_id, revision, created_feature, elapsed_ms, attempt, retry_of, reconciliation}``
line after. ``s.log_path`` (``root/build.log``): one readable line per attempt. Both are
appended, so several sessions can share a root; ``sdk_session`` tells them apart.

``close()`` (also the context-manager exit): headless, closes every open document of the
private Controller with ``discard: true`` (saved files are untouched; a ``close_document``
done record carries ``discarded_unsaved_changes`` and ``recovery_manifest``), then
``Controller.close()``, then restores ``KURTSHAPE_SESSION_DIR`` in inherited mode. Bridge:
see ``close_documents``. Calling ``call`` after ``close`` raises ``SessionError``. When the
``with`` body raised, a failure inside ``close()`` is logged and added as a note to the
original exception, which propagates unchanged.

Exceptions: ``SessionError`` (base), ``IsolationError``, ``OperationFailed``,
``StaleRevision(OperationFailed)``, ``PartNotFound(SessionError, LookupError)``,
``SelectorError``.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import uuid

CHECKOUT = Path(__file__).resolve().parents[2]
LIVE_RUNTIME = CHECKOUT / "runtime"
LIVE_USER_DATA = LIVE_RUNTIME / "user-data"
BUNDLED_BIN = LIVE_RUNTIME / "freecad-1.1.4" / "FreeCAD_1.1.4-Windows-x86_64-py311" / "bin"
ASSISTANT_CLIENT = CHECKOUT / "tools" / "assistant_client.py"
TEMP_PATH_LIMIT = 104
# Environment variable -> folder under the session root. Set before FreeCAD is imported.
LAYOUT = {"KURTSHAPE_SESSION_DIR": "session", "FREECAD_USER_HOME": "user-data", "APPDATA": "appdata",
          "LOCALAPPDATA": "localappdata", "TEMP": "temporary", "TMP": "temporary"}
ISOLATION_VARIABLES = tuple(LAYOUT)
# Controller.CREATE_OPS, for the envelope fallback only (servers without operation_schema).
CREATE_OPS = frozenset({"new", "open", "recover", "import_step"})
# Operations that always carry expected_revision whatever the class lists say (see call()). The published
# schema already requires it for preview (operation_schemas.envelope_requirements); this is belt-and-braces
# for a server whose schema omits it.
REVISION_ALWAYS = frozenset({"preview"})


class SessionError(RuntimeError):
    """Base class of every error this module raises."""


class IsolationError(SessionError):
    """The requested root or the loaded FreeCAD profile is not a private, isolated one."""


class OperationFailed(SessionError):
    """The server answered ``ok: false``; carries the error payload and the request."""

    def __init__(self, request, response, attempts=1):
        self.request = request
        self.response = response
        self.op = request.get("op")
        self.error = (response or {}).get("error") or {}
        self.code = self.error.get("code")
        self.reconciliation = (response or {}).get("reconciliation")
        self.attempts = attempts
        details = {key: value for key, value in self.error.items() if key not in ("code", "message")}
        text = f"{self.op} failed: {self.code}: {self.error.get('message', '')}"
        if details:
            text += " " + json.dumps(details, default=str)[:3000]
        if self.reconciliation:
            text += " reconciliation " + json.dumps(self.reconciliation, default=str)[:500]
        super().__init__(text)


class StaleRevision(OperationFailed):
    """``stale_revision`` again after one re-inspect and resend."""


class PartNotFound(SessionError, LookupError):
    """No studio part (or single solid Body) matches the lookup."""


class SelectorError(SessionError):
    """A resolved selector did not match exactly one entity."""


_CLIENT = None


def _load_assistant_client():
    """tools/assistant_client.py of this checkout, loaded by file path (once)."""
    global _CLIENT
    if _CLIENT is None:
        spec = importlib.util.spec_from_file_location("kurtshape_session_assistant_client", ASSISTANT_CLIENT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _CLIENT = module
    return _CLIENT


def _utc():
    now = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)) + f".{int(now * 1000) % 1000:03d}Z"


def _json_default(value):
    if isinstance(value, os.PathLike):
        return os.fspath(value)
    raise TypeError(f"Request values must be JSON data (or paths); got {type(value).__name__}")


def _inside(path, folder):
    return path == folder or path.is_relative_to(folder)


def _refuse_live(root):
    if root == LIVE_RUNTIME or _inside(root, LIVE_USER_DATA):
        raise IsolationError(f"Session root {root} is the live KurtShape runtime or profile; choose a private folder "
                             r"(for example runtime\bench\<name>)")


def _prepare_headless(root, project_roots):
    """Validate, create the layout, write settings.json and set the environment.

    Returns ``(root, isolation info, variables to restore on close)``.
    """
    root = Path(root).resolve()
    _refuse_live(root)
    grants = [root]
    for raw in project_roots or ():
        grant = Path(raw)
        if not grant.is_absolute():
            raise IsolationError(f"project_roots entries must be absolute paths: {raw!r}")
        grants.append(grant.resolve())
    loaded = "FreeCAD" in sys.modules or "kurtshape.core" in sys.modules
    layout = {name: root / child for name, child in LAYOUT.items()}
    if not loaded and len(str(layout["TEMP"])) > TEMP_PATH_LIMIT:
        raise IsolationError(f"TEMP would be {layout['TEMP']} ({len(str(layout['TEMP']))} characters); the limit is "
                             f"{TEMP_PATH_LIMIT} because previews save document clones under TEMP. Choose a shorter root.")
    warnings = []
    if loaded:
        import FreeCAD
        import tempfile
        actual = Path(FreeCAD.getUserAppDataDir()).resolve()
        home = os.environ.get("FREECAD_USER_HOME")
        if (not home or _inside(Path(home).resolve(), LIVE_USER_DATA) or _inside(actual, LIVE_USER_DATA)
                or not _inside(actual, Path(home).resolve())):
            raise IsolationError(f"FreeCAD is already imported with profile {actual} (FREECAD_USER_HOME={home!r}); "
                                 "create the Session before importing FreeCAD (or run inside an isolated environment "
                                 "with FREECAD_USER_HOME set outside the live runtime\\user-data)")
        temp = tempfile.gettempdir()
        if len(temp) > TEMP_PATH_LIMIT:
            warnings.append(f"inherited TEMP {temp} is {len(temp)} characters, over the {TEMP_PATH_LIMIT}-character "
                            "limit for preview clones; it was not changed")
        layout["KURTSHAPE_SESSION_DIR"].mkdir(parents=True, exist_ok=True)
    else:
        for folder in set(layout.values()):
            folder.mkdir(parents=True, exist_ok=True)
    unique = list(dict.fromkeys(str(grant) for grant in grants))
    (layout["KURTSHAPE_SESSION_DIR"] / "settings.json").write_text(
        json.dumps({"workspace_layout": "portable", "project_roots": unique}, indent=2), encoding="utf-8")
    previous = {name: os.environ.get(name) for name in ISOLATION_VARIABLES}
    if loaded:
        os.environ["KURTSHAPE_SESSION_DIR"] = str(layout["KURTSHAPE_SESSION_DIR"])
        restore = {"KURTSHAPE_SESSION_DIR": previous["KURTSHAPE_SESSION_DIR"]}
    else:
        for name, folder in layout.items():
            os.environ[name] = str(folder)
        import tempfile
        tempfile.tempdir = None  # gettempdir() caches; recompute it from the new TEMP
        restore = {}
        if importlib.util.find_spec("FreeCAD") is None and BUNDLED_BIN.is_dir():
            sys.path.append(str(BUNDLED_BIN))
        import FreeCAD
        actual = Path(FreeCAD.getUserAppDataDir()).resolve()
        if not _inside(actual, layout["FREECAD_USER_HOME"]):
            raise IsolationError(f"FreeCAD loaded profile {actual}, not {layout['FREECAD_USER_HOME']}")
    return root, {"mode": "inherited" if loaded else "fresh", "root": str(root), "project_roots": unique,
                  "freecad_user_data": str(actual), "warnings": warnings,
                  "environment": {name: os.environ.get(name) for name in ISOLATION_VARIABLES}}, restore


class Session:
    """A tracked KurtShape session; build one with ``Session.headless`` or ``Session.bridge``."""

    def __init__(self, transport, send, root, *, controller=None, isolation=None, restore=None,
                 close_documents=False):
        self.transport = transport
        self._send = send
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.controller = controller
        self.isolation = isolation or {}
        self._restore = restore or {}
        self._close_documents = close_documents
        self.session_path = None
        self.ledger_path = self.root / "requests.jsonl"
        self.log_path = self.root / "build.log"
        self.sdk_session = str(uuid.uuid4())
        self.state = {}
        self.document_id = None
        self.revisions = {}
        self.created = []
        self.closed = False
        self._seq = 0
        self._envelopes = None
        self._classes = None
        self.capabilities = self.call("capabilities")
        (self.root / "capabilities.json").write_text(json.dumps(self.capabilities, indent=2, default=str),
                                                     encoding="utf-8")
        self._load_envelopes()

    # -- constructors -------------------------------------------------------------------------

    @classmethod
    def headless(cls, root, project_roots=()):
        """An isolated in-process Controller under ``root`` (see the module docstring)."""
        root, isolation, restore = _prepare_headless(root, project_roots)
        from .core import Controller
        controller = Controller()

        def transport(request):
            # JSON copies, as the bridge returns: identical shapes, and no aliasing of Controller-owned objects.
            return json.loads(json.dumps(controller.dispatch(request)))
        try:
            return cls("headless", transport, root, controller=controller, isolation=isolation, restore=restore)
        except BaseException:
            controller.close()
            for name, value in restore.items():
                _set_env(name, value)
            raise

    @classmethod
    def bridge(cls, session_path=None, *, root=None, wait=300.0, close_documents=False, send=None):
        """Requests through ``tools/assistant_client.py`` ``send`` (see the module docstring)."""
        if send is None:
            client = _load_assistant_client()
            send = client.send
            if session_path is None:
                session_path = client.default_session_path()
        session_path = Path(session_path).resolve() if session_path is not None else None
        if root is None:
            if session_path is None:
                raise SessionError("Session.bridge needs root= when no session_path is given")
            root = session_path.parent / "sdk-ledger"

        def transport(request):
            return send(request, session_path, wait=wait)
        session = cls("bridge", transport, root, close_documents=close_documents)
        session.session_path = session_path
        return session

    # -- envelope -----------------------------------------------------------------------------

    def _load_envelopes(self):
        try:
            schema = self.call("operation_schema")
        except OperationFailed as exc:
            if exc.code != "unsupported_operation":
                raise
            from . import operation_schemas
            read = frozenset(self.capabilities.get("read_operations") or ())
            view = frozenset(self.capabilities.get("non_mutating_operations") or ()) - read
            self._classes = {"read": read, "create": CREATE_OPS, "view": view,
                             "documentless": operation_schemas.DOCUMENTLESS_OPS}
            self._envelopes = {}
            return
        self._envelopes = {op: tuple(body["request"]["required"]) for op, body in schema["operations"].items()}

    def envelope(self, op):
        """``(document_id required, expected_revision required)`` for ``op`` as this session stamps it."""
        if self._envelopes is None:  # the two startup reads, before the table exists
            return False, False
        if op in self._envelopes:
            required = self._envelopes[op]
            return "document_id" in required, "expected_revision" in required or op in REVISION_ALWAYS
        if self._classes is not None:
            from . import operation_schemas
            document, revision, _ = operation_schemas.envelope_requirements(op, self._classes)
            return document, revision or op in REVISION_ALWAYS
        # Not in the server's schema: it will reject the operation; send what we know.
        return self.document_id is not None, False

    # -- call ---------------------------------------------------------------------------------

    @property
    def revision(self):
        return self.revisions.get(self.document_id)

    def call(self, op, **args):
        """Send one operation with the stamped envelope; return its result or raise (module docstring)."""
        if self.closed:
            raise SessionError("This session is closed")
        request = {"op": op, "request_id": str(uuid.uuid4()), "measure": False}
        request.update(args)
        request = json.loads(json.dumps(request, default=_json_default))
        needs_document, needs_revision = self.envelope(op)
        if needs_document and "document_id" not in request and self.document_id is not None:
            request["document_id"] = self.document_id
        stamped = False
        if needs_revision and "expected_revision" not in request:
            revision = self.revisions.get(request.get("document_id"))
            if revision is not None:
                request["expected_revision"] = revision
                stamped = True
        response = self._attempt(request, attempt=1)
        if not response.get("ok") and stamped and (response.get("error") or {}).get("code") == "stale_revision":
            # A stale rejection is raised before anything changes: re-inspect and resend once, new request_id.
            self.refresh(request["document_id"])
            retry = dict(request, request_id=str(uuid.uuid4()), expected_revision=self.revisions[request["document_id"]])
            response = self._attempt(retry, attempt=2, retry_of=request["request_id"])
            if not response.get("ok"):
                error = StaleRevision if (response.get("error") or {}).get("code") == "stale_revision" else OperationFailed
                raise error(retry, response, attempts=2)
            request = retry
        if not response.get("ok"):
            raise OperationFailed(request, response)
        result = response.get("result")
        result = result if isinstance(result, dict) else {}
        self._absorb(op, result)
        return result

    def _attempt(self, request, attempt, retry_of=None):
        self._seq += 1
        seq = self._seq
        self._ledger({"event": "sent", "seq": seq, "utc": _utc(), "sdk_session": self.sdk_session,
                      "transport": self.transport, "attempt": attempt, "retry_of": retry_of, "request": request})
        began = time.perf_counter()
        try:
            response = self._send(dict(request))
        except Exception as exc:
            response = {"ok": False, "error": {"code": "transport_exception", "message": repr(exc)}}
            self._done(seq, request, response, began, attempt, retry_of)
            raise
        if not isinstance(response, dict):
            response = {"ok": False, "error": {"code": "transport_exception", "message": "response is not a dict"}}
        self._done(seq, request, response, began, attempt, retry_of)
        return response

    def _done(self, seq, request, response, began, attempt, retry_of):
        elapsed = round((time.perf_counter() - began) * 1000, 1)
        result = response.get("result") if isinstance(response.get("result"), dict) else {}
        error = response.get("error") or {}
        reconciliation = response.get("reconciliation")
        summary = {"event": "done", "seq": seq, "utc": _utc(), "sdk_session": self.sdk_session,
                   "request_id": request.get("request_id"), "op": request.get("op"), "ok": bool(response.get("ok")),
                   "error_code": error.get("code"), "error_message": error.get("message"),
                   "document_id": result.get("document_id", request.get("document_id")),
                   "revision": result.get("revision"), "created_feature": result.get("created_feature"),
                   "elapsed_ms": elapsed, "attempt": attempt, "retry_of": retry_of,
                   "reconciliation": (reconciliation or {}).get("outcome")}
        closed = result.get("closed")
        if request.get("op") == "close_document" and isinstance(closed, dict):
            summary.update(document_id=closed.get("document_id"), revision=closed.get("revision"),
                           discarded_unsaved_changes=closed.get("discarded_unsaved_changes"),
                           recovery_manifest=closed.get("recovery_manifest"))
        self._ledger(summary)
        label = next((str(request[key]) for key in ("id", "path", "sketch", "feature", "part", "name")
                      if request.get(key) is not None), "")
        if response.get("ok"):
            outcome = "OK" + (f" rev {summary['revision'][:8]}" if summary["revision"] else "")
            if summary["created_feature"]:
                outcome += f" created {summary['created_feature']}"
        else:
            outcome = f"FAIL {error.get('code')}: {str(error.get('message', ''))[:300]}"
        retry = f" (retry of {retry_of[:8]})" if retry_of else ""
        self._log(f"{summary['utc']} {seq:05d} {request.get('op')} {label} {elapsed:.0f}ms {outcome}{retry}")

    def _ledger(self, record):
        with self.ledger_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, default=str) + "\n")

    def _log(self, line):
        with self.log_path.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")

    def _absorb(self, op, result):
        if op == "close_document":
            closed = (result.get("closed") or {}).get("document_id")
            self.revisions.pop(closed, None)
            if closed == self.document_id:
                self.document_id, self.state = None, {}
            return
        document, revision = result.get("document_id"), result.get("revision")
        if not isinstance(document, str) or not isinstance(revision, str):
            return
        self.revisions[document] = revision
        if op in CREATE_OPS and document not in self.created:
            self.created.append(document)
        if result.get("detail") != "compact" and "features" in result:
            self.state = result
            self.document_id = document
        elif self.document_id is None:
            self.document_id = document

    # -- state and lookup ---------------------------------------------------------------------

    def refresh(self, document_id=None):
        """Full ``inspect`` of ``document_id`` (default: the current document); returns ``state``."""
        document = document_id or self.document_id
        if document is None:
            raise SessionError("No document: create or open one first")
        self.call("inspect", document_id=document)
        return self.state

    def _current(self):
        if self.state and self.revisions.get(self.state.get("document_id")) != self.state.get("revision"):
            self.refresh(self.state["document_id"])
        return self.state

    @property
    def parts(self):
        """The studio part rows of the current document (``state.studio.parts``)."""
        return list(((self._current().get("studio") or {}).get("parts")) or [])

    def part_named(self, name=None):
        """The id of the studio part called ``name`` (``None``: the first part); see the module docstring."""
        state = self._current()
        parts = list(((state.get("studio") or {}).get("parts")) or [])
        if not parts:
            bodies = [row["id"] for row in state.get("bodies") or []
                      if row.get("type") == "PartDesign::Body" and row.get("build_status") != "sketch_only"]
            if len(bodies) == 1:
                return bodies[0]
            raise PartNotFound(f"No studio parts and {len(bodies)} Bodies with geometry; cannot pick {name!r}")
        if name is None:
            return parts[0]["id"]
        for part in parts:
            if part.get("name") == name:
                return part["id"]
        raise PartNotFound(f"No part named {name!r}; parts: {[part.get('name') for part in parts]}")

    part = part_named

    def feature(self, id_or_name):
        """The ``state.features`` row whose id or name is ``id_or_name``, or ``None``."""
        for row in self._current().get("features") or []:
            if row.get("id") == id_or_name or row.get("name") == id_or_name:
                return row
        return None

    def resolve(self, selector):
        """``resolve_selector``: the matching entity rows."""
        return self.call("resolve_selector", selector=selector)["matches"]

    def _closest(self, entity_type, point, part, geometry, radius, tolerance, resolve):
        query = {"kind": "owned_by", "part": part if part is not None else self.part_named(), "entity_type": entity_type}
        if geometry is not None or radius is not None:
            # A radius filter without a named geometry means a circle edge or a cylinder face.
            # tolerance only refines this filter; on its own it adds nothing.
            query = {"kind": "geometry", "geometry": geometry or ("circle" if entity_type == "edge" else "cylinder"),
                     "query": query}
            if radius is not None:
                query["radius"] = radius
            if tolerance is not None:
                query["tolerance"] = tolerance
        selector = {"kind": "closest", "point": list(point), "query": query}
        if resolve:
            matches = self.resolve(selector)
            if len(matches) != 1:
                raise SelectorError(f"{entity_type} selector matched {len(matches)} entities: "
                                    + json.dumps(matches, default=str)[:1500])
        return selector

    def edge_at(self, point, part=None, radius=None, geometry=None, tolerance=None, resolve=False):
        """A ``closest`` edge selector near ``point`` on ``part``; see the module docstring."""
        return self._closest("edge", point, part, geometry, radius, tolerance, resolve)

    def face_at(self, point, part=None, geometry=None, radius=None, tolerance=None, resolve=False):
        """A ``closest`` face selector near ``point`` on ``part`` (``radius`` alone implies a cylinder)."""
        return self._closest("face", point, part, geometry, radius, tolerance, resolve)

    # -- modelling helpers (Rev B fixture harness semantics) ----------------------------------

    def sketch(self, stem, origin=(0, 0, 0), normal=(0, 0, 1), x_direction=(1, 0, 0), body="Body"):
        """``create_plane`` ``stem+"Plane"`` and ``create_sketch`` ``stem+"Sketch"`` on it; returns the sketch id."""
        self.call("create_plane", id=stem + "Plane", body=body, origin=list(origin), normal=list(normal),
                  x_direction=list(x_direction))
        self.call("create_sketch", id=stem + "Sketch", body=body, support={"feature": stem + "Plane"})
        return stem + "Sketch"

    def _pad(self, stem, sketch, length, operation, part, name, body):
        args = dict(id=stem, profile=sketch, length=length, operation=operation, body=body)
        if part:
            args["merge_scope"] = [part]
        if name:
            args["name"] = name
        self.call("pad", **args)
        return self.part_named(name) if operation == "new" else part

    def circle(self, stem, origin, diameter, length, operation="new", part=None, name=None, body="Body"):
        """Pad a circle of ``diameter`` centred at ``origin`` by ``length``; returns the part id."""
        sketch = self.sketch(stem, origin, body=body)
        self.call("add_circle", sketch=sketch, body=body, x=0, y=0, diameter=diameter)
        return self._pad(stem, sketch, length, operation, part, name, body)

    def polygon(self, stem, points, z, length, operation="new", part=None, name=None, body="Body"):
        """Pad a closed polyline through ``points`` on a plane at height ``z``; returns the part id."""
        sketch = self.sketch(stem, (0, 0, z), body=body)
        self.call("add_polyline", sketch=sketch, body=body, points=points, closed=True)
        return self._pad(stem, sketch, length, operation, part, name, body)

    def finish(self, part, folder, stem, name, color):
        """Appearance, geometry check, FCStd, STEP and inspection JSON in ``folder``; returns the manifest row."""
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        self.call("set_part_appearance", part=part, name=name, color=color)
        check = self.call("check_geometry")
        native, step = folder / (stem + ".FCStd"), folder / (stem + ".step")
        self.call("save", path=str(native))
        self.call("export", body=part, path=str(step))
        inspection = self.call("inspect", measure="full")
        report = folder / (stem + "-inspection.json")
        report.write_text(json.dumps(inspection, indent=2, default=str), encoding="utf-8")
        return {"id": stem, "name": name, "path": str(step), "native": str(native), "color": color,
                "inspection": str(report), "geometry_check": (check.get("geometry_check_report") or {}).get("status")}

    # -- lifecycle ----------------------------------------------------------------------------

    def close(self):
        """Close documents (headless: all, discarded; bridge: see close_documents), then the Controller."""
        if self.closed:
            return
        try:
            if self.controller is not None:
                rows = self.call("list_documents", detail="compact")["documents"]
                targets = [(row["document_id"], row["revision"], True) for row in rows]
            elif self._close_documents:
                targets = [(document, self.revisions[document], False)
                           for document in self.created if document in self.revisions]
            else:
                targets = []
            for document, revision, discard in targets:
                try:
                    self.call("close_document", document_id=document, expected_revision=revision, discard=discard)
                except OperationFailed as exc:
                    self._log(f"{_utc()} close {document} kept open: {exc.code}")
        finally:
            self.closed = True
            try:
                if self.controller is not None:
                    self.controller.close()
            finally:
                for name, value in self._restore.items():
                    _set_env(name, value)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc is None:
            self.close()
            return False
        # The with-body already failed: a close() failure must not replace that exception.
        try:
            self.close()
        except Exception as close_error:
            try:
                self._log(f"{_utc()} close failed after an exception in the with-body: {close_error!r}")
            except Exception:
                pass
            exc.add_note(f"Session.close() also failed: {close_error!r}")
        return False


def _set_env(name, value):
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
