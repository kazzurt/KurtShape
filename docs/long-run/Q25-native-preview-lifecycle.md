# Q25 — Native preview cache and clone lifecycle

Plan written October 4, 2026 before implementation, on main77af50c (longrun/Q24b).

## Scope and reason

Section9 of the long-run program chooses an open budget once the ordered queue is exhausted. The first-preview median is10403.857ms against50ms, and the preview update median is8942.989ms. This increment establishes a stricter native regression oracle for the already-shipped disposable preview engine. It does not introduce the Q07 live-document engine or restore any parked implementation. Q03, Q09 and Q24c stay parked until their respective separately landed blockers exist; preview LRU behavior cannot prove the absent Q03 memo's mutable-limit transition.

Add five consequential native tests to the existing ExtrusionPreviewTests class. Preserve all five existing methods and every existing assertion. Exercise the fixed eight-result cache with real detached native solids, equivalent unit input, promotion and genuine eviction/recomputation. Exercise actual native dimension and Body-placement changes rejecting stale tasks; clone operation and loader failures preserving the source and unrelated documents; task/source closure and reuse of a native name without granting an old task ownership of the replacement. Record actual initial/final cache inventories, source generations, native evaluation counts, snapshot identity/hash, source/core/native document inventories and retained fixture provenance. No timing benefit will be inferred from these small fixtures.

## Touch points verified on main

- src/kurtshape/extrusion_preview.py: ExtrusionEvaluator._guard/_proposal/evaluate/close, OrderedDict LRU8, hidden saveCopy/openDocument clone, detached shapes, owned transaction and finally cleanup. Generation is sampled before saveCopy; actual generation changes must be recorded, not suppressed to manufacture hits.
- src/kurtshape/core.py: _is_open, sync, managed document registration, observer generations and evaluations; controller operation validation remains the acceptance path.
- src/kurtshape/document_state.py: source invalidation and clone document deletion cleanup.
- tests/test_extrusion_preview.py: five existing registered native methods and isolated_session fixture ownership. New methods use tools/native_validation_snapshot.py's complete strict native snapshot, including owned intrinsic datum content and modeled BRep/hash, history, Tip and revision. GUI availability is reported honestly.
- tests/support.py: exclusive short fixtures, test/PID/environment/directory-identity receipt, redirect-aware cleanup. No test helper changes planned.
- tools/run_native_tests.py: existing class registration and full tests source hash inventory already cover new methods; no new registration required.
- tools/extrusion-preview-validation.FCMacro: current20 checks retain real debounce/overlay/selection/camera/history behavior. No existing GUI assertion change.
- README.md, docs/OPERATION_CONTRACT.md and docs/M1_PROGRESS.md receive short factual validation updates in the finished commit. No atlas behavior ships, so no parity row is warranted.

## Contract and assertions

Contract remains2.0. No operation/profile/serialized model format change is planned. Existing assertions changed: none. New assertions require real correct geometry, genuine native evaluation/hit/recomputation, exact strict source preservation on nonmutating paths, correct revision rejection before new clone work, exact unrelated-document preservation and owned resource cleanup. If a new test reveals a shipped lifecycle bug, record the failed gate and its cause before a bounded implementation correction; never weaken the oracle or restore parked code. Observed generation/refresh and read cache changes are recorded separately from authoritative strict native state.

## Gates and budgets

