# Fresh controller benchmarks, 2026-10-17, checkout f57d592

Medians in ms over 5 repeats (p95 in parentheses). Isolated bundled-Python process per run, private profile under `runtime/bench/fable-review-20261017-034920`, `measure=true` (volume/area/bbox) and `measure=false` (solid count only, the GUI's ordinary policy). Machine: Intel64 Family 6 Model 183 Stepping 1, GenuineIntel, 32 logical processors, Windows-10-10.0.26200-SP0. FreeCAD 1.1.4 (4fd3bf320) / OCCT 7.8.1. Seven review agents ran concurrently (file reading, occasional short headless probes); treat as lightly noisy. Raw reports: the JSON beside this file (`controller-benchmarks-2026-10-17.json`) carries every sample.

| Metric | plate60 m=true | plate60 m=false | plate20 m=true | studio m=true | studio m=false | Budget |
|---|---|---|---|---|---|---|
| `tip_edit.total_ms` | 522.9 (541.1) | 481.4 (488.8) | 96.4 (100.5) | 1343.4 (2093.7) | 1462.7 (2287.8) |  |
| `tip_edit.overhead_ms` | 141.5 (145.6) | 65.4 (68.4) | 38.2 (39.1) | 1190.5 (1689.4) | 1298.0 (1837.8) | 150 (phase0) / 50 (phase1) |
| `tip_edit.native_recompute_ms` | 388.4 (403.3) | 416.2 (423.4) | 58.4 (61.4) | 211.4 (404.2) | 236.1 (450.0) |  |
| `upstream_edit.total_ms` | 7099.0 (7269.7) | 6916.7 (7414.7) | 529.3 (561.3) | 991.0 (999.7) | 1060.1 (1066.1) |  |
| `upstream_edit.native_recompute_ms` | 6934.8 (7118.3) | 6844.5 (7341.7) | 485.9 (520.3) | 268.5 (269.9) | 285.8 (288.3) |  |
| `add_pocket.total_ms` | 1284.4 (1368.0) | 1245.9 (1341.3) | 207.7 (213.0) | — | — |  |
| `add_sketch.total_ms` | 314.8 (321.7) | 253.5 (271.4) | 64.9 (65.7) | — | — |  |
| `inspect_warm_ms` | 17.8 (18.6) | 16.5 (16.9) | 6.6 (7.7) | 47.7 (48.6) | 58.7 (66.7) |  |
| `inspect_after_change_ms` | 130.0 (133.8) | 56.9 (59.5) | 31.5 (34.4) | 306.9 (312.1) | 310.1 (329.4) | 20 |
| `checkpoint_ms` | 1667.1 (1760.9) | 1755.7 (1770.1) | 292.7 (299.3) | 302.9 (343.3) | 326.9 (340.3) | 16 (phase1) |
| `preview_first_ms` | 8657.0 (9140.3) | 8715.1 (10413.8) | 811.3 (851.4) | 1331.1 (1359.3) | 1481.9 (1512.4) | 50 (phase1) |
| `preview_update_ms` | 7186.4 (7723.4) | 7192.2 (8182.8) | 564.8 (587.7) | 1118.5 (1139.6) | 1249.1 (1298.2) |  |
| `kurtshape_open_ms` | 2122.0 (2177.3) | 2214.2 (2283.4) | 205.6 (206.6) | 472.4 (483.5) | 461.5 (480.3) |  |
| `native_open_ms` | 2003.3 (2039.4) | 2185.2 (2278.6) | 166.0 (171.0) | 249.7 (256.2) | 283.0 (295.5) |  |
| `total_rebuild_ms` | — | — | — | 528.8 (542.8) | 551.5 (556.1) | 4468 (studio 1.5x) |
| `selector_evaluation_ms` | — | — | — | 211.8 (218.8) | 234.0 (236.1) |  |
| `auto_scope_sync_ms` | — | — | — | 15.9 (16.4) | 17.1 (18.1) |  |
| `tip_edit.selector_evaluation_ms` | 0.0 (0.0) | 0.0 (0.0) | 0.0 (0.0) | 651.6 (810.8) | 710.6 (906.1) |  |
| `tip_edit.auto_scope_sync_ms` | 0.0 (0.0) | 0.0 (0.0) | 0.0 (0.0) | 444.0 (652.6) | 491.1 (712.1) |  |
| `upstream_edit.selector_evaluation_ms` | 0.0 (0.0) | 0.0 (0.0) | 0.0 (0.0) | 446.6 (456.9) | 508.3 (518.6) |  |

Fixtures: plate60 = 600 mm plate with 60 pocketed holes (132 objects, 66 faces); plate20 = 20 holes (52 objects); studio = U2 fixture with 30 base features, 4 parts, 11 selector consumers and 2 scoped operations (164 objects).

Reading: `tip_edit.overhead_ms` is controller work outside native recompute (inspection, intent digest, selector/scope reconciliation). `preview_*` here is the synchronous in-process `ExtrusionEvaluator` path (the wire `preview` op and the headless contract), not the GUI's private worker, so it bounds what the worker must hide. `checkpoint_ms` is the synchronous native `saveCopy` + verification that the GUI still runs on the Qt thread at idle. `inspect_after_change_ms` is the cost the GUI pays on the first tick after any model change.

## Repeat run (plate60, measure=false, ~15 min later)

| Metric | Run 1 median (p95) | Run 2 median (p95) | Delta |
|---|---|---|---|
| `tip_edit.total_ms` | 481.4 (488.8) | 493.2 (503.3) | +2.5 % |
| `tip_edit.overhead_ms` | 65.4 (68.4) | 65.9 (68.8) | +0.7 % |
| `tip_edit.native_recompute_ms` | 416.2 (423.4) | 427.4 (434.5) | +2.7 % |
| `upstream_edit.total_ms` | 6916.7 (7414.7) | 7610.8 (7626.9) | +10.0 % |
| `add_pocket.total_ms` | 1245.9 (1341.3) | 1371.2 (1402.6) | +10.1 % |
| `inspect_warm_ms` | 16.5 (16.9) | 18.4 (18.8) | +11.2 % |
| `inspect_after_change_ms` | 56.9 (59.5) | 56.1 (64.3) | -1.4 % |
| `checkpoint_ms` | 1755.7 (1770.1) | 1826.6 (1857.8) | +4.0 % |
| `preview_first_ms` | 8715.1 (10413.8) | 9518.6 (9777.7) | +9.2 % |
| `preview_update_ms` | 7192.2 (8182.8) | 7853.5 (8171.2) | +9.2 % |
| `kurtshape_open_ms` | 2214.2 (2283.4) | 2217.7 (2256.1) | +0.2 % |

Both plate60 measure=false runs agree within the noise expected from concurrent agent activity; the ordering of costs (native recompute on upstream edits ≫ synchronous preview ≫ open ≈ checkpoint ≫ tip-edit overhead ≫ inspection) is stable.
