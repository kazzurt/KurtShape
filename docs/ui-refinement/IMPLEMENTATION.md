# Modeling and interface refinement — October 2, 2026

FreeCAD 1.1.4 (`4fd3bf320d9566a27e60069fc8387448aaa3a094`), OCCT 7.8.1. This increment follows the single-level Assembly integration in commit `10c333f`; both conversations used the documented shared-checkout handoff. Original Onshape files and the user's open modeling window were preserved.

## Behavior

New Extrude and Remove tasks preview the actual controller result in a disposable FCStd. The live document gains no preview feature or undo transaction. A transient, unpickable Coin overlay shows added material in blue and removed material in orange. Cut-only depth state makes removed material visible through the unchanged opaque solid; additive geometry keeps normal occlusion. Depth, quantity strings, reverse and blind/through-all conditions update it. Invalid input removes the ghost and reports the reason beside the fields. Confirm commits the same normalized proposal against the preview revision; Cancel, source changes, document switches and task/window closure clear the overlay.

The native quantity field normalizes text when focus moves. Equivalent quantities retain the valid preview so clicking Confirm never disables the button halfway through the click. Save preserves the task and restarts its preview without saving a proposed feature; Undo/Redo/Rebuild close the staged task. A newer assistant/native revision requires restarting the extrusion rather than committing a stale ghost.

Sweep, Loft, Linear pattern, Circular pattern, Mirror and Plane are direct top-toolbar tools. More contains the existing grouped catalog. Hole is omitted from the default buttons, and sheet metal remains deferred. Everyday tool help and feature settings use modeling names. New part creates a separate solid/feature history and gives new parts a Part-number label; it does not insert an assembly occurrence. Plane creates reference geometry; Show planes controls visibility.

Settings contains the mouse-navigation choice. The native NavigationIndicator is hidden, including when constructed after startup. SolidWorks stays the default; explicit choices persist across existing/new/open views, with alternative styles retaining their own gestures. Native view dimensions and notification controls remain in the status bar.

The actual native `Gui::NotificationLabel` had dark text on a black background. A same-size object-specific theme rule and tooltip palette repair existing parentless notifications and future popups. The verified pair is dark ink on white at 12.67:1 contrast; ordinary rich tooltips keep white text on dark blue. A clean-profile surface click itself did not create another popup, so identifying that warning as Kurt's exact reported popup remains an inference.

## Reproduction

From the repository:

```powershell
.\run-checks.ps1
.\validate-ui-refinement.ps1 -Scenario modeling
.\validate-ui-refinement.ps1 -Scenario interface
.\tools\validate-extrusion-preview.ps1
```

GUI scripts return the PID of an independent hidden process and use project-local profiles. Read their JSON reports after the helper exits; never treat launch as success. Editable modeling fixtures remain under `runtime/modeling-workflow-validation`. Screenshots are reproducible generated evidence and remain local.

## Verification and practical limits

- Full regression: 88 offline native tests, 4 bridge tests and 22 shortcut tests passed. Original source hashes/three-solid STEP geometries are unchanged.
- Six modeling fixtures passed 405 assertions: actual feature-pattern count/spacing/extent, plane-driven solid transforms, sweep profile/path edits and loft section edits, dependencies, creation/edit undo/redo, staged save/reopen and fresh rebuild. The known native AttacherEngine display alias after reopen is normalized while authoritative AttacherType and all other object intent fields are compared exactly. See `validation/ui-refinement/modeling-workflows.json`.
- Standalone preview: 5 focused native tests and 20 GUI checks passed, including semantic quantity dedup, cut-only depth state, exact live intent/history/identity/selection/visibility/modified state, acceptance equivalence and cleanup. See `validation/ui-refinement-preview/gui-result.json` and `../ui-refinement-preview/README.md`.
- Notification theme: 17 actual native Qt checks passed, including preexisting/future labels, actual rendered glyphs, unchanged native sizes, normal rich tooltips and unchanged native theme preferences. See `validation/ui-refresh/production-popup-validation.json`.

The integrated Panel report is `validation/ui-refinement/gui-refinement.json`; 106 assertions passed in 15.17 seconds. It exercises actual Qt buttons and scenegraph geometry at 1200/1600 logical pixels, Save/re-edit, stale shared-controller edits, navigation preferences and actual native notifications. Actual Confirm press/release accepts once despite quantity normalization. The removed-volume interior has 625/625 orange pixels with preview and 0/625 after Cancel; complete live state remains unchanged. Native near/far clipping distances adjust to encompass the ghost; camera position/orientation/focus/zoom stay unchanged. Screenshots were visually inspected. Synthetic fixtures supplement Kurt's feel test.

Preview evaluation remains on the GUI thread, with 160 ms debounce and eight cached results. Initial small-fixture evaluations measured roughly 0.5 seconds; cached equivalent values avoid recomputation. Large-part latency is not established. Previewing edits to existing features or tools beyond new Pad/Pocket, curved/subtractive sweep/loft, part/face pattern equivalence and full Onshape parity remain outside this increment. Raw FeatureScript interpretation and real parametric source conversions remain incomplete (0/2); STEP geometry import and the assembly workflow do not change that count.

## Lessons and next step

The first GUI recipe deadlocked its own More-menu inspection until a watchdog because InstantPopup enters a nested event loop. Schedule inspection/closure before clicking it. Programmatic history selection does not reproduce a user's native selection; use actual item clicks. Visual inspection additionally caught a removed volume hidden by the existing solid, which a node-presence test alone cannot detect.

Save and relaunch KurtShape to load this increment, then check actual extrusion/cut preview and surface-selection notifications on Kurt's parts. The next larger upgrades are named variables/configurations, imported-part Split/Transform/Move-face workflows, expanded feature-editing previews, and broadening the shared assistant operations. See `UPDATE_PLAN.md` for scope and official references.
