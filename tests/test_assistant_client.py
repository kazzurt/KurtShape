"""Contract 3.2 U8 (F5 §6.3): client reconciliation against the real loopback Bridge.

A fake controller (no FreeCAD) owns a real RequestLedger and the queue-bypassing status lookup;
a ticker thread plays the GUI owner thread. Each test is one reconciliation case of the design
probe (client3.json): the outcome the client reports decides the caller's next action, so a
mutation is never reported not_executed unless it provably never started.
"""
import json
import math
from pathlib import Path
import socket
import sys
import threading
import time
import unittest
from unittest.mock import patch

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
import assistant_client as client
from kurtshape import build_identity
from kurtshape.bridge import Bridge
from kurtshape.request_ledger import RequestLedger, RequestStatusLookup


class LedgerController:
    """The controller surface the bridge uses: READ_OPS, ledger, status lookup and dispatch."""
    READ_OPS = {"request_status", "inspect", "capabilities"}
    NON_MUTATING_OPS = READ_OPS | {"render_view"}

    def __init__(self):
        self.ledger = RequestLedger()
        self.default_measure = True
        self.request_status_lookup = RequestStatusLookup(self.ledger, self.__dict__)
        self.runs = []
        self.delay = 0.0
        self.before = None  # callable run at the start of a mutation (crash, token change, ...)
        self.build = None

    def dispatch(self, request):
        op = request.get("op")
        if op == "request_status":
            return {"ok": True, "result": self.ledger.status(request.get("request_id"))}
        if op == "capabilities":
            return {"ok": True, "result": {"build": self.build}}
        if op == "inspect":
            time.sleep(self.delay)
            return {"ok": True, "result": {"document_id": "D"}}
        replay = self.ledger.register(request, "started")
        if replay is not None:
            return replay
        if self.before:
            self.before()
        self.runs.append(request.get("request_id"))
        time.sleep(self.delay)
        response = ({"ok": False, "error": {"code": "build_failed", "message": "failed on purpose"}} if op == "fail"
                    else {"ok": True, "result": {"op": op, "run": len(self.runs)}})
        self.ledger.complete(request["request_id"], response)
        return response


class AssistantClientReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.folder = support.scratch(self, prefix="assistant-client-")
        self.controller = LedgerController()
        self.bridge = Bridge(self.controller, self.folder, request_timeout=0.15)
        self.session = self.folder / "assistant-session.json"
        self.paused = threading.Event()
        self.stopping = threading.Event()
        self.ticker = threading.Thread(target=self.tick, daemon=True)
        self.ticker.start()
        self.addCleanup(self.stop)

    def tick(self):
        while not self.stopping.is_set():
            if not self.paused.is_set():
                self.bridge.tick()
            time.sleep(0.005)

    def stop(self):
        self.stopping.set()
        self.ticker.join(5)
        try:
            self.bridge.close()
        except OSError:
            pass

    def send(self, request, **options):
        options.setdefault("wait", 15.0)
        return client.send(request, self.session, **options)

    def block(self, result):
        return result.get("reconciliation") or {}

    def test_outcome_unknown_polls_until_completed_and_returns_stored_response(self):
        self.controller.delay = 0.5
        request = {"op": "mutate", "value": 1}
        result = self.send(request)
        self.assertTrue(result["ok"], result)
        self.assertEqual((self.block(result)["outcome"], self.block(result)["status"]), ("completed", "completed"))
        self.assertEqual(self.block(result)["request_id"], request["request_id"], "the id never changes")
        self.assertEqual(result["result"]["run"], 1)
        self.assertEqual(self.controller.runs, [request["request_id"]])
        self.assertEqual(client.exit_code(result), 0)

    def test_failed_outcome_reports_failed(self):
        self.controller.delay = 0.4
        result = self.send({"op": "fail"})
        self.assertEqual((self.block(result)["outcome"], result["error"]["code"]), ("failed", "build_failed"))
        self.assertEqual(client.exit_code(result), 1)

    def test_queued_timeout_reports_not_executed_and_never_resends(self):
        self.paused.set()
        request = {"op": "mutate"}
        result = self.send(request)
        self.assertEqual((self.block(result)["outcome"], self.block(result)["reason"]), ("not_executed", "timeout"))
        self.assertNotIn("polls", self.block(result))
        self.paused.clear()
        time.sleep(0.2)
        self.assertEqual(self.controller.runs, [], "a request cancelled in the queue never starts")
        self.assertEqual(self.controller.ledger.status(request["request_id"])["status"], "cancelled")
        self.assertEqual(client.exit_code(result), 4)

    def test_queue_full_503_reports_not_executed(self):
        self.paused.set()
        for _ in range(32):
            self.bridge.pending.put_nowait(object())
        result = self.send({"op": "mutate"})
        self.assertEqual((self.block(result)["outcome"], self.block(result)["reason"]), ("not_executed", "queue_full"))
        while not self.bridge.pending.empty():
            self.bridge.pending.get_nowait()

    def test_a_short_budget_gives_the_first_post_time_to_answer(self):
        # Fable review R2 (2026-10-19): wait=2 gave the first POST 0.2 s, so a 0.6 s operation was
        # abandoned (the bridge then wrote to a dead socket) and only reconciliation found the answer.
        self.bridge.request_timeout = 5.0
        self.controller.delay = 0.6
        request = {"op": "mutate"}
        result = self.send(request, wait=2.0)
        self.assertTrue(result["ok"], result)
        self.assertNotIn("reconciliation", result, "answered by the first POST")
        self.assertEqual(self.controller.runs, [request["request_id"]])
        # A slower operation still leaves room for status polls: pending, not unknown.
        self.controller.delay = 3.0
        result = self.send({"op": "mutate"}, wait=2.0)
        self.assertEqual((self.block(result)["outcome"], self.block(result)["status"]), ("pending", "started"))
        self.assertGreaterEqual(self.block(result)["polls"], 1)
        time.sleep(3.2)  # let the owner thread finish before tearDown

    def test_pending_past_deadline_reports_pending(self):
        self.controller.delay = 3.0
        result = self.send({"op": "mutate"}, wait=1.0)
        self.assertEqual((self.block(result)["outcome"], result["error"]["code"], self.block(result)["status"]),
                         ("pending", "outcome_pending", "started"))
        self.assertEqual(client.exit_code(result), 2)

    def test_session_file_rewrite_does_not_disturb_reconciliation(self):
        self.controller.delay = 0.6
        original = self.session.read_text(encoding="utf-8")

        def rewrite():
            time.sleep(0.25)
            self.session.write_text(json.dumps(dict(json.loads(original), token="other", url="http://127.0.0.1:9/operation")),
                                    encoding="utf-8")
        threading.Thread(target=rewrite, daemon=True).start()
        result = self.send({"op": "mutate"})
        self.assertEqual(self.block(result)["outcome"], "completed", result)
        self.session.write_text(original, encoding="utf-8")

    def test_app_crash_reports_unreachable_unknown_before_deadline(self):
        self.controller.delay = 0.3
        server = self.bridge.server

        def crash():
            server.shutdown()
            server.server_close()
        self.controller.before = crash
        started = time.monotonic()
        result = self.send({"op": "mutate"}, wait=30.0, unreachable_after=0.5)
        self.assertEqual((self.block(result)["outcome"], self.block(result)["reason"]), ("unknown", "unreachable"), result)
        self.assertLess(time.monotonic() - started, 30.0)
        self.assertEqual(client.exit_code(result), 3)
        self.bridge.close = lambda: None  # the server is already gone

    def test_poll_403_reports_session_ended(self):
        self.controller.delay = 0.4
        self.controller.before = lambda: setattr(self.bridge, "token", "another-bridge")
        result = self.send({"op": "mutate"})
        self.assertEqual((self.block(result)["outcome"], self.block(result)["reason"]), ("unknown", "session_ended"))

    def test_status_session_id_mismatch_reports_unknown(self):
        self.controller.delay = 0.4
        self.controller.before = lambda: setattr(self.controller.ledger, "session_id", "restarted")
        result = self.send({"op": "mutate"})
        self.assertEqual((self.block(result)["outcome"], self.block(result)["reason"]), ("unknown", "session_changed"))

    def test_lost_post_resends_identical_request_once_same_session(self):
        post = client._post
        bodies = []

        def lose_first(url, token, body, timeout):
            bodies.append(body)
            if len(bodies) == 1:
                return "transport", None, "ConnectionResetError()"  # the request never reached the bridge
            return post(url, token, body, timeout)
        with patch.object(client, "_post", side_effect=lose_first):
            result = self.send({"op": "mutate", "value": 7})
        self.assertEqual((self.block(result)["outcome"], self.block(result)["resent"]), ("completed", True), result)
        self.assertEqual(len(self.controller.runs), 1)
        resent = [body for body in bodies if json.loads(body).get("op") == "mutate"]
        self.assertEqual(len(resent), 2)
        self.assertEqual(resent[0], resent[1], "the resend is byte-identical")

    def test_expired_status_and_request_expired_reply_are_unknown(self):
        self.controller.ledger.expired["gone"] = True
        result = self.send({"op": "mutate", "request_id": "gone"})
        self.assertEqual((self.block(result)["outcome"], self.block(result)["reason"]), ("unknown", "expired"))
        result = client.reconcile_request("gone", self.session, wait=5.0)
        self.assertEqual((self.block(result)["outcome"], self.block(result)["reason"]), ("unknown", "expired"))
        self.assertEqual(self.controller.runs, [])

    def test_invalid_request_and_oversize_are_rejected_without_polls(self):
        with patch.object(client, "_reconcile", side_effect=AssertionError("no reconciliation")):
            result = self.send({"op": "mutate", "value": math.nan})
            self.assertEqual(result["error"]["code"], "invalid_request")
            self.assertNotIn("reconciliation", result)
            result = self.send({"op": "mutate", "blob": "x" * (client.REQUEST_SIZE_LIMIT + 1)})
            self.assertEqual(result["error"]["code"], "request_too_large")
        self.assertEqual(self.controller.runs, [])
        self.assertEqual(client.exit_code(result), 1)

    def test_refused_initial_connect_is_not_executed(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.close()
        dead = self.folder / "dead-session.json"
        dead.write_text(json.dumps(dict(json.loads(self.session.read_text(encoding="utf-8")),
                                        url="http://127.0.0.1:%d/operation" % port)), encoding="utf-8")
        result = client.send({"op": "mutate"}, dead, wait=10.0)
        self.assertEqual((self.block(result)["outcome"], self.block(result)["reason"]), ("not_executed", "unreachable"))
        self.assertEqual(client.exit_code(result), 4)

    def test_read_transport_failure_is_retry_safe(self):
        self.controller.delay = 0.5
        result = self.send({"op": "inspect"})
        self.assertEqual((self.block(result)["outcome"], self.block(result)["retry_safe"]), ("unknown", True))
        self.assertIsNone(self.block(result)["request_id"], "reads are never given a request_id")
        self.assertEqual(client.exit_code(result), 4)

    def test_unrecorded_render_view_is_retry_safe(self):
        """A tracked view op gets a request_id and reconciles; an unknown outcome is still safe to retry."""
        post = client._post
        calls = []

        def lose_first(url, token, body, timeout):
            calls.append(body)
            if len(calls) == 1:
                return "transport", None, "ConnectionResetError()"
            return post(url, token, body, timeout)
        request = {"op": "render_view", "size": [320, 240]}
        with patch.object(client, "_post", side_effect=lose_first):
            result = self.send(request, wait=4.0, resend=False)
        self.assertIn("request_id", request, "a view op is tracked")
        self.assertEqual((self.block(result)["outcome"], self.block(result)["reason"], self.block(result)["retry_safe"]),
                         ("unknown", "not_recorded", True))
        self.assertEqual(client.exit_code(result), 4)

    def test_reconcile_resends_only_into_the_verified_session(self):
        body = {"op": "mutate", "request_id": "elsewhere", "value": 1}
        result = client.reconcile_request("elsewhere", self.session, wait=3.0, body=body, session_id="an-earlier-session")
        self.assertEqual((self.block(result)["outcome"], self.block(result)["reason"]), ("unknown", "session_changed"))
        result = client.reconcile_request("elsewhere", self.session, wait=3.0, body=body)
        self.assertEqual((self.block(result)["reason"], self.block(result)["resent"]), ("not_recorded", False),
                         "without --session-id a body is never re-sent")
        sid = json.loads(self.session.read_text(encoding="utf-8"))["session_id"]
        result = client.reconcile_request("elsewhere", self.session, wait=6.0, body=body, session_id=sid)
        self.assertEqual((self.block(result)["outcome"], self.block(result)["resent"]), ("completed", True))
        self.assertEqual(self.controller.runs, ["elsewhere"])

    def test_transport_failures_never_raise(self):
        with patch.object(client, "_post", return_value=("transport", None, "ConnectionResetError()")):
            result = self.send({"op": "inspect"})
        self.assertEqual((self.block(result)["outcome"], self.block(result)["retry_safe"]), ("unknown", True))
        import http.client
        with patch("urllib.request.OpenerDirector.open", side_effect=http.client.IncompleteRead(b"partial")):
            kind, status, payload = client._post("http://127.0.0.1:9/operation", "t", b"{}", 1.0)
        self.assertEqual(kind, "transport")
        self.bridge.token = "rotated"  # a 403 (HTML) before registration
        result = self.send({"op": "mutate"})
        self.assertEqual(result["error"]["code"], "forbidden")
        self.assertNotIn("reconciliation", result)

    def test_status_polls_use_canonical_queue_bypassing_shape(self):
        self.paused.set()  # the owner thread is blocked: only the bypass can answer
        result = client.status("never-sent", self.session, timeout=2.0)
        self.assertEqual((result["ok"], result["result"]["status"]), (True, "not_recorded"))
        self.assertTrue(self.bridge.pending.empty(), "nothing was queued for the owner")
        bodies = []
        post = client._post
        with patch.object(client, "_post", side_effect=lambda *a: (bodies.append(json.loads(a[2])), post(*a))[1]):
            client.reconcile_request("never-sent", self.session, wait=1.5)
        self.assertTrue(bodies)
        self.assertTrue(all(body == {"op": "request_status", "request_id": "never-sent"} for body in bodies), bodies)

    def run_cli(self, *arguments):
        with patch("sys.stdout"), patch("sys.stderr"):
            return client.main([*arguments, "--session", str(self.session), "--wait", "10"])

    def test_cli_exit_codes_request_id_replay_and_reconcile_by_id(self):
        body = json.dumps({"op": "mutate", "value": 3})
        self.assertEqual(self.run_cli("--json", body, "--request-id", "cli-1"), 0)
        self.assertEqual(self.run_cli("--json", body, "--request-id", "cli-1"), 0, "an identical rerun replays")
        self.assertEqual(self.controller.runs, ["cli-1"])
        self.assertEqual(self.run_cli("--json", json.dumps({"op": "mutate", "value": 4}), "--request-id", "cli-1"), 1,
                         "another payload under the same id is rejected")
        self.assertEqual(self.run_cli("--reconcile", "--request-id", "cli-1"), 0)
        self.assertEqual(self.run_cli("--status", "cli-1"), 0)
        self.assertEqual(self.run_cli("--json", json.dumps({"op": "fail"})), 1)
        self.paused.set()
        self.assertEqual(self.run_cli("--json", json.dumps({"op": "mutate", "value": 5})), 4)
        self.paused.clear()
        with patch("sys.stdout"):
            # Nothing was sent: a request without a session file is safe to retry (4); --build-check says 3.
            self.assertEqual(client.main(["--json", body, "--session", str(self.folder / "missing.json")]), 4)
            self.assertEqual(client.main(["--build-check", "--session", str(self.folder / "missing.json")]), 3)
        for arguments in (("--json", json.dumps({"op": "mutate", "request_id": "a"}), "--request-id", "b"),
                          ("--reconcile",), ("--json", "{not json"), ("--json", "[1, 2]")):
            with self.subTest(arguments=arguments), patch("sys.stderr"), patch("sys.stdout"):
                with self.assertRaises(SystemExit) as raised:
                    client.main([*arguments, "--session", str(self.session)])
                self.assertEqual(raised.exception.code, client.USAGE, "usage errors are not 'pending' (2)")

    def test_cli_build_check_verdicts(self):
        package = ROOT / "src" / "kurtshape"
        checkout = build_identity.snapshot(package)
        self.controller.build = {"source_dir": checkout["directory"], "source_sha256": checkout["sha256"],
                                 "id": checkout["id"]}
        self.assertEqual(client.build_check(self.session)["verdict"], "current")
        self.assertEqual(self.run_cli("--build-check"), 0)
        self.controller.build = dict(self.controller.build, source_sha256="0" * 64)
        self.assertEqual(client.build_check(self.session)["verdict"], "stale")
        self.assertEqual(self.run_cli("--build-check"), 1)
        self.controller.build = dict(self.controller.build, source_dir=str(self.folder))
        self.assertEqual(client.build_check(self.session)["verdict"], "different_tree")
        self.controller.build = None
        self.assertEqual(client.build_check(self.session)["verdict"], "unknown")

    def test_discovery_is_explicit_token_free_and_does_not_guess_old_visibility(self):
        session = json.loads(self.session.read_text())
        session.pop("launch", None)
        self.session.write_text(json.dumps(session))
        calls = []
        def fake(request, session_path=None, **kwargs):
            calls.append(request)
            if request["op"] == "capabilities":
                return {"ok": True, "result": {"session_id": session["session_id"], "build": {"id": "test"}}}
            return {"ok": True, "result": {"documents": [{"document_id": "D", "native_file": "fixture.FCStd"}]}}
        with patch.object(client, "ROOT", self.folder), patch.object(client, "default_session_path", return_value=self.session), patch.object(client, "send", side_effect=fake):
            rows = client.discover_sessions([self.folder])
        row = next(row for row in rows if row["session_file"] == str(self.session.resolve()))
        self.assertTrue(row["live"])
        self.assertEqual(row["visibility"], "unknown")
        self.assertNotIn(session["token"], json.dumps(rows))
        self.assertEqual({request["op"] for request in calls}, {"capabilities", "list_documents"})

    def test_open_requires_nonblank_session_before_reading_credentials(self):
        target = self.folder / "fixture.FCStd"
        with patch.object(client, "_session") as read_session, patch.object(client, "send") as send:
            for invalid in (None, "", " ", "\t\r\n", False):
                with self.subTest(session_path=invalid), self.assertRaisesRegex(ValueError, "explicit session_path"):
                    client.open_in_session(target, invalid)
            read_session.assert_not_called()
            send.assert_not_called()

    def test_open_and_fit_requires_selection_pins_identity_and_reuses_document(self):
        session = json.loads(self.session.read_text())
        target = self.folder / "fixture.FCStd"
        calls = []
        def fake(request, session_path=None, **kwargs):
            calls.append(request)
            if request["op"] == "list_documents":
                return {"ok": True, "result": {"documents": [{"document_id": "D", "revision": "r", "native_file": str(target)}]}}
            return {"ok": True, "result": {"applied": True}}
        with self.assertRaises(ValueError):
            client.open_in_session(target, None)
        with patch.object(client, "send", side_effect=fake):
            changed = client.open_in_session(target, self.session, expected_session_id="different")
            self.assertEqual(changed["error"]["code"], "session_changed")
            self.assertEqual(calls, [])
            result = client.open_in_session(target, self.session, expected_session_id=session["session_id"])
        self.assertTrue(result["ok"])
        self.assertTrue(result["reused_document"])
        self.assertEqual([request["op"] for request in calls], ["list_documents", "set_view"])
        self.assertEqual(calls[-1]["document_id"], "D")
        self.assertEqual(calls[-1]["frame"], "model")
        with patch("sys.stderr"), patch("sys.stdout"):
            with self.assertRaises(SystemExit) as raised:
                client.main(["--open", str(target)])
            self.assertEqual(raised.exception.code, client.USAGE)

    def test_open_unknown_is_not_retried_or_followed_by_view(self):
        calls = []
        def fake(request, session_path=None, **kwargs):
            calls.append(request)
            if request["op"] == "list_documents":
                return {"ok": True, "result": {"documents": []}}
            return {"ok": False, "error": {"code": "outcome_unknown"},
                    "reconciliation": {"outcome": "unknown", "request_id": request["request_id"]}}
        with patch.object(client, "send", side_effect=fake):
            result = client.open_in_session(self.folder / "fixture.FCStd", self.session)
        self.assertEqual(client.exit_code(result), 3)
        self.assertEqual([request["op"] for request in calls], ["list_documents", "open"])
        self.assertEqual(result["reconciliation"]["request_id"], calls[-1]["request_id"])


if __name__ == "__main__":
    unittest.main()
