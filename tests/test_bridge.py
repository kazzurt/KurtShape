"""Timeout semantics: queued cancellation versus started, unknown outcome."""
import http.client
import io
import json
from copy import deepcopy
from pathlib import Path
import socket
import struct
import sys
import threading
import time
import traceback
import unittest
import urllib.error
import urllib.request
from unittest.mock import Mock, patch
import support

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from kurtshape.bridge import Bridge
from kurtshape import contract
from kurtshape.request_ledger import RequestLedger, RequestStatusLookup


class DummyController:
    def __init__(self,delay=0):
        self.calls=0
        self.delay=delay

    def dispatch(self,request):
        self.calls+=1
        time.sleep(self.delay)
        return {"ok":True,"result":{"call":self.calls}}


class RetryController(DummyController):
    READ_OPS = {"request_status", "inspect"}

    def __init__(self, delay=0):
        super().__init__(delay)
        self.ledger = RequestLedger()

    def dispatch(self, request):
        if request["op"] == "request_status":
            return {"ok": True, "result": self.ledger.status(request["request_id"])}
        replay = self.ledger.register(request, "started")
        if replay is not None:
            return replay
        response = super().dispatch(request)
        self.ledger.complete(request["request_id"], response)
        return response


class BridgeTimeoutTests(unittest.TestCase):
    def create(self,delay=0,retry=False,request_timeout=0.08,lookup=False,ledger=None,controller=None):
        folder=support.scratch(self, prefix="bridge-timeout-session-")
        controller=controller or (RetryController(delay) if retry else DummyController(delay))
        if ledger is not None:
            controller.ledger=ledger
        if lookup:
            controller.default_measure=True
            controller.request_status_lookup=RequestStatusLookup(controller.ledger,controller.__dict__)
        bridge=Bridge(controller,folder,request_timeout=request_timeout)
        self.addCleanup(bridge.close)
        return bridge,controller

    def request(self,bridge,payload=None):
        req=urllib.request.Request(f"http://127.0.0.1:{bridge.server.server_port}/operation",data=json.dumps({"op":"dummy"} if payload is None else payload).encode(),headers={"Content-Type":"application/json","Authorization":"Bearer "+bridge.token},method="POST")
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req,timeout=3) as response:
            return json.loads(response.read())

    # Fable review R1 (2026-10-19): a client that is gone before the answer --------------
    def record_handler_errors(self, bridge):
        """Replace the server's handle_error: anything escaping do_POST lands in the returned list."""
        errors = []
        bridge.server.handle_error = lambda request, address: errors.append(traceback.format_exc())
        return errors

    def attempt(self, bridge, payload=None):
        """Send a request from a thread, play the owner thread once; the response or the client's exception."""
        results = []

        def send():
            try:
                results.append(self.request(bridge, payload))
            except Exception as exc:
                results.append(exc)
        thread = threading.Thread(target=send)
        thread.start()
        deadline = time.monotonic() + 3
        while bridge.pending.empty() and time.monotonic() < deadline:
            time.sleep(0.002)
        self.assertTrue(bridge.tick())
        thread.join(3)
        self.assertEqual(len(results), 1, "the request ended within the timeout")
        return results[0]

    def answered(self, bridge, payload=None):
        result = self.attempt(bridge, payload)
        self.assertIsInstance(result, dict, result)
        return result

    def test_a_client_gone_before_the_answer_never_reaches_handle_error_or_stderr(self):
        bridge, controller = self.create(request_timeout=3)
        errors = self.record_handler_errors(bridge)
        body = json.dumps({"op": "dummy"}).encode()
        raw = socket.create_connection(("127.0.0.1", bridge.server.server_port), timeout=3)
        raw.sendall(b"POST /operation HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
                    b"Authorization: Bearer " + bridge.token.encode() + b"\r\nContent-Length: "
                    + str(len(body)).encode() + b"\r\n\r\n" + body)
        deadline = time.monotonic() + 3
        while bridge.pending.empty() and time.monotonic() < deadline:
            time.sleep(0.002)
        # An abortive close, like a client whose own timeout fired: the answer goes to a dead socket.
        raw.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        raw.close()
        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
            self.assertTrue(bridge.tick())
            time.sleep(0.3)  # the handler thread writes to the dead socket
            self.assertEqual(self.answered(bridge), {"ok": True, "result": {"call": 2}, "queue_wait_ms": unittest.mock.ANY})
        self.assertEqual((errors, stderr.getvalue()), ([], ""))
        self.assertEqual(controller.calls, 2)

    def test_every_reply_write_tolerates_windows_socket_errors(self):
        bridge, _ = self.create(request_timeout=3)
        errors = self.record_handler_errors(bridge)
        handler = bridge.server.RequestHandlerClass
        failures = (ConnectionAbortedError(10053, "aborted by the host"), ConnectionResetError(10054, "reset"),
                    TimeoutError("timed out"), OSError(10058, "socket shut down"))
        for error in failures:
            def fail(*args, error=error, **kwargs):
                raise error
            for write in ("send_json", "send_error"):
                with self.subTest(error=type(error).__name__, write=write), patch.object(handler, write, fail):
                    client_errors = (OSError, http.client.HTTPException, urllib.error.URLError)
                    if write == "send_json":
                        # The reply write of a dispatched request fails: the client sees the connection close.
                        self.assertIsInstance(self.attempt(bridge), client_errors)
                    else:
                        with self.assertRaises(client_errors):
                            self.forbidden(bridge)  # the send_error(403) path
        self.assertEqual(errors, [], "nothing escaped do_POST")
        self.assertTrue(self.answered(bridge)["ok"], "the bridge still answers")

    def forbidden(self, bridge):
        """A request without the token takes the send_error(403) path."""
        req = urllib.request.Request(f"http://127.0.0.1:{bridge.server.server_port}/operation", data=b"{}",
                                     headers={"Content-Type": "application/json"}, method="POST")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=3) as response:
            return response.read()

    def test_handle_error_writes_the_session_log_and_never_stderr(self):
        bridge, _ = self.create()
        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
            try:
                raise RuntimeError("handler bug on purpose")
            except RuntimeError:
                bridge.server.handle_error(None, ("127.0.0.1", 1))
        self.assertEqual(stderr.getvalue(), "")
        log = (bridge.path.parent / "kurtshape.log").read_text(encoding="utf-8")
        self.assertIn("Bridge handler error for ('127.0.0.1', 1)", log)
        self.assertIn("RuntimeError: handler bug on purpose", log)

    # Contract 3.2 U2d: transport (F5 §6.1, §9.5) ---------------------------------------
    def test_queue_full_returns_json_503_with_request_identity(self):
        bridge, controller = self.create(retry=True, lookup=True)
        sentinels = [object() for _ in range(32)]
        for sentinel in sentinels:
            bridge.pending.put_nowait(sentinel)
        self.assertTrue(bridge.pending.full())
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        payload = {"op": "mutate", "request_id": "no-room"}
        request = urllib.request.Request(f"http://127.0.0.1:{bridge.server.server_port}/operation",
                                         data=json.dumps(payload).encode(),
                                         headers={"Content-Type": "application/json", "Authorization": "Bearer " + bridge.token},
                                         method="POST")
        with self.assertRaises(urllib.error.HTTPError) as rejected:
            opener.open(request, timeout=3)
        error = rejected.exception
        try:
            self.assertEqual(error.code, 503)
            self.assertEqual(error.headers.get("Retry-After"), "1")
            self.assertEqual(error.headers.get("Content-Type"), "application/json")
            body = json.loads(error.read())
        finally:
            error.close()
        self.assertEqual(body["error"]["code"], "queue_full")
        self.assertEqual(body["error"]["request_id"], "no-room")
        self.assertEqual(body["error"]["session_id"], bridge.ledger.session_id)
        self.assertEqual(bridge.ledger.status("no-room")["status"], "cancelled", "a tracked request is recorded as cancelled")
        self.assertEqual([bridge.pending.get_nowait() for _ in range(32)], sentinels, "nothing was queued")
        self.assertEqual(controller.calls, 0)
        # an untracked read gets the same 503 and is not ledgered
        for sentinel in sentinels:
            bridge.pending.put_nowait(sentinel)
        request = urllib.request.Request(f"http://127.0.0.1:{bridge.server.server_port}/operation",
                                         data=json.dumps({"op": "inspect", "request_id": "read-no-room"}).encode(),
                                         headers={"Content-Type": "application/json", "Authorization": "Bearer " + bridge.token},
                                         method="POST")
        with self.assertRaises(urllib.error.HTTPError) as rejected:
            opener.open(request, timeout=3)
        rejected.exception.close()
        self.assertEqual(rejected.exception.code, 503)
        self.assertEqual(bridge.ledger.status("read-no-room")["status"], "not_recorded")
        for _ in range(32):
            bridge.pending.get_nowait()

    def test_malformed_and_non_finite_bodies_return_json_400_before_registration(self):
        bridge, controller = self.create(retry=True, lookup=True)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        cases = [(b"[]", "Request body must be one JSON object"), (b"null", "Request body must be one JSON object"),
                 (b"invalid json", "Request body must be one JSON object"), (b"\xff\xfe", "Request body must be one JSON object"),
                 (b'{"op":"mutate","request_id":"nan-1","value":NaN}', "Request contains a non-finite number"),
                 (b'{"op":"inspect","value":Infinity}', "Request contains a non-finite number"),
                 (b'{"op":"mutate","request_id":"neg-inf","value":-Infinity}', "Request contains a non-finite number")]
        with patch.object(RequestStatusLookup, "lookup", side_effect=AssertionError("lookup reached")) as lookup:
            for raw, message in cases:
                with self.subTest(raw=raw):
                    request = urllib.request.Request(f"http://127.0.0.1:{bridge.server.server_port}/operation", data=raw,
                                                     headers={"Content-Type": "application/json",
                                                              "Authorization": "Bearer " + bridge.token}, method="POST")
                    with self.assertRaises(urllib.error.HTTPError) as rejected:
                        opener.open(request, timeout=3)
                    error = rejected.exception
                    try:
                        self.assertEqual(error.code, 400)
                        self.assertEqual(error.headers.get("Content-Type"), "application/json")
                        body = json.loads(error.read())
                    finally:
                        error.close()
                    self.assertEqual(body, {"ok": False, "error": {"code": "invalid_request", "message": message}})
            lookup.assert_not_called()
        self.assertEqual(bridge.ledger.status("nan-1")["status"], "not_recorded", "nothing is registered")
        self.assertEqual(bridge.ledger.status("neg-inf")["status"], "not_recorded")
        self.assertTrue(bridge.pending.empty())
        self.assertEqual(controller.calls, 0)
        # a bad Content-Length header is the same JSON 400
        request = urllib.request.Request(f"http://127.0.0.1:{bridge.server.server_port}/operation", data=b"{}",
                                         headers={"Content-Type": "application/json", "Authorization": "Bearer " + bridge.token,
                                                  "Content-Length": "two"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as rejected:
            opener.open(request, timeout=3)
        rejected.exception.close()
        self.assertEqual(rejected.exception.code, 400)

    def test_tick_records_dispatched_operation_only(self):
        bridge, controller = self.create(retry=True, lookup=True, request_timeout=0.08)
        self.assertIsNone(bridge.last_op)
        self.assertFalse(bridge.tick())
        self.assertIsNone(bridge.last_op, "an idle tick records nothing")
        worker, done, results, errors = self.start_request(bridge, {"op": "inspect", "request_id": "last-op-1"})
        deadline = time.monotonic() + 3
        while bridge.pending.empty() and time.monotonic() < deadline:
            time.sleep(.002)
        self.assertTrue(bridge.tick())
        self.assertEqual(bridge.last_op, "inspect")
        self.assertTrue(done.wait(3))
        self.assertEqual(errors, [])
        self.assertTrue(results[0]["ok"], results)
        # a request cancelled by its queued timeout is dequeued but never dispatched: last_op is None
        cancelled = self.request(bridge, {"op": "mutate", "request_id": "cancelled-last-op"})
        self.assertEqual(cancelled["error"]["code"], "timeout")
        self.assertEqual(bridge.pending.qsize(), 1)
        self.assertTrue(bridge.tick())
        self.assertIsNone(bridge.last_op)
        self.assertFalse(bridge.tick())
        self.assertIsNone(bridge.last_op)

    def test_session_file_lists_read_operations_and_build(self):
        from kurtshape import build_identity

        class ClassifiedController(DummyController):
            READ_OPS = {"inspect", "capabilities"}
            NON_MUTATING_OPS = frozenset({"inspect", "capabilities", "render_view"})
        bridge, _ = self.create(controller=ClassifiedController())
        session = json.loads(bridge.path.read_text(encoding="utf-8"))
        self.assertEqual(session["read_operations"], ["capabilities", "inspect"])
        self.assertEqual(session["non_mutating_operations"], ["capabilities", "inspect", "render_view"])
        self.assertEqual(session["build"], build_identity.summary())
        self.assertEqual(session["request_size_limit"], contract.REQUEST_SIZE_LIMIT)
        self.assertEqual(session["contract_revision"], contract.CONTRACT_REVISION)
        plain, _ = self.create()
        session = json.loads(plain.path.read_text(encoding="utf-8"))
        self.assertEqual(session["read_operations"], [])
        self.assertEqual(session["non_mutating_operations"], [])

    def test_started_timeout_marks_untracked_reads(self):
        bridge, controller = self.create(delay=0.3, request_timeout=0.08)
        # The dummy controller publishes no READ_OPS, so the bridge treats "dummy" as its one read.
        worker, done, results, errors = self.start_request(bridge, {"op": "dummy", "request_id": "slow-read"})
        deadline = time.monotonic() + 3
        while bridge.pending.empty() and time.monotonic() < deadline:
            time.sleep(.002)
        self.assertTrue(bridge.tick())
        self.assertTrue(done.wait(3))
        self.assertEqual(errors, [])
        error = results[0]["error"]
        self.assertEqual(error["code"], "outcome_unknown")
        self.assertIs(error["tracked"], False, "a read is not in the ledger; resending it is safe")
        self.assertEqual(bridge.ledger.status("slow-read")["status"], "not_recorded")

    def test_queued_timeout_cancels_before_any_mutation(self):
        bridge,controller=self.create()
        result=self.request(bridge)
        self.assertEqual(result["error"]["code"],"timeout")
        bridge.tick()
        self.assertEqual(controller.calls,0)

    def test_started_timeout_reports_unknown_and_does_not_claim_cancellation(self):
        bridge,controller=self.create(delay=0.18)
        results=[]
        worker=threading.Thread(target=lambda:results.append(self.request(bridge)))
        worker.start()
        deadline=time.monotonic()+2
        while bridge.pending.empty() and time.monotonic()<deadline:
            threading.Event().wait(0.002)
        self.assertFalse(bridge.pending.empty())
        bridge.tick()
        worker.join(timeout=2)
        self.assertEqual(results[0]["error"]["code"],"outcome_unknown")
        self.assertEqual(controller.calls,1)

    def test_started_timeout_lookup_replay_and_different_payload_reuse(self):
        bridge,controller=self.create(delay=0.18,retry=True)
        payload={"op":"mutate", "request_id":"late-once", "value":8}
        results=[]
        worker=threading.Thread(target=lambda:results.append(self.request(bridge,payload)))
        worker.start()
        deadline=time.monotonic()+2
        while bridge.pending.empty() and time.monotonic()<deadline:
            threading.Event().wait(0.002)
        bridge.tick()
        worker.join(timeout=2)
        self.assertEqual(results[0]["error"]["code"],"outcome_unknown")
        status=controller.ledger.status("late-once")
        self.assertEqual(status["status"],"completed")
        replay=self.request(bridge,payload)
        self.assertEqual(replay,status["response"])
        mismatch=self.request(bridge,dict(payload,value=9))
        self.assertEqual(mismatch["error"]["code"],"request_id_reused")
        self.assertEqual(controller.calls,1)

    def test_cancelled_request_id_is_not_later_executed(self):
        bridge,controller=self.create(retry=True)
        payload={"op":"mutate", "request_id":"cancelled-once"}
        response=self.request(bridge,payload)
        self.assertEqual(response["error"]["code"],"timeout")
        bridge.tick()
        self.assertEqual(controller.ledger.status("cancelled-once")["status"],"cancelled")
        self.assertEqual(self.request(bridge,payload),response)
        self.assertEqual(controller.calls,0)

    def test_rejects_missing_token_wrong_path_origin_header_non_json_and_oversize(self):
        bridge, controller = self.create()
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + bridge.token,
                   "Content-Length": "14"}
        cases = [
            ("missing token", "/operation", {"Content-Type": "application/json", "Content-Length": "14"}, 403),
            ("wrong path", "/other", headers, 403),
            ("Origin", "/operation", dict(headers, Origin="https://example.invalid"), 403),
            ("empty Origin", "/operation", dict(headers, Origin=""), 403),
            ("non JSON", "/operation", dict(headers, **{"Content-Type": "text/plain"}), 403),
            ("oversize", "/operation", dict(headers, **{"Content-Length": "65537"}), 413),
        ]
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for label, path, request_headers, status in cases:
            with self.subTest(label=label):
                # These guards reject the headers before consuming a body.
                # Sending only headers avoids a Windows reset from unread data.
                request = urllib.request.Request(f"http://127.0.0.1:{bridge.server.server_port}" + path,
                                                 data=None, headers=request_headers, method="POST")
                with self.assertRaises(urllib.error.HTTPError) as rejected:
                    opener.open(request, timeout=3)
                self.assertEqual(rejected.exception.code, status)
                rejected.exception.close()
                self.assertEqual(controller.calls, 0)
                self.assertTrue(bridge.pending.empty())

    def test_accepts_json_media_type_with_charset(self):
        bridge, controller = self.create(request_timeout=1)
        request = urllib.request.Request(f"http://127.0.0.1:{bridge.server.server_port}/operation",
                                         data=b'{"op":"dummy"}',
                                         headers={"Content-Type": "application/json; charset=utf-8",
                                                  "Authorization": "Bearer " + bridge.token}, method="POST")
        results, errors = [], []
        def send():
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(request, timeout=3) as response:
                    results.append(json.loads(response.read()))
            except Exception as exc:
                errors.append(exc)
        worker = threading.Thread(target=send)
        worker.start()
        deadline = time.monotonic() + 2
        while bridge.pending.empty() and worker.is_alive() and time.monotonic() < deadline:
            threading.Event().wait(0.002)
        bridge.tick()
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["ok"], results)
        self.assertEqual(controller.calls, 1)

    def test_session_file_reports_shared_contract_constant(self):
        bridge, _ = self.create()
        session = json.loads(bridge.path.read_text(encoding="utf-8"))
        self.assertEqual(session["contract"], contract.CONTRACT_VERSION)
        self.assertEqual(session["contract_revision"], contract.CONTRACT_REVISION)

    def start_request(self,bridge,payload):
        results,errors,done=[],[],threading.Event()
        def send():
            try:
                results.append(self.request(bridge,payload))
            except BaseException as exc:
                errors.append(exc)
            finally:
                done.set()
        thread=threading.Thread(target=send,daemon=True)
        thread.start()
        self.addCleanup(thread.join,3)
        return thread,done,results,errors

    def queued_request(self,bridge,payload):
        queued=threading.Event()
        original=bridge.pending.put_nowait
        def publish(item):
            original(item)
            queued.set()
        bridge.pending.put_nowait=publish
        try:
            request=self.start_request(bridge,payload)
            self.assertTrue(queued.wait(2),"Request did not reach the owner queue")
        finally:
            bridge.pending.put_nowait=original
        return request

    def finish_request(self,request):
        thread,done,results,errors=request
        self.assertTrue(done.wait(3),"HTTP request did not finish")
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors,[])
        self.assertEqual(len(results),1)
        return results[0]

    def queued_oracle(self,bridge,controller,payload):
        expected={"ok":False,"error":{"code":"owner_validation","request":deepcopy(payload)}}
        dispatch=Mock(return_value=deepcopy(expected))
        controller.dispatch=dispatch
        request=self.queued_request(bridge,payload)
        self.assertTrue(bridge.tick())
        response=self.finish_request(request)
        self.assertIsInstance(response.pop("queue_wait_ms"),float)
        self.assertEqual(response,expected)
        dispatch.assert_called_once_with(payload)
        self.assertTrue(bridge.pending.empty())

    def test_opted_in_status_needs_no_tick_dispatch_or_timing(self):
        bridge,controller=self.create(retry=True,lookup=True)
        controller.dispatch=Mock(side_effect=AssertionError("Status called the controller"))
        controller.timings=Mock()
        controller.timings.record.side_effect=AssertionError("Status touched owner timings")
        # The capsule uses the exact plain ledger implementation, not an
        # overridden instance method or an owner descriptor.
        controller.ledger.status=Mock(side_effect=AssertionError("Bound status override called"))
        for default in (False,True,"full"):
            controller.default_measure=default
            for identifier in ("not-recorded","x"*128):
                with self.subTest(default=default,identifier=identifier):
                    response=self.request(bridge,{"op":"request_status","request_id":identifier})
                    self.assertEqual(response,{"ok":True,"result":RequestLedger.status(controller.ledger,identifier),"queue_wait_ms":0.0})
                    self.assertIs(type(response["queue_wait_ms"]),float)
        self.assertTrue(bridge.pending.empty())
        controller.dispatch.assert_not_called()
        controller.timings.record.assert_not_called()
        controller.ledger.status.assert_not_called()

    def test_status_runs_while_owner_mutation_is_blocked_and_after_unknown_outcome(self):
        bridge,controller=self.create(retry=True,lookup=True,request_timeout=1)
        started,release=threading.Event(),threading.Event()
        owner_calls,timing_calls,owner_errors=[],[],[]
        response={"ok":True,"result":{"committed":True,"nested":{"value":[8]}}}
        payload={"op":"mutate","request_id":"barrier-once","value":8}
        def dispatch(request):
            self.assertEqual(request,payload)
            self.assertIsNone(controller.ledger.register(request,"started"))
            owner_calls.append(threading.get_ident())
            started.set()
            self.assertTrue(release.wait(4),"Mutation barrier was never released")
            controller.ledger.complete(request["request_id"],response)
            return deepcopy(response)
        controller.dispatch=dispatch
        controller.timings=Mock()
        controller.timings.record.side_effect=lambda *args:timing_calls.append((threading.get_ident(),args))
        request=self.queued_request(bridge,payload)
        queued=self.request(bridge,{"op":"request_status","request_id":payload["request_id"]})
        self.assertEqual(queued["result"]["status"],"queued")
        def tick():
            try:
                bridge.tick()
            except BaseException as exc:
                owner_errors.append(exc)
        owner=threading.Thread(target=tick,daemon=True)
        owner.start()
        try:
            self.assertTrue(started.wait(2))
            status=self.request(bridge,{"op":"request_status","request_id":payload["request_id"]})
            self.assertEqual(status["result"]["status"],"started")
            self.assertEqual(status["queue_wait_ms"],0.0)
            self.assertFalse(release.is_set())
            self.assertTrue(owner.is_alive())
            self.assertEqual(timing_calls,[])
            unknown=self.finish_request(request)
            self.assertEqual(unknown["error"]["code"],"outcome_unknown")
        finally:
            release.set()
            owner.join(3)
        self.assertFalse(owner.is_alive())
        self.assertEqual(owner_errors,[])
        self.assertEqual(len(owner_calls),1)
        self.assertEqual(len(timing_calls),1)
        self.assertEqual(timing_calls[0][0],owner_calls[0])
        completed=self.request(bridge,{"op":"request_status","request_id":payload["request_id"]})
        self.assertEqual(completed["result"]["status"],"completed")
        self.assertEqual(completed["result"]["response"],response)
        self.assertEqual(self.request(bridge,payload),response)
        self.assertEqual(len(owner_calls),1)
        self.assertEqual(len(timing_calls),1)

    def test_status_bypasses_full_32_item_owner_queue(self):
        bridge,controller=self.create(retry=True,lookup=True)
        controller.dispatch=Mock(side_effect=AssertionError("Full-queue status dispatched"))
        self.assertIsNone(controller.ledger.register({"op":"mutate","request_id":"waiting"},"queued"))
        sentinels=[object() for _ in range(32)]
        for sentinel in sentinels:
            bridge.pending.put_nowait(sentinel)
        self.assertTrue(bridge.pending.full())
        response=self.request(bridge,{"op":"request_status","request_id":"waiting"})
        self.assertEqual(response["result"]["status"],"queued")
        self.assertEqual(response["queue_wait_ms"],0.0)
        self.assertEqual([bridge.pending.get_nowait() for _ in range(32)],sentinels)
        controller.dispatch.assert_not_called()

    def test_status_lookup_authentication_and_json_guards_precede_lookup(self):
        bridge,controller=self.create(retry=True,lookup=True)
        base={"Content-Type":"application/json","Authorization":"Bearer "+bridge.token,"Content-Length":"14"}
        cases=[("/operation",{"Content-Type":"application/json","Content-Length":"14"},403),
               ("/other",base,403),
               ("/operation",dict(base,Origin="https://example.invalid"),403),
               ("/operation",dict(base,Origin=""),403),
               ("/operation",dict(base,**{"Content-Type":"text/plain"}),403),
               ("/operation",dict(base,**{"Content-Length":"65537"}),413)]
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with patch.object(RequestStatusLookup,"lookup",side_effect=AssertionError("Guard bypassed")) as lookup:
            for path,headers,status in cases:
                request=urllib.request.Request(f"http://127.0.0.1:{bridge.server.server_port}"+path,data=None,headers=headers,method="POST")
                with self.subTest(path=path,headers=headers),self.assertRaises(urllib.error.HTTPError) as rejected:
                    opener.open(request,timeout=3)
                self.assertEqual(rejected.exception.code,status)
                rejected.exception.close()
            for raw in (b"[]",b"null",b"invalid json"):
                request=urllib.request.Request(f"http://127.0.0.1:{bridge.server.server_port}/operation",data=raw,headers={"Content-Type":"application/json","Authorization":"Bearer "+bridge.token},method="POST")
                with self.subTest(raw=raw),self.assertRaises(urllib.error.HTTPError) as rejected:
                    opener.open(request,timeout=3)
                self.assertEqual(rejected.exception.code,400)
                rejected.exception.close()
            lookup.assert_not_called()
        self.assertTrue(bridge.pending.empty())
        self.assertEqual(controller.calls,0)

    def test_noncanonical_status_and_invalid_defaults_keep_queued_validation(self):
        bridge,controller=self.create(retry=True,lookup=True,request_timeout=2)
        canonical={"op":"request_status","request_id":"unknown"}
        payloads=[{"op":"request_status"},
                  *[{"op":"request_status","request_id":value} for value in (None,False,1,"","x"*129,[],{})],
                  *[dict(canonical,**{key:value}) for key,value in (("measure",True),("document_id","doc"),("expected_revision","old"),("extra",1))],
                  {"op":"inspect","request_id":"read-other"}]
        for payload in payloads:
            with self.subTest(payload=payload):
                self.queued_oracle(bridge,controller,payload)
        for default in (None,0,1,"true","FULL",[],{}):
            with self.subTest(default=default):
                controller.default_measure=default
                self.queued_oracle(bridge,controller,canonical)
        del controller.default_measure
        self.queued_oracle(bridge,controller,canonical)

    def test_status_requires_exact_explicit_capability_and_matching_live_ledger(self):
        class DerivedLookup(RequestStatusLookup):
            pass
        variants=("absent","duck","subclass","wrong-ledger")
        for variant in variants:
            with self.subTest(variant=variant):
                controller=RetryController()
                controller.default_measure=True
                if variant=="duck":
                    controller.request_status_lookup=Mock()
                elif variant=="subclass":
                    controller.request_status_lookup=DerivedLookup(controller.ledger,controller.__dict__)
                elif variant=="wrong-ledger":
                    other=RequestLedger()
                    controller.request_status_lookup=RequestStatusLookup(other,{"ledger":other,"default_measure":True})
                bridge,_=self.create(controller=controller,request_timeout=2)
                self.queued_oracle(bridge,controller,{"op":"request_status","request_id":"unseen"})
                if variant=="duck":
                    controller.request_status_lookup.lookup.assert_not_called()
        bridge,controller=self.create(retry=True,lookup=True,request_timeout=2)
        controller.ledger=RequestLedger()
        self.queued_oracle(bridge,controller,{"op":"request_status","request_id":"new-ledger"})

    def test_lookup_refuses_nonplain_inputs_and_configuration_change_during_copy(self):
        class DerivedLedger(RequestLedger):
            pass
        class DerivedDict(dict):
            pass
        class DerivedString(str):
            pass
        with self.assertRaises(TypeError):
            RequestStatusLookup(DerivedLedger(),{})
        with self.assertRaises(TypeError):
            RequestStatusLookup(RequestLedger(),DerivedDict())
        ledger=RequestLedger()
        configuration={"ledger":ledger,"default_measure":True}
        lookup=RequestStatusLookup(ledger,configuration)
        self.assertIsNone(lookup.lookup(DerivedDict(op="request_status",request_id="id")))
        self.assertIsNone(lookup.lookup({"op":"request_status","request_id":DerivedString("id")}))
        request={"op":"mutate","request_id":"copy-reentry"}
        self.assertIsNone(ledger.register(request,"started"))
        for changed_key,changed_value in (("default_measure",None),("ledger",RequestLedger())):
            configuration.update(ledger=ledger,default_measure=True)
            class ChangeDuringCopy:
                def __deepcopy__(self,memo):
                    configuration[changed_key]=changed_value
                    return "detached"
            # Deliberate internal fault injection: normal responses are plain
            # JSON, and complete() itself defensively copies them.
            ledger.records["copy-reentry"]["response"]={"ok":True,"result":{"value":ChangeDuringCopy()}}
            self.assertIsNone(lookup.lookup({"op":"request_status","request_id":"copy-reentry"}))

    def test_status_copies_nested_results_without_changing_cached_replay(self):
        bridge,controller=self.create(retry=True,lookup=True)
        payload={"op":"mutate","request_id":"nested-once"}
        original={"ok":True,"result":{"features":[{"values":[1,2]}]}}
        self.assertIsNone(controller.ledger.register(payload,"started"))
        controller.ledger.complete(payload["request_id"],original)
        original["result"]["features"][0]["values"].append(99)
        copied=controller.request_status_lookup.lookup({"op":"request_status","request_id":payload["request_id"]})
        copied["result"]["response"]["result"]["features"][0]["values"].append(77)
        expected={"ok":True,"result":{"features":[{"values":[1,2]}]}}
        for _ in range(2):
            status=self.request(bridge,{"op":"request_status","request_id":payload["request_id"]})
            self.assertEqual(status["result"]["response"],expected)
            status["result"]["response"]["result"]["features"][0]["values"].append(88)
        self.assertEqual(self.request(bridge,payload),expected)
        self.assertEqual(controller.calls,0)
        self.assertTrue(bridge.pending.empty())

    def test_status_preserves_failed_expired_and_capacity_semantics(self):
        ledger=RequestLedger(limit=1)
        bridge,controller=self.create(retry=True,lookup=True,ledger=ledger)
        for index in range(8):
            identifier="item-"+str(index)
            self.assertIsNone(ledger.register({"op":"mutate","request_id":identifier},"started"))
            response={"ok":False,"error":{"code":"native_failure","details":[index]}}
            ledger.complete(identifier,response)
            status=self.request(bridge,{"op":"request_status","request_id":identifier})
            self.assertEqual(status["result"]["status"],"failed")
            self.assertEqual(status["result"]["response"],response)
        for identifier,status in (("item-0","expired"),("unseen","not_recorded")):
            actual=self.request(bridge,{"op":"request_status","request_id":identifier})
            self.assertEqual(actual["result"]["status"],status)
            self.assertNotIn("response",actual["result"])
        self.assertEqual(ledger.register({"op":"mutate","request_id":"overflow"},"started")["error"]["code"],"request_capacity_reached")
        self.assertEqual(ledger.register({"op":"mutate","request_id":"item-0"},"started")["error"]["code"],"request_expired")
        self.assertEqual(controller.calls,0)
        self.assertTrue(bridge.pending.empty())

    def test_fast_status_reports_actual_queued_cancellation_and_cached_replay(self):
        bridge,controller=self.create(retry=True,lookup=True)
        payload={"op":"mutate","request_id":"cancelled-with-status"}
        cancelled=self.request(bridge,payload)
        self.assertEqual(cancelled["error"]["code"],"timeout")
        status=self.request(bridge,{"op":"request_status","request_id":payload["request_id"]})
        self.assertEqual(status["result"]["status"],"cancelled")
        self.assertEqual(status["result"]["response"],cancelled)
        self.assertEqual(status["queue_wait_ms"],0.0)
        self.assertEqual(self.request(bridge,payload),cancelled)
        self.assertEqual(bridge.pending.qsize(),1)
        self.assertTrue(bridge.tick())
        self.assertEqual(controller.calls,0)
        self.assertTrue(bridge.pending.empty())


