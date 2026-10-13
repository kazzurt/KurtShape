"""Private S07B timing instrumentation; production checks remain unchanged.

Import with importlib for the GUI recipe. As a child bootstrap, retain the
production worker argv and replace only its geometry.check_shape call with a
timestamping wrapper that invokes the original exactly once.
"""
from pathlib import Path
import json
import os
import runpy
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kurtshape.geometry_check_worker import NativeGeometryCheckWorker

TIMING_ENV = "KURTSHAPE_GEOMETRY_CHECK_TIMING_PATH"


class TimingGeometryCheckWorker(NativeGeometryCheckWorker):
    evidence_directory = ROOT / "runtime" / "architecture-upgrade-working" / "s07b-child-check-timings"

    def __init__(self, executable, parent_directory, timeout=120, *, evidence_directory=None):
        super().__init__(executable, parent_directory, timeout)
        directory = Path(evidence_directory or self.evidence_directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.check_timing_path = directory / ("geometry-check-" + self.token + ".json")

    def _start(self):
        from kurtshape import geometry_check_worker as production
        original_popen = production.subprocess.Popen
        script = Path(production.__file__).resolve()

        def launch(command, **kwargs):
            command = list(command)
            if len(command) < 3 or Path(command[2]).resolve() != script:
                raise RuntimeError("Unexpected private geometry-check child command")
            command[2] = str(Path(__file__).resolve())
            kwargs["env"] = dict(kwargs["env"], **{TIMING_ENV: str(self.check_timing_path)})
            return original_popen(command, **kwargs)

        with patch.object(production.subprocess, "Popen", side_effect=launch):
            super()._start()


def read_child_timing(worker):
    path = Path(worker.check_timing_path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def make_face_rich_fixture(core, document, count=1000):
    """Real axis-aligned disjoint native solids; no delays or repeated checks."""
    import FreeCAD as App
    import Part
    if type(count) is not int or not 1 <= count <= 2048:
        raise ValueError("The private fixture requires 1..2048 boxes")
    if document.getObject("GeometryTimingSolids") is not None:
        raise ValueError("The private geometry timing fixture already exists")
    shapes = [Part.makeBox(2, 3, 4, App.Vector((index % 16) * 5, (index // 16) * 6, 0))
              for index in range(count)]
    target = document.addObject("Part::Feature", "GeometryTimingSolids")
    target.Label = "Geometry timing solids"
    target.Shape = Part.makeCompound(shapes)
    core._recompute(document)
    core.sync(document)
    if len(target.Shape.Solids) != count or len(target.Shape.Faces) != count * 6:
        raise RuntimeError("The native timing fixture has unexpected topology")
    return target


def _run_child():
    from kurtshape import geometry
    timing_path = Path(os.environ[TIMING_ENV])
    token = sys.argv[2]
    original_check = geometry.check_shape
    trace = {"task": token, "pid": os.getpid(), "clock": "time.perf_counter_ns",
             "bootstrap_start_ns": time.perf_counter_ns(), "checks": [],
             "method": "one unchanged production check per wrapper call; no artificial delay"}

    def publish():
        stage = timing_path.with_suffix(".writing")
        stage.write_text(json.dumps(trace, allow_nan=False), encoding="utf-8")
        os.replace(stage, timing_path)

    def measured_check(shape, *args, **kwargs):
        entry = {"index": len(trace["checks"]), "check_start_ns": time.perf_counter_ns()}
        trace["checks"].append(entry)
        try:
            result = original_check(shape, *args, **kwargs)
        except BaseException as exc:
            entry["check_end_ns"] = time.perf_counter_ns()
            entry["error"] = {"type": type(exc).__name__, "message": str(exc)}
            raise
        else:
            entry["check_end_ns"] = time.perf_counter_ns()
            entry["result"] = dict(result, issues=list(result["issues"]))
            return result
        finally:
            # Outside the timed native check, and before the production result
            # exists: the parent may close its worker as soon as that appears.
            publish()

    geometry.check_shape = measured_check
    try:
        runpy.run_path(str(ROOT / "src" / "kurtshape" / "geometry_check_worker.py"), run_name="__main__")
    finally:
        geometry.check_shape = original_check
        trace["bootstrap_end_ns"] = time.perf_counter_ns()
        publish()


if __name__ == "__main__":
    _run_child()
