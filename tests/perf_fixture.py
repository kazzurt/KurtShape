"""One native plate recipe and truthful measurements for the Q03 test gate."""
from collections import defaultdict
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import sys
import time
from unittest.mock import patch

import support


@contextmanager
def preserved_environment():
    """Keep a shared class fixture from becoming the per-method profile root."""
    before = dict(os.environ)
    with patch.dict(os.environ):
        yield
    if dict(os.environ) != before:
        raise AssertionError("Shared fixture must restore exact environment presence and values")


@contextmanager
def timing_events(core):
    """Capture actual events, including when the bounded native deque is full."""
    events = defaultdict(list)
    original = core.timings.record

    def record(label, milliseconds):
        events[label].append(float(milliseconds))
        original(label, milliseconds)

    core.timings.record = record
    try:
        yield events
    finally:
        core.timings.record = original


def measured(function):
    began = time.perf_counter()
    result = function()
    return result, (time.perf_counter() - began) * 1000


def summary(samples):
    values = list(samples)
    if not values or any(type(value) not in (int, float) or not math.isfinite(value) or value < 0
                         for value in values):
        raise AssertionError("Timing samples must be finite nonnegative actual measurements")
    ordered = sorted(values)
    return {"samples": values, "median_ms": statistics.median(values),
            "p95_ms": ordered[math.ceil(len(values) * .95) - 1], "worst_ms": max(values)}


def build_plate(folder):
    """Reuse the real benchmark's 60-hole recipe outside measured intervals."""
    sys.path.insert(0, str(support.ROOT / "tools" / "perf"))
    from bench_core import Benchmark
    builder = Benchmark(folder, fixture="plate", holes=60, repeat=5, measure=False)
    builder.core.default_measure = False
    try:
        fixture = builder.build()
        original = Path(folder) / "plate.FCStd"
        builder.call("save", path=str(original))
        assert builder.doc.UseHasher is False
        assert fixture["holes"] == 60
        assert abs(fixture["hole_diameter_mm"] - 30) < 1e-9
        assert len(builder.doc.Body.Shape.Solids) == 1
        return original, fixture
    finally:
        builder.close()


class FixtureOwner:
    """An honest class-fixture cleanup adapter, never an extra TestCase."""
    def __init__(self, identifier):
        self.identifier = identifier
        self.cleanups = []

    def id(self):
        return self.identifier

    def addCleanup(self, function, *args, **kwargs):
        self.cleanups.append((function, args, kwargs))

    def close(self):
        errors = []
        while self.cleanups:
            function, args, kwargs = self.cleanups.pop()
            try:
                function(*args, **kwargs)
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise errors[0]


def write_report(testcase, metrics, checks, fixture=None, budgets=None, extra=None):
    """Keep absolute misses open; correctness and final paired gates are separate."""
    import FreeCAD as App
    import Part
    evidence = support._native_fixture_path(os.environ["KURTSHAPE_EVIDENCE_DIR"], support.TEST_TMP)
    directory = support._native_fixture_path(evidence / "build-status", evidence)
    directory.mkdir(parents=True, exist_ok=True)
    destination = support._native_fixture_path(directory / (testcase._testMethodName + ".json"), directory)
    report = {"schema_version": 1, "passed": True, "test_id": testcase.id(), "pid": os.getpid(),
              "completed_utc": datetime.now(timezone.utc).isoformat(), "method": "Native Q03 consequence test",
              "engine": {"FreeCAD": App.Version(), "OCCT": Part.OCC_VERSION, "home": App.getHomePath()},
              "hardware": {"processor": os.environ.get("PROCESSOR_IDENTIFIER", platform.processor()),
                           "logical_processors": os.cpu_count(), "platform": platform.platform()},
              "measure": False if metrics else None, "fixture": fixture, "checks": checks,
              "timings": {name: summary(values) for name, values in metrics.items()},
              "budgets": {}, "limits": ["Absolute targets remain open when missed; final serial paired benchmarks decide regression.",
                                         "Headless proof does not observe GUI Modified, camera or selection."]}
    for metric, limit in (budgets or {}).items():
        median = report["timings"][metric]["median_ms"]
        report["budgets"][metric] = {"limit_ms": limit, "median_ms": median,
                                     "budget_met": median <= limit, "open": median > limit}
    paths = [support.ROOT / "tests" / name for name in ("test_build_status.py", "perf_fixture.py", "support.py")]
    paths += [support.ROOT / "src" / "kurtshape" / name for name in
              ("core.py", "geometry.py", "document_state.py", "contract.py")]
    report["source_sha256"] = {str(path.relative_to(support.ROOT)).replace("\\", "/"):
                               hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    allocation = evidence / "native-fixtures" / (testcase.folder.name + ".json")
    report["fixture_receipt"] = json.loads(allocation.read_text(encoding="utf-8"))
    if report["fixture_receipt"]["test_id"] != testcase.id() or report["fixture_receipt"]["pid"] != os.getpid():
        raise AssertionError("Fixture receipt must belong to this actual native test and PID")
    report["fixture_receipt_sha256"] = hashlib.sha256(allocation.read_bytes()).hexdigest()
    if extra:
        report.update(deepcopy(extra))
    support._native_fixture_path(destination, directory)
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")
    if metrics:
        print("PERFREPORT " + json.dumps(report, sort_keys=True, allow_nan=False), flush=True)
    return report
