# Workspace behavior follow-up — October 2, 2026

This follow-up to `cb96ddf` uses FreeCAD 1.1.4 (`4fd3bf320d9566a27e60069fc8387448aaa3a094`), OCCT 7.8.1. It addresses Kurt's startup Messages panel, direct assembly STEP insertion, floating sketch text and persistent Line tool. Original source files and the user's modeling instance remain untouched.

## Changes

Messages starts hidden and opens only through its bottom-right button. Closing it is respected through later errors. Explicit application failures retain red status text and log details; the button indicates unread entries. Native Report view output is retained without interpreting every information/warning/log fragment as an application error or overwriting the current status. Native automatic Report view opening is hidden by an application event filter; OutputWindow preferences are preserved. Mirroring uses native text-document insertion positions, avoiding Unicode offsets and duplicate surviving lines after Clear/front trimming. The startup status label uses `addPermanentWidget`, eliminating the invalid permanent-widget index warning.

Assembly Insert accepts FCStd, STEP and STP directly, including uppercase extensions. STEP solids become explicit Solid1/Solid2/etc choices, with child locations retained and non-solid references excluded. The existing typed operations, request replay and immutable same-document geometry snapshots remain authoritative. Sources are copied and hash checked before native reading, and unchanged at completion; bad/source-changing reads roll back. Hidden source documents close on every path. Read-only candidate inspection preserves active document, camera, exact selected subelements/picked coordinates and unsaved state. Repeated occurrences of one source revision/solid share an embedded snapshot and have independent identities/placements. Assemblies reopen without the original STEP.

Line toolbar and L use native Polyline for connected segments: each click continues drawing, Escape/right-click ends the tool. Geometry also exposes Single line for independent two-point segments. Native continuous-creation mode is enabled only while activating Line handlers, then the original preference value or absence is restored. Native handlers retain the activation setting; no synthetic geometry/transactions are introduced. Finish, one Undo/Redo, and Cancel retain the managed sketch lease semantics.

Floating native quantity controls and notification labels can carry local CSS which overrides application palette/CSS. The app now owns their local foreground/background/selection colors. Input styling is scoped to spin boxes/line edits beneath `Gui::View3DInventor`; Tasks, ordinary tooltips and other native controls retain their existing treatment. Styles for newly shown/polished controls are deferred one event-loop tick with a native-wrapper validity check to avoid rebuilding children during construction. Geometry, font sizing and native layout remain native.

## Reproduction and evidence

Run from the repository:

```powershell
.\run-checks.ps1
.\tools\validate-messages.ps1
.\tools\validate-assembly-step.ps1
.\validate-sketch-behavior.ps1 -FreshProfile
.\validate-review-gui.ps1 -Scenario interaction
.\validate-review-gui.ps1 -Scenario step
.\validate-review-gui.ps1 -Scenario assembly
```

GUI launchers return the PID of their own hidden native process with a project-local profile. Read the resulting JSON after that process exits; launch alone is not success. Editable fixtures, screenshots and profile files remain reproducible ignored working materials.

Full regression passed 92 offline native tests, 4 bridge tests and 22 shortcut tests. After the source-loading GUI-state fix, all 19 native Assembly tests passed again, including direct use of both original three-solid STEP files, transformed nested solids, rejected references/invalid reads, replay/undo and portable save/reopen after source deletion. The original source hashes and geometry remain unchanged.

Production GUI evidence: `validation/messages-behavior/gui-result.json` (22 checks), `validation/assembly-step-import/gui-result.json` (35 checks), `validation/sketch-behavior/native-behavior.json` (28 checks), and the existing interaction (10), STEP (19) and Assembly (58) reports. Checks use actual toolbar/file/part-picker events, native geometry and rendered text, rather than just setting properties. The floating-text test deliberately installs white-on-white local CSS on actual native controls and verifies dark glyphs after Show; native long notification layout is measured for clipping. The two floating fields render 37/39 ink pixels and the notification 5,069, with all three native control sizes unchanged. The notification's measured 218 px rich-text height fits its 218 px contents rectangle. The final guarded styling run used a fresh isolated profile and exited cleanly. See `SKETCH_VALIDATION.md` for the retained baseline and native diagnostics.

## Limits and next step

Kurt identified the unreadable message as floating over the drawing area. Plane/axis hover and sketch editing did not reproduce its exact original text. Actual floating dimension controls and the parentless native notification surface are covered; identifying one of these as the exact original popup remains an inference. One reused diagnostic profile encountered native startup access violations; a fresh isolated profile and the guarded styling recipe are used for final validation. No native-layout resize is needed for the measured notification content.

Save, close and relaunch KurtShape to load this code, then check the floating message during actual sketching and direct STEP insertion through Assembly Insert. This increment does not change the 0/2 historical FeatureScript/parametric conversion gate or implement nested assemblies. Larger upgrade priorities remain named variables/configurations, imported-part editing, expanded feature-edit previews and shared assistant operations.
