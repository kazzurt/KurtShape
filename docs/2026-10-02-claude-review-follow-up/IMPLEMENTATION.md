# Review follow-up implementation and handoff

October 2, 2026. Kurt approved the plan and selected Pierce on **Shift+G**, Perpendicular on **Shift+L**, ordinary **Ctrl+S/Escape**, and deferred analysis/history-bar tools, assemblies/mates, Feature Studio code tools and drawings. The independent app work in increments 0–3 is implemented. Source-dependent reconstruction and the human foundation gate remain open; real conversions stay **0/2**.

The app repository starts at `b65f066` (native app and review baseline). The implementation commit is recorded in the local Git log under “Implement native safety, project workflows and assistant contract 2”. FreeCAD is **1.1.4**, revision `4fd3bf320d9566a27e60069fc8387448aaa3a094`, OCCT **7.8.1**. Runtime, credentials, local settings, recovery files and test scratch remain ignored. Original Claude material and Onshape sources remain in place.

## Delivered behavior

- Failed Finish retains the complete draft and lease, reopens Sketcher and displays a persistent error. Repair then Finish works. A rejected typed sketch command restores its pre-command state; explicit Cancel restores the accepted pre-edit sketch. Checkpoint material survives a history/grouping failure.
- Native observers invalidate intent/evaluation. Idle GUI ticks avoid inspection, geometry serialization and BRep validation. Validity is cached per geometry/recompute generation. Typed commands, native commits and mouse releases create undo snapshots instead of each poll.
- Startup creates an empty part studio. Example opening is explicit. Save/export use selected project locations; chosen folders, last location and recent projects persist. Assistants retain folder grants without self-granting access.
- Native quantity fields stage units/arithmetic through the controller; dimensional formulas use a separate native expression operation. Wrong units, cycles and expression-driven numeric replacements reject. Feature paste is `duplicate_feature`, with native links, fingerprint guards and one undo step.
- Shift+G creates a true native crossing-curve intersection reference and coincident constraint. It follows upstream curve changes. Select a sketch endpoint/center and a crossing edge, then press Shift+G. Perpendicular stays Shift+L. Shortcut help provides validated rebind/reset; palettes follow runtime availability. The remaining unavailable actions were not added solely to reduce the count.
- Contract 2 adds session request IDs/status, replay before stale checking, and bounded isolated parameter/formula previews. The bridge still caps requests at 64 KiB. Expired/cancelled IDs cannot silently execute again; session capacity rejects new IDs instead of forgetting old ones.
- Body ownership is shared across controller/UI. Body choice and New Body are visible. Ambiguous assistant requests reject; target edits infer ownership. Inspection/exports include final Bodies and standalone Part solids. Unmanaged FCStd is inspectable; Adopt copy assigns a new project identity and file, preserving the original and native IDs/links. Proxy/external-link adoption rejects.
- Messages captures native/controller errors. Engine versions accompany export provenance. Native autosave is enabled at one minute; a separate verified native checkpoint every 30 seconds retains unfinished sketch state and its accepted Cancel buffer. Recovery lists available checkpoints; recovered documents require choosing a Save destination.

## Verified evidence

| Evidence | Result |
|---|---|
| [Offline suite](../../validation/offline-test-result.json) | 61 native tests pass with Python networking denied, including 14 follow-up regressions |
| Bridge tests | 4 pass: queued cancellation, started unknown outcome, lookup/replay once, different payload rejection |
| Routing tests | 22 pass, including native input/modal behavior and override collision rejection |
| [Integrated GUI](../../validation/interface-pass/gui-test-result.json) | 41 checks pass, including real quantity input, preview preserving live view/history/modified/file state, loopback replay, body choice and origin ownership |
| [Review GUI](../../validation/review-followup/gui-review.json) | 10 checks pass: actual Shift+G, undo/redo, Shift+L mapping, failed Finish/reopen/repair/Cancel, visible errors, 25 idle ticks with zero hashes/validity calls |
| [Native copy/paste](../../validation/general-actions-gui-result.json) | 25 checks pass, including editable Pad/sketch copies, repeated pastes, undo/reopen, task/document guards and native sketch clipboard |
| [Sketch lifecycle](../../validation/sketch-lifecycle-result.json) | 22 stages pass; real mouse drawing, command-boundary snapshots, native auto-commit grouping, Cancel and staged-save guards |
| [Crash recovery](../../validation/review-followup/recovery-crash.json) | Separate hidden process terminated via `os._exit(23)` after real timers; native stable autosave reopens with unsaved 27 mm³ solid; custom checkpoint recovers unsaved 1800 mm³ plate and unfinished sketch; explicit Cancel restores accepted sketch; original saved file unchanged |
| [Performance fixtures](../../validation/review-followup/performance.json) | 100 warm-inspection samples/case, 20 changed-intent samples/case and 20 parameter commits for native fixtures; runtime/hardware recorded |

