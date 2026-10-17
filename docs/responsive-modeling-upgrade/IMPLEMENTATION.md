# Responsive modeling upgrade

October 5, 2026, America/Los_Angeles. Implementation on the working tree based on `559e034`, following Kurt's authorization to proceed with the [engine review](../engine-responsiveness-review/REVIEW.md). FreeCAD 1.1.4 and OCCT 7.8.1 remain the native foundation. Earlier uncommitted workflow and presentation work is preserved.

## Implemented behavior

- **Provisional extrusion, then exact validation.** Supported blind Pad/Pocket profiles produce a transient mesh before exact evaluation. Depth changes reuse its mesh and transform. The panel explicitly labels the result provisional and disables confirmation. A private native Python process evaluates an immutable document snapshot and returns display geometry and measurements. Confirmation requires an exact result matching the current proposal, revision and geometry generation. Other supported typed feature editors use the same asynchronous exact path without inventing a provisional shape.
- **Bounded asynchronous work.** Each editor owns one exact worker, one in-flight request and the latest pending proposal. Intermediate responses cannot replace a newer proposal. Cache size is eight results; cancellation terminates only that editor's worker. Worker messages contain JSON and paths, never live FreeCAD, Qt or Coin objects. Equivalent quantity text retains the exact result. Native-generation changes invalidate the snapshot and cache even when authored intent has not changed.
- **Document indexes.** Observed documents cache object membership, Body ownership, history-prefix states and bounded selector contexts. Structural, property, recompute, transaction, undo and close events invalidate the appropriate derived data. Unobserved documents retain uncached reads. The native graph and native recompute ordering remain authoritative.
- **Presentation work follows changes.** Sketch color/material mapping, region membership and historical visibility use event dirtiness and cached scene nodes. A bounded fallback handles native view changes outside the observer. Pointer motion coalesces before picking, with a bounded boundary cache. The conservative native endpoint-color proof rules are unchanged.
- **Persistent history rows.** Part Studio feature and part trees reconcile stable row identities instead of discarding all rows on every refresh. Unchanged rows, selections, current item, expansion and scroll survive. Assembly trees still use their existing rebuild path.
- **Idle recovery.** Ordinary recovery waits for two seconds without user activity and outside feature editors or placement tasks. Idle managed sketches retain draft recovery. At most one native snapshot is attempted per eligible turn, including when a previous publication finishes or the new snapshot fails. ZIP verification, streaming hashing and file publication then run in a file-only worker. Forced checkpoints retain synchronous durability. Older publication failure is reported without preventing a fresh forced checkpoint. Recovery reads wait for publication of their document's complete pair.
- **Interaction timing.** Bounded traces distinguish input, command execution, UI update, paint-event delivery and OpenGL frame swap. Delays longer than five seconds are retained. Event-loop delay is sampled separately. A frame swap is not a physical display-presentation measurement.

## Boundaries

Native `saveCopy` must still run on the GUI thread. The first exact preview snapshot can pause the UI after the provisional visual appears. Worker startup, JSON transfer and overlay application also have costs. Committing a feature still performs the authoritative native operation on the GUI thread; upstream recompute, import/export, explicit geometry checking and forced recovery are not made asynchronous by this change. Native one-minute autosave remains enabled.

This increment does not replace the native kernel, add a selective recompute scheduler, finish incremental authored-intent signatures, unify every tool session, or establish Onshape frame-time parity. No side-by-side Onshape measurement was performed. The separately deferred native endpoint diagnosis patch remains deferred. Original source conversions remain 0/2; these local modeling improvements do not change that gate.

## Measured asynchronous preview behavior

The isolated native GUI benchmark used the original immutable Plate60 review file: 60 native Pocket features, 66 final faces and 133 objects including the preview profile. It exercised the actual asynchronous adapter and Coin renderer for three trials. All 28 checks passed, including current-result gating, mesh reuse, replacing an in-flight proposal, canceling only the owned worker, unchanged source/GUI state and unchanged fixture/source hashes.

| Measured phase | Median | Largest observed |
|---|---:|---:|
| First provisional schedule + redraw, three trials | 11.83 ms | 188.05 ms |
| Provisional depth update + redraw, nine updates | 7.10 ms | 8.16 ms |
| First exact result, complete elapsed time | 12.57 s | 13.63 s |
| Exact result after the depth-change batch | 7.27 s | 7.44 s |
| Native snapshot on the GUI thread | 1.30 s | 1.69 s |
| Timer gap while the exact worker was running | 10.75 ms | 50.59 ms |

