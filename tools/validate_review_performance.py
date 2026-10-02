"""Reproducible native timing fixtures; STEP references are not conversions."""
import json
import os
from pathlib import Path
import platform
import sys
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
import Sketcher
from kurtshape.core import Controller
from kurtshape.timing import Timings

output = ROOT / "validation" / "review-followup"
output.mkdir(parents=True, exist_ok=True)
report = {"engine": {"FreeCAD": App.Version(), "OCCT": Part.OCC_VERSION},
          "hardware": {"processor": os.environ.get("PROCESSOR_IDENTIFIER"), "logical_processors": os.cpu_count(), "platform": platform.platform()},
          "limits": "Headless inspection and native recompute; viewport and hand comfort require the GUI and user. STEP cases are preserved reference geometry, not editable conversions.", "cases": []}

def measure_case(label, doc, core, mutable=False):
    core.inspect(doc)
    timing = Timings()
    for _ in range(100):
        timing.measure("warm_inspection", core.inspect, doc)
    for index in range(20):
        doc.Label = label + str(index)
        timing.measure("changed_intent_inspection", core.inspect, doc)
    if mutable:
        for index in range(20):
            state = core.inspect(doc)
            response = timing.measure("parameter_commit", core.dispatch, {"op": "set_parameter", "document_id": state["document_id"],
                "expected_revision": state["revision"], "feature": "Pad", "parameter": "Length", "value": 6 + index / 10})
            assert response["ok"], response
    report["cases"].append({"label": label, "objects": len(doc.Objects), "measurements": core.inspect(doc)["measurements"],
                           "timings": timing.report(), "controller_stages": core.timings.report()})

for count in (1, 200):
    core = Controller()
    doc = App.newDocument("PerformanceHistory")
    body = doc.addObject("PartDesign::Body", "Body")
    doc.openTransaction("Synthetic performance fixture")
    for index in range(count):
        sketch = body.newObject("Sketcher::SketchObject", "Circle" + str(index))
        sketch.addGeometry(Part.Circle(App.Vector(), App.Vector(0, 0, 1), 10))
        sketch.addConstraint(Sketcher.Constraint("Diameter", 0, 20))
        sketch.renameConstraint(0, "Diameter")
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = sketch
    pad.Length = 6
    doc.recompute()
    doc.commitTransaction()
    core.attach(doc)
    measure_case("synthetic-" + str(count) + "-sketch-history", doc, core, True)
    core.close()
    App.closeDocument(doc.Name)

for filename in ("Dodec pipe mount.step", "Dodec Hub Conformal.step"):
    source = ROOT.parent.parent / "Onshape examples" / filename
    core = Controller()
    doc = App.newDocument("StepReferenceTiming")
    obj = doc.addObject("Part::Feature", "ReferenceGeometry")
    began = time.perf_counter()
    obj.Shape = Part.read(str(source))
    import_ms = (time.perf_counter() - began) * 1000
    doc.recompute()
    core.attach(doc)
    measure_case("STEP reference: " + filename, doc, core)
    report["cases"][-1].update(source=str(source), import_ms=import_ms)
    core.close()
    App.closeDocument(doc.Name)

(output / "performance.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps({"cases": [{"label": case["label"], "timings": case["timings"]} for case in report["cases"]]}, indent=2))
