# KurtShape project continuity

Updated October 2, 2026, America/Los_Angeles. Implementation authorized in this chat; **M1 remains incomplete**. Current runnable slice: `Codex/kurtshape`. Prior plans remain in `cadkz-project-planning`; source examples and Claude reference area are preserved in place.

## October 2 Claude review follow-up — implemented app changes

Kurt approved the follow-up and selected Shift+G Pierce, Shift+L Perpendicular and ordinary Ctrl+S/Escape, with analysis/history-bar tools, assemblies/mates, code editing and drawings deferred. [Implementation and handoff](2026-10-02-claude-review-follow-up/IMPLEMENTATION.md) records the completed independent app work: draft preservation/repair, observer caches and command-boundary undo, user folders/start/recent projects, native units/formulas, controller duplication, visible errors, shortcut overrides, contract-2 request identity/isolated preview, shared body ownership, multi-solid export and unmanaged adoption.

New evidence passes: 61 offline native tests, 4 bridge and 22 routing tests; 41 integrated GUI checks, 10 review GUI checks, 25 native clipboard checks and 22 lifecycle stages. Controlled disposable-process crash/reopen recovered native stable autosave and unsaved active-sketch checkpoints, while preserving the saved input. Performance fixtures include 200 native sketches and both original STEP geometries as references. These are not parametric real conversions. Baseline Git commit is `b65f066`; FreeCAD 1.1.4 / OCCT 7.8.1 remains pinned. Impeccable was updated to 4.5.0 with authorization; a verified redundant installer cache was removed during the full-C: incident, and Kurt freed more space. Sources, Claude files and the user's open app were preserved.

Next: save/close older app and relaunch, then Kurt's comfort walkthrough. Actual Claude/MCP shared edits, authenticated source capture, pattern/suppress/split/merge reference tests, physical offline acceptance and real conversions remain open. **M1 stays incomplete; real conversions remain 0/2.** The original assessment below is historical context.

### Original review assessment

Kurt requested an assessment and update plan for Claude's comprehensive app review. The [proposed update plan](2026-10-02-claude-review-follow-up/UPDATE_PLAN.md), [response prepared for Claude](2026-10-02-claude-review-follow-up/RESPONSE_TO_CLAUDE.md) and [assessment evidence](2026-10-02-claude-review-follow-up/REVIEW_EVIDENCE.md) are saved together. The main findings are accepted, with qualifications on preview isolation, quantity/expression handling, observer/undo boundaries, human-selected file destinations and the limits of the current evidence.

Recommended next engineering step: establish an app-scoped Git baseline, then preserve sketch drafts on failed Finish/typed edits before the performance and project-workflow changes. The proposed Claude/Codex ownership split is not assigned. This review request changed documentation only; no app fixes, full validation rerun, Git initialization or Claude message occurred. A small read-only quantity-parser probe confirmed fractional units, arithmetic and the radians/degrees conversion distinction. M1 and source conversion remain incomplete, with real conversion at **0/2**.

## October 2 interface milestone

Kurt requested Onshape-style organization, SolidWorks navigation, default Onshape shortcuts, sketches visible/editable in 3D, Shift+S followed by one face/plane click, persistent left history, and a full functionality pass. These are implemented around the existing FreeCAD 1.1.4 native document. Launch with `KurtShape.cmd`; save and close an older window before relaunching, because it retains the code loaded at startup. The user's already-open process was preserved during validation.

The layout has document and contextual model/sketch toolbars above the native viewport, left origin/feature history and parts, and right feature settings/native Sketcher Tasks. Native drawing tools, constraints, feature dependencies, transactions and persistence remain authoritative. Managed sketch editing now groups completed geometry into one undo step and restores the initial sketch on Cancel even when native `resetEdit` has already committed intermediate commands. Sketch entry preserves the camera, and orbit/normal/isometric views retain the editing session.