class FakeHandle:
    """A parked view-op job: poll() is None until finish(); cancel() completes it like render_jobs.Deferred."""

    def __init__(self):
        self.response = None
        self.callbacks = []
        self.polls = 0
        self.fail = None

    def add_done_callback(self, callback):
        self.callbacks.append(callback)

    def finish(self, response):
        if self.response is None:
            self.response = response
            for callback in self.callbacks:
                callback(deepcopy(response))

    def poll(self):
        self.polls += 1
        if self.fail is not None:
            raise self.fail
        return None if self.response is None else deepcopy(self.response)

    def cancel(self, response):
        self.finish(response)


class ViewController(RetryController):
    """Ledger semantics of Controller._run: view ops begin and park; everything else dispatches."""
    READ_OPS = {"request_status", "inspect"}
    VIEW_OPS = frozenset({"render_view"})

    def __init__(self):
        super().__init__()
        self.handles = []
        self.begun = []
        self.dispatched = []

    def dispatch(self, request):
        self.dispatched.append(request["op"])
        if request["op"] == "inspect":  # reads are never ledgered (Controller._run)
            return {"ok": True, "result": {"inspect": True}}
        return super().dispatch(request)

    def begin(self, request):
        self.begun.append(request["op"])
        replay = self.ledger.register(request, "started")
        if replay is not None:
            return replay
        handle = FakeHandle()
        handle.add_done_callback(lambda response, rid=request["request_id"]: self.ledger.complete(rid, response))
        self.handles.append(handle)
        return handle


