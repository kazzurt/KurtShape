# October 6 startup and sketch interaction repairs

## October 21 user retest: native overlay input obstruction

Kurt subsequently confirmed that both the endpoint and ghost-control repairs
work in his app and requested commit/push. Publication includes the five sketch
and history fixes and the face-provenance dependency already used by the history
highlighting. Separate launcher/open-file/startup-blank work remains local.
The evidence below records the tested working checkout, including that separate
startup work; its full-checkout source hashes are not a claim that every byte
belongs to this scoped commit.

The staged Python/macros pass Ruff 0.16.10 and Git whitespace checks. Full-tree
lint still reports 16 pre-existing findings in untouched files, retained outside
this change. Two unused QtGui imports were removed from validation macros after
the native runs; production behavior was unchanged. The final staged dependency
audit found no missing modules or launcher dependencies, and no raw runtime,
profile, model, token or log files are included.

Kurt confirmed whole-line Coincident, rollback sketch visibility and history
highlighting work, but endpoint sticking and the ghost controls remain unchanged.
Moving the mouse around eventually releases the endpoint. The earlier midpoint
and floating-QToolBar proofs therefore do not establish a fix for his report.
Investigation now uses a private copy of the latest 17:04 recovery and the
17:05 saved profile. The actual app had exited normally; its log identifies this
main checkout. No live app is launched, controlled or restarted.

Original hashes are retained in
`runtime/sketch-sticking-toolbar-followup-working/original-inputs.json`.
SnapToGrid is explicitly off. The profile still associates Tasks with the native
right-side overlay at size zero. Checking actual overlay widgets and input
routing identified the artifact that the earlier QToolBar fixture missed.
The copied-profile native inventory reproduces a visible `Gui::OverlayTabWidget`
named `OverlayRight` at main-window rectangle `[730,228,352,568]`. It is not
mouse-transparent, and `main.childAt()` at its viewport overlap returns a
`Gui::OverlaySplitter`, not the drawing widget. This establishes an input
obstruction. In copied-profile native run
`sketch-floating-controls/run-083b2b6b6fc344f99b63642a0caf4cc0`, six hit-routed
pending-line positions retain the preceding free endpoint, missing the pointer
by 71–212 pixels. Direct delivery to the drawing widget at the identical pixels
tracks within 0–0.47 pixels; returning to clear canvas releases it within 0.33
pixels. No geometry is changed, and the scene has no mouse-grabber item. Two
other targets naturally invoke sketch inference and are not used for the
near-zero-error causal comparison. The earlier direct-to-GL input tests bypassed
this obstruction entirely. The repair releases native overlays before Tasks
is reparented and covers delayed empty-shell restoration. Verification routes
preview, placement and the following continuous segment through the actual
widget under each requested pixel.