1. Independent review of the new methods, failure injection boundaries, retained report integrity and cleanup before any native launch.
2. Fresh root-owned isolated run-checks.ps1 -Full -KeepNativeTemp: derive actual method inventory (planned164 native,7 bridge,22 shortcut plus405 workflow checks), zero failure/error/skip, exact source hashes and per-test native provenance reports. Every process uses the six private environment roots and exact PID/command ledger. No live session or global/native runtime changes.
3. Fresh tools/ci/run-local.ps1 -SkipNativeTests and existing local script/layout/performance probes. No absent ruff/archive installation and no hosted CI claim.
4. Full GUI cadence is due: fresh serial18 recipes through the blocking runner, preserve all established counts and77 images, recovery producer exit plus fresh10-check/11-flag proof, Assembly58 plus fresh4-check readback, Messages clipboard restoration, exact17-check carrier baseline failure only. Read every JSON, wait for every owned process, classify warning classes and inspect every image. A separate completed visual-review receipt binds the immutable full-GUI aggregate SHA and all77 actual image paths/hashes/inspections; the benchmark cannot start without it. No parked Controls/Display recipes.
5. Both unchanged benchmark fixtures with at least five repeats:67 metrics/335 samples; compare each current median against its target and1.2 times min(Q00b,Q24b) plus5ms. Require an independent five-repeat confirmation only for a candidate regression. Record misses open; no cache microfixture speed claim or studio post-Q03 budget invented.
6. Before/after full tracked/ignored status and diff SHA equality excluding docs/long-run and established Kurt-owned paths; no tool may modify tracked inputs. Full root and independent final diff reviews. Small reviewed reports go through tools/record_evidence.py into validation/2026-10-03-upgrade/native-preview-lifecycle.
7. Update living docs, this record and STATUS, commit focused files with Kurt's verified identity, tag longrun/Q25, attempt the guarded green updater once, then resume the queue immediately.

## Governing descriptions that are stale

The brief's preview cost/platform/test counts are historical; current main and native receipts determine counts. Existing preview is deliberately still a disposable native clone: documentation must retain that behavior. Q03's GeometryCache module is absent on main, has no independently shipped mutable limit here, and is outside this increment. Q24c's offscreen popup observations are parked diagnostic results, not product GUI/display acceptance. Main's existing preview has no configurable cache capacity; do not invent one solely to imitate Q03's failed test.

## Implementation and evidence

Acceptance pending. First Full passed199/199 cases (164native/7bridge/22shortcut/6workflows405) and allfive lifecycle proofs, but consolidated CPU gate1 failed before localCI: PowerShell parsed schema1 as Int64 while the new wrapper required Int32 only. Original tests and assertions remain unchanged. New attempt2 helpers accept exact integer1 in either CLR integer width and bind the immutable original attempt plus alloriginal source bytes; all117 common inputs match. Every native result will be regenerated for the retry. Three new ignored orchestration helpers share one exact source universe (all nonignored src/tests/tools, three root scripts and the three new helpers). Historical benchmark readback independently verified all67 five-sample medians: plate winners7Q00b/32Q24b and studio2Q00b/26Q24b. Current metric comparisons exclude the new values until future-best recording. All original/historical inputs remain unchanged.

Pre-retry reviews (2026-10-04 09:14): two independent complete/delta reviews0; allthree inverse transformations reproduce original helper bytes. CPU9CF260E3, GUI986A0CDF, benchmark07D09703, testAB673 are frozen. Actual first-run source generation40 stayed40 through snapshot creation; the primer records the real behavior without altering generation or cache. First receipt115145B4...54507/rawA825F6B2...98D65 retained; source/tree/environment exact. No localCI/GUI/benchmark/publication acceptance yet.

### Accepted native and GUI gates — October 4, 2026

The fresh second Full run passed all 199 cases: 164 native, 7 bridge, 22 shortcut and six workflow cases containing 405 checks. No case failed, errored or skipped. All five new reports were written by native process 53100 and verified after ordinary fixture cleanup. Local CI then passed its three checks, including the separate 20-hole, three-repeat benchmark. The consolidated receipt is `runtime/longrun/q25-native-ci-attempt2.json`, SHA-256 `3125F3FB753584DC9260D99E4967851A476C824ACD01C98083CDE16839C3A33F`. Its 117 source bindings, exact tree comparison and environment restoration passed; all eleven owned processes exited.

| New native method | Verified consequence |
|---|---|
| Fixed LRU of eight real results | Primer plus eight depths reaches nine evaluations; equivalent `5 mm`, `0.5 cm` and numeric 5 reuse one result. Promotion, ninth-depth insertion and recomputation of the actually evicted depth end at eleven evaluations with the recorded inventory `[4,6,7,8,5,9,1,2]`. Closing twice clears owned cache/snapshot while detached solids remain usable. |
| Partial model failure | A real clone Pad recomputes before injected failure; its clone closes, cache stays empty and native/global transaction state is restored. Retry succeeds with correct added material. |
| Partial native open failure | The real loader opens its clone before injected failure. Cleanup closes only the new clone and preserves the unrelated sentinel document; retry succeeds. |
| Native dimension and placement changes | Real length and placement edits invalidate the old task before any clone opens. A fresh preview follows the translated Body; original saved bytes remain exact. |
| Closed source with reused native name | The replacement has a fresh document UUID. Old tasks reject before clone/cache work and cannot take ownership of it; a fresh preview has the correct 60 mm³ volume. |

