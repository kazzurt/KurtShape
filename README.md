# KurtShape — local native CAD

KurtShape uses portable FreeCAD 1.1.4, native Sketcher/PartDesign, and OCCT 7.8.1. Editable `.FCStd` is the authoritative model. The October 2 interface pass adds Onshape-style organization, SolidWorks mouse controls, native sketch editing in 3D, face/plane sketch placement, and the complete default Onshape Windows key registry.

**M1 remains in progress. Neither supplied Onshape design has been converted.** Source migration and edited-reference acceptance remain separate from this local modeling implementation. See [project continuity](docs/M1_PROGRESS.md) and [conversion coverage](docs/CONVERSION_COVERAGE.md).

Claude's October 2 review has a [proposed update plan](docs/2026-10-02-claude-review-follow-up/UPDATE_PLAN.md), [Codex response](docs/2026-10-02-claude-review-follow-up/RESPONSE_TO_CLAUDE.md) and [full unavailable-shortcut inventory](docs/2026-10-02-claude-review-follow-up/UNAVAILABLE_SHORTCUTS.md). These are planning documents; the proposed fixes are not yet implemented.

## Launch

Double-click **KurtShape.cmd** in this directory, or run:

```powershell
.\launch-kurtshape.ps1
```

Save your changes and close any older KurtShape window before launching the updated interface. Already-running processes keep the code they loaded. The launcher opens the editable acceptance plate; it is a development fixture separate from the supplied designs.

The pinned portable engine is installed under `runtime/freecad-1.1.4`. For a fresh checkout run `install-runtime.ps1`; there is no global FreeCAD or package installation. Configuration, app data, temporary material and generated files are kept under this project. Use one normal application instance for the default assistant session.

## Modeling workflow

1. **New** creates another native part studio without closing existing projects. Press **Shift+S**, then click **Top, Front or Right** in the left history, a visible plane, or one planar model face. A preselected planar face/plane also starts immediately. Face sketches retain native attachment and follow supported upstream face movement.
2. In a sketch, **G** draws a corner rectangle, **R** a center rectangle, **C** a circle, **L** a line and **Shift+S** a point. **D** opens the native dimension tool. The native task pane provides solver feedback, geometry and constraints. Use the toolbar for spline and other tools. **S** opens the context tool palette.
3. **Middle drag orbits**, **Ctrl+middle pans**, **Shift+middle zooms**. Wheel zoom uses SolidWorks direction; double-middle fits. The sketch stays active while orbiting or switching to **3D / Shift+7**. **N** returns normal and pressing it again flips the normal. Ordinary feature selection and parameter edits preserve the camera.
4. **Finish sketch** commits the edit as one history step. **Cancel sketch** restores the sketch from before this edit. **Escape** cancels the current native drawing tool, or pending face/plane placement; it does not discard the whole sketch. **Ctrl+Z/Y** work within a sketch and across completed features.
5. **Shift+E / Extrude** opens depth controls, including directly from an active sketch. **Remove** opens a blind or through-all cut. Press **Enter** in the depth field to confirm, or **Shift+Enter** to confirm and repeat with a new profile. Blind cuts honor depth; omitted pocket direction chooses the material side. Reverse explicitly overrides direction.
6. Select a feature in the left history to edit its driving dimensions in the settings pane. Press Enter in a value field or choose **Apply dimension**. Expression-driven/reference dimensions remain read-only. Double-click sketches to edit; right-click native solid features for **Edit feature**, visibility, rename and dependency-checked deletion. The parts list selects the resulting solid.
7. **Ctrl+S** saves a native project through staged replacement, retaining `.recovery.FCStd` for the previous file. **Ctrl+O** opens a managed native file. **Export** writes STEP/STL with settings, source mapping, revision and geometry SHA256. A failed/unrecomputed build cannot be exported as current geometry.

Additional controls include measurement (**[**), native select-other at the pointer (**\`**), native feature/sketch copy-paste, construction visibility, section clipping, persisted named cameras and quality settings. [Navigation details](docs/SOLIDWORKS_NAVIGATION.md), [view tools](docs/VIEWPORT_ACTIONS.md), [copy-paste and document tools](docs/general-actions-compatibility.md), [sketch lifecycle](docs/SKETCH_PLANE_CONTRACT.md).

The feature bar now includes Sweep, Loft, Hole, Shell, Draft and Boolean, alongside the existing tools. **Build, Cut, Modify, Patterns, Reference and Shape tools** menus expose 39 native modeling commands, including circular patterns, helix variants, datum geometry and binders. While sketching, **Geometry, Constraints and Edit** menus expose 64 native sketch commands. Hover an icon for its name and purpose; compact windows retain access through the toolbar overflow menu. Shape tools identify standalone results outside the active Body; the current assistant/export subset remains scoped to the managed Body.

The app owns a consistent light palette for fields, popups and native Tasks, including disabled controls. Save and close a previously running window before relaunching to load appearance changes.

## Shortcut coverage

All 126 normalized official Windows default actions/gestures are registered, plus Ctrl+S/N/O local file extensions. Meaning changes by context: Shift+S is sketch creation outside a sketch and Point inside it; Shift+F is edge fillet or sketch fillet. **Shift+/** opens searchable shortcut help; **Alt+C** searches tools.

Registration is complete; function equivalence is partial. Assemblies/mates, drawings, Feature Studios, rollback, analysis tools, and a few advanced sketch constraints remain explicitly unavailable. Six mouse/held-modifier entries are recorded without claiming exact Onshape gesture equivalence. Native equivalent tools can use different selection flows. The live help reports actual availability; unsupported keys identify the missing action instead of invoking an unrelated command. [Complete keymap and sources](docs/ONSHAPE_SHORTCUTS.md).

## Assistant access

The app owns a token-authenticated loopback bridge; only the GUI thread edits models. The default session file is `runtime/assistant-session.json`. Do not publish it.

```powershell
python -B tools\assistant_client.py --json '{"op":"list_documents"}'
python -B tools\assistant_client.py --request-file path-to-request.json
```

Every mutation uses the current document UUID and opaque revision. Native edits, undo/redo and reopen invalidate stale tokens. Requests queue on the GUI thread; managed sketch sessions guard unrelated modeling and file operations. Use `--session path-to-session.json` when explicitly selecting an isolated instance. This is a shared local adapter, not an installed MCP integration. No actual Claude client has been connected or messaged. [Full operation contract](docs/OPERATION_CONTRACT.md).

## Reproduce verification

```powershell
.\run-checks.ps1
.\launch-kurtshape.ps1 -Validation
```

The first command verifies original source hashes/STEP geometry, runs offline native model tests, transport tests and Qt shortcut routing. The second launches an independent invisible Qt window with separate configuration/session, exercises the actual interface and viewport, records screenshots/native files under `validation/interface-pass`, then exits. It preserves an already-open user window. Other targeted native GUI recipes and reports are listed in [interface pass notes](docs/INTERFACE_PASS.md).

Python networking is denied during offline core checks; native C++ networking and physical disconnection are not instrumented. Exact native rebuilds run synchronously. Automated GUI evidence supplements Kurt's hands-on usability review. Original examples and the Claude reference directory are preserved. Full source conversion remains **0/2**; two edited STEP variants per source design are deferred until Kurt provides them.
