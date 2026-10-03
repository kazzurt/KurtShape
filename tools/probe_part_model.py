"""Bounded U2 carrier proof in pinned bundled Python, without a GUI or custom proxy.

Run: runtime/.../bin/python.exe -B tools/probe_part_model.py
Reports and native working fixtures: validation/u2-part-model-spike/
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime/freecad-1.1.4/FreeCAD_1.1.4-Windows-x86_64-py311"
sys.path.insert(0, str(RUNTIME / "Mod/Part"))
import FreeCAD as App
import Part
import Sketcher

OUT = ROOT / "validation/u2-part-model-spike"
WORK = OUT / "native-carrier-fixtures-working"
WORK.mkdir(parents=True, exist_ok=True)


def summary(obj):
    shape = obj.Shape
    return {"id": obj.Name, "type": obj.TypeId, "status": obj.getStatusString(),
            "solids": len(shape.Solids), "volume": shape.Volume,
            "valid": not shape.isNull() and shape.isValid(),
            "element_map_size": shape.ElementMapSize}


def check(value, message):
    if not value:
        raise AssertionError(message)


def rectangle(doc, body, name, x, y, width=8, height=8):
    sk = doc.addObject("Sketcher::SketchObject", name)
    if body:
        body.addObject(sk)
    pts = [(x, y), (x + width, y), (x + width, y + height), (x, y + height)]
    for i, p in enumerate(pts):
        q = pts[(i + 1) % 4]
        idx = sk.addGeometry(Part.LineSegment(App.Vector(*p, 0), App.Vector(*q, 0)), False)
        sk.addConstraint(Sketcher.Constraint("Block", idx))
    return sk


def make_fixture(carrier):
    """Four creations plus 26 spatially distinct through cuts, exactly 30 operations."""
    doc = App.newDocument("U2_" + carrier)
    doc.UndoMode = 1
    meta = doc.addObject("App::DocumentObjectGroup", "Studio")
    meta.addProperty("App::PropertyLinkList", "FeatureOrder")
    meta.addProperty("App::PropertyInteger", "RollbackIndex")
    roots, order, features = [], [], []
    start = time.perf_counter()
    for i in range(4):
        body = doc.addObject("PartDesign::Body", "Part" + str(i)) if carrier == "bodies" else None
        sk = rectangle(doc, body, "Profile" + str(i), i * 12, 0)
        if body:
            feat = body.newObject("PartDesign::Pad", "Create" + str(i))
            feat.Profile = sk
            feat.Length = 6
            roots.append(body)
        else:
            feat = doc.addObject("Part::Extrusion", "Create" + str(i))
            feat.Base = sk
            feat.Dir = App.Vector(0, 0, 1)
            feat.LengthFwd = 6
            feat.Solid = True
            roots.append(feat)
        doc.recompute()
        features.append(feat)
        order.append(feat)
    if carrier == "compound":
        result = doc.addObject("Part::Compound", "InitialParts")
        result.Links = roots
        doc.recompute()
    for index in range(26):
        part_index = index % 4
        pos = index // 4
        cx = part_index * 12 + 1 + (pos % 4) * 1.6
        cy = 1 + (pos // 4) * 3
        if carrier == "bodies":
            body = roots[part_index]
            sk = doc.addObject("Sketcher::SketchObject", "Hole" + str(index))
            body.addObject(sk)
            geo = sk.addGeometry(Part.Circle(App.Vector(cx, cy, 0), App.Vector(0, 0, 1), .3), False)
            sk.addConstraint(Sketcher.Constraint("Block", geo))
            feat = body.newObject("PartDesign::Pocket", "Cut" + str(index))
            feat.Profile = sk
            feat.Type = 1
            feat.Reversed = True
        else:
            tool = doc.addObject("Part::Cylinder", "Hole" + str(index))
            tool.Radius = .3
            tool.Height = 8
            tool.Placement.Base = App.Vector(cx, cy, -1)
            feat = doc.addObject("Part::Cut", "Cut" + str(index))
            feat.Base = result
            feat.Tool = tool
            result = feat
        doc.recompute()
        features.append(feat)
        order.append(feat)
    meta.FeatureOrder = order
    meta.RollbackIndex = len(order)
    doc.recompute()
    creation = time.perf_counter() - start
    results = roots if carrier == "bodies" else [result]
    baseline = sum(obj.Shape.Volume for obj in results)
    check(sum(len(obj.Shape.Solids) for obj in results) == 4, "fixture must contain four parts")
    samples = []
    for _ in range(3):
        for obj in features:
            obj.touch()
        start = time.perf_counter()
        doc.recompute()
        samples.append(time.perf_counter() - start)
    first = features[0]
    param = "Length" if carrier == "bodies" else "LengthFwd"
    doc.openTransaction("Change first part depth")
    setattr(first, param, 7)
    doc.recompute()
    doc.commitTransaction()
    changed = sum(obj.Shape.Volume for obj in results)
    doc.undo()
    doc.recompute()
    check(abs(sum(obj.Shape.Volume for obj in results) - baseline) < 1e-5, "undo geometry")
    doc.redo()
    doc.recompute()
    check(abs(sum(obj.Shape.Volume for obj in results) - changed) < 1e-5, "redo geometry")
    path = WORK / (carrier + ".FCStd")
    doc.saveAs(str(path))
    Part.export(results, str(WORK / (carrier + ".step")))
    case = {"creation_seconds": creation, "rebuild_seconds": samples,
            "operations": 30, "parts": 4, "native_objects": len(doc.Objects),
            "baseline_volume": baseline, "edited_volume": changed,
            "undo_redo": True, "results": [summary(obj) for obj in results],
            "order_persisted_on_native_metadata": [obj.Name for obj in meta.FeatureOrder],
            "result_ids": [obj.Name for obj in results], "path": str(path)}
    App.closeDocument(doc.Name)
    return case


def compositions():
    from BOPTools import SplitFeatures
    doc = App.newDocument("NativeCompositions")
    doc.UndoMode = 1
    source = doc.addObject("Part::Box", "Source")
    source.Length, source.Width, source.Height = 20, 10, 10
    plane = doc.addObject("Part::Plane", "SplitPlane")
    plane.Length, plane.Width = 40, 40
    plane.Placement = App.Placement(App.Vector(10, -10, 30), App.Rotation(App.Vector(0, 1, 0), 90))
    doc.recompute()
    split = SplitFeatures.makeSlice("Slice")
    split.Base, split.Tools, split.Mode = source, [plane], "Split"
    doc.recompute()
    check(len(split.Shape.Solids) == 2, "installed Slice splits into two solids")
    halves = []
    for i in range(2):
        binder = doc.addObject("PartDesign::SubShapeBinder", "HalfBinder" + str(i))
        binder.Support = [(split, ["Solid" + str(i + 1)])]
        binder.Relative = False
        doc.recompute()
        body = doc.addObject("PartDesign::Body", "Half" + str(i))
        body.BaseFeature = binder
        doc.recompute()
        tip = body.Tip
        fillet = body.newObject("PartDesign::Fillet", "Fillet" + str(i))
        fillet.Base, fillet.Radius = (tip, ["Edge1"]), .5
        doc.recompute()
        check(fillet.Shape.isValid(), "split output must accept native fillet")
        halves.append(body)
    # A script-free planar split uses paired native booleans. Expressions bound
    # the finite cutter from current source bounds, rather than freezing geometry.
    cutter = doc.addObject("Part::Box", "PositiveHalfspace")
    cutter.Placement.Base = App.Vector(10, -1, -1)
    cutter.setExpression("Length", "Source.Shape.BoundBox.XLength + 2")
    cutter.setExpression("Width", "Source.Shape.BoundBox.YLength + 2")
    cutter.setExpression("Height", "Source.Shape.BoundBox.ZLength + 2")
    positive = doc.addObject("Part::Common", "PositiveHalf")
    positive.Base, positive.Tool = source, cutter
    negative = doc.addObject("Part::Cut", "NegativeHalf")
    negative.Base, negative.Tool = source, cutter
    doc.recompute()
    for result in [positive, negative]:
        body = doc.addObject("PartDesign::Body", result.Name + "Body")
        body.BaseFeature = result
    doc.recompute()
    check(abs(positive.Shape.Volume + negative.Shape.Volume - source.Shape.Volume) < 1e-5,
          "paired native booleans preserve both halves")
    link = doc.addObject("App::Link", "Copy")
    link.setLink(source)
    link.Placement.Base = App.Vector(40, 0, 0)
    transformed = doc.addObject("Part::Compound", "TransformedShape")
    transformed.Links = [link]
    body = doc.addObject("PartDesign::Body", "TransformedPart")
    body.BaseFeature = transformed
    mirror = doc.addObject("Part::Mirroring", "Mirror")
    mirror.Source = source
    mirror.Normal = App.Vector(1, 0, 0)
    mirror.Base = App.Vector(0, 0, 0)
    doc.recompute()
    check(body.Shape.BoundBox.XMin == 40, "link transform must reach output Body")
    source.Length = 22
    doc.recompute()
    check(abs(body.Shape.BoundBox.XMax - 62) < 1e-5, "copy must follow upstream dimensions")
    check(abs(positive.Shape.Volume - 1200) < 1e-5 and abs(negative.Shape.Volume - 1000) < 1e-5,
          "native split must follow upstream dimensions")
    mapping = []
    for obj in [source, split, positive, transformed, body]:
        mapped = obj.Shape.getElementMappedName("Face1")
        started = time.perf_counter()
        if mapped:
            for _ in range(100):
                obj.Shape.getElement(mapped)
                obj.getElementHistory(mapped)
        mapping.append({"object": obj.Name, "map_size": obj.Shape.ElementMapSize,
                        "mapped_face_available": bool(mapped),
                        "mapped_face": mapped, "indexed_face": obj.Shape.getElementIndexedName(mapped),
                        "history": str(obj.getElementHistory(mapped)),
                        "100_resolution_seconds": time.perf_counter() - started})
    # Studio rollback can change native per-body tips without a second graph.
    current = halves[0].Tip
    doc.openTransaction("Rollback one Body")
    halves[0].Tip = current.Base[0]
    doc.recompute()
    doc.commitTransaction()
    check(halves[0].Tip != current, "Tip rollback")
    doc.undo()
    doc.recompute()
    check(halves[0].Tip == current, "Tip rollback undo")
    # Delete-part intent belongs in metadata so dependent native objects survive.
    body.addProperty("App::PropertyBool", "KurtShapePartDeleted")
    doc.openTransaction("Delete part intent")
    body.KurtShapePartDeleted = True
    doc.commitTransaction()
    doc.undo()
    check(not body.KurtShapePartDeleted, "delete metadata undo")
    path = WORK / "compositions.FCStd"
    doc.recompute()
    doc.saveAs(str(path))
    case = {"path": str(path), "result_ids": [obj.Name for obj in halves] +
            ["PositiveHalfBody", "NegativeHalfBody", "TransformedPart", "Mirror"],
            "installed_slice_proxy": type(split.Proxy).__module__ + "." + type(split.Proxy).__name__,
            "split_solids": len(split.Shape.Solids), "split_then_native_fillets": [summary(obj) for obj in halves],
            "native_planar_split": [summary(positive), summary(negative)],
            "transformed_body": summary(body), "mirror": summary(mirror),
            "native_tip_rollback_undo": True, "delete_metadata_undo": True,
            "element_maps": mapping,
            "indexed_solid_binders_are_probe_only": True}
    App.closeDocument(doc.Name)
    return case


def refinement(use_hasher=True):
    """Check real adjacent solids, mapped names and surviving native ancestry."""
    doc = App.newDocument("BodyBooleanRefinement")
    doc.UseHasher = use_hasher
    a = doc.addObject("Part::Box", "SourceA")
    b = doc.addObject("Part::Box", "SourceB")
    b.Placement.Base = App.Vector(10, 0, 0)
    doc.recompute()
    first = doc.addObject("PartDesign::Body", "BodyA")
    first.BaseFeature = a
    second = doc.addObject("PartDesign::Body", "BodyB")
    second.BaseFeature = b
    # FeatureBase copies local primitive geometry; preserve its native placement.
    second.Placement = b.Placement
    doc.recompute()
    tip = first.Tip
    boolean = first.newObject("PartDesign::Boolean", "BodyUnion")
    boolean.Type = 0
    boolean.Group = [second]
    boolean.BaseFeature = tip
    cases = []
    for refine in [False, True]:
        boolean.Refine = refine
        doc.recompute()
        check(abs(boolean.Shape.Volume - 2000) < 1e-5, "two real adjacent cubes")
        faces = []
        for i, face in enumerate(boolean.Shape.Faces, 1):
            indexed = "Face" + str(i)
            mapped = boolean.Shape.getElementMappedName(indexed)
            history = boolean.getElementHistory(mapped)
            check(boolean.Shape.getElement(mapped).isSame(face), "map names actual face")
            faces.append({"indexed": indexed, "mapped": mapped,
                          "center": list(face.CenterOfMass),
                          "raw_native_tag_ids": [int(tag, 16) for tag in re.findall(r";:H([0-9a-fA-F]+)(?=[:,])", mapped)],
                          "history_ids": [entry[0].Name for entry in history],
                          "history": str(history)})
        stale = [{"mapped": key, "indexed": value} for key, value in boolean.Shape.ElementMap.items()
                 if value.startswith("Face") and int(value[4:]) > len(boolean.Shape.Faces)]
        cases.append({"refine": refine, "faces": faces, "stale_face_maps": stale,
                      "volume": boolean.Shape.Volume, "map_size": boolean.Shape.ElementMapSize})
    path = WORK / ("body-boolean-refinement" + ("" if use_hasher else "-unhashed") + ".FCStd")
    doc.saveAs(str(path))
    App.closeDocument(doc.Name)
    doc = App.openDocument(str(path))
    for obj in doc.Objects:
        if obj.TypeId.startswith(("Part::", "PartDesign::")):
            obj.touch()
    doc.recompute()
    check(len(doc.BodyUnion.Shape.Faces) == 6, "refined Boolean persists and rebuilds")
    persisted = [entry[0].Name for entry in doc.BodyUnion.getElementHistory(
        doc.BodyUnion.Shape.getElementMappedName("Face2"))]
    persisted_name = doc.BodyUnion.Shape.getElementMappedName("Face4")
    persisted_tags = [int(tag, 16) for tag in re.findall(r";:H([0-9a-fA-F]+)(?=[:,])", persisted_name)]
    source_tags = {obj.Name: obj.ID for obj in [doc.SourceA, doc.SourceB]}
    if not use_hasher:
        check(set(source_tags.values()).issubset(persisted_tags), "unhashed composite preserves both source tags")
    App.closeDocument(doc.Name)
    report = {"use_hasher": use_hasher, "cases": cases, "save_reopen_recompute": True,
              "reopen_face2_history_ids": persisted, "path": str(path),
              "reopen_top_face_mapped_name": persisted_name, "reopen_top_face_raw_native_tag_ids": persisted_tags,
              "reopen_source_ids": source_tags,
              "limit": "Recursive history returns one lineage. Unhashed composite mapped names retain both source tags; no production provenance parser is implemented."}
    report_path = OUT / ("body-boolean-refinement" + ("" if use_hasher else "-unhashed") + ".json")
    report_path.write_text(json.dumps(report, indent=2))
    return report


def reopen():
    cases = []
    for filename in ["bodies", "compound", "compositions"]:
        doc = App.openDocument(str(WORK / (filename + ".FCStd")))
        for obj in doc.Objects:
            if obj.TypeId.startswith(("Part::", "PartDesign::", "Sketcher::")):
                obj.touch()
        doc.recompute()
        results = []
        if filename == "bodies":
            results = [obj for obj in doc.Objects if obj.TypeId == "PartDesign::Body"]
        elif filename == "compound":
            results = [doc.Cut25]
        else:
            results = [doc.Half0, doc.Half1, doc.PositiveHalfBody, doc.NegativeHalfBody,
                       doc.TransformedPart, doc.Mirror]
            check(type(doc.Slice.Proxy).__module__ == "BOPTools.SplitFeatures", "installed proxy restored")
            doc.Source.Length = 24
            doc.recompute()
            check(abs(doc.TransformedPart.Shape.BoundBox.XMax - 64) < 1e-5, "fresh copy edit")
            check(abs(doc.PositiveHalf.Shape.Volume - 1400) < 1e-5, "fresh native split edit")
            check(len(doc.Slice.Shape.Solids) == 2, "fresh installed split edit")
        for obj in results:
            check(not obj.Shape.isNull() and obj.Shape.isValid(), "fresh recompute " + obj.Name)
        if filename != "compositions":
            check(len(doc.Studio.FeatureOrder) == 30 and doc.Studio.RollbackIndex == 30,
                  "native studio metadata persists")
            check(sum(len(obj.Shape.Solids) for obj in results) == 4, "fresh four part fixture")
        cases.append({"fixture": filename, "results": [summary(obj) for obj in results],
                      "native_order_count": len(doc.Studio.FeatureOrder) if filename != "compositions" else None})
        App.closeDocument(doc.Name)
    (OUT / "fresh-process-reopen.json").write_text(json.dumps(cases, indent=2))
    print(json.dumps({"fresh_process_reopen": "passed", "fixtures": len(cases)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reopen", action="store_true")
    parser.add_argument("--refinement", action="store_true")
    parser.add_argument("--unhashed-refinement", action="store_true")
    args = parser.parse_args()
    if args.reopen:
        reopen()
    elif args.refinement:
        print(json.dumps(refinement(), indent=2))
    elif args.unhashed_refinement:
        print(json.dumps(refinement(use_hasher=False), indent=2))
    else:
        report = {"FreeCAD": App.Version(), "OCCT": Part.OCC_VERSION, "gui_up": App.GuiUp}
        try:
            report["bodies"] = make_fixture("bodies")
            report["compound"] = make_fixture("compound")
            report["compositions"] = compositions()
            report["body_boolean_refinement"] = refinement()
            report["body_boolean_unhashed_refinement"] = refinement(use_hasher=False)
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--reopen"],
                                  cwd=str(ROOT), capture_output=True, text=True, timeout=60,
                                  creationflags=flags)
            report["fresh_process"] = {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
            check(proc.returncode == 0, "fresh process reopen failed")
            report["passed"] = True
        except Exception:
            report["passed"] = False
            report["error"] = traceback.format_exc()
        (OUT / "carrier-result.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
        sys.exit(0 if report["passed"] else 1)
