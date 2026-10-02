"""Authenticated loopback transport. Only the Qt thread touches native documents."""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import secrets
import threading
import time
from .request_ledger import RequestLedger


class Bridge:
    def __init__(self, controller, runtime, request_timeout=30):
        self.controller=controller
        self.pending=queue.Queue(maxsize=32)
        self.token=secrets.token_urlsafe(32)
        self.request_timeout=request_timeout
        self.ledger=getattr(controller, "ledger", None) or RequestLedger()
        bridge=self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):
                pass

            def do_POST(self):
                if self.path!="/operation" or self.headers.get("Authorization")!="Bearer "+bridge.token:
                    self.send_error(403)
                    return
                # Prevent web pages from silently reaching the native local adapter.
                if self.headers.get("Origin") or self.headers.get("Content-Type")!="application/json":
                    self.send_error(403)
                    return
                try:
                    size=int(self.headers.get("Content-Length","0"))
                    if size<=0 or size>65536:
                        self.send_error(413)
                        return
                    request=json.loads(self.rfile.read(size))
                    if not isinstance(request, dict):
                        raise ValueError("Request must be an object")
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
                            if tracked:
                                bridge.ledger.complete(request["request_id"], {"ok":False,"error":{"code":"queue_full","message":"Queue is full; request was not started"}}, "cancelled")
                            raise
                    try:
                        result=reply.get(timeout=bridge.request_timeout)
                    except queue.Empty:
                        with gate:
                            cancel.set()
                            was_started=started.is_set()
                        result={"ok":False,"error":{"code":"outcome_unknown" if was_started else "timeout","message":"Operation may have completed; look up request_status or replay the identical request" if was_started else "Queued operation canceled before start", "request_id":request.get("request_id"),"session_id":bridge.ledger.session_id}}
                        if tracked and not was_started:
                            bridge.ledger.complete(request["request_id"], result, "cancelled")
                    raw=json.dumps(result).encode()
                    self.send_response(200)
                    self.send_header("Content-Type","application/json")
                    self.send_header("Content-Length",str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except (ValueError,queue.Full):
                    self.send_error(400)
                except (BrokenPipeError,ConnectionResetError):
                    pass

        self.server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
        self.server.daemon_threads=True
        self.path=Path(runtime)/"assistant-session.json"
        self.path.write_text(json.dumps({"url":f"http://127.0.0.1:{self.server.server_port}/operation","token":self.token,"pid":os.getpid(),"contract":2,"session_id":self.ledger.session_id},indent=2))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def tick(self):
        try:
            request,reply,cancel,started,gate,queued_at,tracked=self.pending.get_nowait()
        except queue.Empty:
            return False
        with gate:
            should_start=not cancel.is_set()
            if should_start:
                started.set()
        if should_start:
            queue_ms=round((time.perf_counter()-queued_at)*1000,2)
            result=self.controller.dispatch(request)
            result["queue_wait_ms"]=queue_ms
            if hasattr(self.controller,"timings"):
                self.controller.timings.record("queue_wait",queue_ms)
            reply.put(result)
        return True

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        # Do not remove another instance's session file.
        try:
            if json.loads(self.path.read_text()).get("pid")==os.getpid():
                self.path.unlink()
        except (OSError,ValueError):
            pass