The final integrated GUI separates five ordinary UI-feedback samples (p95 **3.456 ms**) from fourteen modeling feedback samples (p95 **173.902 ms**). The combined nineteen samples have p95 **173.902 ms**. These are small hidden-Qt event-to-UI-update samples; they do not measure onscreen/compositor latency or establish a broad 100 ms interaction guarantee. The 200-sketch native fixture had warm-inspection p95 **16.520 ms** and parameter-commit p95 **84.263 ms**. The preserved hub STEP reference had warm-inspection p95 **0.495 ms**; this contains reference solids, not reconstructed parametric hub history. Native recompute, intent, inspection, queue, operation and checkpoint timings are separate. The final plate checkpoint stalled for **227.846 ms**; disk/recovery work has a separate budget from ordinary feedback. Kurt's actual model navigation and edits remain the comfort gate.

Native recovery files were observed under the disposable profile's `user-data/temp/FreeCAD_Doc_…/fc_recovery_file.fcstd` and `.xml`. The active sketch lease produced no native recovery archive in that test. The separate `project-recovery` store recovered it, which is why a saved `.FCBak` alone was not accepted as recovery evidence. Checkpoints retain up to 30 seconds of uncheckpointed work; process interruption during paired replacement is detected by SHA256 and the previous pair is retained.

## Reproduce

Run from the app directory with the pinned runtime installed:

```powershell
.\run-checks.ps1
.\launch-kurtshape.ps1 -Validation
.\validate-review-gui.ps1 -Scenario interaction
.\validate-review-gui.ps1 -Scenario copy
.\validate-review-gui.ps1 -Scenario lifecycle
.\validate-review-gui.ps1 -Scenario recovery
# Wait for only this disposable recovery process to exit (about 75 seconds).
& .\runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\python.exe -B .\tools\validate_review_recovery.py
& .\runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\python.exe -B .\tools\validate_review_performance.py
```

The GUI launcher uses separate profiles and hidden helper windows; it does not attach to or close Kurt's app. Repeating crash recovery in a profile that already has native recovery files may show FreeCAD's recovery dialog; inspect/reconcile that disposable profile first. Runtime artifacts and screenshots are reproducible and ignored; the small JSON results are retained.

During implementation C: filled. One verified, reproducible 418 MB FreeCAD installer cache was removed after confirming the installed runtime remained intact; no source/model/original was deleted. Kurt then freed more space. The authorized Impeccable update completed at **4.5.0**, engine **0.1.11**. Intermediate harness failures included a missing quantity `selectAll`, an outdated stale-replay expectation, and isolated test adapters missing gesture boundaries; these were corrected. An interim hidden GUI run reported a native access exception; fresh startup probes and the final GUI runs did not reproduce it. No original/user process was affected.

## Next gate

Save and close an older app window, then launch `KurtShape.cmd` to load the new code. Kurt's create/edit/conflict-repair/undo/save/reopen/export workflow in his own project folder decides comfort. Record any bad transition and timing. Actual Claude/MCP edits on the shared document, source-backed pattern/suppress/split/merge tests, authenticated source/configuration capture, both real conversions and physical offline acceptance remain M1 work. The proposed Claude/Codex ownership split is documented; no message was sent or work assigned to Claude from this chat.
