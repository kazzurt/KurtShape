# Onshape workflow update — October 4, 2026

This update targets Kurt's reported daily modeling friction on portable FreeCAD 1.1.4 / OCCT 7.8.1. It preserves the existing light Qt interface, native FCStd dependency graph, original source files and open user process. The older green checkout remains separate. After saving and closing the previous instance, `Codex/KurtShape-workflow-update.cmd` launches the updated main source using the existing local runtime and profile.

## Behavior and decisions

### October 5 — sketch presentation and unfinished profiles

Driving, reference, expression-based and inactive dimension annotations use black. Sketch points use blue while free and black when fixed. The point presentation adapter handles fixed centers/endpoints in otherwise free curves without changing constraints. Native geometry errors remain red; selection and preselection keep their distinct highlights.

Closed defining sketch regions have a transient light gray fill, including holes and separate regions. The fill is unpickable and leaves native geometry, constraints, `MakeInternals`, history and exported geometry unchanged. Geometry changes invalidate a cached mesh and rebuild it after a short coalescing delay; idle ticks do not rebuild faces. Hidden sketches and geometry after the active history boundary remain hidden.

Pressing **D** supplies a dimension cursor both before selecting references and while placing a native dimension. Escape, right-click, another tool and Finish release it. Completed unused sketches retain visible containers and remain selectable. Profile/path consumption is determined through native feature properties and binder links; attachment or projection references alone do not consume a sketch. Explicitly hidden sketches are not re-shown on each rebuild, and Finish restores visibility only for the accepted unused sketch.

Validation uses independent hidden native processes. Final acceptance passed **261/261 regression cases** with unchanged source and **354 GUI checks**; [reports, screenshots and editable fixtures](../../validation/sketch-presentation/acceptance-summary.json) retain exact reproduction sessions.

