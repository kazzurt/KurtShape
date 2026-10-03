# First Assembly workflow

October 2, 2026, America/Los_Angeles. This increment uses the pinned portable FreeCAD 1.1.4 Assembly objects and solver. FCStd remains the authoritative document; there is no separate editable assembly graph or custom joint solver.

## Source and portability policy

Insert chooses a Body/final solid from a saved FCStd project. Multiple candidates require choosing the intended source ID. Each occurrence is a native `App::Link` with its own stable native ID and placement, linked to a hidden **same-document** `Part::Feature` shape snapshot. Original files are read, never modified. Source filename/ID/hash are provenance, not live external dependencies.

This is an embedded geometry snapshot, not an editable reconstruction of source sketches/history. Later source edits do not update accepted occurrences automatically. Insert again to take a new snapshot; existing instances stay at their accepted geometry. Reopening or relocating the assembly requires only its FCStd file and the bundled Assembly implementation. Source files may move or be unavailable after insertion. Unsafe proxy/script-owned source projects, external references and nested assemblies reject; this narrowly supported workflow does not make arbitrary FCStd projects adoptable.

STEP parts use **Open STEP → Save FCStd → Insert part**. Both supplied STEP examples remain unchanged and their imported Bodies can be selected independently. STEP geometry contains no reconstructed historical mates or FeatureScript interpretation; the real parametric conversion gate stays **0/2**.

## Workspaces and results

The workspace chooser exposes Assembly controls and returns to a separate Part Studio document for modeling. A project supports one single-level assembly. Assembly inspection/export enumerates its occurrences exactly once, excluding hidden snapshots and any Part Studio geometry that preceded assembly creation. Independent instances may remain unjointed and carry free degrees of freedom; solver success does not imply every part is constrained.

The first inserted occurrence is grounded automatically. Ground another occurrence to change the reference. A fixed joint fastens two native connectors. Revolute permits rotation around connector Z; slider permits translation along connector Z. References name instance IDs and native Face/Edge/Vertex subelements; empty subelement uses the instance origin. Connectors come from the bundled native Assembly implementation, so topology and orientation retain native semantics rather than guessed mate positions.

Movement of a revolute/slider joint sets its permitted coordinate and then solves the native assembly. Free instance placement accepts millimeter position and quaternion rotation; constrained/grounded moves reject or must satisfy the actual solver. Fixed joints have no movement coordinate. Native solver errors remain visible in Messages. Conflicting creation/edit/movement aborts the whole transaction, including placements and references, and preserves the accepted revision/history.

Rename preserves internal IDs. Removal requires explicit cascade when joints depend on an occurrence; native undo restores occurrence references and solved placements in one command. Native Tasks and sketch editing retain ownership and block assembly/file mutations. Ctrl+S and Escape keep ordinary behavior; sketch Pierce on Shift+G and Perpendicular on Shift+L are preserved.

## Shared controller

GUI and authenticated loopback clients use the same typed, argument-whitelisted operations. Existing UUID/revision checks, session request-ID replay and unknown-outcome reconciliation apply. Invalid/stale requests reject before model mutation. Inspection reports assembly/instances/joints, grounding, placements and solver/build status. Source reads and solves occur at meaningful commands, never on idle polling. Observer generations invalidate shape measurements on recompute and native placement/link changes.

Native save uses the existing checked staging/replacement/recovery path. Reopen validates the native solver. STEP export writes the compound of each occurrence's global transformed shape once without fusion; sidecar provenance includes instance/joint state, engine, revision, geometry measurements and SHA256. Failed or unresolved current intent blocks export, while inspection distinguishes retained geometry from current success.

## Reproduce acceptance

```powershell
& runtime/freecad-1.1.4/FreeCAD_1.1.4-Windows-x86_64-py311/bin/python.exe -B tools/assembly-native-probe.py
.\run-checks.ps1
.\validate-review-gui.ps1 -Scenario assembly
& runtime/freecad-1.1.4/FreeCAD_1.1.4-Windows-x86_64-py311/bin/python.exe -B tools/validate_assembly_reopen.py
```

Native evidence, isolated GUI reports, screenshots and disposable fixtures are under `validation/assembly-workflow`. The GUI recipe launches its own hidden process/profile and preserves the user's open modeling window. Run the fresh-process recipe after that GUI finishes. Large/generated files are reproducible and ignored; small JSON reports are retained.

Final acceptance: **83 offline native tests**, including 15 Assembly tests; **4 bridge tests**, **22 shortcut tests**, **58 actual Assembly GUI checks**, **4 fresh-process reopen checks**, and **19 existing STEP GUI checks** passed. The native API probe passed fixed/revolute/slider motion and persistence, and original STEP geometry transform checks. The final saved GUI fixture is `gui-solved-assembly-40576.FCStd`. Both original STEP hashes remain unchanged. Rendered controls, grounding, occurrence/joint history and relocated reopen were visually inspected. Authenticated loopback creation selects the Assembly workspace automatically; rejected shared-client constraints display once in Messages and replay preserves the original outcome. Y/Shift+Y hides/restores occurrences while embedded sources stay hidden. [Detailed evidence and runtime warnings](VALIDATION.md).

Validation fixed native joint membership/recompute ordering, solver-zero results with unsatisfied connector relations, abort diagnostics reopening a rejected undo command, and BRep display/validation cache differences across GUI/headless restore. The adapter now verifies connector residuals and immutable mesh-free geometry seals while ignoring only OCCT's transient `Checked` flag. Current solver failures remain visible and retained geometry is not labeled current success. Checkpoint/recovery restores instances, references and accepted poses. Idle inspection performs no solve, source read, geometry serialization or measurement recalculation.

## First hands-on assembly

Save and close an older running app when ready, then launch `KurtShape.cmd` to load the new code. Choose **Assembly → Create Assembly**, then **Insert** a saved FCStd Body; repeat Insert for another instance. The first is grounded; select an instance and **Ground** to change the reference. Ctrl-select one native face/edge/vertex from each of two instances and choose **Fixed**, **Revolute** or **Slider**; the dialog also permits explicit instance/reference selection, with blank reference meaning origin. Select the revolute/slider joint and **Move** to set degrees/millimeters. Use **Edit** or history context menus to change, rename or remove it; undo/redo restores the command. **Ctrl+S** saves FCStd. Close that assembly before Open of its saved or relocated copy; instances and joints restore without source files. **Export** writes all occurrences at global placement. Choose **Part Studio** to return to independent modeling.

Deferred: nested assemblies, advanced joint types, drawing/BOM, animation/simulation, assembly snapping, broad connector tooling, and automatic source updates. Additional modeling UI refinements are coordinated separately in [COORDINATION.md](COORDINATION.md).