Consequential fixes include face/datum attachment, blind-pocket depth and automatic material-side direction, editable unnamed dimensions and radian angle values, exact spline intent detection, live document ownership for placement/feature tasks, native document activation after New/Open, clean modified flags after successful save/reopen, and selection/visibility preservation during refresh/rebuild. Enter applies dimensions/confirms extrusion; Shift+Enter confirms extrusion and waits for the next profile. Native task Close also finalizes the sketch lease. N now handles datum planes and planar faces with repeated flip; Y supports hovered objects. Native built-in PartDesign features have dependency-safe deletion and undo; deletion clears Body.Tip when no solid remains. Scripted/proxy features and unsafe cascade consumers reject. Native feature Tasks guard file/modeling/document-switch actions, including direct shared-adapter New/Open requests.

The shortcut registry contains all 126 normalized official Windows default action/gesture entries and three local file shortcuts. Current backends: 38 native equivalents, 47 official callbacks, 35 explicitly unavailable entries and six passive gestures; the local shortcuts add three callbacks. This is complete registration with partial function equivalence. Assemblies, drawings, Feature Studios, rollback and some analysis/advanced sketch tools are not implemented. Help/search/palette display actual context and availability. Named cameras persist in native metadata; section clipping, quality, construction layers, copy/paste and select-other have separate native GUI evidence.

| Current verification | Result | Record |
|---|---|---|
| Offline core/conversion/sketch plane/projection suite | 47 tests passed | `validation/offline-test-result.json` |
| Transport cancellation/unknown-outcome semantics | 2 tests passed | `tests/test_bridge.py` |
| Qt shortcut routing, text input and context collisions | 21 tests passed | `tests/test_shortcuts.py` |
| Integrated shell, actual keys/plane and face clicks, native tools, bridge, save/reopen and document switches | 36 checks passed | `validation/interface-pass/gui-test-result.json` |
| Native SolidWorks navigation and 3D sketch camera | 16 checks passed | `validation/navigation-test-result.json` |
| Native sketch history/cancel/save lifecycle | Passed | `validation/sketch-lifecycle-result.json` |
| Native feature/sketch copy-paste and document actions, including active-feature switch guard | 25 checks passed | `validation/general-actions-gui-result.json` |
| Native select-other including occluded ray hits | 8 checks passed | `validation/general-actions-select-other-result.json` |
| Construction layers, persisted cameras, clipping and tessellation | 40 checks passed | `validation/viewport-actions-test-result.json` |
| Normal view/flip on all datum planes and a planar face, selected/hovered hide | 20 checks passed | `validation/view-selection-result.json` |
| Native model toolbar and edit guards | 8 scenarios plus 39 guards passed: valid Fillet/Chamfer/Revolve accepted; Mirror/Pattern dialog/cancel smoke; UI and direct assistant operations reject during editing | `validation/toolbar-pass/toolbar-test-result.json` |
| Native light theme, dynamic dialogs, indicators and scrolling menus | 72 checks passed; minimum checked text contrast 4.703:1 | `validation/appearance-pass/theme-result.json` |
| Expanded toolbar, direct menus, compact/narrow overflow, native Tasks and rendered layout | 133 checks passed with 21 screenshots | `validation/appearance-pass/layout-test-result.json` |
| Added native model tools and Tasks without a graphical edit object | 17 scenarios and 48 direct-core guards passed | `validation/appearance-pass/native-model-tools-final-result.json` |

The integrated GUI recipe uses an invisible independent window and separate config/session under `runtime/interface-validation`. Test projects/exports/screenshots are under `validation/interface-pass`; it does not rewrite the original acceptance plate. Actual mouse tests target the active MDI viewport and convert physical bottom-left native pixels to logical top-left Qt coordinates at 150% display scale. An earlier test failure selected an inactive viewport; another compared Windows path separators literally. Both harness errors were corrected. Reproduce with `run-checks.ps1` and `launch-kurtshape.ps1 -Validation`; targeted recipes are in `INTERFACE_PASS.md`.

Source migration remains **0/2**. The mutable Onshape links and deferred edited STEP variants remain the same input gaps. Next step is Kurt's hands-on review of this interface, then authenticated frozen source capture and source-driven conversion work. Do not count the local acceptance plate, synthetic converter fixtures or GUI pass as real-source conversion.

## Consequential decisions

