# Windows friends preview — 2026-10-17

> **Archived 2026-10-21 by the slice A/B work:** a dated handoff; the current entry points are
> [README.md](../../README.md), [AGENTS.md](../../AGENTS.md), [docs/OPERATIONS.md](../OPERATIONS.md) and
> [docs/COOKBOOK.md](../COOKBOOK.md). Moved from `docs/SHARING_STATUS.md`; below this banner only its three
> relative links changed (they now start with `../`).

This handoff prepares the current `main` application for other Windows users.
Its modeling baseline is `f57d59267857ad32c302d2ae6e6c1368ce3c6a68`; it does not
merge unreviewed feature branches or implement the Fable backlog wholesale.

## Included

- Native editable sketches, extrusions, cuts, fillets and chamfers; shared Part
  Studio history, rollback, Undo/Redo, STEP/STL export and basic assemblies.
- The October 16–17 bridge additions: arcs, arbitrary datum-plane frames,
  connected polylines, native Hole, selector parameter filters, multi-edge query
  references and pattern `include_source`. Some are typed operations without
  dedicated toolbar dialogs; query `capabilities` and read the operation contract.
- `setup.ps1`: pinned runtime installation and an isolated end-to-end native
  smoke check; `tools/assistant.ps1` uses bundled Python for agent connections.
- Portable first-run save locations under `<checkout>/projects`. Existing
  settings retain their legacy implicit grants and explicit chosen folders.
- A concise README, Windows/agent guides, repository-local AGENTS/CLAUDE entry
  points, MIT license for original code, and third-party notices.
- Hosted test scratch-root correction and unused-import/assignment cleanup.
  The assertions and accepted test coverage are retained.
- The full Fable review, backlog and supporting artifacts, labeled with their
  original evidence and verification limits. Those findings describe the
  baseline review; this document records subsequent setup/CI changes.

## Validation

- Fresh isolated Windows regression: **619 cases, 612 passed, seven skipped,
  zero failures/errors**. Three skips require private external examples; four
  are opt-in performance tests. Source hashes were unchanged and rechecked
  against the final application/test files.
- Clean source-only install: the official 418 MB archive was downloaded,
  checksum-verified and extracted in a separate folder with no copied profile
  or runtime. Windows PowerShell 5.1 setup passed **18 smoke checks**, including
  native save/reopen, Undo/Redo, STEP and STL export. Repeat setup passed.
- Missing 7-Zip was rejected before downloading; an invalid cached archive was
  rejected before extraction. The checksum was never bypassed.
- A private offscreen app started and answered `capabilities` and
  `list_documents` through the bundled-Python wrapper. Its process was stopped
  after the check; no user document was opened or mutated.
- Ruff 0.16.10: clean. Documentation links and Git whitespace checks: clean.

