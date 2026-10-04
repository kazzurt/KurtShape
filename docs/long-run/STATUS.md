# Long run status

Program: C:\Users\Kurtz\Documents\KURT\CADkz\Claude\prompts\2026-10-03_codex_long-run-program.md
Program SHA-256 when last read: 5253C586CF649C8C16531F9F42A7278258CB0F2968B4DA9FAB02C925F02E1D1C, 2026-10-04 14:44 America/Los_Angeles
Revision 2 applied: 2026-10-04 14:44 America/Los_Angeles
Pilot: Q03 only; started 2026-10-04 14:41:47; deadline 2026-10-04 18:41:47 America/Los_Angeles
Updated: 2026-10-04 15:43 America/Los_Angeles
State: IN PROGRESS Q03 since 2026-10-04 14:44 America/Los_Angeles
Last green commit: c311f60 (tag longrun/Q25)
Green copy: still at longrun/Q24a (660acc5); updater refused because process inventory access was denied
Free disk: 153.33 GiB

## Queue

| Q | Increment | State | Commit | Tests native/bridge/shortcut | Note |
|---|---|---|---|---|---|
| Q00a | Foundation: fixes, isolation, one runner | DONE | 259a61b | 147/7/22 | 405 workflows; exactly 3 external skips without examples |
| Q01 | Green copy | DONE | 7a20a63 | 147/7/22 | Green interface41;31 script probes;405 workflow checks |
| Q00b | Foundation: CI, GUI runner, benchmarks, lint | DONE | d2e1b35 | 150/7/22 +405 | Full18:17 pass+exact carrier;77 images;67 five-repeat metrics; green update refused safely |
| Q02a | Keyboard registry, keymap, chords and palette | PARKED | d8cdb1b WIP | 147/7/59 +405 | Three GUI failures; hidden combo popup blocker, no Q02a tag |
| Q02b | Native shortcut audit and behavior bindings | BLOCKED | | | Needs parked Q02a; completes Q02 |
| Q03 | Fast build status | VERIFIED | | 187/7/22 +415 | Full/CI/GUI/paired bench/profile passed; commit and tag next |
| Q04 | Operation registry | READY | | | Q03 verified; deferred for this pilot |
| Q05 | Sketch operations | BLOCKED | | | Needs Q04 |
| Q06 | Agent read access | BLOCKED | | | Needs Q03/Q04 |
| Q07 | Preview engine | READY | | | Q03 verified; deferred for this pilot |
| Q08 | Feature framework, first six features | BLOCKED | | | Needs Q02/Q04/Q07 |
| Q09 | Idle recovery | PARKED | 8e4d230 resumed WIP | Native183/7/22+405 | Three resumed failures; copied-profile3/86 exact unrelated XML assertion; no Q09 tag/GUI/bench |
| Q10 | Remaining schema features | BLOCKED | | | Needs Q08 |
| Q11 | Incremental intent and summaries | READY | | | Q03 verified; deferred for this pilot |
| Q12 | Feature list | BLOCKED | | | Needs Q08/Q11 |
| Q13 | Variables | BLOCKED | | | Needs Q08 |
| Q14 | Event-driven shell | BLOCKED | | | Needs Q09/Q11 |
| Q15 | Inspection and performance panel | BLOCKED | | | Needs Q06 |
| Q16 | Import/export worker | BLOCKED | | | Needs Q03/Q09 |
| Q17 | Exchange formats | BLOCKED | | | Needs Q16 |
| Q18 | Assemblies: live links | BLOCKED | | | Needs Q04/Q07 |
| Q19 | Assemblies: connectors/mates/drag | BLOCKED | | | Needs Q18 |
| Q20 | Assemblies: structure/reports | BLOCKED | | | Needs Q19 |
| Q21 | Configurations | BLOCKED | | | Needs Q12/Q13 |
| Q22 | Sketcher behaviors | BLOCKED | | | Needs Q05/Q13 |
| Q23 | Feature repair and control | BLOCKED | | | Needs Q12 |
| Q24a | Hardening: bounded validation fixtures and current architecture | DONE | 660acc5 | 147/7/22 +405 | Assembly58/native4; full17:16 pass,1 exact baseline;76 images inspected; green updated |
| Q24b | Hardening: native fixture, file identity and datum observations | DONE | 77af50c | 159/7/22 +405 | Native/CI/nine proofs/67×5 benchmark; Q03/Q09 blockers proved; green update refused safely |
| Q24c | Hardening: hidden controls, display and final stale-doc sweep | PARKED | c23b1cf WIP | Controls10/19+2cleanup | Three failed mechanics gates; Settings hidden with2045px toolbar hint; no display/full/CI/bench |
| Q25 | Native preview cache and clone lifecycle | DONE | c311f60 | 164/7/22 +405 | Native/CI/full18 GUI/77 images/67×5; final evidence audits0; one failed wrapper gate retained; green update refused safely |
| Q26 | Avoid redundant recompute in proven plain previews | PARKED | a153585 WIP | | Revision 2 sets aside current work; revisit only after Q07 if still relevant |
| Q27 | Remaining status and phase-one speed targets | BLOCKED | | | Needs Q11; changed inspect20, edit50 and studio ownership costs remain; preview/checkpoint belong to Q07/Q09 |
| N01 | Safe green update from the launcher | READY | | | Revision 2 next step after Q03; deferred for this pilot |

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
| 10 | Q00b | Ruff0.16.10 is absent on PATH; make it available outside FreeCAD when convenient. | Added configuration and named fixes by inspection; no installation during run | Local lint only |

