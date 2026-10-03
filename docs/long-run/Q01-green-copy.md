# Q01: stable green copy

Started October 3, 2026. Base: 259a61b, longrun/Q00a.

## Scope and touch points

Add RuntimeRoot, SessionRoot and side-effect-free PrintOnly to launch-kurtshape.ps1. Preserve its existing no-argument executable, macro, profile paths, environment and normal window behavior. Validation remains hidden and uses interface-validation below the chosen session base. tools/validation-session.ps1 currently limits validation to the source checkout's runtime; extend only the explicit session-root validation needed for this gate, without allowing a live runtime session. tools/gui-validation.FCMacro is the interface recipe; its baseline Confirm failure occurred after changing depth and before debounce completed. Probe readiness with bounded waits, retaining all assertions.

Add tools/update-green-copy.ps1 resolving the main checkout and sibling from its own script location. Refuse dirty tracked green files, skip a running green FreeCAD, fail closed if process enumeration is unavailable. Add/checkout only a resolved commit; never remove, restore, clean or copy the green tree. Write the authorized sibling KurtShape-green.cmd with RuntimeRoot and SessionRoot both pointing at main/runtime. Audit source-relative runtime/session defaults. No profile format change or operation contract change (2.0).

## Gates and sequence

1. Prove Validation PrintOnly creates no directories/processes and changes no environment; then compare no-argument PrintOnly against pre-Q01 hard-coded paths, and inspect CMD PrintOnly. Parse PowerShell and probe skip/refusal safeguards without touching user processes.
2. Run run-checks.ps1 and exact before/after local tree check. Review full diff, notes and living docs before any commit.
3. A green worktree must contain the committed launcher to accept these new parameters. If needed, land a focused tested Q01 launcher commit, then create its detached sibling and run the actual hidden interface recipe there with main runtime and green private session. This commit is an identified intermediate Q01 commit, not a completed increment; tag only after all gates. Both tracked trees must remain clean.
4. Inspect screenshot, record warnings and small evidence through record_evidence.py, update README/OPERATION_CONTRACT/M1 and this record. Commit final record, tag longrun/Q01, update green copy to the final commit. Preserve the old green copy on any skip/refusal.

Keep the increment small. No benchmark/CI gate applies until Q00b. Budget: private interface process bounded at 15 minutes, scratch disk remains above 20 GiB. No live launch, CMD execution, runtime copy/link, dependency, download, push or profile write.

## Spec adjustments

The current launcher has WriteEvidence from Q00a in addition to Validation; preserve it. Current validation helper accepts only a source-relative runtime; green validation uses its own source runtime so this is already compatible, but a general SessionRoot override must be validated safely. Existing interface is baseline red; any recipe synchronization change retains exact behavioral assertions and is documented separately. Assembly runtime location now comes from App.getHomePath and is already green-copy compatible.

The first interface run passed Confirm and 18 checks, then exposed a latent U2 regression: hide_internal synchronized logical-part visibility even when studio.enabled was false, overwriting a legacy Body/Tip's explicit native visibility. Guard only that logical-part loop by enabled(doc); keep internal hiding and the unchanged GUI assertion. This is a repair of U2's documented legacy behavior, not a new operation or profile format. The full native gate will run on the repaired source.

Recipe assertion edits: three object-property references now use the captured created feature id instead of the obsolete hard-coded Pad id (the GUI creates Extrude). Numeric tolerances, geometry, revision, undo and visibility assertions are unchanged. Two request feature ids and one selection id likewise follow the captured name. A bounded 15-second readiness wait precedes the existing real Confirm click; no forced acceptance or preview flush replaces the click.

## Implementation record: main-source gate

Launcher defaults match pre-Q01 executable/macro/profile paths, quoted arguments and nine environment overrides. PrintOnly returns before filesystem, environment or process mutations. Validation clears inherited demo state, rejects protected folders and reparse components, and uses six isolated environment locations. Updater rejects unknown process inventory, unreadable FreeCAD commands, foreign/linked worktrees and staged/unstaged tracked edits; Git stderr is separate and command-only safe.directory overrides do not alter config. No production source-relative runtime/session path blocks the sibling.

Main interface attempt 1 reached 18 checks and exposed the legacy visibility regression; after the enabled-studio guard, attempt 2 passed all 41 checks. Exact before/after tree SHA256 on the final main source: 8ba4d5e87eabe3df9e6ee4ae6a166c258678fb22a1a718936d26864989ee9be0. Full checks: 147 native, 7 bridge, 22 shortcuts, 6 workflows / 405 checks, 0 skips; source hashes unchanged. Raw reports and recipes remain in runtime/longrun and runtime/test-tmp; small evidence is under validation/2026-10-03-upgrade/green-copy and green-copy-launcher.

