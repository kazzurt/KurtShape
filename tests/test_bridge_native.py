"""Real native Controller coverage for the loopback Bridge status path."""
from contextlib import ExitStack
from copy import deepcopy
import json
import math
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch
import urllib.request

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kurtshape.bridge import Bridge

try:
    import FreeCAD as App
except ImportError:
    App = None
if App is not None:
    from kurtshape.core import Controller


@unittest.skipIf(App is None, "Requires the bundled native FreeCAD runtime")
class NativeBridgeStatusTests(unittest.TestCase):
    def setUp(self):
        self.names = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="bridge-status-native-")
        self.core = Controller()
        self.state = None
        self.call("new")

    def tearDown(self):
        try:
            self.core.close()
        finally:
            for name in set(App.listDocuments()) - self.names:
                App.closeDocument(name)

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def request(self, op, **arguments):
        request = {"op": op, **arguments}
        if op not in {"new", "open"}:
            request.update(document_id=self.state["document_id"], expected_revision=self.state["revision"])
        return request

    def call(self, op, **arguments):
        response = self.core.dispatch(self.request(op, **arguments))
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        return self.state

    def plate(self):
        self.call("sketch_rectangle", id="Plate", width=20, height=10)
        self.call("pad", profile="Plate", length=6)

    @staticmethod
    def _status_http(bridge, payload):
        request = urllib.request.Request(
            f"http://127.0.0.1:{bridge.server.server_port}/operation",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + bridge.token},
            method="POST")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=4) as response:
            return json.loads(response.read())

    def _queued_status_on_owner(self, bridge, payload):
        """Only the HTTP client runs off-thread; native dispatch stays here."""
        replies, errors, owners = [], [], []
        finished = threading.Event()
        owner = threading.get_ident()
        dispatch = self.core.dispatch

        def actual_dispatch(request):
            owners.append(threading.get_ident())
            return dispatch(request)

        def send():
            try:
                replies.append(self._status_http(bridge, payload))
            except BaseException as exc:
                errors.append(exc)
            finally:
                finished.set()

        client = threading.Thread(target=send, daemon=True)
        with patch.object(self.core, "dispatch", side_effect=actual_dispatch) as called:
            client.start()
            try:
                deadline = time.monotonic() + 3
                while bridge.pending.empty() and not finished.is_set() and time.monotonic() < deadline:
                    finished.wait(.002)
                self.assertFalse(bridge.pending.empty(), (payload, replies, errors))
                self.assertFalse(finished.is_set(), (payload, replies, errors))
                called.assert_not_called()
                self.assertTrue(bridge.tick())
                client.join(timeout=4)
                self.assertFalse(client.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual(len(replies), 1)
                called.assert_called_once_with(payload)
                self.assertEqual(owners, [owner])
            finally:
                client.join(timeout=4)
        self.assertTrue(bridge.pending.empty())
        return replies[0]

    def test_session_file_and_capabilities_share_build_identity(self):
        from kurtshape import build_identity, contract
        bridge = Bridge(self.core, self.folder, request_timeout=2)
        try:
            session = json.loads(bridge.path.read_text(encoding="utf-8"))
        finally:
            bridge.close()
            bridge.thread.join(timeout=2)
        capabilities = self.core.dispatch({"op": "capabilities"})["result"]
        self.assertEqual(session["build"], build_identity.summary())
        self.assertEqual(session["build"]["source_sha256"], capabilities["build"]["source_sha256"])
        self.assertEqual(session["build"]["id"], capabilities["build"]["id"])
        self.assertEqual(session["read_operations"], sorted(Controller.READ_OPS))
        self.assertEqual(session["read_operations"], capabilities["read_operations"])
        self.assertEqual(session["non_mutating_operations"], capabilities["non_mutating_operations"])
        self.assertEqual(session["request_size_limit"], contract.REQUEST_SIZE_LIMIT)
        self.assertEqual(session["request_size_limit"], capabilities["request_size_limit_bytes"])
        self.assertEqual(session["contract_revision"], 2)

    def test_controller_construction_starts_no_git_probe(self):
        import subprocess
        from kurtshape import build_identity
        with patch.object(build_identity, "start_git_probe") as probe, \
                patch.object(subprocess, "Popen", side_effect=AssertionError("a Controller must start no process")):
            core = Controller()
            try:
                core.dispatch({"op": "new", "name": "No probe"})
            finally:
                for doc in list(core.documents.values()):
                    if core._is_open(doc):
                        App.closeDocument(doc.Name)
                core.close()
            probe.assert_not_called()
            bridge = Bridge(self.core, self.folder, request_timeout=2)
            try:
                probe.assert_called_once_with()
            finally:
                bridge.close()
                bridge.thread.join(timeout=2)

    def test_canonical_http_status_and_replay_preserve_real_controller_state_without_tick(self):
        from native_validation_snapshot import snapshot_document
        self.plate()
        request = self.request("set_parameter", feature="Pad", parameter="Length", value=8,
                               request_id="http-completed-edit")
        first = self.core.dispatch(request)
        self.assertTrue(first["ok"], first)
        self.state = first["result"]
        self.call("set_parameter", feature="Pad", parameter="Length", value=9)
        expected = {"ok": True, "result": self.core.ledger.status(request["request_id"])}
        expected_http = dict(expected, queue_wait_ms=0.0)
        self.assertEqual(expected["result"]["response"], first)
        self.assertIn("operation_ms", first["result"])
        state_before = self.core.inspect(self.doc)
        snapshot_document(self.doc, self.core)  # Prime native datum/BRep getters.
        native_before = snapshot_document(self.doc, self.core)["strict"]
        timings_before = self.core.timings.report()
        bridge = Bridge(self.core, self.folder, request_timeout=2)
        try:
            with ExitStack() as stack:
                sentinels = [stack.enter_context(patch.object(target, name,
                    side_effect=AssertionError("Canonical status touched " + name)))
                    for target, name in ((bridge, "tick"), (self.core, "dispatch"),
                        (self.core, "_dispatch"), (self.core, "_prune_closed_sketch_edits"),
                        (self.core.timings, "measure"), (self.core.timings, "record"))]
                self.core.busy = True
                for default in (False, True, "full"):
                    self.core.default_measure = default
                    actual = self._status_http(bridge, {"op": "request_status", "request_id": request["request_id"]})
                    self.assertEqual(actual, expected_http)
                    self.assertEqual(actual["queue_wait_ms"], 0.0)
                actual["result"]["response"]["result"]["measurements"]["volume_mm3"] = -1
                actual["result"]["response"]["result"]["features"].append({"id": "client-only"})
                self.assertEqual(self._status_http(bridge, {"op": "request_status", "request_id": request["request_id"]}), expected_http)
                replay = self._status_http(bridge, request)
                self.assertEqual(replay, first)
                replay["result"]["measurements"]["volume_mm3"] = -2
                self.assertEqual(self._status_http(bridge, request), first)
                for sentinel in sentinels:
                    sentinel.assert_not_called()
                self.assertTrue(bridge.pending.empty())
        finally:
            self.core.busy = False
            self.core.default_measure = True
            bridge.close()
            bridge.thread.join(timeout=2)
        self.assertFalse(bridge.thread.is_alive())
        self.assertEqual(self.core.timings.report(), timings_before)
        self.assertEqual(self.core.ledger.status(request["request_id"]), expected["result"])
        self.assertEqual(snapshot_document(self.doc, self.core)["strict"], native_before)
        self.assertEqual(self.core.inspect(self.doc), state_before)
        self.assertEqual(snapshot_document(self.doc, self.core)["strict"], native_before)
        self.assertAlmostEqual(self.doc.Pad.Length.Value, 9)

    def test_noncanonical_http_status_keeps_owner_validation_and_default_measure_semantics(self):
        from native_validation_snapshot import snapshot_document
        self.plate()
        request = self.request("set_parameter", feature="Pad", parameter="Length", value=8,
                               request_id="http-fallback-edit")
        response = self.core.dispatch(request)
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        canonical = {"op": "request_status", "request_id": request["request_id"]}
        cases = [("missing-id", True, {"op": "request_status"})]
        cases += [("id-" + repr(value), True, {"op": "request_status", "request_id": value})
                  for value in (None, 17, False, True, "", "x" * 129)]
        cases += [("measure-" + repr(value), True, dict(canonical, measure=value))
                  for value in (False, True, "full", None, 1, "invalid")]
        cases += [
            ("unknown-before-measure", True, dict(canonical, measure=None, unknown=True)),
            ("ignored-context", True, dict(canonical, document_id={"ignored": True}, expected_revision=["ignored"])),
            ("ignored-context-and-valid-measure", False, dict(canonical, document_id=None, expected_revision=False, measure=True)),
        ]
        for value in (None, 1, "invalid", [], {}):
            cases.append(("invalid-default-" + repr(value), value, dict(canonical)))
            cases.append(("explicit-overrides-default-" + repr(value), value, dict(canonical, measure=False)))
        missing_default = object()
        cases += [("missing-default", missing_default, dict(canonical)),
                  ("explicit-overrides-missing-default", missing_default, dict(canonical, measure=False))]
        state_before = self.core.inspect(self.doc)
        snapshot_document(self.doc, self.core)
        native_before = snapshot_document(self.doc, self.core)["strict"]
        bridge = Bridge(self.core, self.folder, request_timeout=2)
        try:
            for label, default, payload in cases:
                with self.subTest(case=label):
                    if default is missing_default:
                        self.core.__dict__.pop("default_measure", None)
                    else:
                        self.core.default_measure = default
                    expected = self.core.dispatch(deepcopy(payload))
                    actual = self._queued_status_on_owner(bridge, payload)
                    queue_ms = actual.pop("queue_wait_ms")
                    self.assertIsInstance(queue_ms, (int, float))
                    self.assertTrue(math.isfinite(queue_ms) and queue_ms >= 0)
                    self.assertEqual(actual, expected)
                    if label == "unknown-before-measure":
                        self.assertEqual(actual["error"]["code"], "unknown_argument")
        finally:
            self.core.default_measure = True
            bridge.close()
            bridge.thread.join(timeout=2)
        self.assertFalse(bridge.thread.is_alive())
        self.assertEqual(snapshot_document(self.doc, self.core)["strict"], native_before)
        self.assertEqual(self.core.inspect(self.doc), state_before)
        self.assertEqual(snapshot_document(self.doc, self.core)["strict"], native_before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
