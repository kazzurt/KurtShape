"""Interaction-cost probe for contract 3.2 A/B comparisons (promoted from the verification prototype).

Measures the operations bench_core does not, on the same native fixtures and with
the same method as the 3.1 baseline: idle sync, inspect false/true/full,
list_documents, capabilities, intent signature, snapshot saveCopy, upstream and tip
edits, managed rebuild, undo and redo (separately), preview ops, check_geometry
cold/cached, studio Add creation with its post-condition share, the drill's
expensive result checks with BRep digest stability, and the contract 3.2 item-1
reproduction. Per family it counts BRepCheck calls (geometry.check_shape), studio
result checks (studio._check_result, with their ms), exact boxes
(geometry.tight_bounding_box) and native recompute calls (document observer).
Every call family records overhead_ms (dispatch total minus native recompute).

Fixtures: plate (bench_core plate60), studio (bench_core studio), repro (item 1),
drill (tests/perf_fixture build_drill/add_flute) and coldstart (worker import).
Metric names are the prototype's, so the 3.1 baseline stays comparable.

The code under test is the source root in KURTSHAPE_ROOT (the live checkout by
default, or the frozen copy in runtime/bench/f31 for the A side); bench_core is
imported from that root. The drill helpers come from this script's own checkout:
they only send typed operations, so both sides run the identical method.

Contract 3.2 families (parameters, compact inspect, render, batch) are detected
through capabilities (compact inspect through a read-only list_documents request)
and recorded under ``families_32``; a build without them records "unsupported", so
one script serves both sides. U0 only detects them: a family the build offers but
this probe does not measure yet is "available_unmeasured" and listed in
``families_32_unmeasured`` until its owning unit (U2c, U4, U5, U6) adds the metrics.

Run inside an isolated session (bench_core.isolated_session refuses live profiles),
normally through tools/perf/run_ab.py:
  pythonw.exe -B tools/perf/interaction_probe.py <out.json> [--repeat 5] [--holes 60]
      [--fixtures repro,drill,studio,plate,coldstart]
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import traceback

HERE = Path(__file__).resolve().parent
CHECKOUT = HERE.parents[1]
ROOT = Path(os.environ.get("KURTSHAPE_ROOT", str(CHECKOUT))).resolve()
sys.path[:0] = [str(ROOT / "tools" / "perf"), str(ROOT / "tools"), str(ROOT / "src")]
import bench_core  # noqa: E402  (no native import at module level)

FIXTURES = ("repro", "drill", "studio", "plate", "coldstart")
# Contract 3.2 families (verification §4.5). A build offers a family when capabilities list
# every required operation and, where given, the probe request is accepted (compact inspect
# has no operation of its own: 3.1 refuses list_documents' detail argument).
FAMILIES_32 = {
    "parameters": {"requires": ("list_parameters", "create_parameter", "edit_parameter"), "owner": "U5"},
    "compact_inspect": {"requires": (), "accepts": {"op": "list_documents", "detail": "compact", "measure": False},
                        "owner": "U2c"},
    "render": {"requires": ("render_view",), "owner": "U4"},
    "batch": {"requires": ("batch",), "owner": "U6"},
}
# Families this probe measures. U0 measures none: each owning unit adds its family's metrics
# (plate.parameter_tip_ms/_upstream_ms and *.parameter_usage_ms, *.compact_inspect_ms,
# *.render_*_ms, studio.batch_*_4_ms) and its name here. A family the build offers but this
# probe does not measure is reported as "available_unmeasured" in families_32_unmeasured,
# and compare_ab.py repeats it as a warning.
MEASURED_32 = frozenset({"compact_inspect"})  # U2c


def stats(values):
    values = [float(v) for v in values]
    ordered = sorted(values)
    return {"median": statistics.median(values), "p95": ordered[math.ceil(len(values) * .95) - 1],
            "worst": max(values), "samples": values}


def source_identity():
    files = sorted((ROOT / "src" / "kurtshape").rglob("*.py"))
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    try:
        head = subprocess.check_output(["git", "-c", "safe.directory=" + CHECKOUT.as_posix(), "-C", str(CHECKOUT), "rev-parse", "HEAD"],
                                       stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).decode().strip()
        dirty = subprocess.check_output(["git", "-c", "safe.directory=" + CHECKOUT.as_posix(), "-C", str(CHECKOUT), "status", "--porcelain"],
                                        stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).decode().splitlines()
    except Exception:
        head, dirty = None, None
    return {"git_head": head, "dirty_entries": dirty, "src_kurtshape_tree_sha256": digest.hexdigest(),
            "src_files": len(files), "source_root": str(ROOT),
            "probe_script": str(Path(__file__).resolve()),
            "probe_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def drill_helpers():
    """tests/perf_fixture from this checkout, without leaving its sys.path changes behind."""
    saved = list(sys.path)
    sys.path.append(str(CHECKOUT / "tests"))
    try:
        import perf_fixture
    finally:
        sys.path[:] = saved
    return perf_fixture


class Probe:
    def __init__(self, scratch, repeat):
        import FreeCAD as App
        from kurtshape import geometry, studio
        self.App, self.geometry, self.studio = App, geometry, studio
        self.scratch, self.repeat = Path(scratch), repeat
        self.checks = defaultdict(int)
        self.result_checks = defaultdict(list)
        self.metrics = {}
        self.notes = {}
        self.errors = {}
        self._family = None
        self._originals = (geometry.check_shape, studio._check_result, geometry.tight_bounding_box)
        original_check, original_result, original_box = self._originals
        probe = self
        # Contract 3.2 F1 (U3): history validation checks and fingerprints per family. The frozen 3.1
        # tree has no result_checks module, so the counters stay at zero there.
        self.history_checks = defaultdict(int)
        self.fingerprints = defaultdict(int)
        try:
            from kurtshape import result_checks as _result_checks
        except ImportError:
            _result_checks = None
        self._result_checks = _result_checks
        if _result_checks is not None:
            self._history_originals = (studio.check_operation, _result_checks.fingerprint)
            original_operation, original_fingerprint = self._history_originals

            def counting_operation(*args, **kwargs):
                probe.history_checks[probe._family or "unlabelled"] += 1
                return original_operation(*args, **kwargs)

            def counting_fingerprint(*args, **kwargs):
                probe.fingerprints[probe._family or "unlabelled"] += 1
                return original_fingerprint(*args, **kwargs)
            studio.check_operation = counting_operation
            _result_checks.fingerprint = counting_fingerprint

        def counting_check(*args, **kwargs):
            probe.checks[probe._family or "unlabelled"] += 1
            return original_check(*args, **kwargs)

        def timed_result(*args, **kwargs):
            began = time.perf_counter()
            try:
                return original_result(*args, **kwargs)
            finally:
                probe.result_checks[probe._family or "unlabelled"].append((time.perf_counter() - began) * 1000)
        geometry.check_shape = counting_check
        studio._check_result = timed_result
        # Result-check work beyond BRepCheck (exact boxes) and every native document recompute,
        # observed natively (Controller._recompute's 'native_recompute' timing misses direct recomputes).
        self.tight_boxes = defaultdict(int)
        self.recomputes = defaultdict(int)

        def counting_box(*args, **kwargs):
            probe.tight_boxes[probe._family or "unlabelled"] += 1
            return original_box(*args, **kwargs)
        geometry.tight_bounding_box = counting_box

        class RecomputeCounter:
            def slotRecomputedDocument(self, doc):
                probe.recomputes[probe._family or "unlabelled"] += 1
        self._observer = RecomputeCounter()
        App.addDocumentObserver(self._observer)

    def close(self):
        self.geometry.check_shape, self.studio._check_result, self.geometry.tight_bounding_box = self._originals
        if self._result_checks is not None:
            self.studio.check_operation, self._result_checks.fingerprint = self._history_originals
        self.App.removeDocumentObserver(self._observer)

    @contextmanager
    def family(self, name):
        previous, self._family = self._family, name
        try:
            yield
        finally:
            self._family = previous

    def sample(self, name, function, repeat=None, warm=False):
        values = []
        result = None
        with self.family(name):
            if warm:
                function()
            for _ in range(repeat or self.repeat):
                began = time.perf_counter()
                result = function()
                values.append((time.perf_counter() - began) * 1000)
        self.metrics[name] = stats(values)
        return result

    def attempt(self, name, function):
        try:
            function()
        except Exception:
            self.errors[name] = traceback.format_exc()

    # --- shared measurements ------------------------------------------------
    def common(self, prefix, bench):
        from kurtshape.core import intent_signature
        core, doc = bench.core, bench.doc
        self.sample(prefix + "idle_sync_ms", lambda: core.sync(doc), warm=True)
        self.sample(prefix + "inspect_false_warm_ms", lambda: core.inspect(doc, False), warm=True)
        self.sample(prefix + "inspect_true_warm_ms", lambda: core.inspect(doc, True), warm=True)
        self.sample(prefix + "inspect_full_warm_ms", lambda: core.inspect(doc, "full"), warm=True)
        self.sample(prefix + "dispatch_inspect_false_ms",
                    lambda: core.dispatch({"op": "inspect", "document_id": bench.state["document_id"], "measure": False}), warm=True)
        self.sample(prefix + "list_documents_false_ms",
                    lambda: core.dispatch({"op": "list_documents", "measure": False}), warm=True)
        self.sample(prefix + "capabilities_ms", lambda: core.dispatch({"op": "capabilities"}), warm=True)
        self.sample(prefix + "intent_signature_ms", lambda: intent_signature(doc), warm=True)
        families = families_32(core)
        self.notes[prefix + "families_32"] = {name: family["status"] for name, family in families.items()}
        if families["compact_inspect"]["available_in_build"]:
            # Contract 3.2 U2c: the compact overview and one selected feature row (no measurement).
            self.sample(prefix + "compact_inspect_ms", lambda: core.dispatch(
                {"op": "inspect", "document_id": bench.state["document_id"], "detail": "compact"}), warm=True)
            self.sample(prefix + "compact_inspect_feature_ms", lambda: core.dispatch(
                {"op": "inspect", "document_id": bench.state["document_id"], "features": [bench.tip]}), warm=True)
        self.sample(prefix + "snapshot_key_ms", lambda: core.snapshot_key(doc), warm=True)
        folder = Path(tempfile.mkdtemp(prefix="savecopy-", dir=self.scratch))
        counter = iter(range(1000))
        self.sample(prefix + "save_copy_snapshot_ms", lambda: doc.saveCopy(str(folder / f"snap-{next(counter)}.FCStd")))
        sizes = [p.stat().st_size for p in folder.glob("*.FCStd")]
        self.notes[prefix + "snapshot_bytes"] = max(sizes) if sizes else None
        self.notes[prefix + "objects"] = len(doc.Objects)

    def call_samples(self, name, bench, requests):
        """requests: list of (op, kwargs) applied in order; one sample per request."""
        values, totals = [], []
        with self.family(name):
            for op, kwargs in requests:
                measured = bench.call(op, **kwargs)
                values.append(measured["total_ms"])
                totals.append(measured)
        self.metrics[name] = stats(values)
        self.metrics[name]["native_recompute_ms"] = [item["native_recompute_ms"] for item in totals]
        # Rule 4.4(a) compares overhead (dispatch total minus native recompute) for long operations.
        self.metrics[name]["overhead_ms"] = stats([item["overhead_ms"] for item in totals])
        return totals

    def dispatch_samples(self, name, bench, request_factory, repeat=None):
        values, responses = [], []
        with self.family(name):
            for index in range(repeat or self.repeat):
                request = request_factory(index)
                began = time.perf_counter()
                response = bench.core.dispatch(request)
                values.append((time.perf_counter() - began) * 1000)
                responses.append(response)
        self.metrics[name] = stats(values)
        return responses

    def check_geometry(self, prefix, bench, change):
        cold, cached = [], []
        with self.family(prefix + "check_geometry"):
            for index in range(self.repeat):
                change(index)
                began = time.perf_counter()
                bench.call("check_geometry")
                cold.append((time.perf_counter() - began) * 1000)
                began = time.perf_counter()
                bench.call("check_geometry")
                cached.append((time.perf_counter() - began) * 1000)
        self.metrics[prefix + "check_geometry_cold_ms"] = stats(cold)
        self.metrics[prefix + "check_geometry_cached_ms"] = stats(cached)

    # --- fixtures ------------------------------------------------------------
    def plate(self, holes):
        bench = bench_core.Benchmark(self.scratch / "plate", "plate", holes, self.repeat, measure=False)
        try:
            with self.family("plate_fixture_build"):
                self.notes["plate_fixture"] = bench.build()
            self.common("plate.", bench)
            tip = f"H{holes - 1}"
            self.call_samples("plate.set_parameter_tip_ms", bench,
                              [("set_parameter", {"feature": tip, "parameter": "Diameter", "value": bench.pitch * (.40 + .01 * (i % 3))}) for i in range(self.repeat)])
            self.call_samples("plate.edit_extrusion_upstream_ms", bench,
                              [("edit_extrusion", {"feature": "Pad", "length": 12 + (.5 if i % 2 == 0 else 0)}) for i in range(self.repeat)])
            self.call_samples("plate.set_expression_upstream_ms", bench,
                              [("set_expression", {"feature": "Pad", "parameter": "Length", "expression": f"{12 + (.5 if i % 2 == 0 else .25)} mm"}) for i in range(self.repeat)])
            bench.call("set_expression", feature="Pad", parameter="Length", expression=None)
            # A reversed through-all pocket cuts air (empty_cut); distinct blind depths cut real material.
            self.attempt("plate.edit_extrusion_tip_ms", lambda: self.call_samples(
                "plate.edit_extrusion_tip_ms", bench,
                [("edit_extrusion", {"feature": f"P{holes - 1}", "end_type": "blind", "length": 6 + i}) for i in range(self.repeat)]))
            self.attempt("plate.edit_extrusion_tip_restore", lambda: bench.call("edit_extrusion", feature=f"P{holes - 1}", end_type="through_all"))
            self.call_samples("plate.rebuild_ms", bench, [("rebuild", {})] * self.repeat)
            # Undo and redo are different operations with different costs; pooled they give a bimodal median.
            undo, redo = [], []
            with self.family("plate.undo_redo"):
                for _ in range(self.repeat):
                    undo.append(bench.call("undo"))
                    redo.append(bench.call("redo"))
            for name, totals in (("plate.undo_ms", undo), ("plate.redo_ms", redo)):
                self.metrics[name] = stats([item["total_ms"] for item in totals])
                self.metrics[name]["overhead_ms"] = stats([item["overhead_ms"] for item in totals])
            self.notes["plate.undo_redo_names"] = list(bench.doc.UndoNames[:2])
            self.dispatch_samples("plate.preview_op_set_parameter_ms", bench, lambda i: {
                "op": "preview", "document_id": bench.state["document_id"], "expected_revision": bench.state["revision"],
                "measure": False, "proposal": {"op": "set_parameter", "feature": tip, "parameter": "Diameter", "value": bench.pitch * .35}})
            self.dispatch_samples("plate.preview_op_new_sketch_ms", bench, lambda i: {
                "op": "preview", "document_id": bench.state["document_id"], "expected_revision": bench.state["revision"],
                "measure": False, "proposal": {"op": "sketch_circle", "id": "PreviewHole", "x": bench.pitch / 2, "y": bench.pitch / 2, "diameter": 10}})
            self.check_geometry("plate.", bench, lambda i: bench.call("set_parameter", feature=tip, parameter="Diameter",
                                                                     value=bench.pitch * (.41 + .01 * (i % 3))))
        finally:
            bench.close()

    def studio_fixture(self):
        bench = bench_core.Benchmark(self.scratch / "studio", "studio", 0, self.repeat, measure=False)
        try:
            with self.family("studio_fixture_build"):
                self.notes["studio_fixture"] = bench.build()
            self.common("studio.", bench)
            # Distinct, never-validated values (uncached metric), then a revisit of already-visited values.
            self.call_samples("studio.edit_extrusion_add_ms", bench,
                              [("edit_extrusion", {"feature": "BenchExplicitAdd", "length": 7 + i}) for i in range(self.repeat)])
            self.notes["studio.edit_extrusion_add_result_report"] = "result_report" in bench.state
            self.call_samples("studio.edit_extrusion_add_revisit_ms", bench,
                              [("edit_extrusion", {"feature": "BenchExplicitAdd", "length": 7 + (i % 2)}) for i in range(self.repeat)])
            self.call_samples("studio.set_parameter_upstream_ms", bench,
                              [("set_parameter", {"feature": "Pad1", "parameter": "Length", "value": 5 + (1 if i % 2 == 0 else .5)}) for i in range(self.repeat)])
            self.call_samples("studio.set_expression_upstream_ms", bench,
                              [("set_expression", {"feature": "Pad1", "parameter": "Length", "expression": f"{5 + (1 if i % 2 == 0 else .5)} mm"}) for i in range(self.repeat)])
            bench.call("set_expression", feature="Pad1", parameter="Length", expression=None)
            self.call_samples("studio.rebuild_ms", bench, [("rebuild", {})] * self.repeat)
            create, report_ms = [], []
            with self.family("studio.create_add"):
                for index in range(self.repeat):
                    bench.call("sketch_rectangle", id="ProbeAddProfile", body=bench.primary_part, x=1, y=1, width=3, height=3)
                    measured = bench.call("pad", id="ProbeAdd", profile="ProbeAddProfile", body=bench.primary_part,
                                          length=9, operation="add", merge_scope=[bench.primary_part])
                    create.append(measured["total_ms"])
                    report_ms.append(bench.state["result_report"]["check_ms"])
                    bench.call("undo")
                    bench.call("undo")
            self.metrics["studio.create_add_with_checks_ms"] = stats(create)
            self.metrics["studio.create_add_result_check_ms"] = stats(report_ms)
            self.dispatch_samples("studio.preview_op_set_parameter_ms", bench, lambda i: {
                "op": "preview", "document_id": bench.state["document_id"], "expected_revision": bench.state["revision"],
                "measure": False, "proposal": {"op": "set_parameter", "feature": "Pad1", "parameter": "Length", "value": 6.25}})
            bench.call("sketch_rectangle", id="ProbePreviewProfile", body=bench.primary_part, x=1, y=1, width=3, height=3)
            responses = self.dispatch_samples("studio.preview_op_add_ms", bench, lambda i: {
                "op": "preview", "document_id": bench.state["document_id"], "expected_revision": bench.state["revision"],
                "measure": False, "proposal": {"op": "pad", "profile": "ProbePreviewProfile", "body": bench.primary_part,
                                                "length": 9 + i, "operation": "add", "merge_scope": [bench.primary_part]}})
            self.notes["studio.preview_op_add_valid"] = [bool(r.get("ok") and r["result"].get("valid")) for r in responses]
            self.check_geometry("studio.", bench, lambda i: bench.call("set_parameter", feature="Pad1", parameter="Length",
                                                                      value=5 + .25 * (i + 1)))
        finally:
            bench.close()

    def drill(self):
        """Expensive result checks: the Zimmer drill of tests/perf_fixture.py (two helical flutes)."""
        from kurtshape.core import Controller
        from kurtshape import studio
        fixture = drill_helpers()
        core = Controller()
        core.default_measure = False
        state = None

        def call(op, **kwargs):
            nonlocal state
            response = core.dispatch({"op": op, "document_id": state["document_id"], "expected_revision": state["revision"],
                                      "measure": False, **kwargs})
            if not response["ok"]:
                raise RuntimeError(json.dumps(response)[:2000])
            state = response["result"]
            return state

        def digest(doc, part):
            shape = studio.current_part(doc, part).Shape
            return hashlib.sha256(shape.exportBrepToString().encode()).hexdigest()[:16], round(shape.Volume, 6)
        try:
            began = time.perf_counter()
            state, part = fixture.build_drill(core, name="Drill interaction probe", measure=False)
            self.notes["drill.body_build_ms"] = (time.perf_counter() - began) * 1000
            height = fixture.FLUTE_HEIGHT

            def flute(n, **options):
                nonlocal state
                # As in the 3.1 baseline: helix and section unlabelled and untimed, then the timed sweep.
                state = fixture.add_flute_inputs(core, state, n, measure=False)
                with self.family(f"drill.flute{n}_create"):
                    began = time.perf_counter()
                    response = fixture.sweep_flute(core, state, n, part, measure=False, **options)
                    ms = (time.perf_counter() - began) * 1000
                if not response["ok"]:
                    raise RuntimeError(json.dumps(response)[:2000])
                state = response["result"]
                self.metrics[f"drill.flute{n}_create_ms"] = stats([ms])
                self.notes[f"drill.flute{n}_result_report"] = {k: state.get("result_report", {}).get(k)
                                                              for k in ("check_ms", "volume_delta_mm3", "refine")}
            flute(1, refine=False)
            flute(2)
            doc = core.documents[state["document_id"]]
            self.notes["drill.objects"] = len(doc.Objects)
            self.notes["drill.volume_mm3"] = studio.current_part(doc, part).Shape.Volume
            self.sample("drill.idle_sync_ms", lambda: core.sync(doc), warm=True)
            self.sample("drill.inspect_false_warm_ms", lambda: core.inspect(doc, False), warm=True)
            original = digest(doc, part)
            edits = []
            with self.family("drill.helix_upstream_edit"):
                for index in range(self.repeat):
                    began = time.perf_counter()
                    call("set_parameter", feature="Flute1Helix", parameter="Height", value=height + .5 * (index + 1))
                    edits.append((time.perf_counter() - began) * 1000)
            self.metrics["drill.helix_upstream_edit_ms"] = stats(edits)
            call("set_parameter", feature="Flute1Helix", parameter="Height", value=height)
            roundtrip = digest(doc, part)
            rebuilds, digests = [], []
            with self.family("drill.rebuild"):
                for _ in range(self.repeat):
                    began = time.perf_counter()
                    call("rebuild")
                    rebuilds.append((time.perf_counter() - began) * 1000)
                    digests.append(digest(doc, part))
            self.metrics["drill.rebuild_ms"] = stats(rebuilds)
            self.notes["drill.brep_digest"] = {"after_create": original, "after_A_B_A_roundtrip": roundtrip,
                                               "after_each_rebuild": digests,
                                               "stable_across_rebuild": all(d == original for d in digests),
                                               "stable_after_roundtrip": roundtrip == original}
        finally:
            core.close()
            for name in list(self.App.listDocuments()):
                self.App.closeDocument(name)

    def repro(self):
        """Contract 3.2 item 1: an edit_extrusion that empties an Add (accepted at 3.1, rejected once validated)."""
        from kurtshape.core import Controller
        core = Controller()
        core.default_measure = False
        out = {}
        try:
            state = core.dispatch({"op": "new", "name": "Edit validation repro"})["result"]

            def call(op, **kwargs):
                nonlocal state
                response = core.dispatch({"op": op, "document_id": state["document_id"], "expected_revision": state["revision"],
                                          "measure": True, **kwargs})
                if response["ok"]:
                    state = response["result"]
                return response
            call("sketch_rectangle", id="Base", width=20, height=20)
            call("pad", id="Block", profile="Base", length=10, operation="new")
            call("sketch_rectangle", id="Cap", width=20, height=20)
            created = call("pad", id="Raise", profile="Cap", length=15, operation="add", merge_scope=["Body"])
            out["create_15_ok"] = created["ok"]
            out["create_15_delta"] = created.get("result", {}).get("result_report", {}).get("volume_delta_mm3")
            with self.family("repro.edit_extrusion"):
                edited = call("edit_extrusion", feature="Raise", length=5)
            out["edit_to_5"] = {"ok": edited["ok"], "build_status": edited.get("result", {}).get("build_status"),
                                "has_result_report": "result_report" in edited.get("result", {}),
                                "volume_mm3": (edited.get("result", {}).get("measurements") or {}).get("volume_mm3"),
                                "error": edited.get("error")}
            with self.family("repro.rebuild"):
                rebuilt = call("rebuild")
            out["rebuild_after_edit"] = {"ok": rebuilt["ok"], "build_status": rebuilt.get("result", {}).get("build_status"),
                                         "error": rebuilt.get("error")}
            call("sketch_rectangle", id="Cap2", width=20, height=20)
            direct = call("pad", id="Raise2", profile="Cap2", length=5, operation="add", merge_scope=["Body"])
            out["direct_create_5"] = {"ok": direct["ok"], "error_code": (direct.get("error") or {}).get("code")}
        finally:
            core.close()
            for name in list(self.App.listDocuments()):
                self.App.closeDocument(name)
        self.notes["contract32_item1_repro"] = out


def families_32(core=None):
    """Which contract 3.2 families this build offers (capabilities plus read-only probe requests;
    no document needed) and whether this probe measures them."""
    owned = core is None
    if owned:
        from kurtshape.core import Controller
        core = Controller()
    try:
        operations = set((core.dispatch({"op": "capabilities"}).get("result") or {}).get("operations", ()))
        out = {}
        for name, family in FAMILIES_32.items():
            available = set(family["requires"]) <= operations
            if available and family.get("accepts"):
                available = bool(core.dispatch(dict(family["accepts"])).get("ok"))
            status = ("unsupported" if not available else "measured" if name in MEASURED_32 else "available_unmeasured")
            out[name] = {"requires": list(family["requires"]), "accepts": family.get("accepts"),
                         "owner": family["owner"], "available_in_build": available, "status": status,
                         "measured": status == "measured"}
        return out
    finally:
        if owned:
            core.close()


def child_cold_start(samples=3):
    """Cost a per-job native worker pays before any work (python + FreeCAD + Part import)."""
    executable = Path(sys.executable).with_name("python.exe")
    script = Path(tempfile.mkdtemp(prefix="coldstart-")) / "cold.py"
    script.write_text("import time\nb=time.perf_counter()\nimport FreeCAD, Part\nprint((time.perf_counter()-b)*1000)\n", encoding="utf-8")
    walls, imports = [], []
    for _ in range(samples):
        began = time.perf_counter()
        out = subprocess.run([str(executable), "-B", str(script)], capture_output=True, text=True,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), env=os.environ.copy())
        walls.append((time.perf_counter() - began) * 1000)
        try:
            imports.append(float(out.stdout.strip().splitlines()[-1]))
        except (ValueError, IndexError):
            pass
    return {"child_wall_ms": stats(walls), "child_import_freecad_part_ms": stats(imports) if imports else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out")
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--holes", type=int, default=60)
    parser.add_argument("--fixtures", default=",".join(FIXTURES))
    args = parser.parse_args()
    fixtures = [name for name in args.fixtures.split(",") if name]
    unknown = sorted(set(fixtures) - set(FIXTURES))
    if unknown or args.repeat < 1 or args.holes < 2:
        parser.error("unknown fixtures " + ", ".join(unknown) if unknown else "repeat must be >= 1 and holes >= 2")
    session = bench_core.isolated_session()  # refuses live profiles
    scratch = bench_core.prepare_environment(session / "supplement-working")

    def deny(*a, **k):
        raise RuntimeError("Networking disabled for native benchmark")
    socket.socket.connect = deny
    socket.create_connection = deny
    socket.getaddrinfo = deny
    report = {"source": source_identity(), "session": str(session), "repeat": args.repeat, "holes": args.holes,
              "fixtures": fixtures,
              "method": "Bundled pythonw; real Controller.dispatch through bench_core.Benchmark fixtures; wall ms",
              "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    probe = None
    began = time.perf_counter()
    try:
        import FreeCAD as App
        import Part
        report["engine"] = {"FreeCAD": App.Version(), "OCCT": Part.OCC_VERSION}
        import kurtshape
        report["source"]["loaded_from"] = str(Path(kurtshape.__file__).resolve().parent)
        report["families_32"] = families_32()
        report["families_32_unmeasured"] = sorted(name for name, family in report["families_32"].items()
                                                  if family["status"] == "available_unmeasured")
        probe = Probe(scratch, args.repeat)
        if "repro" in fixtures:
            probe.attempt("repro", probe.repro)
        if "drill" in fixtures:
            probe.attempt("drill", probe.drill)
        if "plate" in fixtures:
            probe.attempt("plate", lambda: probe.plate(args.holes))
        if "studio" in fixtures:
            probe.attempt("studio", probe.studio_fixture)
        if "coldstart" in fixtures:
            report["worker_cold_start"] = child_cold_start()
    except Exception:
        report["error"] = traceback.format_exc()
    if probe is not None:
        report.update(metrics=probe.metrics, notes=probe.notes, errors=probe.errors,
                      brepcheck_calls_by_family=dict(probe.checks),
                      result_check_calls_by_family={k: len(v) for k, v in probe.result_checks.items()},
                      tight_box_calls_by_family=dict(probe.tight_boxes),
                      native_recomputes_by_family=dict(probe.recomputes),
                      history_checks_by_family=dict(probe.history_checks),
                      fingerprints_by_family=dict(probe.fingerprints),
                      studio_result_check_ms_by_family={k: v for k, v in probe.result_checks.items()})
        probe.close()
    report["seconds"] = time.perf_counter() - began
    report["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    report["source_end"] = source_identity()
    report["source_unchanged"] = report["source_end"]["src_kurtshape_tree_sha256"] == report["source"]["src_kurtshape_tree_sha256"]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"out": args.out, "errors": list((probe.errors if probe else {}).keys()),
                      "error": bool(report.get("error")), "seconds": report["seconds"],
                      "families_32_unmeasured": report.get("families_32_unmeasured", [])}))
    return 1 if report.get("error") or (probe and probe.errors) else 0


if __name__ == "__main__":
    raise SystemExit(main())
