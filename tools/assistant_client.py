"""Same local operations for Codex/Claude/manual tooling; stdlib, no cloud access.

python -B tools/assistant_client.py --request-file examples/inspect-request.json
python -B tools/assistant_client.py --json '{"op":"list_documents"}'
python -B tools/assistant_client.py --status <request_id>
python -B tools/assistant_client.py --reconcile --request-id <request_id>
python -B tools/assistant_client.py --build-check

Contract 3.2 (F5 §6.3): ``send`` never raises for transport errors. A mutation keeps its
``request_id`` for life; when the bridge cannot say whether it ran (timeout, reset,
``outcome_unknown``) the client polls the canonical ``request_status`` at the URL and token
it started with and returns the stored response, or a ``reconciliation`` block saying
``pending`` (reconcile later with the same id) or ``unknown`` (inspect before acting; never
resend with a new id). ``not_executed`` is reported only when the request provably never
started: a queued request that timed out, a full queue, a ledger ``cancelled`` or a refused
first connect.

Exit codes, by the caller's next action: 0 ok or completed; 1 rejected or failed; 2 pending
(reconcile later with the same id); 3 unknown (inspect before acting); 4 safe to retry (a mutation
with a new request_id, after inspecting); 64 usage error (nothing was sent). ``--build-check``:
0 current, 1 otherwise, 3 no session.
"""
import argparse
import http.client
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
# A conservative subset of Controller.READ_OPS for session files that predate read_operations.
READ_OPS_FALLBACK = frozenset({"inspect", "list_documents", "capabilities", "request_status", "preview", "diagnostics",
                               "assembly_candidates", "resolve_selector", "check_geometry", "orphan_helpers"})
REQUEST_SIZE_LIMIT = 65536
UNREACHABLE_AFTER = 5.0
INITIAL_TIMEOUT = 35.0
POLL_TIMEOUT = 10.0
CLI_WAIT = 75.0
EXIT = {"ok": 0, "completed": 0, "rejected": 1, "failed": 1, "pending": 2, "unknown": 3, "not_executed": 4}
USAGE = 64


def default_session_path():
    return Path(os.environ.get("KURTSHAPE_SESSION_DIR", str(ROOT / "runtime"))) / "assistant-session.json"


def _post(url, token, body, timeout):
    """(kind, http status, payload): kind is json, http (non-JSON reply), refused or transport."""
    message = urllib.request.Request(url, data=body, headers={"Authorization": "Bearer " + token,
                                                              "Content-Type": "application/json"}, method="POST")
    # Loopback never uses system proxies or external services.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(message, timeout=max(0.2, timeout)) as response:
            payload = json.loads(response.read())
            return ("json", 200, payload) if isinstance(payload, dict) else ("transport", 200, "reply is not a JSON object")
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read())
        except (ValueError, OSError, http.client.HTTPException):
            return "http", exc.code, None
        return ("json", exc.code, payload) if isinstance(payload, dict) else ("http", exc.code, None)
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ConnectionRefusedError):
            return "refused", None, None
        return "transport", None, repr(exc.reason)
    except ConnectionRefusedError:
        return "refused", None, None
    except (ValueError, OSError, http.client.HTTPException) as exc:
        # Not JSON, a socket timeout, a reset, a remote disconnect, an incomplete or malformed reply.
        return "transport", None, repr(exc)


def outcome_of(result):
    """ok, rejected, completed, failed, pending, unknown or not_executed."""
    block = result.get("reconciliation") if isinstance(result, dict) else None
    if block:
        return block["outcome"]
    return "ok" if isinstance(result, dict) and result.get("ok") else "rejected"


def exit_code(result):
    block = result.get("reconciliation") if isinstance(result, dict) else None
    if block and block.get("retry_safe"):
        return EXIT["not_executed"]
    return EXIT[outcome_of(result)]


def _block(result, outcome, rid, sid, **extra):
    return dict(result, reconciliation=dict({"outcome": outcome, "request_id": rid, "session_id": sid}, **extra))


