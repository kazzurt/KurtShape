# Long run status

Program: C:\Users\Kurtz\Documents\KURT\CADkz\Claude\prompts\2026-10-03_codex_long-run-program.md
Program SHA-256 when last read: BFD1820915CDEDE335C2FF421163F1A404E666211402E81DB8E936631D3C2995, 2026-10-03 14:44 America/Los_Angeles
Updated: 2026-10-03 14:44 America/Los_Angeles
State: IN PROGRESS Q01 since 2026-10-03 14:44
Last green commit: 259a61b (tag longrun/Q00a)
Green copy: not created; Q01 follows Q00a
Free disk: 60.1 GiB

## Queue

| Q | Increment | State | Commit | Tests native/bridge/shortcut | Note |
|---|---|---|---|---|---|
| Q00a | Foundation: fixes, isolation, one runner | DONE | 259a61b | 147/7/22 | 405 workflows; exactly 3 external skips without examples |
| Q01 | Green copy | IN PROGRESS | | | Launcher isolation and safe sibling worktree |
| Q00b | Foundation: CI, GUI runner, benchmarks, lint | QUEUED | | | Needs Q00a |
| Q02 | Keyboard and command registry | QUEUED | | | Needs Q00a |
| Q03 | Fast build status | QUEUED | | | Needs Q00b |
| Q04 | Operation registry | QUEUED | | | Needs Q03 |
| Q05 | Sketch operations | QUEUED | | | Needs Q04 |
| Q06 | Agent read access | QUEUED | | | Needs Q03/Q04 |
| Q07 | Preview engine | QUEUED | | | Needs Q03 |
| Q08 | Feature framework, first six features | QUEUED | | | Needs Q02/Q04/Q07 |
| Q09 | Idle recovery | QUEUED | | | Needs Q00b |
| Q10 | Remaining schema features | QUEUED | | | Needs Q08 |
| Q11 | Incremental intent and summaries | QUEUED | | | Needs Q03 |
| Q12 | Feature list | QUEUED | | | Needs Q08/Q11 |
| Q13 | Variables | QUEUED | | | Needs Q08 |
| Q14 | Event-driven shell | QUEUED | | | Needs Q09/Q11 |
| Q15 | Inspection and performance panel | QUEUED | | | Needs Q06 |
| Q16 | Import/export worker | QUEUED | | | Needs Q03/Q09 |
| Q17 | Exchange formats | QUEUED | | | Needs Q16 |
| Q18 | Assemblies: live links | QUEUED | | | Needs Q04/Q07 |
| Q19 | Assemblies: connectors/mates/drag | QUEUED | | | Needs Q18 |
| Q20 | Assemblies: structure/reports | QUEUED | | | Needs Q19 |
| Q21 | Configurations | QUEUED | | | Needs Q12/Q13 |
| Q22 | Sketcher behaviors | QUEUED | | | Needs Q05/Q13 |
| Q23 | Feature repair and control | QUEUED | | | Needs Q12 |
| Q24 | Hardening and handoff | QUEUED | | | After eligible work |

## Questions for Kurt (answer in NOTES.md or in the chat)

| # | Since | Question | Options, with the default I took | Blocks |
|---|---|---|---|---|
| 1 | Start | Projects/history D4, atlas question 9: snapshot store or branches/merges, formal releases? | Draft: snapshot store, optionally on Git; parked | U6/G10 |
| 2 | Start | Cross-project pinned links? | Park until projects/history is settled | Cross-project links |
| 3 | Start | Drawings D7/questions 7–8: GD&T or reference sheets, standards, title block, model tolerances? | Draft: TechDraw storage, drawing workspace, model-owned tolerances; parked | U8/G13 |
| 4 | Start | Decoder D8 and API capture of the two Dodec documents? | Draft: REST JSON plus captured query oracle; no API access during this run | U5/G8 |
| 5 | Start | Onshape archive plan and API allowance (question 4)? | Parked; no API calls | Archive collector |
| 6 | Start | Selection D6/question 2: additive toggle or replace/Ctrl? | Draft additive; today's selection remains until answered | Default selection model |
| 7 | Start | Assistant write roots: scope to chosen projects and revocable grants? | Existing roots remain; proposed REVIEW P1-12 design parked | Root scoping |
| 8 | Start | Sheet metal, frames and DWG (questions 10–11)? | Deferred; DWG requires external converter | These features |
| 9 | Start | Push local main when ready so CI can run. | Kurt pushes; this run never pushes or opens PRs | GitHub CI only |

