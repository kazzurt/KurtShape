"""Explicit file delivery validation, always on private copies in an isolated session.

Importing this module does not initialize FreeCAD. Surface comparison is sampled,
opt-in, and deliberately reported separately from native integrity and validity.
"""
import hashlib
import json
import math
from pathlib import Path
import shutil
import time
import uuid


def sha256(path):
    with Path(path).open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256")
    return digest.hexdigest()


def compare_shapes(native, exchange, *, surface=False, tolerance_mm=0.02, max_samples=2000):
    """Compare solid count, volume, exact bounds and optionally sampled surfaces.

    No coincident-face Boolean is used. Samples are projected triangle centres
    in both directions; this is not an exact Hausdorff bound or equivalence proof.
    """
    import Part
    from . import geometry
    if not math.isfinite(tolerance_mm) or tolerance_mm <= 0:
        raise ValueError("tolerance_mm must be positive and finite")
    if isinstance(max_samples, bool) or not isinstance(max_samples, int) or max_samples < 8:
        raise ValueError("max_samples must be an integer of at least 8")
    metrics = []
    for shape in (native, exchange):
        metrics.append({"solid_count": len(shape.Solids), "volume_mm3": shape.Volume,
                        "bbox_mm": geometry.tight_bounding_box(shape), "valid": bool(shape.Solids and shape.isValid())})
    first, second = metrics
    bound_delta = max(abs(first["bbox_mm"][key][axis] - second["bbox_mm"][key][axis])
                      for key in ("min", "max") for axis in range(3))
    volume_delta = abs(first["volume_mm3"] - second["volume_mm3"])
    volume_tolerance = max(1e-5, abs(first["volume_mm3"]) * 1e-7)
    passed = (all(item["valid"] for item in metrics) and first["solid_count"] == second["solid_count"]
              and bound_delta <= tolerance_mm and volume_delta <= volume_tolerance)
    report = {"passed": passed, "method": "solid count, validity, volume and exact bounds",
              "native": first, "exchange": second, "bbox_delta_mm": bound_delta,
              "volume_delta_mm3": volume_delta, "volume_tolerance_mm3": volume_tolerance,
              "tolerance_mm": tolerance_mm, "surface": {"performed": False}}
    if surface:
        directions = []
        for source, target in ((native, exchange), (exchange, native)):
            # Vertices alone miss displaced holes when every vertex also lies
            # on an unchanged end face. Sample face interiors, projecting each
            # triangle centre back onto its exact source face. Measure against
            # target faces: distance to a solid can be zero for interior points.
            samples = []
            for face in source.copy(True, False).Faces:
                vertices, triangles = face.tessellate(tolerance_mm)
                samples.extend((face, (vertices[a] + vertices[b] + vertices[c]) / 3)
                               for a, b, c in triangles)
            if not samples:
                raise ValueError("The comparison shape produced no surface samples")
            stride = max(1, math.ceil(len(samples) / max_samples))
            points = samples[::stride]
            target_surface = Part.makeCompound(target.Faces)
            maximum = 0.0
            for face, point in points:
                projected = face.distToShape(Part.Vertex(point))[1][0][0]
                maximum = max(maximum, Part.Vertex(projected).distToShape(target_surface)[0])
            directions.append({"sample_count": len(points), "available_triangles": len(samples),
                               "stride": stride, "maximum_sample_distance_mm": maximum})
        surface_passed = all(row["maximum_sample_distance_mm"] <= tolerance_mm for row in directions)
        report["surface"] = {"performed": True, "passed": surface_passed, "directions": directions,
                             "method": "two-way exact-face-projected triangle centres, capped deterministically",
                             "limitation": "Unsampled surface deviations may remain; not an exact equivalence proof."}
        report["passed"] = passed and surface_passed
    return report


def embedded_references(doc):
    """Embedded seals are mandatory; backing-file freshness is separate and portable."""
    from . import assembly
    rows = []
    for source in doc.Objects:
        if not assembly.is_embedded_source(source):
            continue
        path = Path(source.SourcePath)
        actual = sha256(path) if path.is_file() else None
        rows.append({"embedded": source.Name, "source_path": str(path), "source_object": source.SourceObject,
                     "saved_source_sha256": source.SourceSHA256, "current_source_sha256": actual,
                     "source_file_state": "missing" if actual is None else "current" if actual == source.SourceSHA256 else "different",
                     "instances": [obj.Name for obj in assembly.result_objects(doc) if obj.LinkedObject == source]})
    errors = assembly.validation_errors(doc)  # bypass generation cache: recompute the seals now
    return {"valid": not errors, "errors": errors, "sources": rows}