def _unknown(rid, sid, reason, **extra):
    return _block({"ok": False, "error": {"code": "outcome_unknown", "request_id": rid,
                                          "message": "Outcome cannot be determined; inspect before acting; "
                                                     "never resend with a new request_id"}},
                  "unknown", rid, sid, reason=reason, **extra)


def _session(session_path):
    path = Path(session_path) if session_path else default_session_path()
    session = json.loads(path.read_text(encoding="utf-8"))
    return path, session


def send(request, session_path=None, *, wait=300.0, reconcile=True, resend=True, unreachable_after=UNREACHABLE_AFTER,
         _session_data=None):
    """Send one request; returns the response dict, with a ``reconciliation`` block when one was needed.

    The session file is read once. Mutations get a ``request_id`` (this mutates ``request``, as before).
    ``wait`` is one budget from the start; every HTTP timeout and sleep is clamped to what remains.
    """
    started = time.monotonic()
    deadline = started + wait
    session = _session_data if _session_data is not None else _session(session_path)[1]
    url, token, sid = session["url"], session["token"], session.get("session_id")
    read_ops = frozenset(session.get("read_operations") or READ_OPS_FALLBACK)
    limit = session.get("request_size_limit") or REQUEST_SIZE_LIMIT
    op = request.get("op")
    mutation = op not in read_ops
    if mutation:
        request.setdefault("request_id", str(uuid.uuid4()))
    rid = request.get("request_id")
    body = json.dumps(request).encode()
    if len(body) > limit:
        # The bridge answers 413 without reading the body; on Windows the client then sees a
        # connection reset while still writing. Refuse locally: nothing is sent.
        return {"ok": False, "error": {"code": "request_too_large", "bytes": len(body), "limit": limit,
                                       "message": "Request body exceeds the bridge limit; nothing was sent"}}
    # Leave room for one status poll after the first POST, so a short budget can still learn "pending";
    # but give the first POST at least half a short budget (up to 2 s), so a quick operation is answered
    # directly instead of being abandoned after 0.2 s (Fable review R2). A wait under about 5 s still means
    # "send, then reconcile": an operation slower than half the budget is left to request_status.
    remaining = deadline - time.monotonic()
    first = max(min(remaining / 2, 2.0), remaining - min(POLL_TIMEOUT, 2.0))
    kind, status, payload = _post(url, token, body, min(INITIAL_TIMEOUT, max(0.2, first)))
    if kind == "refused":
        return _block({"ok": False, "error": {"code": "unreachable",
                                              "message": "No KurtShape bridge is listening; nothing was sent"}},
                      "not_executed", rid, sid, reason="unreachable")
    if kind == "json":
        error = (payload or {}).get("error") or {}
        code = error.get("code")
        if status == 200 and payload.get("ok"):
            return payload
        if code in {"timeout", "queue_full"}:
            return _block(payload, "not_executed", rid, sid, reason=code)
        if code == "request_expired":
            return _unknown(rid, sid, "expired")
        if code not in {"outcome_unknown", "request_pending"} and not (status and status >= 500 and not code):
            return payload  # rejected: invalid_request (400), invalid_argument, stale_revision, request_id_reused, ...
    elif kind == "http" and status in {403, 413}:
        code = "forbidden" if status == 403 else "request_too_large"
        return {"ok": False, "error": {"code": code, "message": f"HTTP {status} before the request was registered"}}
    if not mutation:
        return _block({"ok": False, "error": {"code": "outcome_unknown", "message": str(payload)[:500]}},
                      "unknown", rid, sid, reason=kind, retry_safe=True)
    result = (_unknown(rid, sid, "not_reconciled") if not reconcile
              else _reconcile(url, token, sid, body, rid, deadline, resend, unreachable_after, started))
    if outcome_of(result) == "unknown" and op in frozenset(session.get("non_mutating_operations") or ()):
        # A tracked view op (render_view) changes no model: whatever happened, running it again is safe.
        result["reconciliation"]["retry_safe"] = True
    return result


