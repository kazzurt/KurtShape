# Q03 — Fast build status, explicit geometry checks and stored-shape open

Resumed October 4, 2026 under Revision 2, from longrun/parked-Q03-fast-status-resumed on main at longrun/Q25. This pilot works on Q03 only and pauses after tagging it, or at 18:41:47 Pacific with work uncommitted.

## Scope and decisions

Contract 3.0 uses feature flags, null shapes, solid counts and rebuild reasons for interactive status. Geometry checking is explicit or required at export; import boundaries retain their checks. Geometry facts and exact selector/scope pair results are cached by object shape versions and placement dependencies. GUI requests use measure false; API defaults remain true, and full adds the solid centre of mass. Saved false-hasher documents trust stored shapes. True-hasher files switch off and rebuild once, then receive an engine stamp. Rebuild and its stamp remain one undo transaction.

Touch points are core, geometry, document_state, studio, selectors, reference_tools, extrusion_preview, ui and general_actions. The standing native runner, benchmark and affected GUI recipes follow the new semantics. Existing model authority, typed revisions, failure rollback, staged save/export and recovery are preserved. No profile migration or live-session action is involved.

## Resume repairs and stale specifications

The parked native run passed every case except its new bounded-cache test. Lowering a populated cache limit requires draining every excess entry, so check and memo now evict with while. The recomputation assertion is unchanged. Q25's added preview inventory now reads geometry.documents instead of removed Controller.evaluations and includes geometry.py in its source inventory. Every preview.evaluations assertion still counts real clone evaluation and remains unchanged.

The brief's source anchors/counts predate U2. U2 studio order, exact queries and merge scope remain authoritative. Per-object facts use Tip topology for Body validity; frame changes invalidate measurements and pairs. Exact reconciliation occurs at managed/open or recorded recompute boundaries, never idle polls. Raw native stored-open tests proved empty Body/Plane map marker restoration from actual shape map versions. Detached compound inputs protect source BRep serialization while preserving measured geometry and export publication.

The prior attempt records remain on retained branches. Revision 2 replaces their attempt limits, proof prerequisites, receipt wrappers and hash pins. Use the standing scripts directly; retain only small summaries after landing.

## Existing assertion changes

- NativeConversionTests.assert_volume explicitly requests geometry checking and keeps solid, volume and unchanged-revision checks.
- Review follow-up and Assembly idle tests spy on geometry.check_shape and retain no-work, source, solver, intent and cache consequences.
- Preview invariants and Q25 inventory use geometry provider document ownership in place of the removed evaluations cache.
- gui-review-validation uses the new check/fact counters; gui-validation asserts stored-open zero recompute and unchanged Modified; general-actions-validation rebuilds explicitly before accepting pasted features; assembly-step-validation requests measured volume/bounds; extrusion-preview-validation checks geometry cache ownership.
- The angled-plane workflow compares its concrete read-only Pad output Placement against a fresh native stored-open oracle, while every authored input and other property remains exact against pre-save intent. Ten additional consequences cover raw ownership, BRep/flags, frames, history, full maps/element identities, native markers, zero recompute and source bytes. Other five workflows and later rebuild/edit/undo assertions are unchanged.

New tests cover thirteen BuildStatus cases, four performance cases and six GeometryQuery cases. Q25 retains five lifecycle cases, giving 187 native cases after integration, plus seven bridge, 22 shortcut and six workflows with 415 named checks. Derive final counts from actual reports.

## Gates and budgets

Run run-checks.ps1 -Full and tools/ci/run-local.ps1 -SkipNativeTests. Run the full standing GUI set and the Q03 status recipe; read each JSON after process exit. Inspect changed status screens and failed recipe screenshots. Classify warnings against the previous baseline. Check/checkpoint/core/U2 spies must record zero interactive BRepCheck calls.

Measure the standing plate60 and studio benchmarks, five repeats, with GUI false policy and retained API true measurements clearly identified. Compare prior best medians; confirm only a metric worse than both its target and best times 1.2 plus 5 ms. The plate targets are edit overhead 150 ms, added pocket overhead 300 ms, changed/warm inspection 20 ms, and open overhead max(300 ms, 10% of native open). Improved absolute misses remain open. Profile the standing studio benchmark once with cProfile; record its three largest remaining costs. Set studio rebuild budget to 1.5 times the measured post-Q03 median and enforce subsequent runs.

## Implementation and evidence

