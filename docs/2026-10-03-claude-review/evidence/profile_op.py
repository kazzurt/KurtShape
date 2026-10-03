import cProfile
import io
import math
import os
import pstats
import sys
import tempfile
import time
from pathlib import Path

SCRATCH = Path(os.environ.get("BENCH_SCRATCH") or tempfile.mkdtemp(prefix="kurtshape-bench-"))
os.environ["KURTSHAPE_SESSION_DIR"] = str(SCRATCH / "session")
(SCRATCH / "session").mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
import FreeCAD as App  # noqa: E402
from kurtshape.core import Controller  # noqa: E402

N = int(os.environ.get("BENCH_HOLES", "30"))
core = Controller()
state = None


def call(**req):
    global state
    if req["op"] != "new":
        req.update(document_id=state["document_id"], expected_revision=state["revision"])
    r = core.dispatch(req)
    assert r["ok"], r
    state = r["result"]


call(op="new", name="p")
call(op="sketch_rectangle", id="Plate", width=600, height=600)
call(op="pad", profile="Plate", length=12)
grid = int(math.ceil(math.sqrt(N)))
pitch = 600 / (grid + 1)
for i in range(N):
    call(op="sketch_circle", id=f"H{i}", x=pitch * (1 + i % grid), y=pitch * (1 + i // grid), diameter=pitch * 0.45)
    call(op="pocket", id=f"P{i}", profile=f"H{i}")
doc = core.documents[state["document_id"]]

# Which objects does a plain recompute touch after a sketch is added?
touched_log = []
orig = doc.recompute
def counting_recompute(*a):
    touched = [o.Name for o in doc.Objects if "Touched" in o.State]
    touched_log.append(touched)
    return orig(*a)
core._recompute = lambda d: core.timings.measure("native_recompute", d.recompute) if d is not doc else counting_recompute()

pr = cProfile.Profile()
t = time.perf_counter()
pr.enable()
call(op="sketch_circle", id="Extra", x=1, y=1, diameter=0.5)
pr.disable()
print("SKETCH_OP_MS", round((time.perf_counter() - t) * 1000))
print("TOUCHED_BEFORE_EACH_RECOMPUTE", [len(x) for x in touched_log], touched_log[0][:6] if touched_log else None)
s = io.StringIO()
pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(28)
print(s.getvalue())
s = io.StringIO()
pstats.Stats(pr, stream=s).sort_stats("tottime").print_stats(15)
print(s.getvalue())
body = doc.Body
t = time.perf_counter(); body.Shape.copy().isValid(); print("ISVALID_MS", round((time.perf_counter() - t) * 1000))
print("BODY_SHAPE", len(body.Shape.Faces), "faces", len(body.Shape.Solids), "solids")
for name in ("Pad", "P0", f"P{N-1}"):
    o = doc.getObject(name)
    print("FEATURE_SHAPE", name, len(o.Shape.Faces), "faces", "AddSubShape" in o.PropertiesList and len(o.AddSubShape.Faces))
