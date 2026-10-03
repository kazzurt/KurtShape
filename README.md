# KurtShape — local native CAD

KurtShape uses portable FreeCAD 1.1.4, native Sketcher/PartDesign, and OCCT 7.8.1. Editable `.FCStd` is the authoritative model. The October 2 interface pass adds Onshape-style organization, SolidWorks mouse controls, native sketch editing in 3D, face/plane sketch placement, and the complete default Onshape Windows key registry.

**M1 remains in progress. Neither supplied Onshape design has been converted.** Source migration and edited-reference acceptance remain separate from this local modeling implementation. See [project continuity](docs/M1_PROGRESS.md) and [conversion coverage](docs/CONVERSION_COVERAGE.md).

Claude's October 2 review has an [approved update plan](docs/2026-10-02-claude-review-follow-up/UPDATE_PLAN.md), [updated Codex response](docs/2026-10-02-claude-review-follow-up/RESPONSE_TO_CLAUDE.md), [implementation and validation record](docs/2026-10-02-claude-review-follow-up/IMPLEMENTATION.md) and [shortcut inventory](docs/2026-10-02-claude-review-follow-up/UNAVAILABLE_SHORTCUTS.md).

## Launch

Double-click **KurtShape.cmd** in this directory, or run:

```powershell
.\launch-kurtshape.ps1
```

Save your changes and close any older KurtShape window before launching the updated interface. Already-running processes keep the code they loaded. Startup opens an empty part studio; **Example** explicitly opens the development acceptance plate.

The pinned portable engine is installed under `runtime/freecad-1.1.4`. For a fresh checkout run `install-runtime.ps1`; there is no global FreeCAD or package installation. Configuration, app data, temporary material and generated files are kept under this project. Use one normal application instance for the default assistant session.

## Modeling workflow

1. **New** creates another native part studio without closing existing projects. Press **Shift+S**, then click **Top, Front or Right** in the left history, a visible plane, or one planar model face. A preselected planar face/plane also starts immediately. Face sketches retain native attachment and follow supported upstream face movement.
2. In a sketch, **G** draws a corner rectangle, **R** a center rectangle, **C** a circle, **L** a line and **Shift+S** a point. **D** opens the native dimension tool. The native task pane provides solver feedback, geometry and constraints. Use the toolbar for spline and other tools. **S** opens the context tool palette.
3. **Middle drag orbits**, **Ctrl+middle pans**, **Shift+middle zooms**. Wheel zoom uses SolidWorks direction; double-middle fits. The sketch stays active while orbiting or switching to **3D / Shift+7**. **N** returns normal and pressing it again flips the normal. Ordinary feature selection and parameter edits preserve the camera.
4. **Finish sketch** commits one history step. Failed Finish keeps the draft/editor open with a visible error; repair and retry. **Cancel sketch** restores the accepted pre-edit sketch. **Escape** cancels the current drawing tool or placement without discarding the sketch. **Ctrl+Z/Y** work within a sketch and across completed features. **Shift+G** applies Pierce to a selected sketch endpoint/center and crossing curve edge; **Shift+L** applies Perpendicular.
5. **Shift+E / Extrude** opens depth controls, including directly from an active sketch. **Remove** opens a blind or through-all cut. Press **Enter** in the depth field to confirm, or **Shift+Enter** to confirm and repeat with a new profile. Blind cuts honor depth; omitted pocket direction chooses the material side. Reverse explicitly overrides direction.
6. Select a feature to edit dimensions. Quantity fields accept `1/8 in` and `12.7/2`; a separate Formula field supports native references. Numeric replacement of a driven/reference dimension rejects. Double-click sketches to edit; right-click native features for native editing, visibility, rename and dependency-checked deletion. **New Body** and the Body chooser select ownership for new geometry.
7. **Open / Ctrl+O** accepts FCStd, STEP and STP. STEP import creates a new unsaved project with each solid in a native Body; select a Body to add modeling features. **Ctrl+S** saves as FCStd in your chosen folder through staged replacement, retaining `.recovery.FCStd`. Recent projects and STEP sources persist. Unmanaged FCStd opens for inspection; **Adopt copy** creates a managed copy. **Export** includes all final solids and engine/settings/revision/SHA256 provenance; failed/unrecomputed builds reject. **Recovery** lists verified checkpoints, including unfinished sketches; choose a Save destination after recovery.

STEP import preserves geometry, positions and units while leaving the source unchanged. It does not recover Onshape sketches, dimensions, feature history, product names/colors or assembly relationships. Assembly occurrences become independent solids; non-solid geometry remains as native references and is excluded from solid exports. This is geometry import, not a FeatureScript conversion. [Import behavior and validation](docs/STEP_IMPORT.md).

