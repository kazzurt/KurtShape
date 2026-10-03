# Long run status

Program: C:\Users\Kurtz\Documents\KURT\CADkz\Claude\prompts\2026-10-03_codex_long-run-program.md
Program SHA-256 when last read: BFD1820915CDEDE335C2FF421163F1A404E666211402E81DB8E936631D3C2995, 2026-10-03 13:45 America/Los_Angeles
Updated: 2026-10-03 13:49 America/Los_Angeles
State: BETWEEN INCREMENTS
Last green commit: initialization commit receives tag longrun/start
Green copy: not created; Q01 follows Q00a
Free disk: 60.4 GiB

## Queue

| Q | Increment | State | Commit | Tests native/bridge/shortcut | Note |
|---|---|---|---|---|---|
| Q00a | Foundation: fixes, isolation, one runner | NEXT | | | GUI baseline before edits |
| Q01 | Green copy | QUEUED | | | Needs Q00a |
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

### Messages copy controls (69dc29c)

1. Open Messages and use Copy all; the hidden recipe verified exact Unicode and newlines.
2. Select log text and use Ctrl+C; the recipe verified CAD Copy does not run.
3. Select a status error and use Ctrl+C, or right-click Copy message for its full clipped text.

## Budgets on Kurt's machine

| Metric | Fixture | Baseline | Best | Latest | Target | Open? |
|---|---|---|---|---|---|---|
| Baselines | Plate/studio | Q00b pending | | | Program section 9 | Yes |

## Red at baseline

- None in run-checks: 141 native, 4 bridge, 22 shortcut tests passed; 0 skips. Native suite 170.872 s. GUI baseline is pending Q00a.

## Parked work

| Q | Branch | Cause | What would unblock it |
|---|---|---|---|
| Initial decision-dependent items | None | Questions above | Kurt's answer |

## Notes handled

| Note or report (first line) | Date | What I did | Commit |
|---|---|---|---|
| Existing user reports | 2026-10-03 | Five reports from October 2 existed before this run; recorded below as baseline | Start |

Existing reports: kurtshape-problem-20261002-075903-f80b59d0.json, kurtshape-problem-20261002-080303-4731a62a.json, kurtshape-problem-20261002-080518-cb77b2bc.json, kurtshape-problem-20261002-085826-d3479fc2.json, kurtshape-problem-20261002-181622-afd5a3ef.json. No green tree exists. No Kurt-owned tracked changes at initialization.

## Log

- 2026-10-03 13:40: Started first steps. Located repo under Codex/kurtshape. Fetch succeeded after Windows credentials required broader access and a command-only safe.directory exception; no config file changed.
- 2026-10-03 13:42: Messages recipe passed 34 checks, exited, restored clipboard; screenshot inspected and independent read-only review found 0 issues. Committed 69dc29c.
- 2026-10-03 13:43: Merged origin/claude/clever-cerf-fe9sjf with --no-ff; exactly 9 review files, no conflict.
- 2026-10-03 13:45: Baseline run-checks passed 141/4/22, no skips. Preserved native report in runtime/longrun; restored exactly 4 rewritten tracked evidence paths. Completed full program and required first-step source reading. Initialization records ready for longrun/start.
