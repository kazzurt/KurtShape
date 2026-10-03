"""Headless profile of KurtShape controller hot paths on a growing native model.

Runs against the unmodified src/kurtshape package with FreeCAD 1.1.4 (Linux AppImage).
Separates native kernel time (doc.recompute) from controller overhead.
"""
import json
import math
import os
import statistics
import sys
import tempfile
import time
import zipfile
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRATCH = Path(os.environ.get("BENCH_SCRATCH") or tempfile.mkdtemp(prefix="kurtshape-bench-"))
os.environ["KURTSHAPE_SESSION_DIR"] = str(SCRATCH / "session")
(SCRATCH / "session").mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / "src"))

import FreeCAD as App  # noqa: E402
import Part  # noqa: E402
import Sketcher  # noqa: E402
from kurtshape.core import Controller, intent_signature, measurements, native_intent  # noqa: E402
from kurtshape.extrusion_preview import ExtrusionEvaluator  # noqa: E402

N_HOLES = int(os.environ.get("BENCH_HOLES", "60"))
report = {"freecad": App.Version()[:4], "occt": Part.OCC_VERSION, "holes": N_HOLES, "growth": []}


def ms(fn, *args, repeat=1, **kwargs):
    samples = []
    value = None
    for _ in range(repeat):
        t = time.perf_counter()
        value = fn(*args, **kwargs)
        samples.append((time.perf_counter() - t) * 1000)
    return value, samples


core = Controller()
state = None


def call(**req):
    global state
    if req["op"] not in {"new", "open", "import_step"}:
        req.update(document_id=state["document_id"], expected_revision=state["revision"])
    before = {k: len(v) for k, v in core.timings.samples.items()}
    t = time.perf_counter()
    response = core.dispatch(req)
    total = (time.perf_counter() - t) * 1000
    assert response["ok"], response
    state = response["result"]
    recompute = sum(list(core.timings.samples["native_recompute"])[before.get("native_recompute", 0):])
    intent = sum(list(core.timings.samples["intent"])[before.get("intent", 0):])
    inspection = sum(list(core.timings.samples["inspection"])[before.get("inspection", 0):])
    return {"total_ms": total, "native_recompute_ms": recompute, "intent_signature_ms": intent,
            "inspection_ms": inspection, "overhead_ms": total - recompute}


call(op="new", name="Bench plate")
call(op="sketch_rectangle", id="Plate", width=600, height=600)
call(op="pad", profile="Plate", length=12)
doc = core.documents[state["document_id"]]

