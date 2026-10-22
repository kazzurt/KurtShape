"""kurtshape.session (slice A/B U4): the shared headless / bridge session SDK.

In-process tests run with FreeCAD already imported by this module, so the SDK takes its
"inherited" isolation path (the runner's private profile; only KURTSHAPE_SESSION_DIR is set
and restored). The "fresh" path (the six variables set before FreeCAD loads), the TEMP
length refusal and the FreeCAD-free bridge import are checked in one fresh child process.
The bridge transport runs through tools/assistant_client.py send with its HTTP layer
replaced by an in-process Controller, and through scripted fakes for the failure paths.
The Rev B excerpt compares a geometry digest with the 2026-10-20 STEP in the Dodec tree.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch
import uuid

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
# Imported first on purpose: in-process Sessions must take the inherited path, never re-point
# the runner's own profile variables.
import FreeCAD as App
import Part
from kurtshape import session as sdk
from kurtshape.core import Controller
from kurtshape.session import (IsolationError, OperationFailed, PartNotFound, SelectorError, Session, SessionError,
                               StaleRevision)

REVB = Path(r"C:\Users\Kurtz\Documents\Dodec\Commercial design trade study"
            r"\Conformal hub machining fixture Rev B 2026-10-20")
REVB_M8_STEP = REVB / "fixture-components" / "revb_pedestal_M8x16_screw_1.step"


def ledger(session):
    return [json.loads(line) for line in session.ledger_path.read_text(encoding="utf-8").splitlines()]


def sent(session, op):
    return [record["request"] for record in ledger(session) if record["event"] == "sent" and record["request"]["op"] == op]


def done(session, op=None):
    return [record for record in ledger(session) if record["event"] == "done" and (op is None or record["op"] == op)]


def _round(value):
    value = round(float(value), 6)
    return 0.0 if value == 0 else value


def step_digest(path):
    """The gate's digest: volume, area, centre of mass, box, counts and sorted vertices at 1e-6 mm."""
    shape = Part.read(str(path))
    solids = shape.Solids
    total = sum(solid.Volume for solid in solids)
    com = ([sum(solid.Volume * getattr(solid.CenterOfMass, axis) for solid in solids) / total for axis in "xyz"]
           if solids and total else [0.0, 0.0, 0.0])
    box = shape.BoundBox
    facts = {"volume": _round(shape.Volume), "area": _round(shape.Area), "center_of_mass": [_round(c) for c in com],
             "bbox": [_round(v) for v in (box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax)],
             "solids": len(solids), "faces": len(shape.Faces), "edges": len(shape.Edges),
             "vertices": len(shape.Vertexes),
             "vertex_coordinates": sorted([_round(v.X), _round(v.Y), _round(v.Z)] for v in shape.Vertexes)}
    return hashlib.sha256(json.dumps(facts, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


class FakeBridge:
    """A scripted bridge `send`: an old server (no operation_schema) holding one document."""

    READ = ["inspect", "list_documents", "capabilities", "request_status", "preview", "diagnostics",
            "assembly_candidates", "resolve_selector", "check_geometry", "orphan_helpers"]

    def __init__(self, stale=(), replies=None):
        self.requests = []
        self.paths = []
        self.revision = 0
        self.stale = set(stale)
        self.replies = dict(replies or {})

    def inspection(self):
        return {"document_id": "doc-1", "revision": f"r{self.revision}", "features": [], "bodies": [],
                "studio": {"enabled": False, "feature_order": [], "rollback_index": 0, "parts": []}}

    def __call__(self, request, session_path=None, wait=None):
        self.requests.append(json.loads(json.dumps(request)))
        self.paths.append(session_path)
        op = request["op"]
        if op in self.replies:
            return self.replies[op]
        if op == "capabilities":
            return {"ok": True, "result": {"read_operations": self.READ,
                                           "non_mutating_operations": self.READ + ["render_view", "set_view"]}}
        if op == "operation_schema":
            return {"ok": False, "error": {"code": "unsupported_operation", "message": "Unknown operation"}}
        if op in {"new", "inspect"}:
            return {"ok": True, "result": self.inspection()}
        if op in self.stale:
            self.revision += 1  # another writer keeps moving the document
            return {"ok": False, "error": {"code": "stale_revision", "message": "Inspect the current document"}}
        if request.get("expected_revision") != f"r{self.revision}" and op not in self.READ:
            return {"ok": False, "error": {"code": "stale_revision", "message": "Inspect the current document"}}
        if op not in self.READ:
            self.revision += 1
        return {"ok": True, "result": dict(self.inspection(), base_revision=request.get("expected_revision"))}


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.initial = set(App.listDocuments())
        self.session_dir = os.environ.get("KURTSHAPE_SESSION_DIR")
        # Registered first, so it runs after every Session.close cleanup a test adds.
        self.addCleanup(self.after_sessions)

    def after_sessions(self):
        for name in set(App.listDocuments()) - self.initial:
            App.closeDocument(name)
        self.assertEqual(os.environ.get("KURTSHAPE_SESSION_DIR"), self.session_dir)

    def short_root(self):
        # A short private root under runtime\test-tmp (the suite's run folder is longer than TEMP allows).
        base = ROOT / "runtime" / "test-tmp"
        base.mkdir(parents=True, exist_ok=True)
        folder = Path(tempfile.mkdtemp(prefix="ses-", dir=base)).resolve()
        self.addCleanup(shutil.rmtree, folder, True)
        return folder

    def headless(self, **kwargs):
        session = Session.headless(root=self.short_root(), **kwargs)
        self.addCleanup(session.close)
        return session

    def pin(self, session, name="Pin"):
        session.call("new", name=name)
        return session.circle("Pin", (0, 0, 0), 10, 5, name=name)

    def out_of_band_change(self, session, stem):
        # A writer the SDK does not see: the Controller directly, with the true current revision.
        response = session.controller.dispatch({
            "op": "create_plane", "document_id": session.document_id, "expected_revision": session.revision,
            "id": stem, "body": "Body", "origin": [0, 0, 40], "normal": [0, 0, 1], "x_direction": [1, 0, 0]})
        self.assertTrue(response["ok"], response)
        return response["result"]["revision"]

    # -- isolation ----------------------------------------------------------------------------

    def test_refuses_the_live_runtime_and_profile_before_creating_anything(self):
        for root in (sdk.LIVE_RUNTIME, sdk.LIVE_USER_DATA, sdk.LIVE_USER_DATA / "sdk-session-test"):
            with self.subTest(root=str(root)):
                with self.assertRaises(IsolationError):
                    Session.headless(root=root)
        self.assertFalse((sdk.LIVE_USER_DATA / "sdk-session-test").exists())
        self.assertEqual(os.environ.get("KURTSHAPE_SESSION_DIR"), self.session_dir)
        with self.assertRaises(IsolationError):
            Session.headless(root=self.short_root(), project_roots=["relative\\grant"])

    def test_inherited_mode_requires_freecad_user_home_outside_the_live_profile(self):
        root = self.short_root()
        without = {name: value for name, value in os.environ.items() if name != "FREECAD_USER_HOME"}
        with patch.dict(os.environ, without, clear=True):
            with self.assertRaises(IsolationError):
                Session.headless(root=root)
        with patch.dict(os.environ, {"FREECAD_USER_HOME": str(sdk.LIVE_USER_DATA)}):
            with self.assertRaises(IsolationError) as caught:
                Session.headless(root=root)
        self.assertIn("FREECAD_USER_HOME", str(caught.exception))
        self.assertFalse((root / "session").exists())  # refused before anything was written
        self.assertEqual(os.environ.get("KURTSHAPE_SESSION_DIR"), self.session_dir)

    def test_a_close_failure_does_not_mask_the_with_body_exception(self):
        with self.assertRaises(ValueError) as caught:
            with Session.headless(root=self.short_root()) as s:
                real_close = s.controller.close

                def failing_close():
                    real_close()
                    raise RuntimeError("controller close broke")
                s.controller.close = failing_close
                s.call("new", name="Body raises")
                raise ValueError("the with-body failed")
        self.assertEqual(str(caught.exception), "the with-body failed")
        self.assertTrue(any("controller close broke" in note for note in getattr(caught.exception, "__notes__", [])))
        self.assertIn("close failed after an exception in the with-body", s.log_path.read_text(encoding="utf-8"))
        self.assertTrue(s.closed)

    def test_inherited_isolation_points_the_controller_at_the_private_root_and_restores(self):
        root = self.short_root()
        grant = self.short_root()
        with Session.headless(root=root, project_roots=[grant]) as s:
            self.assertEqual(s.isolation["mode"], "inherited")
            # Inherited TEMP is left alone; one over the preview-clone limit is only recorded.
            self.assertEqual(bool(s.isolation["warnings"]), len(tempfile.gettempdir()) > sdk.TEMP_PATH_LIMIT)
            self.assertEqual(os.environ["KURTSHAPE_SESSION_DIR"], str(root / "session"))
            self.assertEqual(s.controller.settings.path, root / "session" / "settings.json")
            settings = json.loads((root / "session" / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(settings, {"workspace_layout": "portable", "project_roots": [str(root), str(grant)]})
            self.assertTrue({root, grant} <= s.controller.settings.roots)
            self.assertNotIn(sdk.LIVE_RUNTIME / "user-data", [Path(App.getUserAppDataDir()).resolve()])
            first = s.call("new", name="One")["document_id"]
            second = s.call("new", name="Two")["document_id"]
            self.assertEqual(s.document_id, second)
            self.assertEqual(set(s.created), {first, second})
            controller = s.controller
        self.assertEqual(os.environ.get("KURTSHAPE_SESSION_DIR"), self.session_dir)
        self.assertEqual(controller.documents, {})
        self.assertTrue(s.closed)
        s.close()  # idempotent
        with self.assertRaises(SessionError):
            s.call("capabilities")
        self.assertEqual([record["request"]["discard"] for record in ledger(s)
                          if record["event"] == "sent" and record["request"]["op"] == "close_document"], [True, True])
        closes = done(s, "close_document")
        self.assertEqual({record["document_id"] for record in closes}, {first, second})
        self.assertEqual([record["discarded_unsaved_changes"] for record in closes], [True, True])
        self.assertTrue(all(record["recovery_manifest"] for record in closes))

    def test_fresh_process_sets_the_profile_before_freecad_and_the_bridge_needs_no_freecad(self):
        root = self.short_root()
        script = root / "fresh_child.py"
        long_root = root / ("x" * 60)
        script.write_text(textwrap.dedent(f"""
            import json, os, sys, tempfile
            sys.path.insert(0, {str(ROOT / "src")!r})
            out = {{}}
            import kurtshape.session as ks
            out["freecad_after_import"] = "FreeCAD" in sys.modules or "kurtshape.core" in sys.modules
            def fake(request, session_path=None, wait=None):
                if request["op"] == "capabilities":
                    return {{"ok": True, "result": {{"read_operations": ["capabilities"]}}}}
                return {{"ok": False, "error": {{"code": "unsupported_operation", "message": "Unknown operation"}}}}
            bridge = ks.Session.bridge(root={str(root / "bridge")!r}, send=fake)
            out["bridge_envelope"] = list(bridge.envelope("pad"))
            out["freecad_after_bridge"] = "FreeCAD" in sys.modules or "kurtshape.core" in sys.modules
            try:
                ks.Session.headless(root={str(long_root)!r})
                out["long_root"] = "accepted"
            except ks.IsolationError as exc:
                out["long_root"] = str(exc)
            out["long_root_created"] = os.path.exists({str(long_root)!r})
            out["freecad_after_refusal"] = "FreeCAD" in sys.modules
            s = ks.Session.headless(root={str(root / "fresh")!r})
            import FreeCAD
            out["isolation"] = s.isolation
            out["environment"] = {{name: os.environ.get(name) for name in ks.ISOLATION_VARIABLES}}
            out["tempdir"] = tempfile.gettempdir()
            out["user_data"] = FreeCAD.getUserAppDataDir()
            out["settings_path"] = str(s.controller.settings.path)
            out["document"] = s.call("new", name="Fresh")["document_id"] == s.document_id
            s.close()
            print("RESULT " + json.dumps(out))
            """), encoding="utf-8")
        completed = support.run_native_proof([sys.executable, "-B", str(script)], capture_output=True, text=True,
                                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=300)
        lines = [line for line in completed.stdout.splitlines() if line.startswith("RESULT ")]
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(len(lines), 1, completed.stdout + completed.stderr)
        out = json.loads(lines[0][len("RESULT "):])
        fresh = root / "fresh"
        self.assertFalse(out["freecad_after_import"])
        self.assertFalse(out["freecad_after_bridge"])
        self.assertEqual(out["bridge_envelope"], [True, True])  # fallback classes: pad needs both
        self.assertIn("104", out["long_root"])
        self.assertFalse(out["long_root_created"])
        self.assertFalse(out["freecad_after_refusal"])
        self.assertEqual(out["isolation"]["mode"], "fresh")
        self.assertEqual(out["isolation"]["warnings"], [])
        expected = {name: str(fresh / child) for name, child in sdk.LAYOUT.items()}
        self.assertEqual(out["environment"], expected)
        self.assertEqual(Path(out["tempdir"]).resolve(), fresh / "temporary")
        self.assertTrue(Path(out["user_data"]).resolve().is_relative_to(fresh / "user-data"), out["user_data"])
        self.assertEqual(Path(out["settings_path"]), fresh / "session" / "settings.json")
        self.assertTrue(out["document"])

    # -- envelope, state, stale recovery, preview --------------------------------------------

    def test_envelope_stamping_follows_the_operation_schema(self):
        s = self.headless()
        part = self.pin(s)
        s.call("inspect", detail="compact")
        s.call("check_geometry")
        s.resolve(s.edge_at((5, 0, 5), part=part))
        requests = [record["request"] for record in ledger(s) if record["event"] == "sent"]
        self.assertEqual(len({request["request_id"] for request in requests}), len(requests))
        for request in requests:
            self.assertIs(request["measure"], False)
        for op in ("capabilities", "operation_schema", "new"):
            self.assertNotIn("document_id", sent(s, op)[0])
            self.assertNotIn("expected_revision", sent(s, op)[0])
        for op in ("inspect", "check_geometry", "resolve_selector"):
            self.assertEqual(sent(s, op)[0]["document_id"], s.document_id)
            self.assertNotIn("expected_revision", sent(s, op)[0])
        for op in ("create_plane", "create_sketch", "add_circle", "pad"):
            self.assertEqual(sent(s, op)[0]["document_id"], s.document_id)
            self.assertIn("expected_revision", sent(s, op)[0])
        self.assertEqual(s.envelope("render_view"), (True, False))
        self.assertEqual(s.envelope("preview"), (True, True))
        # Headless results are JSON copies, as over the bridge: mutating one cannot reach the schema cache.
        schema = s.call("operation_schema", operations=["pad"])
        schema["operations"]["pad"]["summary"] = "mutated by the caller"
        self.assertNotEqual(s.call("operation_schema", operations=["pad"])["operations"]["pad"]["summary"],
                            "mutated by the caller")

    def test_state_follows_full_inspections_and_lookups_refresh_after_compact_reads(self):
        s = self.headless()
        part = self.pin(s)
        self.assertIn("features", s.state)
        self.assertEqual(s.state["revision"], s.revision)
        moved = self.out_of_band_change(s, "OutOfBand")
        compact = s.call("inspect", detail="compact")
        self.assertEqual(compact["revision"], moved)
        self.assertEqual(s.revision, moved)
        self.assertNotEqual(s.state["revision"], moved)  # a compact result never becomes the state
        inspections = len(sent(s, "inspect"))
        self.assertEqual(s.part_named("Pin"), part)
        self.assertEqual(len(sent(s, "inspect")), inspections + 1)
        self.assertEqual(s.state["revision"], moved)
        self.assertIsNotNone(s.feature("OutOfBand"))

    def test_stale_revision_reinspects_and_resends_once_with_a_new_request_id(self):
        s = self.headless()
        self.pin(s)
        stale = s.revision
        moved = self.out_of_band_change(s, "OutOfBand")
        s.call("create_plane", id="AfterStale", body="Body", origin=[0, 0, 60], normal=[0, 0, 1], x_direction=[1, 0, 0])
        attempts = [request for request in sent(s, "create_plane") if request["id"] == "AfterStale"]
        self.assertEqual([request["expected_revision"] for request in attempts], [stale, moved])
        self.assertNotEqual(attempts[0]["request_id"], attempts[1]["request_id"])
        records = done(s)
        first = next(index for index, record in enumerate(records) if record["request_id"] == attempts[0]["request_id"])
        self.assertEqual(records[first]["error_code"], "stale_revision")
        self.assertEqual(records[first + 1]["op"], "inspect")
        self.assertEqual((records[first + 2]["request_id"], records[first + 2]["ok"], records[first + 2]["attempt"],
                          records[first + 2]["retry_of"]), (attempts[1]["request_id"], True, 2, attempts[0]["request_id"]))
        self.assertIsNotNone(s.feature("AfterStale"))
        # A revision the caller passed is an assertion: no re-inspect, no resend.
        inspections = len(sent(s, "inspect"))
        with self.assertRaises(OperationFailed) as caught:
            s.call("create_plane", id="Asserted", body="Body", origin=[0, 0, 70], normal=[0, 0, 1],
                   x_direction=[1, 0, 0], expected_revision=stale)
        self.assertEqual((caught.exception.code, caught.exception.attempts), ("stale_revision", 1))
        self.assertNotIsInstance(caught.exception, StaleRevision)
        self.assertEqual(len(sent(s, "inspect")), inspections)

    def test_a_second_stale_rejection_raises_stale_revision(self):
        fake = FakeBridge(stale={"pad"})
        s = Session.bridge(root=self.short_root(), send=fake)
        s.call("new", name="Busy")
        with self.assertRaises(StaleRevision) as caught:
            s.call("pad", id="Pad", profile="Sketch", length=3)
        pads = [request for request in fake.requests if request["op"] == "pad"]
        self.assertEqual(len(pads), 2)
        self.assertEqual(caught.exception.attempts, 2)
        self.assertEqual(fake.requests[-2]["op"], "inspect")
        self.assertEqual(pads[1]["expected_revision"], "r1")  # what the re-inspect returned
        self.assertNotEqual(pads[0]["request_id"], pads[1]["request_id"])
        self.assertEqual(caught.exception.request["request_id"], pads[1]["request_id"])

    def test_preview_carries_the_current_revision(self):
        s = self.headless()
        self.pin(s)
        result = s.call("preview", proposal={"op": "create_body", "id": "Spare"})
        self.assertTrue(result["accepted"], result)
        self.assertEqual(result["base_revision"], s.revision)
        self.assertEqual(sent(s, "preview")[0]["expected_revision"], s.revision)
        # Through a server without operation_schema the fallback envelope keeps the rule.
        fake = FakeBridge()
        b = Session.bridge(root=self.short_root(), send=fake)
        b.call("new", name="Old server")
        b.call("preview", proposal={"op": "create_body", "id": "Spare"})
        b.call("inspect")
        b.call("pad", id="Pad", profile="Sketch", length=3)
        last = {request["op"]: request for request in fake.requests}
        self.assertEqual(last["preview"]["expected_revision"], "r0")
        self.assertNotIn("expected_revision", last["inspect"])
        self.assertEqual(last["pad"]["expected_revision"], "r0")
        self.assertNotIn("document_id", last["new"])

    # -- lookup and helpers -------------------------------------------------------------------

    def test_part_named_with_the_single_body_fallback(self):
        s = self.headless()
        part = self.pin(s, "Disc")
        self.assertEqual(s.part_named("Disc"), part)
        self.assertEqual(s.part_named(), part)
        self.assertEqual(s.part("Disc"), part)
        self.assertEqual([row["name"] for row in s.parts], ["Disc"])
        with self.assertRaises(PartNotFound):
            s.part_named("Nope")
        s.call("new", name="Single body")
        s.call("sketch_rectangle", id="BlockProfile", body="Body", x=0, y=0, width=30, height=10)
        s.call("pad", id="Block", profile="BlockProfile", body="Body", length=5)
        self.assertEqual(s.parts, [])
        self.assertEqual(s.part_named(), "Body")
        s.call("new", name="Empty")
        with self.assertRaises(PartNotFound):
            s.part_named()
        self.assertIsNone(s.feature("Block"))  # the state follows the current (empty) document

    def test_edge_at_builds_closest_selectors_that_drive_a_chamfer(self):
        s = self.headless()
        part = self.pin(s)
        self.assertEqual(s.edge_at((5, 0, 5)), {"kind": "closest", "point": [5, 0, 5], "query": {
            "kind": "owned_by", "part": part, "entity_type": "edge"}})
        selector = s.edge_at((5, 0, 5), part=part, radius=5, resolve=True)
        self.assertEqual(selector["query"], {"kind": "geometry", "geometry": "circle", "radius": 5, "query": {
            "kind": "owned_by", "part": part, "entity_type": "edge"}})
        with self.assertRaises(SelectorError):
            s.edge_at((5, 0, 5), part=part, radius=7, resolve=True)
        # tolerance alone adds no geometry filter.
        self.assertEqual(s.edge_at((5, 0, 5), part=part, tolerance=0.01)["query"],
                         {"kind": "owned_by", "part": part, "entity_type": "edge"})
        self.assertEqual(s.face_at((0, 0, 2.5), part=part, radius=5)["query"]["geometry"], "cylinder")
        result = s.call("chamfer", id="Lead", part=part, edges=[{"selector": selector}], size=0.5)
        self.assertEqual(result["created_feature"], "Lead")
        self.assertEqual(s.feature("Lead")["type"], "PartDesign::Chamfer")

    def test_finish_writes_native_step_and_inspection_and_the_ledger_records_every_call(self):
        s = self.headless()
        part = self.pin(s, "Finished pin")
        folder = s.root / "out"
        row = s.finish(part, folder, "pin", "Finished pin", [0.2, 0.4, 0.6])
        self.assertEqual(row, {"id": "pin", "name": "Finished pin", "path": str(folder / "pin.step"),
                               "native": str(folder / "pin.FCStd"), "color": [0.2, 0.4, 0.6],
                               "inspection": str(folder / "pin-inspection.json"), "geometry_check": "valid"})
        for path in (row["path"], row["native"], row["inspection"]):
            self.assertTrue(Path(path).is_file(), path)
        inspection = json.loads(Path(row["inspection"]).read_text(encoding="utf-8"))
        self.assertEqual(inspection["document_id"], s.document_id)
        self.assertIn("center_of_mass_mm", json.dumps(inspection))
        self.assertEqual(s.parts[0]["name"], "Finished pin")
        self.assertAlmostEqual(Part.read(row["path"]).Volume, math.pi * 25 * 5, places=3)
        s.call("save", path=folder / "pin-again.FCStd")  # a path-like argument is sent as a string
        self.assertTrue((folder / "pin-again.FCStd").is_file())
        records = ledger(s)
        self.assertEqual(s.ledger_path, s.root / "requests.jsonl")
        sends = [record for record in records if record["event"] == "sent"]
        dones = [record for record in records if record["event"] == "done"]
        self.assertEqual([record["seq"] for record in sends], [record["seq"] for record in dones])
        self.assertEqual([record["request"]["request_id"] for record in sends], [record["request_id"] for record in dones])
        for record in dones:
            for key in ("ok", "error_code", "revision", "created_feature", "elapsed_ms", "op", "attempt"):
                self.assertIn(key, record)
            self.assertTrue(record["ok"], record)
        self.assertEqual(next(record for record in dones if record["op"] == "pad")["created_feature"], "Pin")
        self.assertEqual({record["transport"] for record in sends}, {"headless"})
        log = s.log_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(log), len(dones))
        self.assertIn(" pad Pin ", next(line for line in log if " pad " in line))

    # -- bridge transport ---------------------------------------------------------------------

    def test_bridge_transport_goes_through_assistant_client_send(self):
        h = self.headless()
        client = sdk._load_assistant_client()
        self.assertEqual(Path(client.__file__).resolve(), ROOT / "tools" / "assistant_client.py")
        session_file = self.short_root() / "assistant-session.json"
        session_file.write_text(json.dumps({"url": "http://127.0.0.1:9/never", "token": "tok-" + uuid.uuid4().hex,
                                            "session_id": "fake",
                                            "read_operations": sorted(Controller.READ_OPS),
                                            "non_mutating_operations": sorted(Controller.NON_MUTATING_OPS)}),
                                encoding="utf-8")
        posts = []

        def post(url, token, body, timeout):
            request = json.loads(body)
            posts.append(request)
            return "json", 200, h.controller.dispatch(request)

        h.controller.settings.roots.add(session_file.parent)
        with patch.object(client, "_post", post):
            b = Session.bridge(session_path=session_file, close_documents=True)
            self.assertEqual(b.root, session_file.parent / "sdk-ledger")
            b.call("new", name="Over the bridge")
            part = b.circle("Disc", (0, 0, 0), 12, 4, name="Disc")
            self.assertEqual(b.part_named("Disc"), part)
            self.assertTrue(b.call("preview", proposal={"op": "create_body", "id": "Spare"})["accepted"])
            b.call("save", path=str(session_file.parent / "bridge.FCStd"))
            b.call("create_body", id="Unsaved")
            b.close()
        self.assertEqual([request["op"] for request in posts[:2]], ["capabilities", "operation_schema"])
        self.assertTrue(all("request_id" in request for request in posts))
        self.assertEqual({record["transport"] for record in ledger(b) if record["event"] == "sent"}, {"bridge"})
        # close_documents never discards: the unsaved document stays open and the refusal is logged.
        self.assertEqual(done(b, "close_document")[0]["error_code"], "unsaved_changes")
        self.assertIn("kept open: unsaved_changes", b.log_path.read_text(encoding="utf-8"))
        self.assertEqual(len(h.call("list_documents")["documents"]), 1)
        # The bridge token never reaches the ledger files.
        token = json.loads(session_file.read_text(encoding="utf-8"))["token"]
        for path in (b.ledger_path, b.log_path):
            self.assertNotIn(token, path.read_text(encoding="utf-8"))

    def test_bridge_failures_raise_with_the_reconciliation_block_and_are_never_resent(self):
        unknown = {"ok": False, "error": {"code": "outcome_unknown", "message": "Outcome cannot be determined"},
                   "reconciliation": {"outcome": "unknown", "request_id": "x", "session_id": "s", "reason": "deadline"}}
        fake = FakeBridge(replies={"pad": unknown})
        root = self.short_root()
        s = Session.bridge(session_path=root / "assistant-session.json", root=root / "ledger", send=fake)
        s.call("new", name="Unknown outcome")
        with self.assertRaises(OperationFailed) as caught:
            s.call("pad", id="Pad", profile="Sketch", length=3)
        self.assertEqual(caught.exception.code, "outcome_unknown")
        self.assertEqual(caught.exception.reconciliation["outcome"], "unknown")
        self.assertEqual([request["op"] for request in fake.requests].count("pad"), 1)
        self.assertEqual(done(s, "pad")[0]["reconciliation"], "unknown")
        self.assertEqual(set(fake.paths), {(root / "assistant-session.json").resolve()})

    # -- Rev B recipe excerpt -----------------------------------------------------------------

    @unittest.skipUnless(REVB_M8_STEP.is_file(), support.EXTERNAL_SKIP_PREFIX + " Rev B fixture STEP not present: "
                         + str(REVB_M8_STEP))
    def test_revb_m8_screw_excerpt_reproduces_the_original_step_geometry(self):
        def xy(r, t, a):
            a = math.radians(a)
            return (r * math.cos(a) - t * math.sin(a), r * math.sin(a) + t * math.cos(a))

        def hexpoints(af, cx, cy, a=0):
            rr = af / math.sqrt(3)
            return [[cx + rr * math.cos(math.radians(a + 30 + 60 * i)), cy + rr * math.sin(math.radians(a + 30 + 60 * i))]
                    for i in range(6)]

        s = self.headless()
        x, y = xy(38, 0, 0)
        s.call("new", name="Rev B pedestal M8 x 16 socket screw 1")
        p = s.circle("M8Shank", (x, y, -60), 8, 16, name="Pedestal M8 x 16 screw 1")
        s.circle("M8Head", (x, y, -44), 13, 8, "add", p)
        s.polygon("M8Socket", hexpoints(6, x, y), -40, 4, "remove", p)
        row = s.finish(p, s.root / "fixture-components", "revb_pedestal_M8x16_screw_1", "Pedestal M8 x 16 screw 1",
                       [.34, .37, .41])
        self.assertEqual(step_digest(row["path"]), step_digest(REVB_M8_STEP))


if __name__ == "__main__":
    unittest.main()