class BridgeDeferredTests(unittest.TestCase):
    """Contract 3.2 F2: view ops begin and park on the owner thread; nothing else changes (U4)."""

    def create(self, request_timeout=2, controller=None):
        folder = support.scratch(self, prefix="bridge-deferred-session-")
        controller = controller or ViewController()
        controller.default_measure = True
        controller.request_status_lookup = RequestStatusLookup(controller.ledger, controller.__dict__)
        bridge = Bridge(controller, folder, request_timeout=request_timeout)
        self.addCleanup(bridge.close)
        return bridge, controller

    def post(self, bridge, payload):
        req = urllib.request.Request(f"http://127.0.0.1:{bridge.server.server_port}/operation", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": "Bearer " + bridge.token},
                                     method="POST")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=5) as response:
            return json.loads(response.read())

    def start(self, bridge, payload):
        results = []
        thread = threading.Thread(target=lambda: results.append(self.post(bridge, payload)))
        thread.start()
        deadline = time.monotonic() + 3
        while bridge.pending.empty() and time.monotonic() < deadline:
            time.sleep(0.002)
        return thread, results

    def test_only_view_ops_route_to_begin(self):
        bridge, controller = self.create()
        thread, results = self.start(bridge, {"op": "mutate", "request_id": "m-1"})
        self.assertTrue(bridge.tick())
        thread.join(3)
        thread, _ = self.start(bridge, {"op": "render_view", "request_id": "v-1"})
        self.assertTrue(bridge.tick())
        self.assertEqual((controller.dispatched, controller.begun), (["mutate"], ["render_view"]))
        self.assertEqual(bridge.last_op, "render_view")
        controller.handles[0].finish({"ok": True, "result": {"image": 1}})
        bridge.poll_deferred()
        thread.join(3)
        # A patched dispatch (tests, GUI recipes) still receives every non-view op synchronously.
        seen = []
        controller.dispatch = lambda request: seen.append(request["op"]) or {"ok": True, "result": {}}
        thread, results = self.start(bridge, {"op": "inspect"})
        bridge.tick()
        thread.join(3)
        self.assertEqual((seen, results[0]["ok"]), (["inspect"], True))

    def test_deferred_reply_after_poll_without_blocking_tick(self):
        bridge, controller = self.create()
        view, view_results = self.start(bridge, {"op": "render_view", "request_id": "v-2"})
        self.assertTrue(bridge.tick())
        self.assertEqual(len(bridge.deferred), 1)
        other, other_results = self.start(bridge, {"op": "inspect", "request_id": "i-2"})
        self.assertTrue(bridge.tick(), "other requests are served while the view job runs")
        other.join(3)
        self.assertTrue(other_results[0]["ok"])
        self.assertTrue(bridge.poll_deferred(), "still waiting")
        self.assertEqual(view_results, [])
        time.sleep(0.05)
        controller.handles[0].finish({"ok": True, "result": {"image": 2}})
        self.assertFalse(bridge.poll_deferred())
        view.join(3)
        self.assertEqual(view_results[0]["result"], {"image": 2})
        self.assertGreaterEqual(view_results[0]["queue_wait_ms"], 0)
        self.assertEqual(bridge.deferred, [])
        self.assertEqual(controller.ledger.status("v-2")["status"], "completed")

    def test_deferred_outcome_unknown_then_request_status_returns_stored_response(self):
        bridge, controller = self.create(request_timeout=0.3)
        thread, results = self.start(bridge, {"op": "render_view", "request_id": "v-3"})
        bridge.tick()
        thread.join(3)
        self.assertEqual(results[0]["error"]["code"], "outcome_unknown")
        self.assertNotIn("tracked", results[0]["error"], "a view op is ledger-tracked")
        self.assertEqual(self.post(bridge, {"op": "request_status", "request_id": "v-3"})["result"]["status"], "started")
        controller.handles[0].finish({"ok": True, "result": {"image": 3}})
        self.assertFalse(bridge.poll_deferred(), "the waiter is gone; the reply is dropped, not an error")
        status = self.post(bridge, {"op": "request_status", "request_id": "v-3"})["result"]
        self.assertEqual((status["status"], status["response"]), ("completed", {"ok": True, "result": {"image": 3}}))

    def test_poll_exception_completes_waiter_and_ledger(self):
        bridge, controller = self.create()
        thread, results = self.start(bridge, {"op": "render_view", "request_id": "v-4"})
        bridge.tick()
        controller.handles[0].fail = RuntimeError("worker vanished")
        self.assertFalse(bridge.poll_deferred())
        thread.join(3)
        self.assertEqual(results[0]["error"]["code"], "render_failed")
        self.assertIn("worker vanished", results[0]["error"]["message"])
        self.assertEqual(controller.ledger.status("v-4")["status"], "failed")

    def test_close_cancels_deferred(self):
        bridge, controller = self.create()
        thread, results = self.start(bridge, {"op": "render_view", "request_id": "v-5"})
        bridge.tick()
        bridge.close()
        thread.join(3)
        self.assertEqual(results[0]["error"]["code"], "render_cancelled")
        self.assertEqual(controller.ledger.status("v-5")["status"], "failed")
        self.assertEqual(bridge.deferred, [])

    def test_close_replies_with_an_already_completed_response(self):
        bridge, controller = self.create()
        thread, results = self.start(bridge, {"op": "render_view", "request_id": "v-7"})
        bridge.tick()
        closed = {"ok": False, "error": {"code": "document_closed", "message": "closed"}}
        controller.handles[0].finish(closed)  # completed (ledger written) but not yet polled
        bridge.close()
        thread.join(3)
        self.assertEqual(results[0]["error"]["code"], "document_closed", "the reply matches the ledger")
        self.assertEqual(controller.ledger.status("v-7")["response"], closed)

    def test_a_non_dict_from_dispatch_is_not_parked(self):
        bridge, controller = self.create()
        controller.dispatch = lambda request: object()  # a broken patched dispatch for an ordinary op
        thread, results = self.start(bridge, {"op": "inspect"})
        with self.assertRaises(TypeError):
            bridge.tick()
        self.assertEqual(bridge.deferred, [], "only view ops begun through begin are parked")
        thread.join(5)  # the HTTP waiter ends with outcome_unknown

    def test_ledger_unchanged_for_other_ops(self):
        bridge, controller = self.create()
        thread, results = self.start(bridge, {"op": "mutate", "request_id": "m-6"})
        bridge.tick()
        thread.join(3)
        self.assertEqual(controller.ledger.status("m-6")["status"], "completed")
        thread, results = self.start(bridge, {"op": "inspect", "request_id": "i-6"})
        bridge.tick()
        thread.join(3)
        self.assertTrue(results[0]["ok"])
        self.assertEqual(controller.ledger.status("i-6")["status"], "not_recorded")
        self.assertEqual(controller.begun, [])
        self.assertFalse(bridge.poll_deferred())


if __name__=="__main__":
    unittest.main(verbosity=2)