Full checks and local CI passed; the final standing runs follow the status-capture correction and recorded studio budget. The complete GUI sweep passed seventeen recipes and retained the exact carrier-spike baseline after seventeen checks. Independent recovery verification passed ten checks; the Q03 status recipe passed seventeen.
The first status capture preceded painting of a newly opened GL view. The corrected recipe uses product open_path, processes Qt events, fits the model, and additionally asserts Body/Tip visibility and retained 1200 mm3. All 17 checks pass and the solid renders beside the rebuild reason. Existing zero-recompute, Modified, undo and source-archive assertions remain unchanged.

One reviewer pass found zero material production issues and one documentation issue, corrected: export reuses a valid cached verdict and checks only when needed. Warning classes match Q25; scope-warning text can differ by order and truncation. No helper or evidence review rounds were added.

| Evidence | Result |
|---|---|
| Full native/bridge/shortcut | 187 / 7 / 22 cases, no failures, errors or skips |
| Workflows | Six fixtures, 415 named checks; original save/undo/rollback consequences retained |
| Local CI | Pinned runtime layout, plate20 three-repeat benchmark and exact tree comparison passed |
| Standing GUI | 17 passes; exact carrier history baseline retained; recovery proof 10 checks |
| Q03 GUI | 17 checks; stored-open zero recompute, retained solid, unchanged Modified/source and rebuild/undo reason |
| Paired benchmark | 67 five-sample metrics per policy, 134 metrics / 670 samples in all |
| Plate confirmation | 39 metrics / 195 samples; none exceeds historical best times 1.2 plus 5 ms |

| Metric, ms | GUI false initial | GUI false confirmation | API true initial |
|---|---:|---:|---:|
| Plate tip overhead | 157.867 | 62.623 | 280.827 |
| Added pocket overhead | 335.924 | 155.879 | 319.006 |
| Changed inspection | 130.818 | 41.166 | 251.128 |
| Idle inspection | 50.066 | 19.684 | 47.223 |
| Checkpoint | 3971.062 | 1605.292 | 3503.171 |
| First / update preview | 17621.940 / 15584.913 | 8116.546 / 6645.136 | 16340.492 / 13220.280 |
| Native / managed open | 3869.809 / 3304.048 | 1798.671 / 1838.901 | 4053.672 / 5082.295 |
| Studio full rebuild | 2984.416 | — | 2978.420 |
| Studio selectors / auto-scope | 1091.421 / 65.057 | — | 1111.530 / 50.803 |
| Studio changed / warm inspect | 5622.713 / 1932.179 | — | 5925.599 / 1804.449 |

The first paired runs had broadly slower native, signature and checkpoint timings. An independent full plate run on unchanged source did not reproduce any historical-threshold excess; no regression was confirmed. A short saved-plate diagnostic also changed timing within its run, so it established no cause and led to no application edit. The prepared Q25 snapshot was never executed. Historical Contract 2 true included checking and mass centre; Contract 3 true omits both, while false returns count only. These policy changes and observed variability limit equal-work comparisons. All raw medians are summarized in the evidence; the separate profile is excluded from benchmark/budget medians.

The required one-repeat cProfile of the standing studio benchmark recorded the three largest own costs: native Body enumeration 6.674 s, ownership matching 3.161 s and native recompute 1.220 s. The prior eight-phase diagnostic recorded body enumeration 4.01654 s, result scanning 2.00197 s and native recompute 0.95629 s; its workload differs, so these are cost locations rather than a speed ratio. Repeated ownership scans remain a substantial cost. The studio API-true five-repeat median 2978.419600 ms sets its budget to exactly 4467.629400 ms, 1.5 times the median. Its five actual samples are stored in budgets.json; report.py --enforce evaluates it successfully. Future default studio benchmarks use --enforce and this comparable baseline.

Reproduce with run-checks.ps1 -Full, tools/ci/run-local.ps1 -SkipNativeTests, tools/run_gui_recipe.ps1 -Recipe NAME and tools/validate-q03-status.ps1. Initialize tools/validation-session.ps1's private environment before bundled Python. Run tools/perf/bench_core.py --fixture plate --holes 60 --repeat 5 --measure false, then true; run --fixture studio --repeat 5 --measure false, then true --enforce. Give each run its own --scratch and --out below that session. Profile once with -m cProfile -o studio.prof tools/perf/bench_core.py --fixture studio --repeat 1 --measure true. Package the small summaries through unchanged tools/record_evidence.py.

Changed inspection's 20 ms target remains open and gets follow-up Q27, alongside later preview50/checkpoint16/edit50 targets. Q04/Q07/Q11 are unblocked, but this pilot starts none of them. Stored Part Studios and explicit checking are covered; Assembly/recovery retain their reconstruction paths. Hidden GUI automation does not establish hands-on comfort, native autosave recovery has no archive proof, and hosted CI/lint remain unrun. M1 remains incomplete and real parametric conversions remain 0/2.
