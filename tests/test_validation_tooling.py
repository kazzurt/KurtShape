"""Contract 3.2 verification tooling: snapshot oracles, the result-check counter, --only routing
and the A/B acceptance tooling.

These helpers are the oracles later units rely on, so their own behaviour is
pinned here: content_view masks exactly the C32 fields, no_result_checks sees a
direct native recompute and each counted result-check path, run_native_tests
--only maps names to their registered suites and refuses anything else (whatever
the parent's KURTSHAPE_WRITE_EVIDENCE), --perf reaches only the suite children,
and compare_ab applies the verification §4.4 / integration C34 rules: over-gate
steps, changed sources and foreign trees are never pooled, and count allowances
are per counter with native recomputes never allowed to grow.
"""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import importlib
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import support
import perf_fixture

sys.path.insert(0, str(support.ROOT / "src"))
sys.path.insert(0, str(support.ROOT / "tools"))
import FreeCAD as App
from kurtshape import geometry, studio
from kurtshape.core import Controller, METADATA
import native_validation_snapshot as nvs
import run_native_tests as rnt
from test_build_status import no_result_checks


def perf_tool(name):
    """Import a tools/perf script without leaving tools/perf on sys.path."""
    saved = list(sys.path)
    sys.path.insert(0, str(support.ROOT / "tools" / "perf"))
    try:
        return importlib.import_module(name)
    finally:
        sys.path[:] = saved


def leaf_paths(value, prefix=()):
    """Every leaf of a JSON-like value as a path tuple (list items by index)."""
    if isinstance(value, dict) and value:
        for key, item in value.items():
            yield from leaf_paths(item, prefix + (key,))
    elif isinstance(value, list) and value:
        for index, item in enumerate(value):
            yield from leaf_paths(item, prefix + (index,))
    else:
        yield prefix


