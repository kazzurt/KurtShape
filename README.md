# KurtShape — local native CAD

KurtShape uses portable FreeCAD 1.1.4, native Sketcher/PartDesign, and OCCT 7.8.1. Editable `.FCStd` is the authoritative model. The U2 increment adds one ordered history over many parts, scoped result operations, whole-part tools, rollback insertion and stored reference queries. It builds on the Onshape-style interface, SolidWorks mouse controls, native sketch editing in 3D and default Onshape Windows key registry. [Try the U2 walkthrough](docs/U2_WALKTHROUGH.md); [tested parity and limits](docs/ATLAS_PARITY.md).

**M1 remains in progress. Neither supplied Onshape design has been converted.** Source migration and edited-reference acceptance remain separate from this local modeling implementation. See [project continuity](docs/M1_PROGRESS.md) and [conversion coverage](docs/CONVERSION_COVERAGE.md).

**Current accepted architecture checkpoint: S18.** Eligible geometry checks and STEP exports use private native workers, compatible previews reuse immutable snapshots, and ownership guards reject stale work. Validation retains 426 native passes/four opt-in skips and five focused passes, plus 91 fresh STEP GUI checks. Synchronous capture, Save and committed recompute remain. See the [status report](docs/architecture-responsiveness-upgrade/STATUS_REPORT.md), [architecture](ARCHITECTURE.md) and [publication proposal](docs/architecture-responsiveness-upgrade/PUBLICATION_SCOPE.md). S19 prepares documentation and a diagnostic packaging correction; publication is pending.

The October 6 interaction repair maximizes startup on the main monitor and centers new parts at the origin. Native snapping accounts for display scaling and prioritizes origin, endpoint and center markers, including converted geometry. Nearby competing points now resolve to the nearest target, correcting the reproduced second-endpoint lock onto the line's first point. Right-click fully ends continuous drawing before model-edge selection resumes, fixing intercepted placement clicks after cancellation. Circle dragging no longer leaves an old unselectable outline or stale fill. Idle recovery waits until a drawing tool ends. Repeated snap-cursor images are cached, and sketch pauses over half a second leave a bounded local diagnostic log. **Check geometry** is optional; export checks solids automatically. [Reproduction, validation and remaining performance limits](docs/architecture-responsiveness-upgrade/STATUS_REPORT.md#baseline-foundation).