## Try this (newest first)

### Q00a foundation (259a61b)

1. Switch from a separate FreeCAD document tab back to the KurtShape project; the interaction recipe verified state returns after an unmanaged tab.
2. Run run-checks.ps1 -Full; the recipe verified 147/7/22 plus 405 workflow checks with original source hashes unchanged.
3. Run an isolated check with a nonexistent KURTSHAPE_ONSHAPE_EXAMPLES override; the recipe verified exactly three external skips.
4. Copy a feature, save and reopen its project; review-copy verified retained native dependencies and restored the clipboard.

### Messages copy controls (69dc29c)

1. Open Messages and use Copy all; the hidden recipe verified exact Unicode and newlines.
2. Select log text and use Ctrl+C; the recipe verified CAD Copy does not run.
3. Select a status error and use Ctrl+C, or right-click Copy message for its full clipped text.

## Budgets on Kurt's machine

| Metric | Fixture | Baseline | Best | Latest | Target | Open? |
|---|---|---|---|---|---|---|
| Baselines | Plate/studio | Q00b pending | | | Program section 9 | Yes |

## Red at baseline

- None in run-checks: 141 native, 4 bridge, 22 shortcut tests passed; 0 skips. Native suite 170.872 s. GUI baseline completed: 14 pass, 2 red, plus Messages pass.

- interface: Confirm creates valid native solid failed after 11 checks; task remained open after depth change (screenshot inspected).
- carrier-spike: historical pre-U2 history expectation failed after 17 checks.

## Parked work

| Q | Branch | Cause | What would unblock it |
|---|---|---|---|
| Initial decision-dependent items | None | Questions above | Kurt's answer |

## Notes handled

| Note or report (first line) | Date | What I did | Commit |
|---|---|---|---|
| Existing user reports | 2026-10-03 | Five reports from October 2 existed before this run; recorded below as baseline | Start |

Existing reports: kurtshape-problem-20261002-075903-f80b59d0.json, kurtshape-problem-20261002-080303-4731a62a.json, kurtshape-problem-20261002-080518-cb77b2bc.json, kurtshape-problem-20261002-085826-d3479fc2.json, kurtshape-problem-20261002-181622-afd5a3ef.json. No green tree exists. No Kurt-owned tracked changes at initialization.

Own recipe report: kurtshape-problem-20261003-204924-ac7dc9ee.json came from the baseline review-copy check and is not a new user instruction.

## Log

- 2026-10-03 13:40: Started first steps. Located repo under Codex/kurtshape. Fetch succeeded after Windows credentials required broader access and a command-only safe.directory exception; no config file changed.
- 2026-10-03 13:42: Messages recipe passed 34 checks, exited, restored clipboard; screenshot inspected and independent read-only review found 0 issues. Committed 69dc29c.
- 2026-10-03 13:43: Merged origin/claude/clever-cerf-fe9sjf with --no-ff; exactly 9 review files, no conflict.
- 2026-10-03 13:45: Baseline run-checks passed 141/4/22, no skips. Preserved native report in runtime/longrun; restored exactly 4 rewritten tracked evidence paths. Completed full program and required first-step source reading. Initialization records ready for longrun/start.

- 2026-10-03 13:56: Q00a started; full program re-read, unchanged SHA-256. GUI baseline completed before source/script/macro edits; U2 99, refinement 106, interaction 10, other results in runtime/longrun/gui-baseline-results.json. Probe verifies pinned runtime home/OCCT/Assembly module. Plan recreated after baseline wrapper had restored/deleted in-flight records.
- 2026-10-03 14:09: Resumed after compaction; program/STATUS/NOTES/spec re-read, git state explained by Q00a. Source implementation reviewed; closing PID records for fresh-native proofs and exact-byte local tree hashing before consolidated gates. No user notes or new user reports.

- 2026-10-03 14:11: Consolidated Q00a Full gate started; staged explicit implementation paths, exact-byte local tree snapshot captured. Read-only runner review ongoing.

