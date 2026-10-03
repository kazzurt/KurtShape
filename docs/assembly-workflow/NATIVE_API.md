# Native Assembly API and representation

October 2, 2026. This increment uses the installed **FreeCAD 1.1.4**, revision `4fd3bf320d9566a27e60069fc8387448aaa3a094`, and OCCT 7.8.1. The original runtime remains unmodified. The adapter is `src/kurtshape/assembly.py`; the shared controller owns native transactions, UUID/revision checks, edit/busy guards, request replay, staged save and rollback.

## Verified native foundation

The isolated bundled-Python probe creates `Assembly::AssemblyObject`, sets its native `Type` to `Assembly`, creates an `Assembly::JointGroup`, and adds same-document `App::Link` occurrences. Native joints are `App::FeaturePython` objects initialized with the installed `JointObject.Joint`; the grounded reference uses `JointObject.GroundedJoint`. The corresponding GUI providers are the installed `ViewProviderJoint` and `ViewProviderGroundedJoint`. These exact classes and this bounded native structure are accepted; arbitrary Python proxies, additional Python properties, scripted view providers, external document links and nested assemblies remain outside the workflow.

Native joint references are `[occurrence, [element, element]]`, where an empty element uses the occurrence origin. `FaceN` uses the native face connector center, `EdgeN` uses its center/midpoint and native axis, and `VertexN` uses the vertex position. The adapter validates analytic faces, line/circle edges and vertices before assigning references. Native `Joint.Proxy.updateJCSPlacements()` computes each local connector frame. Native `assembly.solve(False)` computes occurrence placements; the adapter does not implement a second solver.

The actual `solve()` binding returns an integer, with the documented priorities:

| Code | Native meaning |
|---|---|
| `0` | Success |
| `-6` | No fixed parts |
| `-4` | Over-constrained |
| `-3` | Conflicting constraints |
| `-5` | Malformed constraints |
| `-1` | Solver error |
| `-2` | Redundant constraints |

New native link/joint membership must be recomputed before requesting the explicit solver result. A zero return alone is insufficient: a real conflicting fixed-joint fixture returned zero while leaving earlier intent unsatisfied. After every meaningful solve, the adapter verifies that the grounded occurrence did not move, all fixed connector frames coincide, revolute origins coincide and axes are parallel, and slider frames retain orientation with only axial separation. Unsatisfied residuals produce `assembly_solver_failed` even when the native code is zero; the caller aborts the entire native transaction. Redundant but satisfied constraints may be accepted by the native solver.

The first probe corrects a displaced fixed follower, retains a 35° revolute rotation and retains a 25 mm slider displacement, then saves/reopens and solves each case. Native revolute axes are physically undirected: an additional probe starts the follower at a 180° rotation about X; the native solver retains its antiparallel Z axis with code zero. The residual check therefore checks parallel axes of either sign. Typed motion uses the directed first connector's Z axis for a repeatable signed coordinate.

## Portable embedded sources

Insertion reads a saved FCStd through a temporary isolated native document. Archive preflight rejects scripted source objects/properties and linked/nested assembly sources before restoration. The sole Python metadata exception is an exact `KurtShapeProject` object with a null proxy, including a null metadata GUI proxy. The source copy is recomputed and checked; the original file is hashed before/after reading and is never overwritten. Several final Bodies or standalone native solid results require an explicit `source_id` from `assembly_candidates`.

The selected evaluated solid is embedded as a hidden native `Part::Feature` at identity placement, with its original placement and provenance recorded in native properties. Repeated instances of the same saved source SHA256/object ID share this embedded snapshot through separate same-document `App::Link` objects. Every occurrence has its own stable native ID and placement. The first occurrence is grounded automatically; Ground can change the reference while retaining the current poses.

The embedded geometry is a solid snapshot, not a parametric clone of the source feature history. Recorded source paths are informational. Reopen, relocation and export do not read them, so renaming or removing a source path does not break the assembly. Source edits do not update existing instances automatically; insert the revised saved source explicitly. A changed saved-file hash creates a separate snapshot without replacing accepted occurrences. The original parametric project remains the place to edit the source.

