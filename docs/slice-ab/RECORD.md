# Slice A/B record — started 2026-10-21

One dated file for the execution of slices A (fast, honest feedback loop) and B (agent surface, cheap
half) of the October 21 improvement plan
(`C:\Users\Kurtz\Documents\KURT\CADkz\Claude\reviews\2026-10-21-improvement-plan-proposal.md`, §3, §5,
§9; evidence in `2026-10-21-improvement-plan-evidence\` beside it). Integrator: the KurtShape slice
session (Claude Fable 5.1), started from the Dodec session. The integrator writes no product code; one
implementation subagent and one independent reviewer subagent per unit. Unit briefs and reviewer
briefs live outside the repo in the side-session notes folder
`C:\Users\Kurtz\AppData\Roaming\Claude\side-session-notes\local_efbc217d-df6e-4d1f-9afe-dd70edf64a6e\`
(`slice-ab-COMMON-RULES.md`, `slice-ab-U<n>-brief.md`).

## Assumptions and permissions

Kurt approved starting without answering the four slice-A decisions. The work proceeds on the plan's
recommendations, stated to Kurt in the integrator's first message so he can object:

1. Confirm commits immediately once the provisional preview is valid; the exact preview is advisory (U1).
2. Escape ends the tool, never the sketch (wave 2, U7).
3. FreeCAD's one-minute autosaver is off while KurtShape recovery is on (wave 2, U8).
4. (Decision 6) The other agent's uncommitted open-handoff work is committed as one commit on its own
   branch; `KurtShape.exe` is ignored and built by `tools/build-windows-launcher.ps1`.

Branch commits per unit on `claude/slice-ab`: **granted by Kurt on 2026-10-21 at 20:12** ("commit
each reviewed unit on claude/slice-ab as it passes its gate"). Each unit is committed only after its
reviewer verdict is ACCEPT (or its fixes are applied and re-checked) and its gate is met; the commit
holds exactly that unit's files, the record, and the unit's test registration, made through a
temporary index so other units' uncommitted work in the same tree is never swept in.

## Phase 0 — baseline

**Branches (done 2026-10-21 18:56).** `main` untouched at `aec0336`.
`claude/open-handoff-startup-blank` = `bae9093` "Open a double-clicked FCStd in the running app;
replace the untouched startup blank" (the other agent's 14 files committed unchanged, authored Oct 20
18:28 – Oct 21 17:19; `KurtShape.exe` added to `.gitignore` instead of tracked). `claude/slice-ab`
created from `bae9093` and checked out; working tree clean at that point.

**Full suite baseline (`run-checks.ps1`, 19:18:21–19:38:58, in the background under the bundled
`pythonw.exe`, source `bc04f8aa…`, 74 files).** **Green: 1,074 tests, 1,069 passed, 5 skipped,
0 failures, 0 errors in 1,230 s** (native 961 / 956 passed / 5 skipped in 1,147 s; bridge 73 / 73 in
80 s; shortcuts 34 / 34; workflows 6 cases, 415 checks). The five skips are the opt-in perf checks
(`ResultValidationPerfTests` ×1, `StatusPerformanceTests` ×4, `KURTSHAPE_PERF` unset); the external
examples were present, so no external-fixture skip. Report:
`runtime\test-tmp\checks-20261021-191821-36264\evidence\checks\native.json` (junit beside it). Log
copy: `…\scratchpad\perf-baseline\baseline-run-checks.txt`. Wave 1 edits started only after this
result; the one tree change before them is the registration of the five wave-1 test classes in
`tools/run_native_tests.py` `SUITES` (integrator, 19:45).

**Pinned benchmarks (`tools/perf/bench_core.py --repeat 3 --measure false`, P-core mask `0xFFFF`,
private sessions `runtime\bench\slice-ab-baseline\<step>`, src tree `d3313b76…`, 74 files, same tree
the perf audit measured).** Medians in ms; "audit" = the perf audit's pinned run of 18:03 on the same
tree. Within ±20 % of the audit except `inspect_warm` on plate60 (18 vs 41 ms, the audit's number
was the outlier against Oct 17's 16.5).

| plate60 | baseline | audit pinned |
|---|---|---|
| tip edit total / overhead / kernel | 444 / 66 / 385 | 435 / 55 / 377 |
| upstream edit | 6,755 | 7,071 |
| inspect warm / after change | 17.8 / 52.9 | 40.5 / 49.5 |
| checkpoint (forced saveCopy + verify) | 1,374 | 1,271 |
| exact preview first / update | 8,207 / 6,805 | 9,074 / 7,381 |
| open KurtShape / native | 1,906 / 1,754 | 1,972 / 1,864 |

| studio fixture | baseline | audit pinned |
|---|---|---|
| tip edit total / overhead / kernel | 1,457 / 1,219 / 238 | 1,396 / 1,184 / 213 |
| selector evaluation / auto-scope / result validation + keys | 656 / 487 / 67 + 12 | 583 / 504 / 57 + 11 |
| upstream edit / full rebuild | 920 / 577 | 829 / 598 |
| inspect warm / after change | 45.4 / 281 | 46.9 / 266 |
| checkpoint | 264 | 220 |
| exact preview first / update | 1,191 / 1,017 | 1,093 / 985 |
| open KurtShape / native | 402 / 223 | 379 / 211 |

Reports: `runtime\bench\slice-ab-baseline\p60\evidence\perf\bench-p60-baseline.json` and
`…\studio\evidence\perf\bench-studio-baseline.json` (system busy 21 % and 30 % of all cores during the
runs; no `freecad.exe` running). Runner scripts and copies of the reports:
`C:\Users\Kurtz\AppData\Local\Temp\claude\C--Users-Kurtz-Documents-Dodec\94fae404-9685-4c94-8cd1-756878db2de4\scratchpad\perf-baseline\`.

**Dodec Hub probe (private copy of the Oct 20 recovery checkpoint `runtime\project-recovery\9aeff2fd-….FCStd`,
10.0 MB, 727 objects, 60 bodies, 306 features; the perf audit's probe B script, pinned, session
`runtime\bench\slice-ab-baseline\probeB`, 19:08).** Kurt's file and app untouched. Baseline / audit:
native open 1,459 / 1,501 ms; managed open 1,347 / 1,263; inspect warm 75-82 / 72-80; saveCopy
2,434-2,464 / 2,367-2,423; forced checkpoint 2,567-2,637 / 2,631-2,702; **one Length edit on
`NotchesTool` 8,507 / 9,270 = kernel 3,465 + selectors 4,158 + validation 589 + inspection 106**;
undo 7,880 / 8,197; rebuild 10,312 / 12,921 = kernel 4,749 + selectors 4,160 + validation 1,098.
Output: `…\scratchpad\perf-baseline\probeB-baseline.jsonl`.

**Hidden app from the branch.** `tools/private-session.ps1 -Session sliceab -Ensure` started a private
offscreen KurtShape from the `claude/slice-ab` checkout twice (PID 57496 at 19:09, whose response
body a stale shell chain overwrote; PID 33580 at 19:40). `capabilities` through
`tools/assistant_client.py` under `pythonw.exe` answered `ok` both times: build id
`src-bc04f8aac61ef01a` (source `bc04f8aa…`, 74 files, workers load from disk), git `head`
`bae9093…` on `refs/heads/claude/slice-ab`, `dirty: false`, `on_disk.matches_loaded: true`, 84
operations, contract 3 revision 2. Stopped with `-Stop` each time; no `freecad.exe` before or after.
Response copy: `…\scratchpad\perf-baseline\hidden-caps2.txt`.

## Wave 1 — parallel units on disjoint files

| Unit | Brief (one line) | Implementer result | Reviewer verdict | Gate measurement | Commit |
|---|---|---|---|---|---|
| U1 | A1 immediate Confirm: commit on a valid provisional preview, exact preview advisory (`ui.py` accept paths, `feature_panel.py`; Fable, high) | reported 21:05: new pure rule `confirm_gate.verdict/accept_enabled` (exact valid → commit; provisional with mesh and no error → commit for creation; proposal mismatch → none); `ui.py` ±19 lines in `preview_status`/`accept_task` (`flush(provisional=True)`), `extrusion_preview.flush/current_result` gain a `provisional` flag (defaults unchanged); no cancel code needed because `_operation` already clears the preview worker before dispatch; edits, Up to face, Through all, face extrusions and legacy Remove without direction keep the exact-only gate (no provisional result exists for them); `ConfirmGatingTests` 6/6, regression set 64/64 (`runtime\bench\slice-ab-u1\`); new recipe `confirm-gating` (plate60, real dialog, `QTest` click while the exact worker was evaluating): shell latency click→`pad` dispatch **91.6 ms** (loaded machine; ~42 ms gate, rest the pre-existing pre-dispatch inspect), total click→row 2,731 ms (kernel), exact wait skipped 20.7 s, committed volume = exact 3,815,146.0606 mm³ (Δ 0.0); `extrusion-preview` 32/32 and `extrusion-edit` 43/43 recipes pass; `docs/EXTRUSION_EDIT.md` updated; notes: recipe source-drift check narrowed to the Confirm-path files during concurrent edits; latency to be re-measured on a quiet machine | **SEND BACK** (21:45; Opus high) after an otherwise sound review (scope clean, edits exact-only, defaults preserved for every caller, no late ghost: `_operation` clears the worker synchronously before dispatch, failure paths keep the dialog open; reviewer's own recipe run passed 24/24 with shell latency **56.0 ms**, total 1,580 ms, 12.4 s exact wait skipped, volume Δ 0.0; test set 64/64). Two blocking findings, both reproduced headlessly: (1) a **legacy Pad that adds no material commits as a no-op** because legacy `core.py` pad has no empty-add check (only legacy pocket and Part Studio validate), so the brief's premise "the real operation validates at commit" is false for legacy pads; (2) an **exact "no material" verdict is erased by the `schedule()` that `accept_task` itself runs**, so Enter / Shift+Enter commit anyway. Six minor: a failed provisional commit is re-offered; a click during the 0.4–0.8 s exact snapshot is dropped with "Preview cleared"; the stale-revision test never dispatches; the narrowed drift check; no keyboard path in the recipe; a stale docstring. Fixes sent to the implementer at 21:50: provisional acceptance only where the commit validates geometry (Part Studio documents and legacy pocket; legacy pad keeps the exact gate), remember exact and commit rejections per normalized field set, defer a click during the snapshot, the extra tests and recipe steps; the missing legacy-pad `empty_add` check is recorded as a wave-2 core item | Confirm click → commit dispatched < 100 ms on plate60; committed volume = exact preview | — |
| U2 | A5 bounded, stably keyed icon cache; row icons set only on change (`presentation_icons.py`, `history_model.py`; Opus, high) | reported 20:05: pixel-signature LRU (`NATIVE_CACHE_LIMIT` 128), hit returns a stable-cacheKey copy; `HistoryModel.icon_sets` counter + per-row signature records; `IconCacheTests` 6/6, `test_responsiveness` 13/13 (reports `runtime\bench\slice-ab-u2\`); hit 23.5 µs vs miss 1,481 µs per call; hidden-app memory check not done | **ACCEPT** (20:20; Opus high): scope clean, signature stable across fresh QIcons and sensitive to the last pixel, LRU and `clear_cache` behave, no record leak on document switch or row removal, test would fail on the old code; 4 minor notes: signature ignores Disabled/Selected/Active pixmaps and other sizes (docstring to say so), raw native feature-row icons still pay one signature per refresh (~0.8 ms per 34-row studio refresh, 9 ms if SVG-backed), the limit comment omits DPR, one timing assertion with a 50× margin; reviewer re-ran `IconCacheTests` 6/6 and `test_responsiveness` 13/13 (`runtime\bench\slice-ab-rev2\`); the two doc fixes were applied by the implementer (comment-only delta checked by the integrator) | cache length 2, constant over 1,000 refreshes (bound 128); 0 `setIcon` on unchanged refreshes, 41 on the first; integrator run `IconCacheTests` + `test_responsiveness` 19/19, `source_unchanged: true` (`runtime\bench\slice-ab-int\u2-report.json`) | `5391b8e` (20:31) | cache length constant over 1,000 refreshes; zero `setIcon` on an unchanged refresh | — |
| U3 | A3 performance-core pinning in the launchers, bench-gui A/B decides the default (`launch-kurtshape.ps1`, `private-session.ps1`, `assistant.ps1`, plus the shared helper `tools/performance-cores.ps1` approved by the integrator at 19:55 so the mask derivation is not duplicated; Opus, high) | implementer launched 19:47 | — | pinned/unpinned ratio recorded; default off without a gain | — |
| U4 | B2 session SDK `kurtshape.session` + `tests/test_session.py`; no `core.py` edits (Opus, xhigh) | reported 21:10: `session.py` 687 lines (headless and bridge transports with one API; fresh-mode isolation sets the six variables and `settings.json` `workspace_layout: portable` before FreeCAD loads, refuses `runtime`/`runtime\user-data`, TEMP ≤ 104; inherited mode when FreeCAD is already loaded; envelope from the server's `operation_schema` with a schema fallback; `preview` always carries the revision; `stale_revision` → re-inspect and resend once with a new request id, only for SDK-stamped revisions; `part_named`, `parts`, `feature`, `edge_at`/`face_at`, `resolve`, `sketch`/`circle`/`polygon`/`finish` with the Rev B semantics; `requests.jsonl` + `build.log`; `close()` closes documents then the Controller); `SessionTests` 14/14 in ~8 s (`runtime\bench\slice-ab-U4\tests\report-final.json`); **gate: Rev B recipe replayed through the SDK, 316 calls, 0 failures, 11 of 11 STEP geometry digests identical to the Oct 20 originals** (`runtime\bench\slice-ab-U4\digest-replay.json`; the recipe has 11 parts, not 12); request streams identical to the original build's once envelopes are dropped; `preview` bug recorded for U6 (`core.py:323` READ_OPS vs `_preview` ~2438 rejecting a missing revision with `stale_revision`; `operation_schemas.py:1420` special-cases it); not verified: no live loopback bridge run (the bridge path was tested through the real `send` with `_post` patched); one rule slip (a global `python -` probe that ran no code, stopped after 120 s) | **ACCEPT** (21:35; Opus high): scope clean; fresh-mode isolation, envelope stamping, once-only stale resend (never after a timeout or unknown outcome), state tracking, helpers and ledger all checked against the code and `assistant_client`; the reviewer re-ran the Rev B replay itself (158 requests, 0 failures, `COMPLETE 11`) and recomputed the digests: 11/11 equal; the `preview` bug record verified (`core.py:323` vs `:2438`; the schema already requires the revision, the inconsistency is the `READ_OPS` classification); 7 minor notes: inherited mode checks only `FREECAD_USER_HOME` (no test for its refusal), `tolerance` alone wraps the selector in a geometry filter, a refusal test that would write into the live runtime if the guard regressed, `REVISION_ALWAYS` is redundant with the schema, `close()` can mask the body's exception and does not log discards, the bridge's default ledger lands in the live `runtime\sdk-ledger`, no token-absence assertion; five fixes (1, 2, 4, 5, 7) sent to the implementer at 21:40 and applied at 21:55 (delta checked by the integrator: inherited-mode refusal also for a `FREECAD_USER_HOME` inside the live profile, with a test and `isolation["warnings"]` for a long inherited TEMP; `tolerance` alone adds no geometry filter; `REVISION_ALWAYS` documented as belt-and-braces; `__exit__` keeps the body's exception and notes a close failure, `close_document` done records carry `discarded_unsaved_changes`; token-absence assertion); the live-runtime write risk (3) and the bridge ledger default (6) are recorded as follow-ups | integrator run `SessionTests` 16/16, `source_unchanged: true` (`runtime\bench\slice-ab-int\u4-report.json`); **integrator replay of the Rev B recipe on the fixed SDK: `COMPLETE 11`, 11/11 STEP geometry digests equal to the Oct 20 originals** (`runtime\bench\slice-ab-int\u4\digest.json`) | committed 22:00 (hash in the next record update) | Rev B fixture recipe replays through the SDK with identical STEP geometry digests | — |
| U5 | B4 generated `docs/OPERATIONS.md`, `docs/COOKBOOK.md`, one launch rule in `AGENTS.md`, `SHARING_STATUS.md` archived (Opus, high) | reported 20:38: `tools/generate_operations_doc.py` renders all 84 ops (sections by kind, every argument with type/default/required, the schema's first example, derived Errors lines intersected with the codes `src/` raises, `--check` mode, self-isolating profile); `OPERATIONS.md` **58,691 bytes (target was about 35 KB; accepted by the integrator rather than cutting runnable examples or argument lists)**; `COOKBOOK.md` 1,365 words, quickstart executed headless; launch rule section "Launching: which app an agent uses" in `AGENTS.md`, quickstart and CADkz `AGENTS.md` link to it (before-copy kept in scratch, delta limited to the "Which path" paragraphs); `SHARING_STATUS.md` moved by `git mv` with banner; one pointer line in `OPERATION_CONTRACT.md`; `OperationsDocTests` 4/4 ×3 runs, neighbours 6/6 (`runtime\bench\slice-ab-U5\`); notes: `OPERATIONS.md` must be regenerated after every integration that changes schemas or raised codes; `.gitattributes eol=lf` suggested (not done, out of list); the rule says the user starts the visible app (Kurt's standing rule), no agent exception | **ACCEPT WITH FIXES** (21:10; Opus high): scope clean, seven generated entries checked by hand against the schema, Remove/Hole polarity and helix/pattern/rim claims checked against the code, quickstart executed, determinism confirmed (two hash seeds, `--check` 0/1), link checker proven on a probe, launch rule matches Kurt's standing rule; fixes (all minor): per-op Errors lines are honest but incomplete, so the reading guide must say so (`save`, `hole`, `pad`/`revolve`/`sweep` miss handler-raised codes); the cookbook's batch snippet pads 4 mm inside the 6 mm plate and fails `empty_add` when run; a latent test bug on Python dict snippets; a spacing nit; the four fixes were applied by the implementer at 21:20 (delta checked by the integrator: reading-guide wording, "Schema-named errors:" label and regenerated `OPERATIONS.md` now 59,733 bytes, batch snippet `length: 10` run after the quickstart, `request["op"] = op.value`, spacing) | `OPERATIONS.md` regenerates byte-identically (`--check` exit 0 on the live tree; two hash seeds identical per the reviewer); 245 links and anchors resolve; integrator run `OperationsDocTests` + contract neighbours 10/10, `source_unchanged: true` (`runtime\bench\slice-ab-int\u5-report.json`); the CADkz `AGENTS.md` edit is outside the repo (not versioned; before-copy in the U5 scratch) | `007d0f9` (21:27) | `OPERATIONS.md` regenerates byte-identically; every link resolves | — |

Test registration for the five classes in `tools/run_native_tests.py` `SUITES` is done by the
integrator before the implementers start (so no two units edit that file).

## Wave 2 — serial owners of `core.py` and `ui.py`

Not started. Follows the plan's §9 after wave 1 is integrated and the full suite is green again.