## Try this (newest first)

### Q03 fast status (verified; tag next)

1. Open a project saved by an older build: true-hasher files rebuild once on first open; other engine/build mismatches ask for one Rebuild while retaining the solid. The Q03 recipe and stored-open tests cover both paths.
2. Change an extrusion depth, then use Check geometry twice; status becomes checked and the second check reuses its verdict. The Q03 recipe preserves revision and history.
3. Use Measure on a current solid; explicit volume/area/bounds and full mass centre are available while ordinary status avoids integration. Geometry-level tests and the status recipe cover this.
4. Rebuild a mismatched project, then Undo; its prior rebuild reason returns with retained geometry. The Q03 recipe verifies one undo step and unchanged saved input.
5. Save and reopen, then export STEP; native tests and interface/assembly-step recipes retain source geometry, file safety and explicit export checking.


### Q25 preview lifecycle (c311f60)

1. Run run-checks.ps1 -Full -KeepNativeTemp; the five new native methods retain actual cache, clone, source and fixture cleanup receipts alongside all 164 native regressions.
2. Preview depths 5 mm and 0.5 cm in one task; the native cache test verified one geometry evaluation for equivalent quantities, then genuine promotion, eviction and reevaluation across nine depths.
3. Change a native Pad length and translate its Body; the stale-task test rejected the old task before any clone opened, and a fresh task followed the changed geometry and world placement.
4. Close the source while its preview task remains open and create a document with the same native name; the ABA test rejected the old task before clone work. Then close that task twice; the closed task rejects, while held detached results remain usable.
5. Save and reopen an Assembly after relocation, or recover a draft and Cancel it; the full GUI sweep and separate native proofs retained four embedded occurrences and the original saved recovery input respectively.


### Q24b native verification (77af50c)

1. Run run-checks.ps1 -Full -KeepNativeTemp and inspect the retained native fixture/test/PID receipts; all159 native methods passed with actual ownership, source hashes and ordinary fixture cleanup verified.
2. In a disposable native document, save a2mm cube, assign a custom Label, edit to3mm and saveCopy; the file test verified custom saved XML, filename-stem raw reopen, undo8/redo27mm3 and unchanged original8mm3 bytes.
3. Snapshot the studio fixture with30 base features/four parts/11 consumers/two scoped operations and inspect twice; its test verified96 owned datums/12Points/63 modeled Shape objects with exact content, history, Tip and revision unchanged.
4. Translate and rotate a Body, then undo; the frame test detected the exact changed placement and directly verified its restoration, retaining native Touched semantics.
5. Move an offset hole while retaining equal box bounds and volume, then undo; the content test detected the changed complete BRep and restored the original model hash/content.


