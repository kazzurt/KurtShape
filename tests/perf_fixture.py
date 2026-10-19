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


# Zimmer 5978-14 step drill body with two U flutes on 30-degree helices (Y is the
# tool axis, build_drill.py frame). Shared by test_result_checks and the
# interaction probe: the expensive result-check fixture.
STEP_R, BODY_R, PILOT_R, SHANK_R, NECK_R = 6.5, 4.0, 1.7, 3.25, 2.75
CUT_Y, TAPER_Y, NECK_Y, BACK_Y, FRONT_Y, SHOULDER_Y, PILOT_END_Y = 56.0, 54.0, 53.5, 49.5, 26.0, -57.0, -62.5
TIP_Y = PILOT_END_Y - PILOT_R / math.tan(math.radians(59))
LEAD = math.pi * 2 * BODY_R / math.tan(math.radians(30.0))
FLUTE_R, FLUTE_C, FLUTE_OUT = 2.9, 3.6, 8.0
FLUTE_HEIGHT = BACK_Y - TIP_Y + 2.5
FLUTED_VOLUME = 3998.494


def _drill_call(core, state, op, measure, **arguments):
    request = {"op": op, "document_id": state["document_id"], "expected_revision": state["revision"], **arguments}
    if measure is not None:
        request["measure"] = measure
    return core.dispatch(request)


def _drill_step(core, state, op, measure, **arguments):
    response = _drill_call(core, state, op, measure, **arguments)
    if not response.get("ok"):
        raise AssertionError("Drill fixture step " + op + " failed: " + json.dumps(response, default=str)[:2000])
    return response["result"]


def build_drill(core, state=None, *, name="Drill", measure=None):
    """Revolve the drill body and its flute start plane through typed operations.

    Builds in the document of ``state`` (an inspect result), or in a new document
    when ``state`` is None. Returns ``(state, part)`` with the latest accepted
    state and the body's studio part id. ``measure`` is sent only when given.
    """
    if state is None:
        response = core.dispatch({"op": "new", "name": name})
        if not response.get("ok"):
            raise AssertionError("Drill fixture document failed: " + json.dumps(response, default=str)[:2000])
        state = response["result"]
    lip = STEP_R - BODY_R
    shoulder = BODY_R - PILOT_R
    state = _drill_step(core, state, "create_sketch", measure, id="DrillProfile", plane="XY")
    state = _drill_step(core, state, "add_polyline", measure, sketch="DrillProfile", points=[
        [STEP_R, BACK_Y - 1], [STEP_R, FRONT_Y], [BODY_R, FRONT_Y - lip], [BODY_R, SHOULDER_Y],
        [PILOT_R, SHOULDER_Y - shoulder], [PILOT_R, PILOT_END_Y], [0, TIP_Y], [0, CUT_Y], [SHANK_R, CUT_Y],
        [SHANK_R, TAPER_Y], [NECK_R, NECK_Y], [NECK_R, BACK_Y], [STEP_R - 1, BACK_Y]])
    state = _drill_step(core, state, "add_arc", measure, sketch="DrillProfile", cx=STEP_R - 1, cy=BACK_Y - 1,
                        radius=1, start_angle=0, end_angle="90 deg")
    state = _drill_step(core, state, "revolve", measure, id="DrillBody", profile="DrillProfile",
                        axis={"origin": [0, 0, 0], "direction": [0, 1, 0]}, angle="360 deg", operation="new")
    state = _drill_step(core, state, "create_plane", measure, id="FluteStart", origin=[0, BACK_Y, 0],
                        normal=[0, -1, 0], x_direction=[1, 0, 0])
    return state, state["studio"]["parts"][0]["id"]


def add_flute_inputs(core, state, n, *, segment_length=None, measure=None):
    """Flute ``n``'s helix path and section sketch; every step must succeed. Returns the new state."""
    sign = 1 if n == 1 else -1
    helix = {"segment_length": segment_length} if segment_length is not None else {}
    state = _drill_step(core, state, "create_helix", measure, id=f"Flute{n}Helix", pitch=LEAD, height=FLUTE_HEIGHT,
                        radius=FLUTE_C, axis={"origin": [0, BACK_Y, 0], "direction": [0, -1, 0]},
                        start_angle=0 if sign > 0 else "180 deg", **helix)
    state = _drill_step(core, state, "create_sketch", measure, id=f"Flute{n}Section", support={"feature": "FluteStart"})
    centre = sign * FLUTE_C
    state = _drill_step(core, state, "add_arc", measure, sketch=f"Flute{n}Section", cx=centre, cy=0, radius=FLUTE_R,
                        start_angle="90 deg" if sign > 0 else "-90 deg", end_angle="270 deg" if sign > 0 else "90 deg")
    return _drill_step(core, state, "add_polyline", measure, sketch=f"Flute{n}Section", points=[
        [centre, -FLUTE_R], [sign * FLUTE_OUT, -FLUTE_R], [sign * FLUTE_OUT, FLUTE_R], [centre, FLUTE_R]])


def sweep_flute(core, state, n, part, *, measure=None, **options):
    """The flute's Remove sweep along its helix; returns the dispatch response unchanged."""
    return _drill_call(core, state, "sweep", measure, id=f"Flute{n}", profile=f"Flute{n}Section",
                       path=f"Flute{n}Helix", frenet=True, operation="remove", merge_scope=[part], **options)


def add_flute(core, state, n, part, *, segment_length=None, measure=None, **options):
    """Add flute ``n`` (1 or 2): its helix, section sketch, then the Remove sweep.

    The helix and section steps must succeed. The sweep response is returned
    unchanged, so callers assert acceptance or the expected rejection. Returns
    ``(state, response)``: the latest accepted state (before the sweep) and the
    sweep's response; on success the caller's next state is ``response["result"]``.
    """
    state = add_flute_inputs(core, state, n, segment_length=segment_length, measure=measure)
    return state, sweep_flute(core, state, n, part, measure=measure, **options)


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
