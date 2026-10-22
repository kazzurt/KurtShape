"""Run each regression suite in a fresh, isolated bundled Python process."""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import traceback
import unittest
import uuid
import xml.etree.ElementTree as ET

from kurtshape_evidence import ROOT, evidence_dir, register_runtime_folder

SUITES = {
    "native": (
        "test_core.NativeCoreTests", "test_onshape.NativeConversionTests",
        "test_incremental_state.IncrementalDocumentStateTests",
        "test_snapshots.SnapshotStoreTests", "test_snapshots.NativeSnapshotSharingTests",
        "test_onshape.PreflightTests", "test_core_safety.CoreSafetyTests",
        "test_sketch_planes.SketchPlaneTests", "test_sketch_arcs.SketchArcTests",
        "test_sketch_polylines.SketchPolylineTests",
        "test_navigation.SketchProjectionTests",
        "test_sketch_snapping.SketchSnappingTests",
        "test_sketch_cursor.SketchCursorTests",
        "test_sketch_constraints.SketchConstraintTests",
        "test_review_followup.ReviewFollowupTests", "test_step_import.StepImportTests",
        "test_assembly.AssemblyWorkflowTests", "test_extrusion_preview.ExtrusionPreviewTests",
        "test_extrusion_edit.ExtrusionEditTests", "test_history_lifecycle.HistoryLifecycleTests",
        "test_everyday_modeling.EverydayModelingDirectionTests",
        "test_dress_up_edit.DressUpEditTests", "test_holes.HoleTests",
        "test_borrowed_preview.BorrowedPreviewTests",
        "test_preview_worker_leases.PreviewWorkerLeaseTests",
        "test_step_export_jobs.StepExportJobTests", "test_step_export_jobs.StepExportWorkerLifetimeTests",
        "test_step_capture.StepDigestCandidateTests",
        "test_geometry_check_jobs.GeometryCheckJobTests",
        "test_geometry_check_jobs.GeometryCheckWorkerLifetimeTests",
        "test_render_jobs.RenderWorkerLifetimeTests", "test_model_render.ModelRenderTests",
        "test_render_jobs.RenderJobTests", "test_render_jobs.RenderOwnershipTests",
        "test_gui_view.GuiViewTests",
        "test_parameters.ParameterTests", "test_parameters.ParameterPruningTests", "test_batch.BatchTests",
        "test_snapshot_transport.SnapshotTransportTests",
        "test_reference_tools.ReferenceToolTests", "test_datum_planes.DatumPlaneFrameTests",
        "test_selectors.SelectorTests",
        "test_face_provenance.FaceProvenanceTests",
        "test_selector_preparation.SelectorPreparationTests",
        "test_selector_parameters.SelectorParameterTests",
        "test_scope_membership.ScopeMembershipTests",
        "test_part_studio.PartStudioTests", "test_pattern_tools.PatternToolTests",
        "test_result_checks.ResultCheckTests",
        "test_result_validation.ResultValidationTests", "test_result_validation.ResultValidationPerfTests",
        "test_selector_consumers.SelectorConsumerTests",
        "test_multi_edge_references.MultiEdgeReferenceTests",
        "test_runtime_layout.RuntimeLayoutTests", "test_settings.SettingsTests",
        "test_native_files.NativeFileBehaviorTests",
        "test_native_validation_snapshot.NativeValidationSnapshotTests",
        "test_build_status.BuildStatusTests", "test_build_status.StatusPerformanceTests",
        "test_geometry_queries.GeometryQueryTests",
        "test_responsiveness.InteractionTimingTests", "test_responsiveness.HistoryModelTests",
        "test_responsiveness.SketchStallDiagnosticsTests",
        "test_responsiveness.RecoverySchedulingTests",
        "test_validation_tooling.ValidationToolingTests",
        "test_dispatch_pipeline.DispatchPipelineTests", "test_contract32_conventions.Contract32ConventionTests",
        "test_document_lifecycle.DocumentLifecycleTests", "test_compact_inspection.CompactInspectionTests",
        "test_parameter_panel.ParameterPanelTests", "test_parameter_panel.SectionLayoutTests", "test_parameter_panel.ParameterAdapterTranslationTests",
        "test_operation_schemas.OperationSchemaTests",
        "test_section_view.SectionViewGeometryTests", "test_section_view.SectionViewSelectionTests",
        "test_section_view.PolygonFillTests",
        # Slice A/B wave 1 (docs/slice-ab/RECORD.md): registered ahead of the units so no two of them edit this file.
        "test_icon_cache.IconCacheTests",
    ),
    "bridge": ("test_bridge.BridgeTimeoutTests", "test_bridge.BridgeDeferredTests", "test_batch.BatchBridgeTests", "test_assistant_client.AssistantClientReconciliationTests", "test_bridge_native.NativeBridgeStatusTests",
               "test_build_identity.BuildIdentityTests"),
    "shortcuts": ("test_shortcuts.RouterTests", "test_shortcuts.QtRoutingTests", "test_tool_session.ToolSessionTests",
                  "test_tool_search.ToolSearchTests"),
    "workflows": (),
}
EXTERNAL_SKIP_PREFIX = "external fixture:"
PERF_SKIP_PREFIX = "perf:"