### Q00b CI and benchmark foundation (d2e1b35)

1. Copy an Extrude or Remove into its Body, change the original and copy dimensions independently, then undo; the unchanged Copy25 recipe and new Pad/Pocket native tests verified actual editable dependencies and one-step copies.
2. Save, relocate and reopen an Assembly without its original source; Assembly58 and fresh native4 verified four embedded occurrences, three joints and complete geometry fingerprints.
3. Recover an unfinished sketch checkpoint, then explicitly Cancel; the fresh native proof verified draft1→0, unsaved1800mm3 and original1200mm3 with original bytes unchanged.
4. Run run-checks.ps1 -Full, then tools/ci/run-local.ps1 -SkipNativeTests; isolated gates verified150/7/22+405, pinned layout, all five benchmark sections and unchanged source/tree.

### Q24a bounded Assembly validation (660acc5)

1. Create an Assembly and insert a saved multi-body source; the hidden recipe selected a body and retained four occurrences with three solved joints.
2. Move a revolute joint45 degrees and a slider23mm, then undo and redo; the recipe verified actual native placement, history and revision consequences.
3. Save, relocate and reopen the Assembly without its original source path; both the GUI and fresh native process verified embedded geometry and joints.
4. Export STEP and read it back; the recipe verified exactly four solids and unchanged original source FCStd bytes.


## Budgets on Kurt's machine

| Metric ms | Fixture | Before Q00b | Prior best | Q03 latest | Target | Open? |
|---|---|---|---|---|---|---|
| Tip overhead | Plate60 GUI false | 3914.570 | 3128.398 | 62.623 | 150 now /50 phase1 | Phase1 |
| Changed inspect | Plate60 GUI false | 3075.623 | 3037.953 | 41.166 | 20; Q27/Q11 | Yes |
| Warm inspect | Plate60 GUI false | 23.343 | 19.751 | 19.684 | 20 | No |
| First preview | Plate60 GUI false | 10956.598 | 10180.061 | 8116.546 | 50; Q07 | Yes |
| Preview update | Plate60 GUI false | 9115.445 | 8783.091 | 6645.136 | Q07 follow-up | Yes |
| Checkpoint | Plate60 GUI false | 1586.709 | 1562.307 | 1605.292 | 16; Q09 | Yes |
| Native / managed open | Plate60 GUI false | 1750.139 /16187.745 | 1750.139 /12468.022 | 1798.671 /1838.901 | Added40.230 <=300; zero recompute | No |
| Full rebuild | Studio API true | 1222.620 | 1119.408 historical | 2978.420 | 4467.629 (1.5x Q03 true median) | No |
| Rebuild selector /auto-scope | Studio API true | 397.702 /22.161 | 367.172 /20.315 | 1111.530 /50.803 | Remaining cost; no prior absolute target | Yes |
| Kernel recompute | Studio API true | 170.005 | 150.048 | 464.469 | Comparison only | No |
| Changed /warm inspect | Studio API true | 2108.505 /1731.540 | 1834.373 /1655.516 | 5925.599 /1804.449 | Q11; no prior studio absolute target | Yes |
| Tip overhead | Studio API true | 4250.458 | 3739.866 | 10274.123 | Q11; no prior studio absolute target | Yes |

Q03 recorded both policies:134 medians/670 samples. Initial timings varied broadly; independent plate false confirmation39/195 had zero metrics above historical best times1.2+5 and confirmed no regression. Plate latest is that confirmation; paired API plate and both initial policies remain in evidence. Historical Contract2 true did checking/full mass work, unlike Contract3 true/false; these are descriptive historical comparisons. Studio's comparable true-policy baseline and five actual samples are in budgets.json; report.py --enforce passed. Use --enforce for future default studio benchmarks. Profile own costs: Body enumeration6.674s, ownership matching3.161s, native recompute1.220s. Before diagnostic4.01654s/2.00197s/0.95629s used another workload, so no profile speed ratio is claimed.
## Red at baseline