class ValidationToolingTests(unittest.TestCase):
    def setUp(self):
        self.initial = set(App.listDocuments())
        self.folder = support.isolated_session(self, prefix="validation-tooling-")
        self.core = Controller()
        self.state = self.core.dispatch({"op": "new", "name": "Validation tooling"})["result"]

    def tearDown(self):
        for name in set(App.listDocuments()) - self.initial:
            App.closeDocument(name)
        self.core.observer.close()

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    def call(self, op, **kwargs):
        response = self.core.dispatch({"op": op, "document_id": self.state["document_id"],
                                       "expected_revision": self.state["revision"], **kwargs})
        self.assertTrue(response["ok"], response)
        self.state = response["result"]
        return self.state

    def block(self):
        self.call("sketch_rectangle", id="Base", width=20, height=20)
        self.call("pad", id="Block", profile="Base", length=10, operation="new")

    # --- content_view ---------------------------------------------------------------------

    def masked_paths(self, strict):
        rows = strict["objects"]
        paths = {path for path in leaf_paths(strict) if path[0] == "gui"}
        for index, row in enumerate(rows):
            for prop, facts in row["shapes"].items():
                if "hash_code" in facts:
                    paths.add(("objects", index, "shapes", prop, "hash_code"))
            if row["name"] == METADATA:
                paths |= {path for path in leaf_paths(row, ("objects", index))
                          if path[2] in {"state", "status"}}
        return paths

    def test_content_view_masks_exactly_the_c32_fields(self):
        self.block()
        snapshot = nvs.snapshot_document(self.doc, self.core)
        original = deepcopy(snapshot)
        strict = snapshot["strict"]
        self.assertEqual(nvs.PROJECT_METADATA, METADATA)
        view = nvs.content_view(snapshot)
        self.assertEqual(snapshot, original, "content_view must not modify its input")
        # Non-vacuous: there are model hash codes and a project metadata row to mask.
        meta = [row for row in strict["objects"] if row["name"] == METADATA]
        self.assertEqual(len(meta), 1)
        self.assertLessEqual({"state", "status"}, set(meta[0]))
        hash_codes = [facts for row in strict["objects"] for facts in row["shapes"].values() if "hash_code" in facts]
        self.assertGreater(len(hash_codes), 3)
        # Exactly the C32 fields are gone; every other leaf survives with its value.
        removed = set(leaf_paths(strict)) - set(leaf_paths(view))
        self.assertEqual(removed, self.masked_paths(strict))
        self.assertEqual(set(leaf_paths(view)) - set(leaf_paths(strict)), set())
        expected = deepcopy(strict)
        expected.pop("gui")
        for row in expected["objects"]:
            for facts in row["shapes"].values():
                facts.pop("hash_code", None)
            if row["name"] == METADATA:
                del row["state"], row["status"]
        self.assertEqual(view, expected)
        self.assertEqual(nvs.content_view(strict), view, "the strict record alone gives the same view")
        self.assertEqual(nvs.without_gui(snapshot), {key: value for key, value in strict.items() if key != "gui"})
        # Masked leaves do not matter; content leaves do.
        body_row = next(index for index, row in enumerate(strict["objects"])
                        if "hash_code" in row["shapes"].get("Shape", {}) and row["name"] != METADATA)
        meta_row = strict["objects"].index(meta[0])

        def changed(edit):
            other = deepcopy(strict)
            edit(other)
            return nvs.content_view(other)
        self.assertEqual(changed(lambda s: s["objects"][body_row]["shapes"]["Shape"].update(hash_code=-1)), view)
        self.assertEqual(changed(lambda s: s["objects"][meta_row].update(state=["Touched"], status="Touched")), view)
        self.assertEqual(changed(lambda s: s.update(gui={"available": True, "camera": "x"})), view)
        for label, edit in [
                ("brep digest", lambda s: s["objects"][body_row]["shapes"]["Shape"].update(brep_sha256="0" * 64)),
                ("another row's state", lambda s: s["objects"][body_row].update(state=["Touched"])),
                ("revision", lambda s: s.update(revision="other-" + str(s["revision"]))),
                ("undo names", lambda s: s.update(undo_names=s["undo_names"] + ["Other"])),
                ("intent", lambda s: s.update(intent_sha256="0" * 64)),
                ("placement", lambda s: s["objects"][body_row]["shapes"]["Shape"]["placement"].update(base=[1, 2, 3]))]:
            with self.subTest(content=label):
                self.assertNotEqual(changed(edit), view)
        with self.assertRaises(TypeError):
            nvs.content_view([strict])
        with self.assertRaises(ValueError):
            nvs.content_view({"strict": {}})

    def test_content_view_is_stable_across_a_native_recompute_of_unchanged_features(self):
        self.block()
        before = nvs.snapshot_document(self.doc, self.core)
        for obj in self.doc.Objects:
            if obj.Name != METADATA and obj.TypeId.startswith(("PartDesign::", "Sketcher::", "Part::")):
                obj.touch()
        self.doc.recompute()
        after = nvs.snapshot_document(self.doc, self.core)
        self.assertEqual(nvs.content_view(after), nvs.content_view(before))
        differing = {path for path in set(leaf_paths(before["strict"])) | set(leaf_paths(after["strict"]))
                     if self.leaf(before["strict"], path) != self.leaf(after["strict"], path)}
        # Non-vacuous: the recompute renewed raw hash codes, and nothing else differs.
        self.assertTrue(any(path[-1] == "hash_code" for path in differing), differing)
        self.assertLessEqual(differing, self.masked_paths(before["strict"]) | self.masked_paths(after["strict"]))

    @staticmethod
    def leaf(value, path):
        for key in path:
            try:
                value = value[key]
            except (KeyError, IndexError, TypeError):
                return ("<missing>",)
        return value

    def test_gui_invariants_report_unavailable_without_a_gui(self):
        self.assertFalse(App.GuiUp)
        self.assertEqual(nvs.gui_invariants(self.doc)["available"], False)

    def test_camera_normalisation_drops_only_the_clipping_distances(self):
        # The GUI branch of gui_invariants records normalise_camera(view.getCamera()).
        def camera(near, far, position="0 0 1", height="4.1421356"):
            return ("#Inventor V2.1 ascii\n\n\nOrthographicCamera {\n  viewportMapping ADJUST_CAMERA\n"
                    f"  position {position}\n  orientation 0 0 1  0\n  nearDistance {near}\n"
                    f"  farDistance {far}\n  aspectRatio 1\n  focalDistance 5\n  height {height}\n\n}}\n")
        normal = nvs.normalise_camera(camera("0.25", "12.5"))
        self.assertNotIn("nearDistance", normal)
        self.assertNotIn("farDistance", normal)
        for kept in ("OrthographicCamera {", "position 0 0 1", "orientation 0 0 1  0", "focalDistance 5",
                     "height 4.1421356", "aspectRatio 1", "viewportMapping ADJUST_CAMERA"):
            self.assertIn(kept, normal)
        # Scene-bound clipping changes compare equal; the user's view does not.
        self.assertEqual(nvs.normalise_camera(camera("-3.5e-05", "1e+03")), normal)
        self.assertNotEqual(nvs.normalise_camera(camera("0.25", "12.5", position="0 0 2")), normal)
        self.assertNotEqual(nvs.normalise_camera(camera("0.25", "12.5", height="8")), normal)
        # Only whole lines that start with the field name are blanked.
        self.assertIn("focalDistance 5", nvs.normalise_camera("  focalDistance 5\n  farDistance 9\n"))
        self.assertEqual(nvs.normalise_camera("x\n    nearDistance 1\ny"), "x\n\ny")
        self.assertIsNone(nvs.normalise_camera(None))
        self.assertIsNone(nvs.normalise_camera(""))

    # --- no_result_checks ----------------------------------------------------------------

    def test_no_result_checks_counts_a_direct_recompute_and_result_checks(self):
        self.block()
        with no_result_checks(self) as counts:
            self.core.sync(self.doc)
            self.core.inspect(self.doc, False)
            self.core.dispatch({"op": "list_documents", "measure": False})
        self.assertEqual(counts, {"check_shape": 0, "result_checks": 0, "tight_boxes": 0, "native_recomputes": 0})
        # A direct native recompute bypasses Controller._recompute's timing; the observer sees it.
        with self.assertRaises(AssertionError):
            with no_result_checks(self) as counts:
                self.doc.Block.touch()
                self.doc.recompute()
        self.assertEqual(counts["native_recomputes"], 1)
        self.assertEqual((counts["check_shape"], counts["result_checks"], counts["tight_boxes"]), (0, 0, 0))
        # The observer is removed on exit.
        self.doc.Block.touch()
        self.doc.recompute()
        self.assertEqual(counts["native_recomputes"], 1)
        # A studio Add creation runs one result check with its BRepCheck and exact boxes.
        self.call("sketch_rectangle", id="Cap", width=20, height=20)
        with self.assertRaises(AssertionError):
            with no_result_checks(self) as counts:
                created = self.core.dispatch({"op": "pad", "document_id": self.state["document_id"],
                                              "expected_revision": self.state["revision"], "id": "Raise",
                                              "profile": "Cap", "length": 15, "operation": "add",
                                              "merge_scope": ["Body"]})
        self.assertTrue(created["ok"], created)
        self.assertEqual(created["result"]["result_report"]["feature"], "Raise")
        self.assertEqual((counts["result_checks"], counts["check_shape"]), (1, 1))
        self.assertGreaterEqual(counts["tight_boxes"], 1)
        self.assertGreaterEqual(counts["native_recomputes"], 1)
        # The helper restores the production functions it wrapped.
        self.assertEqual(geometry.check_shape.__module__, "kurtshape.geometry")
        self.assertEqual(studio._check_result.__qualname__, "_check_result")
        self.assertEqual(geometry.tight_bounding_box.__qualname__, "tight_bounding_box")

    # --- offscreen Qt fonts ----------------------------------------------------------------

    def test_offscreen_qt_fonts_resolve_segoe_and_restore_the_app_font(self):
        from PySide6 import QtGui, QtWidgets
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        before = QtGui.QFont(app.font())
        owner = perf_fixture.FixtureOwner(self.id())
        try:
            loaded = support.offscreen_qt_fonts(owner)
            fonts = support.Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
            self.assertEqual(loaded, all((fonts / name).is_file() for name in support.OFFSCREEN_FONT_FILES))
            if loaded:
                self.assertEqual(QtGui.QFontInfo(app.font()).family(), "Segoe UI")
                self.assertEqual(app.font().pointSize(), 9)
                self.assertTrue(owner.cleanups, "the previous application font is restored in a cleanup")
            else:
                self.assertEqual(app.font(), before, "missing fonts leave the application font unchanged")
        finally:
            owner.close()
        self.assertEqual(app.font(), before)

    # --- drill fixture --------------------------------------------------------------------

    def test_drill_fixture_helpers_build_through_typed_operations(self):
        state, part = perf_fixture.build_drill(self.core, self.state, measure=False)
        self.assertEqual(state["studio"]["parts"][0]["id"], part)
        self.assertEqual(self.core.documents[state["document_id"]].Name, self.doc.Name)
        state, response = perf_fixture.add_flute(self.core, state, 1, part, refine=False, measure=False)
        self.assertTrue(response["ok"], response)
        self.assertAlmostEqual(response["result"]["result_report"]["volume_delta_mm3"], -1824.389, places=2)
        self.assertIsNotNone(self.doc.getObject("Flute1Helix"))

    # --- run_native_tests --only ---------------------------------------------------------

    def main_error(self, *argv, environment=None):
        """run_native_tests.main() refusal text. The parent's KURTSHAPE_WRITE_EVIDENCE (set by
        run-checks.ps1 -WriteEvidence and inherited by the suite child) is removed unless the
        caller passes it, so each refusal is tested on its own."""
        stderr = io.StringIO()
        with patch.object(sys, "argv", ["run_native_tests.py", *argv]), \
                patch.dict(os.environ), redirect_stderr(stderr):
            os.environ.pop("KURTSHAPE_WRITE_EVIDENCE", None)
            os.environ.update(environment or {})
            with self.assertRaises(SystemExit) as caught:
                rnt.main()
        self.assertEqual(caught.exception.code, 2)
        return stderr.getvalue()

    def test_only_maps_names_to_registered_suites_and_rejects_unregistered_names(self):
        this = "test_validation_tooling.ValidationToolingTests"
        self.assertIn(this, rnt.SUITES["native"])
        for suite, classes in rnt.SUITES.items():
            for name in classes:
                with self.subTest(name=name):
                    self.assertEqual(rnt.select_tests([name]), {suite: [name]})
        method = this + ".test_only_maps_names_to_registered_suites_and_rejects_unregistered_names"
        self.assertEqual(rnt.select_tests([method]), {"native": [method]})
        self.assertEqual(rnt.select_tests(["test_build_status"]),
                         {"native": ["test_build_status.BuildStatusTests", "test_build_status.StatusPerformanceTests"]})
        # SUITES order, duplicates dropped.
        self.assertEqual(list(rnt.select_tests(["test_bridge.BridgeTimeoutTests", this, this])), ["native", "bridge"])
        for name in ("test_core.NoSuchTests", "test_nonexistent", "test_core.NativeCoreTest", "test_core.",
                     "", " test_core.NativeCoreTests", "test_core..NativeCoreTests", "test_build"):
            with self.subTest(unregistered=name), self.assertRaisesRegex(ValueError, "not registered in SUITES"):
                rnt.select_tests([name])
        # The same refusals whether or not the parent run writes tracked evidence (-WriteEvidence).
        for parent in (None, "1"):
            with self.subTest(parent_write_evidence=parent), patch.dict(os.environ):
                os.environ.pop("KURTSHAPE_WRITE_EVIDENCE", None)
                if parent:
                    os.environ["KURTSHAPE_WRITE_EVIDENCE"] = parent
                self.assertIn("not registered in SUITES: test_core.NoSuchTests",
                              self.main_error("--only", "test_core.NoSuchTests"))
                self.assertIn("KURTSHAPE_WRITE_EVIDENCE",
                              self.main_error("--only", this, environment={"KURTSHAPE_WRITE_EVIDENCE": "1"}))
                self.assertIn("outside --suite", self.main_error("--suite", "bridge", "--only", this))
                self.assertEqual(os.environ.get("KURTSHAPE_WRITE_EVIDENCE"), parent)
        command = rnt.child_command("native", "report.json", [this, method])
        self.assertEqual(command[-4:], ["--only", this, "--only", method])
        self.assertNotIn("--only", rnt.child_command("native", "report.json"))

    def test_perf_reaches_only_the_suite_children_and_partial_reports_carry_their_selection(self):
        this = "test_validation_tooling.ValidationToolingTests"
        folder = Path(self.folder) / "runner"
        launched = []

        class FakeProcess:
            pid, returncode = 4242, 0

            def __init__(self, command, **kwargs):
                launched.append({"command": list(command), "env": dict(kwargs["env"])})

            def communicate(self, timeout=None):
                return "", None
        before = dict(os.environ)
        with patch.object(rnt.subprocess, "Popen", FakeProcess), patch.object(rnt, "log_process"), \
                patch.dict(os.environ), redirect_stdout(io.StringIO()):
            os.environ.pop("KURTSHAPE_PERF", None)  # a --perf parent run exports it to this child
            parent = dict(os.environ)
            rnt.run_suite("native", folder / "perf", 60, [this], perf=True)
            rnt.run_suite("native", folder / "plain", 60, [this], perf=False)
            self.assertEqual(dict(os.environ), parent, "--perf never changes the parent environment")
        self.assertEqual(dict(os.environ), before)
        self.assertEqual(launched[0]["env"]["KURTSHAPE_PERF"], "1")
        self.assertNotIn("KURTSHAPE_PERF", launched[1]["env"])
        self.assertEqual(launched[0]["command"][-2:], ["--only", this])
        # The child report records its selection; a full child report has none.
        loaded = []

        def loader(names):
            loaded.append(list(names))
            return unittest.TestSuite()
        saved_path = list(sys.path)
        try:
            with patch.object(rnt.unittest.defaultTestLoader, "loadTestsFromNames", loader), \
                    redirect_stderr(io.StringIO()):
                self.assertEqual(rnt.child_suite("shortcuts", folder / "selected.json",
                                                 only=["test_tool_search.ToolSearchTests"]), 0)
                self.assertEqual(rnt.child_suite("shortcuts", folder / "full.json"), 0)
        finally:
            sys.path[:] = saved_path
        self.assertEqual(loaded, [["test_tool_search.ToolSearchTests"], list(rnt.SUITES["shortcuts"])])
        selected = json.loads((folder / "selected.json").read_text(encoding="utf-8"))
        self.assertEqual(selected["selection"], ["test_tool_search.ToolSearchTests"])
        self.assertNotIn("selection", json.loads((folder / "full.json").read_text(encoding="utf-8")))
        # The parent report: selection and perf only on partial / --perf runs.
        calls = []

        def fake_run_suite(name, run_folder, timeout, only=None, perf=False):
            calls.append((name, only, perf))
            return {"name": name, "passed": True, "cases": [], "counts": rnt.counts([]), "seconds": 0.0,
                    "source_unchanged": True, "skips": [], "exit_code": 0, "engine": {}}

        def parent_report(label, *argv):
            path = folder / f"parent-{label}.json"
            with patch.object(sys, "argv", ["run_native_tests.py", *argv, "--report", str(path),
                                            "--junit", str(path.with_suffix(".xml"))]), \
                    patch.object(rnt, "run_suite", fake_run_suite), \
                    patch.object(rnt, "unassigned_test_cases", lambda: []), \
                    patch.dict(os.environ), redirect_stdout(io.StringIO()):
                for name in ("KURTSHAPE_WRITE_EVIDENCE", "GITHUB_STEP_SUMMARY"):
                    os.environ.pop(name, None)
                self.assertEqual(rnt.main(), 0)
            return json.loads(path.read_text(encoding="utf-8"))
        partial = parent_report("partial", "--only", this, "--perf")
        self.assertEqual(calls, [("native", [this], True)])
        self.assertEqual(partial["selection"], [this])
        self.assertIs(partial["perf"], True)
        self.assertEqual([suite["selection"] for suite in partial["suites"]], [[this]])
        calls.clear()
        full = parent_report("full")
        self.assertEqual(calls, [(name, None, False) for name in rnt.SUITES])
        self.assertNotIn("selection", full)
        self.assertNotIn("perf", full)
        self.assertTrue(all("selection" not in suite for suite in full["suites"]))

    # --- A/B acceptance tooling (verification §4.4, integration C34) ------------------------------

    FAMILY = "studio.edit_extrusion_add_ms"

    def ab_run(self, name, *, busy=15.0, tree=None, supplement_tree=None, unchanged=True,
               supplement_unchanged=None, exit=0, ms=590.0, brep=0, recomputes=1640, extra_family=None,
               fixtures=("studio",), bench_busy=None, summary=True):
        """A synthetic run_ab result folder (run-summary.json, supplement.json, optional bench step)."""
        compare_ab = perf_tool("compare_ab")
        tree = tree or compare_ab.FROZEN_31_TREE
        folder = Path(self.folder) / "ab" / name
        folder.mkdir(parents=True)
        counters = {"brepcheck_calls_by_family": {}, "result_check_calls_by_family": {},
                    "tight_box_calls_by_family": {},
                    "native_recomputes_by_family": {self.FAMILY: recomputes, "unlabelled": 12},
                    "studio_result_check_ms_by_family": {}}
        if brep:
            counters["brepcheck_calls_by_family"][self.FAMILY] = brep
            counters["result_check_calls_by_family"][self.FAMILY] = brep
            counters["tight_box_calls_by_family"][self.FAMILY] = 2 * brep
            counters["studio_result_check_ms_by_family"][self.FAMILY] = [20.0] * brep
        metrics = {self.FAMILY: {"samples": [ms] * 5, "overhead_ms": {"samples": [ms - 400] * 5}},
                   "studio.inspect_false_warm_ms": {"samples": [25.0] * 5}}
        if extra_family:
            metrics[extra_family] = {"samples": [40.0] * 5}
            counters["native_recomputes_by_family"][extra_family] = 3
        supplement = {"source": {"src_kurtshape_tree_sha256": supplement_tree or tree},
                      "source_unchanged": unchanged if supplement_unchanged is None else supplement_unchanged,
                      "fixtures": list(fixtures), "metrics": metrics, **counters}
        (folder / "supplement.json").write_text(json.dumps(supplement), encoding="utf-8")
        steps = {"supplement": {"exit": exit, "system_busy_pct_all_cores": busy, "over_load_gate": busy > 32}}
        if bench_busy is not None:
            steps["plate-false"] = {"exit": 0, "system_busy_pct_all_cores": bench_busy, "over_load_gate": bench_busy > 32}
            (folder / "bench-plate-false.json").write_text(
                json.dumps({"timings": {"inspect_warm": {"samples": [30.0] * 5}}}), encoding="utf-8")
        if summary:
            (folder / "run-summary.json").write_text(json.dumps(
                {"src_kurtshape_tree_sha256": tree, "max_busy_pct": 32.0, "affinity": "0xffff",
                 "source_unchanged": unchanged, "steps": steps}), encoding="utf-8")
        return str(folder)

    def test_compare_ab_pools_only_gated_unchanged_runs_of_one_expected_tree(self):
        compare_ab = perf_tool("compare_ab")
        a1, a2, b1, b2 = (self.ab_run(name) for name in ("A1", "A2", "B1", "B2"))
        clean = compare_ab.compare([a1, a2], [b1, b2])
        self.assertTrue(clean["passed"], clean["invalid_reasons"])
        self.assertTrue(clean["valid"])
        self.assertEqual(clean["metrics"], 2)
        self.assertEqual({row["A_samples"] for row in clean["rows"]}, {10})
        self.assertEqual(clean["trees"]["A"], [compare_ab.FROZEN_31_TREE])

        def reasons(report):
            return " | ".join(report["invalid_reasons"])
        # (a) An over-gate step is discarded by default, and the side must re-run it.
        over = self.ab_run("A2-over", busy=55.0, ms=5000.0)
        report = compare_ab.compare([a1, over], [b1, b2])
        self.assertFalse(report["passed"])
        self.assertIn("step supplement: A pools 1 run(s), B pools 2", reasons(report))
        self.assertEqual([(item["side"], item["step"]) for item in report["discarded"]], [("A", "supplement")])
        self.assertIn("load gate", report["discarded"][0]["reasons"][0])
        self.assertEqual(report["runs"]["A"][1]["over_load_gate"], ["supplement"])
        self.assertEqual({row["A_samples"] for row in report["rows"]}, {5}, "over-gate samples are not pooled")
        rerun = self.ab_run("A2-rerun")
        report = compare_ab.compare([a1, over, rerun], [b1, b2])
        self.assertTrue(report["passed"], report["invalid_reasons"])
        self.assertEqual({row["A_samples"] for row in report["rows"]}, {10})
        # --keep-over-gate pools it for diagnosis only: the comparison cannot pass.
        kept = compare_ab.compare([a1, over], [b1, b2], keep_over_gate=True)
        self.assertEqual({row["A_samples"] for row in kept["rows"]}, {10})
        self.assertFalse(kept["passed"])
        self.assertIn("--keep-over-gate", reasons(kept))
        # The gate is per step, not per run folder.
        mixed_a = [self.ab_run("A1-bench", bench_busy=20.0), self.ab_run("A2-bench-over", bench_busy=40.0)]
        mixed_b = [self.ab_run("B1-bench", bench_busy=20.0), self.ab_run("B2-bench", bench_busy=21.0)]
        report = compare_ab.compare(mixed_a, mixed_b)
        self.assertEqual(report["runs"]["A"][1]["kept_steps"], ["supplement"])
        self.assertEqual(report["step_coverage"]["plate-false"]["A_pooled"], 1)
        self.assertIn("step plate-false: A pools 1 run(s), B pools 2", reasons(report))
        self.assertNotIn("step supplement", reasons(report))
        self.assertFalse(report["passed"])
        # A changed source, a failed step or a missing run-summary is never pooled.
        for label, folder, expected in [
                ("run source changed", self.ab_run("A2-changed", unchanged=False), "run-summary source_unchanged false"),
                ("supplement source changed", self.ab_run("A2-sup-changed", supplement_unchanged=False),
                 "supplement source_unchanged false"),
                ("failed step", self.ab_run("A2-exit", exit=1), "step exited 1"),
                ("no run-summary", self.ab_run("A2-bare", summary=False), "no run-summary.json")]:
            with self.subTest(discarded=label):
                report = compare_ab.compare([a1, folder], [b1, b2])
                self.assertFalse(report["passed"])
                self.assertIn(expected, json.dumps(report["discarded"]))
                self.assertEqual({row["A_samples"] for row in report["rows"]}, {5})
        # Trees: one per side, the A side on the frozen 3.1 tree unless told otherwise.
        other = "0" * 64
        foreign = [self.ab_run("A1-other", tree=other), self.ab_run("A2-other", tree=other)]
        for label, a_side, b_side, options, expected in [
                ("foreign A tree", foreign, [b1, b2], {}, "is not the expected " + compare_ab.FROZEN_31_TREE),
                ("mixed A trees", [a1, foreign[0]], [b1, b2], {}, "pooled runs come from 2 src trees"),
                ("mixed B trees", [a1, a2], [b1, self.ab_run("B2-other", tree=other)], {}, "B: pooled runs come from 2"),
                ("expected B tree", [a1, a2], [b1, b2], {"expect_b_tree": other}, "B: src tree"),
                ("summary and supplement disagree", [a1, self.ab_run("A2-split", supplement_tree=other)], [b1, b2], {},
                 "run-summary and supplement name different src trees"),
                ("different fixtures", [a1, a2], [b1, self.ab_run("B2-fixtures", fixtures=("studio", "drill"))], {},
                 "supplements ran different fixtures")]:
            with self.subTest(tree=label):
                report = compare_ab.compare(a_side, b_side, **options)
                self.assertFalse(report["passed"])
                self.assertFalse(report["valid"])
                self.assertIn(expected, reasons(report))
        for skip in (None, "any"):
            self.assertTrue(compare_ab.compare(foreign, [b1, b2], expect_a_tree=skip)["passed"])

    def test_compare_ab_count_allowances_are_per_counter_and_recomputes_never_grow(self):
        compare_ab = perf_tool("compare_ab")
        family = self.FAMILY
        a = [self.ab_run("A1"), self.ab_run("A2")]
        checks = [f"{counter}:{family}" for counter in compare_ab.COUNTERS[:3]]

        def blocking(report):
            return [(row["counter"], row["family"], row["direction"] if "direction" in row else row["kind"])
                    for row in report["blocking_count_differences"]]
        # Validation work on an edit family passes once each checked counter is documented.
        validated = [self.ab_run("B1-checked", brep=5, ms=600.0), self.ab_run("B2-checked", brep=5, ms=600.0)]
        report = compare_ab.compare(a, validated, bounded={family}, count_allow=checks)
        self.assertTrue(report["passed"], (report["invalid_reasons"], report["blocking_count_differences"]))
        self.assertEqual(report["unused_count_allowances"], [])
        self.assertEqual(next(row for row in report["rows"] if row["metric"] == "probe:" + family)["check_allowance_ms"], 20.0)
        # Allowing one counter does not allow the others.
        report = compare_ab.compare(a, validated, count_allow=checks[:1])
        self.assertFalse(report["passed"])
        self.assertEqual(blocking(report), [("result_check_calls_by_family", family, "increase"),
                                            ("tight_box_calls_by_family", family, "increase")])
        # C34: more native recomputes is blocking even with every counter of the family allowed.
        grown = [self.ab_run("B1-grown", brep=5, recomputes=3280), self.ab_run("B2-grown", brep=5, recomputes=3280)]
        for allowances in (checks, checks + [f"native_recomputes_by_family:{family}"]):
            with self.subTest(allowances=len(allowances)):
                report = compare_ab.compare(a, grown, bounded={family}, count_allow=allowances)
                self.assertFalse(report["passed"])
                self.assertEqual(blocking(report), [("native_recomputes_by_family", family, "increase")])
        # A decrease passes only when documented; long families compare overhead and gate recomputes too.
        long_a = [self.ab_run("A1-long", ms=1500.0), self.ab_run("A2-long", ms=1500.0)]
        fewer = [self.ab_run("B1-fewer", ms=1500.0, recomputes=820), self.ab_run("B2-fewer", ms=1500.0, recomputes=820)]
        report = compare_ab.compare(long_a, fewer)
        self.assertFalse(report["passed"])
        self.assertEqual(blocking(report), [("native_recomputes_by_family", family, "decrease")])
        self.assertEqual(next(row for row in report["rows"] if row["metric"] == "probe:" + family)["basis"], "overhead")
        self.assertEqual(len(report["long_family_recompute_count_differences"]), 1)
        report = compare_ab.compare(long_a, fewer, count_allow=[f"native_recomputes_by_family:{family}"])
        self.assertTrue(report["passed"], report["blocking_count_differences"])
        # Counters must agree inside a side; no allowance covers that.
        uneven = [self.ab_run("B1-uneven", brep=5), self.ab_run("B2-uneven", brep=6)]
        report = compare_ab.compare(a, uneven, count_allow=checks)
        self.assertFalse(report["passed"])
        self.assertIn(("brepcheck_calls_by_family", family, "nondeterministic"), blocking(report))
        # A family only B measures (a new 3.2 family) is listed, not compared; unused allowances are reported.
        extra = "studio.batch_commit_4_ms"
        newer = [self.ab_run("B1-new", extra_family=extra), self.ab_run("B2-new", extra_family=extra)]
        report = compare_ab.compare(a, newer, count_allow=checks)
        self.assertTrue(report["passed"], report["blocking_count_differences"])
        self.assertEqual(report["count_families_only_in_B"], [extra])
        self.assertEqual(report["only_in_B"], ["probe:" + extra])
        self.assertEqual(report["unused_count_allowances"], sorted(checks))
        # A bare family is refused: allowances name the counter.
        with self.assertRaisesRegex(ValueError, "COUNTER:FAMILY"):
            compare_ab.compare(a, validated, count_allow=[family])
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            compare_ab.main(["--a", a[0], "--b", validated[0], "--count-allow", family])
        self.assertEqual(caught.exception.code, 2)

    def test_run_ab_reruns_over_gate_steps_and_records_process_command_lines(self):
        run_ab = perf_tool("run_ab")
        self.assertEqual(run_ab.build_parser().parse_args(["dest"]).retries, 1)
        query = run_ab.process_query()
        self.assertIn("Get-CimInstance Win32_Process", query)
        for field in ("Name", "ProcessId", "ParentProcessId", "CreationDate", "CommandLine"):
            self.assertIn(field, query)
        for name in run_ab.WATCHED_PROCESSES:
            self.assertIn(f"Name='{name}'", query)
        row = {"Name": "pythonw.exe", "ProcessId": 7, "ParentProcessId": 3,
               "CreationDate": "2026-10-17T20:38:05.0000000-07:00", "CommandLine": "pythonw.exe -B probe.py"}
        expected = {"name": "pythonw.exe", "pid": 7, "parent_pid": 3, "created": row["CreationDate"],
                    "command_line": "pythonw.exe -B probe.py"}
        self.assertEqual(run_ab.parse_cim_processes(json.dumps([row])), [expected])
        self.assertEqual(run_ab.parse_cim_processes(json.dumps(row)), [expected], "one row may print as an object")
        self.assertEqual(run_ab.parse_cim_processes("[]"), [])
        self.assertEqual(run_ab.parse_cim_processes(""), [])

    def test_interaction_probe_reports_offered_but_unmeasured_32_families(self):
        probe = perf_tool("interaction_probe")
        families = probe.families_32(self.core)
        self.assertEqual(set(families), set(probe.FAMILIES_32))
        operations = set(self.core.dispatch({"op": "capabilities"})["result"]["operations"])
        for name, family in families.items():
            with self.subTest(family=name):
                if not set(family["requires"]) <= operations:
                    self.assertFalse(family["available_in_build"])
                expected = ("unsupported" if not family["available_in_build"]
                            else "measured" if name in probe.MEASURED_32 else "available_unmeasured")
                self.assertEqual(family["status"], expected)
                self.assertEqual(family["measured"], expected == "measured")
        self.assertFalse(families["compact_inspect"]["requires"], "compact inspect has no operation of its own")
        fake = {"offered": {"requires": ("inspect",), "owner": "test"},
                "refused": {"requires": ("inspect",), "accepts": {"op": "list_documents", "no_such_argument": 1},
                            "owner": "test"},
                "missing": {"requires": ("no_such_operation",), "owner": "test"}}
        with patch.dict(probe.FAMILIES_32, fake, clear=True):
            families = probe.families_32(self.core)
        self.assertEqual({name: family["status"] for name, family in families.items()},
                         {"offered": "available_unmeasured", "refused": "unsupported", "missing": "unsupported"})
        self.assertIn(self.doc.Name, App.listDocuments(), "detection used the caller's controller and closed nothing")


if __name__ == "__main__":
    unittest.main()