The October 5 responsiveness upgrade adds provisional extrusion visuals while exact geometry runs in a private worker, document indexes, persistent Part Studio history rows, less idle sketch/hover work, and idle recovery file publication. Confirm waits for an exact current result. Native snapshot creation and committed model recomputes still run on the UI thread. [Implementation, measurements and validation](docs/architecture-responsiveness-upgrade/STATUS_REPORT.md#baseline-foundation).

The historical Q03 checkpoint introduced contract **3.0** for lightweight status, explicit geometry checks and stored-shape opening. Local full checks passed 187 native, seven bridge and 22 shortcut cases plus 415 workflow checks. The full GUI sweep retained seventeen passes and the recorded carrier-history exception; the status recipe passed seventeen checks. On the 60-hole plate, the confirmation measured 62.6 ms edit overhead, 19.7 ms idle inspection and about 40 ms open overhead. Changed inspection measured 41.2 ms against its open 20 ms target. [Evidence, reproduction and limits](docs/architecture-responsiveness-upgrade/STATUS_REPORT.md#validation-and-source-versions).

Claude's October 2 review has an [approved update plan](docs/2026-10-02-claude-review-follow-up/UPDATE_PLAN.md), [updated Codex response](docs/2026-10-02-claude-review-follow-up/RESPONSE_TO_CLAUDE.md), [implementation and validation record](docs/2026-10-02-claude-review-follow-up/IMPLEMENTATION.md) and [shortcut inventory](docs/2026-10-02-claude-review-follow-up/UNAVAILABLE_SHORTCUTS.md).

## Launch

Use the repository launcher below for the current checkout. Save and close the previous app first. The earlier interaction update adds modeless tool-first picking, outline-only face hover, selected planes/axes, planar face extrusion and associated sketch Use. [Workflow changes, reproduction and remaining direct-editing limits](docs/architecture-responsiveness-upgrade/STATUS_REPORT.md#baseline-foundation).

The October 5 sketch update supports **highlight an edge, then U** to create linked sketch geometry, including out-of-plane edges. Selecting an edge alone does not change the sketch. For an offset, Ctrl-select a circle center and body edge, press **D**, and place the dimension; starting D first also works. Dimension/constraint references stay outside the extrusion profile. A missing source edge produces a reference error. Rollback is a draggable horizontal line between feature rows, with adjacent feature names instead of a numeric slider. The repository launcher loads this behavior after the previous window is closed.

Earlier local workflow/green-copy launchers and long-run test totals are historical. They are not required by this checkout; use `KurtShape.cmd` or `launch-kurtshape.ps1` here.

The sketch box shows its support plane or face. Use its small **X** to choose another support; **Escape** keeps the current plane, and the header X cancels the edit. Accepting a sketch, extrusion or other feature closes its box. Editing an earlier sketch hides later geometry until Finish/Cancel. History supports **Shift-click** ranges, **Ctrl-click** independent selections, and **Delete** for the selected set. Selecting an origin/datum plane highlights it in the view; rolled-back features appear gray and italic.

Sketch dimensions are black. Free points are blue and fixed points are black; closed sketch regions have a light gray interior. **D** shows a dimension cursor while picking and placing a dimension. Accepted sketches remain visible and selectable until used by a solid feature, and explicit sketch hiding is retained during rebuilds.

The launcher accepts `-RuntimeRoot` (the folder containing `freecad-1.1.4`) and `-SessionRoot` (the profile base). `-Validation` uses `interface-validation` below that base in a hidden process. `-PrintOnly` prints the resolved paths, environment and arguments as JSON without creating folders, changing the environment or starting a process.

Validation sends Qt input to the active modeling view in its own hidden window, including with a fresh profile.

Double-click **KurtShape.cmd** in this directory, or run:

```powershell
.\launch-kurtshape.ps1
```

Save your changes and close any older KurtShape window before launching the updated interface. Already-running processes keep the code they loaded. Startup opens an empty part studio; **Example** explicitly opens the development acceptance plate.

The pinned portable engine is installed under `runtime/freecad-1.1.4`. A fresh Windows checkout requires **7-Zip**, resolved from `KURTSHAPE_7Z`, PATH, or `C:\Program Files\7-Zip\7z.exe`; run `install-runtime.ps1`, then `launch-kurtshape.ps1`. The installer accepts `-RuntimeRoot` for a separate extraction, downloads the pinned official engine and verifies its SHA256 before extraction; no global FreeCAD or Python package installation is needed. Runtime binaries, configuration, app data, temporary material and generated files stay local and are excluded from Git. Use one normal application instance for the default assistant session.

The full acceptance checks additionally use the original STEP/FeatureScript files in the local `Onshape examples` folder two levels above this repository, or at `KURTSHAPE_ONSHAPE_EXAMPLES`. Those source files stay outside Git. Default checks skip the three external real-part tests when the folder is unavailable and omit four opt-in status performance methods unless `KURTSHAPE_PERF=1`. `run-checks.ps1 -Full` requires the originals, enables those four methods and rejects every skip. Launching the app and its included acceptance-plate example does not require them.

## Modeling workflow

1. **New** creates another native part studio without closing existing projects. Press **Shift+S**, then click **Top, Front or Right** in the left history, a visible plane, or one planar model face. A preselected planar face/plane also starts immediately. Face sketches retain native attachment and follow supported upstream face movement.
2. In a sketch, **G** draws a corner rectangle, **R** a center rectangle, **C** a circle, **L** a line and **Shift+S** a point. **D** opens the native dimension tool. The native task pane provides solver feedback, geometry and constraints. Use the toolbar for spline and other tools. **S** opens the context tool palette.
3. **Middle drag orbits**, **Ctrl+middle pans**, **Shift+middle zooms**. Wheel zoom uses SolidWorks direction; double-middle fits. The sketch stays active while orbiting or switching to **3D / Shift+7**. **N** returns normal and pressing it again flips the normal. Ordinary feature selection and parameter edits preserve the camera.
4. **Finish sketch** commits one history step. Failed Finish keeps the draft/editor open with a visible error; repair and retry. **Cancel sketch** restores the accepted pre-edit sketch. **Escape** cancels the current drawing tool or placement without discarding the sketch. **Ctrl+Z/Y** work within a sketch and across completed features. **Shift+G** applies Pierce to a selected sketch endpoint/center and crossing curve edge; **Shift+L** applies Perpendicular.
5. **Shift+E / Extrude** opens depth controls, including directly from an active sketch. **Remove** opens a blind or through-all cut. New extrusions/cuts show an unpickable material preview while depth, reverse and end condition change. Confirm commits the previewed solid; Cancel preserves the model and history. Press **Enter** in the depth field to confirm, or **Shift+Enter** to confirm and repeat with a new profile. Blind cuts honor depth; omitted pocket direction chooses the material side. Reverse explicitly overrides direction.
6. Select a feature to edit dimensions. Quantity fields accept `1/8 in` and `12.7/2`; a separate Formula field supports native references. Numeric replacement of a driven/reference dimension rejects. Double-click sketches to edit; right-click features for editing, visibility, rename and dependency-checked deletion. **New part** starts a separate sketch owner; result operation **New** creates a solid in the shared history; the part chooser selects ownership for new geometry. **Settings** contains mouse navigation, with SolidWorks as the default.
7. **Open / Ctrl+O** accepts FCStd, STEP and STP. STEP import creates a new unsaved project with each solid in a native Body; select a Body to add modeling features. **Ctrl+S** saves as FCStd in your chosen folder through staged replacement, retaining `.recovery.FCStd`. Recent projects and STEP sources persist. Unmanaged FCStd opens for inspection; **Adopt copy** creates a managed copy. **Export** includes all final solids and engine/settings/revision/SHA256 provenance; failed/unrecomputed builds reject. **Recovery** lists verified checkpoints, including unfinished sketches; choose a Save destination after recovery.

STEP import preserves geometry, positions and units while leaving the source unchanged. It does not recover Onshape sketches, dimensions, feature history, product names/colors or assembly relationships. Assembly occurrences become independent solids; non-solid geometry remains as native references and is excluded from solid exports. This is geometry import, not a FeatureScript conversion. [Import behavior and validation](docs/STEP_IMPORT.md).

Managed Part Studios already using `UseHasher=false` open their stored shapes and native flags without a rebuild. A true-hasher managed file migrates once through native recomputation; Assembly reopen and recovery retain their existing solve/reconstruction paths. An engine mismatch, another saved program build, missing engine stamps or missing expected stored shapes require **Rebuild**; retained geometry remains visible, and export stays blocked. Rebuild stamps the current engine in the same undo step, so Undo restores the prior reason. Opening an unrecomputed or failed Part Studio preserves that state instead of silently repairing it.

Ordinary GUI status requests solid count with `measure:false`; volume, area, bounding box and centre of mass stay null. **Check geometry** explicitly checks current solids, shows per-part issues in Messages and caches the verdict until their source shape changes. The status adds “checked” only for a valid cached check. **[ / Measure** requests geometry or full mass properties explicitly. Export requires a current build and a valid geometry check, checking when a current verdict is unavailable. Native flags still report modeling failures during ordinary editing; a `valid` build alone is not a BRepCheck verdict.

Additional controls include measurement (**[**), native select-other at the pointer (**\`**), native feature/sketch copy-paste, construction visibility, section clipping, persisted named cameras and quality settings. [Navigation details](docs/SOLIDWORKS_NAVIGATION.md), [view tools](docs/VIEWPORT_ACTIONS.md), [copy-paste and document tools](docs/general-actions-compatibility.md), [sketch lifecycle](docs/SKETCH_PLANE_CONTRACT.md).

The feature bar directly includes Sweep, Loft, Linear pattern, Circular pattern, Mirror, Plane, Shell, Draft and Boolean. **More** groups **Build, Cut, Modify, Patterns, Reference and Shape tools**, exposing 39 modeling commands; sketch **Geometry, Constraints and Edit** expose 64 commands. Hole is omitted from the default buttons; sheet metal is deferred. Hover icons for names and purposes; compact windows retain toolbar overflow. Inspection/export includes standalone Part solid results as well as Bodies. Typed operations resolve native ownership explicitly. [Modeling refinement, verification and next upgrades](docs/ui-refinement/IMPLEMENTATION.md).

The app owns a consistent light palette for fields, popups and native Tasks, including disabled controls. Save and close a previously running window before relaunching to load appearance changes.

To share errors, open **Messages** at the bottom right and click **Copy all**, then paste the log into chat. Selected log text also copies with **Ctrl+C**. Status and feature-preview messages are selectable; right-click one and choose **Copy message** to copy its full text. The log includes native output emitted during startup.

In a sketch, **Line / L** draws connected segments with successive clicks and stays active until Escape or right-click. **Geometry → Single line** draws separate two-point segments. Finish retains the edit as one Undo step; Cancel discards the current edit. Floating dimensions and notifications use readable application colors even when native controls supply their own style.

## Assembly workflow

Choose **Assembly** in the workspace selector, then **Create Assembly**. **Insert / I** accepts FCStd and STEP/STP files directly. Choose the intended Body or solid; repeat to create independent instances. The first instance is grounded automatically; select another and **Ground** to change the reference.

Ctrl-select a native face/edge/vertex on each of two instances, then choose **Fixed / M**, **Revolute**, or **Slider**. The dialog also allows explicit instance/reference choices; blank reference uses the part origin. Select a revolute/slider joint and **Move** to enter degrees/millimeters. Select a free instance and Move to place it. **Edit** changes joint references/type/name. History context menus rename/remove; dependent instance removal requires cascade. Undo/redo restores the whole command, including placements.

**Ctrl+S** saves the assembly as FCStd; Open restores instances, grounding, joints and solved placements. Export STEP includes all occurrences once at global placement. Parts are embedded geometry snapshots: sources remain unchanged, assemblies relocate without them, and source edits do not automatically update inserted geometry. **Part Studio** returns to an independent modeling document; the assembly stays open in its tab. **J / H** toggles joint visibility. Rejected commands preserve the accepted model and report the problem in the status bar. **Messages** at the bottom right opens retained details; it stays closed until opened explicitly. [Policy, limitations and verification](docs/assembly-workflow/WORKFLOW.md).

## Shortcut coverage

All 126 normalized official Windows default actions/gestures are registered, plus Ctrl+S/N/O local file extensions. Meaning changes by context: Shift+S is sketch creation outside a sketch and Point inside it; Shift+F is edge fillet or sketch fillet. **Shift+/** opens searchable shortcut help; **Alt+C** searches tools.

Registration is complete; equivalence is partial. The first single-level Assembly workflow now implements insertion, grounding and fixed/revolute/slider joints. Nested assemblies, snap/connector tools, advanced mates, drawings, Feature Studio code tools and analysis remain deferred. U2 implements shared Part Studio rollback with the horizontal history marker and its Up/Down context. Pierce is implemented; three other advanced sketch meanings remain unavailable. Six mouse/held-modifier entries remain recorded. Live help shows actual availability and provides **Rebind selected / Reset selected** with context validation. [Complete keymap and sources](docs/ONSHAPE_SHORTCUTS.md).

## Assistant access

The app owns a token-authenticated loopback bridge; only the GUI thread edits models. The default session file is `runtime/assistant-session.json`; when `KURTSHAPE_SESSION_DIR` is set, the CLI uses that folder's session file. An explicit `--session` takes precedence. Do not publish session files.

```powershell
python -B tools\assistant_client.py --json '{"op":"list_documents"}'
python -B tools\assistant_client.py --request-file path-to-request.json
```

Contract 3.0 mutations retain `request_id` and, for an existing document, its current UUID/revision. Identical retry returns the original result; use `request_status` after an unknown outcome. `measure` accepts exactly `false`, `true` or `"full"` and participates in retry identity: omitted defaults to `true`, with volume/area/bounding box; `"full"` adds centre of mass. Validity stays null until an explicit or export check is cached, independently of measurement level. `capabilities` reports these policies and session/retention limits. Native edits, undo/redo and reopen invalidate stale tokens. `preview` evaluates typed modeling operations in a hidden disposable clone; commit checks the base revision afresh. Use `--session path-to-session.json` to select an isolated instance. No actual Claude client has been connected or messaged. [Full contract](docs/OPERATION_CONTRACT.md).

## Reproduce verification

```powershell
.\run-checks.ps1
.\run-checks.ps1 -Full
.\run-checks.ps1 -Full -KeepNativeTemp
.\tools\run_gui_recipe.ps1 -Recipe interface
.\launch-kurtshape.ps1 -Validation
.\tools\run_gui_recipe.ps1 -Recipe part-studio
```

Checks use one suite runner, `tools/run_native_tests.py`, with fresh native, transport, shortcut and modeling-workflow processes. Sessions, profiles and temporary fixtures stay in isolated scratch. Source hashes/STEP geometry are checked when originals are available; `-Full` requires them, runs four status performance methods and rejects all skips. Their raw timings retain missed absolute budgets explicitly; final paired benchmarks decide regression acceptance. `-WriteEvidence` explicitly refreshes tracked reports, and `-Lint` requests an installed ruff. Ordinary checks leave tracked evidence unchanged.

Native document fixtures use exclusive short UUID folders under `runtime/test-tmp`; FreeCAD profiles and app data remain private to each suite. `-KeepNativeTemp` retains suite profiles and receipts, while ordinary per-test cleanup removes disposable document fixtures. Native tests verify source preservation and process/lease cleanup; headless results do not establish GUI behavior. The [status report](docs/architecture-responsiveness-upgrade/STATUS_REPORT.md#validation-and-source-versions) distinguishes the five focused passes and 426 native passes/four opt-in skips retained from S17 from S18's 91 fresh GUI checks.

The performance harness in `tools/perf` measures controller edits, inspection, checkpoints, previews and opens, plus Studio selectors and scope rebuilding. Use isolated sessions with `--fixture plate --holes 60 --repeat 5` or `--fixture studio --repeat 5` for future measurements; enforcement is opt-in. [Supported performance claims and open targets](docs/architecture-responsiveness-upgrade/STATUS_REPORT.md#performance-evidence) are separate from correctness. Ruff is optional locally and pinned in the Windows workflow. S19 does not run native suites or hosted CI.

The blocking GUI runner creates a new private profile for each recipe and requires a fresh passing report. Acceptance also requires an observed native exit and complete owned-worker cleanup. Hosted GUI rendering remains unverified. Existing local CI/green-copy wrappers and their committed continuity records remain in the reviewed project history; their unrelated current working edits are outside the new change set.

Feature Copy compares complete stored feature content, so changing ZIP timestamps during FreeCAD serialization does not make an unchanged source stale. Changes to the copied feature still require copying it again; pasted sketches, extrudes and removals retain editable parameters and existing dependencies.

The validation launcher opens an independent invisible Qt window with a separate configuration/session, exercises the actual interface and viewport, then exits. Reports, screenshots and fixtures default to the printed session evidence folder; add `-WriteEvidence` to refresh historical validation reports. It preserves an already-open user window. Other targeted recipes are listed in [interface pass notes](docs/INTERFACE_PASS.md).

The U2 command launches the isolated Part Studio check; wait for its printed process to exit, then read the printed report path. Its fixture and source-hash assertions remain in the recipe. The [status report](docs/architecture-responsiveness-upgrade/STATUS_REPORT.md) describes current acceptance; detailed historical evidence remains local.

Python networking is denied during offline core checks; native C++ networking and physical disconnection are not instrumented. Exact native rebuilds run synchronously. Automated GUI evidence supplements Kurt's hands-on usability review. Original examples and the Claude reference directory are preserved. Full source conversion remains **0/2**; two edited STEP variants per source design are deferred until Kurt provides them.
