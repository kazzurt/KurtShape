# S10: measurements of the accepted architecture

October 8, 2026. Production is the accepted S09B revision, unchanged throughout this batch. S10 measures the combined revision and reconciles architecture documentation; it introduces no production, benchmark, test or budget changes. The original working-tree baseline is preserved under `runtime/architecture-upgrade-working/baseline-20261007-155828/source`.

Both matched benchmarks completed successfully. Most recorded operation totals are lower than the original measurements, but these separate three-sample runs cannot establish causality, statistical significance or broad responsiveness. Post-operation inspection, Studio reopen and one checkpoint worst case provide slower observations worth retaining. The existing absolute targets remain separate from correctness acceptance.

Fresh native validation passed **407/407 with zero skips**, including all four opt-in `StatusPerformanceTests`, in 308.65 seconds. All 95 native-run input hashes match the unchanged accepted source. Idle inspection was 27.58 ms and post-change inspection 47.89 ms median against 20 ms targets; both remain **open**. Tip overhead was 81.70 ms against 150 ms, and managed-minus-native open medians were 49.98 ms against the test's 515.08 ms limit; those targets were met. Correctness passes do not close the two missed inspection budgets.

## Matching and interpretation

Both runs use the identical FreeCAD 1.1.4 commit `4fd3bf320d9566a27e60069fc8387448aaa3a094`, OCCT 7.8.1, 32-logical-processor Intel Family 6 Model 183 machine, and Windows build. `bench_core.py`, `report.py` and `budgets.json` are byte-identical to the preserved baseline. Every final run records its source hashes, verifies them after completion and matches the accepted S09B manifest.

Plate60 has 132 objects and 66 faces; Studio has 30 base features, four parts, 11 selector consumers, two added scoped operations, 34 history features and 162 objects. Measurement level is `false`; the section order and three repetitions match exactly. The full original/final engine, hardware, fixture, settings, raw samples and receipt/archive hashes are retained in the [machine comparison](../../runtime/architecture-upgrade-working/s10-measurement-working/measurement-comparison.json).

- Three repetitions are operations within one process, not three independent cold processes. Only median and worst are interpreted; the stored three-sample p95 equals the worst.
- Warm inspection follows an untimed prime. Changed inspection follows an untimed native upstream edit/recompute. Operation-internal inspection is a different measurement.
- First preview uses a new synchronous `ExtrusionEvaluator`; update changes the proposal on that evaluator. These headless calls bypass the UI worker adapter. Forced checkpoints bypass snapshot sharing. Neither measures S01/S02 lease benefits.
- Reopen reads the same saved file in the same running process, all native opens before managed opens. OS caches are not reset; no cold-start claim follows.
- Overhead subtracts only measured native-recompute events from total wall time. Other native work can remain in it. Selector timing measures the complete consumer refresh. Nested timing columns must not be summed.
- Three-sample budget evaluations are explicitly unavailable, not passes. The five-sample/independent-confirmation regression rule cannot be applied to these baselines. Studio's embedded budget uses `measure=true` and a different historical object count, so it is also incompatible.
- This is a comparison of all combined accepted changes. It does not attribute timing changes to a particular cache, worker, selector change or native kernel improvement.

### S11 qualification: the status tests are a different, instrumented workload

The official `no_kernel_checks` guard in `tests/test_build_status.py` installs `sys.setprofile(observe)` around the timed idle/changed inspections, tip edits and native/managed opens. Python and C events invoke that callback even when its filter records no kernel calls. Explicit check/true/full measurement timings use a different path without that guard. S10's budget outcomes above remain the official outcomes of this instrumented harness; they are not uninstrumented application latency and must not be corrected by subtracting an assumed profiler cost.

The opt-in test reopens an original saved Plate60 in a fresh Controller and times five direct `core.inspect(..., measure=False)` calls without an explicit prime. Managed open itself already inspects. Its changed samples set H59 diameter to 31 through 35 and recompute without an explicit transaction. The matched benchmark instead retains its Controller after additions/undos and edits (H59 diameter 28, Pad length 13 before warm inspection), primes once, then times three `dispatch(inspect)` calls. Its changed samples increase upstream Pad length in committed transactions. Therefore 27.58/47.89 ms in the opt-in tests and 14.69/38.27 ms in the matched Plate benchmark are not the same workload and do not establish a between-harness regression. S11 diagnoses profiler cost under matched controls; the original samples and recorded open budgets are preserved.