The first provisional sample was **188 ms**, followed by 11.83 and 11.00 ms; the median must not hide that cold-start cost. Cancellation returned in 1.64 ms. The whole-run largest timer gap was **1.74 seconds**, consistent with native snapshot serialization still blocking the GUI. The worker-phase timer samples exclude snapshot creation and demonstrate continued event processing during the expensive exact work; they do not establish a universal 50 ms latency bound.

This is a standalone adapter in a hidden native GUI, not full-application physical input-to-display latency. `view.redraw()` is included, but physical display presentation is not measured. Approximate visual feedback and exact validation have different contracts: a 7 ms provisional update does not mean the native model was recomputed in 7 ms. Exact first-result timing includes debounce, snapshot, worker startup, evaluation and delivery. Screenshots were taken outside the timed trial windows. [Raw measurements, source hashes and checks](evidence/plate60-async-preview-benchmark.json) and [independent process receipt](evidence/plate60-async-preview-process-receipt.json) preserve the evidence.

## Final validation

**285/285 regression cases passed**, with zero skips, failures or errors: 250 native cases, seven bridge cases, 22 shortcut cases and six workflows containing 415 named assertions. The complete source inventory remained unchanged during the run and was verified again during collection.

**19 isolated GUI recipes passed 1,217 named checks**, including the 17-recipe application sweep, exact-preview validation and the final GUI benchmark. All 44 production source hashes matched across those runs and final collection. Inspected native and retained worker logs contained no Python/worker exception matches. The intentionally terminated crash producer was accepted only after a separate process proved checkpoint reopening, draft recovery, Cancel restoration and preservation of the original file. No native autosave archive was produced in that test; enabled native autosave preferences are not treated as proof of native autosave recovery.

The preview suite includes 11 focused native tests, including cancellation/task replacement at every adapter guard boundary, plus 29 real GUI checks. Presentation scheduling passes 21 checks: 100 unchanged adapter passes cause no additional expensive work, 50 pointer events coalesce to one pick, and numeric property/arrow edits publish the visible depth text. Completing an older publication or failing a new snapshot cannot permit two native snapshot attempts in one idle turn. The broad sweep covers feature editing, history selection/rollback, sketch planes/references/visibility, Part Studio, assemblies, STEP import, Messages and crash recovery.

[Acceptance summary and source manifest](evidence/acceptance-summary.json), [full regression](evidence/full-regression.json) and the copied GUI reports/independent process receipts retain the exact results. The collector is [collect-acceptance.py](collect-acceptance.py); original native fixtures and earlier failed diagnostics remain in their private runtime directories. Hidden GUI checks do not replace Kurt's hands-on assessment of feel.

## Final integrated GUI benchmark

The final source tree also passed an isolated 20-Pocket, three-repeat GUI benchmark after the regression workload and application sweep had exited. All 11 benchmark checks passed, including retained row identity, recent-input recovery deferral and durable publication of each captured checkpoint.

| Measured phase | Median |
|---|---:|
| Panel refresh | 10.52 ms |
| Unchanged idle tick | 0.020 ms |
| Tick with a refresh flag | 12.76 ms |
| Native recovery snapshot in the GUI | 250.33 ms |
| Upstream model edit | 1,435.34 ms |

These are current-source function timings in a hidden GUI, not input-to-display latency or a before/after speedup. Its synchronous exact-preview diagnostics (2,040.96 ms first / 1,631.50 ms update) call `ExtrusionEvaluator` directly; they do not measure the new asynchronous adapter's provisional feedback. The separate Plate60 measurements above measure that adapter. [Raw integrated benchmark](evidence/gui-bench-gui.json) and [process receipt](evidence/gui-bench-gui-process-receipt.json) preserve the distinction.

## Measured controller changes

The earlier audit and the new complete repeat-three runs had substantially different native recompute/open timings. Their raw results are retained in [the historical comparison](evidence/headless-benchmark-comparison.json), but those elapsed-time differences alone do not isolate the code change. A fresh **baseline → updated → updated → baseline** comparison used the captured pre-upgrade code and current code in separate native processes, loading identical immutable saved fixtures. It asserted the loaded code path, unchanged code/fixture hashes, correct scope migration and matching final native volumes.

| Fresh paired metric | Pre-upgrade median | Updated median |
|---|---:|---:|
| Multi-part inspection, unchanged model | 1,124 ms | 87 ms |
| Multi-part inspection after native upstream geometry change | 3,588 ms | 617 ms |
| Multi-part edit shrinking automatic cut scope from four parts to one | 11,034 ms | 2,984 ms |
| Plate60 final-hole diameter edit | 1,073 ms | 1,077 ms |
| Plate60 inspection, unchanged model | 35 ms | 19 ms |