[Compact evidence and source hashes](../sharing-release/validation-2026-10-17.json).
The [Windows workflow](https://github.com/kazzurt/KurtShape/actions/workflows/windows-ci.yml)
records hosted results after push and now also exercises newcomer setup under
Windows PowerShell. The earlier Fable report describes the baseline separately.

The first hosted Windows 2022 run reproduced all 612 passes/seven skips and
passed the 18-step setup. Its final hygiene check rejected the new empty
`projects/` directory. The check now permits that empty destination while still
rejecting files placed there or any other unexpected repository changes.

## Known limitations to tell testers

- This is a preview, with ongoing sketch/status/viewport polish documented in
  the [review](../fable-deep-review/FABLE_REVIEW.md). Performance on large models
  can stall during snapshot capture, save and committed recompute.
- Pattern-reference and cross-body Mirror work on separate branches is not
  included by this sharing change. A Mirror link-scope warning can still occur.
- Assembly parts are embedded snapshots; editing a source part does not update
  the assembly automatically. Advanced mates and nested assemblies are deferred.
- Slow bridge operations need explicit request-status reconciliation; the
  [agent guide](../AGENT_QUICKSTART.md) describes safe retries. The current app does
  not report the loaded source commit in its title/capabilities. A setup report
  identifies checked source only; save and relaunch after updating.
- Cylindrical Move face, retained-error deletion and further Sweep improvements
  remain separate work. Do not assume all audit suggestions are implemented.
- Source conversion is separate from STEP geometry import. Private Onshape
  examples and the author's CAD projects are not needed or bundled for setup.
- Headless validation does not establish graphics, DPI or mouse behavior on a
  friend's machine. Perform the brief interactive check in the Windows guide.

The user's already-running CAD session and original model files were not
restarted or modified during release preparation.

## Next development step

Collect short installation and modeling reports from friends, then address a
bounded usability increment from the Fable backlog. Prioritize build identity,
bridge outcome reconciliation and useful error/status feedback before broad
visual redesign. Keep experimental branches separate until reviewed and tested.

## Contract 3.2 — final (2026-10-19)

Contract 3.2 (validated edits, model images, parameters, batches and bridge
basics) was implemented unit by unit from the integration plan in
`runtime/contract-3.2/specs/integration.md` (untracked, with the area specs and
design probes beside it). Serial units U1–U7 each own `core.py`, `studio.py` and
`ui.py` while active; N1–N5 add new files only; U8 follows U2d and U4; U9 writes
the docs and examples; U10 verified the final tree, which also carries the fixes from
Fable's independent review and a separate Codex plane-visibility change (see U10).
Nothing is committed.

The 3.1 baseline is frozen in `runtime/bench/f31` (src tree `dbb163f9…`, 58
files, `SHA256SUMS.txt` verified). Every baseline report is listed with its
command, tree hash, system busy % and timestamp in
`runtime/bench/f31/baseline/INDEX.json`.

| Unit | Scope | Status | src tree | Tests run (report, counts) | Deviations | Decisions for Kurt |
|---|---|---|---|---|---|---|
| U0 | Baseline freeze, verification tooling | done (2026-10-17; review round 1 fixed) | `dbb163f9…`, unchanged; no `src/` writes | see U0 below | see U0 below | see U0 below |
| N1 | Loaded build identity (`build_identity.py`, `BuildIdentityTests`; new files, plus its `SUITES["bridge"]` line) | done (2026-10-18; review round 1 fixed); wired in by U2a | see N1 below | see N1 below | see N1 below | see N1 below |
| N2 | Model render (`model_render.py`, `ModelRenderTests`; new files, plus its `SUITES["native"]` line) | done (2026-10-18; review round 1 fixed); wired in by U4 | see N2 below | see N2 below | see N2 below | see N2 below |
| N3 | Render worker (`render_worker.py`, `RenderWorkerLifetimeTests`; new files, plus its `SUITES["native"]` line) | done (2026-10-18; review round 1 fixed); wired in by U4 | see N3 below | see N3 below | see N3 below | see N3 below |
| N4 | Operation schemas (`operation_schemas.py`, `OperationSchemaTests`; new files, plus its `SUITES["native"]` line) | done (2026-10-18; review round 1 fixed); wired in by U2a | see N4 below | see N4 below | see N4 below | see N4 below |
| N5 | Parameter-panel widgets (`parameter_panel.py`, `ParameterPanelTests`, `SectionLayoutTests`; new files, plus their `SUITES["native"]` line) | done (2026-10-18; review round 1 fixed); finalised and wired in by U7 | see N5 below | see N5 below | see N5 below | see N5 below |
| U1 | Shared dispatch pipeline, contract revision 2 | done (2026-10-18; review round 1 fixed) | `63d60bed…` (63 files, `run_ab.tree_sha256`) | see U1 below | see U1 below | see U1 below |
| U2a–d | Schemas and build identity; lifecycle and failure records; compact inspect; transport and quiet refresh | done (2026-10-18; review round 1 fixed) | `1cceef95…` (63 files, `run_ab.tree_sha256`) | see U2 below | see U2 below | see U2 below |
| U3 | Result validation on edits and rebuilds | done (2026-10-18; review round 1 fixed) | `f63c12dc…` (64 files, `run_ab.tree_sha256`) | see U3 below | see U3 below | see U3 below |
| U4 | `render_view` | done (2026-10-18; review round 1 fixed; independent review follow-up fixed) | `85350243…` (65 files, `run_ab.tree_sha256`) | see U4 below | see U4 below | see U4 below |
| U5 | Parameters backend | done (2026-10-18; review round 1 fixed) | `35015d85…` (66 files, `run_ab.tree_sha256`) | see U5 below | see U5 below | see U5 below |
| U6 | Atomic batches | done (2026-10-18; review round 1 fixed) | `de9e70b2…` (67 files, final tree) | see U6 below | see U6 below | see U6 below |
| U7 | Parameters panel | done (2026-10-18; review round 1 fixed) | `de9e70b2…` (67 files, final tree) | see U7 below | see U7 below | see U7 below |
| U8 | Client reconciliation | done (2026-10-18; review round 1 fixed) | `de9e70b2…` (67 files, final tree) | see U8 below | see U8 below | see U8 below |
| U9 | Docs, examples, walkthrough | partly (docs and examples landed with U5–U8; the five examples ran end to end in U10's private smoke; no formal walkthrough runner) | — | see U10 below | see U10 below | see U10 below |
| U10 | Final verification; Fable independent review fixes R1, R2, R5, R6 | done (2026-10-19) | `a3e14aaa…` (67 files, `run_ab.tree_sha256`; build `3dd512eb…`; includes Codex's plane-visibility `ui.py`) | see U10 below | see U10 below | see U10 below |

### U0 — baseline freeze and verification tooling

Tooling (no product behaviour changes):

- `tools/run_native_tests.py`: `--only MODULE[.CLASS[.METHOD]]` (repeatable; a
  bare module selects its registered classes; unregistered names are refused;
  refused when `KURTSHAPE_WRITE_EVIDENCE` is set), `--perf` (sets
  `KURTSHAPE_PERF=1` in the suite children), and a `selection` field on partial
  reports. A `--only` report is never the regression result.
- `tools/native_validation_snapshot.py`: `content_view` (strict record minus
  `gui`, every `shapes.*.hash_code`, and the KurtShapeProject row's
  `state`/`status`), `without_gui`, `gui_invariants` (camera through the pure
  `normalise_camera`, which blanks only nearDistance/farDistance).
- `tests/test_build_status.no_result_checks` (BRepCheck gate, studio result
  checks, exact boxes and native recomputes all zero);
  `tests/support.offscreen_qt_fonts`; `tests/perf_fixture.build_drill` /
  `add_flute` (moved from `test_result_checks`, which imports them back).
- `tools/perf/interaction_probe.py`, `run_ab.py` (pinning, load gate, retries,
  tree check, process list) and `compare_ab.py` (§4.4 (a)/(b)/(c)), promoted from
  the design prototypes; `bench_core.OPTIONAL_SECTIONS`.
  - `run_ab` re-runs a step over the 32 % load gate once by default
    (`--retries 1`) and records the concurrent pythonw/python/freecad processes
    with `Get-CimInstance Win32_Process` (name, PID, parent, creation time,
    command line) at the start and end.
  - `compare_ab` pools only what §4.4(a) and integration §2 allow: a step over
    `--max-busy 32` is discarded (per step, not per run folder;
    `--keep-over-gate` pools it for diagnosis and the comparison then cannot
    pass); so is a step that exited non-zero or has no report, every step of a
    run whose run-summary or supplement says `source_unchanged:false`, and a
    folder without `run-summary.json`. Each side must hold one src tree,
    recorded by every pooled run (A must be `dbb163f9…` unless
    `--expect-a-tree any`); supplements must have run the same fixtures; and each
    step both sides measured must pool the same number of runs per side, so a
    discarded step is re-run and its folder added. Any of these makes the
    report `valid:false`, `passed:false`, with `invalid_reasons`.
  - Count allowances are per counter: `--count-allow COUNTER:FAMILY`, where
    FAMILY is the counter key the probe records (call families keep `_ms`, e.g.
    `brepcheck_calls_by_family:studio.edit_extrusion_add_ms`; timed families
    drop it, e.g. `…:drill.helix_upstream_edit`). A bare family is refused.
    Native recompute counts follow C34: B above A is always blocking, B below A
    passes only when listed (`native_recomputes_by_family:FAMILY`); long-family
    recompute differences feed `passed`. Counters that differ between runs of
    one side are always blocking. Families only B measures (new 3.2 families)
    are listed in `count_families_only_in_B`, not compared.
  - `interaction_probe` detects the 3.2 families (compact inspect through a
    read-only `list_documents detail:"compact"` request, since it has no
    operation of its own) but measures none of them yet; an offered family it
    does not measure is `available_unmeasured`, listed in
    `families_32_unmeasured`, and `compare_ab` repeats it as a warning.
- `tools/private-session.ps1` (private app under `runtime\private\<name>`;
  `-Stop` checks PID, start time and the session's `user.cfg` on the command line).
- `tools/run_gui_recipe.ps1`: recipe `interaction-idle`
  (`tools/interaction-idle-validation.FCMacro`, with `-PreviewSource`),
  `-SeedUserConfig`, `-Parameters` / `BENCH_PARAMETERS`; `bench_gui.FCMacro`
  records `tick_after_read_request_ms` (a real loopback inspect served by the
  timed tick) and checks `parameter_section.created` when that section exists.
- New test class `test_validation_tooling.ValidationToolingTests` (native, 13
  tests after review round 1). It also pins the A/B rules above, the `--only`
  refusals with and without a parent `KURTSHAPE_WRITE_EVIDENCE` (so
  `run-checks.ps1 -WriteEvidence` stays green), `--perf` reaching only the suite
  children, the `selection` report field, `run_ab`'s retry default and process
  query, the probe's family detection, and `native_validation_snapshot.normalise_camera`
  (the GUI branch of `gui_invariants`, now a pure helper). `run_native_tests`
  hashes `compare_ab.py`, `run_ab.py` and `interaction_probe.py` into
  `source_unchanged`, since the test imports them.

Tests (reports under `runtime/bench/f31/baseline/u0/tests/`):

- Unit tests, `--only test_validation_tooling test_result_checks.ResultCheckTests
  test_geometry_queries test_build_status`: 43 tests, 39 passed, 4 `perf:` skips
  (`only-unit-final`). `--perf --only test_build_status.StatusPerformanceTests`:
  4/4 (`only-perf-status`).
- Full regression (`run-checks.ps1`, 636 cases = 630 + 6 new; one more test was
  added afterwards): run 1 had one intermittent failure,
  `test_sketch_arcs…test_d_profile_free_arc_then_joined_line_stays_parametric`
  (`stale_revision` at its pad). It passed 3/3 alone and in run 2 (632 passed, 4
  `perf:` skips, no `selection` field, `source_unchanged` true). No code that
  runs before that test changed in U0, so the flake predates U0. Final U0 tree
  (`full-regression-final`): **637 cases, 633 passed, 4 `perf:` skips, 0
  failures**, no `selection` field, `source_unchanged` true.
- Review round 1 (same `src/` tree): `--only` on the four unit targets
  (`only-unit-r1`): **49 tests, 45 passed, 4 `perf:` skips**, 0 failures,
  `source_unchanged` true. ValidationToolingTests run as a `-WriteEvidence`
  regression's native child would run it (`KURTSHAPE_WRITE_EVIDENCE=1` in the
  child, `--only` refusal bypassed): 13/13, `validation/` untouched
  (`wev-child-r1`). Full regression (`run-checks.ps1`, `full-regression-r1`):
  **643 cases (637 + 6 new), 639 passed, 4 `perf:` skips, 0 failures**, no
  `selection` field, `source_unchanged` true; all three reports hash the same
  120 source files as the final tree. An earlier run on the tree before the
  last docstring edit (`full-regression-r1a`) hit the known intermittent
  `SketchArcTests…test_d_profile_free_arc_then_joined_line_stays_parametric`
  `stale_revision` once (the class runs before any U0 test). A pinned `run_ab` smoke (A = f31, B = live,
  `--fixtures repro,drill --repeat 2`, `smoke-ab-r1`) ran while other work kept
  the machine 36–46 % busy: each side re-ran its supplement once, both attempts
  stayed over the gate, and `compare_ab` refused (`valid:false`, both steps
  discarded); with `--max-busy 100` the same folders compare valid, 6 metrics,
  counters equal.
- Smoke checks: `run_ab` + `interaction_probe` on f31; private session start,
  `capabilities`/`list_documents` with an explicit session file, `-Stop -Remove`;
  `-SeedUserConfig` (a marker group survived into the second process); refusals
  of `bench_core` sections without an implementation and of misplaced runner
  options.

Baselines on the unchanged tree (machine quiet, 14–18 % busy):

- Pinned (`0xffff`) `interaction_probe --fixtures repro,drill,studio,plate
  --repeat 5` from f31 (14.6 % busy): studio `edit_extrusion` 581 ms, upstream
  `set_parameter` 415, `rebuild` 516; drill helix upstream edit 385 (0 checks),
  Flute2 1313; plate60 tip `set_parameter` 421, `rebuild` 6904. Per-family
  counters equal the design pinned runs; the item-1 repro still accepts the
  emptying edit. `probe/pinned-f31/`.
- bench-gui `-Holes 60 -Repeat 5` ×2: `panel_refresh` 10.7/9.7 ms,
  `tick_after_refresh_flag` 18.2/21.3, new `tick_after_read_request` 49.5/57.0.
- interaction-idle ×3 (+1 trial): 13 checks each; idle 5 s total tick 51–53 ms,
  tick max 3.3–4.3, heartbeat max 29–36, 0 dispatches, 10 syncs; bridge inspect
  138–193 ms with 2 inspect dispatches (3.2 expects 1); exact status polls
  answered `started`, final status `completed`.
- responsiveness-preview `-Holes 60 -Repeat 3`: 3 passing runs (28 checks): first
  proxy 24.0–33.5 ms, depth proxy 13.6–15.2, worker heartbeat max 88–115.
- GUI recipe matrix (integration §4 step 3 list, 21 recipes): 12 pass
  (design-surface 408 checks, parts-refresh 91, extrusion-edit 43, dress-up-edit
  57, onshape-workflows 45, sketch-plane-editor 27, step-import 19, assembly 58,
  assembly-step 38, everyday-ui 46, presentation-scheduling 73, step-export 91).
  9 are pre-existing failures, reproduced identically (same error, same check
  count) with the pre-U0 runner: history-selection, rollback-history,
  part-studio, interface and headless-open (`path_outside_workspace` when they
  save into their session; the portable first-run grant covers only
  `<checkout>/projects`); history-lifecycle (its Extrude is now rejected
  "added no material" by the 3.1 result checks); carrier-spike ("Feature
  canceled"); ui-refinement (toolbar coverage at 1200 px); geometry-check (fewer
  than 2 GUI heartbeats while its child ran: the child finishes too fast).
  responsiveness-preview fails intermittently at "Trial 0 retains all
  source/native/GUI invariants" with either runner (2 of 5 and 2 of 3), and
  always while the fixture file was read-only.

Deviations from the plan: the frozen tree sits at `runtime/bench/f31` itself
(not a `frozen-3.1` subfolder) so worker paths stay short; `--only` also takes a
bare module; interaction-idle's `passed` covers functional facts while the
§4.4(d) guards are recorded in `guards` (the 3.1 bridge inspect gives 2
dispatches, so that guard reads false until U2d); `-PreviewSource` is refused
for other recipes; the probe takes the drill helpers from the live checkout on
both sides; `compare_ab` rule (b) allows the B side's check ms per operation
(family total / samples). The review round 1 fixes added more: `compare_ab`
is stricter than §4.4 states (it also rejects unequal pooled run counts per
step, mixed supplement fixtures, failed steps and folders without a
run-summary, and refuses bare-family `--count-allow`); design-3.1 reports
predate `source_unchanged` and are compared with a warning, not refused. The
probe detects but does not measure the four 3.2 families (§4.5): each owning
unit adds its metrics and its name in `interaction_probe.MEASURED_32` —
compact inspect U2c, `render_view` U4, parameters U5, batch U6 — and until
then the family reads `available_unmeasured`. In `INDEX.json` the 38
design-3.1 copies now carry their production time (the origin file's mtime,
content verified by sha256; the copies' mtimes were reset to it) instead of the
copy time, and every entry has a `timestamp_source`.

For Kurt: the 9 failing GUI recipes and the intermittent
responsiveness-preview and SketchArcTests failures predate 3.2. Fixing the
recipes' save destinations (grant the session folder) and history-lifecycle's
now-rejected Extrude is outside U0; later units judge "every recipe that
passed in U0 must pass" against the 12 passes above. `compare_ab` enforces
C34 literally: no family may gain native recomputes. If U3's edit validation
runs an unrefined retry (`_recompute` inside the request), that family gains r
recomputes and the comparison fails; U3 then reports it as a decision rather
than an allowance.

### N1 — loaded build identity (new files)

`src/kurtshape/build_identity.py` (stdlib only, F5 §2.1) and
`tests/test_build_identity.py::BuildIdentityTests` (bridge suite, 14 tests). No
other module imports it yet: U2a wires it into `core` (first kurtshape import),
`capabilities`/`diagnostics`, the session file, export/STEP provenance, the
three worker launchers (`KURTSHAPE_WORKER=1`) and `run_native_tests`
(`kurtshape_build_sha256`).

Hand-over text for §3.2.5 (U2a drafts it) and §3.2.7:

- `capabilities.build` = `identity()`: `{id, source_sha256, source_files,
  source_dir, loaded_at, pid, python, workers_load_from_disk, git, on_disk}`.
  `source_sha256` is SHA-256 over `<name>\0<sha256 of the LF-normalised file>\n`
  for every `*.py` directly in the package, in name order; `id` is `src-` plus
  its first 16 hex digits. CRLF and LF checkouts of the same sources match.
- `git` always carries `state`, `head` and `ref` (at load), `head_now` (re-read
  from the git files on each call) and `head_moved`; outside a checkout they are
  null/false with `state:"unavailable", reason:"not a git checkout"`. `state` is
  `pending` until the one background comparison of the process finishes, then
  `ready` (`dirty`, `modified`, `untracked`, `deleted` against the commit
  checked out at load; a file matches if git stores either its LF or its raw
  bytes) or `unavailable` with a `reason`. The comparison runs
  `git -c safe.directory=… -C <checkout> ls-tree -r -z <head at load> -- <package>`
  in a daemon thread started by the bridge or the first `identity()` call, never
  at import: no window, stdin closed, `GIT_DIR`-style overrides dropped. A git
  that has not answered after 10 s is killed with its child processes
  (`taskkill /T`; Git for Windows' `cmd\git.exe` is a launcher whose real git
  holds the pipes) and its pipes get 2 s more, so `pending` ends within about
  17 s.
- `on_disk` (`matches_loaded`, `changed`, `added`, `removed`) stats the package
  on every call and re-reads only files whose size or mtime changed.
- If the package cannot be read at startup, `build` is `{state:"unavailable",
  reason:"<exception>: …"}` and the session-file and provenance views are
  `{state:"not_captured"}`. Workers capture nothing and start no thread.
- `summary()` (session file) is `{id, source_sha256, source_dir, loaded_at,
  git_head}`; `provenance()` (export/STEP) is `{id, source_sha256, git_head}`,
  constant for the life of the process.
- `python -B -m kurtshape.build_identity [package_dir]` prints `{source_dir,
  source_sha256, id, source_files}`. A directory that lacks `__init__.py`,
  `contract.py` or `core.py` (for example the checkout root) is not a package:
  the CLI exits 2 with a JSON error on stderr that names `<dir>\src\kurtshape`
  when that is a package, and `build_verdict()` (for `--build-check`) answers
  `unknown`. Older trees without `build_identity.py` (KurtShape-green, -sweep)
  still count as packages. Otherwise the verdict is `current` (same directory
  and digest), `stale` (same directory, other digest), `different_tree` or
  `unknown` (no identity from the app).
- Limitations (§3.2.7): only SHA-1 repositories are compared (a SHA-256
  repository reports `unavailable`, "unsupported git object format", instead of
  every file modified); modules that `core` imports lazily are read from disk
  at first use, so `on_disk.matches_loaded:false` means restart to be sure; a
  git that escapes the tree kill is left to finish on its own after the probe
  has already reported the timeout.

Runner registration: `SUITES["bridge"]` now lists
`test_build_identity.BuildIdentityTests` (added in N1's review round 1, while no
serial unit edits `run_native_tests.py`; U2a only confirms it). One SUITES line
per unit does not unblock `run_native_tests.py`: its inventory gate refuses to
run any suite, full or `--only`, and reports `passed:false` while any test
class is unregistered. At 00:17 on 2026-10-18 it still listed
`test_model_render.ModelRenderTests` (N2),
`test_operation_schemas.OperationSchemaTests` (N4) and
`test_parameter_panel.ParameterPanelTests`/`SectionLayoutTests` (N5); N3
registered its class meanwhile (`runtime/test-tmp/n1/r1/probe-gate-final.json`).

Final state (2026-10-18 00:17): `build_identity.py` `46b0ffa4…`,
`test_build_identity.py` `26200ba4…`, `run_native_tests.py` `d7e23b9c…` (with
N3's line); src tree `838364de…` (63 files, `run_ab.tree_sha256`), package
digest `src-4df1ca8c525be0ea`. Other units kept writing `src/` and `tests/`
during this round, so every run below waited for 75 s without writes, and runs
that reported `source_unchanged:false` were discarded (four).

Tests (reports under `runtime/test-tmp/n1/r1/`):

- Bridge suite through the class harness, `BridgeTimeoutTests` +
  `NativeBridgeStatusTests` + `BuildIdentityTests` (`bridge-final-1.json`):
  **33 tests, 33 passed**, `source_unchanged` true, loopback allowed.
- The runner's own child with the real SUITES (`child_only.py`, because the
  parent's `--only` is refused by the gate above): `--in-process bridge --only
  test_build_identity` **14/14** (`identity-child.json`), and `--in-process
  native --only test_validation_tooling.ValidationToolingTests` **13/13**
  (`tooling-child.json`; it checks every SUITES entry routes). Both
  `source_unchanged` true. Run through `run_classes.py`, ValidationToolingTests
  errors in `test_only_maps_names…` because that harness replaces
  `SUITES["native"]` in its child; that is a harness artifact, not a failure.
- Mutation probe (`mutate_r1.py`, private copies): all 19 mutants of the fixed
  behaviour fail at least one test, and the unmutated copy passes 14/14
  (`mutation-results.json`).
- Probes on the final module, each recording `build_identity_py_sha256`:
  `probes/identity-live-and-worktrees-r1.json` (live checkout `ready`, dirty
  with the 3.1 and N-unit files; KurtShape-green and -sweep `ready`, clean,
  `different_tree`), `probes/identity-cost-r1.json` (`identity()` 4.0 ms,
  `compare_disk()` 3.6 ms, startup snapshot 15.8 ms; best of 20/5), and
  `r1/probe-timeout-fixed.json` (a launcher holding the pipes: 4.1 s for a 3 s
  limit, both processes gone; the old `subprocess.run` path waited 30.1 s; the
  real `cmd\git.exe` with a hanging alias: 2.3 s for a 1 s limit). The earlier
  `identity-*.json` files predate round 1.

Deviations: the plan keeps N-units out of SUITES and docs; this round added
the bridge SUITES line and this section on the orchestrator's instruction (the
N1–N5 row was split the same way N3 split its own). F5 §9.1 lists 10 tests;
there are 14 (module stdlib-only, SHA-256 repository, timeout tree kill,
startup capture failure). `test_checkout_digest_differs_from_loaded_tree` checks
`build_verdict()` and the CLI, since `assistant_client.build_check` is U8 work;
U8 pins the client. "`pending` in < 50 ms" is asserted on the fastest of three
calls (each under 1 s). SHA-256 repositories are refused, not compared. The
package rule is the three files every KurtShape tree has, not
`build_identity.py`, so older trees keep their `different_tree` verdict.

For Kurt (or the orchestrator): pick one rule for the N-unit classes the gate
still lists, before U1 needs `run_native_tests.py`: register each standalone
class now (as N1 and N3 did) and hold N4's `OperationSchemaTests` until U2a
(it needs the U2a wiring), or give U-unit runs an explicit allow-list of
pending classes. Until then U1's `--only` runs and its full regression cannot
run through the runner.

### N2 — model render (new files)

`src/kurtshape/model_render.py` (F2 §4, productionised `softrender.py`; numpy,
Pillow, FreeCAD, Part and MeshPart only, never a `kurtshape` import) and
`tests/test_model_render.py::ModelRenderTests` (native suite, 28 tests). The
worker child reaches it through N3's default renderer
(`render_worker.render_scene` → `render_job`); U4's `render_jobs` builds the
scene and owns the request limits. Files at completion: `model_render.py`
sha256 `bf9936726f7f…`, `test_model_render.py` `f88fc1319cf0…`,
`run_native_tests.py` `7f9a960c6374…`; src tree `62c6b173b110…` (63 files,
`run_ab.tree_sha256` rule).

Interface for U4:

- `render_job(scene, settings, out_dir, *, metadata, limits)` writes
  `view-<k>.png` or `sheet.png` and returns JSON-safe rows: images (file, size,
  sha256, camera with `pixel_from_world`, tiles, highlight rows `{label,
  visible, visible_px, ghost_px, rendered, anchor_px, label_box_px}`, section
  `{origin, normal, cap_faces, cap_failures, cap_skipped_not_solid,
  overlapping_parts}`), `tessellation` `{tolerance_mm, requested_tolerance_mm,
  angular_deflection_rad, triangles, cap_triangles, highlight_triangles,
  coarsened, coarsen_steps, coarsen_ladder}`, per-part triangle counts,
  `non_solid_parts`, ordered `banners`, `note` (= `RESPONSE_NOTE`) and
  `phases`. `Scene.from_capture` reads the `scene.json` format N3 verifies.
- `limits` overrides `DEFAULT_LIMITS` `{coarsen_triangles 1.5M,
  coarsen_steps 3, max_triangles 2.5M, fragment_budget 2M, chunk_triangles
  32768, deadline_seconds 18}`; `deadline_seconds: None` turns the job budget
  off (tests only).
- The owner must check `frame:"highlights"` without a rendered match
  (`highlight_not_rendered`) and a scene with nothing to draw (`no_geometry`)
  before it starts a worker: the renderer raises them only as backstops, and
  through the worker they arrive as plain `render_failed` (pinned by
  `test_renderer_errors_on_the_worker_wire`).

Hand-over text (U4 writes §3.2.2; U4/U9 carry §3.2.6 and §3.2.7):

- §3.2.2, renderer paragraph: images are orthographic software renders of
  display meshes. Each part is meshed once per job by OCCT (whole shape, so
  faces meet without cracks) with a linear tolerance of 0.6 × the finest
  mm/px (rounded down to a power of two, clamped to 1e-4–2e-3 × the scene
  diagonal, doubled for draft) and an angular deflection of 0.25 rad. Above
  1.5 M triangles the mesh is coarsened (tolerance and angle doubled, the angle
  up to 0.5 rad) at most three times, stopping when a step removes less than
  10 %; above 2.5 M triangles, section caps and highlight faces included, the
  render is refused. Sections cap every solid separately; where two caps
  overlap, from two parts or from two solids of one part, they are
  cross-hatched and the pair is listed in `overlapping_parts` (a pair naming
  one part twice means its own solids overlap); caps that only touch are not
  listed. A face several highlights match is drawn in the colour of the
  highlight with fewer faces (the later one on a tie), and every one of them
  counts as visible. Images narrower than 320 px shorten the banners
  ("RETAINED · FAILED") and drop the scale bar and axis triad before the
  caption's "not a validity check".
- §3.2.6 rows produced by the renderer (through the worker):
  - `render_too_large`, `reason:"triangles"`: `triangles`, `limit`,
    `tolerance_mm` when the mesh stays over `max_triangles`; `triangles`,
    `views`, `budget_seconds` when the job exceeds its 18 s budget (the worker
    forwards these details; it is deterministic, so the owner's negative cache
    keeps it). `reason:"memory"` when an allocation fails.
  - `highlight_not_rendered` and `render_failed` `reason:"no_geometry"` are
    owner checks; if the renderer meets them it reports them, and the worker
    maps both to `render_failed` (`phase:"render"`).
- §3.2.7 limitations:
  - A render has an 18 s budget inside the 25 s worker limit. Meshing cost is
    dominated by OCCT on curved BSpline faces (about 160 ms per copy of the
    drill capture) and does not fall with coarsening, so scenes near the
    prescreen caps can run out of time: 76 drill copies (4940 faces,
    808 k triangles) at 2048×1536 take 16.1–17.3 s; seven views of 30 stacked
    drills at 1024×768 (1.15 M triangles at the end-on view's finer
    tolerance) end with `render_too_large{budget_seconds}` after 18 s. Near
    the limit the outcome depends on machine load.
  - Peak commit (PagefileUsage peak, in-process `render_job`, process
    included): 366 MiB for one drill at 1024×768 (2× supersampling), 489 MiB
    for 30 stacked drills (475 k triangles), 515 MiB for 40 drills at
    2048×1536 (486 k), 628–631 MiB for 76 drills at 2048×1536 (808 k), and
    621 MiB for the seven-view job that runs out of time. The 600 MiB target
    holds except at that prescreen extreme (round 0 measured 714–801 MiB at
    about 1.5 M triangles); the Job Object's 1536 MiB cap stays the hard
    bound. The fixed raster buffers of a 2048×1536 raster take about 300 MiB.
  - The silhouette test is slope-aware (a steep but continuous surface is not
    an outline), so end-on views have no line clusters; faint streaks can
    remain where steep helical faces meet (drill front view tip region:
    324 dark pixels at 0.25 rad, 308 at Part's 0.1 rad).
  - Overlaps narrower than about two supersampled pixels are not reported or
    cross-hatched (the same opening that keeps touching caps unreported).

Runner registration: `SUITES["native"]` now lists
`test_model_render.ModelRenderTests` after `RenderWorkerLifetimeTests` (review
round 1, on the orchestrator's instruction, as N1, N3, N4 and N5 did). With it
the inventory gate lists no class: `unassigned_test_cases()` is `[]`
(`runtime/contract-3.2/n2/fix-r1/probe_gate.out.txt`), so `--only` and full
runs execute again.

Tests (reports under `runtime/contract-3.2/n2/fix-r1/`):

- `ModelRenderTests` through the class harness (`runtime/bench/f31/run_classes.py
  --suite native`), twice (`final-classes-1.json`, `final-classes-2.json`):
  **28/28 each** (15.9 s, 15.2 s), no skips. The three files' hashes were
  equal before and after (`hash-before.txt`, `hash-after.txt`).
- The runner itself, now that its gate is clear: `run_native_tests.py
  --require-native --only test_model_render.ModelRenderTests --only
  test_validation_tooling.ValidationToolingTests --only
  test_render_jobs.RenderWorkerLifetimeTests` (`runner-only.json`):
  **68/68**, `source_unchanged` true, `unassigned_test_cases` `[]`. N3's
  default-renderer tests draw through the changed module.
- Full regression, the first since the N-units because the gate now passes:
  `run_native_tests.py --require-native --timeout 3600` with run-checks'
  isolation (`full-regression.json`, run dir
  `runtime/test-tmp/regression-run-20261018-013924-32488-6101f06f`):
  **796 tests, 792 passed, 4 perf skips** (native 724/720, bridge 33,
  shortcuts 33, workflows 6), `source_unchanged` true, `unassigned_test_cases`
  `[]`, 928 s. The 3.1 baseline was 630 cases; the rest are the N-units'
  classes.
- Mutation probe (`mutations.py`, `mut_parent.py`; private copies of the
  module): all 25 mutants fail at least one test and the unmutated copy passes
  28/28 (`mutation-summary-full.json`, then `mutation-summary-r2.json` after
  the last test change). They cover the 12 round-1 survivors (prototype
  silhouette rule, tolerance ×10, later cap wins, caption without the note,
  end-on edge rule, `two_sided` ignored, failed orientation sample culled,
  limits ×10, two-column sheets, memory mapping, unclipped model frame,
  1-px label threshold) and 13 for this round (Part's 0.1 rad mesher,
  per-face meshing, blind doubling, fixed angle, caps and highlights
  uncounted, no budget, winner-tag face visibility, order-only highlight
  colour, whole-compound caps, unopened overlap, suppressed highlight
  outline, no short banners, caption keeping the scale bar). Still not caught
  by cheap scenes, as in round 1: `SPAN_EPS = 0` and dropping the orientation
  sample (BRepMesh already returns outward triangles for these shapes).
- Probes: `p3-e*.out.txt` (scale, the review's `p3_scale.py`),
  `p4_coarsen_curve.json` (ladder), `p_memphase-final-*.out.txt` (commit per
  phase), `p_mesh2.out.txt`/`p_mesh3.out.txt` (Part's 0.1 rad vs 0.25/0.5 rad:
  counts, watertightness, chord error), `p_streaks.out.txt`,
  `determinism-seed1.json`/`-seed987.json` (identical across processes and
  hash seeds, the drill capture through MeshPart included), and the review's
  `p2_semantics`, `p9_small_bands`, `p10_bounds_touch` and `p11_compound_caps`
  rerun on the fixed module (`*.out.txt`). Images opened and checked: two
  highlights on one face (the one-face highlight on top, both labels solid),
  a pin pressed through a plate in one compound (cross-hatched pin, no hole),
  a 128-px failed build ("RETAINED · FAILED", "not a validity check"), and the
  drill iso/front and dodec iso at 0.25 rad next to the round-0 renders.
- Round 0 (implementer): `runtime/contract-3.2/n2/model-render-*`, 21/21.
  Review round 1 verification: `runtime/contract-3.2/review/N2-verify-r1`,
  21/21.

Deviations from F2 §4 (round 0 and review round 1):

- Meshing goes through MeshPart (whole-shape BRepMesh with an angular
  deflection) instead of `shape.tessellate(tol)`: Part fixes 0.1 rad, which on
  the captures gives 4.5–5.3× the triangles (drill 70148 vs 15576 at
  0.0625 mm) and makes the coarsening ladder almost useless (three doublings
  kept 43–113 % of the triangles; now 14–26 %). The count for the ladder
  comes from the C++ mesh, and each face is read back once.
- The ladder stops early when a step removes < 10 % and keeps the smallest
  mesh; caps and highlight faces count toward `max_triangles`.
- A wall-clock budget (`deadline_seconds`, 18 s) ends a job with
  `render_too_large{reason:"triangles", budget_seconds}` instead of the
  worker's 25 s `render_timeout` (review finding 1). F2 lists no such reason;
  "triangles" keeps the child's reason list (N3 `TOO_LARGE_REASONS`)
  unchanged.
- Silhouettes use a slope-aware depth step (F2 §4.9 says depth jumps of
  12 px): the end-on drill clusters came from silhouettes, not feature edges.
  Pinned by `test_end_on_edge_segments_dropped` (pyramid end-on image, plus a
  grazing self-occlusion that must stay dark). A highlighted face also gets an
  outline against the background now (`test_highlight_face_outline_against_background`).
- A highlight edge seen end-on (under 2 px projected) is visible when a sample
  passes the depth test (pinned in `test_edge_and_vertex_highlights_depth_tested`).
- Caps are sliced per solid (F2: one cap per part); a part's overlapping
  solids are reported as `[part, part]` in `overlapping_parts`.
- Highlight face visibility is computed per highlight, so highlights sharing a
  face are all visible; the colour policy (fewer faces on top) is new.
- Narrow images use shorter banner forms and give the caption priority
  over the scale bar and triad.
- `OPERATION_CONTRACT.md` is unchanged, because U1 creates the Contract 3.2
  skeleton; the text above is the hand-over (as N3 did).

Decisions for Kurt (defaults adopted, for confirmation):

- The 18 s job budget fails as a deterministic `render_too_large`, so N3/U4
  cache it for 10 minutes; under heavy machine load a render that normally
  fits could be refused and cached. U4 may treat errors that carry
  `budget_seconds` as transient instead.
- Display meshes use 0.25 rad (0.5 rad after coarsening) instead of Part's
  0.1 rad: same silhouettes within the pixel tolerance, slightly coarser
  shading on small curved faces, about a fifth of the triangles.

### N3 — render worker (new files)

`src/kurtshape/render_worker.py` (F2 §2.3, Job Object helper) and
`tests/test_render_jobs.py::RenderWorkerLifetimeTests` (native suite, 27
tests). No module imports it yet: U4's `render_jobs.RenderService` drives it and
adds `RenderJobTests`/`RenderOwnershipTests` to the same test module. Files at
completion: `render_worker.py` sha256 `c6a27829d2d0…`, `test_render_jobs.py`
`556c557a118b…`.

Interface for U4:

- `NativeRenderWorker(executable, session_dir, timeout=25, memory_limit=1536 MiB,
  renderer=None)` owns `<session>/render-jobs/render-*`. The owner writes
  `scene.json` (and any highlight BREPs) into `worker.folder`, then
  `submit(1, {scene_sha256, settings_digest, captures: [{name, path, sha256,
  bytes}], outputs: [{view, name, width, height}]})`; every capture path must
  lie inside the session folder. `poll()` returns None while the child runs and
  the response only after confirmed exit, or raises `RenderWorkerError` /
  `RenderTimeout`; then `child_error(response)` and `validated_images(response)`
  (rows with `path` inside the job folder, PNG signature, IHDR size, bytes and
  sha256 checked). `close()` never waits: the reaper deletes the folder and
  closes the Job only after confirmed exit. `diagnostics()` is cheap;
  `as_render_error(exc, timeout_seconds)` maps transport exceptions.
- The child runs below normal priority with `OPENBLAS_NUM_THREADS=OMP_NUM_THREADS=1`
  and a private environment, inside a Job Object (process commit cap,
  kill-on-close, die-on-unhandled-exception) assigned before its wake-up line.
  It verifies `scene.json` and every capture against its sha256 before any
  native import (the response's `native_modules_at_verify` is `[]`), never
  imports `core` and never opens a document. It resets FreeCAD's
  `_set_new_mode(1)` so numpy allocation failures raise `MemoryError`, and turns
  off abort fault reporting so a native abort exits at once.
- The default renderer `kurtshape.render_worker:render_scene` adapts
  `model_render.render_job(scene, settings, out_dir, metadata=, limits=)`. It
  builds the `Scene` from the shapes the child imported from verified bytes (no
  capture file is read twice). `scene.json` uses `Scene.from_capture`'s format
  (`parts[].brep`, `sketches[]`, `highlights[].rendered`/`ghost` name captures,
  `.brep` suffix optional) plus `settings`, `metadata` (PNG tEXt `document`,
  `revision`, `render_id`, `note`) and optional `limits`. The images the
  settings produce (`view-<k>.png` or `sheet.png`, with sizes) must equal
  `outputs`, checked before rendering. The response's `render` is
  `render_job`'s result.
- `deterministic` (for the negative cache) is true for `render_too_large` and
  for `render_failed` in the load, render and seal phases, with two exceptions.
  A child error marked `transient` is never deterministic: a real OS or
  file-system error (an `OSError` subclass or one with an errno: a scanner's
  sharing violation, access denial, a full disk), a missing module, or a
  renderer that cannot be called as `renderer(job)`. A memory failure is
  deterministic only with evidence of the Job cap (the job's memory-limit
  notification, or a peak commit within 64 MiB of the cap); a `MemoryError`
  without it is system commit exhaustion. Timeouts and failures in verify,
  import, write or transport are never deterministic, and neither is a crash
  without cap evidence. `transient` is consumed by the parent and never appears
  in `details`.
- Scanner locks: the child retries `PermissionError` for 2 s while it seals the
  PNGs and publishes its result; the parent retries reading the result until
  the job timeout. `validated_images` runs on the owner thread and does not
  wait: a lock there is a non-deterministic `render_failed`.

Hand-over text (U4 writes §3.2.2; U4/U9 carry §3.2.6 and §3.2.7):

- §3.2.2, worker paragraph: each render runs in a private one-shot child
  process (below normal priority, single-thread BLAS, 1536 MiB commit cap,
  25 s limit) that is killed when KurtShape exits. Its inputs are BREP
  captures checked against their sha256 before any native module loads, and
  every PNG is checked again (type, size, sha256) before it is published.
- §3.2.6 rows produced by the worker:
  - `render_timeout`: `timeout_seconds`. The child exceeded its time limit, or
    its result stayed locked until then. Never cached.
  - `render_failed`: `phase` (verify, import, load, render, seal, write) when
    the child reported the failure, or `exit_code` when it died without a
    result. Also covers malformed or foreign results, failed image checks and
    launch failures (message only).
  - `render_too_large`: `reason` (faces, edges, brep_bytes, triangles, memory),
    `phase` when the child reported it, `peak_commit_mb` and `cause` for memory
    failures, plus the renderer's scalar details (for example `triangles`,
    `limit`).
- §3.2.7: the Job's memory-limit notification is best-effort, and a single
  allocation that the cap refuses leaves the peak low. Without the
  notification that failure is not negatively cached, so a repeated render
  runs the worker again. Off Windows there is no Job Object: no hard memory
  cap, and memory failures are never cached. A native fault that FreeCAD
  reports as an errno-less `OSError` ("Access violation") is treated as
  deterministic, or as a memory failure when the cap was reached.

Runner registration: `SUITES["native"]` lists
`test_render_jobs.RenderWorkerLifetimeTests` beside the other worker lifetime
classes (added in N3's review round 1 while no serial unit edits
`run_native_tests.py`, following N1; U4 no longer adds it). At 00:13 on
2026-10-18 the inventory gate still listed `test_model_render.ModelRenderTests`,
`test_operation_schemas.OperationSchemaTests` and
`test_parameter_panel.ParameterPanelTests`/`SectionLayoutTests`. While any class
is listed, no `run_native_tests.py` run executes a suite.

Tests (`runtime/bench/f31/run_classes.py --suite native`; reports under
`runtime/contract-3.2/n3/fix-r1-20261018-000955/`):

- `RenderWorkerLifetimeTests`, whole class, twice (`lifetime-run1.json`,
  `lifetime-run2.json`): **27/27 each** (19.9 s and 19.4 s), no skips. The
  hashes of both N3 files were equal before and after (`hash-before.txt`,
  `hash-after.txt`). Development runs: `quick.json` 5/5 and `children.json`
  6/6. No render child was left running.
- New in round 1: the production default renderer end to end on a box with a
  highlight (`model_render` PNGs, tEXt metadata, drawn pixels); transient
  classification in a real child (scanner `PermissionError`, a renderer with the
  wrong signature, an inner `TypeError` that stays deterministic); clean
  `phases` and the write-phase fallback; child and parent error mapping
  (reserved and invalid detail keys, errno and errno-less `OSError`,
  `Part.OCCError`); the two memory signals separately, through `poll()` and
  `child_error()` with a fake job; the seal's lock retry with a real
  no-sharing `CreateFileW` handle; and the adapter refusing miswired scenes
  before it renders. Each timeout path now checks `timeout_seconds`.
- Probes (`probes/`): `probe_default` renders iso and an XZ section of a drilled
  box through the default seam in 1.4 s (peak commit 261 MB). The images were
  opened and checked: section caps hatched, label A drawn, and the edge-on
  label marked "(hidden)". `probe_oldseam`: round 0's seam
  (`model_render:render_job` called as `renderer(job)`) now reports a
  non-deterministic `render_failed`. `probe_exc`: FreeCAD/OCCT report geometry
  failures as `RuntimeError` subclasses (`Part.OCCError`) or `ValueError`; only
  native faults surface as a bare `OSError`.
  `probe_suites`: registration and `--only test_render_jobs` routing.
- Round 0 (implementer): `runtime/bench/n3-render-worker-20261017-233237` and
  `-233337`, 20/20. Review round 1 verification: `runtime/contract-3.2/review/N3-verify-r1`, 20/20.

Deviations from the spec:

- The `model_render` adapter lives in `render_worker` (`model_render.py`
  belongs to N2), and `DEFAULT_RENDERER` is now `kurtshape.render_worker:render_scene`.
- The review asked for `OSError` to be transient; the rule is narrower. FreeCAD
  turns native faults inside OCCT into a bare `OSError("Access violation")`
  (round 0 probe `probe_alloc2`), which repeats for identical inputs, so only
  errno-carrying or subclassed `OSError`s are transient.
- F2 §2.4 caches "deterministic" failures; memory failures now count as
  deterministic only with cap evidence. The real-child memory tests no longer
  require the best-effort notification; a grow-to-cap scenario pins
  determinism from the peak alone.
- A memory failure inferred from a child that died has no `phase`.
- The SUITES line was added by N3 rather than U4 (integration §2 kept N-units
  out of SUITES).
- `OPERATION_CONTRACT.md` is unchanged, because U1 creates the Contract 3.2
  skeleton; the text above is the hand-over.

Decisions for Kurt: none new. Default adopted for confirmation: a render memory
failure without evidence of the Job cap is not negatively cached, so an
identical request runs the worker again instead of returning the stored error
for 10 minutes. For the orchestrator: the N2, N4 and N5 classes must be
registered before U1 can run `run_native_tests.py`.

### N4 — operation schemas (new files)

`src/kurtshape/operation_schemas.py` (F5 §3.1; no top-level kurtshape import)
and `tests/test_operation_schemas.py::OperationSchemaTests` (native suite, 18
tests). Nothing imports the module yet. U2a wires it into `core`: the generic
pre-check, the `operation_schema` read, capabilities `schemas`, and `_id` on
`FEATURE_ID_PATTERN`. The registry covers all 74 operations in `Controller.OPS`
with 84 examples (every op except `repair_orphan_helpers`, which needs orphaned
helpers), 80 declared defaults, three example fixtures (plate, studio,
assembly) and the import-time `REQUIRED`/`ONE_OF` tables (24 ops with
generic-required fields, 55 `checked_by_handler` entries).

Review round 1 (2026-10-18):

- The leave-one-out guard cannot pass vacuously any more. With
  `missing_arguments` patched off, a `missing_required` rejection fails the
  test. The new `test_generic_precheck_is_called_through_the_module_attribute`
  passes before U2a (nothing calls the pre-check). After U2a it passes only if
  core calls `operation_schemas.missing_arguments` through the module: a
  sentinel return must come back as `fields:["__probe__"]`.
- The default proof was rebuilt. Explicit default and omission are compared by
  a signature of two parts:
  - response facts: full inspect feature rows (sketch placement and support,
    helix and datum frames, reversed flags) and `result_report` without
    `check_ms`;
  - the native model: each object's type, label, state, placements, group, tip
    and rounded shape geometry (topology counts, volume, area, length, bounds,
    sorted vertices), plus `core.native_intent` without the request echo
    `KurtShapeStudioOperation` and the random `Uid`.

  The `content_view` BRep digest is not used: two identical shell runs gave
  BRep texts one byte apart.
- Fifteen test-local probes (`DEFAULT_PROBES`) give 30 defaults a request in
  which the default matters:
  - a dependent, for cascade;
  - an edit before the finish, for cancel;
  - Add results that touch only Body, and patterns that touch Body and Tool,
    for merge_scope, operation and include_source;
  - coplanar faces, for refine;
  - a helix path, for frenet;
  - three sections, for ruled;
  - a free native line, for pierce `point`;
  - a hole drilled into the plate, for reversed, end_type and point_angle.

  For every default, explicit equals omitted on each example in its mode and
  on its probe. At least one of those pairs must succeed. A `WRONG_VALUES`
  value must change the signature.
- `select()` always returns a new top-level dict, so decorating it leaves the
  cached build and its digest intact. It raises TypeError for non-string names.
- pad `end_type` and pocket `through_all` defaults apply only without
  `up_to_face`. The constraints now say that `up_to_face` selects the end and
  that `end_type` (and, for pocket, `through_all`) is then ignored. The
  `length` x-required-when text matches. `test_up_to_face_selects_the_end`
  pins this.
- The `move_assembly_instance.position_mm` items now allow 1e7 mm, the
  handler's bound. `move_assembly_joint.value` gains `x-max-abs: 1e7`.
- Each transitional enum is pinned at its handler site: the function, the
  compared argument and its `req.get` default. Every declared default must
  validate against its rendered field schema.
- `test_envelope_claims_hold_on_dispatch` checks the envelope on dispatch. A
  missing `expected_revision` gives `stale_revision` exactly where it is
  required. Bogus `x-ignored` keys leave the example's outcome unchanged.
- Application-transaction leaks are pinned: only `adopt` leaves one open (see
  §3.2.7 below).

Hand-over for U2a:

- Call `operation_schemas.missing_arguments` through the module attribute.
  Two tests pin this.
- Validate `operation_schema`'s `operations` as a list of distinct strings
  before calling `select`. Decorate only the dict that `select` returns: nested
  values are shared with the cache.
- When U1 names the `TRANSITIONAL` constants, remove their entries. The enum
  test switches to the constants by itself.
- Add the remaining §9.2 cases that need wiring.

Hand-over for the contract text:

- §3.2.0: with the pre-check, an explicit `null` for a generic-required field
  rejects with `invalid_argument`/`missing_required`:
  - `set_parameter`/`set_expression` `parameter` returned
    `unsupported_parameter` before;
  - 22 other field cases returned `operation_failed`;
  - 26 cases returned `invalid_argument` with a handler message, and now
    return the generic message and reason.

  U2a pins both changes in an explicit-null case (evidence in
  `runtime/contract-3.2/review/N4-correctness-r1/probe_n4.json`,
  `required_codes`).
- §3.2.5: every op has one entry. Defaults live only in the per-op `fields`.
  `required` is truthful, and `checked_by_handler` fields keep their own codes.
  `x-required-when` documents mode-dependent fields. `x-default-when` says
  when a mode-dependent default applies. Examples run on documented fixtures.
  The digest is the SHA-256 of the canonical JSON.
- §3.2.6: N4 adds no error codes.
- §3.2.7:
  - `adopt` leaves FreeCAD's application-level transaction "KurtShape: adopt
    native copy" open. `core._adopt` uses `Document.openTransaction` and
    `commitTransaction`, so the next document opened in that process starts
    with a pending transaction. This is pre-existing.
  - `merge_scope:"auto"` is verified only against explicit lists that differ
    from the touched parts. `"auto"` and the exact list of touched parts build
    the same model and differ only when a rebuild re-scopes, which the default
    test does not exercise.

Runner registration: `SUITES["native"]` lists
`test_operation_schemas.OperationSchemaTests`. N4 added it in review round 1,
as N1, N3 and N5 did for their classes. This answers N1's open question for
N4: the class passes on the 3.1 core without the U2a wiring, and the §9.2
cases that need the wiring are U2a's. At 00:37 on 2026-10-18 the inventory
gate listed only `test_model_render.ModelRenderTests` (N2)
(`runtime/contract-3.2/review/N4-fix-r1/unassigned.out.txt`). While it is
listed, no `run_native_tests.py` run executes a suite, `--only` included.

Tests (`runtime/bench/f31/run_classes.py --suite native`; reports under
`runtime/contract-3.2/review/N4-fix-r1/`):

- `OperationSchemaTests`, whole class, twice. Each run waited for 75 s
  without writes to `src/` or `tests/`, and the summary is in
  `final_runs.json`.
  - `final-run1.json`: **18/18** in 103.6 s, of which the default test took
    61.5 s.
  - `final-run2.json`: **18/18** in 136.3 s (default test 81.1 s), on a shared
    and loaded machine.
  - Both runs had no skips, reported `source_unchanged` true, and left the N4
    file hashes equal before and after.
  - Final files: `operation_schemas.py` `d0316d6f…`,
    `test_operation_schemas.py` `4e1ad85a…`, `run_native_tests.py`
    `179c1fb5…`. The src tree was `1804fee2…` (63 files,
    `run_ab.tree_sha256`).
- Development runs `dev2.json` and `dev3.json`: 18/18 each. Their harness
  verdict was `passed:false` only because other units wrote files during the
  run.
- Mutation probe (`n4mutate.py`, in-memory patches; `mut1.json`, results in
  `mutation-results/`):
  - All 41 mutated declared defaults fail: the 35 that round 1 found
    unverifiable, `hole.reversed`, and 5 that were already detected.
  - Every unmutated op passes.
  - Pre-check wirings:
    - With no wiring, or with module-attribute wiring, both guard tests pass.
    - A wrongly required `x` fails leave-one-out under either wiring.
    - Binding by name fails both guard tests.
  - The probe classes inherit the class, which passed twice more there
    (38/38).
- Exploration (`explore-schema.json`, `explore-probes.json`) found the noise
  that the signature masks: the one-byte shell BRep difference, the request
  echo, `Uid`, and the OutList order.
- Round 0 and review round 1 verification:
  `runtime/contract-3.2/review/N4-verify-r1`, 15/15.

Stray files: this round's first mutation run wrote `mut1.json`,
`mut1-output.txt` and `mut1-evidence/` into the checkout root, because the
harness resolves `--out` after changing to the root. They were moved into the
evidence folder. The root-level `probe-*.json`, `probe-*-output.txt` and
`probe-*-evidence/` files come from the round-1 test review; they are
untracked, not ignored, and this round left them alone.

Deviations from the spec:

- The SUITES line was added by N4 rather than U2a.
- F5 §9.2's default test compares created-feature parameters and build status.
  This one compares the full signature, adds the probes and the wrong-value
  check, and replaces `content_view`'s BRep digest with rounded geometry
  because BRep text is not reproducible.
- 18 tests instead of round 0's 15. The new ones are the pre-check sentinel,
  the envelope claims and up_to_face.
- `OPERATION_CONTRACT.md` is unchanged. U1 creates the 3.2 skeleton, and U2a
  lands §3.2.5 with the `operation_schema` op; the text above is the
  hand-over.

Decisions for Kurt: none new.

### N5 — parameter-panel widgets (new files)

`src/kurtshape/parameter_panel.py` (3b §3–§4: `ParameterSection`,
`ParameterValueEdit`, `ParameterTree`, `ParameterDialog`, the adapter contract
`ParameterAdapter` with the only error-code table, `ControllerParameterAdapter`,
`normalize_value`/`format_number`, `SectionLayout`/`PreferenceStore`) and
`tests/test_parameter_panel.py` (`ParameterPanelTests`, `SectionLayoutTests`,
native suite, offscreen Qt, FakeAdapter). Qt only: FreeCAD is imported lazily
and FreeCADGui never. No module imports it yet; U7 wires it into the left panel
and adds `ParameterAdapterTranslationTests`. Files at completion:
`parameter_panel.py` sha256 `97df034b61ea…`, `test_parameter_panel.py`
`a8f2cfee4757…`.

Hand-over for U7 (adapter finalisation, 3b §9) and for U7/U9 doc text:

- `ControllerParameterAdapter(panel)` reads `panel.state` (rows, `parameter_set`
  or the `build_errors` fallback, `revision`, `studio`), `workspace_mode`,
  `document()`, `active_sketch()`, `native_feature_task_active()`, `task`,
  `pending_sketch`, `selecting_support`, `studio_dialog`,
  `sketch_plane_editor.picking` and `core.busy`; writes go through
  `panel.operation(op, …, _document_id, _expected_revision)`. On failure it reads
  `panel.last_operation_error` (the wire error); U7 must set that in
  `Panel._operation`, otherwise a failure is reported as the transient
  `not_applied` with the status-label text. The name hint and the usage helper
  come from `kurtshape.parameters` (`NAME_PATTERN`, `usage(doc, names)`); without
  that module there is no local name rule and usage falls back to a
  `list_parameters` dispatch.
- Section entry points: `refresh(force)` (cheap unless the adapter key changed),
  `clear()`, `set_unavailable(reason)`, `set_editable()`/`sync_editable()`,
  `flush_pending()` (before Save, Export, New, Open, a document switch and Close;
  False refuses the action), `cancel_edit()` (for `general.cancel`), `close()` on
  panel shutdown, `owns_focus()`, `select()`, `rename_current()`,
  `delete_current()`, `copy_reference()`, `paste()`. C25's `parameter_edit`
  activity is any row whose field is `edited` or `rejected` and not `retired`.
  `SectionLayout(splitter, PreferenceStore()).restore()` at build and `.flush()`
  on close.
- Commit rules (3b §4), as refined in review round 1: a field has at most one
  scheduled commit. Input Qt delivers before the zero-delay dispatch (a second
  Enter, the click after Enter, typed-ahead keys) joins it when the text is the
  same and replaces it when the text changed; Escape drops it. At dispatch the
  field must still hold the decided text (otherwise nothing is sent) and the
  adapter's blocker is checked again: a tool or dialog opened in between rejects
  the edit inline (`blocked`, transient) without taking focus back. A commit that
  succeeds moves the later scheduled commits decided on the same revision to the
  new revision, so typed-ahead entry across several fields applies each one
  once; any other change in between still gives `stale_revision` (transient,
  Enter retries). A conflict note is withdrawn when the value changes back
  elsewhere to the one the edit started from.

Review round 1 fixes: the double dispatch of one edit (a stale-revision error
and a red outline on a value that had been stored) when a second Enter, a click
elsewhere or typed-ahead input was queued before the deferred commit; Escape
before the dispatch now discards; the blocker re-check at dispatch; the stale
conflict note. New tests pin these and the gaps the review listed: actions
(add, rename, delete, Replace formula) flush first or refuse; a failed
focus-out commit leaves focus where the user moved it; the 45 % value-column
ceiling; tooltip help events read usage only on hover; only `Touched`, `Invalid`
or `Error` flags mark the set out of date; no name rule without the backend;
`close()` rejects the open dialog; a deleted section drops its scheduled commit;
the banner in `minimumSizeHint`; focus-in makes the row current; the 400 ms
debounce (timer interval, and no write sooner than 0.9 × 400 ms after the last
move, allowing for coarse timers). The fake now refuses a stale
`_expected_revision` on value edits as core does.

Runner registration: `SUITES["native"]` lists
`test_parameter_panel.ParameterPanelTests` and
`test_parameter_panel.SectionLayoutTests` after `ValidationToolingTests` (added
in N5's review round 1 while no serial unit edits `run_native_tests.py`,
following N1 and N3; U7 adds only `ParameterAdapterTranslationTests`). At 00:29
on 2026-10-18 the inventory gate still listed `test_model_render.ModelRenderTests`
and `test_operation_schemas.OperationSchemaTests`; another unit registered
`OperationSchemaTests` at 00:36, so only `ModelRenderTests` still blocks
`run_native_tests.py` (checked again in the final inventory below).

Tests (`runtime/bench/f31/run_classes.py --suite native`; reports under
`runtime/contract-3.2/n5/fix-r1-20261018-001852/`):

- Both N5 classes, twice (`run1.json`, `run2.json`): **66/66 each** (4.3 s and
  4.5 s), no skips. `ParameterPanelTests` has 60 tests: the 33 listed in 3b §12
  plus 27 more (round 0 had 46 = 33 + 13; the round-0 hand-over's 47 was a
  miscount); `SectionLayoutTests` has 6. Hashes of the N5 files were equal
  before and after (`hash-tests.txt`). The error-state image
  (`run1-evidence/parameter-panel/parameters-section-error.png`) was opened and
  checked.
- Full native suite in the registered `SUITES["native"]` order, N5 after
  `ValidationToolingTests` (`full-native2.json`, 57 classes including N4's
  `OperationSchemaTests`): **696 tests, 692 passed, 4 `perf:` skips, 0
  failures**, `source_unchanged` true (952 s while other units' runs kept the
  machine busy). An earlier run (`full-native.json`, 678 tests, 674 passed, 4
  skips, 0 failures) is discarded: another unit edited `run_native_tests.py`
  during it (`source_unchanged` false).
- Mutation check (`mutants.json`, 17 mutants each in a fresh isolated child):
  16 turn tests red, including the round-0 commit, execute and revert code
  (alone and together), no blocker re-check, no revision advance, no conflict
  withdrawal, a focus-out failure that takes focus back, actions without flush, no value ceiling, no tooltip wiring,
  `Expanded` counted as stale, a fallback name rule, `close()` keeping the
  dialog, a deferred commit without the section as context, the banner left out
  of the size hint and a 100 ms debounce. The survivor removes the section's own
  "make the row current" call: Qt's item view already makes the row of a focused
  index widget current (`probe_focus.json`; the same probe shows a focus-out
  leaves the item's column-1 text empty).
- `inventory.json`: `--only test_parameter_panel` maps to both classes in
  `native`. `inventory-final.json` (after the full run): the gate lists only
  `test_model_render.ModelRenderTests` (N2); until that class is registered,
  every `run_native_tests.py` run, full or `--only`, still runs no suite.

Deviations from the spec:

- The SUITES lines were added by N5 rather than U7 (integration §2 keeps
  N-units out of SUITES), as N1 and N3 did.
- 3b §4 does not cover input queued before the deferred run. Escape pressed
  after Enter but before the dispatch discards the edit, and text typed after
  Enter replaces that Enter's decision (the field stays edited until Enter or a
  committing focus move), so what is sent always equals what the field shows.
- 3b §4 step 6 captures the revision at the decision; a scheduled commit now
  follows the revision of this section's own earlier commit in the same queue.
  The blocker is checked at the decision (3b §4 step 5) and again at dispatch.
- The evaluation banner and stale formula rows appear only for the `Touched`,
  `Invalid` or `Error` flags (3b: any state other than `["Up-to-date"]`);
  FreeCAD view flags such as `Expanded` do not count.
- `OPERATION_CONTRACT.md` is unchanged: N-units do not edit docs other than
  this row, and nothing on the wire changed. The text above is the hand-over.

Decisions for Kurt: none blocking. Defaults adopted for confirmation: Escape
pressed after Enter but before the edit is sent cancels it; text typed after
Enter but before the edit is sent replaces that Enter; typed-ahead edits to
several fields in a row are applied one after another without a stale-revision
error between them.

### U1 — shared dispatch pipeline and contract revision 2

Implemented (integration §2 U1). Files: `core.py`, `studio.py`, `hole_tools.py`,
`modeling_geometry.py`, `contract.py`, `bridge.py`, `document_state.py`,
`tests/test_build_status.py`, `docs/OPERATION_CONTRACT.md`, `tools/run_native_tests.py`
(two SUITES entries), the new `tests/test_dispatch_pipeline.py` and
`tests/test_contract32_conventions.py`, plus one line in `extrusion_preview.py`,
the `TRANSITIONAL` table in `operation_schemas.py` and one test in
`tests/test_operation_schemas.py` (deviations below). `extrusion_edit.py` needed
no edit (`END_TYPES` already existed). Final `core.py` sha256 `67df6039…`.

- `contract.CONTRACT_REVISION = 2` and `contract.REQUEST_SIZE_LIMIT = 65536`
  (C1, C5); `bridge.py` and `capabilities.request_size_limit_bytes` read it.
- Operation classes (C2, C6): `VIEW_OPS` and `LIFECYCLE_OPS` (empty frozensets,
  already in `OPS`), `NON_MUTATING_OPS`, `DOCUMENTLESS_OPS`, `QUIET_OPS` (3.1
  membership; U2a/U4/U5 add their ops) and `TRANSPORT_FIELDS` (used by the
  unknown-argument check). The unmanaged allow-list and the unmanaged
  `operations` list read `NON_MUTATING_OPS` (membership unchanged).
- `Controller._reports` (C8): one per-request mapping, reset at the start of
  `_dispatch`; `studio._result_operation` writes `result_report` and
  `_repair_orphan_helpers` writes `repair_report` into it. The instance-attribute
  stashes `_result_report`, `_repair_report` and `_new_sketch_name` are gone.
  Responses carry every non-internal key (`changed_inputs` stays internal); the
  except path drops the per-step keys.
- `Controller._model_step(doc, req, editing=False) -> ModelStep(created_feature,
  reports)` (C9, without U5's verify step): handler, `studio.reconcile`,
  `_recompute`, `_mark_rebuilt` (rebuild), native gate (skipped while editing),
  legacy single-solid gate. It never touches transactions, the revision or
  DocumentId-keyed state. `NULL_WINDOW` and `_validation_window(doc, mode,
  trigger=None, before=None)` (C10) return the no-op window; the MODEL_OPS
  branch and `_preview` call `window.finish()` after the step.
- `_preview` (C11, C12): runs `_model_step` on the clone, adds `accepted`
  (`failure is None`), keeps `valid = accepted and status in {valid,
  sketch_only}`, copies the step reports (so a `repair_orphan_helpers` proposal
  now returns `repair_report`), and its cleanup closes (aborts) any app-level
  transaction that was not active before the preview, after closing its own.
- Extractions with unchanged behaviour: `_log_exception()`, `_record_failure(doc,
  op, request, error)` (the generic `LastFailure` write; the two recovery
  writes keep their content), `_result_row(doc, obj, meta, measure)` and
  `_helper_reference_health(doc, rows_by_id)`.
- `_model_operation` returns the created name for `create_sketch`,
  `sketch_rectangle`, `sketch_circle` and legacy `pad`/`pocket`;
  `created_sketches` is set from `step.created_feature`.
- Constants `studio.RESULT_OPERATIONS`, `studio.BOOLEAN_KINDS`,
  `hole_tools.END_TYPES`, `modeling_geometry.HANDEDNESS`; `extrusion_edit.END_TYPES`
  replaces the literal sets in core.py (legacy pad) and studio.py (studio pad).
- `document_state`: `commit_count` (incremented in `slotCommitTransaction`) and
  `note_intent_change(obj)`.
- `OPERATION_CONTRACT.md`: "## Contract 3.2" after the 3.1 section, with §3.2.0
  (six rows, each with its test) to §3.2.7; the §3.2.6 table and §3.2.7 list
  are empty for U1.

Tests added: `tests/test_dispatch_pipeline.py::DispatchPipelineTests` (11) and
`tests/test_contract32_conventions.py::Contract32ConventionTests` (5, `NEW_CODES`
empty), registered in `SUITES["native"]`. The golden test runs the frozen
`runtime/bench/f31` tree in a child process on the plate (9 holes) and studio
bench fixtures and compares `inspect` at `measure` False, True and "full"
with the live tree (UUIDs and `native_file` masked, `dependencies` as a
multiset, see deviations). `test_build_status…test_capabilities_contract_3_reports_measurement_and_check_policy`
asserts revision 2.

Tests run (reports under `runtime/contract-3.2/u-runs/<name>/native.json`, each
through `tools/run_native_tests.py --require-native` in run-checks' isolation,
`source_unchanged` true unless said otherwise):

- `u1-new-classes-4`: both new classes, **16/16**.
- `u1-only`: the §2 U1 guard list (test_core, test_result_checks,
  test_reference_tools, test_dress_up_edit, test_holes, test_datum_planes,
  test_multi_edge_references, test_sketch_polylines, test_review_followup,
  test_extrusion_preview, test_extrusion_edit, test_borrowed_preview,
  test_part_studio, test_build_status, test_geometry_queries,
  test_history_lifecycle) plus test_operation_schemas, the two new classes and
  the bridge suite: **294 tests, 289 passed, 4 `perf:` skips, 1 failure**:
  `OperationSchemaTests.test_enums_come_from_code_constants`, whose closing
  assertion still expected `operation_schemas.TRANSITIONAL` to hold the four
  enum sources U1 turned into constants (N4's hand-over asked for the removal
  but not for that assertion). The test now checks that each handler site
  compares its argument against the named constant, keeps no literal copy and
  keeps its default (`u1-schemas`: that test plus the two U1 classes, 17
  passed; the same report shows one loader error for a mistyped `--only`
  selector of mine, so its `passed` flag is false).
- `u1-mutant-txn`: review finding F1 (below). With the foreign-transaction close
  in `_preview` disabled, `test_preview_closes_a_foreign_app_transaction_left_by_the_proposal`
  fails (`((True,), ('rogue app-level transaction', 4)) not found in []`);
  `core.py` was restored byte-for-byte (sha256 `67df6039…` before and after).
- Full regression on the final tree (`u1-full-2`, `run_native_tests.py
  --require-native --timeout 3600` in run-checks' isolation, run dir
  `regression-run-20261018-091423-42352-4e16c46f`): **812 tests, 808 passed, 4
  `perf:` skips, 0 failures** (native 740/736, bridge 33, shortcuts 33, workflows
  6), `source_unchanged` true, `unassigned_test_cases` `[]`, 769 s. The N-unit
  tree had 796 cases; U1 adds 16.
- Informational pinned A/B against f31 (`u1-ab`; `run_ab.py --only supplement
  --supplement-args "--fixtures repro,drill,studio --repeat 2" --affinity 0xffff`,
  A = `runtime/bench/f31` at 14.1 % busy, B = live tree `63d60bed…` at 13.9 % busy;
  `compare_ab.py` default rules): **valid, passed; 27 metrics, 0 suspected,
  all per-family counters equal**, no families only in B. Largest ratios:
  `studio.intent_signature_ms` 1.22 (7.7 → 9.5 ms, under the 5 ms slack),
  `studio.capabilities_ms` 1.15 (sub-millisecond). `compare.txt` has the table.

Independent review (one round, read-only reviewer on the U1 diff against the
frozen 3.1 tree): verdict ready, no blocking findings. F1 (should-fix): the
foreign-transaction test could pass without the cleanup it pins, because a
rogue opened while the clone's transaction is pending is committed with it.
Fixed: the rogue is now injected in the last controller call before the
clone's commit (`_geometry`), `App.closeActiveTransaction` is wrapped and the
abort-close of the rogue is asserted; the mutant run above proves the pin.
F2 (nit): a `repair_orphan_helpers` preview now returns `repair_report`; added
as a §3.2.0 row and asserted in `test_reports_mapping_carries_result_and_repair_reports`.
F3 (nit): the two files outside the U1 list are recorded below. F4 (nit): C2
says the unmanaged `operations` list becomes `READ_OPS | VIEW_OPS | {adopt,
close_document}`, which would drop `CREATE_OPS`; U1 kept them (no 3.1 change);
U2b decides and lists a §3.2.0 row if it drops them.

Deviations from the plan:

- `extrusion_preview.py:426` (not in U1's file list) changed one line: the live
  evaluator pops `result_report` from `controller._reports` instead of the
  removed instance attribute (the old pop had become dead code). U3 edits the
  same file next.
- `operation_schemas.py` (N4's file): the four `TRANSITIONAL` entries were
  removed as its own comment and N4's hand-over asked once the constants
  exist; `tests/test_operation_schemas.py::test_enums_come_from_code_constants`
  was updated as described above (`handler_enum_site` now also returns the
  constant names a site compares against).
- The inspect golden compares each feature row's `dependencies` as a multiset.
  The raw native OutList of a tool whose Placement expression links other
  objects comes back in object-pointer order, which differs between processes
  with different allocation histories: two fresh children agree with each other
  and with the frozen tree, a child that had hosted and closed another
  Controller first does not (`runtime/test-tmp/u1-order-probe`,
  `runtime/test-tmp/u1-golden-probe`). Pre-existing 3.1 behaviour.
- `created_feature` for the five ops is additive; no test asserted its absence.
- `_validation_window` already takes the C10 signature (`mode`, `trigger`,
  `before`) so U3 replaces only the body; the trigger is `{"op": op}` for now.
- The round-2 reviews of U0 and N1–N5 interrupted by the crash were not redone.
  Their verification runs all pass (N1 14/14, N2 28/28, N3 27/27, N4 18/18,
  `runtime/contract-3.2/review/*-verify-r2`); the correctness and test
  reviewers' verdicts are not recorded. `N1-tests-r2/summary.txt` lists 18
  surviving mutants of `build_identity.py`; none concerns U1's files, and U2a
  judges them before wiring N1.

Decisions for Kurt:

- Preview applies the commit's gates exactly (§3.2.0 row 4). The observable
  differences are confined to legacy (non-studio) documents whose Body is not
  `valid`: a legacy `pad`/`pocket` proposal is now refused like the commit, and
  a `rename_feature`/`add_*` proposal is no longer refused. Confirm.
- `features[].dependencies` could be sorted to make inspect output stable
  across processes; U1 left it unchanged because the golden proves identity
  with 3.1. Decide in U9, or leave as is.
- F4 above: whether the unmanaged `operations` list should drop `CREATE_OPS`
  (U2b).

### U2 — bridge basics (U2a schemas and build identity, U2b lifecycle, U2c compact inspect, U2d transport)

Implemented per integration §2 U2 and F5 (`runtime/contract-3.2/specs/bridge.md`).
Files: `core.py`, `bridge.py`, `recovery.py`, `ui.py`, `selectors.py`, the three worker
launchers, `operation_schemas.py` (entries for `operation_schema`, `close_document`,
`inspect`/`list_documents` arguments), `tools/run_native_tests.py`,
`tools/perf/bench_core.py`, `tools/perf/interaction_probe.py`, `tools/run_gui_recipe.ps1`,
new `tools/document-lifecycle-gui-validation.FCMacro`, new tests
`tests/test_document_lifecycle.py`, `tests/test_compact_inspection.py`, additions to
`tests/test_operation_schemas.py`, `tests/test_bridge.py`, `tests/test_bridge_native.py`,
`tests/test_contract32_conventions.py`, `tests/test_dispatch_pipeline.py`, new
`examples/operation_schema-request.json`, `docs/OPERATION_CONTRACT.md` (§3.2.0 rows,
§3.2.5, §3.2.6, §3.2.7).

- **U2a.** `core` imports `build_identity` first; `capabilities` gains `build`,
  `read_operations`, `non_mutating_operations`, `schemas` (digest and count of the
  schema document built once per process); `diagnostics` gains `build`; export
  sidecars and STEP provenance gain `kurtshape_build`; the session file gains
  `build`, `read_operations`, `non_mutating_operations`, `request_size_limit` and
  the Bridge starts the one git probe. New read `operation_schema` (READ, DOCUMENTLESS,
  QUIET; `ARGS` from `operation_schemas.arg_names`). The generic missing-field
  pre-check runs after the unknown-argument and `measure` checks
  (`invalid_argument`, `fields`, `reason:"missing_required"`, `one_of`), the
  KeyError net `_missing_field_error` turns mode-dependent misses into
  `missing_conditional` after rollback (dispatch and preview), a legacy
  `pad`/`pocket` with `face` but no studio field rejects before the profile lookup,
  a non-string `document_id` is `unknown_document`, `_id` reads
  `operation_schemas.FEATURE_ID_PATTERN`, `selectors.schema()` is public, previews
  with a missing generic field return `accepted:false` without cloning, workers
  set `KURTSHAPE_WORKER=1`, and the runner records `kurtshape_build_sha256`.
- **U2b.** `document_modified(doc)` (GUI basis when a GUI document exists, else the
  session basis `saved_revision != Revision`); `inspect` gains `modified`,
  `modified_basis`, `unsaved`; `save`/`open`/`adopt` set the saved revision, report
  `modified:false`, and the GUI clear now covers `adopt`. F-05: `pre_modified`,
  `pre_signature`, `committed`, `ended_edit` in `_dispatch`; a rejected request with
  nothing committed and an unchanged signature restores the pre-request GUI flag.
  C13: the generic `LastFailure` write skips `NON_MUTATING_OPS` and the refusals
  `unsaved_changes`, `document_in_use`, `user_editing`; all three write sites have an
  `_is_open` guard. `LIFECYCLE_OPS = {close_document}`, `_close_document` (argument
  and transaction checks, the `editor_activity` hook, cross-document users, unsaved
  changes with `discard`, the discard checkpoint, native close, controller map
  cleanup, `closed` + `open_documents`), allowed on unmanaged documents.
  `RecoveryStore.capture_discarded` writes `<DocumentId>.discarded-<rev12>` pairs
  and keeps the newest 20. `Panel.editor_activity(doc_name)` reports
  `feature_editor`, `task`, `placement`, `step_export`, `geometry_check`.
- **U2c.** `inspect_compact(doc, features, parts, measure, summary)` behind
  `inspect` (`detail`, `features`, `parts`) and `list_documents` (`detail`), timed as
  `inspection_compact`; `_result_row(..., measure=None)` uses the cached solid count
  and verdict only. `interaction_probe` measures the family (`MEASURED_32 =
  {compact_inspect}`; `*.compact_inspect_ms`, `*.compact_inspect_feature_ms`).
- **U2d.** Bridge: JSON 400 `invalid_request` (malformed body, non-object, bad
  Content-Length, non-finite numbers via `parse_constant`), JSON 503 `queue_full`
  with `Retry-After: 1` and the request identity, `last_op`, `tracked:false` on an
  untracked read's `outcome_unknown`. `Panel.tick` skips the trailing inspect and
  refresh after a quiet read when revision, build status, refresh flag and document
  are unchanged (C22). `bench_core` section `bridge_reads`. GUI recipe
  `document-lifecycle` registered.

Tests added: `OperationSchemaTests` +7 (U2a), `NativeBridgeStatusTests` +2,
`DocumentLifecycleTests` (11), `CompactInspectionTests` (10), `BridgeTimeoutTests` +5,
`Contract32ConventionTests.NEW_CODES` = 6 codes, the inspect golden masks the new
keys and operations, the schema `DEFAULT_PROBES` gain `close_dirty` and
`WRONG_VALUES` the two `detail` defaults (the comparison `outcome()` now sees
`list_documents` row shapes).

Tests run (reports under `runtime/contract-3.2/u-runs/<name>/native.json`):

- Class runs during development (`runtime/contract-3.2/u-runs/<name>/native.json`): `u2a-classes`
  (OperationSchemaTests, DispatchPipelineTests, Contract32ConventionTests: 110 of 115 before the
  golden-inspect fix), `u2a-golden` (DispatchPipelineTests 11/11), `u2b-classes-4`
  (DocumentLifecycleTests 11/11), `u2c-classes-4` (CompactInspectionTests 10/10), `u2d-bridge-2`
  (bridge suite 22/22), `u2d-classes` (native 39/39; bridge 38/40 before the two bridge test fixes).
- Full regression before the review: `u2-full` — 847 tests, 843 passed, 4 perf skips
  (`StatusPerformanceTests`), 0 failures, 0 errors, 836 s, `source_unchanged: true`.
- Review round 1 fixes: `u2-fix-classes` (DocumentLifecycleTests, CompactInspectionTests,
  OperationSchemaTests, DispatchPipelineTests: 61 tests, 60 passed, 1 error in the new
  unmanaged-compact test's own full-mode assertion, corrected), `u2-fix-compact` (11/11).
- Full regression on the final tree: `u2-full-2` — 851 tests, 847 passed, 4 perf skips, 0 failures,
  0 errors, 855 s, `source_unchanged: true`, `kurtshape_build_sha256 5b795638…`; `src/kurtshape`
  tree `1cceef95…` (63 files, `run_ab.tree_sha256`).
- `bench_core --sections bridge_reads` smoke on a 6-hole plate
  (`runtime/test-tmp/u2d-bench-smoke/result.json`): passed; the five `bridge_reads` timings recorded.

GUI recipes:

- `document-lifecycle` (new): `runtime/ci-gui/document-lifecycle/run-fe21bbb4…` before the review and
  `run-986074b3…` on the final tree — 48 checks each. Quiet reads: 20 compact inspects plus
  `capabilities` and `operation_schema` caused 0 `Panel.refresh` calls and exactly 20 inspect
  dispatches; one mutation refreshed once; GUI-thread time per bridge read median 3.0 ms, p95 6.3 ms
  (hidden GUI, recorded, not compared).
- `interaction-idle` (U0 recipe): `runtime/ci-gui/interaction-idle/run-fd326474…` — 12 checks, every
  §4.4(d) guard within its budget, a bridge inspect produces 1 dispatch.

Review (round 1, independent read-only read of the U2 diff against bridge.md and integration.md):

- F1 (should-fix, fixed): `Panel.tick`'s quiet-read skip read `_meta()` of the active document before
  checking it was the panel's own; `metadata()` would have attached KurtShape metadata to a foreign
  native document that happened to be active during one tick. The skip now requires
  `last_document == doc.Name` and an existing metadata object, and also covers a request cancelled in
  its queue (`last_op is None`). Pinned by the `document-lifecycle` recipe (quiet reads still skip).
- F2 (should-fix, fixed): after a native `undo`/`redo` (or an in-lease snapshot restore) whose
  following recompute raised, the F-05 restore reset the GUI flag although the content had moved.
  `history_moved` now blocks the restore; pinned by
  `DocumentLifecycleTests.test_failed_undo_after_the_native_history_moved_keeps_the_gui_flag`.
- Nits fixed: an explicit `null` `features`/`parts` counts as absent (`_inspect_detail`); `used_by` and
  `affects` never map a foreign document's object onto a same-named history feature; part rows'
  `reference_issues` count the hidden helpers' unhealthy inputs like the feature rows do; the dead
  `and` in `test_compact_measure_only_when_explicit`; §3.2.5 documents the `x-example-*` keys of the
  schema result, the null-selection rule, the helper count and the cancelled-request skip. Three
  tests added: `checkpoint_failed` keeps the document open, compact inspection of an unmanaged
  document (`list_documents` counts, null selection), the KeyError net rewrites only omitted arguments.
- Not changed: the unmanaged `operations` list keeps `CREATE_OPS` (the reviewer agreed the code is
  right and C2's wording should be amended; decision for Kurt below).

Deviations from the plan / spec:

- The discard checkpoint is named `<DocumentId>.discarded-<rev12>.FCStd` (first 12 hex
  digits of the revision; the manifest carries the full revision) instead of the
  full revision: the bundled FreeCAD's `saveCopy` fails ("Failed to open file") once
  a path passes about 225 characters (probe `runtime/test-tmp/u2b-pathlen`), and the
  full name pushed the validated short session path over it.
- The unmanaged `operations` list keeps `CREATE_OPS` and adds `close_document`
  (integration C2's wording would drop `CREATE_OPS`; U1 review F4). Decision for Kurt.
- `test_operation_schemas.py` (N4's file) gained the U2a §9.2 cases, the
  `close_dirty` default probe, two `WRONG_VALUES`, a richer `outcome()` for
  `list_documents` rows and a guard in `SchemaRunner.signature()` for a closed
  document; `test_generic_required_covers_every_envelope_only_leak` now requires
  the pre-check outcome (it allowed `operation_failed` before U2a).
- `operation_schema`'s result carries the whole schema document decorated with
  `contract`/`contract_revision` (also `x-example-fixtures`, `x-example-placeholders`).
- `_close_document` details: `checkpoint_failed` carries `cause`; the response adds
  `operation_ms` like other document operations.
- F-05 restore and the C13 skips sit at the end of the except branch; the two
  recovery `last_failures` writes keep their content behind an `_is_open` guard.
- E-08: `Panel.tick` keeps `processed` for the notification loop (`dequeued`) and
  clears it for a quiet read only when all C22 conditions hold.
- `families_32(core)` now runs inside the probe's `common()` so the compact family
  is measured only where the build offers it (the frozen A side skips it).

Decisions for Kurt:

- `CREATE_OPS` in the unmanaged `operations` list (above).
- Session-basis `modified` is conservative (undo to the saved state, `begin_sketch_edit`,
  out-of-band `doc.save()` all count as modified); the GUI basis follows FreeCAD.
- Only `close_document` consults the editor hook; other agent mutations still cancel an
  open feature editor (F-14, unchanged).
- Discard checkpoints: 20 per recovery folder, one FCStd each.

### U3 — result validation on edits and rebuilds (F1)

Implemented per integration §2 U3 and `runtime/contract-3.2/specs/validation.md` (revision 2).
Files: new `src/kurtshape/result_checks.py`; `core.py` (ValidationWindow, `_validate_results`,
attach, `_build_status` fold, `_inspect`, compact rows, `_result_row`, capabilities, dispatch
branches for MODEL_OPS/finish_sketch_edit/undo-redo/check_geometry/begin_sketch_edit/recover,
except-path restamp, `_preview`, `_export`, `prepare_geometry_check`, `prepare_step_export`);
`studio.py` (`_check_result` pairs/recompute/facts, `operation_inputs`, `refine_state`,
`check_operation`, `retry_unrefined`, creation seeding in `_result_operation`);
`incremental_intent.py` (`IntentCache.row`); `document_state.py` (`result_serial`,
`history_serial`, `_COSMETIC`, drop on close); `extrusion_edit.py` (studio block live-only);
`extrusion_preview.py` (`_result_checks:"live"` for edits); `ui.py` (status text, Messages rows,
wait cursors); `tools/run_native_tests.py` (two SUITES lines), `tools/perf/bench_core.py`
(`result_validation_ms`, `result_keys_ms`), `tools/perf/interaction_probe.py`
(`history_checks_by_family`, `fingerprints_by_family`), `tools/run_gui_recipe.ps1`
(`result-validation`), new `tools/result-validation-gui-validation.FCMacro`, new
`tests/test_result_validation.py` (ResultValidationTests, ResultValidationPerfTests), key-set and
golden-mask updates in `tests/test_compact_inspection.py` and `tests/test_dispatch_pipeline.py`,
`docs/OPERATION_CONTRACT.md` (§3.2.1, §3.2.0 rows, §3.2.7, 3.1 Caching/Scope bullets),
`docs/EXTRUSION_EDIT.md`, `docs/AGENT_QUICKSTART.md`, `ARCHITECTURE.md`.

What landed (short): every managed change re-runs the 3.1 result post-conditions for the
Add/Remove/Intersect operations it affects, at their own history positions, and rejects with the
creation codes plus `validation:"history"`/`trigger`/`previous_status`; keys are content digests of
the input closure (shared `IntentCache` rows), verdicts live in a controller-wide store and in the
hidden `KurtShapeResultChecks` property; reuse is gated by observer shape versions and confirmed by a
copy-free vertex fingerprint; rollback/rebuild/undo/redo/native edits expose, never reject; inspect
reads an O(1) stamped summary (`result_checks`, `features[].result_check`, `bodies[].result_check`,
`bodies[].geometry_state`); export and check_geometry validate pending operations first; the GUI
shows "Result check failed — see Messages" / " · checks pending" and a wait cursor during the
synchronous validation before Check Geometry / STEP export.

Tests run (reports under `runtime/contract-3.2/u-runs/<name>/native.json`):

- `u3-classes-1`…`u3-classes-6` (ResultValidationTests while the fixture and the module were corrected: the runner refused
  an unregistered TestCase base class; a method-name clash in `result_checks.py` (`_row`); the TopCut pocket direction;
  explicit merge scopes; stale revisions after native edits; the audit re-check counted as a real check); final
  `u3-classes-6`: 21 tests, 21 passed, 0 skipped, 0 failures, 0 errors, 20 s, `source_unchanged: true`.
- `u3-perf-1` (ResultValidationPerfTests, `--perf`, 16-pocket plate): 1 tests, 1 passed, 0 skipped, 0 failures, 0 errors, 26 s, `source_unchanged: true` — a first-sketch edit checks
  exactly the 16 downstream Removes, rebuild/undo 0 checks, rename 0 checks and 0 fingerprints.
- `u3-classes-7`/`u3-classes-8` (CompactInspectionTests, ResultValidationTests, DispatchPipelineTests, ResultCheckTests,
  ExtrusionEditTests): round 3 fixed the compact header's `result_checks`, the U1 window test (every managed document
  now gets the real window), delivered reports are cleared, and `extrusion_edit.apply` keeps its 3.1 own-tip block
  (see deviations); final `u3-classes-8`: 65 tests, 65 passed, 0 skipped, 0 failures, 0 errors, 47 s, `source_unchanged: true`.
- Full regression on the final tree: `u3-full-2` — 874 tests, 869 passed, 5 skipped, 0 failures, 0 errors, 1856 s, `source_unchanged: true`; `src/kurtshape` tree `f63c12dc…` (64 files,
  `run_ab.tree_sha256`), `kurtshape_build_sha256 f97628e2…`.
- Full regression in audit mode (`KURTSHAPE_RESULT_CHECK_AUDIT=1`, every reused verdict re-checked and compared):
  `u3-full-audit-2` — 874 tests, 865 passed, 5 skipped, 4 failures, 0 errors, 1850 s, `source_unchanged: true`. The four failures are explained and none is a reuse mismatch: three are
  kernel-call-count tests (`ResultCheckTests.test_gui_live_preview_skips_kernel_checks_and_acceptance_runs_them`,
  `GeometryQueryTests.test_interactive_reference_and_studio_operations_do_not_check`,
  `ValidationToolingTests.test_no_result_checks_counts_a_direct_recompute_and_result_checks`) that the audit's extra
  re-check inflates by design (2 instead of 1); the fourth
  (`ResultCheckTests.test_a_failed_refined_result_is_retried_unrefined`) patches `studio._check_result` with a
  positional-only fake, which the audit's keyword call (`recompute=False, facts=…`) turns into a TypeError recorded as a
  fresh `build_failed` verdict (logged in the run's `kurtshape.log`). The audit mode is for the spec's verification run,
  not for the default suite.
- `bench_core --fixture studio` smoke (`runtime/test-tmp/u3-bench-smoke/bench-studio.json`): passed; `tip_edit`/`upstream_edit`
  rows carry `result_validation_ms` and `result_keys_ms`.

GUI recipe:

- `result-validation` (new, `runtime/ci-gui/result-validation/run-abdc60c8361f4b7e9e9ee8eb620f864e`): 36 checks. Creation of a studio
  Remove through the panel: 1 BRepCheck, 0 history checks (seeding hit with
  displayed tips). Extrude-dialog edit of the Add: 2 history checks (the Add and its downstream Remove),
  inspect valid afterwards (GUI-only writes do not stale the table). Save/close/reopen over the bridge: 0
  history checks, status valid. A native Sketcher lease that empties TopCut is refused with the TopCut row, the editor
  stays open, cancel restores a valid model. A native property change shows " · checks pending"; Check Geometry
  validates synchronously (2 checks) and the status returns to valid; the worker's own check
  of a Part Studio document is refused by its archive-equivalence oracle ("The loaded archive does not match the captured geometry"), reproduced on
  the frozen 3.1 tree (`runtime/test-tmp/u3-probe-7-f31`), so it predates 3.2 — recorded, not asserted (follow-up for Kurt).
  An emptying native change plus `check_geometry` over the bridge shows "Result check failed — see Messages" with the
  TopCut row in Messages; correcting the Add over the bridge returns to valid; rollback steps over unchanged operations
  run 0 history checks.

Review:

Review (round 1, independent read-only read of the U3 diff against validation.md rev 2 and integration.md; 15 findings,
none blocking; the three behavioural ones and the doc/test ones fixed, the nits taken where cheap):

- F1 (should-fix, fixed): while the table was stale, `part_status`/`failed_parts` looked for `part` in the last-known
  failure rows, but `empty_cut`/`empty_add` verdicts carry `parts=` and no `part=`, so `bodies[].result_check` read
  `pending` and `bodies[].build_status` `valid` next to a document-level `failed`. Both now read the stored table's
  outputs; `_verdict` also derives `part` from `parts[0]`. Pinned by `test_stale_failure_survives_an_unrelated_edit`.
- F2 (should-fix, fixed): an unrefined retry left two `checked` rows for the retried operation (the refined failure and
  the unrefined pass). The superseded row is dropped before the second pass; the refine test asserts one row.
- F3 (should-fix, fixed): a known failure flipped to `pending` (and `build_status` to `valid`) when an unrelated managed
  edit followed a native change, against D10 ("a failure clears only when its op is revalidated"). Previously failed
  operations without a reusable verdict are now checked in every mode but `report`, and `report` mode (undo/redo) keeps
  the known row marked `stale:true`; a rejection restores the previously stamped table (F8). New test
  `test_stale_failure_survives_an_unrelated_edit` covers the stale row, undo/redo, the forced recheck and the clearing.
- F4 (docs): already consistent at review end (the own-tip pre-check of `edit_extrusion` is kept, see deviations);
  the reviewer read an intermediate state.
- F5 (docs, fixed): §3.2.1 no longer claims cross-operation measurement substitution (deviation below).
- F6/F7 (tests, fixed): the export sidecar is asserted (`result_checks` block equals status/operations/checker);
  `prepare_step_export` returning None is pinned to the `BuildStatus` gate.
- Nits fixed: `prepare_geometry_check(doc, body)` converts a Body id to its part id; the stale summary lists the other
  pending operations beside the failures; unexpected checker exceptions are logged through `_log_exception`; the table
  property is hidden and read-only (editor mode 3); `snapshot()` returns an empty table for documents without the
  studio (no key table per request on legacy documents); `result_ops` is cached under the `structure`/`history`
  domains; the GUI macro comment names the frozen-tree evidence of the pre-existing worker refusal.
- Not changed: finding 13 (held-operation edits) is moot with the own-tip pre-check kept; the review's reading of
  `extrusion_edit.py` predates round 3.

Deviations from the spec:

- `finish_sketch_edit` validates read-only against the lease baseline and never runs the unrefined
  retry; the spec's grouped-transaction retry (`_commit_sketch_edit(regroup=…)`, §5.8 step 3) is
  not implemented. A refined result that fails at finish is refused (lease and draft kept) and
  the user fixes the sketch or rebuilds the earlier result with `refine:false`. Documented in
  §3.2.7.
- `validate(retry=True)` does not assert `doc.HasPendingTransaction`; without a pending transaction
  the retry is simply disabled (a hard assert would turn an edge case into `operation_failed`).
- A deletion another result operation consumes is refused by the 3.1 structural gate
  (`external_dependency`) before any result validation, so spec test 17 ("a delete that empties a
  downstream cut rejects with a cascade hint") is unreachable; the test pins the structural refusal
  and the accepted `cascade:true`. The validator still adds the cascade hint for deletions that
  pass the gate.
- Spec test 16 (revolve with its axis sketch in another part's Body) is replaced by a sketch and a
  later Add in the part's Body plus a creation-key/post-dispatch-key equality check through a spy on
  `ResultChecks.remember`; the container rule is exercised (the Body holding TopSketch is a
  container of TopCut's closure).
- Spec test 15's helical-sweep/revolve model is replaced by block + Add + through-all Remove +
  blind Remove + Intersect + unrefined Remove; the Modified-flag assertion is left to the GUI recipe
  (headless sessions have no GUI flag).
- `extrusion_edit.apply` keeps its 3.1 own-tip block for dispatch too (the spec made it live-only): without it an
  `edit_extrusion` that empties an automatic-merge-scope Remove reports `build_failed`/`auto_merge_scope_changed`
  from the native gate instead of 3.1's `empty_cut` (`ExtrusionEditTests` pins that). `extrusion_preview.py` is
  therefore unchanged by U3. Explicit-scope operations get the validator's `Change not applied` errors.
- Measurement reuse (§5.5) goes through the GeometryCache per object, but the substitution of a snapshot by its
  upstream result is not implemented: a snapshot is measured once per version, not shared with the operation
  that produced it. The contract text says so.
- The audit mode compares reused and fresh verdicts (status and code); it does not compare the
  substituted measurement facts with direct measurements (§5.5's second audit).
- `build_status` fold: `_validate_results` re-runs `_build_status` only when the report has failures
  or the stored status is `failed` (so a cleared failure flips back), not after every validation.
- `_validation_window` returns the real window for every managed document (not only documents that
  already have result operations), so the first result operation of a document is covered; a
  legacy document pays an empty key table.
- The GUI recipe drives rollback through the bridge `rollback` op (the keyboard path dispatches the
  same op) and emulates the property editor with a native property write inside a native
  transaction.

Decisions for Kurt:

- Intermediate result operations reached only through an upstream change keep a per-operation
  BRepCheck in edit mode (spec default; on the 28-pocket plate that is most of the added time).
- rollback, rebuild and undo/redo expose result failures (`build_status:"failed"`, export refused)
  but never reject (spec default).
- No grouped unrefined retry at `finish_sketch_edit` (deviation above).
- An edit after which an exact Boolean fails natively stays a `build_failed` from the native gate,
  without the automatic-fuzz fallback creation uses (documented limitation).
- The compact rows carry `result_check` (features and parts) and `geometry_state` (parts); the
  U2c key-set tests were extended accordingly.

### U4 — render_view (F2)

Implemented per integration §2 U4 and `runtime/contract-3.2/specs/render.md`. Files: new `src/kurtshape/render_jobs.py`
(integrates N2 `model_render` and N3 `render_worker`); `core.py` (`VIEW_OPS = {render_view}`, `ARGS["render_view"]` from the
schema, `dispatch`/`begin`/`_run`, lazy `renders`, the `_dispatch` branch next to `resolve_selector`, `capabilities.render`,
`diagnostics.renders`, `close`); `bridge.py` (`deferred`, `tick` routes VIEW_OPS to `begin` and parks the handle,
`poll_deferred`, `close` cancels); `ui.py` (`Panel.tick` calls `poll_deferred`; the U2d quiet skip already covers VIEW_OPS);
`selectors.py` additive (`world_shape`, `result_source`, `resolve(..., shapes=)`, `stored_input_names`,
`stored_input_refs`); `document_state.py` (`slotDeletedDocument` → `retire_document`); `operation_schemas.py` (the
`render_view` entry, `Ref` form `scalar`, view-op envelope: `expected_revision` optional and checked); tests
`tests/test_render_jobs.py` (`RenderFixture`, `RenderJobTests`, `RenderOwnershipTests`, fixture renderer `gated`),
`tests/test_bridge.py` (`BridgeDeferredTests`), `tests/test_operation_schemas.py` (render `outcome()`, `WRONG_VALUES`, the
envelope claim, scalar refs), `tests/test_contract32_conventions.py` (`NEW_CODES` + 13 render codes),
`tests/test_dispatch_pipeline.py` (`NEW_OPERATIONS_32` + `render_view` in the golden mask); `tools/run_native_tests.py`
(SUITES), `tools/run_gui_recipe.ps1` (`render-view`), new `tools/render-view-validation.FCMacro`, `tools/perf/bench_core.py`
(`render` section, report-only); new `examples/render_view-iso-request.json`, `render_view-section-request.json`,
`render_view-highlight-input-request.json`; curated `docs/contract-3.2/renders/*.png` + `renders.json`;
`docs/OPERATION_CONTRACT.md` (§3.2.2, three §3.2.0 rows and the quiet-read row, 13 §3.2.6 rows, one §3.2.7 bullet).

What landed (short): `render_view` is a read-only view op (in `non_mutating_operations`, not in `read_operations`),
ledger-tracked through the bridge and allowed on unmanaged documents. The owner thread validates the request, syncs like
`inspect`, reads status without computing geometry, keys the image and answers from the cache, a remembered failure, the
running job (join) or `render_busy`; otherwise it prescreens faces/edges, resolves and classifies highlights
(rendered / sketch / filtered_part / history), exports world BREPs under a 48 MiB cap (reused across settings-only
changes), fences the capture (one restart from a fresh sync) and starts one N3 child. The bridge parks the handle and the
Panel tick completes it; a direct `dispatch` waits. Every outcome completes the ledger once. The owner process never imports
numpy or Pillow's imaging (renderer values it needs are mirrored and pinned). Images live in
`<session>/renders/<session_id>/` for the session; owners that provably exited are swept.

Tests run (reports under `runtime/contract-3.2/u-runs/<name>/native.json`, run-checks' isolation):

- `u4-classes-1`…`u4-classes-5` during development and after the review: the first runs exposed test-side assumptions (a
  studio part id is not a native object for literal selectors; `openTransaction` is pending only after a change; the
  render's sync legitimately rotates the revision after native edits) and two real bugs (sketch-only Bodies excluded
  their sketches; a native failure upstream left the document-level `geometry` "current"). `u4-classes-3` (render, bridge,
  schema, conventions, pipeline, compact, lifecycle, model render, selectors): 196 tests, 195 passed, 0 skipped, 1 failures, 0 errors, 325 s, `source_unchanged: true`; its only failure was the inspect
  golden's `operations` list growing by `render_view` (mask extended). After the review fixes `u4-classes-4`: 177 tests, 176 passed, 0 skipped, 1 failures, 0 errors, 316 s, `source_unchanged: true`
  (the one failure was the new asynchronous capture removal, which the test now waits for); `u4-classes-5`
  (test_render_jobs): 60 tests, 60 passed, 0 skipped, 0 failures, 0 errors, 47 s, `source_unchanged: true`.
- Full regression on the final tree: `u4-full` — 915 tests, 910 passed, 5 skipped, 0 failures, 0 errors, 2131 s, `source_unchanged: true`; `src/kurtshape` tree `64a5028f…` (65 files,
  `run_ab.tree_sha256` rule), `kurtshape_build_sha256 3f6c2a71…`.
- `bench_core --sections render --holes 60 --repeat 5` (`runtime/test-tmp/u4-bench-run/session/bench-render.json`, report
  only, before the review fixes): owner time on a miss median 56 ms (first render 676 ms: capture plus the one-time numpy
  import the review removed), cache hit 39 ms, end to end 1.86 s, 8 distinct highlights 633 ms owner time, child peak commit
  380 MiB.
- Curated images (`docs/contract-3.2/renders/`, regenerated on the final tree by an isolated headless probe, all opened and
  checked): iso; the six standard views (separately and as a 7-tile sheet; front/back/left/right/top/bottom follow the
  documented camera conventions); section XZ offset −20 (section view and the cut iso); highlights with labels (a history
  ghost drawn dashed and listed "not in shown geometry", a fillet face, the boss annulus, a back face with the hollow
  "D (hidden)" label); `RETAINED GEOMETRY · BUILD FAILED` (an over-constrained profile, last shape kept);
  `VALIDATION PENDING` and `VALIDATION FAILED` (U3's stepped block; current geometry with the emptied cut absent).

GUI recipe `render-view` (new; hidden private FreeCAD, production Panel, real Bridge over loopback):
`runtime/ci-gui/render-view/run-d2b77b4f32814463add7d13e688c13d3` — 47 checks. Four renders (iso, section, highlight, 4-view draft sheet) and four
refusals (`highlight_no_match`, `invalid_argument`, `section_misses_parts`, `stale_revision`) leave the active document
(two documents open), the selection, the camera, object and ViewObject visibility, the GUI Modified flag, undo/redo, the
revision and LastFailure unchanged; no Panel inspect and no refresh; an identical request is a synchronous cache hit.
Owner-thread time per render (the tick that begins it): median 46 ms, max 81 ms (first render); polling
ticks while the child runs max 33 ms (bound 100 ms); total Qt time per render median 75 ms. Hidden-GUI timings,
recorded, not compared.

Review (one independent read-only agent; verdict "needs fixes", no blocking findings; all should-fix items fixed):

- F1 (fixed): a failure after the child answered (verification, publishing, building the response, the cache) could leave
  the job and its joined requests `started` forever and block later renders with `render_busy`. `poll` now always reaches
  `_finish`; a service watchdog bounds a job at the worker timeout + 5 s; `Deferred.wait` turns a poll exception into
  `render_failed`; `_finish` cannot raise. Pinned by `test_a_failure_after_the_child_answered_completes_every_joined_request`.
- F2 (fixed): `frame:"highlights"` without highlights, or with every shown match on the removed side of the section, reached
  the child and came back as a remembered `render_failed`. Both are `highlight_not_rendered` on the owner thread now
  (`test_frame_highlights_needs_a_shown_match_on_the_kept_side`).
- F3 (fixed): the capture-fence retry compared against the old fence and could never succeed; a change during capture now
  restarts the request once from a fresh sync.
- F4 (fixed): the first render imported numpy and Pillow into the GUI process (via `model_render.font_id`). The owner now
  mirrors `font_id`, the highlight palette and the two notes; `test_owner_process_never_imports_numpy` renders in a child
  owner process and asserts numpy, `PIL.Image` and `model_render` stay unloaded.
- F5 (fixed): publishing retried a scanner lock with `sleep` on the Qt thread; it now retries on the next tick and unlinks
  partly published files on failure.
- Nits fixed: the bridge parks only results of `begin` (`test_a_non_dict_from_dispatch_is_not_parked`); `Bridge.close`
  replies with an already completed response (`test_close_replies_with_an_already_completed_response`); captures of a
  cancelled job are removed after its child exited; a hidden sketch-only Body's sketches are filtered by `parts:"visible"`;
  a plain `TimeoutError` maps to `render_timeout`; assembly occurrences are not flagged `in_container`; doc rows (quiet
  reads include `render_view`; the revision can rotate at sync; cache entries; `render_capture_changed`); schema strings
  gain `minLength` and the `size` default description; the GUI macro opens a second document so the active-document check
  can fail.
- Not changed: the edit guard reads `doc.HasPendingTransaction` only (an open native transaction without a change is not
  detected; capture is read-only, so this is consistency, not safety).

Deviations from the spec:

- Image files are `img-<render_id>-<index>.png` (or `-sheet.png`), not `-<view>.png`: custom view names are free text.
- Document-level `geometry_status.geometry` is `retained` whenever the native status is failed or needs_rebuild (the banner
  says RETAINED), even when every result row's `geometry_state` reads current: a native failure flags the upstream feature,
  not the result object. Per-part rows keep inspect's `geometry_state`.
- `render_too_large` with `budget_seconds` (the N2 18 s job budget) is not negatively cached (N2 left the choice to U4).
- Highlight labels default to A, B, C… by position; `section_misses_parts` also rejects a plane with every part on the kept
  side (the spec's "strictly on one side").
- `renderer_limits`, `limits`, `worker_factory`, `worker_timeout` and `renderer` on `RenderService` are test seams.
- Tests: no `test_assembly_occurrences_render_in_world` (the nested App::Part test pins the world frame) and no separate
  `test_failing_resolve_selector_no_longer_overwrites_last_failure` (U2b pins the LastFailure skip for every non-mutating
  op); the label/colour/title invalidation test is folded into the capture-reuse test.
- AGENT_QUICKSTART, ARCHITECTURE, DEVELOPMENT_HISTORY and the workspace AGENTS.md line are left to U9 (integration §2 U4
  lists only OPERATION_CONTRACT; render.md §10 lists them).
- `budgets.json` is unchanged and render metrics are report-only (C34).

Decisions for Kurt:

- Images are session artifacts: deleted when KurtShape closes (spec open question; default kept).
- Non-rendered highlight matches are drawn as dashed ghosts and reported `rendered:false` rather than rejected (spec
  default).
- Budget overruns (18 s) are not remembered, so a slow machine retries instead of serving a cached refusal for 10 minutes.
- The pre-existing frame discrepancy (inspect's `bbox_mm` and STEP export use `assembly.global_shape`, container-local for
  Bodies nested in a placed `App::Part`) is flagged by `frame_note` and not fixed in 3.2.
- Restart: Kurt's running app needs a restart to offer `render_view` (headless sessions have it now).

#### U4 follow-up after Kurt's independent review (`runtime/contract-3.2/u4-independent-review/REVIEW.md`)

- **Captured-versus-live metadata (P2, fixed).** Part names, colours, body names and drawn sketch names are frozen
  in `_targets` at capture; the child's scene, the image key and the completion response all use the frozen
  values, and completion reads the live document only for `stale`. Pinned by
  `RenderJobTests.test_response_metadata_describes_the_captured_scene` (rename and recolour through
  `set_part_appearance` while the job runs, then deletion of the drawn feature while the job runs).
- **Assembly coverage (added).** `test_assembly_occurrences_render_in_world`: three occurrences of one source,
  one translated and turned 90° about Z, a `parts` filter that omits one occurrence, a highlight framed on its top
  face (selector centre and camera centre both (25, 7, 13)), the turned occurrence's box centre (25, 7, 9); then the
  review's case of a natively moved assembly (native build failed, `RETAINED GEOMETRY · BUILD FAILED`, centres
  aligned at (125, 27, 13)). Occurrences report `in_container:false` and no `frame_note`.
- **Highlight owner-thread cost (proportionate pass).** Profile (60-hole plate, 8 closest-point highlights,
  `runtime/contract-3.2/u4-probes/highlight_profile.py`; reports `highlight-profile-before.json` /
  `-after.json` in the run sessions): 322 ms went to exporting 8 highlight BREPs that held only about 2 distinct
  faces, 234 ms to selector resolution (81 ms of it `resolve_selector` summaries a render never reads, 138 ms
  to recomputing candidate boxes twice per query), and a settings-only change paid all of it again. Changes:
  resolved highlights and their exported files are cached with the capture (keyed by capture and selector/input;
  labels and notes excluded), identical match sets share one file, `selectors.resolve(shapes=True)` skips the
  summaries, and the `closest` selector memoizes each candidate's pruning box on its context row. Owner time:
  before 656–718 ms for every 8-highlight render (settings-only 673–697 ms); after 315–357 ms for 8 new
  highlights (the rest is OCCT `distToShape`, about 40 ms per query on the 60-hole face, left as selector
  semantics) and 52–88 ms for a repeat or a settings-only change. The `render-view` GUI recipe gained an
  8-highlight fresh render and a settings-only re-render (`runtime/ci-gui/render-view/run-184f50b9dcf147729f31233924fbfea5`,
  56 checks: owner tick 45 ms then 44 ms on the recipe plate, 0 resolutions and 0 exports on the re-render).
  `RenderJobTests.test_highlights_resolve_once_per_capture_and_share_identical_exports` pins the counters.
  The cache-hit path also checks the per-highlight match limit (found by the class run).
- Tests: `u4-followup-1` (render module + selector, dress-up and multi-edge classes: 134 tests, 133 passed, the
  per-highlight-limit failure above), `u4-followup-2` (test_render_jobs: 63/63). Full regression on the corrected
  tree `u4-full-2`: 918 tests, 913 passed, 5 perf skips, 0 failures,
  0 errors, 2547 s, `source_unchanged: true`;
  `src/kurtshape` tree `85350243…` (65 files).
- Kept visible for final acceptance: the Part Studio Check Geometry worker refusal (U3, pre-existing) and the
  container-local `bbox_mm`/STEP frame for Bodies nested in a placed `App::Part` (`frame_note`).

### U5 — parameters backend (F3a)

Implemented per integration §2 U5 and `runtime/contract-3.2/specs/params_backend.md`. Files: new
`src/kurtshape/parameters.py` (the native `App::VarSet` "Params" with the hidden marker `KurtShapeParameterSet`; types
length/angle/number; the name rules; `prepare_expression`, the one formula validator every formula path uses; records,
`apply_change` with pruning, `precheck`, `verify_applied`; `list_parameters`, `create/edit/rename/delete_parameter`;
`usage`, `usage_rows`, `observe_names`); `core.py` (op classes and ARGS from the schemas, `Params` reserved, sync calls
`observe_names` first, VarSet status, inspect `parameter_set`/`parameters`/`other_parameter_sets`, compact
`uses_parameters`, `error.parameter` after rollback and in preview, `_model_step` runs `verify_applied` and the legacy gate
over changed inputs, `set_parameter`/`set_expression` through `parameters.target`/`prepare_expression`/`precheck` with no
inner recompute); `hole_tools.py` (`recheck`), `extrusion_edit.py` and `reference_tools.py` (shared validator),
`result_checks.py` (C17: set-reading formula text dropped from keys, local and container modes; the VarSet skipped in
closures), `document_index.py`, `assembly.py` (`params` reserved); `operation_schemas.py` (five entries, the 3.2.3
anchor); `tools/native_validation_snapshot.py` (`parameter_record`); `tools/perf/bench_core.py` (`parameters` section,
report-only); tests `tests/test_parameters.py` (`ParameterTests`, `ParameterPruningTests`), two C17 tests in
`ResultValidationTests`, schema/pipeline/compact/conventions tables; examples `create_parameter-request.json`,
`edit_parameter-request.json`; `docs/OPERATION_CONTRACT.md` (§3.2.3, twelve §3.2.0 rows, ten §3.2.6 codes, a §3.2.7
bullet, the helix, `set_expression` and Hole rows).

Tests run (reports under `runtime/contract-3.2/u-runs/<name>/native.json`):

- `u5-classes-1`…`u5-classes-5` during development (`u5-classes-5`, test_parameters: 27/27).
- After the independent review: `u5-classes-6` (test_parameters + ResultValidationTests) 55 tests, 52 passed, 3
  failures — one real bug the strengthened unit matrix exposed (a studio revolve's float `Angle` formula was verified in
  degrees against the radian wire value, so `set_expression … "tilt * 9"` rejected with `parameter_not_applied`; fixed
  with the public unit of the target) and two test-side ones (per-document UUIDs in the `native_intent` comparison; a
  helix test that floated the cap off the block). `u5-classes-7`: 53/55 (an ambiguous-body test setup and a plane edit
  that detached the cap, both test-side). `u5-classes-8`: 55 tests, 55 passed, 0 skipped, 0 failures, 0 errors, 40 s, `source_unchanged: true`.
- Full regression `u5-full`: 951 tests, 945 passed, 5 skipped, 0 failures, 1 error, 1169 s, `source_unchanged: true`;
  `src/kurtshape` tree `35015d85…` (66 files, `run_ab.tree_sha256` rule), `kurtshape_build_sha256 292969f2…`. The
  error was `StepExportWorkerLifetimeTests.test_published_result_waits_for_successful_exit_and_artifact_survives_poll`
  hitting the STEP worker's time limit while the audit run shared the machine; it passed alone (`u5-rerun`).
- Audit regression `u5-full-audit` (`KURTSHAPE_RESULT_CHECK_AUDIT=1`, every reused result verdict re-checked), run
  concurrently: 951 tests, 941 passed, 5 skipped, 5 failures, 0 errors, 1169 s, `source_unchanged: true`. Four are the
  audit-by-design failures U3 documented (three kernel-call counts doubled by the re-check, and the positional-only
  `_check_result` fake); the fifth was the new pruning comparison catching recompute noise in sketch coordinates
  (`-1.1e-16` against `0`), now masked below 1e-10. No reuse mismatch.
- After that test fix (no `src/` change): `u5-rerun` (test_parameters + test_step_export_jobs) 65 tests, 65 passed,
  0 failures, `source_unchanged: true`; `u5-rerun-audit` (test_parameters, audit on) 31 tests, 31 passed. The full
  regression and audit run on the U6 tree cover U5 again.
- `bench_core --sections parameters` (report-only, before the review): inspect 7.3 → 7.8 ms with 20 parameters,
  `list_parameters` 4.4 ms, one managed rebuild for 1 and for 10 bind targets.

Review (one independent read-only agent; verdict "needs fixes", no blocking findings):

- 1 (fixed): `create_parameter` returned `created_feature` = the parameter name; it now returns `created_parameter` and
  no `created_feature` (`test_types_units_reopen_undo_redo`).
- 2 (fixed): `verify_applied` compared against a value evaluated before the step's recompute; it re-evaluates the formula
  after it (`current` stays the reported value).
- 3 (fixed): a Hole that became a consumer through `bind` had no before-snapshot for its re-check; bind targets'
  Holes are snapshotted before the change.
- 4 (fixed): pruning could purge an object linked to the set without a formula; only formula owners are pruned.
- 5 (fixed): wrong argument types (`expression: 5`, `type: ["length"]`, a list bind parameter) gave `operation_failed`;
  they are `invalid_argument` before any change (`test_argument_types_reject_before_any_change`).
- 6 (fixed): the rolled-back test now rolls back before `Top2`, binds the held consumer and spies that only the active
  consumer is verified, then rolls forward; the rename test creates a real dangling consumer, checks its warning and
  the rebind; `rename_failed` and `parameter_not_applied` are triggered; the `set_parameter` hints, the Hole column of the
  unit matrix and `reserved_id` on assemblies are tested; the pruning matrix adds a Hole driven by one parameter, helix
  Pitch, plane Offset and a rolled-back shaft, comparing build status, volumes, native states and `native_intent`
  (UUIDs masked) between pruned and full recompute after each edit and after undo; the C17 test binds Raise to its own
  parameter and asserts `audit_mismatches == []` with the audit forced on.
- 7 (fixed): the helix, `set_expression` and Hole rows; §3.2.0 rows for the shared validator on `edit_extrusion` /
  `edit_dress_up`, the helix formula limits, `pseudo_object`, any touched VarSet, the empty set kept after the last
  delete, and assemblies' `invalid_id`.
- 8–11 (fixed unless listed): `usage(doc, names)` and `parameter_record` exist; the early name-cache writes in rename and
  delete are gone; `rewritten` includes dependent parameter formulas; the create row has `used_by_count`; `hole_intent`
  stays internal; a literal formula infers its type without a set; the "unit" reason heuristic no longer matches
  "definition"/"infinite"; container-mode digests drop set-reading Placement formulas; `for_features` builds one map;
  `observe_names` reads `dir()` once. Not changed: `hole_tools.set_parameter` keeps its own recompute instead of
  `recheck` (same behaviour); `parse_value` keeps `invalid_argument` for a wrong-dimension length/angle string
  (`unit_mismatch` for a number parameter); `precheck` also applies to held helices (stricter than the spec);
  `parameter_set` stays a block after the last delete (documented).

Deviations from the spec: the angle/radian fix above (`verify_applied` and `changed_inputs` use the public unit of the
target, because a studio revolve stores its angle in a float property); parameter names must start with a lowercase
letter (C28); rename and delete are not batchable (U6 `EXCLUDED`, with the reason); AGENT_QUICKSTART, ARCHITECTURE and
DEVELOPMENT_HISTORY are left to U9.

Decisions for Kurt:

- One parameter set per document (`Params`), document-wide, outside every Body; names start lowercase.
- Deleting a parameter in use rejects unless `freeze_consumers:true` keeps the current values (spec default).
- Restart: Kurt's running app needs a restart to offer parameters (headless sessions have them now).

### U6 — atomic batches (F4)

Implemented per integration §2 U6 and `runtime/contract-3.2/specs/batch.md`. Files: new `src/kurtshape/batch.py`
(`EXCLUDED` with reasons, `OPS = MODEL_OPS − EXCLUDED` computed on use, `NO_FEATURE`/`NO_PART`, `validate`, `resolve`,
`run`, `finish_validation`, `report`, `failure_record`, `SplitGuard`, `capabilities`); `core.py` (`batch` in `OPS`,
`ARGS["batch"]` from the schema, `request_budget_s`, `BATCH_DISCARD_BOUNDARY`/`DISCARD_BOUNDARIES` in `_native_history`,
the `_dispatch` batch branch, `batch_report` in the result, the except-path split recovery and compact failure record,
the `_preview` batch proposal, `capabilities.batch`, `preview_operations`); `ui.py` (`request_budget_s` = 2/3 of the
bridge timeout); `operation_schemas.py` (the `batch` entry, `DOC_32_BATCH`, a batch preview example); tests
`tests/test_batch.py` (`BatchTests` 25, `BatchBridgeTests` 1, the reviewed `ALLOWED_TRANSACTION_CALLERS`),
`tests/test_operation_schemas.py` (a batch is previewable and undoable), `tests/test_dispatch_pipeline.py`
(`NEW_OPERATIONS_32`), `tests/test_contract32_conventions.py` (four codes); `tools/run_native_tests.py` (SUITES),
`tools/perf/bench_core.py` (`batch` section, report-only), new `tools/batch-undo-validation.FCMacro` registered as
`batch-undo`; new `examples/batch-request.json`, `examples/preview-batch-request.json`; `docs/OPERATION_CONTRACT.md`
(§3.2.4, two §3.2.0 rows, four §3.2.6 codes, one §3.2.7 bullet).

Tests run:

- `u6-classes-1` (test_batch, schemas, pipeline, conventions): 62 tests, 28 failures — one subTest-heavy test reporting
  each structural case (preview raised structural errors where the test expected `accepted:false`; changed so preview
  reports them like a single-op preview with a missing field), an ambiguous fillet point on the boss seam (test and
  example fixed), a pending-transaction test that needed an inspect after its native edit, the U2a schema test's
  preview/undoable expectation (batch is both by design) and the doc anchor. `u6-classes-2`: 62 tests, 1 failure (a
  nested `check_ms` timing in the preview/commit row comparison; the comparison now ignores timing keys).
  `u6-classes-3` (test_batch): 20/20 plus `BatchBridgeTests` 1/1.
- GUI recipe `batch-undo` (new; hidden private FreeCAD, production Panel, real Bridge over loopback):
  `runtime/ci-gui/batch-undo/run-e0d7d6b1bd1a4fd9933cb54390447fd3` — 26 checks: the GUI budget is 2/3 of the bridge
  timeout; a batch preview and a failing batch (rejected at its fillet step) leave revision, undo names, objects,
  intent, the GUI Modified flag, the selection, the camera and the active document unchanged with no transaction
  left active; the 4-feature batch commits as one undo step named after its label and one revision change, the tree
  and the panel's history show the four features; one panel undo removes all four, one redo restores them with the
  same volume.
- `bench_core --sections batch --holes 20 --repeat 3` (`runtime/test-tmp/u6-bench-batch/session/bench-batch.json`,
  report-only): six sketch-level steps sent one by one 344 ms (median), as one batch 184 ms, as a batch preview 403 ms.

Review (one independent read-only agent; verdict "needs fixes", one blocking finding; all code findings fixed):

- 1 (blocking, fixed): a numeric or boolean `steps` made the compact failure record raise inside the except path, so
  `dispatch` raised and a tracked request stayed `started`. `failure_record` is now total (never raises) and counts
  only list steps.
- 2 (fixed): the failure record was not really capped (a long invalid `label` or op string was stored whole); fields
  are clipped and a final fallback keeps only code, message and step/phase/rolled_back.
- 3 (fixed): an earlier parameter step's `parameter_context` leaked into a later step's error; it is cleared at every
  step start and after each successful batch step.
- 4 (fixed): a non-string step `op` gave `operation_failed` with a traceback; it is `unsupported_operation`.
- 5 (fixed): a step that aborted the batch transaction, changed the model outside any transaction and then raised went
  undetected; `run` flags the error when the active transaction is no longer the batch's, and `SplitGuard` treats it
  as a split (revision rotated, `rolled_back:false`, `residual_objects`).
- 6 (fixed): `after_abort` could raise; recovery runs in `_recover` behind a fallback that closes transactions,
  rotates the revision and returns `transaction_split` with `recovery_error`.
- 7–8 (fixed, tests): new `test_more_op_families_keep_one_transaction` (rectangle, arc, polyline, support change,
  `set_expression`, chamfer, `extrude_face`, hole, a parameter, new part, `transform_part`, `delete_part`, helix; one
  transaction; `created_feature` is None exactly for `NO_FEATURE`; one undo restores the full object set) and
  `test_legacy_pad_and_pocket_batch`; rejections compare `content_view` (BRep text digests masked, see below) plus a
  rounded geometric signature per object and `parameter_record`; structural rejections run with a non-empty redo list.
- 9–15 (fixed unless listed): test 20 has a lower bound; 12(a) checks the names after the boundary and the cleared
  redo list; the AST guard documents its static limits; `elapsed_ms` added; the preview budget starts before the
  clone; `capabilities.batch` no longer repeats the request size limit; `capabilities.parameters.batchable` derives
  from `EXCLUDED`; unexpected exceptions in the final checks keep `batch` details; docs describe the preview's
  structural-error shape and the preview `transaction_split`; a refusal for the user's pending transaction
  (`unmanaged_transaction`) no longer writes `LastFailure` into that transaction (§3.2.0 row). Not changed: test 5's
  "`$ref` resolved to null" case is unreachable with today's handlers (every non-`NO_FEATURE` op returns a name).
- Found while strengthening the oracle: an aborted studio recompute rebuilds the same solid with different canonical
  BRep text (Block/BaseFeature), so the rollback oracle masks `brep_sha256` and compares topology counts, volume,
  area, box and sorted vertices instead (the precedent in `test_operation_schemas`).
- After the fixes: `u6-classes-7` (test_batch, ParameterTests, test_operation_schemas) 80 tests, 0 failures.

Deviations from the spec:

- `rename_parameter` and `delete_parameter` are excluded from batches (U5 decision: native abort and undo restore a
  parameter wrongly when one transaction changes its identity twice); spec test 21's rename/delete parts became an
  exclusion assertion.
- `batch.validate` runs the per-step required-field check already (the spec deferred it to 5A, which U2a shipped).
- A batch preview reports structural errors (validation, unknown proposal keys) as `accepted:false` with the commit's
  error object and no clone; its guards still reject the request.
- AGENT_QUICKSTART, ARCHITECTURE and DEVELOPMENT_HISTORY are left to U9.

Decisions for Kurt:

- Deletions, rollback and parameter rename/delete stay out of batches (spec scope decision, reasons in
  `capabilities.batch.excluded`).
- The app stops a batch at two thirds of the bridge timeout (20 s of 30 s) with a clean, rolled-back
  `batch_time_budget_exceeded` instead of `outcome_unknown`.
- Restart: Kurt's running app needs a restart to offer `batch` (headless sessions have it now).

- Shared final-tree runs for U6–U8 (no `src/` change after them): full regression `final-full` — 1005 tests, 1000 passed, 5 perf skips, 0 failures, 0 errors, 1176 s, `source_unchanged: true`; `src/kurtshape` tree `de9e70b2…` (67 files), `kurtshape_build_sha256 191ff45d…`. The audit run and the GUI matrix are in U10 below; U10's review fixes moved the final tree to `a3e14aaa…` (`final-full-r2`).

### U7 — parameters panel (F3b)

Implemented per integration §2 U7 and `runtime/contract-3.2/specs/params_ui.md` on top of the N5 widget layer. Files:
`src/kurtshape/ui.py` (the three-section splitter with remembered heights; `last_operation_error`; the generic
staged-document refusal with code `document_changed`; `body` injected only for operations that take one and only as a
value the controller resolves (`_request_body`); action names; section hooks in `refresh`, `refresh_assembly`, the
no-document branch and `sync_edit_ui`; flush before New, Open (also before the file dialog), Save, Export, the Help
example, Recover, Create Assembly's new document and main-window Close; Delete/Rename routing; `general.cancel` →
`cancel_key`; `shutdown` closes the section and flushes the layout; `show_parameter_use`; C25 `editor_activity`
reports `parameter_edit`; transport attributes read defensively so stub transports keep working);
`general_actions.py` (Ctrl+C/Ctrl+V and document switches); `theme.py` (parameter rules); `parameter_panel.py`
(backend state strings, `usage_rows`, `unapplied`, a refresh before flush retries, a shutdown-safe `close`,
idempotent `set_unavailable` with the right discard reason); `parameters.py` (`usage_rows`; a set that is both
Touched and Invalid now names its failing formula); tests `ParameterAdapterTranslationTests` (headless Controller)
and `test_a_broken_native_formula_is_named_although_the_set_is_also_touched`; new GUI recipes `parameter-panel`
(77 checks) and `parameter-panel-reopen` (6), `design-surface` updated to three sections, the run_gui_recipe gate for
`parameter-panel` (check count and owned documents); `tools/perf/bench_gui.FCMacro` parameter metrics
(`-Parameters N`: N parameters created natively in one recompute, `parameter_section_refresh_ms`,
`parameter_commit_ms`); DESIGN.md, README.md, docs/EVERYDAY_UI.md, ARCHITECTURE.md, OPERATION_CONTRACT §3.2.3 "In the
app" and the `user_editing` tool list.

Found by the new recipe (fixed): binding a studio sketch through the feature editor's Formula field failed with
"body must identify a native PartDesign Body" — the panel sent the sketch's internal tool Body as `body`; and U4's
`Panel.tick` (`bridge.deferred`) plus U6's budget line broke recipes that stub the transport (design-surface,
rollback-history).

Review (one independent read-only agent; verdict "needs fixes", one blocking finding; fixed): C25 was missing (an
unapplied parameter edit now makes `close_document` refuse with `user_editing`, `tool:"parameter_edit"`); the
bench-gui parameter metrics existed only as a placeholder; `_request_body` fell back to the active Body when the
target had an owner (it now sends nothing then); Help→Example, Recover and Create Assembly skipped the flush; recipe
checks that could pass trivially were tightened (the bridge-New step asserts retirement and the "discarded" note and
adds the C25 refusal, the GUI-New flush and a dialog rejected across a bridge document switch; the stale banner must
name the failing parameter and mark formula rows stale; a refused Ctrl+S may not resend the known failure; the clean
field must read exactly 16; a downstream rejection must carry its feature-1 code into `last_operation_error`;
deleting a parameter leaves the Features rows unchanged); flush refreshes after a transient retry; `close()` is
shutdown-safe; repeated assembly refreshes are no-ops. Not changed: the tooltip appends parts to the "Affects" line
rather than to each "Used by" entry; `Panel._operation`'s new paths are covered by the recipe, not by unit tests.

### U8 — client reconciliation (F5 §6.3–§6.5)

`tools/assistant_client.py` rewritten from the reviewed prototype: `send` never raises for transport errors, keeps a
mutation's `request_id` for life, refuses oversize bodies locally, and reconciles uncertain outcomes through the
queue-bypassing `request_status` at the URL and token it started with (`completed`/`failed` with the stored response,
`pending`, `unknown` with a reason, `not_executed` only when the request provably never started; a read or a view op
that ends unknown is `retry_safe`). CLI: `--request-id`, `--wait` (75 s), `--no-reconcile`, `--status`,
`--reconcile --request-id` (a body is re-sent only with `--session-id` naming the same, still running session),
`--build-check`; exit codes 0/1/2/3/4 by the caller's next action and 64 for usage errors. `tools/assistant.ps1`
reads the exit code with `ErrorActionPreference` relaxed around the native call (Windows PowerShell 5.1) and throws a
message per code. Tests: `tests/test_assistant_client.py::AssistantClientReconciliationTests` (20: the 17 of §9.5,
the render_view matrix row, session-verified resends, transport failures that never raise, usage exit codes) against
the real Bridge with a fake controller and a ticker thread. Docs: OPERATION_CONTRACT §3.2.5 and the client-made codes
in §3.2.6, AGENT_QUICKSTART "Slow operations and retries", AGENTS.md `--build-check`.

Review (one independent read-only agent; verdict "needs fixes", nothing blocking; fixed): `http.client` errors and
non-object JSON could escape `_post`; `--reconcile` with a body could re-send into a restarted app's new session;
usage errors exited 2 ("pending"); the docs said a `not_executed` mutation may be retried with the same id (the ledger
replays the old answer — a new id is needed); the stderr identity line could trip PowerShell 5.1's `Stop`
preference; the resend's own answer is now used; the first POST leaves room for one status poll; `--reconcile`
applies the view-op rule; the CLI reads the session file once; a missing session file is 4 for requests;
`request_too_large` reports `limit` from the session file; `--build-check` honours `--wait`. Not changed: the
fallback read set is checked by reading, not by a bridge_native test.

- Shared final-tree runs for U6–U8 (no `src/` change after them): full regression `final-full` — 1005 tests, 1000 passed, 5 perf skips, 0 failures, 0 errors, 1176 s, `source_unchanged: true`; `src/kurtshape` tree `de9e70b2…` (67 files), `kurtshape_build_sha256 191ff45d…`. The audit run and the GUI matrix are in U10 below; U10's review fixes moved the final tree to `a3e14aaa…` (`final-full-r2`).

### U10 — final verification (2026-10-19)

Final tree: `src/kurtshape` `a3e14aaa…` (67 files, `run_ab.tree_sha256` rule), `kurtshape_build_sha256 3dd512eb…`.
It is the U1–U8 tree (`de9e70b2…`, build `191ff45d…`) plus the Fable independent-review fixes below and one change
from another agent: during U10 a Codex session edited `src/kurtshape/ui.py` (09:35 and 09:42), `tools/run_gui_recipe.ps1`,
`docs/OPERATION_CONTRACT.md` ("Viewport plane visibility"), `docs/DEVELOPMENT_HISTORY.md` and added
`tools/plane-visibility-validation.FCMacro` (P / Show planes covers custom datum planes; Hide/Show selected; GUI
presentation only, no bridge op). Kurt paused Codex and chose to keep that change in the 3.2 tree; every run below
from `final-full-r2` on includes it (hashes in `runtime/contract-3.2/u10/codex-plane-visibility-sha256.txt`). Its own
recipe (`plane-visibility`, needs the private BREF fixture) was not run by U10. Nothing committed.

**Fable's independent review** (`runtime/contract-3.2/fable-independent-review/REVIEW.md`; nothing in batch commit and
rollback, parameter rollback, `close_document`, render cancellation or the client state machine loses data):

- **R1 (fixed): bridge handler socket errors.** `do_POST` now catches `OSError` around every reply write (including
  `send_error` and `invalid_request`), so a client that left (WinError 10053/10054, a write timeout) never reaches
  `handle_error`; the server's `handle_error` appends to the session's `kurtshape.log` and never touches `sys.stderr`
  (FreeCAD's console in the GUI). Tests (`test_bridge.BridgeTimeoutTests`): a raw client that resets before the answer,
  then a second request answered in time with nothing on stderr; every reply write failing with
  `ConnectionAbortedError`/`ConnectionResetError`/`TimeoutError`/`OSError` on both the dispatched and the 403 path,
  with `handle_error` recording anything that escapes; `handle_error` writes the log, not stderr.
- **R2 (fixed, documented): first-POST floor.** The client's first POST gets at least half of a short budget (up to
  2 s), still leaving room for a status poll (`wait=2` gave 0.2 s before). §3.2.5 says a `wait` under about 5 s means
  "send, then reconcile". Test `test_a_short_budget_gives_the_first_post_time_to_answer` (0.6 s op answered directly
  with `wait=2`; a 3 s op still ends `pending` with polls).
- **R5 (fixed): ledger never left `started`.** `Controller._run` completes a tracked entry with `operation_failed` in a
  `finally` when `_dispatch` produced no response (a `BaseException`); test
  `test_dispatch_pipeline…test_a_base_exception_in_dispatch_never_leaves_the_ledger_entry_started` (an identical
  replay then returns the recorded failure without running).
- **R6 (docs):** §3.2 `close_document` now says `expected_revision` is required and a missing or stale one is refused
  with `stale_revision` before the other refusals.
- **R3 (decision for Kurt, unchanged):** see Decisions below. **R4:** first post-3.2 experiment in
  `docs/fable-deep-review/IMPROVEMENT_BACKLOG.md` ("After contract 3.2"), with its bench recipe.
- The four new checks fail on the pre-fix tree for the reviewed reasons (`u-runs/u10-r1-prefix`: R1 ×2, R2, R5) and
  pass after (`u-runs/u10-r1-fixed`: bridge, client, pipeline, conventions, schemas, bridge-native, 102/102,
  `source_unchanged: true`). Ruff 0.16.10 clean on the touched files.
- Also documented: the practical batch size in the app (§3.2.4, AGENT_QUICKSTART, `CADkz/AGENTS.md`): a 20-step chunk
  of `sketch_circle` + `pocket` on the 300 mm smoke plate took 9.6 s with no holes yet; with 10–20 holes only 17–20
  steps fit in 20 s (about 1.1 s per step), so keep such batches to about 12 steps and preview first.

1. **Regressions.** `final-full-r2` (final tree): 1010 tests, 1004 passed, 5 `perf:` skips, 0 failures, 1 error,
   1702 s, `source_unchanged: true` (native 898, bridge 73, shortcuts 33, workflows 6 cases). The error is a cleanup
   `PermissionError [WinError 5]` removing a render worker's `user-data` folder in
   `test_render_jobs…test_tracked_render_records_ledger_and_request_status` after its assertions passed, while other
   applications held the machine at 30–70 % load; the class rerun on the same build passed 63/63
   (`u-runs/final-full-r2-render-rerun`). `final-full-r1` (R1 tree, before Codex's edit; build `14b84541…`) is not a
   record: Codex changed `ui.py` mid-run, so `source_unchanged:false` and the build-identity test failed for exactly
   that reason. The audit-mode run was not repeated: `result_checks` did not change since `final-full-audit` (native
   897, the four U3 audit-by-design failures, no reuse mismatch).
2. **GUI matrix** (run on the U1–U8 tree before the review fixes, not rerun after R1–R6; the bridge paths they touch are covered by the regression): parameter-panel 77,
   parameter-panel-reopen 6, batch-undo 26, render-view 56, result-validation 36, document-lifecycle 48,
   interaction-idle passed; the 12 recipes that passed at U0 pass with their U0 check counts (design-surface 408,
   parts-refresh 91, extrusion-edit 43, dress-up-edit 57, onshape-workflows 45, sketch-plane-editor 27, step-import 19,
   assembly 58, assembly-step 38, everyday-ui 46, presentation-scheduling 73, step-export 91). history-lifecycle and
   rollback-history fail exactly as at U0 (pre-existing). On the final tree:
   - **interaction-idle ×3** (`runtime/contract-3.2/u10/perf-r1/gui-summary.json`; runs
     `run-5bbefdc4…`, `run-1947bb6d…`, `run-bce98e80…`): all three within every guard: idle tick total 46–50 ms
     (≤200), tick max 3.2–4.2 ms (≤50), heartbeat gap max 26–29 ms (≤100), 0 idle dispatches, 10 syncs (≤10),
     checkpoint median 6.3–7.0 ms, one bridge inspect 179–237 ms (≤500) with 1 dispatch; matching U0. (The earlier
     135 ms heartbeat gap right after the A/B did not recur.)
   - **bench-gui `-Holes 60 -Repeat 5` ×2 against U0** (`run-b2cffa7f…`, `run-34efc713…`): both passed. Taken alone
     they looked slower than U0 (`panel_refresh_ms` 19.0 / 39.5 ms against the 16.6 ms limit, `inspect_after_change`
     85–94 ms against 37 ms, `preview_first` about 17 s against 9.5 s). The **paired GUI A/B against 3.1**
     (`runtime/contract-3.2/u10/gui-ab/README.md`; 3.1 and 3.2 roots that differ only in `src/`, interleaved, 12
     unpinned and 8 pinned runs) settled it: **3.2 adds no GUI-only cost**. Pinned to the P-cores (`FFFF`, as the
     headless A/B), 3.2/3.1 is 0.82–1.05 on every shell, inspect, preview, checkpoint and edit metric (panel refresh
     9.9 against 12.1 ms, inspect after change 42.5 against 40.5 ms, preview first 9.6 against 10.1 s), and both match
     U0. `tick_after_read_request` is about 3× faster in 3.2 (17 against 49 ms; one inspect dispatch instead of two).
     Unpinned, the hidden GUI process runs in one of two speeds about 3× apart (likely E-cores or power throttling;
     not proven, and busy % does not show it), which hit 3.1 and 3.2 alike; the U10 overruns were slow-mode runs.
     Future GUI bench comparisons should pin both sides or compare only same-mode runs.
   - **bench-gui `-Parameters 50`** (informative, `run-0dc2712b…`): panel refresh 30.5 ms, idle tick 0.06 ms, tick
     after a refresh flag 47.3 ms, after a read request 41.2 ms, inspect after change 93.5 ms, parameter section
     refresh with a forced key change 1.5 ms, one parameter commit 325 ms; every section ok.
3. **Performance against f31** (final tree; `runtime/contract-3.2/u10/perf-r1/ab`, pinned `0xffff`, ABBA A1 B1 B2 A2,
   steps plate-false, studio-false and the supplement `--fixtures repro,drill,studio --repeat 5`; every step 15.6–24.7 %
   busy, under the 32 % gate, none discarded; A `dbb163f9…`, B `a3e14aaa…`): `compare_ab` valid, 99 metrics. With the
   designed changes declared (`compare-allowed.json`, same declarations as before) **0 metrics suspected**;
   `drill.helix_upstream_edit` 396 → 697 ms is inside its result-check allowance (limit 767 ms). As before, the
   comparison reads `passed:false` for one C34 count only: `repro.edit_extrusion` native recomputes 2 → 5 (the edit
   3.2 now rejects: the attempt, U3's unrefined retry and the recompute after rollback); a decision below. Without
   declarations (`compare.json`): 1 suspected (the helix family), the same counts. The pre-fix A/B
   (`runtime/contract-3.2/u10/ab`, tree `de9e70b2…`) gave the same picture (helix 400 → 646 ms, limit 770 ms).
4. **Private-app smoke, green** (`runtime/contract-3.2/u10/private_smoke.py`; walkthrough responses and images in
   `docs/contract-3.2/walkthrough/`, from the post-fix session `u10stall3fix` run 1, images checked by eye; the
   2026-10-18 set is in `runtime/contract-3.2/u10/walkthrough-2026-10-18/`): capabilities (contract 3, revision 2),
   `--build-check` current (`3dd512eb…`), `operation_schema`, compact inspect, the five examples, `close_document` dirty
   refused and clean closed, the 20-hole plate `rebuild` with a 2 s budget reconciled to `completed` by its original
   `request_id`. **25 checks, 0 failures.** The batch budget stopping the growing plate's 20-step chunks is now an
   expected check (`batch_time_budget_exceeded`, `rolled_back:true`, revision unchanged) listed under
   `expected_rejections` (here 19 and 20 of 20 steps completed at 20.0 and 21.7 s); before, `smoke-out.txt` read
   `passed:false` for it. Saved test documents moved to `runtime/contract-3.2/u10/stall-repro/saved-documents/`, so
   `projects/` is empty again.
5. **U10 stall: not reproduced in 4 pre-fix smoke runs (2 sessions); its one identified trigger is fixed by construction.** Reproduction as
   REVIEW.md lists it (`runtime/contract-3.2/u10/stall-repro/`, folders kept in `runtime/private/` and copied there):
   faulthandler armed inside each private app by a session-local FreeCAD Mod (`faulthandler_InitGui.py`, every Python
   thread dumped each 60 s; a GIL-needing heartbeat every 30 s), `repro_driver.py` (two smoke runs, then capabilities
   every 5 s for 2 min, process and socket state on any failed probe), `map_events.py` (stderr lines to smoke steps).
   - Pre-fix tree, offscreen (`u10stall1`) and `-Visible` Windows QPA (`u10stall2v`): 2 + 2 runs passed, 24/24 probes
     each (21–47 ms). **R1's trigger fired in every run**: the 2 s rebuild's handler thread raised
     `ConnectionAbortedError [WinError 10053]` from `send_json`, which reached `handle_error` and printed into FreeCAD's
     console (mirrored as `Err:` fragments in `freecad.log`), exactly the stalled log's tail. It did not wedge here, so
     no dump was needed; the stall remains a race we could not provoke, with this as its only identified trigger.
   - `resource deadlock would occur` (after `This plugin does not support raise()`): 9 per two runs offscreen, during
     batch commits, a save and inspects, never followed by a wedge, and **0 under Windows QPA**: an offscreen-QPA
     artefact, not the stall.
   - Post-fix (`u10stall3fix`, offscreen, final tree): 2 runs passed, 24/24 probes, **0 handler errors** in
     `freecad-stderr.txt`, `freecad.log` and `kurtshape.log` (the dead-socket write is absorbed in `do_POST`), the
     offscreen artefact unchanged (9).
   - "Refused" was never observed: no probe failed, so no process/backlog state was captured.
6. **Restart determination.** Read-only `Win32_Process` query: Kurt's KurtShape (live profile) was last started at
   10:37, after the last `src/` change (`ui.py` 09:42:06), so it runs the final tree; no restart is needed. The live
   bridge was never contacted.

Kept visible for acceptance (inherited, not fixed in 3.2): the Part Studio Check Geometry worker refuses its archive
(U3, pre-existing); `inspect` `bbox_mm` and STEP export use a container-local frame for Bodies nested in a placed
`App::Part` (`frame_note`); inspect cost grows after many managed recomputes (unattributed, pre-existing, 3b §8); F-14
(agent mutations still cancel an open feature editor; only `close_document` consults the editor); a batch preview cannot
be reconciled after a bridge timeout, only re-run; a single long batch step is not interrupted by the budget.

Not done (scope): U9's formal walkthrough runner and `Contract32ExampleTests` (the five examples run end to end in the
private smoke instead); `docs/contract-3.2/README.md`; responsiveness-preview ×3 (flaky at U0).

Decisions for Kurt:

- **R3, batch budget versus completed steps.** Today a batch whose steps all finished is still rolled back when the
  20 s budget has passed before its final result checks (seen in the smoke: 20 of 20 steps done, rejected at 21.7 s).
  (a) Apply the budget only between steps (§3.2.4's "before its next step" becomes the whole rule): finished steps are
  always validated and committed; the GUI stays busy for the checks (usually well under the time of one step) and an
  answer past the 30 s HTTP wait arrives through `request_status`, which the client already does. (b) Give the final
  validation its own allowance (for example up to the bridge timeout minus a margin): keeps the HTTP answer bounded in
  most cases but adds a second limit to explain. Unchanged until you choose.
- The C34 count above (`repro.edit_extrusion` 2 → 5 native recomputes for the edit 3.2 now rejects).
- Keep Codex's plane-visibility change in this commit (done, as you asked) or commit it separately.
- Batches stop at 20 s in the app (about 12 steps on a large part); parameter names start lowercase; images are
  session artifacts; deletions, rollback and parameter rename/delete are not batchable.

### GUI recipe drift: ui-refinement, sketch-behavior, review-interaction, review-lifecycle (2026-10-19)

These four recipes failed on f4b222b and on 5f4b9d0, on the Intel GPU and under Mesa alike. All four
expectations were stale after intended app changes; no app regression was found, so only the recipes
changed. Causes found with `git log -S`:

- **ui-refinement.** a558615 (10-14) removed the separate Remove toolbar button: Remove material is now
  Extrude's Cut mode and the More → Cut → "Extrude · Cut" preset (docs/EVERYDAY_UI.md). The recipe still
  required "Remove" in the bar (Boolean and Plane were there all along) and clicked it three times. It now
  checks that Remove is *not* a separate button and starts each cut from the real More → Cut menu action,
  checking that Cut mode opened. The next hidden failure was `path_outside_workspace` on Save: the portable
  first-run layout from c596685 (10-17) grants only `<checkout>/projects`. The recipe now grants its session
  file as the Save dialog does.
- **review-interaction.** 4681ddf (10-13) moved the error status colour from `#a2322c` to the theme token
  `COLORS["error"]` (`#bd3039`). It updated messages-validation but not gui-review-validation, which now
  uses the token.
- **review-lifecycle** and the Undo checks in **sketch-behavior.** 52b50b8 (10-14) made the first Finish
  of a *new* sketch one Undo step with its creation (docs/HISTORY_LIFECYCLE.md,
  tests/test_history_lifecycle.py). Both recipes still expected an empty sketch after Undo. They now
  expect the sketch to be gone and Redo to restore its geometry; lifecycle also checks the placement and
  attachment support. Lifecycle also gained a check that an accepted edit of an *existing* sketch is its
  own Undo step and leaves the sketch in place. That keeps the original "Undo removes no more than the
  accepted edit" intent where the contract still promises it. Lifecycle's stage recorder now tolerates the
  removed sketch, and its Save grants its destination (c596685).
- **sketch-behavior**, next hidden failure. The same 4681ddf palette refresh changed ink from `#243447` to
  `COLORS["ink"]` (`#2d3338`). The floating-parameter and hostile-style checks now compare against
  `ui.COLORS['ink']` and `['surface']`.

Local hidden runs (`tools/run_gui_recipe.ps1`, Intel GPU): all four pass. Recipes in one checkout must run
one at a time, because concurrent runs collide on `runtime/longrun/created.txt` and `pids.txt`.
