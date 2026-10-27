"""Reproduce the completed Dodec fixture's nominal access cases through typed reads.

Requires the verified fixture copy (occurrences Hub, Cartridge, etc.). No file is
saved or repaired. Run in bundled pythonw.exe with output redirected.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kurtshape.session import Session


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    source = args.source.resolve()
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    began = time.perf_counter()
    report = {"source": str(source), "source_sha256": before, "cases": {}}
    with Session.headless(ROOT / "runtime" / "clearance" / uuid.uuid4().hex[:8]) as session:
        import FreeCAD as App
        import Part
        from kurtshape import assembly
        session.call("list_documents", detail="compact")
        state = session.call("open", path=str(source), measure=False)
        if state["build_status"] != "valid":
            raise RuntimeError("Fixture must pass native build integrity before checking clearance")
        report["build"] = session.capabilities["build"]
        doc = session.controller.documents[state["document_id"]]
        objects = assembly.result_objects(doc)
        fixture = [obj.Name for obj in objects if obj.Name != "Hub"]
        hub = assembly.global_shape(doc.getObject("Hub"))
        axes = []
        for face in hub.Faces:
            surface = face.Surface
            if isinstance(surface, Part.Cylinder) and abs(surface.Radius - 17.425) < 1e-5:
                axis = surface.Axis
                if axis.z < 0:
                    axis = -axis
                if not any(abs(axis.dot(other)) > 0.99999 for other in axes):
                    axes.append(axis)
        if len(axes) != 3:
            raise RuntimeError("Expected the completed fixture's three snout OD axes")
        rings = []
        for index, axis in enumerate(axes):
            origin = App.Vector(0, 0, 138) + axis * 22.36
            rings.extend([
                {"id": "od-tool-" + str(index), "kind": "annulus", "origin_mm": list(origin), "axis": list(axis),
                 "inner_radius_mm": 17.425, "outer_radius_mm": 27.425, "length_mm": 40},
                {"id": "od-holder-" + str(index), "kind": "annulus", "origin_mm": list(origin + axis * 40), "axis": list(axis),
                 "inner_radius_mm": 9.925, "outer_radius_mm": 34.925, "length_mm": 60}])
        report["cases"]["continuous_od"] = session.call("check_clearance", envelopes=rings, components=fixture)
        wrenches, keys = [], []
        for bolt in range(4):
            angle = math.pi / 4 + bolt * math.pi / 2
            center = App.Vector(28 * math.cos(angle), 28 * math.sin(angle), 0)
            for swing in (-15, 0, 15):
                rotation = App.Rotation(App.Vector(0, 0, 1), math.degrees(angle) + swing)
                corner = center + rotation.multVec(App.Vector(-6.5, -13, 114.5))
                wrenches.append({"id": f"spanner-{bolt}-{swing}", "kind": "box", "origin_mm": list(corner),
                                 "size_mm": [66.5, 26, 4], "rotation_xyzw": list(rotation.Q)})
            keys.append({"id": "straight-key-" + str(bolt), "kind": "cylinder",
                         "origin_mm": list(center + App.Vector(0, 0, 118.9)), "axis": [0, 0, 1],
                         "radius_mm": 3, "length_mm": 80})
        report["cases"]["side_spanner_samples"] = session.call("check_clearance", envelopes=wrenches, components=["Hub", "Cartridge"])
        report["cases"]["straight_key_loaded_hub"] = session.call("check_clearance", envelopes=keys, components=["Hub"])
        report["cases"]["through_dowel_tip"] = session.call("check_clearance", components=["Cartridge"], minimum_clearance_mm=1,
            axis_probe={"tip_mm": [30, 0, 108], "axis": [0, 0, 1], "radius_mm": 3, "max_distance_mm": 4})
        # Recorded rejected radial-normal root approach, retained unchanged.
        origin = App.Vector(27.804757742088654, -8.71249999999995, 132.46660902757068)
        axis = App.Vector(0.30901699437494856, -0.49999999999999956, -0.8090169943749473)
        radial = [{"id": "radial-tool", "kind": "cylinder", "origin_mm": list(origin), "axis": list(axis),
                   "radius_mm": 3, "length_mm": 40},
                  {"id": "radial-holder", "kind": "cylinder", "origin_mm": list(origin + axis * 40), "axis": list(axis),
                   "radius_mm": 12.5, "length_mm": 60}]
        report["cases"]["rejected_radial_root"] = session.call("check_clearance", envelopes=radial, components=fixture)
    report["inputs_unchanged"] = hashlib.sha256(source.read_bytes()).hexdigest() == before
    cases = report["cases"]
    report["regression_passed"] = (report["inputs_unchanged"] and cases["continuous_od"]["passed"]
        and cases["side_spanner_samples"]["passed"] and cases["through_dowel_tip"]["passed"]
        and not cases["straight_key_loaded_hub"]["passed"] and not cases["rejected_radial_root"]["passed"])
    report["seconds"] = time.perf_counter() - began
    args.report.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"regression_passed": report["regression_passed"], "seconds": report["seconds"],
                      "continuous_minima": cases["continuous_od"]["limiting"]}))
    return 0 if report["regression_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
