"""Authenticated loopback transport. Only the Qt thread touches native documents."""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import secrets
import sys
import threading
import time
import traceback
from .request_ledger import RequestLedger, RequestStatusLookup
from .contract import CONTRACT_VERSION, CONTRACT_REVISION, REQUEST_SIZE_LIMIT
from . import build_identity


class _NonFinite(ValueError):
    pass


def _reject_constant(name):
    raise _NonFinite(name)


class _Server(ThreadingHTTPServer):
    """Handler-thread errors go to the session log, never to sys.stderr.

    In the GUI sys.stderr is FreeCAD's console redirect; a server thread printing a traceback into
    it while the GUI thread is busy can wedge the app (U10 stall, Fable review R1).
    """
    log_path=None

    def handle_error(self, request, client_address):
        try:
            with open(self.log_path, "a", encoding="utf-8") as log:
                log.write(f"Bridge handler error for {client_address!r}:\n{traceback.format_exc()}\n")
        except Exception:
            pass


class Bridge:
    def __init__(self, controller, runtime, request_timeout=30):
        self.controller=controller
        # The one background git comparison of the build identity starts with the bridge (F5 §2.1).
        build_identity.start_git_probe()
        self.pending=queue.Queue(maxsize=32)
        # The op the last tick dispatched or began, None when it dequeued nothing or a cancelled
        # request; the Panel skips its trailing inspect and refresh after quiet reads (C22).
        self.last_op=None
        # Parked view-op handles (contract 3.2 F2): (handle, reply, queue_ms); poll_deferred completes them.
        self.deferred=[]
        self.token=secrets.token_urlsafe(32)
        self.request_timeout=request_timeout
        self.ledger=getattr(controller, "ledger", None) or RequestLedger()
        lookup=getattr(controller, "request_status_lookup", None)
        self._request_status_lookup=(lookup if type(lookup) is RequestStatusLookup
                                     and lookup.ledger is self.ledger else None)
        bridge=self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):
                pass

            def send_json(self, result, status=200, headers=None):
                raw=json.dumps(result).encode()
                self.send_response(status)
                self.send_header("Content-Type","application/json")
                self.send_header("Content-Length",str(len(raw)))
                for name,value in (headers or {}).items():
                    self.send_header(name,value)
                self.end_headers()
                self.wfile.write(raw)

            def invalid_request(self, message):
                self.send_json({"ok":False,"error":{"code":"invalid_request","message":message}}, 400)

            def do_POST(self):
                try:
                    self.answer()
                except OSError:
                    # The client is gone or too slow (WinError 10053/10054, a broken pipe, a write
                    # timeout): a tracked request's outcome stays in the ledger for request_status.
                    self.close_connection=True

            def answer(self):
                if self.path!="/operation" or self.headers.get("Authorization")!="Bearer "+bridge.token:
                    self.send_error(403)
                    return
                # Prevent web pages from silently reaching the native local adapter.
                media_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if self.headers.get("Origin") is not None or media_type != "application/json":
                    self.send_error(403)
                    return
                try:
                    try:
                        size=int(self.headers.get("Content-Length","0"))
                    except ValueError:
                        self.invalid_request("Request body must be one JSON object")
                        return
                    if size<=0 or size>REQUEST_SIZE_LIMIT:
                        self.send_error(413)
                        return
                    body=self.rfile.read(size)
                    try:
                        # NaN and Infinity are not JSON; reject them before any registration.
                        request=json.loads(body, parse_constant=_reject_constant)
                    except _NonFinite:
                        self.invalid_request("Request contains a non-finite number")
                        return
                    except (ValueError,UnicodeDecodeError):
                        self.invalid_request("Request body must be one JSON object")
                        return
                    if not isinstance(request, dict):
                        self.invalid_request("Request body must be one JSON object")
                        return
                    lookup=bridge._request_status_lookup
                    if lookup is not None and lookup.ledger is bridge.ledger:
                        status=lookup.lookup(request)
                        if status is not None and lookup.ledger is bridge.ledger:
                            # No CAD queue or native/Controller call. Timings is
                            # owner-thread state; do not sample it here.
                            status["queue_wait_ms"]=0.0
                            self.send_json(status)
                            return
                    tracked=request.get("op") not in getattr(bridge.controller, "READ_OPS", {"dummy"})
                    replay=bridge.ledger.register(request, "queued") if tracked else None
                    reply=queue.Queue(maxsize=1)
                    cancel=threading.Event()
                    started=threading.Event()
                    gate=threading.Lock()
                    if replay is not None:
                        reply.put(replay)
                    else:
                        try:
                            bridge.pending.put_nowait((request,reply,cancel,started,gate,time.perf_counter(),tracked))
                        except queue.Full:
                            full={"ok":False,"error":{"code":"queue_full","message":"Queue is full; request was not started",
                                                      "request_id":request.get("request_id"),"session_id":bridge.ledger.session_id}}
                            if tracked:
                                bridge.ledger.complete(request["request_id"], full, "cancelled")
                            self.send_json(full, 503, {"Retry-After":"1"})
                            return
                    try:
                        result=reply.get(timeout=bridge.request_timeout)
                    except queue.Empty:
                        with gate:
                            cancel.set()
                            was_started=started.is_set()
                        result={"ok":False,"error":{"code":"outcome_unknown" if was_started else "timeout","message":"Operation may have completed; look up request_status or replay the identical request" if was_started else "Queued operation canceled before start", "request_id":request.get("request_id"),"session_id":bridge.ledger.session_id}}
                        if was_started and not tracked:
                            # A read is not in the ledger: request_status cannot settle it, resending is safe.
                            result["error"]["tracked"]=False
                        if tracked and not was_started:
                            bridge.ledger.complete(request["request_id"], result, "cancelled")
                    self.send_json(result)
                except ValueError:
                    self.invalid_request("Request body must be one JSON object")

        self.server=_Server(("127.0.0.1",0),Handler)
        self.server.daemon_threads=True
        self.server.log_path=Path(runtime)/"kurtshape.log"
        self.path=Path(runtime)/"assistant-session.json"
        read_operations=sorted(getattr(controller, "READ_OPS", ()))
        gui = bool(getattr(sys.modules.get("FreeCAD"), "GuiUp", False))
        display = os.environ.get("QT_QPA_PLATFORM", "native").split(":", 1)[0]
        launch = {"gui": gui, "display": display,
                  "visibility": ("offscreen" if display in {"offscreen", "minimal"} else "visible") if gui else "headless",
                  "profile": os.environ.get("FREECAD_USER_HOME"), "session_dir": str(Path(runtime).resolve())}
        self.path.write_text(json.dumps({"url":f"http://127.0.0.1:{self.server.server_port}/operation","token":self.token,"pid":os.getpid(),
                                         "contract":CONTRACT_VERSION,"contract_revision":CONTRACT_REVISION,"session_id":self.ledger.session_id,
                                         "build":build_identity.summary(),"read_operations":read_operations,
                                         "non_mutating_operations":sorted(getattr(controller, "NON_MUTATING_OPS", read_operations)),
                                         "request_size_limit":REQUEST_SIZE_LIMIT,"launch":launch},indent=2))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def tick(self):
        self.last_op=None
        try:
            request,reply,cancel,started,gate,queued_at,tracked=self.pending.get_nowait()
        except queue.Empty:
            return False
        with gate:
            should_start=not cancel.is_set()
            if should_start:
                started.set()
        if should_start:
            self.last_op=request.get("op") if isinstance(request, dict) else None
            queue_ms=round((time.perf_counter()-queued_at)*1000,2)
            # Only view ops may defer, and only through begin; every other op (and any patched
            # dispatch) keeps the synchronous contract (F2 D6).
            begin=getattr(self.controller,"begin",None)
            deferrable=(isinstance(request, dict) and request.get("op") in getattr(self.controller,"VIEW_OPS",())
                        and callable(begin))
            result=begin(request) if deferrable else self.controller.dispatch(request)
            if hasattr(self.controller,"timings"):
                self.controller.timings.record("queue_wait",queue_ms)
            if deferrable and not isinstance(result, dict):
                self.deferred.append((result,reply,queue_ms))
                return True
            result["queue_wait_ms"]=queue_ms
            reply.put(result)
        return True

    def poll_deferred(self):
        """Owner thread (Panel.tick): complete parked view-op handles; never raises. True while any wait."""
        for entry in list(self.deferred):
            handle,reply,queue_ms=entry
            try:
                response=handle.poll()
            except Exception as exc:
                response={"ok":False,"error":{"code":"render_failed","message":("Render poll failed: "+str(exc))[:300]}}
                try:
                    handle.cancel(response)  # runs the done-callbacks (ledger completion)
                except Exception:
                    pass
            if response is None:
                continue
            self.deferred.remove(entry)
            try:
                # The HTTP waiter may be gone (timeout); the ledger still holds the response.
                reply.put_nowait(dict(response, queue_wait_ms=queue_ms))
            except queue.Full:
                pass
        return bool(self.deferred)

    def close(self):
        for handle,reply,queue_ms in list(self.deferred):
            response={"ok":False,"error":{"code":"render_cancelled","message":"The bridge closed before the render completed"}}
            try:
                # A handle that already completed (e.g. document_closed) keeps the response the ledger holds.
                done=handle.poll()
                if done is None:
                    handle.cancel(response)
                else:
                    response=done
            except Exception:
                try:
                    handle.cancel(response)
                except Exception:
                    pass
            try:
                reply.put_nowait(dict(response, queue_wait_ms=queue_ms))
            except queue.Full:
                pass
        self.deferred.clear()
        self.server.shutdown()
        self.server.server_close()
        # Do not remove another instance's session file.
        try:
            if json.loads(self.path.read_text()).get("pid")==os.getpid():
                self.path.unlink()
        except (OSError,ValueError):
            pass
