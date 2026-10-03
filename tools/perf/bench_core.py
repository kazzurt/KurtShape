"""Benchmark real native controller operations in an isolated session.

The plate keeps the historical 600 mm fixture. The studio keeps U2's thirty
native features and eleven query consumers, adding auto and explicit scopes.
Historical review scripts and reports remain unchanged.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import platform
import socket
import statistics
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))
from report import evaluate_budgets

DEFAULT_SECTIONS = ("edits", "inspect", "checkpoint", "preview", "open")


def isolated_session():
    """Refuse live or incomplete profiles before importing FreeCAD."""
    names = ("KURTSHAPE_SESSION_DIR", "FREECAD_USER_HOME", "TEMP", "TMP", "APPDATA", "LOCALAPPDATA")
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise RuntimeError("Initialize an isolated validation environment first: " + ", ".join(missing))
    if any(not Path(os.environ[name]).is_absolute() for name in names):
        raise RuntimeError("Isolated environment paths must be absolute")
    paths = {name: Path(os.environ[name]).resolve() for name in names}
    session = paths["KURTSHAPE_SESSION_DIR"]
    runtime = (ROOT / "runtime").resolve()
    live = [runtime / name for name in ("user-data", "temporary", "appdata", "localappdata", "project-recovery", "freecad-1.1.4", "downloads")]
    if any(path == ROOT or path == runtime or any(path.is_relative_to(protected) for protected in live)
           for path in paths.values()):
        raise RuntimeError("Benchmark session must not use the live runtime profile")
    if any(not paths[name].is_relative_to(session) for name in names[1:]):
        raise RuntimeError("All five native profile/temp paths must belong to the isolated session")
    return session


def resolve_output(output, filename):
    """Validate the destination without creating a folder or importing native modules."""
    session = isolated_session()
    explicit_evidence = os.environ.get("KURTSHAPE_WRITE_EVIDENCE") == "1"
    base = (ROOT / "validation" if explicit_evidence else
            Path(os.environ.get("KURTSHAPE_EVIDENCE_DIR", session / "evidence"))).resolve()
    if not base.is_relative_to(session) and not (explicit_evidence and base.is_relative_to((ROOT / "validation").resolve())):
        raise RuntimeError("Benchmark evidence destination must belong to this isolated session")
    path = Path(output).resolve() if output else (base / "perf" / filename).resolve()
    if not path.is_relative_to(session) and not (explicit_evidence and path.is_relative_to((ROOT / "validation").resolve())):
        raise RuntimeError("Benchmark report must belong to this isolated session or explicitly enabled validation evidence")
    return path


def prepare_environment(scratch):
    session = isolated_session()
    scratch = Path(scratch).resolve()
    if not scratch.is_relative_to(session):
        raise RuntimeError("Benchmark scratch must belong to the isolated session")
    scratch.mkdir(parents=True, exist_ok=True)
    settings = session / "settings.json"
    data = json.loads(settings.read_text(encoding="utf-8")) if settings.is_file() else {}
    roots = data.setdefault("project_roots", [])
    if str(scratch) not in roots:
        roots.append(str(scratch))
    settings.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return scratch


def summary(samples):
    values = [float(value) for value in samples]
    if not values or not all(math.isfinite(value) for value in values):
        raise RuntimeError("A benchmark metric needs finite samples")
    return {"median": statistics.median(values), "p95": sorted(values)[math.ceil(len(values) * .95) - 1],
            "worst": max(values), "samples": values}


def timed(function, repeat):
    values = []
    result = None
    for _ in range(repeat):
        began = time.perf_counter()
        result = function()
        values.append((time.perf_counter() - began) * 1000)
    return result, values


def base_report(fixture, holes, method):
    try:
        commit = subprocess.check_output(["git", "-c", "safe.directory=" + str(ROOT), "-C", str(ROOT), "rev-parse", "HEAD"],
                                         stderr=subprocess.PIPE).decode("ascii").strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    return {"passed": False, "method": method, "checks": [], "engine": {}, "base_commit": commit,
            "run_id": datetime.now(timezone.utc).isoformat() + "/" + str(os.getpid()),
            "hardware": {"processor": os.environ.get("PROCESSOR_IDENTIFIER", platform.processor()),
                         "logical_processors": os.cpu_count(), "platform": platform.platform()},
            "fixture": {"kind": fixture, "holes": holes if fixture == "plate" else 0},
            "sections": {}, "timings": {},
            "limits": "Synthetic native fixtures; wall time includes controller work. No user comfort, Onshape parity or hosted CI claim. Profile and native geometry artifacts remain in isolated scratch."}


class Benchmark:
    def __init__(self, scratch, fixture="plate", holes=20, repeat=3, panel=None):
        import FreeCAD as App
        import Part
        import Sketcher
        from kurtshape import selectors, studio
        from kurtshape.core import Controller
        self.App, self.Part, self.Sketcher = App, Part, Sketcher
        self.selectors, self.studio = selectors, studio
        self.scratch, self.fixture, self.holes, self.repeat = Path(scratch), fixture, holes, repeat
        self.panel = panel
        self.core = panel.core if panel else Controller()
        self.state = panel.state if panel else None
        self.growth = []

    @property
    def doc(self):
        return self.core.documents[self.state["document_id"]]

    @contextmanager
    def capture(self):
        # Record events directly: a bounded Timings deque can already have 512
        # entries, so before/after length slicing would silently lose samples.
        events = defaultdict(list)
        record = self.core.timings.record
        sync = self.studio.sync_auto_scopes

        def capture_record(label, milliseconds):
            events[label].append(milliseconds)
            record(label, milliseconds)

        def scope_sync(doc):
            began = time.perf_counter()
            try:
                return sync(doc)
            finally:
                events["auto_scope_sync"].append((time.perf_counter() - began) * 1000)

        self.core.timings.record = capture_record
        self.studio.sync_auto_scopes = scope_sync
        try:
            yield events
        finally:
            self.core.timings.record = record
            self.studio.sync_auto_scopes = sync

    def call(self, op, **arguments):
        with self.capture() as events:
            began = time.perf_counter()
            if self.panel:
                result = self.panel.operation(op, **arguments)
                if result is None:
                    raise RuntimeError("GUI operation failed: " + self.panel.message.text())
                self.state = result
            else:
                request = {"op": op, **arguments}
                if op not in self.core.CREATE_OPS:
                    request.update(document_id=self.state["document_id"], expected_revision=self.state["revision"])
                response = self.core.dispatch(request)
                if not response["ok"]:
                    raise RuntimeError(json.dumps(response))
                self.state = response["result"]
            total = (time.perf_counter() - began) * 1000
        native = sum(events["native_recompute"])
        return {"total_ms": total, "native_recompute_ms": native, "overhead_ms": total - native,
                "intent_signature_ms": sum(events["intent"]), "inspection_ms": sum(events["inspection"]),
                "selector_evaluation_ms": sum(events["selector_evaluation"]),
                "auto_scope_sync_ms": sum(events["auto_scope_sync"]),
                "managed_rebuild_ms": sum(events["managed_rebuild"])}

    def build(self):
        if self.fixture == "studio":
            return self.build_studio()
        if not self.panel:
            self.call("new", name=f"Benchmark plate {self.holes} holes")
        else:
            self.doc.Label = f"Benchmark plate {self.holes} holes"
        self.call("sketch_rectangle", id="Plate", width=600, height=600)
        self.call("pad", id="Pad", profile="Plate", length=12)
        grid = math.ceil(math.sqrt(self.holes))
        self.pitch = 600 / (grid + 1)
        for index in range(self.holes):
            x, y = self.pitch * (1 + index % grid), self.pitch * (1 + index // grid)
            sketch = self.call("sketch_circle", id=f"H{index}", x=x, y=y, diameter=self.pitch * .45)
            pocket = self.call("pocket", id=f"P{index}", profile=f"H{index}")
            self.growth.append({"holes": index + 1, "add_sketch": sketch, "add_pocket": pocket})
            if index == 0 or (index + 1) % 10 == 0:
                print(f"Fixture growth: {index + 1} holes", flush=True)
        self.primary_part, self.upstream = "Body", "Pad"
        self.tip = f"H{self.holes - 1}"
        expected = (600 * 600 - self.holes * math.pi * (self.pitch * .45 / 2) ** 2) * 12
        assert abs(self.doc.Body.Shape.Volume - expected) < max(1e-6, expected * 1e-8)
        return {"kind": "plate", "holes": self.holes, "grid": grid, "pitch_mm": self.pitch,
                "hole_diameter_mm": self.pitch * .45, "objects": len(self.doc.Objects),
                "faces": len(self.doc.Body.Shape.Faces), "expected_volume_mm3": expected}

    def build_studio(self):
        App, Part = self.App, self.Part
        doc = App.newDocument("BenchmarkStudio30Features")
        doc.UseHasher = False
        for index, holes in enumerate((3, 3, 3, 2)):
            body = doc.addObject("PartDesign::Body", "Part" + str(index + 1))
            profile = body.newObject("Sketcher::SketchObject", "Profile" + str(index + 1))
            x = index * 40
            points = [App.Vector(x, 0, 0), App.Vector(x + 20, 0, 0), App.Vector(x + 20, 20, 0), App.Vector(x, 20, 0)]
            for slot, point in enumerate(points):
                profile.addGeometry(Part.LineSegment(point, points[(slot + 1) % 4]), False)
            pad = body.newObject("PartDesign::Pad", "Pad" + str(index + 1))
            pad.Profile, pad.Length = profile, 5
            doc.recompute()
            for hole in range(holes):
                sketch = body.newObject("Sketcher::SketchObject", "HoleProfile")
                sketch.MapMode = "FlatFace"
                doc.openTransaction("Bind benchmark native support selector")
                self.selectors.bind(sketch, "support", {"kind": "created_by", "feature": pad.Name, "cap": "end"})
                doc.recompute()
                center = sketch.Placement.inverse().multVec(App.Vector(x + 5 + hole * 5, 10, 5))
                sketch.addGeometry(Part.Circle(center, App.Vector(0, 0, 1), 1), False)
                pocket = body.newObject("PartDesign::Pocket", "Pocket")
                pocket.Profile, pocket.Type = sketch, 1
                self.selectors.recompute(doc)
                doc.commitTransaction()
        base_features = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject" or
                         obj.TypeId.startswith("PartDesign::") and obj.TypeId != "PartDesign::Body"]
        base_parts = [obj for obj in doc.Objects if obj.TypeId == "PartDesign::Body"]
        consumers = [obj for obj in doc.Objects if "QueryInputs" in obj.PropertiesList]
        assert len(base_features) == 30 and len(base_parts) == 4 and len(consumers) == 11
        assert all(body.Shape.isValid() and len(body.Shape.Solids) == 1 for body in base_parts)
        self.core.attach(doc)
        self.state = self.core.inspect(doc)
        if self.panel:
            App.setActiveDocument(doc.Name)
            self.panel.state = self.state
            self.panel.refresh()
        self.primary_part, self.upstream, self.tip = "Part1", "Pad1", "BenchAutoProfile"
        self.call("sketch_rectangle", id=self.tip, body=self.primary_part, x=18, y=0, width=5, height=2)
        self.call("pocket", id="BenchAutoCut", profile=self.tip, body=self.primary_part,
                  through_all=True, operation="remove", merge_scope="auto")
        self.call("sketch_rectangle", id="BenchExplicitProfile", body=self.primary_part, x=0, y=0, width=2, height=2)
        self.call("pad", id="BenchExplicitAdd", profile="BenchExplicitProfile", body=self.primary_part,
                  length=7, operation="add", merge_scope=[self.primary_part])
        assert self.studio.enabled(doc) and len(self.studio.current_parts(doc)) == 4
        assert not self.selectors.reference_errors(doc)
        return {"kind": "studio", "base_features": 30, "base_parts": 4, "selector_consumers": 11,
                "scoped_operations": ["BenchAutoCut: remove/auto", "BenchExplicitAdd: add/Part1"],
                "studio_features": len(self.studio.order(doc)), "logical_parts": len(self.studio.current_parts(doc)),
                "objects": len(doc.Objects)}

    def edits(self):
        tip, upstream = [], []
        additions = {"add_sketch": [], "add_pocket": []}
        if self.fixture == "plate":
            # Each pair starts on the completed N-hole fixture. Undo and
            # geometry verification are outside the measured operations.
            grid = math.ceil(math.sqrt(self.holes))
            x, y = (self.pitch * (1 + self.holes % grid), self.pitch * (1 + self.holes // grid)) if self.holes < grid * grid else (self.pitch / 2, self.pitch / 2)
            objects, volume = {obj.Name for obj in self.doc.Objects}, self.doc.Body.Shape.Volume
            for _ in range(self.repeat):
                additions["add_sketch"].append(self.call("sketch_circle", id="BenchAddedHole", x=x, y=y, diameter=min(20, .3 * self.pitch)))
                additions["add_pocket"].append(self.call("pocket", id="BenchAddedPocket", profile="BenchAddedHole"))
                self.call("undo")
                self.call("undo")
                assert {obj.Name for obj in self.doc.Objects} == objects
                assert abs(self.doc.Body.Shape.Volume - volume) < max(1e-6, volume * 1e-8)
        for index in range(self.repeat):
            value = (5 if index % 2 else 125) if self.fixture == "studio" else self.pitch * (.40 + .01 * (index % 3))
            tip.append(self.call("set_parameter", feature=self.tip,
                                 parameter="Width" if self.fixture == "studio" else "Diameter", value=value))
            if self.fixture == "studio":
                assert len(self.doc.BenchAutoCut.KurtShapeMergePartIds) == (4 if value == 125 else 1)
                assert len(self.studio.current_parts(self.doc)) == 4
                assert not self.selectors.reference_errors(self.doc)
        initial_length = float(self.doc.getObject(self.upstream).Length)
        for index in range(self.repeat):
            upstream.append(self.call("set_parameter", feature=self.upstream, parameter="Length",
                                      value=initial_length + (1 if index % 2 == 0 else .5)))
        metrics = {}
        for label, samples in (("tip_edit", tip), ("upstream_edit", upstream)):
            metrics.update({label + "." + key: [item[key] for item in samples] for key in samples[0]})
        for label, samples in additions.items():
            if samples:
                metrics.update({label + "." + key: [item[key] for item in samples] for key in samples[0]})
        return metrics

    def inspect(self):
        request = lambda: self.core.dispatch({"op": "inspect", "document_id": self.state["document_id"]})

        def warm():
            response = request()
            assert response["ok"], response
            self.state = response["result"]
        warm()
        _, samples = timed(warm, self.repeat)
        changed = []
        for _ in range(self.repeat):
            self.doc.openTransaction("Benchmark native upstream edit")
            try:
                upstream = self.doc.getObject(self.upstream)
                upstream.Length = upstream.Length.Value + .5
                self.doc.recompute()
                self.doc.commitTransaction()
            except Exception:
                self.doc.abortTransaction()
                raise
            _, elapsed = timed(warm, 1)
            changed += elapsed
        return {"inspect_warm_ms": samples, "inspect_after_change_ms": changed}

    def checkpoint(self):
        def capture():
            result = self.core.checkpoint(self.doc, force=True)
            assert result is not None, "Forced checkpoint returned no recovery record"
        return {"checkpoint_ms": timed(capture, self.repeat)[1]}

    def preview(self):
        from kurtshape.extrusion_preview import ExtrusionEvaluator
        x, y = (2, 16) if self.fixture == "studio" else (self.pitch / 2, self.pitch / 2)
        diameter = 2 if self.fixture == "studio" else min(20, .3 * self.pitch)
        self.call("sketch_circle", id="BenchPreviewProfile", body=self.primary_part, x=x, y=y, diameter=diameter)
        first, updates = [], []
        for index in range(self.repeat):
            evaluator = ExtrusionEvaluator(self.core, self.doc, self.state["revision"])
            proposal = {"op": "pad", "profile": "BenchPreviewProfile", "length": 25 + index,
                        "body": self.primary_part}
            if self.fixture == "studio":
                proposal.update(operation="add", merge_scope=[self.primary_part])
            try:
                began = time.perf_counter()
                result = evaluator.evaluate(proposal)
                first.append((time.perf_counter() - began) * 1000)
                assert result.valid, result.error
                began = time.perf_counter()
                result = evaluator.evaluate(dict(proposal, length=35 + index))
                updates.append((time.perf_counter() - began) * 1000)
                assert result.valid, result.error
            finally:
                evaluator.close()
        return {"preview_first_ms": first, "preview_update_ms": updates}

    def rebuild(self):
        samples = [self.call("rebuild") for _ in range(self.repeat)]
        return {"total_rebuild_ms": [item["total_ms"] for item in samples],
                **{key: [item[key] for item in samples] for key in
                   ("native_recompute_ms", "selector_evaluation_ms", "auto_scope_sync_ms", "managed_rebuild_ms")}}

    def open(self):
        path = self.scratch / (self.fixture + "-benchmark.FCStd")
        self.call("save", path=str(path))
        self.App.closeDocument(self.doc.Name)

        native = []
        for _ in range(self.repeat):
            opened = None
            try:
                began = time.perf_counter()
                opened = self.App.openDocument(str(path), True)
                native.append((time.perf_counter() - began) * 1000)
            finally:
                if opened is not None:
                    self.App.closeDocument(opened.Name)
        managed = []
        for _ in range(self.repeat):
            measured = self.call("open", path=str(path))
            managed.append(measured["total_ms"])
            self.App.closeDocument(self.doc.Name)
        return {"native_open_ms": native, "kurtshape_open_ms": managed}

    def close(self):
        if not self.panel:
            for doc in list(self.core.documents.values()):
                if self.core._is_open(doc):
                    self.App.closeDocument(doc.Name)
            self.core.close()


def run_sections(benchmark, report, sections):
    for name in sections:
        try:
            samples = getattr(benchmark, name)()
            metrics = {key: summary(values) for key, values in samples.items()}
            report["sections"][name] = {"status": "ok", "metrics": sorted(metrics)}
            report["timings"].update(metrics)
            report["checks"].append(name + " metrics measured through the current native APIs")
        except Exception:
            report["sections"][name] = {"status": "unavailable", "error": traceback.format_exc(), "metrics": []}
    report["passed"] = bool(sections) and all(report["sections"][name]["status"] == "ok" for name in sections)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", choices=("plate", "studio"), default="plate")
    parser.add_argument("--holes", type=int, default=20)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--out")
    parser.add_argument("--scratch")
    parser.add_argument("--sections", default=",".join(DEFAULT_SECTIONS))
    parser.add_argument("--phase", choices=("phase0", "phase1"), default="phase0")
    parser.add_argument("--best", "--baseline", dest="best", help="Comparable best-so-far baseline report")
    parser.add_argument("--confirm")
    parser.add_argument("--enforce", action="store_true")
    args = parser.parse_args()
    if args.holes < 1 or args.repeat < 1:
        parser.error("holes and repeat must be positive")
    sections = list(dict.fromkeys(args.sections.split(",")))
    if any(name not in (*DEFAULT_SECTIONS, "rebuild") for name in sections):
        parser.error("Unknown benchmark section")
    if args.fixture == "studio" and "rebuild" not in sections:
        sections.insert(0, "rebuild")
    # Open is destructive to the in-memory fixture, so always measure it last.
    sections = [name for name in sections if name != "open"] + (["open"] if "open" in sections else [])
    try:
        output = resolve_output(args.out, f"bench-{args.fixture}-{args.holes if args.fixture == 'plate' else 'query-scopes'}.json")
    except RuntimeError as exc:
        parser.error(str(exc))
    report = base_report(args.fixture, args.holes, "Bundled native Python; real revision-checked Controller.dispatch and isolated FCStd fixtures")
    report["repeat"] = args.repeat
    report["add_operation_sampling"] = "Repeated sketch/pocket additions on the completed fixture; two undos and geometry verification outside measured operations"
    benchmark = None
    began = time.perf_counter()
    try:
        session = Path(os.environ.get("KURTSHAPE_SESSION_DIR", ROOT / "runtime" / "bench")).resolve()
        scratch = prepare_environment(args.scratch or session / "benchmark-working")

        def deny_network(*arguments, **keywords):
            raise RuntimeError("Networking disabled for native benchmark")
        socket.socket.connect = deny_network
        socket.create_connection = deny_network
        socket.getaddrinfo = deny_network
        benchmark = Benchmark(scratch, args.fixture, args.holes, args.repeat)
        report["engine"] = {"FreeCAD": benchmark.App.Version(), "OCCT": benchmark.Part.OCC_VERSION}
        report["fixture"] = benchmark.build()
        report["checks"].append("Native fixture geometry and expected feature/part/query counts verified")
        report["growth"] = benchmark.growth
        report["scratch"] = str(scratch)
        run_sections(benchmark, report, sections)
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        if benchmark is not None:
            try:
                benchmark.close()
            except Exception:
                report.update(passed=False, cleanup_error=traceback.format_exc())
    try:
        best = json.loads(Path(args.best).read_text(encoding="utf-8-sig")) if args.best else None
        confirmation = json.loads(Path(args.confirm).read_text(encoding="utf-8-sig")) if args.confirm else None
        report["budgets"] = evaluate_budgets(report, args.phase, best, confirmation)
    except Exception:
        report.update(passed=False, budget_error=traceback.format_exc(),
                      budgets={"evaluated": False, "failed": False, "reason": "Budget inputs unavailable", "metrics": []})
    report["seconds"] = time.perf_counter() - began
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "fixture": report["fixture"], "sections": report["sections"],
                      "report": str(output), "seconds": report["seconds"]}), flush=True)
    return 1 if not report["passed"] or args.enforce and report["budgets"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
