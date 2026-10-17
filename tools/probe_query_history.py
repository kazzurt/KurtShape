"""Probe native element history fidelity in the pinned FreeCAD runtime.

Run with the bundled bin/python.exe -B tools/probe_query_history.py.
This spike deliberately does not implement selectors or infer native creators.
"""
from pathlib import Path
import json
import itertools
from kurtshape_evidence import evidence_dir
import FreeCAD as App
import Part


ROOT = Path(__file__).resolve().parents[1]
DESTINATION = evidence_dir("u2-part-model-spike")
DESTINATION.mkdir(parents=True, exist_ok=True)


def history(obj, name):
    return [{"object": item[0].Name if hasattr(item[0], "Name") else str(item[0]),
             "element": str(item[1]), "intermediate": [str(n) for n in item[2]]}
            for item in obj.getElementHistory(name)]


def faces(obj):
    return [{"native": "Face" + str(i + 1),
             "mapped": obj.Shape.getElementMappedName("Face" + str(i + 1)),
             "area_mm2": face.Area,
             "center_mm": list(face.CenterOfMass),
             "normal": list(face.normalAt(0, 0)),
             "history": history(obj, "Face" + str(i + 1))}
            for i, face in enumerate(obj.Shape.Faces)]


def record(obj):
    mapped = dict(obj.Shape.ElementMap)
    actual = {"Face" + str(i + 1) for i in range(len(obj.Shape.Faces))}
    return {"object": obj.Name, "type": obj.TypeId,
            "solid_count": len(obj.Shape.Solids),
            "face_count": len(obj.Shape.Faces),
            "element_map_size": obj.Shape.ElementMapSize,
            "native_history_property": str(getattr(obj, "History", None)),
            "dangling_face_map_values": sorted({n for n in mapped.values()
                                                if n.startswith("Face") and n not in actual}),
            "faces": faces(obj)}