grid = int(math.ceil(math.sqrt(N_HOLES)))
pitch = 600 / (grid + 1)
for i in range(N_HOLES):
    x, y = pitch * (1 + i % grid), pitch * (1 + i // grid)
    a = call(op="sketch_circle", id=f"H{i}", x=x, y=y, diameter=pitch * 0.45)
    b = call(op="pocket", id=f"P{i}", profile=f"H{i}")
    if i % 10 == 9 or i == 0:
        report["growth"].append({"features": len(doc.Objects), "faces": len(doc.Body.Shape.Faces),
                                 "sketch_op": a, "pocket_op": b})
        print("holes", i + 1, json.dumps(report["growth"][-1]), flush=True)

body = doc.Body
report["final_model"] = {"objects": len(doc.Objects), "faces": len(body.Shape.Faces), "edges": len(body.Shape.Edges)}

# --- Hot path: tip edit (cheap native work) vs upstream edit (full downstream rebuild)
tip_name = f"H{N_HOLES - 1}"
tip_edits = [call(op="set_parameter", feature=tip_name, parameter="Diameter", value=pitch * (0.40 + 0.01 * (k % 3))) for k in range(5)]
report["tip_sketch_edit"] = tip_edits
up_edits = [call(op="set_parameter", feature="Pad", parameter="Length", value=12 + (k % 2)) for k in range(3)]
report["upstream_pad_edit"] = up_edits

# --- Components in isolation
report["intent_signature_ms"] = ms(intent_signature, doc, repeat=5)[1]
_, report["native_intent_ms"] = ms(native_intent, doc, repeat=3)
per_type = {}
for obj in doc.Objects:
    _, s = ms(native_intent, doc, [obj])
    per_type.setdefault(obj.TypeId, []).append(s[0])
report["native_intent_by_type_ms_total"] = {k: round(sum(v), 2) for k, v in per_type.items()}
report["inspect_warm_ms"] = ms(core.dispatch, {"op": "inspect", "document_id": state["document_id"]}, repeat=10)[1]
core.observer.invalidate(doc)
report["inspect_after_invalidate_ms"] = ms(core.dispatch, {"op": "inspect", "document_id": state["document_id"]})[1]
shape = body.Shape
report["isValid_ms"] = ms(lambda: shape.copy().isValid(), repeat=3)[1]
report["measurements_ms"] = ms(lambda: measurements(shape.copy()), repeat=3)[1]
report["mass_props_only_ms"] = ms(lambda: (shape.Volume, shape.Area, [s.CenterOfMass for s in shape.Solids]), repeat=3)[1]
# Build-status cost (runs on every sync, including the 1 Hz checkpoint timer)
report["build_status_warm_ms"] = ms(core._build_status, doc, repeat=10)[1]

# --- Recovery checkpoint as implemented (saveCopy + testzip + sha256 + copy previous)
def checkpoint():
    return core.recovery.capture(doc, core._meta(doc), None, force=True)
report["checkpoint_ms"] = ms(checkpoint, repeat=3)[1]
fcstd = SCRATCH / "bench.FCStd"
report["saveCopy_only_ms"] = ms(doc.saveCopy, str(fcstd), repeat=3)[1]
report["fcstd_bytes"] = fcstd.stat().st_size
report["testzip_ms"] = ms(lambda: zipfile.ZipFile(fcstd).testzip(), repeat=3)[1]

# --- Extrusion preview as implemented (clone FCStd per evaluation)
sk = core.dispatch({"op": "sketch_circle", "id": "PreviewProfile", "x": 300, "y": 300, "diameter": 20,
                    "document_id": state["document_id"], "expected_revision": state["revision"]})
assert sk["ok"], sk
state = sk["result"]
evaluator = ExtrusionEvaluator(core, doc, state["revision"])
cold = evaluator.evaluate({"op": "pad", "profile": "PreviewProfile", "length": "25 mm"})
assert cold.valid, cold.error
warm = [evaluator.evaluate({"op": "pad", "profile": "PreviewProfile", "length": f"{26 + k} mm"}) for k in range(3)]
report["preview_current_ms"] = {"cold_snapshot": cold.milliseconds, "warm": [w.milliseconds for w in warm]}
evaluator.close()

# --- Direct OCCT preview alternative: no document copy, no FCStd I/O
def direct_preview(length):
    profile = doc.getObject("PreviewProfile")
    face = Part.Face(Part.Wire(profile.Shape.Edges)) if len(profile.Shape.Wires) == 1 else Part.makeFace(profile.Shape.Wires, "Part::FaceMakerBullseye")
    normal = profile.getGlobalPlacement().Rotation.multVec(App.Vector(0, 0, 1))
    prism = face.extrude(normal * length)
    added = prism.cut(body.Shape)  # material the Pad would add
    return added.tessellate(0.15)
report["preview_direct_occt_ms"] = ms(direct_preview, 25, repeat=3)[1]

# --- Open as implemented (touch every feature + full recompute) vs native open
saved = SCRATCH / "bench-saved.FCStd"
doc.saveCopy(str(saved))
def native_open():
    d = App.openDocument(str(saved), True)
    App.closeDocument(d.Name)
report["native_open_ms"] = ms(native_open, repeat=2)[1]
def kurtshape_open_rebuild():
    d = App.openDocument(str(saved), True)
    for obj in d.Objects:
        if obj.TypeId.startswith(("Sketcher::", "PartDesign::")):
            obj.touch()
    t = time.perf_counter(); d.recompute(); r = (time.perf_counter() - t) * 1000
    App.closeDocument(d.Name)
    return r
report["open_full_rebuild_recompute_ms"] = ms(kurtshape_open_rebuild, repeat=2)[0]

def summarize(value):
    if isinstance(value, list) and value and all(isinstance(v, (int, float)) for v in value):
        return {"median": round(statistics.median(value), 2), "max": round(max(value), 2), "n": len(value)}
    if isinstance(value, dict):
        return {k: summarize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [summarize(v) for v in value]
    if isinstance(value, float):
        return round(value, 2)
    return value

out = summarize(report)
(SCRATCH / f"bench-{N_HOLES}.json").write_text(json.dumps(out, indent=2))
print(json.dumps(out, indent=2))