- 2026-10-03 14:14: Full gate attempt 1 failed: new rejected-header bridge test hit Windows ConnectionAbortedError 10053; native147, shortcuts22 and405 workflow checks passed, no skips, source hashes unchanged. Interaction passed11, process1352 exited0 and screenshot inspected. Local tree attempt1 failed only new tools/__pycache__, diffhash unchanged. Closing premature helper imports and deterministic header-only rejection requests; independent review identified reporting/class-inventory/process-cleanup gaps being repaired. NOTES remains empty.

- 2026-10-03 14:16: Removed only the new evidence-helper .pyc and its verified-empty tools cache directory. All 23 macros initialize bytecode suppression before helper import; new bridge guards test header-only rejections without changing HTTP or no-mutation assertions. Runner robustness corrections and failure probes in progress; living M1 record updated.

- 2026-10-03 14:24: Failure injection passed 9 checks; deliberate untracked validation JSON was rejected and exactfile removed, normaltreecompare passed. Full attempt 2, missing examples andinteraction/copy/U2 gates launched in isolated sessions; final inventory edge review waits for hash gates to finish.

- 2026-10-03 14:27: Full attempt 2 and missing examples gate passed 147/7/22 plus405 workflow checks, missingfixtures exactly3 external skips. Interaction/copy/U2 passed 11/25/99; owned PIDs50368/20328/71560 exited, source hashes unchanged, U2finalparts andmerge-scope screenshots inspected. Treeattempt2 passed 978a7c0d...42ff9d; no newcache. Missing-source tools each exit2 before report write. Startup thumbnail andcaught native notify Access violation match prior tracked STEP GUI evidence; no new warning class. Closing last inventory name-collision review finding before final record.

- 2026-10-03 14:32: Minimal inventory collision fix frozen; expanded failure probe passed 10 checks. Final Full and missing examples gates started for the final source version. No GUI code changed since11/25/99 passed; final review pending, all user notes still empty.

- 2026-10-03 14:37: Final Full and missing-example gates passed on the final source; exact tree SHA256 dff506781293741634eff0f038b41acf13e1ffd2cc1140dc87e056ae18e4fc60 unchanged. Recorded explicit small evidence and living docs; preparing focused commit/tag, then Q01. Final native suite 94.629 s; this is elapsed validation, not a benchmark.

- 2026-10-03 14:39: Final independent read-only review found0 remaining actionable issues;10 infrastructure findings and2 gate corrections addressed. Evidence regenerated after final M1 record; focused commit/tag next.

- 2026-10-03 14:40: Finished Q00a at 259a61b, tagged longrun/Q00a; tree clean after focused commit. Starting the program re-read for Q01.

- 2026-10-03 14:44: Q01 started after resume audit; main at longrun/Q00a, only STATUS changed, no new user reports or notes. Disk 60.1 GiB. Full program and brief invariants/facts re-read; SHA unchanged.

- 2026-10-03 14:51: Q01 launcher probe attempt 1 stopped on the probe's PSObject property-count check (PowerShell member enumeration); PrintOnly process/directory traps were not triggered and Validation resolution passed. Correcting only the scratch probe count; NOTES empty.

- 2026-10-03 14:54: Q01 launcher probes passed13 and injected updater guards passed6. Independent review found two infrastructure risks: git stderr contaminating metadata and linked session paths redirecting validation; both corrected before actual launch. Starting main interface and full regression gates; no user notes.

- 2026-10-03 14:55: Q01 interface attempt 1 failed; owned PID26412 exited. Reading exact failing report before any retry; launcher/regression source unchanged. NOTES empty.

- 2026-10-03 14:59: Q01 interface attempt1 failed unchanged visibility assertion after18checks. Independent audit confirmed U2 logical-part visibility applied to legacy files; guarded only that loop by studio.enabled, keeping all visibility assertions. Full147/7/22+405 and exact tree check passed before repair; final-source checks and interface attempt2 now start. Main interface is preliminary to the required green-source gate.

- 2026-10-03 15:00: Repaired main interface passed41 checks, ownedPID23724 exited; no visibility assertion changed. Reparse mock probe attempt1 failed because mocked linked-path binding did not cross script scope; correcting scratch injection binding before retry, not production guards. NOTES empty.

- 2026-10-03 15:03: Q01 final main gate passed147/7/22+405 and interface41; diffhash8ba4d5e...e9be0 unchanged. 27 script safety probes passed. Final independent source review0 remaining. Prepared focused intermediate code commit; actual green worktree gate will precede Q01tag. No new warning class; NOTES empty.
