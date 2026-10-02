"""Read original STEP files in place with FreeCAD/OCCT; never align or rewrite.

Run with the bundled FreeCAD bin/python.exe -B tools/validate_sources.py.
Optional --compare reference.step candidate.step writes a geometric difference
report. Boolean failures are indeterminate, never equality.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT.parents[1] / "Onshape examples"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def vector(v):
    return [float(v.x), float(v.y), float(v.z)]


def bounds(b):
    return {"min": [b.XMin, b.YMin, b.ZMin], "max": [b.XMax, b.YMax, b.ZMax],
            "size": [b.XLength, b.YLength, b.ZLength]}


def measurements(shape):
    solids = list(shape.Solids)
    total_volume = sum(s.Volume for s in solids)
    centroid = [sum(s.Volume * vector(s.CenterOfMass)[i] for s in solids) / total_volume
                for i in range(3)] if total_volume else None
    cylinders = []
    for index, face in enumerate(shape.Faces, 1):
        surface = face.Surface
        if type(surface).__name__ == "Cylinder":
            cylinders.append({"face_index": index, "radius_mm": float(surface.Radius),
                              "axis": vector(surface.Axis), "axis_point_mm": vector(surface.Center),
                              "face_area_mm2": face.Area})
    return {
        "is_null": shape.isNull(), "is_valid": shape.isValid(),
        "solid_count": len(shape.Solids), "shell_count": len(shape.Shells),
        "face_count": len(shape.Faces), "edge_count": len(shape.Edges),
        "bounding_box_mm": bounds(shape.BoundBox), "volume_mm3": shape.Volume,
        "area_mm2": shape.Area, "center_of_mass_mm": centroid,
        "center_of_mass_method": "Volume-weighted solid centroids",
        "solids": [{"index": i, "is_valid": s.isValid(), "volume_mm3": s.Volume,
                    "area_mm2": s.Area, "bounding_box_mm": bounds(s.BoundBox),
                    "center_of_mass_mm": vector(s.CenterOfMass)}
                   for i, s in enumerate(shape.Solids, 1)],
        "surface_types": dict(sorted(Counter(type(f.Surface).__name__ for f in shape.Faces).items())),
        "cylindrical_radius_counts_mm": dict(sorted(Counter(str(round(c["radius_mm"], 9)) for c in cylinders).items())),
        "cylindrical_faces": cylinders,
        "cylinder_caveat": "Cylindrical faces include outer surfaces and fillets; radii alone do not identify holes.",
    }


def inspect_step(path):
    import Part
    before = sha256(path)
    begin = time.perf_counter()
    shape = Part.read(str(path))
    result = measurements(shape)
    result.update({"path": str(path), "sha256": before,
                   "original_unchanged": before == sha256(path),
                   "read_measure_seconds": time.perf_counter() - begin,
                   "frame": "Original STEP placement, interpreted by OCCT; no alignment or extra transform",
                   "measurement_units": {"length": "mm", "area": "mm^2", "volume": "mm^3"},
                   "native_feature_conversion": False,
                   "baseline_native_shape_agreement": "not evaluated: no converted native example yet"})
    return result


def compare_shapes(reference, candidate, volume_tolerance_mm3=1e-5):
    """Compare native coordinates. Tolerance is explicit; no automatic alignment."""
    result = {"status": "indeterminate", "volume_tolerance_mm3": volume_tolerance_mm3,
              "alignment": "none", "method": "OCCT bidirectional solid difference"}
    if not reference.isValid() or not candidate.isValid() or not reference.Solids or not candidate.Solids:
        result["reason"] = "Both inputs must contain valid solids"
        return result
    try:
        missing = reference.cut(candidate)
        extra = candidate.cut(reference)
        if (not missing.isNull() and not missing.isValid()) or (not extra.isNull() and not extra.isValid()):
            result["reason"] = "Difference result invalid"
            return result
        residual = missing.Volume + extra.Volume
        result.update({"status": "measured", "missing_volume_mm3": missing.Volume,
                       "extra_volume_mm3": extra.Volume, "symmetric_difference_mm3": residual,
                       "within_volume_tolerance": residual <= volume_tolerance_mm3,
                       "same_solid_count": len(reference.Solids) == len(candidate.Solids),
                       "caveat": "Residual volume complements critical dimensions; it does not prove all surface tolerances or edit equivalence."})
    except Exception as exc:
        result["reason"] = str(exc)
    return result


def main():
    import FreeCAD
    import Part
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compare", nargs=2, metavar=("REFERENCE", "CANDIDATE"))
    parser.add_argument("--volume-tolerance", type=float, default=1e-5)
    args = parser.parse_args()
    if args.volume_tolerance < 0:
        parser.error("volume tolerance must be non-negative")
    output = {"FreeCAD_version": FreeCAD.Version(), "OCCT_version": Part.OCC_VERSION,
              "coordinate_policy": "No alignment, no rewriting source files",
              "sources": [inspect_step(p) for p in sorted(SOURCES.glob("*.step"))]}
    if args.compare:
        reference, candidate = [Path(p).resolve() for p in args.compare]
        output["comparison"] = {"reference": str(reference), "candidate": str(candidate),
                                **compare_shapes(Part.read(str(reference)), Part.read(str(candidate)), args.volume_tolerance)}
    out = ROOT / "validation" / "source-geometry.json"
    out.write_text(json.dumps(output, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(out), "sources": [{"name": Path(s["path"]).name,
          "solid_count": s["solid_count"], "valid": s["is_valid"], "size_mm": s["bounding_box_mm"]["size"],
          "volume_mm3": s["volume_mm3"], "original_unchanged": s["original_unchanged"]} for s in output["sources"]]}, indent=2))


if __name__ == "__main__":
    main()
