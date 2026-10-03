"""Timeout semantics: queued cancellation versus started, unknown outcome."""
import json
from pathlib import Path
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
import support

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from kurtshape.bridge import Bridge
from kurtshape import contract
from kurtshape.request_ledger import RequestLedger


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
    def create(self,delay=0,retry=False,request_timeout=0.08):
        folder=support.scratch(self, prefix="bridge-timeout-session-")
        controller=RetryController(delay) if retry else DummyController(delay)
        bridge=Bridge(controller,folder,request_timeout=request_timeout)
        self.addCleanup(bridge.close)
        return bridge,controller

    def request(self,bridge,payload=None):
        req=urllib.request.Request(f"http://127.0.0.1:{bridge.server.server_port}/operation",data=json.dumps(payload or {"op":"dummy"}).encode(),headers={"Content-Type":"application/json","Authorization":"Bearer "+bridge.token},method="POST")
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


if __name__=="__main__":
    unittest.main(verbosity=2)