[S11's completed diagnostic](S11-INSPECTION-DIAGNOSTIC.md) finds a material profiler cost in paired cases and recommends finer inspection/status attribution before choosing a production optimization. The private authoritative-process milestone remains deferred; S10's original next-milestone proposal below is retained as the decision at that checkpoint.

## Findings and remaining gaps

Plate's recorded tip total falls from 443.04 to 402.74 ms, warm inspection from 18.94 to 14.69 ms, and changed inspection from 45.15 to 38.27 ms. First synchronous preview remains 7377.72 ms and update 6226.69 ms; upstream editing remains 6480.64 ms. Studio's tip total falls from 1240.43 to 1155.78 ms and changed inspection from 248.87 to 222.17 ms. These long operations remain material limitations.

Slower observations are retained: Plate operation-internal inspection medians rise by 6.26 ms for tip edit, 8.95 ms for upstream edit, 9.22 ms for sketch addition and 6.92 ms for pocket addition. All three final samples in each of those categories exceed the earlier worst. Studio tip/upstream inspection rises from 29.63/41.67 to 35.18/46.45 ms; rebuild scope synchronization rises from 13.96 to 14.61 ms. Managed reopen rises from 308.87/314.48 to 322.28/331.16 ms median/worst. Studio checkpoint worst rises from 252.47 to 271.35 ms despite a lower median. These are descriptive investigation signals, not confirmed budget regressions or proof that an individual change caused them.

S08's separate, unchanged-harness three-before/three-after GUI experiment remains the evidence for the narrow per-refresh icon change: median refresh 1823.87 to 102.92 ms and completion polling 2058.25 to 337.08 ms. All six runs pass, and all 36 retained evidence hashes were independently rechecked in S10. Parts reconciliation itself did not improve. See [S08 comparison](../../runtime/architecture-upgrade-working/s08-timing-comparison.md); do not merge those samples with S10.

Dense-sketch interaction, assemblies, representative private projects, memory growth, independent cold processes, rendering and input-to-paint budgets remain unmeasured here. S09B's separate STEP GUI proof showed actual child-work overlap while parent launch and completion polling still took approximately 2.34 and 3.42 seconds. Resident-clone transaction-abort reset was rejected; staged recompute remains unactivated. Its dependency-order discrepancy also occurs in oracle-only controls, so candidate-only attribution is unsupported.

The next prioritized architecture milestone is a private authoritative-process vertical slice that tests native document ownership, command/revision/undo behavior and the Sketcher/GUI boundary. It requires a separate finite batch; S10 performs no migration. The observed slower inspection/reopen paths and remaining capture/acceptance/publication costs should be retained as measurement questions for that work.

## Reproduction and evidence

From the repository root, use PowerShell `docs/engine-responsiveness-review/run-review-benchmark.ps1 -Fixture plate -Holes 60 -Repeat 3`, then `-Fixture studio -Repeat 3`. The runner's fixed timeout is 1200 seconds; each uses a new private session. Original/final runs took 142.77/130.84 seconds for Plate and 22.09/20.46 seconds for Studio.

For the performance methods, set `KURTSHAPE_PERF=1` only in the private launcher environment and use bundled Python with `-B tools/run_native_tests.py --suite native --require-native --require-external --keep-temp --timeout 900 --report <unique-report>`. The ordinary native runner alone leaves these methods skipped. Five-sample status tests use copied Plate60 fixtures and differ from the three-sample operation sequence; they are not substitute baseline pairs. Explicit full measurement follows true measurement, so its timing reflects incremental centre-of-mass work.

Rebuild the tables and machine comparison with ordinary Python `runtime/architecture-upgrade-working/s10-measurement-working/summarize-s10-measurements.py`. This reads retained evidence only and checks matching controls, statistics and frozen source hashes; it performs no native CAD work.

- [Original Plate receipt](../../runtime/architecture-upgrade-working/baseline-plate-e1912231/evidence/benchmark.json)
- [Final Plate receipt](../../runtime/engine-responsiveness-review-working/plate-80add3c122464149bc8f37ef78d409af/evidence/benchmark.json)
- [Original Studio receipt](../../runtime/architecture-upgrade-working/baseline-studio-a077748b/evidence/benchmark.json)
- [Final Studio receipt](../../runtime/engine-responsiveness-review-working/studio-da9645248bfe4d8aae7161eafb3d71fa/evidence/benchmark.json)
- [Native suite with performance enabled](../../runtime/architecture-upgrade-working/s10-measurement-working/native-with-performance.json)
- [Execution record](EXECUTION.md)

<!-- S10_GENERATED_TABLES -->

## Plate — milliseconds

| Metric | Original median / worst | Final median / worst | Median change |
| --- | ---: | ---: | ---: |
| tip_edit.total_ms | 443.04 / 452.95 | 402.74 / 407.63 | -9.1% |
| tip_edit.native_recompute_ms | 375.38 / 381.70 | 353.19 / 354.25 | -5.9% |
| tip_edit.overhead_ms | 67.66 / 71.25 | 49.55 / 55.67 | -26.8% |
| upstream_edit.total_ms | 6652.77 / 6685.50 | 6480.64 / 6601.12 | -2.6% |
| tip_edit.inspection_ms | 21.36 / 21.85 | 27.62 / 27.75 | +29.3% |
| upstream_edit.inspection_ms | 19.61 / 20.04 | 28.56 / 29.77 | +45.7% |
| add_sketch.inspection_ms | 19.43 / 20.81 | 28.65 / 29.46 | +47.5% |
| add_pocket.inspection_ms | 20.48 / 20.70 | 27.40 / 28.16 | +33.8% |
| inspect_warm_ms | 18.94 / 20.61 | 14.69 / 14.87 | -22.4% |
| inspect_after_change_ms | 45.15 / 47.31 | 38.27 / 40.82 | -15.2% |
| checkpoint_ms | 1272.22 / 1284.56 | 1228.07 / 1268.60 | -3.5% |
| preview_first_ms | 7885.72 / 7949.66 | 7377.72 / 7546.29 | -6.4% |
| preview_update_ms | 6616.35 / 6723.48 | 6226.69 / 6458.51 | -5.9% |
| native_open_ms | 1728.75 / 1750.69 | 1632.14 / 1728.67 | -5.6% |
| kurtshape_open_ms | 1801.21 / 1822.75 | 1619.49 / 1641.83 | -10.1% |

## Studio — milliseconds

| Metric | Original median / worst | Final median / worst | Median change |
| --- | ---: | ---: | ---: |
| total_rebuild_ms | 481.52 / 484.97 | 452.60 / 453.31 | -6.0% |
| tip_edit.total_ms | 1240.43 / 1593.29 | 1155.78 / 1516.69 | -6.8% |
| tip_edit.native_recompute_ms | 209.59 / 297.85 | 192.98 / 291.26 | -7.9% |
| tip_edit.overhead_ms | 1030.84 / 1295.44 | 962.80 / 1225.43 | -6.6% |
| upstream_edit.total_ms | 780.64 / 790.03 | 702.52 / 712.64 | -10.0% |
| tip_edit.inspection_ms | 29.63 / 40.48 | 35.18 / 44.38 | +18.8% |
| upstream_edit.inspection_ms | 41.67 / 42.81 | 46.45 / 48.42 | +11.5% |
| inspect_warm_ms | 39.36 / 40.73 | 35.22 / 35.56 | -10.5% |
| inspect_after_change_ms | 248.87 / 252.01 | 222.17 / 223.07 | -10.7% |
| checkpoint_ms | 243.61 / 252.47 | 223.50 / 271.35 | -8.3% |
| preview_first_ms | 1053.78 / 1058.73 | 982.54 / 1009.81 | -6.8% |
| preview_update_ms | 917.85 / 920.17 | 858.96 / 869.87 | -6.4% |
| native_open_ms | 179.42 / 180.96 | 172.16 / 173.03 | -4.0% |
| kurtshape_open_ms | 308.87 / 314.48 | 322.28 / 331.16 | +4.3% |

## Five-sample status tests — milliseconds

Correctness outcomes and absolute timing targets are separate.

| Metric | Median | Worst | Target / outcome |
| --- | ---: | ---: | --- |
| explicit_check_ms | 1036.21 | 1074.15 | reported only |
| explicit_true_measure_ms | 74.68 | 179.53 | reported only |
| explicit_full_measure_ms | 47.91 | 50.11 | reported only |
| idle_inspect_ms | 27.58 | 30.52 | 20; OPEN |
| inspect_after_change_ms | 47.89 | 49.97 | 20; OPEN |
| native_open_ms | 5150.76 | 5264.08 | reported only |
| managed_open_ms | 5200.74 | 5303.19 | reported only |
| managed minus native open medians | 49.98 | — | 515.08; met |
| tip_edit_total_ms | 465.09 | 472.84 | reported only |
| tip_edit_native_recompute_ms | 374.75 | 392.13 | reported only |
| tip_edit_overhead_ms | 81.70 | 90.34 | 150; met |
