"""Authenticated loopback transport. Only the Qt thread touches native documents."""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import secrets
import threading


class Bridge:
    def __init__(self, controller, runtime, request_timeout=30):
        self.controller=controller
        self.pending=queue.Queue(maxsize=32)
        self.token=secrets.token_urlsafe(32)
        self.request_timeout=request_timeout
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
                    reply=queue.Queue(maxsize=1)
                    cancel=threading.Event()
                    started=threading.Event()
                    gate=threading.Lock()
                    bridge.pending.put_nowait((request,reply,cancel,started,gate))
                    try:
                        result=reply.get(timeout=bridge.request_timeout)
                    except queue.Empty:
                        with gate:
                            cancel.set()
                            was_started=started.is_set()
                        result={"ok":False,"error":{"code":"outcome_unknown" if was_started else "timeout","message":"Operation may have completed after the client timeout; inspect before retrying" if was_started else "Queued operation canceled before start; inspect before retrying"}}
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
        self.path.write_text(json.dumps({"url":f"http://127.0.0.1:{self.server.server_port}/operation","token":self.token,"pid":os.getpid(),"contract":1},indent=2))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()

    def tick(self):
        try:
            request,reply,cancel,started,gate=self.pending.get_nowait()
        except queue.Empty:
            return False
        with gate:
            should_start=not cancel.is_set()
            if should_start:
                started.set()
        if should_start:
            reply.put(self.controller.dispatch(request))
        return True

    def close(self):
        self.server.shutdown()
        # Do not remove another instance's session file.
        try:
            if json.loads(self.path.read_text()).get("pid")==os.getpid():
                self.path.unlink()
        except (OSError,ValueError):
            pass