Launcher probes passed 13, green guard probes 6, reparse injection probes 8. Each scratch probe initially had one binding/count mistake, logged before correction; production guards were not weakened. Independent review found three issues (Git output separation, linked validation paths, legacy visibility), fixed all; final source review: 0 remaining. Screenshot kurtshape-1200.png inspected. Caught notify Access violation and empty embedded-shape read warnings also occur in Q00a interaction/copy logs; no new warning class found. No clean-native-startup claim. Required sibling interface/CMD/clean-tree gates pending at this intermediate commit.

Green updater attempt 1 refused before mutation because two Git applications were on PATH; select the first application. Attempt 2 created detached ad166e2 and the sibling CMD. CMD/PrintOnly passed four checks. Initial green tree capture hit Windows cross-user ownership; the scratch wrapper adds command-only safe.directory for the two verified roots and keeps the tracked checker unchanged. Both snapshots compared unchanged (main dc0ec7e252631fc451e0c142fe0f9a12212877407642ba1c10e8812f3c80da44, green empty diff hash).

Green interface attempt 1 failed after two checks: a fresh profile had one real visible modeling viewport but QMdiArea.activeSubWindow() was None. The isolated viewport probe reproduced this and verified the exact view widget class/parent. Replace the locator with a scan of this hidden main window for exactly one visible QOpenGLWidget whose parent is Gui::View3DInventorViewer; reject ambiguity. This changes no input or behavioral assertion. Commit this recipe correction before updating green; never edit its tracked files in place.

Green interface attempt2 passed29 checks, then rejected two visible views after New. A fresh two-document probe confirmed QMdiArea active-subwindow exists after 150 ms of Qt event processing even while both views remain visible. Prefer that active-subwindow scope and require exactly one matching visible view inside it; use the single-view main-window fallback only when no active subwindow exists. Wait150 ms after the recipe's New action before the next key. No behavior assertion changed. Final green retry3 follows the committed correction.

## Final green-source gate

Green interface attempt 3 passed all 41 checks at 8ffd421; owned PID26864 exited. Both exact status/diff snapshots remained unchanged, with empty diff SHA256 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855. Both tracked trees are clean. Green screenshot kurtshape-1200.png inspected; earlier selected feature geometry is visible in this fresh-profile view, so screenshot comfort is not an acceptance claim. Kernel, depth, save/reopen, revision/history and actual input consequences remain asserted. Empty embedded-sketch shape warnings match earlier Q00a logs; no new warning class. No normal launch or CMD execution occurred, and no runtime was copied or linked.

| Gate | Result | Raw evidence |
|---|---|---|
| Full final native source | 147/7/22, 0 skips; 405 workflow checks, unchanged hashes | runtime/test-tmp/checks-20261003-145905-4756/evidence/checks/native.json |
| Main interface | 41 passed | runtime/interface-validation/evidence/interface-pass/gui-test-result.json |
| Green interface | 41 passed | ../kurtshape-green/runtime/interface-validation/evidence/interface-pass/gui-test-result.json |
| PrintOnly / updater / reparse / CMD | 13 + 6 + 8 + 4 passed | runtime/longrun/q01-*-probes.json |
| Both local trees | unchanged, empty exact diff hash | runtime/longrun/q01-tree-green-gate-main.json; ../kurtshape-green/runtime/longrun/q01-tree-green-gate.json |

Reproduce main regression with `./run-checks.ps1 -Full`. Reproduce the green interface with `./runtime/longrun/q01-run-interface.ps1 -SourceRoot <absolute-green-root>` (scratch wrapper waits for and records the owned process). The production invocation is `<green>/launch-kurtshape.ps1 -Validation -RuntimeRoot <main>/runtime -SessionRoot <green>/runtime`; wait for its PID and inspect its private JSON. Run the updater with the tagged commit only after the guards pass. For Windows cross-user tree checks the recorded scratch wrapper applies command-only safe.directory to main/green, with no persistent configuration.

Review: three independent findings repaired before launch; subsequent dynamic gates found PATH multiplicity and two viewport assumptions, each logged/fixed before retry. Final changes touch recipe synchronization/lookup and updater executable selection; no additional modeling source changed after the last Full suite. Native tests do not exercise GUI locators; the actual green recipe does. Final evidence is packaged through record_evidence with explicit opt-in; CI, installer extraction, benchmarks and Kurt's comfort acceptance are not claimed for Q01.
