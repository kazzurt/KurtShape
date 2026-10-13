"""Timeout semantics: queued cancellation versus started, unknown outcome."""
import json
from copy import deepcopy
from pathlib import Path
import sys
import threading
import time
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


if __name__=="__main__":
    unittest.main(verbosity=2)