Each proof retains strict source/native snapshots, real geometry and history, actual cache/generation observations, source bytes, test/PID/allocation identity and cleanup. Headless availability does not establish GUI Modified behavior.

The full GUI run completed eighteen fresh recipes, with seventeen passes and the exact historical carrier failure after seventeen successful checks. The raw carrier report remains false. The immutable aggregate is `runtime/longrun/q25-full-gui-attempt2.json`, SHA-256 `274A49B3E0FB6914849F304A4DDF586B236D643FCC7847F8A1E3364FD7EC419C`. Counts remain interface41, refinement106, both preview20, sketch28 plus one stage, copy25, lifecycle22 stages, interaction11, startup/baseline3 markers each, STEP19, Assembly58, Assembly STEP35, Part Studio99, Messages34 and GUI benchmark9. Recovery's separate native process passed ten checks and eleven consequences; Assembly's separate reopen passed four checks. All twenty owned GUI/proof processes exited, and Messages restored the clipboard. Source, tree and environment stayed unchanged.

At this native/GUI milestone, pixel inspection and paired benchmarks were still pending. Their completed evidence follows. Q25 has one failed consolidated gate, caused by the original wrapper's integer-width check; no product or test assertion was weakened.

### Completed visual and benchmark review

All 77 unique original images were inspected and rehashed through eight disjoint review chunks. The immutable visual receipt is `runtime/longrun/q25-full-gui-visual-review-1a51c3a8237b49b2aba20e19b817dba2.json`, SHA-256 `F1E276E378E6021716756CBEA640532E3C8CE914C8505635F5DABCC5B3EB1689`; an independent full binding/observation audit found zero remaining findings. The raw GUI aggregate retains `screenshots_inspected:false`; acceptance comes from the separate completed receipt. Existing cropped geometry, clipped status labels and dialog/main-window framing limits remain recorded. The high-zoom sketch image does not establish complete rectangle framing, and overlapping Assembly occurrences are separately proved by native identities.

Part Studio produced 35 scope-warning strings without exact earlier-line matches. Sixteen have complete equal token membership with reordered names; nineteen are truncated, so complete membership is unproved. Their classification as pre-existing warning classes is an inference from the unchanged eight producer sources, actual warning types and fixture objects. Raw `baseline_exact_line:false` and `review_required:true` flags remain intact. No warning or failed carrier report was rewritten.

The paired benchmark completed five repeats per metric on the unchanged plate60 and studio fixtures: 67 metrics, 335 samples, correct geometry and pinned FreeCAD1.1.4/OCCT7.8.1. The aggregate is `runtime/longrun/q25-benchmark-baselines-d2239df2fdd34192a5a86cf3bbf793f4.json`, SHA-256 `9C0292D5CF91228C55A371945DA10DA3D773E0A04BA67FF64B4CC5FB6A62DFC3`. Plate raw SHA-256 is `A09CB1A3815FF61E9DF9D4454F7377B830F168A860DDFC3A7A569F71966AFE23`; studio raw is `9BA9A47F3440B220D23532AF9893FE5BD06BCB1FB809382539DB42BD01C3DBC8`. Both owned processes exited normally; all 117 source bindings, tree checks and environment restoration passed.

| Median, ms | Plate60 | Studio |
|---|---:|---:|
| Tip edit overhead | 3128.398 | 4017.464 |
| Changed inspection | 3037.953 | 1864.929 |
| Warm inspection | 19.751 | 1709.372 |
| First preview | 10180.061 | 3231.593 |
| Preview update | 8783.091 | 3073.215 |
| Checkpoint | 1562.307 | 811.555 |
| Native open | 1840.183 | 155.823 |
| Managed open | 12808.609 | 3587.622 |
| Full rebuild | Not measured | 1143.193 |
| Rebuild selector / auto-scope / kernel | Not measured | 372.855 / 20.870 / 152.878 |