def validate_delivery(source, working, *, exports=(), surface=False, tolerance_mm=0.02,
                      max_samples=2000, require_current_sources=False, session_root=None):
    """Copy, reopen, check, save/close/reopen, compare exports; never write inputs.

    A unique descriptive working folder is required. The standalone CLI creates
    its own short runtime profile, never discovers or targets a running app.
    """
    source, working = Path(source).resolve(), Path(working).resolve()
    if not source.is_file() or source.suffix.lower() != ".fcstd":
        raise ValueError("source must be an existing native FCStd")
    if working.exists() and any(working.iterdir()):
        raise ValueError("working must be new or empty; existing delivery evidence is preserved")
    if source == working or source.is_relative_to(working):
        raise ValueError("working must not contain the original")
    paths = [source] + [Path(path).resolve() for path in exports]
    for path in paths[1:]:
        if not path.is_file() or path.suffix.lower() not in {".step", ".stp"}:
            raise ValueError("export comparisons currently accept existing STEP/STP files")
    before = {str(path): sha256(path) for path in paths}
    working.mkdir(parents=True, exist_ok=True)
    copies = working / "native-reopen"
    copies.mkdir()
    copied = copies / source.name
    shutil.copy2(source, copied)
    root = Path(session_root) if session_root else Path(__file__).resolve().parents[2] / "runtime" / "delivery" / uuid.uuid4().hex[:10]
    from .session import Session
    started = time.perf_counter()
    report = {"passed": False, "source": str(source), "copy": str(copied), "input_sha256": before,
              "reopens": [], "exports": [], "surface_opt_in": surface,
              "limits": "Headless file validation only. GUI reopen needs the separate hidden-session regression. Export surface checks are sampled, not exact equivalence."}
    try:
        with Session.headless(root, project_roots=[str(working)]) as session:
            import Part
            from .bodies import results
            from .clearance import world_shape
            report["build"] = session.capabilities["build"]
            session.call("list_documents", detail="compact")
            for stage, path in (("copied_original", copied), ("saved_roundtrip", copies / "delivery-roundtrip.FCStd")):
                state = session.call("open", path=str(path), measure=False)
                check = session.call("check_geometry", measure=False)
                doc = session.controller.documents[state["document_id"]]
                references = embedded_references(doc)
                fresh = all(row["source_file_state"] == "current" for row in references["sources"])
                valid = (check.get("build_status") == "valid"
                         and check.get("geometry_check_report", {}).get("status") == "valid"
                         and references["valid"] and (fresh or not require_current_sources))
                report["reopens"].append({"stage": stage, "passed": valid, "build_status": check.get("build_status"),
                                          "build_errors": check.get("build_errors", []),
                                          "geometry_check_report": check.get("geometry_check_report"),
                                          "embedded_references": references})
                if not valid:
                    break  # never bless a failed build merely because its solids are valid
                if stage == "copied_original":
                    session.call("save", path=str(copies / "delivery-roundtrip.FCStd"), measure=False)
                    session.call("close_document")
                else:
                    native = Part.makeCompound([world_shape(obj) for obj in results(doc)
                                                if hasattr(obj, "Shape") and not obj.Shape.isNull() and obj.Shape.Solids])
                    for export in paths[1:]:
                        shape = Part.read(str(export))
                        report["exports"].append({"path": str(export), "sha256": before[str(export)],
                                                  **compare_shapes(native, shape, surface=surface,
                                                                   tolerance_mm=tolerance_mm, max_samples=max_samples)})
            report["passed"] = (len(report["reopens"]) == 2 and all(row["passed"] for row in report["reopens"])
                                and all(row["passed"] for row in report["exports"]))
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        report["inputs_unchanged"] = all(path.is_file() and sha256(path) == before[str(path)] for path in paths)
        report["passed"] = report["passed"] and report["inputs_unchanged"]
        report["seconds"] = time.perf_counter() - started
        (working / "delivery-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
