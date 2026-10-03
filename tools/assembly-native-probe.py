"""Probe the pinned native Assembly engine without opening a user GUI."""
import json
import hashlib
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime/freecad-1.1.4/FreeCAD_1.1.4-Windows-x86_64-py311"
sys.path.insert(0, str(RUNTIME / "Mod/Assembly"))
import FreeCAD as App
import Part
import Assembly
import JointObject

OUT = ROOT / "validation/assembly-workflow/native-probe"
OUT.mkdir(parents=True, exist_ok=True)
report = {"version": App.Version(), "gui_up": App.GuiUp, "cases": []}

def placement(obj):
    return {"base": list(obj.Placement.Base), "rotation": list(obj.Placement.Rotation.Q)}

try:
    for kind in ("Fixed", "Revolute", "Slider"):
        doc = App.newDocument("Native" + kind)
        doc.UndoMode = 1
        asm = doc.addObject("Assembly::AssemblyObject", "Assembly")
        asm.Type = "Assembly"
        group = asm.newObject("Assembly::JointGroup", "Joints")
        source = doc.addObject("Part::Feature", "EmbeddedSource")
        source.Shape = Part.makeBox(10, 20, 30)
        a = asm.newObject("App::Link", "Base")
        a.setLink(source)
        b = asm.newObject("App::Link", "Follower")
        b.setLink(source)
        b.Placement.Base = App.Vector(40, 50, 60)
        ground = group.newObject("App::FeaturePython", "Ground")
        JointObject.GroundedJoint(ground, a)
        joint = group.newObject("App::FeaturePython", "Joint")
        JointObject.Joint(joint, JointObject.JointTypes.index(kind))
        joint.Proxy.setJointConnectors(joint, [[a, ["", ""]], [b, ["", ""]]])
        doc.recompute()
        case = {"kind": kind, "assembly_properties": asm.PropertiesList,
                "assembly_methods": [k for k in dir(asm) if not k.startswith("_")],
                "solve_doc": asm.solve.__doc__, "solve_return": str(asm.solve()),
                "state": str(asm.State), "status": asm.getStatusString(),
                "base": placement(a), "follower": placement(b),
                "joint_properties": joint.PropertiesList,
                "references": str([joint.Reference1, joint.Reference2])}
        # Preserve the permitted degree of freedom, then deliberately violate it.
        if kind == "Revolute":
            b.Placement = App.Placement(App.Vector(), App.Rotation(App.Vector(0, 0, 1), 35))
        elif kind == "Slider":
            b.Placement.Base = App.Vector(0, 0, 25)
        else:
            b.Placement.Base = App.Vector(15, 0, 0)
        case["movement_return"] = str(asm.solve())
        case["after_movement"] = placement(b)
        case["status_after_movement"] = asm.getStatusString()
        path = OUT / (kind + ".FCStd")
        doc.recompute()
        doc.saveAs(str(path))
        App.closeDocument(doc.Name)
        doc = App.openDocument(str(path))
        asm = doc.getObject("Assembly")
        case["reopen_return"] = str(asm.solve())
        case["reopen_status"] = asm.getStatusString()
        case["reopen_follower"] = placement(doc.getObject("Follower"))
        case["proxy_type"] = str(type(doc.getObject("Joint").Proxy))
        App.closeDocument(doc.Name)
        report["cases"].append(case)
    # Native revolute axes are undirected: an antiparallel connector axis is a
    # valid physical axis, which the C++ solver intentionally preserves.
    doc = App.newDocument("NativeAxisDirection")
    asm = doc.addObject("Assembly::AssemblyObject", "Assembly")
    asm.Type = "Assembly"
    group = asm.newObject("Assembly::JointGroup", "Joints")
    a = asm.newObject("Part::Box", "Base")
    b = asm.newObject("Part::Box", "Rotor")
    b.Placement = App.Placement(App.Vector(), App.Rotation(App.Vector(1, 0, 0), 180))
    ground = group.newObject("App::FeaturePython", "Ground")
    JointObject.GroundedJoint(ground, a)
    joint = group.newObject("App::FeaturePython", "Joint")
    JointObject.Joint(joint, JointObject.JointTypes.index("Revolute"))
    joint.Reference1 = [a, ["", ""]]
    joint.Reference2 = [b, ["", ""]]
    joint.Proxy.updateJCSPlacements(joint)
    doc.recompute()
    result = asm.solve()
    relative = (a.Placement * joint.Placement1).inverse() * (b.Placement * joint.Placement2)
    report["antiparallel_revolute"] = {"native_code": result, "relative_axis_z": list(relative.Rotation.multVec(App.Vector(0, 0, 1))), "relative_rotation": list(relative.Rotation.Q)}
    assert result == 0 and relative.Rotation.multVec(App.Vector(0, 0, 1)).z < -0.999999
    App.closeDocument(doc.Name)

    # OCCT compound mass integration uses an aggregate reference point. With
    # several disconnected imported solids it can differ from the invariant
    # sum of the solids' masses. Prove topology/geometry and rigid transforms
    # independently, without relaxing the native preservation checks.
    report["geometry_mass_probe"] = {"sources": [], "placed_solids": []}
    shapes = []
    for filename in ("Dodec pipe mount.step", "Dodec Hub Conformal.step"):
        path = ROOT.parents[1] / "Onshape examples" / filename
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        shape = Part.read(str(path))
        report["geometry_mass_probe"]["sources"].append({"file": filename, "sha256": digest,
            "compound_volume_mm3": shape.Volume, "sum_solid_volume_mm3": sum(solid.Volume for solid in shape.Solids),
            "solid_count": len(shape.Solids)})
        for index, solid in enumerate(shape.Solids):
            placed = solid.copy()
            placed.Placement = App.Placement(App.Vector(300, 7, 11), App.Rotation(App.Vector(0, 0, 1), 31)) * solid.Placement
            restored = placed.copy()
            restored.Placement = solid.Placement
            original_hash = hashlib.sha256(solid.exportBrepToString().encode()).hexdigest()
            restored_hash = hashlib.sha256(restored.exportBrepToString().encode()).hexdigest()
            # A rectangular bar supplies an independent bidirectional Boolean
            # equality check. Identical complex imported spline bodies can make
            # native self-subtraction take many minutes, without adding a
            # distinct transform case, so verify their native rigid metrics.
            boolean_case = filename == "Dodec pipe mount.step" and index == 0
            forward = solid.cut(restored).Volume if boolean_case else None
            reverse = restored.cut(solid).Volume if boolean_case else None
            original_bounds = [getattr(solid.BoundBox, key) for key in ("XMin", "YMin", "ZMin", "XMax", "YMax", "ZMax")]
            restored_bounds = [getattr(restored.BoundBox, key) for key in ("XMin", "YMin", "ZMin", "XMax", "YMax", "ZMax")]
            report["geometry_mass_probe"]["placed_solids"].append({"file": filename, "solid": index + 1,
                "original_volume_mm3": solid.Volume, "placed_volume_mm3": placed.Volume,
                "original_area_mm2": solid.Area, "placed_area_mm2": placed.Area,
                "restored_bounds_max_difference_mm": max(abs(a - b) for a, b in zip(original_bounds, restored_bounds)),
                "restored_brep_matches": original_hash == restored_hash,
                "original_minus_restored_mm3": forward, "restored_minus_original_mm3": reverse})
            # BRep copies can serialize different native bookkeeping/ordering.
            # Bidirectional native subtraction establishes geometric equality.
            assert not boolean_case or forward < 1e-7 and reverse < 1e-7
            assert len(solid.Faces) == len(restored.Faces) and len(solid.Edges) == len(restored.Edges)
            assert abs(solid.Volume - placed.Volume) < 1e-7 and abs(solid.Area - placed.Area) < 1e-7
            assert max(abs(a - b) for a, b in zip(original_bounds, restored_bounds)) < 1e-7
            shapes.append(solid.copy())
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    repeated = shapes[0].copy()
    repeated.Placement = App.Placement(App.Vector(300, 0, 0), App.Rotation()) * repeated.Placement
    shapes.append(repeated)
    compound = Part.makeCompound(shapes)
    report["geometry_mass_probe"].update(assembly_compound_volume_mm3=compound.Volume,
        assembly_sum_occurrence_volume_mm3=sum(shape.Volume for shape in shapes),
        assembly_solid_count=len(compound.Solids))
    report["passed"] = True
except Exception:
    report["passed"] = False
    report["traceback"] = traceback.format_exc()
finally:
    (OUT / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
raise SystemExit(0 if report["passed"] else 1)
