"""Measure explicit query rebuild cost on 30 native features and four parts."""
from pathlib import Path
import json
import statistics
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
from kurtshape import selectors


destination = ROOT / "validation" / "u2-selector-performance"
destination.mkdir(parents=True, exist_ok=True)
doc = App.newDocument("SelectorPerformance30Features")
doc.UseHasher = False
try:
    for part, holes in enumerate((3, 3, 3, 2)):
        body = doc.addObject("PartDesign::Body", "Part" + str(part + 1))
        profile = body.newObject("Sketcher::SketchObject", "Profile" + str(part + 1))
        x = part * 40
        points = [App.Vector(x, 0, 0), App.Vector(x + 20, 0, 0),
                  App.Vector(x + 20, 20, 0), App.Vector(x, 20, 0)]
        for index, point in enumerate(points):
            profile.addGeometry(Part.LineSegment(point, points[(index + 1) % 4]), False)
        pad = body.newObject("PartDesign::Pad", "Pad" + str(part + 1))
        pad.Profile, pad.Length = profile, 5
        doc.recompute()
        for hole in range(holes):
            sketch = body.newObject("Sketcher::SketchObject", "HoleProfile")
            sketch.MapMode = "FlatFace"
            doc.openTransaction("Bind native support selector")
            selectors.bind(sketch, "support", {"kind": "created_by", "feature": pad.Name, "cap": "end"})
            doc.recompute()
            center = sketch.Placement.inverse().multVec(App.Vector(x + 5 + hole * 5, 10, 5))
            sketch.addGeometry(Part.Circle(center, App.Vector(0, 0, 1), 1), False)
            pocket = body.newObject("PartDesign::Pocket", "Pocket")
            pocket.Profile, pocket.Type = sketch, 1
            selectors.recompute(doc)
            doc.commitTransaction()
    features = [obj for obj in doc.Objects if obj.TypeId == "Sketcher::SketchObject" or
                obj.TypeId.startswith("PartDesign::") and obj.TypeId != "PartDesign::Body"]
    bodies = [obj for obj in doc.Objects if obj.TypeId == "PartDesign::Body"]
    assert len(features) == 30 and len(bodies) == 4
    assert all(body.Shape.isValid() and len(body.Shape.Solids) == 1 for body in bodies)
    assert not selectors.reference_errors(doc)
    samples = []
    for run in range(5):
        doc.openTransaction("Measure explicit native rebuild")
        for feature in features:
            feature.touch()
        samples.append(selectors.recompute(doc))
        doc.commitTransaction()
    doc.saveAs(str(destination / "four-parts-thirty-features.FCStd"))
    report = {"recipe": "tools/measure_selector_rebuild.py", "engine": {"freecad": App.Version(), "occt": Part.OCC_VERSION},
              "feature_count": len(features), "part_count": len(bodies), "selector_consumers": 11,
              "measurement": "Five forced explicit native rebuilds; selector evaluation includes query contexts, native reference/cache writes and health writes; excludes native geometry recomputation.",
              "samples": samples,
              "median_ms": {key: statistics.median(sample[key] for sample in samples)
                            for key in ("selector_evaluation_ms", "query_resolution_ms", "native_recompute_ms", "selector_rebuild_ms")},
              "reference_errors": selectors.reference_errors(doc)}
    (destination / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(destination / "report.json"), "median_ms": report["median_ms"]}))
finally:
    App.closeDocument(doc.Name)
