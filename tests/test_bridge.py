"""Timeout semantics: queued cancellation versus started, unknown outcome."""
import json
from pathlib import Path
import sys
import threading
import time
import unittest
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from kurtshape.bridge import Bridge
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
    def create(self,delay=0,retry=False):
        folder=ROOT/"validation"/"bridge-timeout-session"
        folder.mkdir(exist_ok=True)
        controller=RetryController(delay) if retry else DummyController(delay)
        bridge=Bridge(controller,folder,request_timeout=0.08)
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


if __name__=="__main__":
    unittest.main(verbosity=2)