The native integration failure is ownership order: after Tasks has been moved
out of the overlay's splitter, native
[`removeWidget`](https://github.com/FreeCAD/FreeCAD/blob/1.1.4/src/Gui/OverlayWidgets.cpp#L1799)
returns without removing its tab. Native
[`toggleOverlay`](https://github.com/FreeCAD/FreeCAD/blob/1.1.4/src/Gui/OverlayManager.cpp#L468)
has already erased the ownership map entry, so a later Disable All does not
repair the shell. KurtShape now releases native ownership before arranging
Tasks, both at startup and later native-panel layout boundaries. The public
[`ToggleAll`](https://github.com/FreeCAD/FreeCAD/blob/1.1.4/src/Gui/OverlayManager.cpp#L760)
command is called only when tabs exist, matching its native disable branch.
Owned empty `Gui::OverlayTabWidget` shells and their sibling
`Gui::OverlayProxyWidget` reveal strips are hidden initially and on Show/Polish;
content-bearing overlays and other windows are excluded. InputHint is a
status-bar widget and its setting is unchanged. No sketch snapping/cursor code
or modeling operation changed in this follow-up.

Final saved-profile and clean-profile native runs each passed **33 checks**
and exited normally. Both retain all eight formerly obstructed pixels, test
20 further canvas positions through actual Qt hit receivers, commit a native
segment, continue drawing and cover Finish/Cancel/reentry. Native Tasks has
visible enabled contents and remains docked on the right. The native source
hashes match both runs. A focused input regression passed **69 tests** with
no skips and source unchanged. Startup (17), history selection (49) and
reference picking (74) GUI checks also passed against these final sources.
Recovered-model verification passed **269 native checks** in YZ and XZ using
the saved oblique camera. All six strict formerly blocked targets on each plane
track within 0.8 pixels, and routed clicks create solved native lines and continue
drawing. A separate **592-check post-exit audit** validates the original files,
source hashes, all requested targets and actual GL receivers. One ordinary grid
position snaps exactly to Y=0 within the normal nine-pixel inference aperture;
its unconstrained X is unchanged. This local inference is retained, with raw
coordinates recorded. The ghost shells remain absent through tool entry,
Finish, Cancel and reentry, while native Tasks and KurtShape controls work.

The first repair candidate left an eight-pixel native reveal proxy after
Finish; the final predicate covers that paired empty proxy as well. Superseded
and failed diagnostics are retained but excluded from acceptance. The
[verification manifest](evidence/2026-10-21-native-overlay-routing.json) links
every accepted receipt, the before/after routing evidence, original input
hashes and reproduction commands. It distinguishes the 69 focused regression
tests from the earlier full suite, which was not rerun for this UI-only change.
All test processes exited, and the original profile and both recovery files
retain their recorded hashes. Tests used private hidden native Qt windows and
synthetic events delivered to actual hit receivers; they do not measure physical
mouse hardware or display latency. No visible user app was controlled or
restarted.

## October 21 sketch and history follow-up

Kurt approved five scoped fixes, explicitly choosing collinearity when two
whole sketch lines are selected for Coincident. Applies to this main checkout,
FreeCAD 1.1.4 / OCCT 7.8.1. Existing uncommitted launcher and face-provenance
work is retained. No live app/profile/document is changed or restarted.

- `sketch_constraints.py` handles whole-line Coincident through editable native
  solver relations; point selections retain native coincidence. Toolbar/search
  and I share the contextual path. Redundant/conflicting relations restore the
  sketch, including fixed geometry the engine can otherwise silently move.
  An internal line can align to an associated projected line without altering
  its source or binding. Two immutable projected lines reject unchanged.
- A new native reproduction found a pending endpoint fixed to a long line's
  midpoint across a 5%-of-line-length capture region
  ([native snapping](https://github.com/FreeCAD/FreeCAD/blob/1.1.4/src/Mod/Sketcher/Gui/SnapManager.cpp#L330),
  [automatic constraints](https://github.com/FreeCAD/FreeCAD/blob/1.1.4/src/Mod/Sketcher/Gui/DrawSketchHandler.cpp#L465)). The repair limits that
  capture using the existing framebuffer pick aperture. Outside the aperture,
  native object snapping and automatic constraints are temporarily suppressed
  only within the oversized midpoint region, then restored on leaving it,
  navigation, tool exit or sketch exit. This also prevents a click from moving
  the endpoint back through an unintended midpoint Symmetric constraint.
  Exact midpoint, nearby point-marker and ordinary outside-region snapping
  retain the native path. The suppressed region also omits other automatic
  inferences; it does not rewrite geometry after placement.
  Native 1.1.4 names these curve nodes `CurvesLineSetN` and
  `CurvesCoordinateN`. An early synthetic `CurveSetN` fixture passed while
  missing the real preview; the final native fixture uses the actual names.
- `workspace_preferences.py` hides a complete native toolbar on Show/Polish.
  The former synchronous hide could be bypassed by a queued native restore,
  leaving a floating grip and blank action remnants during sketching. The
  private fixture reproduces that race with the lifecycle filter detached and
  verifies suppression when restored. KurtShape bars and other windows' bars
  remain available.
- `studio.py` hides each future sketch after updating Body containers. The
  view-provider property `KurtShapeRollbackVisible` retains the prior flag for
  roll-forward and save/reopen. It is stored in GUI presentation, not model
  intent. Native dynamic-property observation ignores presentation providers.
- `face_history_links.py` selects/current-marks the resolved feature with tree
  signals blocked, preserving the native selected face. Selection changes and
  clearing replace stale rows. The modifier label/badge is removed; a filtered
  result retains Reveal. The exact provenance resolver is unchanged.
  Whole-object echoes of tree selections preserve the actual Qt current row
  and Shift anchor, including a Ctrl-toggled-off current row.

Reproduction uses private sessions with the bundled runtime:

```powershell
.\run-checks.ps1
.\tools\run_gui_recipe.ps1 -Recipe sketch-coincident-lines -TimeoutSeconds 360
.\tools\run_gui_recipe.ps1 -Recipe sketch-midpoint-motion -TimeoutSeconds 360
.\tools\run_gui_recipe.ps1 -Recipe sketch-floating-controls -TimeoutSeconds 360
.\tools\run_gui_recipe.ps1 -Recipe unused-sketch-visibility -TimeoutSeconds 720
.\tools\run_gui_recipe.ps1 -Recipe history-selection -TimeoutSeconds 360
.\tools\run_gui_recipe.ps1 -Recipe face-feature-selection -TimeoutSeconds 360
.\tools\run_gui_recipe.ps1 -Recipe sketch-origin-snap -TimeoutSeconds 360
.\tools\run_gui_recipe.ps1 -Recipe sketch-references -TimeoutSeconds 360
$env:SURFACE_SNAP_VARIANTS = 'top,isometric,side,projected,circle,circle_isometric'
.\tools\run_gui_recipe.ps1 -Recipe surface-snap -TimeoutSeconds 360
Remove-Item Env:SURFACE_SNAP_VARIANTS
$env:SURFACE_SNAP_CONTINUOUS = '1'
.\tools\run_gui_recipe.ps1 -Recipe surface-snap -TimeoutSeconds 360
Remove-Item Env:SURFACE_SNAP_CONTINUOUS
```

GUI acceptance: **640 checks across ten normal-exit private runs**. These cover
Coincident (31), midpoint motion/commit (118), floating controls (12), rollback
and unused sketches (52), history/planes/anchors (49), face highlighting (90),
origin snaps (46), references (74), and all twelve surface/continuous cases
(96 + 72). Focused native classes also pass: constraints 14, snapping 14 and
incremental state 12. [Aggregate receipts and source hashes](evidence/2026-10-21-interaction-fixes.json)
retain the exact reports. The complete frozen-source regression passed all
four suites: **1,068 passed out of 1,073 cases, with five opt-in performance
tests skipped and no failures or errors** (native 955 passed / 5 skipped,
bridge 73, shortcuts 34, workflows 6). The native suite took 2,663 seconds;
its schema-default matrix was substantially slower than the retained prior
252-second baseline but continued producing native artifacts throughout.

A late native probe found that a horizontal/vertical internal line paired
with a matching immutable projected line must reuse the already fixed
direction. Adding a full Tangent instead introduces a redundant direction
equation. The final correction adds only PointOnObject in that case;
the new regression fails against the preceding source and passes against
the isolated candidate in all four axis/selection-order subcases. After the
frozen broad run, the final production source passed the complete 14-test
constraint class and strengthened 31-check GUI recipe, both with normal exits.
Only `sketch_constraints.py` and its test file differ in the two native-run
source manifests; the GUI recipe records matching hashes of all four command
path modules. The aggregate records that source boundary rather than treating
the earlier full sweep as a test of the final correction. Across the full
sweep and final focused rerun there are **1,074 distinct test methods:
1,069 passed and five optional performance tests skipped**.
The Coincident GUI fixture emits a native lost-link warning when Finish
rewinds its edit lease: that artificial source object was created during
the edit, rather than selected from a pre-existing model. Coincident's link
and source preservation assertions pass before teardown. The separate
74-check reference workflow covers normal existing-edge references,
save/reopen and upstream updates.

Verification environment: freeze production sources after the focused GUI
proofs before starting the expensive full sweep. The restricted run reached
its 1800-second suite limit during the operation-schema matrix; its logs are
retained and excluded from acceptance. The complete replacement uses
`tools/run_native_tests.py --require-native --timeout 3600` in a private
unrestricted profile, with `KURTSHAPE_TEST_TMP` set to this checkout's
`runtime/test-tmp`. Native fixture containment requires that standard short
test root; nesting it under a long custom session caused containment and Git
path-length setup errors in an excluded bridge attempt. Independent bridge
confirmation passed all 73 tests with source unchanged. The complete rerun
writes `runtime/sketch-history-native-validation/regression-result.json`;
that run completed normally with source unchanged. Final correction coverage
is recorded separately in
`runtime/sketch-collinearity-working/projected-axis-final/native-result.json`.
The reproducible receipt collector is
`runtime/sketch-history-interaction-verification/collect-verification.ps1`.

An isolated old-source replay fails the new midpoint motion test
at target `(-4,10)`, returning the wrong native preview endpoint `(0,10)`;
that baseline process exited normally. Earlier timeout sessions are retained
and excluded from acceptance. Recipe watchdogs were extended without changing
behavioral/latency assertions. The reference recipe's old empty-sketch Undo
expectation was corrected to the existing documented new-sketch removal contract.
Hidden input establishes native preview
and commit behavior, not physical mouse-to-display latency. The supplied
screenshot is retained in its original location; it is not edited.

The earlier dated evidence below describes previous sources and does not
establish acceptance for these October 21 changes.

Applies to the main `Codex/kurtshape` source and its `KurtShape-workflow-update.cmd` launcher, using portable FreeCAD 1.1.4. The separate green checkout is unchanged. Save and close an older app window before restarting to load these changes.

## Second-point freeze investigation

Kurt subsequently reported that the second line point still freezes, then clarified that moving away from the target immediately unsticks it. This points to target capture rather than a blocked event loop. The earlier cancellation and pick-priority repairs did not resolve it. A newer recovered sketch on a vertical face was inspected through a private copy. That snapshot contains one unconstrained line and no converted geometry; a supported face edge was then converted in the private copy to reproduce the reported workflow. Original current/previous recovery files are retained unchanged.

That conversion reproduced an incorrect target: the endpoint of `Extrude.Edge8` is at sketch-local `(-17.02, 6)`, while an existing internal endpoint is at `(-17.237285, 6.097578)`. They are only about 2.8 logical screen pixels apart at the tested zoom. Clicking directly on the converted endpoint selected the old internal point, producing a native coincidence to the wrong vertex and an error of approximately 0.238 mm. The error occurred with and without the point-priority wrappers, and at apertures of 2, 3, 5 and 9 logical pixels. A one-pixel aperture isolated the intended target. Coin's on-top picking also assigns equal depth to point candidates, leaving traversal order to break the tie. A uniformly small capture range would regress isolated-point snapping; the repair instead chooses the nearest candidate within the normal range.

Starting a new line at that internal point and clicking the adjacent converted endpoint reproduced the reported refusal to finish: the preview returned to the first point, and the click created no segment. The native handler rejected the resulting zero-length line. Moving farther away released it. The nearest-point prototype instead created a 0.2381895 mm segment with a native coincidence at each intended endpoint.

The production fix performs a native `pickAll` query against a cached path to the sketch edit scene before hover and placement events. It projects the original native point hits into framebuffer coordinates, then narrows only the active viewer's pick aperture enough to exclude farther competing points. An isolated point retains the normal capture range. Camera and sketch placement come from the original scene path; support solids are excluded. No proxy geometry, post-placement rewrite or solver call is introduced. The aperture is restored on navigation, leaving the view and tool/edit cleanup. The scene path is located once at tool activation, with no idle scene searches. Regression covers competing points in the same native point set, translated coordinates, original node/index identity, full-range restoration and preservation of external radius changes.

The original repeated-circle regression caught a precision edge case before acceptance: the origin and a circle center have identical sketch XY but native presentation depths of 0.010 and 0.011. At a 35-degree camera angle those markers differed by just 0.00126 framebuffer pixels in distance from the pointer. Treating them as competing targets created a microscopic aperture split that missed both markers and fell back to an axis. The final picker groups identical sketch-local XY and preserves a native tie within 0.1 framebuffer pixels, preventing unusable aperture splits. Real Coin tests cover both coincident markers at different rendering depths and the near-bisector case for distinct points. The original exact-origin assertions are retained.

Final acceptance passed **311 regression cases**, with four optional performance cases skipped, and **426 native GUI checks** on the final source. Those GUI checks comprise surface snapping (168), origin snapping (46), reference selection (74), dimensions/point colors (31), edit state (45), dense-sketch dragging (15), the recovered-model close-point proof (12), and native/cached cursor comparison (35). The independent precision sweep passed another 162 native Coin cases without losing a point hit. All eight accepted GUI processes exited normally with no Python traceback, access-violation or segmentation-fault matches in retained logs. Both original recovery snapshots remain unchanged. [Acceptance/source manifest](evidence/line-endpoint-freeze/acceptance.json), [close-point proof](evidence/line-endpoint-freeze/neighbor-coincident-final-19.json), [cursor comparison](evidence/line-endpoint-freeze/cursor-coincident-final-20.json), [precision sweep](evidence/line-endpoint-freeze/nearest-point-precision-sweep.json) and [regression report](evidence/line-endpoint-freeze/regression.json) retain the results.

The final 61-circle sketch test exercised 150 pending-line movements after the broad regression workload finished. Maximum synchronous input dispatch was **8.13 ms** and maximum event-loop interval was **56.11 ms**; recovery snapshot count remained unchanged while drawing, and the line committed normally. [Motion and lifecycle results](evidence/line-endpoint-freeze/sketch-drag.json) describe synthetic native input, not physical mouse-to-display latency. Reproduce with `run-checks.ps1` and `tools/run_gui_recipe.ps1 -Recipe <name>` for `surface-snap`, `sketch-origin-snap`, `sketch-references`, `sketch-dimension-point-colors`, `sketch-edit-state` and `sketch-drag`. Private-copy replay instructions are in `runtime/line-endpoint-freeze-working/DIAGNOSTICS.md`. `collect_acceptance.py` in that directory validates current source hashes, process exits, logs and original-file hashes before retaining evidence.

The actual toolbar line command is `Sketcher_CreatePolyline`. A hidden production sweep exercised approximately 1,270 second-point movements around 13 targets, including origin, internal endpoints, axes and support-face vertices, with 600 ms dwells at targets. All 13 sequences created one segment. A separate back-normal sweep used 120 ms held clicks. Neither reproduced a multi-second pause. These runs establish model and input-path behavior; hidden event delivery does not exercise the complete Windows pointer/display path.

Native FreeCAD recreates cursor pixmaps while rendering automatic-constraint feedback, including repeated identical appearances. The recovered-model trace recorded over 100 native cursor-change events in about 100 movements. Disabling automatic constraints reduced the number of distinct pixmaps but was used only as a diagnostic comparison; production retains automatic constraints. Qt's Windows cursor cache uses pixmap identities, so newly generated identical images do not reuse that native cache entry. The relevant primary sources are [FreeCAD's drawing handler](https://github.com/FreeCAD/FreeCAD/blob/1.1.4/src/Mod/Sketcher/Gui/DrawSketchHandler.cpp#L936), [native cursor composition](https://github.com/FreeCAD/FreeCAD/blob/1.1.4/src/Gui/ToolHandler.cpp#L184), [Qt Windows cursor handling](https://github.com/qt/qtbase/blob/v6.8.3/src/plugins/platforms/windows/qwindowscursor.cpp#L531) and [Qt window cursor application](https://github.com/qt/qtbase/blob/v6.8.3/src/gui/kernel/qwindow.cpp#L3181). The isolated native log confirms engine commit `4fd3bf320d9566a27e60069fc8387448aaa3a094` and Qt/PySide 6.8.3.

`SketchCursor` reuses a bounded cache of native cursor appearances while a drawing tool is active and the pointer is over the active viewport. It preserves the native pixels, display scale and hotspot, and does not change geometry, constraints or the widget's native cursor. Leaving the viewport, ending the tool, changing focus or opening a modal releases its application override. Foreign cursor-stack entries are preserved. Native cursor events arrive on `Gui::View3DInventorViewer`, whose OpenGL child inherits its cursor; both direct and ancestor changes must refresh the effective cursor immediately. An initial integration test caught a one-move icon lag when only child events were observed. That failed test is retained and the ancestor path is covered by regression tests.

Sketch event-loop pauses over 500 ms now produce bounded local diagnostics at `runtime/diagnostics/sketch-stalls.jsonl` (or the private session directory during validation). A lazy background writer keeps file writes off the modeling thread and rotates at 1 MiB. Records contain timestamps, drawing-command names, event types, viewport-local pointer coordinates and numeric counters; no model geometry or typed text is recorded. Normal movements produce no log file. This preserves evidence after the app closes, unlike the previous short in-memory timing history.

Diagnostic failures remain in the working-session inventory. Run 09 caught a new observer teardown error caused by transient native Qt wrappers; retaining ancestor wrappers and making cleanup idempotent fixed it, with actual overlapping-child destruction covered by regression. Run 16 passed its geometry assertions but emitted a caught native `Access violation` and is excluded from acceptance. Its early log position preceded many later operations; a stage-marked rerun (17) and the final cache comparison (18) exited cleanly. A source ownership audit found no concrete Coin-path lifetime defect. The intermittent native exception's exact trigger remains unconfirmed and is not claimed fixed by the snapping repair. A completed stall can be recorded after the event loop resumes; forced termination while still blocked cannot flush such a record.

Cursor allocation churn is confirmed, but it is not established as the cause of the reported sticking. The user's later clarification and adjacent-point reproduction supersede that initial performance hypothesis. A visible pointer test was requested but has not been approved or run; the target-selection reproduction is possible entirely within a hidden private test. Hidden cache validation explicitly substitutes only the inactive-window/pointer-location guards and records that limitation. The diagnostic macro is `tools/line-endpoint-freeze-validation.FCMacro`; set `LINE_FREEZE_SOURCE` to a recovery file containing `Sketch2`, and use a private validation session/profile. It copies the input before opening it. `LINE_ENDPOINT_CACHE_PROBE=1` selects native/cache comparison. The visible mode remains opt-in through `LINE_FREEZE_VISIBLE=1`; do not enable it without the user's approval. The reproducible hidden launcher and detailed failed/successful-session inventory are under `runtime/line-endpoint-freeze-working/replay-line-endpoint-diagnostic.ps1` and `DIAGNOSTICS.md`.

## Surface-snapping follow-up

Kurt confirmed startup and zoom were correct, but reported stuck line endpoints and circle centers near converted geometry in a straight-on view. A private copy of the latest recovered part was inspected without modifying the original recovery files. Ordinary endpoint placement on that part worked in the initial tests, so those tests alone did not diagnose the report.

The follow-up reproduced a drawing-state mismatch. Native continuous Circle keeps its handler after canceling a pending radius with right-click; native Polyline also keeps its handler after a completed segment. KurtShape cleared its drawing-tool tracker immediately, enabling model-edge picking while the native handler still awaited a point. Near an unconverted model edge the application could then consume the placement click and leave the native drawing preview active. Event processing remained fast in this reproduction: this is a stuck interaction, not evidence of a multi-second blocked event loop.

Plain right-click now explicitly ends the native handler with `Sketcher_StopOperation` before clearing the tracker, as Escape already did. The matching release is consumed by widget and button. Modified clicks and button chords retain the drawing state for navigation; dimension/reference cancellation retains its cursor cleanup.

A separate angled-view defect was reproduced at a converted endpoint: a click four logical pixels away selected an axis and placed the point about 0.57 mm off the intended vertex. Drawing now gives all original native `PointSetN` markers the same pick priority as the origin. This includes converted endpoints and curve centers. Sketcher still creates the native coincidence constraints; no duplicate geometry or per-pointer solver work is introduced. The marker wrappers are installed once at tool activation and removed on tool exit or edit cleanup.

Final acceptance passed **288 regression cases**, with four optional performance cases skipped and zero failures/errors, plus **406 native GUI checks**. These comprise surface snapping (168), origin snapping (46), reference selection (74), dimension/point colors (31), sketch edit state (45), and the private recovered-model cancellation/restart proof (42). The new surface recipe covers top, side, projected and angled face sketches, converted circle centers, continuous Circle/Polyline cancellation, exact native coincidence, geometry counts, and cleanup after right-click, Escape and edit exit. Its largest synchronous pointer dispatch was **13.221 ms** across 18 tool sequences. This timing run completed before the broader regression workload; hidden Qt input does not measure physical mouse-to-display latency.

[Acceptance/source manifest](evidence/surface-snapping/acceptance.json), [surface recipe](evidence/surface-snapping/surface-snap.json), [recovered-model proof](evidence/surface-snapping/recovered-model-lifecycle.json), [right-click baseline](evidence/surface-snapping/lifecycle-baseline.json), [point-priority comparison](evidence/surface-snapping/point-priority-comparison.json), and [regression report](evidence/surface-snapping/regression.json) retain the evidence. All five critical production file hashes match the recovered-model and final surface tests. Both original recovery snapshot hashes remain unchanged. The five final recipe process logs contain no Python traceback, access-violation or segmentation-fault matches.

The first origin regression exposed an overly specific old assertion: a second circle centered on the first origin-anchored circle can now receive a native center-to-center coincidence. Its coordinates were correct, but it no longer necessarily has a direct origin link. The revised regression proves each center has a two-coordinate coincidence path to the origin and that only the two independent radius degrees of freedom remain; changing a radius preserves both centers and the other radius. The failed diagnostic run remains under `runtime/ci-gui/sketch-origin-snap/run-daa4cc162d3346b49940d1c75f2a2ccb` and is not counted as acceptance.

Reproduce with `run-checks.ps1` and `tools/run_gui_recipe.ps1 -Recipe <name>` for `surface-snap`, `sketch-origin-snap`, `sketch-references`, `sketch-dimension-point-colors`, and `sketch-edit-state`. `runtime/surface-snapping-working/collect_acceptance.py` records exact report paths, hashes and original-file checks. Save work and relaunch the main workflow launcher for hands-on validation of the exact reported cursor sequence. The earlier acceptance counts in the following sections describe the earlier source version.

## Findings and changes

- Startup explicitly capped the application at 1440 × 920 and never maximized or moved the restored window to the primary monitor. Startup now assigns the Windows primary screen and maximizes to its available desktop area. Normal window controls and the taskbar remain available.
- A new empty part used the same isometric command that intentionally preserves the current focus and zoom. New parts now get an explicit orthographic camera focused on world origin, with a 100 mm vertical frame. Ordinary orientation changes retain intentional pan/zoom, and existing documents retain their camera.
- Actual native circle placement reproduced the origin problem: at a click offset of (7, 1) logical pixels on the 150% display, the old settings generated only `PointOnObject` to the horizontal axis. The native pick aperture now covers 9 logical pixels, accounting for display scaling. While drawing, the existing native origin point receives Coin's `SHAPE_ON_TOP` pick priority so a nearer axis cannot win in an angled view. Sketcher still authors the real `Coincident` constraint and retains an editable radius. Ending a drawing tool restores native pick order; ending the edit restores the previous preferences.
- A native circle drag reproduced an unselectable old blue circle despite `GeometryCount == 1`. `HistoricalSketchView` forced the ordinary saved-shape provider visible during editing, alongside Sketcher's live geometry. The ordinary provider now stays hidden while its sketch is in edit mode. Its previous visibility is restored when editing ends.
- Native dragging does not publish the moving solver geometry through `sketch.Geometry` until release. The region overlay now hides stale shading during dragging and refreshes it from committed geometry after release. These triangles remain presentation only, never editable geometry.
- Idle recovery previously allowed a synchronous native snapshot after a pause while a drawing tool still awaited its next point. Recovery now defers captures during an active sketch tool or a held mouse gesture. Completed background writes still publish. FreeCAD's separate native autosave is unchanged; this is not a claim that every possible native stall has been eliminated.
- **Check geometry** remains an optional diagnostic of solid validity. Its hover help now explains that export checks automatically. Empty sketches receive a clear “no solids” response; sketch constraints and solver errors are handled by Sketcher.

## Validation and reproduction

New native GUI recipes exercise startup, actual origin snapping, and actual circle dragging/line placement. Existing sketch, presentation scheduling, and navigation regressions protect the surrounding behavior. Run GUI recipes through `tools/run_gui_recipe.ps1 -Recipe <name>`; each launches its own hidden process and private profile. Original user models and the running application are not modified.

The standard regression passed **286 cases**, with zero failures/errors and four explicitly skipped opt-in status-performance tests. Its six modeling workflows contain 415 named assertions. Original supplied STEP geometries and files were unchanged. **Nine native GUI recipes passed 305 named checks**: startup-view (10), sketch-origin-snap (43), sketch-drag (15), sketch-plane-editor (27), sketch-regions (34), sketch-edit-state (45), presentation-scheduling (26), sketch-references (74), and sketch-dimension-point-colors (31).

Final review removed an unnecessary idle retry when the origin marker is unavailable and made drawing-tool activation initialize snapping for a recovered/native-entered sketch. These small follow-up changes passed five focused unit tests and the final 43-check native snapping recipe; the broader regression and other GUI results keep their original source versions. [Acceptance/source manifest](evidence/acceptance-summary.json), [regression report](evidence/regression.json), [GUI receipts](evidence/gui-validation.json), and [final focused test output](evidence/snapping-unit-check.txt) preserve that boundary. No Python traceback/access-violation/segmentation-fault matches were found in the nine accepted GUI processes' retained logs.

The final standalone drag/line recipe exercised 150 second-point moves in a 61-circle sketch. Maximum dispatched-input time was **20.19 ms** and the largest event-loop gap was **130.32 ms**; no half-second stall occurred in that sample. An intentionally eligible recovery checkpoint stayed deferred during a 2.6-second pause at the pending endpoint. These measurements preceded the headless regression workload. The other GUI correctness recipes ran alongside that workload and are not used as a latency benchmark. [Raw motion samples and framebuffer assertions](evidence/sketch-drag.json) retain the actual timings.

Hidden Qt input and framebuffer checks do not measure physical mouse-to-display latency. The reported multi-second line pause was not reproduced, so these results establish the scheduling guard and observed test behavior, not a complete diagnosis of that pause. Native recomputation and native autosave remain possible sources. Startup was checked with both connected monitors; the hidden window proves primary-screen assignment and maximized state, while visible Windows desktop coverage remains a hands-on check.

Reproduce with `run-checks.ps1`, `tools/run_gui_recipe.ps1 -Recipe <name>` for each recipe above, and the bundled Python running `-B tests/test_sketch_snapping.py`. The default regression deliberately omits the four opt-in status benchmarks; `run-checks.ps1 -Full` includes those separately.

## Diagnostic decisions

Increasing the native pick radius alone repaired top-view snapping after accounting for the 150% display scale, but even exact-origin clicks could still select an axis in angled views. Prioritizing the existing native origin marker fixed that depth-order ambiguity. Cursor warping and post-placement geometry rewriting were unnecessary. Empty FreeCAD preference groups return `None` from `GetContents`, which the helper handles. Native scene nodes are explicitly retained until cleanup because resetEdit can detach them before the next UI update.

Fixing region fill alone did not remove the duplicate blue outline: its source was the ordinary saved-shape provider. The final visibility rule only hides that provider while native sketch editing is active, preserving the existing support-picker behavior when editing is temporarily suspended. Native point-color logic was inspected and left unchanged; there was no evidence that its cached calculation caused the reported cursor stall. Qt can recreate screen wrappers on the mixed-DPI desktop, so startup fetches the primary screen after state/handle changes and copies its rectangle before moving the window.

Before/after evidence: [old ghost circle](evidence/screenshots/ghost-circle-before.png), [corrected drag](evidence/screenshots/circle-drag-after.png), and [origin-centered startup](evidence/screenshots/startup-origin.png). Failed diagnostic runs and their originals remain under the private runtime working/GUI-session directories; they are not counted as passing acceptance.