def reconcile_request(request_id, session_path=None, *, wait=300.0, body=None, session_id=None,
                      unreachable_after=UNREACHABLE_AFTER):
    """Poll ``request_status`` for an id sent earlier (``--reconcile``).

    ``body`` is re-sent (once, byte-identical) only when ``session_id`` names the session the request was
    first sent to and the bridge still runs that session; a restarted app gives ``unknown``/``session_changed``.
    """
    started = time.monotonic()
    _, session = _session(session_path)
    sid = session.get("session_id")
    if session_id is not None and session_id != sid:
        return _unknown(request_id, session_id, "session_changed", polls=0, resent=False, waited_s=0.0)
    encoded = json.dumps(body).encode() if body is not None else None
    result = _reconcile(session["url"], session["token"], sid, encoded, request_id, started + wait,
                        encoded is not None and session_id is not None, unreachable_after, started)
    if (outcome_of(result) == "unknown" and isinstance(body, dict)
            and body.get("op") in frozenset(session.get("non_mutating_operations") or ())):
        result["reconciliation"]["retry_safe"] = True
    return result


def status(request_id, session_path=None, timeout=POLL_TIMEOUT):
    """One canonical status read (exactly op and request_id, the bridge's queue-bypassing shape)."""
    _, session = _session(session_path)
    kind, code, payload = _post(session["url"], session["token"],
                                json.dumps({"op": "request_status", "request_id": request_id}).encode(), timeout)
    if kind == "json":
        return payload
    return _block({"ok": False, "error": {"code": "outcome_unknown", "message": str(payload)[:500]}},
                  "unknown", request_id, session.get("session_id"), reason=kind, retry_safe=True)


def _reconcile(url, token, sid, body, rid, deadline, resend, unreachable_after, started):
    status_body = json.dumps({"op": "request_status", "request_id": rid}).encode()
    delay, polls, resent, last = 0.25, 0, False, None
    not_recorded_since = refused_since = None
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        kind, http_status, payload = _post(url, token, status_body, min(POLL_TIMEOUT, remaining))
        polls += 1
        now = time.monotonic()
        extra = {"polls": polls, "resent": resent, "waited_s": round(now - started, 2)}
        if kind == "refused":
            refused_since = refused_since or now
            if now - refused_since >= unreachable_after:
                return _unknown(rid, sid, "unreachable", **extra)
        else:
            refused_since = None
        if http_status == 403:
            return _unknown(rid, sid, "session_ended", **extra)
        result = payload.get("result") if kind == "json" and http_status == 200 and payload.get("ok") else None
        if isinstance(result, dict) and "status" in result:
            if result.get("session_id") != sid:
                return _unknown(rid, sid, "session_changed", **extra)
            last = result["status"]
            if last in {"completed", "failed", "cancelled"}:
                outcome = {"completed": "completed", "failed": "failed", "cancelled": "not_executed"}[last]
                return _block(result.get("response") or {"ok": False, "error": {"code": "cancelled"}},
                              outcome, rid, sid, status=last, **extra)
            if last == "expired":
                return _unknown(rid, sid, "expired", **extra)
            if last == "not_recorded":
                not_recorded_since = not_recorded_since or now
                if now - not_recorded_since >= 1.0:
                    if not resend or resent or body is None:
                        return _unknown(rid, sid, "not_recorded", **extra)
                    resent = True
                    # The same session never saw it: send the byte-identical body once.
                    reply_kind, reply_status, reply = _post(url, token, body,
                                                            min(INITIAL_TIMEOUT, max(0.2, deadline - time.monotonic())))
                    code = ((reply or {}).get("error") or {}).get("code") if reply_kind == "json" else None
                    if reply_kind == "json" and (reply_status == 200 and reply.get("ok") or code and code not in {
                            "outcome_unknown", "request_pending", "timeout", "queue_full", "request_expired"}):
                        extra = {"polls": polls, "resent": True, "waited_s": round(time.monotonic() - started, 2)}
                        return _block(reply, "completed" if reply.get("ok") else "failed", rid, sid, **extra)
                    not_recorded_since = None
                    continue
            else:
                not_recorded_since = None
        time.sleep(max(0.0, min(delay, deadline - time.monotonic())))
        delay = min(2.0, delay * 2)
    extra = {"polls": polls, "resent": resent, "waited_s": round(time.monotonic() - started, 2), "status": last}
    if last in {"queued", "started"}:
        return _block({"ok": False, "error": {"code": "outcome_pending", "request_id": rid,
                                              "message": "Still running; reconcile later with the same request_id"}},
                      "pending", rid, sid, **extra)
    return _unknown(rid, sid, "deadline", **extra)