- Selected FreeCAD 1.1.4 native FCStd/Sketcher/PartDesign after a bounded installed probe, before UI code. Exact revision, official archive hash, OCCT version and comparison evidence are in `FOUNDATION_DECISION.md`. Reuse a coherent engine/document; no second editable feature graph, custom geometry kernel or deep fork.
- All assistant requests are typed and revision checked. Loopback transport queues them to the native GUI thread. The panel's drawing/parameter operations use the same controller; native Sketcher edits use the same engine/document and invalidate tokens via intent detection.
- Typed edits are reject-and-rollback on failure. Native GUI edits can leave invalid intent; inspection marks failure and export blocks instead of treating retained geometry as current success. Revisions are opaque new UUIDs for mutations, native changes and reopened sessions, preventing undo/reopen ABA.
- File writes stay within `CADkz/Codex`; native atomic stage/recovery saves, export provenance and bundled runtime/config/temp paths are implemented. Native documents do not depend on absolute source paths to rebuild.
- The supplied examples remain the real M1 fixtures. Pipe has 28 static features/98 compressed queries; hub 145/439 with configurations, loft/surface/revolve/pattern/shell/move-face families. Both STEP files have three valid solids. Full conversion exceeds the first single-body slice. Every supplied source feature is explicitly unconverted.
- The converter currently accepts only a clearly marked normalized **synthetic** schema; raw API normalization and generated FS conversion are not implemented. Whole-source preflight rejects unknown geometry-affecting inputs before creating a document. A runtime feature failure reports the partial native document; whole-import atomic rollback is deferred.

## October 1 foundation evidence retained

| Evidence | Result | Record |
|---|---|---|
| Foundation native solver/solid/persistence/export proof | Passed; fully constrained rectangle and centered hole; one valid solid | `validation/foundation-probe/result.json` |
| Core/conversion/safety tests with Python networking denied | 18 passed; analytic dimensions/volumes, independent boolean residual, meaningful edits, source maps, undo/redo, stale-native-edit rejection, failed-cut rollback, fresh native rebuild/save/reopen/relocation, unknown-source preflight, unrecomputed-native export block, duplicate live UUID rejection, failed export-pair recovery | `validation/offline-test-result.json`; `tests` |
| Transport timeout semantics | 2 passed; queued request cancels before mutation, started operation returns unknown outcome instead of claiming cancellation | `tests/test_bridge.py` |
| Native GUI programmatic walkthrough | Passed two-click operation path, native Sketcher enter/finish, actual viewport mouse callback conversion, pad/cut/save/export | `validation/gui-test-result.json`; screenshots |
| Live Codex CLI against open GUI | Passed actual thickness edit, stale replay rejection, native undo, unauthenticated request rejection | `validation/live-bridge-result.json` |
| Original STEP inspection | 3 valid solids each; coordinates, per-solid mass properties and cylindrical faces recorded; hashes unchanged | `validation/source-geometry.json` |
| Synthetic supported conversion | Both fixtures rebuild natively; plate centered dependency and independent diameter edit work; inch placement correct | `examples/onshape-supported-subset`; converter tests |

Timing values are local observed checks, not speed claims or Onshape comparisons. Python network denial does not intercept native C++ sockets or prove physical disconnection. Exact rebuilding still runs synchronously; queued execution prevents racing revisions but large models may block interaction. No complete latency budget has been established.

## Failures found and corrected

- FreeCAD 1.1.4 constraints expose names through `Constraint.Name`, not a `getConstraintName` method; `getDriving` is invalid for geometric constraints. Adapter now uses actual named constraint data.
- Generic native shape-property string representations include transient memory addresses. Including them caused spurious revisions. Shape caches and Visibility are excluded from intent; native constraints/geometry/links/expressions remain authoritative.
- GUI visibility changes initially caused stale errors between panel operations. Excluding visibility fixed the graphical workflow; explicit native modeling edits still invalidate tokens.
- Compound shapes lack direct `CenterOfMass`; compute volume-weighted solid centroids. No source auto-alignment.
- ExpressionEngine returns paths with a leading dot in this runtime. Numeric mutation rejects expression-driven dimensions after normalizing paths.
- Saving through a `.saving.FCStd` stage with `saveAs` renamed default document labels. `saveCopy` now preserves the native label/identity before atomic replacement.
- Browser reader could not access supplied Onshape workspace pages; no authentication or frozen API capture exists. This is an input/collection gap, not a converter success.
- A second agent reviewed the shared boundary after contracts were established. It reproduced unrecomputed native geometry being labeled current and duplicate live project UUIDs redirecting edits. Both now have regressions: `needs_rebuild` exposes only explicitly retained geometry, and duplicate live copies reject without replacing the mapping.
- A read-only export sidecar initially allowed new geometry to replace the old file before provenance failed. Both outputs are staged; read-only targets reject before commit, successful replacements roll back if their partner fails, and SHA256 detects an interrupted pair. Two-file crash atomicity is not available from ordinary filesystem renames; prior recovery files remain.
- The transport's timeout initially implied an operation had never started even if a long rebuild was running. An atomic queued/started state now distinguishes canceled requests from unknown outcomes; clients must inspect before retrying.
- Native tab close/unmanaged tab switches now clear panel state and cancel drawing; expression-driven parameter fields are read-only. The standard Model/Property docks are hidden to give the KurtShape feature list usable space; native Sketcher Tasks reappear when editing.