Root recomputed all current and historical medians and the comparison limits directly from raw five-sample reports. No current metric exceeds `1.2 × min(Q00b,Q24b) + 5 ms`. The six phase-specific plate target misses remain open (two edit-overhead, two changed-inspection, first-preview and checkpoint entries); no independent confirmation run is required. Studio absolute budgets remain pending Q03. Uncontrolled system load limits causal timing conclusions; Q25 changes tests only and establishes no application speed improvement.

### Reproduction, review and limits

Run `./run-checks.ps1 -Full -KeepNativeTemp`, then `./tools/ci/run-local.ps1 -SkipNativeTests`. The reviewed private orchestration is retained under `runtime/longrun`: CPU `q25-native-ci-attempt2.ps1`, full GUI `q25-full-gui-attempt2.ps1`, and `q25-run-benchmarks-attempt2.ps1`. These bind their predecessors and require new outputs; do not overwrite original receipts. The standard blocking runner can reproduce individual recipes as `./tools/run_gui_recipe.ps1 -Recipe interface` or `-Recipe extrusion-preview`; use its private session and wait for completion. Paired raw reproduction commands and six environment roots are retained in the benchmark aggregate's actual process records. Both fixtures use `--repeat 5`; plate uses `--holes 60`, studio includes its 30 base features, four parts, eleven consumers and two scoped operations.

The full test diff and all new helper paths received root and independent reviews. Original five method bodies and their 43 assertion calls remain byte-identical. One prelaunch publisher finding was fixed (hash plain logs as bytes rather than JSON); one inaccurate plan word was corrected to translated Body, because the new fixture does not rotate it. A copied visual hash typo was caught before any output or launch. Zero material review findings remain in the test/helper paths. New native methods use Pad fixtures and prove the shared lifecycle; they do not establish new coverage for every studio tool. Headless GUI Modified state is unavailable, native autosave restore remains unverified without an archive, hosted CI awaits Kurt's push, and local ruff/archive extraction were not run because unavailable. Q03/Q09/Q24c remain parked with their immutable failed attempts.

Final small reports were created through `tools/record_evidence.py` after all four finalized test/living-doc hashes were bound. The owned publisher exited0, restored its environment and retained 209 exact input bindings; root rehashed all inputs, outputs and final source/docs. Wrapper receipt `runtime/longrun/q25-publication-bf124af8b84046b09c4a22f06c0a3374/evidence/wrapper-receipt.json` has SHA-256 `829103A2DA8E1EC682464B0F860CB089A2B1BA96AE5F325433CE5DE62B69BA95`.

| Compact report | SHA-256 | Evidence |
|---|---|---|
| [native-tests.json](../../validation/2026-10-03-upgrade/native-preview-lifecycle/native-tests.json) | `49A966C5BDBEA817CCDF40FD4B1774767C21A54AC3676A914EF3227056777819` | 199 passing cases, five actual lifecycle traces, local CI and the retained false first attempt |
| [gui.json](../../validation/2026-10-03-upgrade/native-preview-lifecycle/gui.json) | `BE13811704A05CEA875F5C7983AFCB19ABFF398AD06EEA233C2C63075D81522F` | Eighteen recipes, raw carrier false, independent recovery/Assembly proofs and 77 reviewed image hashes |
| [benchmark.json](../../validation/2026-10-03-upgrade/native-preview-lifecycle/benchmark.json) | `23454ABB89FB8A65F9C11C34BF9F629BE7680A8198CDE5BEC54B0926A3287F7C` | All 67 raw timing arrays and prior-best comparisons; six targets open, zero suspects |

An independent final doc review found one reproduction-order error in STATUS's ABA action; it now closes/replaces the source before closing the old preview, matching the actual test. Contract stays2.0, no atlas behavior is newly shipped, and no parity row is added. M1 remains incomplete and real parametric conversions remain 0/2.
