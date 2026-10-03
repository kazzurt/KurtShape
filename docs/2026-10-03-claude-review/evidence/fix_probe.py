"""Estimate the effect of taking BRepCheck/mass properties out of the per-operation path."""
import json
import math
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

SCRATCH = Path(os.environ.get("BENCH_SCRATCH") or tempfile.mkdtemp(prefix="kurtshape-bench-"))
os.environ["KURTSHAPE_SESSION_DIR"] = str(SCRATCH / "session")
(SCRATCH / "session").mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
import FreeCAD as App  # noqa: E402
import Part  # noqa: E402
import kurtshape.core as kcore  # noqa: E402

original_measurements = kcore.measurements


def lazy_measurements(shape):
    # Interactive path: no BRepCheck, no mass integration; bounding box is cheap.
    box = shape.BoundBox
    return {"valid": not shape.isNull(), "solid_count": len(shape.Solids), "volume_mm3": None, "area_mm2": None,
            "bbox_mm": {"min": [box.XMin, box.YMin, box.ZMin], "max": [box.XMax, box.YMax, box.ZMax],
                        "size": [box.XLength, box.YLength, box.ZLength]}, "center_of_mass_mm": None}


kcore.measurements = lazy_measurements
N = int(os.environ.get("BENCH_HOLES", "60"))
core = kcore.Controller()
state = None


def call(**req):
    global state
    if req["op"] != "new":
        req.update(document_id=state["document_id"], expected_revision=state["revision"])
    before = len(core.timings.samples["native_recompute"])
    t = time.perf_counter()
    r = core.dispatch(req)
    total = (time.perf_counter() - t) * 1000
    assert r["ok"], r
    state = r["result"]
    return total, sum(list(core.timings.samples["native_recompute"])[before:])


build = []
call(op="new", name="probe")
call(op="sketch_rectangle", id="Plate", width=600, height=600)
call(op="pad", profile="Plate", length=12)
grid = int(math.ceil(math.sqrt(N)))
pitch = 600 / (grid + 1)
for i in range(N):
    a = call(op="sketch_circle", id=f"H{i}", x=pitch * (1 + i % grid), y=pitch * (1 + i // grid), diameter=pitch * 0.45)
    b = call(op="pocket", id=f"P{i}", profile=f"H{i}")
    build.append((a, b))
doc = core.documents[state["document_id"]]
out = {"holes": N, "objects": len(doc.Objects),
       "lazy_last_sketch_op": {"total_ms": round(build[-1][0][0]), "native_ms": round(build[-1][0][1])},
       "lazy_last_pocket_op": {"total_ms": round(build[-1][1][0]), "native_ms": round(build[-1][1][1])}}
lazy = [call(op="set_parameter", feature=f"H{N-1}", parameter="Diameter", value=pitch * (0.40 + 0.01 * (k % 3))) for k in range(5)]
out["lazy_tip_edit"] = {"total_median_ms": round(statistics.median(t for t, _ in lazy)), "native_median_ms": round(statistics.median(n for _, n in lazy))}
kcore.measurements = original_measurements
core.evaluations.clear()
current = [call(op="set_parameter", feature=f"H{N-1}", parameter="Diameter", value=pitch * (0.43 + 0.01 * (k % 3))) for k in range(3)]
out["current_tip_edit"] = {"total_median_ms": round(statistics.median(t for t, _ in current)), "native_median_ms": round(statistics.median(n for _, n in current))}

# Preview geometry without document cloning
profile = doc.getObject(f"H{N-1}")
face = Part.Face(Part.Wire(profile.Shape.Edges))
normal = profile.getGlobalPlacement().Rotation.multVec(App.Vector(0, 0, 1))
samples = []
for k in range(5):
    t = time.perf_counter()
    prism = face.extrude(normal * (20 + k))
    prism.tessellate(0.15)
    samples.append((time.perf_counter() - t) * 1000)
out["prism_only_preview_ms"] = round(statistics.median(samples), 2)
(SCRATCH / "fix-probe.json").write_text(json.dumps(out, indent=2))
print("FIXPROBE", json.dumps(out))
