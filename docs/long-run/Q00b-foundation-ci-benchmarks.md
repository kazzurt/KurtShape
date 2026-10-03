# Q00b — CI, GUI recipes, benchmarks and lint

Started 2026-10-03 15:25 America/Los_Angeles. Governing program SHA-256: BFD1820915CDEDE335C2FF421163F1A404E666211402E81DB8E936631D3C2995. Starting commit/tag: 7a20a63 / longrun/Q01.

## Scope and touch points

Implement review brief Increment 0 items 10–15: parameterized installer, runtime-layout and CI scripts, blocking hidden GUI recipe runner, plate/studio benchmark harness and reporter, lint configuration and listed inspection fixes, and binary media attributes. Q00a already supplies isolated environment/process/evidence helpers, the suite runner and exact local tree comparison; reuse them. Keep historical review evidence untouched.

Current touch points: install-runtime.ps1; tools/validation-session.ps1; tools/check-local-tree.ps1; tools/run_native_tests.py; existing tools/*validation.FCMacro and validate-*.ps1; tools/measure_selector_rebuild.py; core.Controller._recompute/timings/checkpoint/dispatch; studio.sync_auto_scopes; selectors.recompute/rebuild_metrics; the brief's historical bench_core.py and bench_gui.FCMacro. New scripts live in tools/ci and tools/perf. Scratch lives in descriptive subfolders of runtime/longrun, ci-local, ci-gui and bench. Living README, OPERATION_CONTRACT and M1_PROGRESS records accompany implementation.

## Contract, adjustments and exclusions

No operation contract change (2.0). U2's 30-feature, four-part, eleven-consumer fixture replaces obsolete single-Body assumptions for the second benchmark; add scoped operations and measure synchronization separately without changing production behavior. Derive suite counts from Q00a: 147 native, 7 bridge, 22 shortcuts, 405 workflow checks; three external skips only when examples are absent. Use the existing Q01 viewport readiness corrections and isolated process helper.

The brief's default install invocation and downloads are forbidden during this run. The cached archive is absent as checked at 15:25; extraction is not run. Verify path/hash/7-Zip guards with inspection and self-contained scratch probes. Ruff is absent on PATH; no install. Apply the named lint repairs by inspection, record lint as not run and ask once in STATUS. Hosted CI cannot run until Kurt pushes; author files and label this limitation. Do not execute git config at any scope: workflow checkout must preserve byte-sensitive files through attributes and checkout configuration rather than a local/global config mutation.

Fresh CI enforces only ignored runtime/ and no other changes; local run-local uses the exact before/after comparison because this checkout contains Kurt's existing ignored media. -SkipNativeTests prevents duplicate suites. Existing recipe baseline carrier-spike is red; keep its assertions and report it separately. Interface is now green (41 checks); use full recipe inventory including U2, not only the brief's stale map. No normal launcher, no live session, clipboard restored by recipes that use it.

Check recorded hashes before attributes: working files may be CRLF while blobs are LF. Preserve bytes matching each sidecar; exclude any extension for which neither matches rather than rewriting fixtures. No formatting churn.

## Gates, budgets and probes

1. Inspect PowerShell syntax and exercise launcher/runner timeout, false-report, missing-report, layout, installer hash and missing-archive guards with controlled scratch doubles. Never extract over the pinned runtime or invoke download.
2. Run run-checks.ps1 -Full and tools/ci/run-local.ps1 -SkipNativeTests; exact status and binary git diff SHA-256 unchanged around gates (except long-run docs). Deliberate scratch negative tree write must be detected and only that newly created file removed.
3. Run both native fixtures with at least five repeats: 60-hole 600×600×12 plate (diameter .45 pitch) and U2 studio plus scoped operations. Record machine, engine, commit, raw samples, median, p95 and worst. All named sections report ok or explicitly unavailable; unavailable required metrics need correction before acceptance. This establishes local baselines; phase0/phase1 targets remain open until later speed increments. Reporter enforces only at ≥60 holes and only with --enforce, applying the program's target AND best×1.2+5 ms rule with confirmation on a second run.
4. Run the full hidden GUI set (third increment), wait for each owned PID, read JSON, inspect screenshots and classify warnings against baseline. bench-gui joins the runner map; restore clipboard where used. Append owned processes to runtime/longrun/pids.txt.
5. Read the full diff independently; address actionable findings. Record small evidence through record_evidence.py, update STATUS/README/OPERATION_CONTRACT/M1_PROGRESS, focused commit/tag longrun/Q00b and update the green copy. No push/CI claim.

## Implementation record

Installer paths derive from RuntimeRoot; archive verification precedes 7-Zip lookup/extraction. PATH lookup selects one Application, with explicit override first. Actual extraction is not run because the cached archive is absent. The final 103 controlled installer/GUI/helper probes passed without network/extraction/real process starts.

The blocking runner covers eighteen recipe names, uses a unique session and bytecode bootstrap, records the exact owned PID, checks declared exit status and a freshly written exact boolean report, and restores all eighteen changed environment variables including absent entries. Startup diagnostics use exactly three ordered markers in their fresh native log. No existing macro assertion changed. The historical carrier assertion remains a declared baseline failure.

The crash recipe requests exit 23 but the first full GUI attempt returned abnormal native termination 0xC0000409 after writing its passing report. The brief requires owned-process exit and a passing report; the new runner's exact-23 assumption was an added restriction. Recovery alone accepts exactly those two crash statuses, conditioned on a fresh producer PID match and mandatory independent native verification in the same private profile. Verification checks checkpoint reopening, draft preservation, explicit Cancel, 1800 mm3 unsaved geometry, original-file SHA256 before and after, and reopening the saved original at 1200 mm3. A fresh verifier PID and timestamp bind that proof to its owned process. Exit 0, all other statuses and incomplete proof are rejected. The Python helper gains optional PassThru and a bounded timeout with owned-process cleanup; existing calls retain their defaults.

The old crash log also reported abnormal termination, but its actual exit was not recorded. A minimal empty-window os._exit(23) probe returned 23; a Sketcher diagnostic stopped before its marker because Gui.activeDocument() was not ready and only its owned process was timed out. The recovery termination's cause remains unverified. Native autosave files were absent (the startup interval cannot be changed by ui.start); native autosave reopening is explicitly unverified. The app checkpoint/draft/original-file proof is separate from that limitation.

Full GUI attempt two passed recovery and interaction/startup checks, then STEP saving failed in FreeCAD saveCopy. A native same-profile, same-real-pipe diagnostic confirmed a 217-character destination (224-character stage) fails while a 192-character destination (199-character stage) succeeds. The serializer's internal expanded filename was not observed, so a precise MAX_PATH mechanism is unverified. The runner's session basename is shortened to run plus a full random UUID; recipe folders remain descriptive, uniqueness is checked, and PID/time remain in reports. Production save and every STEP assertion stay unchanged.

CI layout uses bundled Python and verifies engine, home and Assembly files. Local checks preserve the checkout's existing ignored files by exact before/after comparison; fresh hosted CI allows only ignored runtime/. Native rejection fixtures use a genuinely ungranted existing parent and self-remove their scratch. Performance cache saves use a unique run/attempt suffix and restore the latest platform prefix, so repeated nightly runs at one commit can retain improved minima and both plate sizes. Ten controlled CI probes plus the actual four runtime checks passed. On Windows, setting an environment variable to null left an empty entry; finally blocks now explicitly remove previously absent entries.

Benchmark timing captures record events rather than slicing the bounded 512-entry deque. Auto-scope synchronization is wrapped temporarily and restored in finally. Repeated plate additions start from the completed fixture and undo twice outside measurement, verifying the original object set and volume. Native open excludes close time. GUI checkpoints verify the captured revision and hash-verified manifest after timing. Output/live/pinned-runtime guards precede writes; unavailable metrics retain diagnostics and fail required-section acceptance. Reporter enforcement uses finite comparable samples, five repeats, independent confirmation, and target AND best×1.2+5 ms. Hosted cache preserves each metric's minimum and source commit. Forty-one stdlib failure probes passed.

The first smoke failed the brief's Length +=0.5 example on the pinned Windows Quantity API. Assigning Length.Value+0.5 retains the real native edit and transaction. The second smoke correctly rejected an interior strip that split crossed parts; moving the benchmark strip to the outside edge makes scope expansion keep four connected parts. The third smoke passed plate edits/inspection and studio rebuild/edits/inspection, preserving all geometry, scope and query-health assertions. Final fixture baselines and full gates follow below.

Independent review found thirteen actionable CI/benchmark integration issues, all repaired, plus a verifier-helper exception path that could leave an owned process running; the helper now cleans up that returned PID before rethrowing. Runtime probes additionally corrected reserved HOME and exact environment-presence handling. Lint was not run (ruff absent); fifteen existing files received only the brief's named inspection repairs. The now-used Part and sys imports remain. Dispatch rollback rebinding is preserved through caught→exc. No media changed; both export sidecars match raw bytes, STEP blob/worktree are LF and identical, and no attribute extension exception was needed. Packaged benchmark evidence retains fixture, repeat count, run identity and section availability so later comparisons remain reproducible.

### Reproduction

Run run-checks.ps1 -Full, then tools/ci/run-local.ps1 -SkipNativeTests. tools/run_gui_recipe.ps1 -Recipe <name> blocks until its owned process exits and verifies its report. runtime/longrun/q00b-full-gui.ps1 enumerates the full local set; runtime/longrun/q00b-run-benchmarks.ps1 initializes all six private paths and runs plate60/studio with five repeats serially. The short isolated scripts remain beside their raw reports; originals and historical review evidence stay in place. No normal launcher, live profile, runtime extraction, download or hosted CI was executed.

### Evidence and budgets

**Parked after the third failed full GUI gate.** Attempt one rejected recovery's abnormal exit despite valid checkpoint consequences; attempt two reached STEP save and failed at a long native filename; attempt three passed STEP's 19 checks after shortening private session names, then Assembly's fingerprint helper tried to read a nonexistent 264-character BREP path. There is no fourth retry. Existing producer assertions remain intact. The required fix is to bound private native fixture paths, prove the original fingerprint/geometry checks at those paths, and land that blocker before restarting this increment.

| Gate | Result and evidence |
|---|---|
| Full native suites | 147 native / 7 bridge / 22 shortcut, no skips; 405 workflow checks. Source hashes unchanged. runtime/test-tmp/checks-20261003-155654-1488/evidence/checks/native.json |
| Local CI -SkipNativeTests | Passed runtime layout, complete 20-hole benchmark and exact tree comparison. runtime/ci-local/run-20261003-230419-4b7b5201e6d5484c8695230efd20f848/evidence/ci-local.json |
| Controlled script/CI/perf probes | 103 / 10 / 41 passed, private raw reports and recipes in runtime/longrun. Earlier failed probes and every repair retained. |
| Headless benchmark smoke | Third run passed plate edits/inspection and studio scoped rebuild/edits/inspection. Five-repeat 60-hole and studio baselines not run before mandatory parking. |
| Full GUI | First six passed 41/106/20/28/25/lifecycle; repaired recovery, interaction11 and both startup logs passed; STEP19 passed; Assembly failed after7. Carrier and last five recipes were not reached. No full-set pass claim. |
| Visual review | All 34 unique screenshots across attempts inspected; no new warning class. Assembly failure shows empty instances and missing 264-character BREP filename. |
| Final exact tree | Status and binary diff unchanged around final attempt: 3cc35f5c851e861d0d3016091c814374aa4bef2280ad1c3382157bbc5826c353. |
| Independent review | Fifteen findings repaired, zero remaining at source freeze; native long-path limitations subsequently exposed by real GUI gates. |
| Unrun checks | Ruff absent, cached installer archive absent, hosted CI awaits Kurt push; no installation or download. |

Small reports under validation/2026-10-03-upgrade/foundation-ci-benchmarks-parked explicitly distinguish passed native/20-hole gates from the incomplete failed GUI set. The parked branch preserves all code and docs; main and the green copy remain at longrun/Q01. Q02 is eligible from Q00a and proceeds independently. No new profile format or operation contract shipped.