Additional controls include measurement (**[**), native select-other at the pointer (**\`**), native feature/sketch copy-paste, construction visibility, section clipping, persisted named cameras and quality settings. [Navigation details](docs/SOLIDWORKS_NAVIGATION.md), [view tools](docs/VIEWPORT_ACTIONS.md), [copy-paste and document tools](docs/general-actions-compatibility.md), [sketch lifecycle](docs/SKETCH_PLANE_CONTRACT.md).

The feature bar includes Sweep, Loft, Hole, Shell, Draft and Boolean. **Build, Cut, Modify, Patterns, Reference and Shape tools** expose 39 native modeling commands; sketch **Geometry, Constraints and Edit** expose 64 native commands. Hover icons for names and purposes; compact windows retain toolbar overflow. Inspection/export includes standalone Part solid results as well as Bodies. Typed operations resolve native ownership explicitly.

The app owns a consistent light palette for fields, popups and native Tasks, including disabled controls. Save and close a previously running window before relaunching to load appearance changes.

## Assembly workflow

Choose **Assembly** in the workspace selector, then **Create Assembly**. **Insert / I** chooses a saved FCStd file and its intended Body/solid; repeat to create independent instances. For STEP parts, Open STEP and Save FCStd first. The first instance is grounded automatically; select another and **Ground** to change the reference.

Ctrl-select a native face/edge/vertex on each of two instances, then choose **Fixed / M**, **Revolute**, or **Slider**. The dialog also allows explicit instance/reference choices; blank reference uses the part origin. Select a revolute/slider joint and **Move** to enter degrees/millimeters. Select a free instance and Move to place it. **Edit** changes joint references/type/name. History context menus rename/remove; dependent instance removal requires cascade. Undo/redo restores the whole command, including placements.

**Ctrl+S** saves the assembly as FCStd; Open restores instances, grounding, joints and solved placements. Export STEP includes all occurrences once at global placement. Parts are embedded geometry snapshots: sources remain unchanged, assemblies relocate without them, and source edits do not automatically update inserted geometry. **Part Studio** returns to an independent modeling document; the assembly stays open in its tab. **J / H** toggles joint visibility. Native solver failures appear in Messages and rejected commands preserve the accepted model. [Policy, limitations and verification](docs/assembly-workflow/WORKFLOW.md).

## Shortcut coverage

All 126 normalized official Windows default actions/gestures are registered, plus Ctrl+S/N/O local file extensions. Meaning changes by context: Shift+S is sketch creation outside a sketch and Point inside it; Shift+F is edge fillet or sketch fillet. **Shift+/** opens searchable shortcut help; **Alt+C** searches tools.

Registration is complete; equivalence is partial. The first single-level Assembly workflow now implements insertion, grounding and fixed/revolute/slider joints. Nested assemblies, snap/connector tools, advanced mates, drawings, Feature Studio code tools, rollback and analysis remain deferred. Pierce is implemented; three other advanced sketch meanings remain unavailable. Six mouse/held-modifier entries remain recorded. Live help shows actual availability and provides **Rebind selected / Reset selected** with context validation. [Complete keymap and sources](docs/ONSHAPE_SHORTCUTS.md).

## Assistant access

The app owns a token-authenticated loopback bridge; only the GUI thread edits models. The default session file is `runtime/assistant-session.json`. Do not publish it.

```powershell
python -B tools\assistant_client.py --json '{"op":"list_documents"}'
python -B tools\assistant_client.py --request-file path-to-request.json
```

Contract 2 mutations require `request_id` and, for an existing document, its current UUID/revision. Identical retry returns the original result; use `request_status` after an unknown outcome. `capabilities` reports the session/retention limits. Native edits, undo/redo and reopen invalidate stale tokens. `preview` evaluates a parameter/formula in a hidden disposable clone; commit checks the base revision afresh. Use `--session path-to-session.json` to select an isolated instance. No actual Claude client has been connected or messaged. [Full contract](docs/OPERATION_CONTRACT.md).

## Reproduce verification

```powershell
.\run-checks.ps1
.\launch-kurtshape.ps1 -Validation
```

The first command verifies original source hashes/STEP geometry, runs offline native model tests, transport tests and Qt shortcut routing. The second launches an independent invisible Qt window with separate configuration/session, exercises the actual interface and viewport, records screenshots/native files under `validation/interface-pass`, then exits. It preserves an already-open user window. Other targeted native GUI recipes and reports are listed in [interface pass notes](docs/INTERFACE_PASS.md).

Python networking is denied during offline core checks; native C++ networking and physical disconnection are not instrumented. Exact native rebuilds run synchronously. Automated GUI evidence supplements Kurt's hands-on usability review. Original examples and the Claude reference directory are preserved. Full source conversion remains **0/2**; two edited STEP variants per source design are deferred until Kurt provides them.