def kurtshape_build_sha256():
    """The loaded-build digest of src/kurtshape as build_identity computes it (module loaded by path).

    A report can then be matched to a running app's capabilities.build.source_sha256.
    """
    path = ROOT / "src" / "kurtshape" / "build_identity.py"
    spec = importlib.util.spec_from_file_location("kurtshape_build_identity_standalone", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.snapshot(path.parent)["sha256"]


def source_snapshot():
    files = sorted((ROOT / "src" / "kurtshape").rglob("*.py"))
    files += sorted((ROOT / "tests").rglob("*.py"))
    files += [Path(__file__).resolve(), ROOT / "tools" / "validate_offline.py",
              ROOT / "tools" / "kurtshape_evidence.py",
              ROOT / "tools" / "native_validation_snapshot.py",
              ROOT / "tools" / "perf" / "bench_core.py",
              ROOT / "tools" / "perf" / "report.py",
              ROOT / "tools" / "perf" / "budgets.json",
              # Imported by test_validation_tooling (A/B acceptance tooling).
              ROOT / "tools" / "perf" / "compare_ab.py",
              ROOT / "tools" / "perf" / "run_ab.py",
              ROOT / "tools" / "perf" / "interaction_probe.py"]
    return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files}


def unassigned_test_cases():
    """Inventory TestCase declarations without importing FreeCAD in the parent."""
    assigned = {item for classes in SUITES.values() for item in classes}
    modules, declarations = {}, []
    for path in sorted((ROOT / "tests").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        module = ".".join(path.relative_to(ROOT / "tests").with_suffix("").parts)
        aliases = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for item in node.names:
                    aliases.setdefault(item.asname or item.name.split(".")[0],
                                       item.name if item.asname else item.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                imported_module = node.module or ""
                if node.level:
                    package = module.split(".")[:-1]
                    package = package[:len(package) - node.level + 1]
                    imported_module = ".".join(package + ([imported_module] if imported_module else []))
                for item in node.names:
                    if item.name == "*":
                        if node.module in {"unittest", "unittest.case"}:
                            aliases.setdefault("TestCase", "unittest.TestCase")
                    else:
                        aliases.setdefault(item.asname or item.name, imported_module + "." + item.name)
            elif isinstance(node, ast.ClassDef):
                # Preserve every declaration: a nested same-name class cannot
                # replace an earlier TestCase in this conservative inventory.
                declarations.append((module + "." + node.name, module, node.bases,
                                     path.name.startswith("test_")))
        modules[module] = aliases

    def qualified_name(node):
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            prefix = qualified_name(node.value)
            return prefix + "." + node.attr if prefix else None
        if isinstance(node, ast.Subscript):
            return qualified_name(node.value)
        return None

    def resolve(module, node):
        name = qualified_name(node)
        if not name:
            return None
        head, separator, tail = name.partition(".")
        target = modules[module].get(head, module + "." + head)
        if separator:
            target += "." + tail
        seen = set()
        while target not in seen:
            seen.add(target)
            if target.startswith("tests.") and target[6:].rpartition(".")[0] in modules:
                target = target[6:]
                continue
            owner, _, symbol = target.rpartition(".")
            replacement = modules.get(owner, {}).get(symbol)
            if replacement is None:
                return target
            target = replacement
        return target

    known = {"unittest.TestCase", "unittest.case.TestCase"}
    changed = True
    while changed:
        changed = False
        for name, module, bases, _ in declarations:
            if name not in known and any(resolve(module, base) in known for base in bases):
                known.add(name)
                changed = True
    declared = {name for name, _, _, is_test_file in declarations
                if is_test_file and name in known}
    return sorted(declared - assigned)


def isolated_environment(folder):
    folder = folder.resolve()
    environment = os.environ.copy()
    locations = {
        "KURTSHAPE_SESSION_DIR": folder / "session",
        "FREECAD_USER_HOME": folder / "user-data",
        "TEMP": folder / "temporary", "TMP": folder / "temporary",
        "APPDATA": folder / "appdata", "LOCALAPPDATA": folder / "localappdata",
        "KURTSHAPE_TEST_RUN_DIR": folder,
    }
    for name, path in locations.items():
        path.mkdir(parents=True, exist_ok=True)
        environment[name] = str(path)
    environment.update(PYTHONDONTWRITEBYTECODE="1", QT_QPA_PLATFORM="offscreen")
    environment["KURTSHAPE_EVIDENCE_DIR"] = str(folder / "evidence")
    return environment


def write_json(path, value):
    path = Path(path).resolve()
    register_runtime_folder(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases = []
        self.active = {}

    def startTest(self, test):
        super().startTest(test)
        self.active[test.id()] = {"id": test.id(), "status": "passed", "seconds": 0.0,
                                  "started": time.perf_counter()}

    def stopTest(self, test):
        case = self.active.pop(test.id())
        case["seconds"] = time.perf_counter() - case.pop("started")
        self.cases.append(case)
        super().stopTest(test)

    def mark(self, test, status, detail=""):
        case = self.active.get(test.id())
        if case is None:
            # unittest reports module/class fixture failures through _ErrorHolder
            # without startTest/stopTest. Keep these visible in JSON and JUnit.
            self.cases.append({"id": test.id(), "status": status, "seconds": 0.0,
                               "detail": detail})
        else:
            severity = {"passed": 0, "expected_failure": 1, "skipped": 2,
                        "failure": 3, "error": 4}
            if severity[status] >= severity[case["status"]]:
                case["status"] = status
            case["detail"] = "\n".join(filter(None, (case.get("detail"), detail)))

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.mark(test, "failure", self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        self.mark(test, "error", self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.mark(test, "skipped", reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self.mark(test, "expected_failure", self._exc_info_to_string(err, test))

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.mark(test, "failure", "Unexpected success")

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self.mark(test, "failure" if issubclass(err[0], test.failureException) else "error",
                      self._exc_info_to_string(err, test))


def counts(cases):
    tally = Counter(case["status"] for case in cases)
    return {"tests": len(cases), "passed": tally["passed"], "skipped": tally["skipped"],
            "failures": tally["failure"], "errors": tally["error"],
            "expected_failures": tally["expected_failure"]}


def select_tests(only):
    """Route MODULE[.CLASS[.METHOD]] names to their registered suites, in SUITES order.

    A bare module selects every class of that module registered in SUITES. A name
    that is not covered by a SUITES entry raises ValueError: --only never runs an
    unregistered class, so partial runs cannot hide the inventory gate.
    """
    selection = {}
    unknown = []
    for name in dict.fromkeys(only):
        if not isinstance(name, str) or not name or name != name.strip() or ".." in name:
            unknown.append(repr(name))
            continue
        routes = []
        for suite, classes in SUITES.items():
            for registered in classes:
                if name == registered or name.startswith(registered + "."):
                    routes.append((suite, name))
                elif registered.startswith(name + ".") and "." not in registered[len(name) + 1:]:
                    routes.append((suite, registered))
        if not routes:
            unknown.append(name)
            continue
        for suite, target in routes:
            selection.setdefault(suite, [])
            if target not in selection[suite]:
                selection[suite].append(target)
    if unknown:
        raise ValueError("not registered in SUITES: " + ", ".join(unknown))
    return {suite: selection[suite] for suite in SUITES if suite in selection}


def child_suite(name, report_path, only=None):
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT / "tests"))
    before = source_snapshot()
    started = time.perf_counter()
    report = {"name": name, "passed": False, "cases": [], "engine": {}}
    if only:
        report["selection"] = list(only)
    try:
        if name == "native":
            def deny_network(*args, **kwargs):
                raise RuntimeError("Networking disabled for offline modeling validation")
            socket.socket.connect = deny_network
            socket.create_connection = deny_network
            socket.getaddrinfo = deny_network
            report["network"] = "Python connect/create_connection/DNS denied"
        else:
            report["network"] = "Loopback available for bridge transport regression"
        if name == "workflows" and only:
            raise RuntimeError("The workflows suite has no selectable test classes")
        if name == "workflows":
            module = importlib.import_module("validate_modeling_workflows")
            code = module.main()
            report["workflow"] = module.REPORT
            report["engine"] = module.REPORT["engine"]
            report["cases"] = [{"id": f"workflows.{case['name']}",
                                "status": "passed" if case["passed"] else "failure",
                                "seconds": 0.0, "detail": case.get("failure", ""),
                                "checks": len(case.get("checks", []))}
                               for case in module.REPORT["cases"]]
            report["checks"] = module.REPORT["checks"]
            report["passed"] = code == 0
        else:
            suite = unittest.defaultTestLoader.loadTestsFromNames(list(only) if only else SUITES[name])
            result = unittest.TextTestRunner(verbosity=2, resultclass=RecordingResult).run(suite)
            report["cases"] = result.cases
            report["passed"] = result.wasSuccessful()
            report["skips"] = [{"id": test.id(), "reason": reason} for test, reason in result.skipped]
            if name == "native":
                import FreeCAD as App
                import Part
                report["engine"] = {"FreeCAD": App.Version(), "OCCT": Part.OCC_VERSION}
    except Exception:
        report["error"] = traceback.format_exc()
        print(report["error"], file=sys.stderr)
    report.update(seconds=time.perf_counter() - started, counts=counts(report["cases"]),
                  source_sha256=before, source_unchanged=source_snapshot() == before)
    report["passed"] = report["passed"] and report["source_unchanged"]
    write_json(report_path, report)
    return 0 if report["passed"] else 1


def log_process(pid, command, session):
    folder = ROOT / "runtime" / "longrun"
    register_runtime_folder(folder)
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "pids.txt").open("a", encoding="utf-8") as stream:
        stream.write(f"{pid}\t{subprocess.list2cmdline(command)}\tsession={session}\n")


def reap_owned_process(process):
    """Kill only our Popen child if necessary, and always reap its handle."""
    try:
        if process.poll() is None:
            process.kill()
        try:
            return process.communicate(timeout=10)
        except Exception:
            return "", None
    finally:
        for pipe in (process.stdout, process.stderr):
            if pipe is not None:
                pipe.close()
        process.wait(timeout=10)


def child_command(name, report_path, only=None):
    command = [sys.executable, "-B", str(Path(__file__).resolve()),
               "--in-process", name, "--report", str(report_path)]
    for item in only or ():
        command += ["--only", item]
    return command


def run_suite(name, folder, timeout, only=None, perf=False):
    folder.mkdir(parents=True, exist_ok=True)
    report_path = folder / "suite-result.json"
    command = child_command(name, report_path, only)
    environment = isolated_environment(folder)
    if perf:
        # Child only: support.perf_only classes run; the parent environment is untouched.
        environment["KURTSHAPE_PERF"] = "1"
    started = time.perf_counter()
    process = subprocess.Popen(command, cwd=ROOT, env=environment,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace",
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    timed_out = False
    execution_error = None
    try:
        log_process(process.pid, command, folder / "session")
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        output, _ = reap_owned_process(process)
    except Exception:
        execution_error = traceback.format_exc()
        output, _ = reap_owned_process(process)
    except BaseException:
        reap_owned_process(process)
        raise
    (folder / "suite-output.txt").write_text(output, encoding="utf-8")
    try:
        print(output, end="", flush=True)
    except UnicodeEncodeError:
        # A redirected console may be cp1252; the child's text (an en dash in a message) must not fail the suite.
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(output.encode(encoding, "replace").decode(encoding), end="", flush=True)
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
    else:
        report = {"name": name, "passed": False, "cases": [], "counts": counts([]),
                  "error": "Child produced no result report", "source_unchanged": False}
    report.update(exit_code=process.returncode, pid=process.pid,
                  seconds=time.perf_counter() - started, timed_out=timed_out)
    report["passed"] = report["passed"] and process.returncode == 0 and not timed_out and execution_error is None
    if timed_out:
        report["error"] = f"Suite exceeded {timeout:g} second timeout"
    if execution_error is not None:
        report["error"] = execution_error
    return report


def junit_report(path, report):
    root = ET.Element("testsuites")
    for suite in report["suites"]:
        total = suite["counts"]
        diagnostics = []
        if suite.get("error"):
            diagnostics.append(("suite_execution", suite["error"]))
        if not suite.get("source_unchanged", False):
            diagnostics.append(("source_unchanged", "Source hash changed during the regression run"))
        if suite.get("rejected_skips"):
            diagnostics.append(("required_test_skipped", json.dumps(suite["rejected_skips"])))
        if suite.get("exit_code", 0) != 0:
            diagnostics.append(("child_exit_code", f"Child exited with code {suite['exit_code']}"))
        node = ET.SubElement(root, "testsuite", name=suite["name"], tests=str(total["tests"] + len(diagnostics)),
                             failures=str(total["failures"]), errors=str(total["errors"] + len(diagnostics)),
                             skipped=str(total["skipped"]), time=str(suite["seconds"]))
        for case in suite["cases"]:
            classname, _, name = case["id"].rpartition(".")
            item = ET.SubElement(node, "testcase", classname=classname, name=name,
                                 time=str(case["seconds"]))
            if case["status"] in {"failure", "error", "skipped"}:
                message = case.get("detail", "")
                ET.SubElement(item, case["status"], message=message.split("\n")[0]).text = message
        for name, message in diagnostics:
            item = ET.SubElement(node, "testcase", classname="runner", name=name)
            ET.SubElement(item, "error", message=message.split("\n")[0]).text = message
    if report.get("unassigned_test_cases"):
        node = ET.SubElement(root, "testsuite", name="suite_inventory", tests="1", errors="1")
        item = ET.SubElement(node, "testcase", classname="runner", name="all_test_cases_assigned")
        ET.SubElement(item, "error").text = "\n".join(report["unassigned_test_cases"])
    if not report.get("source_unchanged", False):
        node = ET.SubElement(root, "testsuite", name="runner_integrity", tests="1", errors="1")
        item = ET.SubElement(node, "testcase", classname="runner", name="parent_source_unchanged")
        ET.SubElement(item, "error").text = "Source hash changed across the parent regression run"
    destination = Path(path).resolve()
    register_runtime_folder(destination.parent)
    destination.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(destination, encoding="utf-8", xml_declaration=True)


def step_summary(report):
    destination = os.environ.get("GITHUB_STEP_SUMMARY")
    if not destination:
        return
    lines = ["## KurtShape regression suites", "", "| Suite | Passed | Skipped | Failed | Seconds |",
             "|---|---:|---:|---:|---:|"]
    for suite in report["suites"]:
        total = suite["counts"]
        lines.append(f"| {suite['name']} | {total['passed']} | {total['skipped']} | "
                     f"{total['failures'] + total['errors']} | {suite['seconds']:.3f} |")
    lines += ["", f"Overall: {'PASS' if report['passed'] else 'FAIL'}", ""]
    with Path(destination).open("a", encoding="utf-8") as stream:
        stream.write("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=tuple(SUITES), action="append")
    parser.add_argument("--report")
    parser.add_argument("--junit")
    parser.add_argument("--require-native", action="store_true")
    parser.add_argument("--require-external", action="store_true")
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--keep-temp", action="store_true")
    parser.add_argument("--only", action="append", metavar="MODULE[.CLASS[.METHOD]]",
                        help="run only these registered tests (repeatable); a partial run, never the regression result")
    parser.add_argument("--perf", action="store_true",
                        help="set KURTSHAPE_PERF=1 in the suite children so perf_only classes run")
    parser.add_argument("--in-process", choices=tuple(SUITES), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.in_process:
        if not args.report or not os.environ.get("KURTSHAPE_TEST_RUN_DIR"):
            parser.error("--in-process requires the parent run environment and --report")
        return child_suite(args.in_process, args.report, args.only)
    selection = None
    if args.only:
        if os.environ.get("KURTSHAPE_WRITE_EVIDENCE"):
            # A partial report must never become tracked validation/ evidence.
            parser.error("--only cannot be combined with KURTSHAPE_WRITE_EVIDENCE")
        try:
            selection = select_tests(args.only)
        except ValueError as exc:
            parser.error(str(exc))
        if args.suite and not set(selection) <= set(args.suite):
            parser.error("--only selects tests outside --suite: " + ", ".join(sorted(set(selection) - set(args.suite))))
    before = source_snapshot()
    missing = unassigned_test_cases()
    requested = list(selection) if selection else list(dict.fromkeys(args.suite or SUITES))
    base = Path(os.environ.get("KURTSHAPE_TEST_TMP", ROOT / "runtime" / "test-tmp")).resolve()
    register_runtime_folder(base)
    base.mkdir(parents=True, exist_ok=True)
    run = base / (time.strftime("regression-run-%Y%m%d-%H%M%S-") + str(os.getpid()) + "-" + uuid.uuid4().hex[:8])
    report_path = Path(args.report) if args.report else evidence_dir("test-runner") / "report.json"
    junit_path = Path(args.junit) if args.junit else report_path.with_suffix(".xml")
    report = {"passed": False, "method": "Fresh isolated Python subprocess per suite",
              "suites": [], "unassigned_test_cases": missing, "run_dir": str(run),
              "kurtshape_build_sha256": kurtshape_build_sha256(),
              "limits": "Headless native and Qt regressions; no GUI acceptance or native C++ networking interception"}
    if selection:
        report["selection"] = list(dict.fromkeys(args.only))
    if args.perf:
        report["perf"] = True
    started = time.perf_counter()
    if missing:
        print("Unassigned TestCase classes: " + ", ".join(missing), file=sys.stderr)
    else:
        for name in requested:
            print(f"Running {name} suite in {run / name}", flush=True)
            only = selection.get(name) if selection else None
            try:
                suite = run_suite(name, run / name, args.timeout, only, args.perf)
            except Exception:
                suite = {"name": name, "passed": False, "cases": [], "counts": counts([]),
                         "seconds": 0.0, "source_unchanged": False, "error": traceback.format_exc()}
            if only:
                suite["selection"] = list(only)
            rejected = []
            for skip in suite.get("skips", []):
                reason = skip["reason"]
                if args.require_external and reason.startswith((EXTERNAL_SKIP_PREFIX, PERF_SKIP_PREFIX)) or (
                    args.require_native and not reason.startswith((EXTERNAL_SKIP_PREFIX, PERF_SKIP_PREFIX))
                ):
                    rejected.append(skip)
            suite["rejected_skips"] = rejected
            suite["passed"] = suite["passed"] and not rejected
            report["suites"].append(suite)
    report.update(seconds=time.perf_counter() - started, source_sha256=before,
                  source_unchanged=source_snapshot() == before,
                  counts=counts([case for suite in report["suites"] for case in suite["cases"]]))
    report["engine"] = next((suite["engine"] for suite in report["suites"]
                              if suite.get("engine")), {})
    report["passed"] = not missing and report["source_unchanged"] and all(
        suite["passed"] for suite in report["suites"])
    write_json(report_path, report)
    junit_report(junit_path, report)
    step_summary(report)
    if os.environ.get("KURTSHAPE_WRITE_EVIDENCE") == "1":
        native = next((suite for suite in report["suites"] if suite["name"] == "native"), None)
        if native is not None:
            legacy = dict(native, tests=native["counts"]["tests"], limits=report["limits"])
            write_json(evidence_dir("") / "offline-test-result.json", legacy)
    if report["passed"] and not args.keep_temp and run.is_dir():
        shutil.rmtree(run)
    print(json.dumps({"passed": report["passed"], "counts": report["counts"],
                      "report": str(report_path.resolve()), "junit": str(junit_path.resolve())}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