Pinned FreeCAD 1.1.4 limitation: `getGeometryWithDependentParameters()` returns the start-point identifier for dependent start, end and center entries ([native implementation](https://raw.githubusercontent.com/FreeCAD/FreeCAD/1.1.4/src/Mod/Sketcher/App/SketchObject.cpp)). Single-point geometry and wholly fixed geometry are unambiguous. The adapter proves individual fixed endpoints through active X/Y, Block, coincidence, horizontal/vertical and point-symmetry relations. An endpoint fixed only through unsupported indirect angled-distance/tangent relations can remain blue when the other endpoint is free. Unknown states stay blue; the adapter does not move geometry or run extra solves to guess. Constraint/dependency changes invalidate its cache, and native error/highlight colors remain intact.

Reproduce the new checks with `tools/run_gui_recipe.ps1 -Recipe sketch-dimension-point-colors`, `-Recipe sketch-regions`, and `-Recipe unused-sketch-visibility`. The existing `sketch-references` recipe also verifies the cursor for D with and without preselection, native placement, Escape, right-click, switching tools and Finish.

### October 5 — sketch editing and history follow-up

The compact sketch editor now contains the current plane/face field and its removal control. Clear the field, select a prior plane or planar face in the history/viewport, and native Sketcher resumes on that support with local sketch coordinates and constraints preserved. Escape keeps the current support; the header X cancels the complete edit. The original support remains native until a valid replacement is selected. A managed edit lease spans the temporary native editor closure needed to release FreeCAD's selection gate. Plane changes participate in draft Undo/Redo, Finish, Cancel and FCStd persistence.

Successful sketch, extrusion and typed feature acceptance closes the editor. Explicit history selection can reopen properties; ordinary inspection refresh cannot reopen an accepted panel. Earlier sketch editing temporarily displays geometry only from before that sketch in shared history, then restores the original visibility on Finish/Cancel. The same history boundary rejects future projection/support inputs, including independent later parts. Editing does not move the persisted rollback marker or native Body Tips.

History uses inclusive Shift range selection and Ctrl toggles, retains selected rows across refresh, and deletes the selected set in one native transaction. Unselected dependent features are listed before cascade deletion. Selected origin/datum planes receive temporary native viewport highlighting. Rolled-back rows use gray italics without a text suffix. Native Sketcher solver state controls blue unconstrained, black constrained and red invalid geometry without applying a whole-sketch constraint shortcut.

Reproduce with `tools/run_gui_recipe.ps1 -Recipe sketch-plane-editor`, `-Recipe history-selection`, and `-Recipe sketch-edit-state`, plus `run-checks.ps1 -Full`. These use isolated hidden FreeCAD processes with the production timer and Qt interactions; screenshots and native solver pixel samples accompany their reports. Final acceptance details are recorded in the project continuity entry.

- SolidWorks mouse gestures remain: middle orbit, Ctrl+middle pan, Shift+middle zoom. Native Classic Trackball uses screen yaw/pitch instead of a rounded arcball's incidental roll. The orbit pivot uses picked geometry with a model-center fallback. Physical comfort/sensitivity still needs Kurt's feedback.
- Hovered faces receive transient, depth-tested boundary lines, including inner wires. Native preselection remains available to shortcuts. Clicking retains native filled selection. The overlay changes no BRep, document properties or view-provider colors and clears on leave, recompute and document close.
- Fillet, Chamfer, Shell and other typed feature tools use a modeless right-side dock. Start the command, click geometry, inspect a disposable preview, remove references if needed, then Confirm. Cancel changes no authoritative feature/history. Confirm checks the source document and revision. More-menu entries use the same typed tools as the toolbar.
- Plane creates a native attached offset plane from Top/Front/Right or a selected datum/planar face. The plane remains selectable in history for sketches and Mirror; its signed Offset is editable in normal feature settings.
- Mirror selects an existing plane/planar face. Revolution selects a straight profile/model edge, including construction lines. Native references follow upstream edits. FreeCAD's lowercase `edgeN` sketch references include construction geometry; uppercase `EdgeN` result shapes omit it. Mirroring uses an attached native driver to handle arbitrary datum names and Body placements correctly.
- Extrude accepts a planar face directly, or a sketch. Face extrusion supports a finite distance, direction and New/Add/Remove/Intersect result operation. Face Remove defaults inward. Through-all/up-to-face remain sketch extrusion modes.
- Move face supports signed offsets of parallel planar faces whose neighbors are perpendicular planes or cylinders parallel to the normal. It explicitly rejects tapered, filleted and nonplanar cases. General face translation/rotation and adjacent-surface extension/retrimming remain future work.
- While editing a sketch, select source edges and press U / Use. Native defining external geometry projects onto the sketch plane, remains associated and participates in a closed profile. Hidden native ShapeBinders bridge FreeCAD's same-Body restriction. Finish groups the edit as one undo step, including its new helpers; Cancel restores the prior sketch.
- Adapter metadata uses document-wide Global link scopes. Managed older files migrate the history order, selector sources and helper metadata links while retaining their objects. This fixes the reported `KurtShapeProject` scope warning at its source.

## System evidence

This is an extension of the incumbent native Qt visual system recorded in [PRODUCT.md](../../PRODUCT.md) and [DESIGN.md](../../DESIGN.md). [theme.py](../../src/kurtshape/theme.py) remains the source for the light palette, Segoe UI typography, compact controls and explicit readable state colors. The new [FeaturePanel and ReferencePicker](../../src/kurtshape/feature_panel.py) use those shared Qt styles; their modeless 290–440-pixel dock leaves the viewport available for picking. [hover_outline.py](../../src/kurtshape/hover_outline.py) adds a transient blue boundary overlay within the existing selection language. The product and design records are preserved. PRODUCT.md's legacy narrative schema is pre-existing; an optional `$impeccable init` refresh belongs to a separate task.

## Repair continuity

- Private Boolean tool Bodies now carry an explicit native `PartDesign::FeatureBase` whose Global `BaseFeature` input links the authoritative source Tip. The private `Body.BaseFeature` stays empty, avoiding the cross-scope warning after Boolean grouping. Independent checks passed for posed coordinate frames, element maps, upstream edits and fresh-process reopening.
- Body-backed selected revolve axes use a native tangent-attached datum and a finite root `Part::Line` driver, including sketch construction lines. Managed older standalone and internal Revolve links migrate on opening and rebuild immediately without adding a hidden Undo step. Recompute orders source snapshots before Boolean tools; fallback Body Tips are restricted to native features containing solid geometry, preventing transient empty tools and datum Tips.
- Up-to-face Pads own traced native Profile and Stop ShapeBinders within their carrier Body. The selector stays on `Stop.Support` with its original source; Pad consumes the carrier-local `Face1`. Scoped native Pad output uses a manual Global FeatureBase to preserve placement once; root `Part::Extrusion` output keeps its direct native input. Legacy migration removes the old geometry-group membership before reparenting an owned Profile, preserves the carrier Tip, output base name, selector and operation ownership, and leaves Undo count at zero.
- Planar-face Remove keeps its distance field enabled. The workflow GUI recipe edits that field with actual keyboard events and checks the inward result. The shared GUI wrapper supports `view-interaction`, checks freshly written passing reports, and fails both `onshape-workflows` and `part-studio` if their native logs contain link-scope warnings.

The unified targeted repair run passed 54/54 checks in 32.337 seconds with zero skips. Those regressions are included in the final frozen-source acceptance below.

## Reproduction

From `Codex/kurtshape`:

```powershell
.\run-checks.ps1 -Full
.\tools\run_gui_recipe.ps1 -Recipe onshape-workflows -WriteEvidence
.\tools\run_gui_recipe.ps1 -Recipe part-studio
.\tools\run_gui_recipe.ps1 -Recipe extrusion-preview
.\tools\run_gui_recipe.ps1 -Recipe view-interaction
```

Validation runs independent hidden native processes and private profiles under descriptive runtime subfolders. Native tests cover actual geometry, selector renumbering, upstream changes, transaction grouping, cancellation, persistence and fresh-process recomputation. GUI recipes exercise the production Panel and Qt controls; framebuffer captures verify hover versus clicked fill. Four optional timing checks run with `-Full`; physical mouse comfort is outside automated proof.

Final acceptance on October 4: **244/244 regression tests passed, with zero skips**, and the runner verified unchanged source hashes throughout the run. GUI recipes passed 45 workflow checks, 99 Part Studio checks, 20 extrusion-preview checks and 6 view-interaction checks (**170 total**). Both modeling recipes reported zero native link-scope warnings. Independent desktop and compact-frame reviews passed. The original STEP sources remain unchanged and valid, with three solids each.

The [acceptance summary](../../validation/onshape-workflows/acceptance-summary.json) links each independent GUI process/report and records limitations. The [native regression report](../../validation/onshape-workflows/native-regression.json) retains the per-test outcomes and source hash manifest. Failed development probes remain under runtime and are not passing acceptance evidence.

Next step: Kurt tries the interaction update on his actual parts, especially orbit comfort and complex Move face cases. Extend direct editing with a surface retrimming implementation before promising general Onshape Move face parity.

## October 5 — sketch edge references

The sketch editor now picks actual model edges through its viewport event path. FreeCAD 1.1.4 disables ordinary model selection while a sketch is edited, so the previous programmatically selected-edge acceptance did not establish the mouse workflow.

- **Use / U** projects a highlighted or selected edge, or starts repeated edge picking with no edge highlighted/selected. Press U, Escape or right-click to end picking. Coplanar and out-of-plane model edges are orthogonally projected into the active sketch and retain their exact native source links. Historical support sketches no longer take priority over a coincident solid boundary.
- Clicking a body edge while no drawing tool is active selects it without modifying the sketch. Ctrl-select a circle center and an edge, press **D**, then place and enter the dimension; activating the dimension imports the reference. Starting D first also accepts a center and a body edge. Select the center point for center-to-edge distance; selecting the circle circumference uses the native curve-distance behavior. Native constraints consume the same sketch references.
- Automatic dimension/constraint references do not enter the sketch profile. Explicit U creates defining geometry and can promote a previously imported reference without changing its constraint IDs. **Construction / Q** remains the native way to toggle defining geometry out of a profile.
- Native external links are counted individually even when FreeCAD's Python property groups several edges from one source. This fixes same-source selector slots and mixed Use/Pierce indexing. Cross-body references retain the existing hidden native ShapeBinder bridge.
- A native dimension command can commit its transaction while the sketch edit lease remains open. Further managed sketch operations reopen the transaction, retaining source bindings and the grouped Finish/Cancel behavior. Escape explicitly ends a continuous native drawing handler; keyboard constraints and construction toggles record an edit boundary for draft Undo.

The six focused native regressions cover driving face-relative circle offsets, source edits and reopen, a circular pocket without stray reference wires, reference promotion with undo/redo, oblique cross-body projection, grouped selector slots, collapsed point projections, and continuation after native command commits. The reproducible GUI recipe is `tools/run_gui_recipe.ps1 -Recipe sketch-references`; it uses actual viewport clicks and native dimension dialogs in a private hidden FreeCAD process. It passed 45 checks with the production inspection timer running. The normal-view command intentionally flips on a repeated press; the recipe starts from isometric before returning normal so its front-edge expectations are explicit. Final validation results are recorded in project continuity after acceptance.

Final October 5 acceptance passed 250/250 regression cases, zero skips, and 90 GUI checks (45 sketch-reference and 45 existing workflow checks). The final manifest remained unchanged. [Reports, screenshot and editable example](../../validation/sketch-references/acceptance-summary.json) retain the evidence; [project continuity](../M1_PROGRESS.md#october-5-2026--face-sketch-edge-references) records the implementation decisions and corrected development probes.

## October 5 — conversion warning repair and graphical rollback

Kurt's follow-up reproduced `Unmanaged change of Constraint Property results in invalid constraint indices` and empty `Sketch.InternalShape.bin` / `Sketch.Shape.bin` reads. The prior GUI report tested resulting geometry but did not reject these console errors; its retained log contains them. The sketch-reference runner now rejects those signatures in both native and process logs.

FreeCAD 1.1.4's generic object-buffer restore applies properties in alphabetical order outside its document-restoration guard. Restoring constraints before their geometry creates invalid intermediate indices. The shared sketch restore helper clears constraints through Sketcher's native API, restores external and internal geometry before constraints, restores expressions afterward, and omits only zero-byte generated BREP caches so native recomputation regenerates them. Draft Undo/Redo, canceled/rejected edits, grouped Finish, recovery and explicit selector retargeting use the same helper. Native geometry and FCStd remain authoritative.

The viewport highlights a model edge without modifying the sketch. **Highlight or select the edge, then U** creates native defining external geometry linked to that exact source. An ordinary edge selection remains selection-only; dimension and constraint activation creates reference-only geometry when needed. Hover picking is coalesced, cleared on leave/zoom/tool changes, and respects current native point/curve preselection. Stale Sketcher preselection is checked against the actual cursor position so an old center-point highlight cannot swallow a distant edge click.

Use now supplies the exact picked native source instead of a nearest-edge selector. Native mapped references follow supported source edits without searching for a replacement neighbor. FreeCAD can retain a cached defining curve with an external `Missing` flag even when its own sketch state says valid. KurtShape derives a missing-reference build error and feature-history diagnostic from that flag, so the old cached profile cannot silently pass as a healthy model.

Rollback is drawn as a horizontal line between actual feature rows. Drag the handle or click a row boundary; the caption names the features on either side. Dragging previews the position and releasing performs one rebuild. Up/Down, Undo/Redo, rollback insertion and legacy single-Body history retain their native operation path. Later features remain visibly held; the marker is disabled during sketch/feature editing. Repositioning listens to layout/scroll events and does not schedule work from paint events.

Reproduce with `tools/run_gui_recipe.ps1 -Recipe sketch-references`, `tools/run_gui_recipe.ps1 -Recipe rollback-history`, and `run-checks.ps1 -Full`. Each GUI recipe owns a hidden isolated FreeCAD process and preserves an editable fixture, screenshots, timings and a result receipt. Final evidence for this follow-up is recorded separately from the earlier behavior-only run in `validation/sketch-conversion-rollback`.

Final acceptance passed **253/253 regression cases, zero skips**, with unchanged source hashes, plus **257 GUI checks** (67 sketch references, 46 rollback, 99 Part Studio, 45 modeling workflows). The sketch recipe recorded zero native shape/constraint warning matches. Three actual U conversions on the final simple GUI fixture took 51.5, 43.2 and 40.3 ms, excluding artificial waits; native direct-source projection also avoided the former selector-evaluation work. The [acceptance summary](../../validation/sketch-conversion-rollback/acceptance-summary.json) links the retained results, editable before/after source-update examples, and graphical rollback evidence. The earlier full run with a late UI guard edit was rejected by its source-change check and is excluded from acceptance.