def build_check(session_path=None, wait=10.0):
    """{verdict: current|stale|different_tree|unknown, running, checkout}; loads build_identity by file path."""
    spec = importlib.util.spec_from_file_location("_kurtshape_build_identity",
                                                  ROOT / "src" / "kurtshape" / "build_identity.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    response = send({"op": "capabilities"}, session_path, wait=wait)
    running = (response.get("result") or {}).get("build") if response.get("ok") else None
    verdict = module.build_verdict(running, ROOT / "src" / "kurtshape")
    if not response.get("ok"):
        verdict["error"] = response.get("error")
    return verdict


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        """Usage errors exit 64: 2 means "pending" to callers (assistant.ps1)."""
        self.print_usage(sys.stderr)
        print(json.dumps({"ok": False, "error": {"code": "usage", "message": message}}), file=sys.stderr)
        raise SystemExit(USAGE)


def main(argv=None):
    parser = _Parser(description=__doc__.split("\n\n")[0])
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument("--json")
    choice.add_argument("--request-file", type=Path)
    choice.add_argument("--status", metavar="ID")
    choice.add_argument("--build-check", action="store_true")
    parser.add_argument("--session", type=Path, help="Session file for an explicitly selected application instance")
    parser.add_argument("--request-id")
    parser.add_argument("--wait", type=float, default=CLI_WAIT, help="Total budget in seconds (default 75)")
    parser.add_argument("--no-reconcile", action="store_true")
    parser.add_argument("--reconcile", action="store_true", help="Poll an earlier --request-id instead of sending")
    parser.add_argument("--session-id", help="With --reconcile: the session the request was first sent to (printed on "
                                             "stderr when it was sent); needed before a body is re-sent")
    args = parser.parse_args(argv)
    session_path = args.session or default_session_path()
    try:
        session = _session(session_path)[1] if Path(session_path).is_file() else None
    except (OSError, ValueError) as exc:
        parser.error("unreadable session file " + str(session_path) + ": " + str(exc))
    if session is None:
        print(json.dumps({"ok": False, "error": {"code": "no_session", "message": "No assistant session file: "
                                                 + str(session_path)}}, indent=2))
        # Nothing was sent: retry-safe for requests; --build-check reports "no session" as 3.
        return 3 if args.build_check else EXIT["not_executed"]
    if args.build_check:
        verdict = build_check(session_path, wait=args.wait)
        print(json.dumps(verdict, indent=2))
        return 0 if verdict.get("verdict") == "current" else 1
    if args.status:
        result = status(args.status, session_path)
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else exit_code(result)
    request = None
    if args.json or args.request_file:
        try:
            request = json.loads(args.json if args.json else args.request_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            parser.error("the request is not readable JSON: " + str(exc))
        if not isinstance(request, dict):
            parser.error("the request must be one JSON object")
        if args.request_id:
            if request.get("request_id") not in (None, args.request_id):
                parser.error("--request-id differs from the request's own request_id")
            request["request_id"] = args.request_id
    if args.reconcile:
        if not args.request_id:
            parser.error("--reconcile needs --request-id")
        result = reconcile_request(args.request_id, session_path, wait=args.wait, body=request, session_id=args.session_id)
    else:
        if request is None:
            parser.error("give --json, --request-file, --status, --build-check or --reconcile --request-id")
        if request.get("op") not in frozenset(session.get("read_operations") or READ_OPS_FALLBACK):
            request.setdefault("request_id", str(uuid.uuid4()))
        print(json.dumps({"request_id": request.get("request_id"), "session_id": session.get("session_id"),
                          "session_file": str(session_path)}), file=sys.stderr)
        result = send(request, session_path, wait=args.wait, reconcile=not args.no_reconcile, _session_data=session)
    print(json.dumps(result, indent=2))
    return exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