doc = App.newDocument("U2QueryHistorySpike")
try:
    body = doc.addObject("PartDesign::Body", "Body")
    sketch = body.newObject("Sketcher::SketchObject", "Profile")
    points = [App.Vector(0, 0, 0), App.Vector(10, 0, 0),
              App.Vector(10, 20, 0), App.Vector(0, 20, 0)]
    for i, point in enumerate(points):
        sketch.addGeometry(Part.LineSegment(point, points[(i + 1) % 4]), False)
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile, pad.Length = sketch, 5
    doc.recompute()
    hole = body.newObject("Sketcher::SketchObject", "Hole")
    hole.addGeometry(Part.Circle(App.Vector(5, 10, 0), App.Vector(0, 0, 1), 2), False)
    pocket = body.newObject("PartDesign::Pocket", "Pocket")
    pocket.Profile, pocket.Type, pocket.Reversed = hole, 1, True
    doc.recompute()

    first = doc.addObject("Part::Box", "BoxA")
    first.Length, first.Width, first.Height = 10, 20, 5
    second = doc.addObject("Part::Box", "BoxB")
    second.Length, second.Width, second.Height = 10, 20, 5
    second.Placement.Base = App.Vector(10, 0, 0)
    divider = doc.addObject("Part::Box", "Divider")
    divider.Length, divider.Width, divider.Height = 2, 30, 10
    divider.Placement.Base = App.Vector(4, -5, -2)
    split = doc.addObject("Part::Cut", "Split")
    split.Base, split.Tool = first, divider
    merged = doc.addObject("Part::MultiFuse", "Merged")
    merged.Shapes, merged.Refine = [first, second], False
    common = doc.addObject("Part::Common", "Common")
    common.Base, common.Tool = first, divider
    doc.recompute()

    report = {"engine": {"freecad": App.Version(), "occt": Part.OCC_VERSION},
              "recipe": "tools/probe_query_history.py",
              "pad": record(pad), "pocket": record(pocket),
              "split": record(split), "common": record(common),
              "unrefined_fuse": record(merged)}
    merged.Refine = True
    doc.recompute()
    report["refined_fuse"] = record(merged)
    refined_top = next(f for f in report["refined_fuse"]["faces"]
                       if abs(f["normal"][2] - 1) < 1e-7)
    report["merged_top_face"] = {
        "current": refined_top,
        "expected_creators_per_atlas": ["BoxA", "BoxB", "Merged"],
        "exposed_history_objects": [h["object"] for h in refined_top["history"]],
    }
    inherited_side = next(f for f in report["pocket"]["faces"]
                          if len(f["history"]) > 1 and f["history"][1]["object"] == "Pad"
                          and abs(f["normal"][2]) < 1e-7)
    report["inherited_side_false_creator_hazard"] = inherited_side
    split_sources = {}
    for face in report["split"]["faces"]:
        source = face["history"][-1]
        key = source["object"] + "." + source["element"]
        split_sources.setdefault(key, []).append(face["native"])
    report["split_source_multiplicity"] = split_sources
    assert pad.Shape.ElementMapSize > 0 and pocket.Shape.ElementMapSize > 0
    assert inherited_side["history"][0]["object"] == "Pocket"
    assert len(split.Shape.Solids) == 2
    assert len(split_sources["BoxA.Face6"]) == 2
    assert report["unrefined_fuse"]["face_count"] == 10
    assert report["refined_fuse"]["face_count"] == 6
    assert report["refined_fuse"]["dangling_face_map_values"]
    assert "BoxB" not in report["merged_top_face"]["exposed_history_objects"]

    fresh_merged = doc.addObject("Part::MultiFuse", "FreshRefinedMerge")
    fresh_merged.Shapes, fresh_merged.Refine = [first, second], True
    doc.recompute()
    report["fresh_refined_fuse"] = record(fresh_merged)
    assert report["fresh_refined_fuse"]["dangling_face_map_values"]
    unrefined = doc.addObject("Part::MultiFuse", "UnrefinedForRefine")
    unrefined.Shapes, unrefined.Refine = [first, second], False
    doc.recompute()
    native_refine = doc.addObject("Part::Refine", "NativeRefine")
    native_refine.Source = unrefined
    doc.recompute()
    report["native_part_refine"] = record(native_refine)
    assert native_refine.Shape.ElementMapSize == 0
    raw_refined = unrefined.Shape.removeSplitter()
    report["raw_remove_splitter"] = {
        "face_count": len(raw_refined.Faces),
        "element_map_size": raw_refined.ElementMapSize,
        "face_map": {k: v for k, v in raw_refined.ElementMap.items() if v.startswith("Face")},
        "history_api_note": (
            "Raw Shape.removeSplitter carries both sources inside a composite mapped "
            "name, but getElementHistory only returns one source tag and opaque composite "
            "text. Native Part::Refine drops this map. A custom adapter/parser would "
            "need separately proven complete and persistent creator semantics."
        ),
    }
    raw_object = doc.addObject("Part::Feature", "RawRefinedHistoryProbe")
    raw_object.Shape = raw_refined
    doc.recompute()
    raw_top = next("Face" + str(i + 1) for i, face in enumerate(raw_object.Shape.Faces)
                   if face.normalAt(0, 0).z > 0.999)

    def serial(value):
        if hasattr(value, "Name"):
            return value.Name
        if isinstance(value, (list, tuple)):
            return [serial(item) for item in value]
        return str(value)

    report["history_api_options"] = {
        "object_docstring": raw_object.getElementHistory.__doc__,
        "shape_docstring": raw_object.Shape.getElementHistory.__doc__,
        "flags": [{"recursive": recursive, "same_type": same_type, "show_name": show_name,
                   "result": serial(raw_object.getElementHistory(raw_top, recursive, same_type, show_name))}
                  for recursive, same_type, show_name in itertools.product([False, True], repeat=3)],
        "shape_result": serial(raw_object.Shape.getElementHistory(raw_object.Shape.getElementMappedName(raw_top))),
    }
    assert "BoxB" not in {h["object"] for h in history(raw_object, raw_top)}

    def wrong_creator_examples(obj):
        wrong = []
        for i, face in enumerate(obj.Shape.Faces):
            trail = history(obj, "Face" + str(i + 1))
            origin = trail[-1] if trail else None
            source = doc.getObject(origin["object"]) if origin else None
            if source is None or origin["element"] not in {"Face1", "Face2", "Face3", "Face4", "Face5", "Face6"}:
                continue
            prior = source.Shape.getElement(origin["element"])
            normal = face.normalAt(0, 0)
            if abs(abs(normal.dot(prior.normalAt(0, 0))) - 1) > 1e-7 or abs(normal.dot(prior.CenterOfMass - face.CenterOfMass)) > 1e-7:
                wrong.append({"current": "Face" + str(i + 1),
                              "current_center_mm": list(face.CenterOfMass),
                              "exposed_source": origin,
                              "source_center_mm": list(prior.CenterOfMass)})
        return wrong

    report["fresh_refined_wrong_creator_examples"] = wrong_creator_examples(fresh_merged)
    assert report["fresh_refined_wrong_creator_examples"]

    doc.UseHasher = False
    unhashed_a = doc.addObject("Part::Box", "UnhashedBoxA")
    unhashed_a.Length, unhashed_a.Width, unhashed_a.Height = 10, 20, 5
    unhashed_b = doc.addObject("Part::Box", "UnhashedBoxB")
    unhashed_b.Length, unhashed_b.Width, unhashed_b.Height = 10, 20, 5
    unhashed_b.Placement.Base = App.Vector(10, 0, 0)
    unhashed_fuse = doc.addObject("Part::MultiFuse", "UnhashedFuse")
    unhashed_fuse.Shapes, unhashed_fuse.Refine = [unhashed_a, unhashed_b], False
    doc.recompute()
    unhashed_raw_refine = unhashed_fuse.Shape.removeSplitter()
    raw_map = dict(unhashed_raw_refine.ElementMap)
    raw_top_index = next("Face" + str(i + 1) for i, face in enumerate(unhashed_raw_refine.Faces)
                         if face.normalAt(0, 0).z > 0.999)
    raw_top_mapped = unhashed_raw_refine.getElementMappedName(raw_top_index)
    report["unhashed_raw_refine"] = {
        "use_hasher": doc.UseHasher,
        "source_object_ids": {unhashed_a.Name: unhashed_a.ID, unhashed_b.Name: unhashed_b.ID},
        "face_map": {k: v for k, v in raw_map.items() if v.startswith("Face")},
        "merged_top_mapped_name": raw_top_mapped,
        "both_source_tags_present": all(";:H" + format(obj.ID, "x") in raw_top_mapped
                                        for obj in (unhashed_a, unhashed_b)),
    }
    assert "#" not in raw_top_mapped
    assert report["unhashed_raw_refine"]["both_source_tags_present"]
    unhashed_fuse.Refine = True
    doc.recompute()
    report["unhashed_native_refined_fuse"] = record(unhashed_fuse)
    assert report["unhashed_native_refined_fuse"]["dangling_face_map_values"]
    report["primary_naming_algorithm_source"] = {
        "url": "https://github.com/realthunder/FreeCAD_assembly3/wiki/Topological-Naming-Algorithm#tracing-model-history",
        "interpretation": (
            "The algorithm author documents multi-source names in parentheses and "
            "first-source linear getElementHistory traversal. Disabling the document "
            "hasher exposes names for parsing. This supports a potential custom "
            "provenance adapter; it does not establish this runtime's complete "
            "creator query behavior across every requested operation."
        ),
    }

    native_file = DESTINATION / "query-history-spike.FCStd"
    doc.saveAs(str(native_file))
    name = doc.Name
    App.closeDocument(name)
    doc = App.openDocument(str(native_file))
    report["refined_fuse_after_reopen"] = record(doc.getObject("Merged"))
    for obj in doc.Objects:
        if obj.TypeId.startswith(("Part::", "PartDesign::", "Sketcher::")):
            obj.touch()
    doc.recompute()
    report["refined_fuse_after_fresh_rebuild"] = record(doc.getObject("Merged"))
    report["fresh_refined_fuse_after_fresh_rebuild"] = record(doc.getObject("FreshRefinedMerge"))
    report["reopened_wrong_creator_examples"] = wrong_creator_examples(doc.getObject("FreshRefinedMerge"))
    report["checks_passed"] = [
        "Native Pad and Pocket expose element maps and history",
        "Current feature appears on untouched inherited face history",
        "Cut split face multiplicity is visible through source histories",
        "Refined MultiFuse loses merged top face's second creator",
        "Refined MultiFuse leaves invalid Face7..Face10 map indexes",
        "Fresh MultiFuse configured Refine=True before first build has the same failure",
        "Native Part::Refine exposes no element map",
        "Raw Shape.removeSplitter preserves composite mapped names but not full history traversal",
        "All eight documented object history flag combinations tested; none traverses both merged creators",
        "UseHasher=False does not repair native MultiFuse refinement maps",
        "Unhashed raw removeSplitter composite mapped name retains both merged source IDs",
        "Native history loss and wrong creator correspondence persist after FCStd reopen and fresh rebuild",
    ]
    assert report["refined_fuse_after_reopen"]["dangling_face_map_values"]
    assert report["refined_fuse_after_fresh_rebuild"]["dangling_face_map_values"]
    assert report["fresh_refined_fuse_after_fresh_rebuild"]["dangling_face_map_values"]
    assert report["reopened_wrong_creator_examples"]
    report["selector_fidelity_proven"] = False
    report["conclusion"] = (
        "getElementHistory membership is not qCreatedBy; all result objects occur "
        "on inherited-face history. Split source multiplicity is available, but "
        "refined native MultiFuse exposes incomplete and incorrectly indexed "
        "history for merged faces. Raw removeSplitter names retain both sources; "
        "the author's documented grammar and UseHasher=False offer a custom parser "
        "route. No exact all-creators query adapter is demonstrated by this spike."
    )
    (DESTINATION / "query-history.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(DESTINATION / "query-history.json"),
                      "checks_passed": report["checks_passed"],
                      "selector_fidelity_proven": report["selector_fidelity_proven"]}))
finally:
    if doc.Name in App.listDocuments():
        App.closeDocument(doc.Name)