- None in run-checks: 141 native, 4 bridge, 22 shortcut tests passed; 0 skips. Native suite 170.872 s. GUI baseline completed: 14 pass, 2 red, plus Messages pass.

- interface: Confirm creates valid native solid failed after 11 checks; task remained open after depth change (screenshot inspected).
- carrier-spike: historical pre-U2 history expectation failed after 17 checks.

## Parked work

| Q | Branch | Cause | What to try next |
|---|---|---|---|
| Q02a | longrun/parked-Q02a-keyboard-registry | Hidden combo popup never becomes active | Drive combo API and signal; keep resulting context assertions |
| Q03 | longrun/parked-Q03-fast-status-resumed | New bounded-cache test expects eviction after lowering limits | Evict with while in check and memo; resume under Revision 2 |
| Q09 | longrun/parked-Q09-idle-recovery-resumed | XML declaration encoding case changes | Use WriteTo and test PowerShell 5.1 and 7 |
| Q24c | longrun/parked-Q24c-hidden-controls-display | Display evaluation and stale-doc sweep remain | Wait until all other rows are done, parked or blocked |
| Q26 | longrun/parked-Q26-preview-recompute | Set aside immediately by Revision 2 | Reconsider after Q07 if clone preview remains |
## Notes handled

| Note or report (first line) | Date | What I did | Commit |
|---|---|---|---|
| Existing user reports | 2026-10-03 | Five reports from October 2 existed before this run; recorded below as baseline | Start |

Existing reports: kurtshape-problem-20261002-075903-f80b59d0.json, kurtshape-problem-20261002-080303-4731a62a.json, kurtshape-problem-20261002-080518-cb77b2bc.json, kurtshape-problem-20261002-085826-d3479fc2.json, kurtshape-problem-20261002-181622-afd5a3ef.json. Main and green reports were checked at pilot start; no new Kurt report or owned tracked change.

Own recipe report: kurtshape-problem-20261003-204924-ac7dc9ee.json came from the baseline review-copy check and is not a new user instruction.

## Log

- 2026-10-04 14:48: Pilot started; park Q26 as Revision 2 requires, then resume Q03 only until tagged or the four-hour limit.
- 2026-10-04 14:44: Q26 parked on its required branch; Revision 2 applied and Q03 selected for this pilot.
- 2026-10-04 14:49: Cache limits now drain excess entries; Q25 preview ownership uses geometry provider; full native checks are running.
- 2026-10-04 14:52: Full checks passed 187 native, seven bridge, 22 shortcut tests and 415 workflow checks without skips; local CI starts.
- 2026-10-04 14:55: Local CI and targeted status GUI passed; changed screens inspected; full GUI sweep runs before paired benchmarks.
- 2026-10-04 14:58: Saved visibility and camera confirm the blank capture preceded GL paint; targeted capture will use the product Open path.
- 2026-10-04 15:01: GUI sweep retains the exact 17-check carrier history baseline; other completed recipes pass and NOTES remains empty.
- 2026-10-04 15:01: Full GUI finished with seventeen passes and one exact baseline exception; corrected status capture passes and benchmarks start.
- 2026-10-04 15:03: GUI warnings match prior classes; recovery proof passes; rebuilt-required capture now visibly retains the solid with no recompute.
- 2026-10-04 15:13: First plate GUI-policy benchmark passed all39 metrics but warm inspect/checkpoint/first preview exceed target and historical best threshold; paired API run and required confirmation remain before commit.
- 2026-10-04 15:33: Independent plate confirmation reproduces no historical-threshold regression; changed inspection41.166ms remains open. Studio profile identifies body enumeration, ownership matching and native recompute; API-true rebuild budget4467.629ms enforced. Final standing scripts start.
- 2026-10-04 15:43: Final full checks187/7/22+415 and local CI passed; unchanged source/tree; small evidence packaged. Review found0 production issues and1 export-documentation correction. Commit/tag Q03 next; NOTES has no new instruction.
