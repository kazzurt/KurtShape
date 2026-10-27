# Session iteration regression

The completed Dodec fixture's cartridge recipe exposed the cost of one full inspection
after every small sketch edit. Its original sequence constructs the flange, neck, collar,
six fork backings, three support pads and five groups of holes, promotes neck length to
a parameter, then checks, saves and exports the finished native component.

The opt-in `Session.headless(..., batch_helpers=True)` or `Session.bridge(...,
batch_helpers=True)` groups the existing helpers into small atomic batches. Circle creation
also uses the existing typed `sketch_circle` shortcut: there is no geometry to validate in
the intermediate empty sketch, so that redundant recompute disappears. No controller
validation, mutation identity or reconciliation check is removed. The default remains
unbatched; the opt-in changes undo grouping to one entry per helper.

Measured on the bundled FreeCAD 1.1.4 / OCCT 7.8.1, isolated headless runs, October 21, 2026:

| Cartridge recipe metric | Separate helper operations | Batched helpers |
|---|---:|---:|
| Wall time, two runs | 29.04 / 28.89 s | 23.42 / 23.25 s |
| Requests | 89 | 48 |
| Full inspections | 88 | 47 |
| Controller recomputes | 119 | 113 |
| Decoded response JSON bytes | 6,646,938 | 4,524,950 |

This is about 19.4% lower mean elapsed time, 46.1% fewer requests, 46.6% fewer inspections,
5.0% fewer recomputes and 31.9% fewer response bytes. Wall time is local evidence, not a
performance guarantee; other development processes were running. Counts are deterministic
for this recipe. Response sizes use compact UTF-8 JSON of decoded responses, excluding
HTTP framing and the SDK constructor's capability/schema requests. Each run includes native
geometry validation, FCStd save, STEP export and final measured inspection. The source
fixture recipe is unchanged; runs write separate deliverables in the regression workspace.

`Session.batch(steps, preview=True)` is the explicit helper for risky changes. It previews
the exact steps and commits only an accepted proposal at its explicit base revision. It
does not silently split, rebase or retry unknown outcomes. See the small executable
[washer example](../examples/session_batch_helpers.py). Session request ledgers now record
response bytes as well as elapsed milliseconds to support workload-specific profiling.

Live session discovery and explicit open/fit are described in the
[agent quickstart](AGENT_QUICKSTART.md#discover-and-explicitly-select-a-delivery-session).
Discovery never targets a benchmark or visible session automatically. Older session files
have unknown visibility until their owner chooses to restart; no restart is required or
performed by discovery.