This supports a substantial reduction in multi-part bookkeeping. It does not establish a general native geometry speedup. Plate60's complete final-hole edit was essentially unchanged. Its changed-inspection samples were mixed: pre-upgrade 128/100 ms, updated 200/103 ms; there is no demonstrated gain on that path. Native Plate60 upstream recomputation was about 13 seconds in both code versions, confirming a remaining native bottleneck.

Warm inspection has six calls per version across two process arms. Changed inspection and edits have two calls per version, one per arm. These are small diagnostic samples, not reliable tail-latency estimates or GUI input-to-paint measurements. The saved-file paired diagnostic differs from the original full build/alternating-edit benchmark, so its absolute times should not be mixed with that earlier table. [Raw samples, procedure and limits](evidence/paired-source-comparison.json) link the four source/fixture-stamped arm reports. Subsequent camera, input-reentrancy and Windows result-file corrections affect only the asynchronous GUI path; these controller measurements use unchanged synchronous paths.

Reproduction uses the pinned runtime through `run-checks.ps1 -Full -KeepNativeTemp` and `tools/run_gui_recipe.ps1 -Recipe <name>`. The integrated GUI benchmark uses `tools/run_gui_recipe.ps1 -Recipe bench-gui -Holes 20 -Repeat 3`. Headless benchmarks use `docs/engine-responsiveness-review/run-review-benchmark.ps1 -Fixture plate -Holes 60 -Repeat 3` and the corresponding `studio` fixture. Baseline source copies and the pre-upgrade tracked patch are retained in `runtime/responsive-modeling-working/baseline-before-upgrades`; original benchmark JSON remains in `docs/engine-responsiveness-review/evidence`. Collected evidence beside this report records its fixture, method and source hashes.

## Continuity

Consequential implementation choices: keep the compatible native runtime; move exact preview evaluation into a disposable process; retain synchronous exact evaluation for the assistant/headless API; keep provisional results nonconfirmable; bind preview validity to native geometry generation as well as revision; preserve forced recovery durability; retain native autosave until a separate replacement is proven.

Failures found during implementation included canceled snapshots re-entering Qt, stale exact results after native recomputation, same-proposal failure preventing retries, recovery publication/read races, failed older recovery blocking a forced checkpoint, deleted Qt child wrappers during row reconciliation, and native hover state interacting with delayed picking. Snapshot cleanup also restored an old camera/selection after reentrant input; the async path now leaves those interactions intact, while the synchronous clone evaluator retains its needed restoration. Each correction has a check for its trigger. A deep worker session path exceeded native serializer path limits on Windows; worker folders now use short, private task paths under `runtime/exact-preview-workers`. An overly deep benchmark session encountered the same native limit, remains retained as a failed run, and is excluded from accepted timings.

An injected reentrant worker completion reproduced an obsolete result appearing while new input was still being normalized. Publication/acceptance now waits until normalization finishes, with single-shot starts explicitly re-armed. A larger-model run then exposed a transient Windows permission error reading/deleting a completed result file. Read locks now defer to a later poll within the existing timeout; deletion locks cannot turn a verified completed result into a failure. The focused transport regression checks read retry, deletion failure and persistent-lock timeout. Failed diagnostic runs remain retained and are excluded from acceptance.

Final review also reproduced cancellation or task replacement during a native preview guard, an idle-recovery publication turnover allowing a second snapshot, and selection toggling when a persistent current history row was selected again after native sketch Close. Preview callbacks now retain task identity across native guards, recovery counts native capture attempts, and explicit feature selection uses Qt's ClearAndSelect command. Deleted native document wrappers and AssemblyGui providers are handled safely. Native Qt spin boxes now schedule previews from value changes as well as edited text; the separate FreeCAD quantity widget's text signal was verified directly. A concurrent edit temporarily dropped the selection correction; subsequent shared-file writes were serialized, its exact persisted code was checked, and the final interface recipe passed without a diagnostic override.

Benchmark files retain the exact code versions measured. The later lifecycle, selection, observer and recovery scheduling corrections receive fresh correctness checks; those timings are not represented as new performance measurements of the final source tree.

Next step: save and close the older application window, then launch `Codex/KurtShape-workflow-update.cmd` to try the updated source on Kurt's own models. The next engineering targets are the measured native snapshot pause and dependency/recompute work on larger edits; a kernel/runtime replacement still needs separate compatibility and performance evidence. The user's running application and original source projects were not changed by the validation processes.