## Outstanding M1 gates and next increment

1. Kurt's hands-on graphical creation/edit workflow and preferred shortcuts. The supplied new-part dimensions were proposed; user approval of manufacturing tolerances is still pending. The programmatic UI test is not a completed user walkthrough.
2. Authenticated frozen feature/sketch/dependency capture, link-to-file/revision/configuration binding. User supplied mutable links; hub URL selects `Switch`, agreeing with `main`. Neither frozen correspondence nor active body membership is verified.
3. Real reusable native conversion of both supplied designs (currently **0/2**), beginning with actual source sketch/query/reference semantics and multi-body support. Do not silently replace fixtures or count STEP bases or hand recreation.
4. Critical dimensions plus two matching edited STEP variants per real design. Kurt said he will provide dimension changes later; do not repeatedly ask while independent work proceeds.
5. Baseline bidirectional shape residuals and both edit-reference comparisons after native conversion, plus fresh rebuilding/persistence on those real models.
6. Actual Claude client edit through the shared adapter, physical offline walkthrough and interaction/build timing. No authorization to message Claude was given.

Next engineering step: review the October 2 interface with Kurt, capture actual frozen source representations, and extend one required sketch/reference/multiple-body family against source-driven acceptance. Keep the native document/core boundary and the explicit shortcut/function coverage limits.

## October 2 appearance follow-up

Kurt's follow-up identified inherited white text and sparse toolbars. The app now owns both Qt's light palette and stylesheet, with native Tasks and dynamic widgets included, visible dropdown indicators and readable disabled/placeholder text. Compact native icons and labeled group menus expose 39 model and 64 sketch commands; document viewports fill the central workspace. Current hostile-theme validation passes 72 checks. Loft, Hole, Shell and Draft were accepted as valid native solids in isolated GUI fixtures. The final native feature audit passes 17 scenarios and 48 direct-core guard checks. Part Extrude exposed a direct-core mutation guard gap because its native Tasks have no `getInEdit()` object; core guards now include `Gui.Control.activeDialog()` and verify managed sketch ownership. The current 47 offline tests and 36 integrated GUI checks pass. Reproduction, layout/menu evidence and bounded tool coverage are recorded in `INTERFACE_PASS.md`, `NATIVE_TOOL_CATALOG.md` and `validation/appearance-pass`.

The next user check is the revised contrast, dense toolbar and real editing workflow after saving/closing an older window and relaunching `KurtShape.cmd`. Original source conversions remain 0/2 and the user-deferred dimension variants remain outstanding; appearance/tool exposure does not change those gates.

## October 2 STEP import follow-up

Kurt authorized STEP/STP import after the Claude-review implementation. Open and Recent now route neutral files through `import_step`, creating a new unsaved managed native project with one Body/base per solid and retained non-solid references. Save creates FCStd; source hashes and original geometry/placements are preserved. Provenance persists through native save and current-solid export. Product hierarchy, names/colors, mates and historical sketches/features are not reconstructed. This does not change the **0/2** parametric source-conversion gate. Behavior, recipes and verification are recorded in `STEP_IMPORT.md` and `validation/step-import`.

Next user check: relaunch the app and Open either supplied STEP, select its three parts, add a feature to a selected Body, and Save as FCStd. Native core and real GUI validation are completed before this handoff; frozen source capture and FeatureScript interpretation remain separate future work.