Each embedded source has a SHA256 fingerprint of a native geometry copy with display mesh omitted: `Shape.copy(True, False).exportBrepToString()`. This exact binding requires positional arguments. The canonical serialized fingerprint masks only the transient third `Checked` bit of seven-bit topology flag rows within the `TShapes` section. The GUI/fresh-process BRep diff changed only this bit for six faces; pinned [OCCT 7.8.1 serialization](https://raw.githubusercontent.com/Open-Cascade-SAS/OCCT/V7_8_1/src/TopTools/TopTools_ShapeSet.cxx) confirms the flag order and that V1 restoration performs native checking. All other flags, geometry, tolerances, topology, locations and orientations remain in the fingerprint. Display triangulation and native validation-cache state therefore cannot invalidate an unchanged saved source. Hashes are checked once per observer geometry generation and reused during idle inspection; caches are removed when the document closes. Editing embedded geometry directly invalidates the assembly and requires reinserting the saved source; Solve cannot silently accept a modified snapshot.

## Motion, inspection and export

`move_assembly_joint` sets an absolute native joint coordinate: degrees for revolute rotation or millimeters for slider travel. It composes the native connector/occurrence placements along the permitted coordinate, applies a rigid displacement to the component found by traversing current native references, then asks the native solver to validate the result. It checks that the requested coordinate survives solving. Fixed, suppressed or otherwise locked motion rejects. This traversal is transient; no editable geometry graph is maintained outside FCStd. Unconstrained, ungrounded occurrences also support a millimeter position and quaternion orientation.

Inspection reports native occurrence identity, placement, embedded-source provenance, grounding, connection to ground, joint references, measured coordinate, suppression, connector detachment/offsets, and solver status. Disconnected inserted occurrences are explicitly counted and retain native free degrees of freedom. A persisted lightweight solved stamp covers assembly/occurrence placements, links, grounding, references, joint types, suppression, connector frames/offsets and native joint-limit flags/values. Native pose or reference changes invalidate the accepted solve without running a solver during inspection. Labels are excluded from this stamp. Enabled joint limits are rejected as outside this first workflow. Unsupported arbitrary native assemblies remain inspectable and cannot enter this bounded mutation/export workflow.

Current-solid export in a document containing this assembly includes each occurrence exactly once at its solved global placement. Hidden source snapshots and pre-existing Part Studio solids are excluded. Source, occurrence and assembly transforms are applied once; occurrences are neither fused nor deduplicated. Generic Part Studio STEP import/measurement behavior remains intact.

OCCT's compound mass integration can vary with the aggregate reference point when several disconnected imported solids are widely separated. In the original hub source, compound volume is approximately 73546.829175 mm³ while the sum of its individual solid volumes is approximately 73542.228565 mm³. Assembly aggregate volume therefore sums individual occurrence measurements. The native probe records both quantities and verifies all six original solids after a rigid displacement and inverse displacement using native volume, area, topology counts and restored bounds. The rectangular pipe bar additionally passes bidirectional native subtraction with zero residual. Native self-subtraction of a complex imported spline body took several minutes; the verified isolated probe process was stopped and that redundant expensive check was bounded to the bar. BRep copies can serialize different native bookkeeping, so serialization equality alone is not used as the rigid-transform geometry proof.

## Reproduction

Run from the app repository:

```powershell
& .\runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\python.exe -B .\tools\assembly-native-probe.py
& .\runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\python.exe -B -m unittest discover -s tests -p test_assembly.py
.\validate-review-gui.ps1 -Scenario assembly
& .\runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\python.exe -B .\tools\validate_assembly_reopen.py
```

The native probe writes its report under `validation/assembly-workflow/native-probe/`. The GUI recipe uses a separate hidden application and isolated profile, exercises the actual controls and rendered window, and writes its report/screenshots under `validation/assembly-workflow/`. The final recipe reopens the GUI-produced relocated FCStd in a genuinely fresh bundled-Python process with the original source path absent. None of these recipes drive, restart or close Kurt's existing modeling window. Full result counts and runtime warnings belong in the assembly implementation/validation handoff.
