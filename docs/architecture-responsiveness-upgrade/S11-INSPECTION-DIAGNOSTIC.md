# S11: inspection-cost diagnostic

October 8, 2026. The existing global profiling guard materially increases inspection timings on the matched private Plate60 cases. Warm inspection medians were **13.93 ms off / 29.68 ms on**; first post-change medians were **31.83 / 51.62 ms**. These are descriptive paired observations from two processes. They do not justify subtracting an overhead estimate from official results or closing a timing budget.

All 110 accepted S09B source hashes remain unchanged. No production algorithm, official test, budget or authoritative-process implementation changed. [S10's report](S10-MEASUREMENTS.md) now explains its two different workloads and preserves its official outcomes: instrumented idle/post-change inspection targets remain open.

## Matched design and evidence

Two fresh, sequential, privately profiled native Python processes used the pinned FreeCAD 1.1.4 / OCCT 7.8.1 engine. The first built and saved an original, unedited Plate60: 132 objects, 66 faces, Pad length 12 and H59 diameter 30. Both processes used the exact same retained archive bytes. Each ran four copied-document pairs, alternating OFF/ON and ON/OFF; the second reversed those orders. Every arm had a new Controller and an identical file copy, with managed open unprofiled and `measure=False` throughout.

Each arm measured the first explicit inspection after managed open, five warm inspections after exactly one untimed explicit prime, and the first inspection after H59 diameter changed to 31 and native recompute. The guard's public `geometry.check_shape` spy remained installed in both conditions; only the global `sys.setprofile` callback was toggled, outside timing. Its callback body matches the existing test guard and does not add event-count instrumentation. Profiler-on observations and the public spy recorded zero check calls. Profiler-off direct-native observations are unavailable, represented as null, not zero. The unchanged S10 guarded correctness run also remains evidence for the original no-kernel-check assertions.

There are **eight pairs, sixteen copied-document arms, and only two independent processes**. First/changed phases have eight samples per condition. Warm comparisons use each arm's median of five operations, with all 40 raw warm operations per condition retained. Sample distributions and paired differences are descriptive; there is no statistical-significance or cold-process claim.

The warm table's ranges are ranges of arm medians. Individual warm operation ranges are 13.13–16.39 ms off and 27.79–55.78 ms on; the 55.78 ms observation is retained. Every paired ON-minus-OFF difference is positive in all three phases.

Managed open itself already inspects. Strict snapshot reads also serialize native BReps and read complete intent before timing, equally in both arms. The diagnostic is therefore explicitly **snapshot-primed**, not a cold inspection test. No inspection-output oracle is called before the first timed explicit call. Setup, recompute, snapshotting, guard installation/removal and JSON writing are outside measured intervals.

Every arm retains complete outputs and strict snapshots. Idle first/prime/warm outputs and strict states match exactly. A changed first inspection legitimately updates the session revision and project metadata state/status; the full raw pre-sync state and exactly these three differences are retained. Every other recorded field, including modeled BRep/native hashes, intent digest, placements, ordered native fields and history, remains equal. Its opposite-mode untimed replay exactly matches the accepted output/state. This proves stable accepted-state replay, **not** equal dirty input for opposite modes in the same live document; timed changed arms use separate identical archive copies and preserve all their real identities.

The existing strict helper applies only its documented intrinsic-Origin observation policy. It does not separately serialize complete ElementMaps or metadata schema, and headless GUI state is unavailable. No camera, Modified or input responsiveness claim is made. All sixteen copied archives and the original archive were rehashed after both diagnostics, including after the coarse profiles, and remain identical.

## Interpretation and next priority

The paired median ON-minus-OFF differences are 15.77 ms for first explicit calls, 15.64 ms for warm arm medians, and 19.24 ms for first changed calls. The higher on-condition worst cases remain in the table. This identifies profiling as a material measurement cost for this fixture; fixture state, priming, direct-versus-dispatch calls and edit sequence also differ between the original S10 harnesses. S11 did not add a separate direct/dispatch or original/post-edit factorial comparison.

The independent coarse profile points to summary handling and status/inspection reads. Warm inspection records 124 summary hits and zero builds in both processes; first post-change inspection records zero hits and 124 builds. This is consistent with the intentional document-wide summary epoch invalidation on native recompute. Summary handling spans about 5.39–6.10 ms warm and 19.01–19.53 ms changed in these instrumented observations. Status handling spans about 4.34–5.84 ms. Geometry key construction is only about 0.21–0.22 ms, and recorded geometry/check computation counters do not increase.

These coarse spans are nested, nonadditive diagnostic observations. Buffered wrappers call the original functions once and restore descriptors in `finally`; their own overhead is unmeasured. Residual values include unwrapped work and wrapper/bookkeeping overhead, not clean exclusive native or Python time. There is no timed uninstrumented equivalent-input control for the coarse profiles, and the changed replay is already synchronized. No accurate phase-percentage or predicted-saving claim follows. Counter snapshots were taken after the strict evidence read; source inspection confirms that helper does not invoke the summary/geometry cache APIs. The raw counter boundary is preserved rather than relabeled.

**No production optimization is justified yet.** Removing the global invalidation fence or changing returned-summary copying would require separate dependency, mutation and reentry proofs. The smallest next diagnostic should split the remaining status and `_inspect` work by existing native-results, Studio/assembly and reference-health helpers, with a matched uninstrumented control. That can identify a safe per-inspection reuse candidate without inventing a new persistent cache. Geometry-key optimization and authoritative-process migration are not supported as the immediate remedy by this diagnostic. The broader private authoritative-process vertical slice remains a separate later milestone.

## Reproduction, failures and cleanup

Native receipts: [run 0](../../runtime/test-tmp/s11-inspection-bda20faf/diagnostic.json), [run 1](../../runtime/test-tmp/s11-inspection-fce57186/diagnostic.json), with sibling `process-result.json`, stdout and all raw arm files. Children 34444 and 40520 exited 0 without timeout in 81.52 and 49.09 seconds of diagnostic work (82.27/49.79 seconds including process startup). Each had a 360-second bound; document cleanup and source guards passed. User FreeCAD 40888 was untouched.

The exact executed recipe is [diagnose-inspection-cost.executed.py](../../runtime/architecture-upgrade-working/s11-inspection-cost-working/diagnose-inspection-cost.executed.py), SHA-256 `374b57939733e9d4e9ab969836dc9113099ea1b426a604e3585d2c12bf0d7844`. After both successful runs, read-only review found a launcher logging-exception window before its reaper guard. The current [diagnostic helper](../../runtime/architecture-upgrade-working/s11-inspection-cost-working/diagnose-inspection-cost.py) moves logging inside that guard, preserves source-verification errors as failures, and rechecks archives after coarse profiling. Those lifecycle-only edits were syntax-checked but were not rerun as native measurements; the original executed recipe and all receipts remain intact. Use the current helper for any separately authorized repeat, with bundled Python `-B <helper> --run 0`, then `--run 1`, one bounded process at a time.

The read-only summarizer had two retained failures: relative-path resolution during hash inventory, then Windows console encoding after successfully writing its result files. Their exact script versions and errors remain in the working folder. It now resolves paths and prints an ASCII JSON status; neither failure changed native evidence. Recreate the final analysis with ordinary Python [summarize-inspection-cost.py](../../runtime/architecture-upgrade-working/s11-inspection-cost-working/summarize-inspection-cost.py), the two diagnostic JSON paths, and `--recipe <diagnose-inspection-cost.executed.py>`. It verifies hashes, native/output parity, counters and arithmetic without native work.

[Machine comparison and 308 retained-file hashes](../../runtime/architecture-upgrade-working/s11-inspection-cost-working/diagnostic-comparison.json) contain raw paired values and inclusive/residual counts. Original archive/fixture settings and pre-qualification S10 documents remain in the same descriptive working folder. S11 stops without a further batch.

<!-- S11_GENERATED_TABLES -->

| Phase | OFF median / range ms | ON median / range ms | Median paired ON−OFF ms |
| --- | ---: | ---: | ---: |
| first-explicit | 14.15 / 13.56–14.97 | 29.73 / 26.71–43.28 | +15.77 |
| warm-arm-median | 13.93 / 13.65–14.44 | 29.68 / 28.41–32.35 | +15.64 |
| changed-first | 31.83 / 29.81–35.12 | 51.62 / 49.25–69.93 | +19.24 |

Each row has eight copied-document pairs across two processes. Warm values are each arm's median of five operations (40 raw warm operations per condition).

| Process / phase | Outer ms | Summary hits / builds | sync incl. ms | build-status incl. ms | summary.get incl. ms | token incl. ms | build incl. ms | copy incl. ms | geometry.key + check_key incl. ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 / warm | 15.22 | 124 / 0 | 4.35 | 4.34 | 6.10 | 2.71 | 0.00 | 2.74 | 0.22 |
| 0 / changed-first | 33.12 | 0 / 124 | 8.44 | 4.34 | 19.53 | 5.17 | 10.16 | 2.89 | 0.21 |
| 1 / warm | 15.65 | 124 / 0 | 5.59 | 5.58 | 5.39 | 2.38 | 0.00 | 2.40 | 0.21 |
| 1 / changed-first | 34.03 | 0 / 124 | 9.88 | 5.84 | 19.01 | 5.58 | 9.55 | 2.67 | 0.22 |

Inclusive columns overlap and must not be summed. Coarse profiling has unmeasured wrapper overhead; raw call counts, inclusive/residual times and exact replay evidence are retained.
