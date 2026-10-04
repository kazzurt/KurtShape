# Long run status

Program: C:\Users\Kurtz\Documents\KURT\CADkz\Claude\prompts\2026-10-03_codex_long-run-program.md
Program SHA-256 when last read: BFD1820915CDEDE335C2FF421163F1A404E666211402E81DB8E936631D3C2995, 2026-10-04 10:08 America/Los_Angeles
Updated: 2026-10-04 10:16 America/Los_Angeles
State: IN PROGRESS Q25 since 2026-10-04 08:23 America/Los_Angeles
Last green commit: 77af50c (tag longrun/Q24b)
Green copy: still at longrun/Q24a (660acc5); updater refused because process inventory access was denied
Free disk: 48.54 GiB

## Queue

| Q | Increment | State | Commit | Tests native/bridge/shortcut | Note |
|---|---|---|---|---|---|
| Q00a | Foundation: fixes, isolation, one runner | DONE | 259a61b | 147/7/22 | 405 workflows; exactly 3 external skips without examples |
| Q01 | Green copy | DONE | 7a20a63 | 147/7/22 | Green interface41;31 script probes;405 workflow checks |
| Q00b | Foundation: CI, GUI runner, benchmarks, lint | DONE | d2e1b35 | 150/7/22 +405 | Full18:17 pass+exact carrier;77 images;67 five-repeat metrics; green update refused safely |
| Q02a | Keyboard registry, keymap, chords and palette | PARKED | d8cdb1b WIP | 147/7/59 +405 | Three GUI failures; hidden combo popup blocker, no Q02a tag |
| Q02b | Native shortcut audit and behavior bindings | BLOCKED | | | Needs parked Q02a; completes Q02 |
| Q03 | Fast build status | PARKED | 5076b4b resumed WIP | Native181/182;7/22+415 | Third resumed Full failed new cache eviction count3vs4; no Q03 tag |
| Q04 | Operation registry | BLOCKED | | | Needs parked Q03 |
| Q05 | Sketch operations | BLOCKED | | | Needs Q04 |
| Q06 | Agent read access | BLOCKED | | | Needs Q03/Q04 |
| Q07 | Preview engine | BLOCKED | | | Needs Q03 |
| Q08 | Feature framework, first six features | BLOCKED | | | Needs Q02/Q04/Q07 |
| Q09 | Idle recovery | PARKED | 8e4d230 resumed WIP | Native183/7/22+405 | Three resumed failures; copied-profile3/86 exact unrelated XML assertion; no Q09 tag/GUI/bench |
| Q10 | Remaining schema features | BLOCKED | | | Needs Q08 |
| Q11 | Incremental intent and summaries | BLOCKED | | | Needs Q03 |
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
| Q25 | Native preview cache and clone lifecycle | IN PROGRESS | | 164/7/22 +405 | Native/CI/full18 GUI/77 images/67×5 benchmarks accepted; final evidence/commit next; one failed wrapper gate retained |

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

### Q25 preview lifecycle (commit pending)

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

### Q01 stable green copy (7a20a63)

1. Save and close the old window, then open the sibling KurtShape-green.cmd; PrintOnly verified its green source and shared main profile. Normal launch remains Kurt's action.
2. Create a rectangle with Shift+S, extrude with Shift+E, change its width, undo and redo; the green interface recipe exercised these actual keys and dimensions.
3. Sketch on a face and make a blind removal; the recipe checked exact removed volume and rebuild visibility.
4. Save and reopen the project, then enter 1/8 in for its depth; the recipe checked geometry and unchanged file/revision/history during preview.


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
| Tip edit overhead ms | Plate60 | 3914.570 | 3128.398 | 3128.398 | 150 phase0 /50 phase1; Q03/Q11 | Yes |
| Changed inspect ms | Plate60 | 3075.623 | 3037.953 | 3037.953 | 20; Q03 | Yes |
| Warm inspect ms | Plate60 | 23.343 | 19.751 | 19.751 | Q03 measured follow-up | Yes |
| First preview ms | Plate60 | 10956.598 | 10180.061 | 10180.061 | 50; Q07 | Yes |
| Preview update ms | Plate60 | 9115.445 | 8783.091 | 8783.091 | Q07 measured follow-up | Yes |
| Checkpoint ms | Plate60 | 1586.709 | 1562.307 | 1562.307 | 16; Q09 | Yes |
| Native / managed open ms | Plate60 | 1750.139 /16187.745 | 1750.139 /12468.022 | 1840.183 /12808.609 | Q03 open without rebuild | Yes |
| Full rebuild ms | Studio | 1222.620 | 1119.408 | 1143.193 | 1.5× post-Q03 median, pending | Yes |
| Rebuild selector /auto-scope ms | Studio | 397.702 /22.161 | 367.172 /20.315 | 372.855 /20.870 | Exact bounded Q03 evaluation | Yes |
| Rebuild kernel recompute ms | Studio | 170.005 | 150.048 | 152.878 | Comparison baseline | No |
| Changed /warm inspect ms | Studio | 2108.505 /1731.540 | 1834.373 /1655.516 | 1864.929 /1709.372 | Q03 | Yes |
| Tip edit overhead ms | Studio | 4250.458 | 3739.866 | 4017.464 | Q03/Q11 | Yes |

Latest Q25 measured all 67 medians from 335 samples. Every metric stayed below 1.2× its prior recorded best plus 5 ms; six phase-specific absolute target misses remain open. Studio absolute budgets await Q03. No application speed improvement is inferred from this validation-only increment.

## Red at baseline

- None in run-checks: 141 native, 4 bridge, 22 shortcut tests passed; 0 skips. Native suite 170.872 s. GUI baseline completed: 14 pass, 2 red, plus Messages pass.

- interface: Confirm creates valid native solid failed after 11 checks; task remained open after depth change (screenshot inspected).
- carrier-spike: historical pre-U2 history expectation failed after 17 checks.

## Parked work

| Q | Branch | Cause | What would unblock it |
|---|---|---|---|
| Initial decision-dependent items | None | Questions above | Kurt's answer |
| Q00b historical WIP | longrun/parked-Q00b-ci-benchmarks | Original three failed gates retained; unparked after Q24a blocker | Completed at longrun/Q00b (d2e1b35); original branch retained |
| Q02a | longrun/parked-Q02a-keyboard-registry | Three keyboard GUI failures; owned processes exited normally. Latest reached16 checks, expected combo popup absent/unverified | Land proven bounded hidden Qt control interaction with diagnostic popup/view/click/selection state and unchanged exact assertions |
| Q03 historical WIP | longrun/parked-Q03-status-profile | Three diagnostic profile gates failed; final11 App::Point origin hashes volatile, all other recorded model/history/datum fields unchanged; Point content was unproved then; no production edit | Q24b landed the proof at77af50c; resumed with new profiles while retaining original branch/attempts |
| Q03 resumed WIP | longrun/parked-Q03-fast-status-resumed (5076b4b); plan-base longrun/parked-Q03-resume-plan-base (a1d4c10) | Three resumed production Full failures; final181/182native plusall415workflow checks pass, sole new memo eviction count3vs4 | Separately land actual native cache initial-inventory/LRU/limit-transition fixture proof; retain eviction/recomputation/geometry assertions before unpark |
| Q09 | longrun/parked-Q09-idle-recovery | Three production Full failures; latest173/174 fails exact filename string separators after all recovery consequences pass; no localCI/GUI/bench run | Land compact fixture/native SaveAs Label/FileName/path-identity proof, then retain exact captured native provenance assertions |
| Q09 resumed WIP | longrun/parked-Q09-idle-recovery-resumed (8e4d230); plan-base longrun/parked-Q09-resume-plan-base (7398c4a) | Three resumed consolidated failures; 218/218 total cases pass (183 native,7 bridge,22 shortcut,6 workflows), final copied-profile3/86 exact unrelated XML identity fails | Separately land exact copied-profile serialization/backup/PrintOnly safety proof without weakened assertions; cause unproved |
| Q24c | longrun/parked-Q24c-hidden-controls-display (c23b1cf; original WIP b36bbf8 retained) | Three Controls mechanics gates failed; Windows hidden popup unregistered, offscreen popup passes but Settings actual widget remains hidden at1600px with2045px toolbar hint | Separately land a bounded owned-control layout/overflow proof retaining exact visibility/selection/native assertions; offscreen GL/fonts do not supply Windows visual acceptance |

## Notes handled

| Note or report (first line) | Date | What I did | Commit |
|---|---|---|---|
| Existing user reports | 2026-10-03 | Five reports from October 2 existed before this run; recorded below as baseline | Start |

Existing reports: kurtshape-problem-20261002-075903-f80b59d0.json, kurtshape-problem-20261002-080303-4731a62a.json, kurtshape-problem-20261002-080518-cb77b2bc.json, kurtshape-problem-20261002-085826-d3479fc2.json, kurtshape-problem-20261002-181622-afd5a3ef.json. No green tree exists. No Kurt-owned tracked changes at initialization.

Own recipe report: kurtshape-problem-20261003-204924-ac7dc9ee.json came from the baseline review-copy check and is not a new user instruction.

## Log

Completed resumed Q03/Q09 events are retained verbatim at docs/long-run/RUN_LOG_2026-10-04_Q03-Q09.md on retained branch longrun/parked-Q24c-hidden-controls-display. Each resumed increment reached three failed gates; neither permits another attempt before a separately landed blocker. Earlier events remain at docs/long-run/RUN_LOG_2026-10-03_to_2026-10-04.md on retained branch longrun/parked-Q03-fast-status-resumed.

- 2026-10-04 06:49: Q24c starts afterfull577-line unchangedprogram/STATUS/NOTES/briefIncrement18+AppendixA reads andhealthaudit. Mainexactlasttag77af50c, treeONLYSTATUSmodified, original/greenreportsunchanged, NOTESempty,48.91GiB free. Allremainingearlierrows done/parked/blocked; Q24cfirsteligible. Scopeplannedbounded hiddenQtcontrol interactionproof to unblockQ02a, actual60hole orbit display-settings evaluation withonlymeasuredbenefits retained, currentlivingdoc sweep/architecture. Q09no4threpair/probe andQ03cache work remainparkeduntilseparateblockersland. Hostednightlyenforcementawaitspush/5stableWindows samples; noformattingcommit. Native/UI/Pythonprocesslaunches remainroot-ownedserial/private6roots; planbeforeedits.

- 2026-10-04 06:52: Q24c plan written before edits, control/display/doc read-only tasks delegated. Relocated priorQ03/Q09eventlog verbatim intoexclusive dated continuity record; exactcopiedbody comparisonpassed, currentcounter/branches/questions preserved. NoQ24cproduction/native/probe/evidence started.

- 2026-10-04 07:10: Resume reread the full unchanged program, STATUS/NOTES, brief invariants/facts and Q24c spec/plan; main remains77af50c and report inventories unchanged. Independent audits confirm129 shortcut entries57/38/28/6 and eight stale table rows. Corrected current registry/reproduction prose and added Superseded notes without erasing historical results; accurate clone/open/timed-recovery/embedded-Assembly policies retained. Reviewed control and display designs, authorized ignored capability drafts and serial guarded launcher only. Pending-Q02 which-key uses ToolTip, not Popup; failed popup cause still unproved. Hidden frame-completion/applied native display-policy capability must be observed before performance measurement. No native process, acceptance gate or public evidence launched yet.

- 2026-10-04 07:26: Final root/independent full capability and launcher reviews close prelaunch findings. Frozen Controls16274CCB(453lines/19newchecks/3images), DisplayB3C78FA9(538/12/3), launcherFD3D9C6C(247/AST0). NativeCI81FF16A4 is an unexecuted draft. All source/helper edits frozen for first serial root-owned Controls mechanics launch; six fresh private roots, exact tree/source/PID/lifetime/image/environment proofs and300s bound. Display remains unlaunched; no full production gate, benchmark, public evidence or acceptance yet. Existing assertions unchanged.

- 2026-10-04 07:31: Q24c FAILED gate1, first Controls mechanics. Owned23332 exited0 and is absent; source/tree/environment restoration true, unchanged diff0ab73a0f...888b67. Receipt runtime/longrun/q24c-hidden-controls-receipt-164a4aa4464d44d8b6703d2ad7590c0d.json SHA22FECD654624D6DAD3F36622C06A0B6EFC8305FA35CEE37299BA71B4B79504D0; raw private probe.json SHA627FDE9B27E2B0D918113DC319CFD3284CF7529BC88E15422B5E4373BD60AA7D. Six checks passed (five control setup/observations plus source cleanup); strict active-popup/own-view guard failed. Actual arrow81,13 press/release delivered; own QComboBoxPrivateContainer typePopup9 and view visible/focused, but QApplication.activePopupWidget null across all default/tooltip/popup cases. Native project unchanged through prior phases; documents closed and original preference presence restored. Own combo popup remained visible during cleanup, so strict owned-window cleanup also failed. FailurePNG directly inspected: correct600mm3 plate/light shell. NOTES empty. First macro/launcher/report remain immutable; no assertion weakening/retry yet. Read-only diagnosis considers hidden attribute/platform registration and explicit owned-popup teardown; displayed popup visibility alone is not acceptance. Display/nativeFull/CI/bench/publication remain unrun.

- 2026-10-04 07:42: Resume read full577-line unchangedprogram/STATUS/NOTES/brief5–6/Increment18/AppendixA/Q24cplan; main77af50c, known Q24c docs only, reports unchanged,48.88GiB free. Before retry, counter remains one failed Q24c gate. Authorized NEW ignored Controls attempt2 and launcher2 for bundled Qt offscreen, actual platform assertion before ordinary windows, original19/3 and exact activePopup/native consequences retained. Explicit owned hidePopup only fixes cleanup. Original first helpers/receipt/raw stay immutable and source-bound. Independent installed-plugin/renderer review confirms experiment feasible but native GL/actualpopup remains unproved; no startup/display/performance equivalence claim. No native/Python launched; authoring/review first. Q03/Q09 remain parked with no new attempt.

- 2026-10-04 07:50: Before Controls retry, failure counter remains1. New macro B0966CB519F129911C91E48A59699CFAD934311332D8D7C51A10FEA9E3185FA7(471lines/unchanged19checks/3successimages) and launcher0C4345DDC4F0BCFF73C211818490059BA3AD68D941C53E08E7F4F7178E58A876(263/AST0) complete root full/diff and independent full reviews with0remaining findings. Five immutable first-attempt inputs pinned; exact actualoffscreen backend guard onlyControls, Display expecteddefaultWindows observation remainsunavailable. All source/helper edits frozen for bounded300s root-owned serial Controls2 native launch, sixprivate roots/fullUUID/PID ledger/source/tree/lifetime/environment guards intact. No existing assertion changed; no public acceptance or speed claim.

- 2026-10-04 07:54: Q24c FAILED gate2, Controls offscreen attempt2. Native37948 exited0/noTimeout and absent; source116/tree/environment restoration exact, unchanged diff0ab73a0f...888b67, original five inputs preserved. Receipt runtime/longrun/q24c-hidden-controls-receipt-attempt2-42982a6a21a04329afbec836f4fbff1c.json SHA21D031CB92F6832F1C253156654904C83CA973AF518CCF598A61F0E3F62CD890; raw private probe.json SHAC7922179F6F48711DA8772BEEA3F5C49CB573DE378862E4926084F2A1B6D27C8. Actual platformoffscreen,12checks (10control+2cleanup) pass, including strict activePopup/ownedview, workspaceEscape and realactivated Assembly/PartStudio withexactnativeGUI/modelstate. Fails actualSettings toolbar button visible/enabled assertion. Rootsourceui.start2697 reapplies screen-based size;800virtualscreen→752×720 finalwindow, Settingsfallsintoolbaroverflow. Bothworkspacepopup/failurePNGs inspected; popup exists butoffscreenfonts displaytofu andGLviewportblank. Newoffscreen backendwarnings include unsupportedraise/keyboardgrab/sizehints, fontpointsize andNoValidGLcontext; noWindowsvisual/performanceacceptance inferred. Allowneddocs/windowsclosed, exactpreferencepresence restored, cleanup_errors0. NOTESempty. Sources/helpers/results remainimmutable; no secondControlsretryyet. Read-onlyreviewboundedpostui.startresize BEFOREfixture/fit/baseline withall19/3/assertionsunchanged; onlyonefurtherfailedgate permitted beforemandatorypark. Display/nativeFull/CI/bench/publication remainunrun.

- 2026-10-04 08:01: Before final Controls retry, Q24c failurecounter2. NEW Controls87DCB025BF4943E4545199D869C859C8158F6B72BDB83EA691DF9508D1AA0034(485lines/19checks/3images) andlauncherF77EE66721E216A72114AC5D6F34714213A707FF68F2E0F288C1053D9BEF63F4(267/AST0) complete root delta/whole-path andtwoindependentfull reviews0remaining; exactinversebytes reproduce immutable predecessors andnineoriginal/priorpins verified. Solefixturechange post-ui.start1600×1000/250ms BEFOREtypedoperations/viewfit/baseline; actualscreen/main/bar/action+widget geometry/visibility/enabled recorded. Layoutoverflow is the evidenced inference fromclipping/source; secondfailedconjunct didnotseparatelyrecordbutton flags. Offscreenfonts/GLlimits remainexplicit; noWindowsvisual/performanceacceptance. All source/helper edits frozen for bounded300s serialrootowned thirdControls launch; NOTESempty. OnanotherfailedQ24cgate parkimmediately/nofourthattempt. NativeFull/CI/Display/fullcadence/bench/publication remainunrun.

- 2026-10-04 08:03: Q24c FAILED gate3 and MUSTPARK now; no fourthfix/probe/retry. Native55960 exited0/notimeout and absent, all120sources/tree/env exact, owned docs/windowsclosed and preferencepresence restored, cleanup_errors0. Receipt runtime/longrun/q24c-hidden-controls-receipt-attempt3-303a52408afd42c9b6cfff69061c58b3.json SHA8907BD6764D386462EAF0A469877052375F7D2BB42D65EEBFDE25A189F8C94FC; rawSHA7A0DD6ADE763029C20C039A63B7647C205A43445BADC8A0E2DC1B9EDB7B58D72. Twelvechecks (10functional+2cleanup) pass; strictworkspacepopup/Escape/realactivation/native exactness retained. Actualwindow1600×1000, Documentbarhint2045×43; SettingsQActionvisible/enabledtrue, actualwidgetvisiblefalse/enabledtrue separately recorded. SameSettingsvisibilityassertion fails. BothownedPNGs inspected: missingglyphboxes/blanknativeGL; noWindowsvisual/displayclaim. Diff91037a1045dd0ae7f2cb131fee7e5b7eefaf765a296f41c8a50afdc28d8b0de1 exact; NOTESempty. Allhelpers/results immutable; Display/nativeFull/localCI/fullGUI/pairedbench/publication/tag/greenupdate unrun. Preserveonlyown docWIP, retainSTATUS/NOTES bytes duringbranchmoves, mainreturns77af50c. Nexteligible item willbechosen afterfullprogram/healthread; Q03/Q09/Q24c requireseparatelandedblockers.

- 2026-10-04 08:18: Q24c parking completed on retained branch longrun/parked-Q24c-hidden-controls-display at c23b1cf3c2029aee0a06db8960b4a80887f825af; original b36bbf8 WIP retained as parent. Factual documentation count corrected by ordinary focused commit, no amend/tag. Branch transitions preserved exact STATUS/NOTES bytes; main remains tagged77af50c and only STATUS is modified. All owned processes closed. Resume read whole577-line unchanged program/STATUS/NOTES/brief5–6, checked branch/log/tags/parked refs/disk/report inventories; no new Kurt report or note. No further Q03/Q09/Q24c attempt is authorized until its separate blocker lands. Read-only route assessment identifies shipped preview LRU lifecycle validation as independently useful for the open preview budget; it does not prove absent Q03 memo capacity-transition behavior or unpark Q03.

- 2026-10-04 08:23: Q25 starts under section9 for the open preview budget; plan written before implementation on tagged main77af50c. Scope is five new native tests/provenance for the shipped fixed LRU8 and clone lifecycle, preserving all existing assertions. Independent route review rejected claiming this as Q03's mutable-memo blocker; Q03/Q09/Q24c remain parked and their artifacts immutable. Full native/localCI/full18 GUI cadence and unchanged67-metric paired five-repeat benchmark are required before landing. Root alone launches private native/Python processes. No acceptance gate or production edit started.

- 2026-10-04 08:40: Q25 five native methods and three ignored gate helpers are in prelaunch review. Existing five preview method assertions remain intact. All helpers use the same complete source universe; CPU requires actual164 native/199 total cases, five postcleanup native receipts and localCI before GUI. Full18 retains77 baseline images and independent recovery/Assembly readback; separate aggregate-bound visual review is mandatory before benchmark. Paired benchmark draft computes per-metric min(Q00b,Q24b) with winning raw provenance, independently read back all67 prior medians (plate7/32 and studio2/26 winners). No Q25 native/Python launch or gate attempt yet; parked Q03/Q09/Q24c remain untouched.

- 2026-10-04 08:58: Resume reread full577-line unchanged program, STATUS/NOTES, brief5–6 and Q25plan; main77af50c, known test/plan/STATUS changes only, reports unchanged,48.84GiB free. Root fully read final666-line tests and allthree gate helpers; independent native/test/CPU/benchmark reviews close0 material findings. Benchmark prelaunch guards now require exact PID-ledger ancestry and a nonempty actual observation for every image; frozen C8689776, inverse two-line delta verified. Native164 expected; no Q25 launch yet. Independent final GUI review remains in progress before immutable-source freeze.

- 2026-10-04 09:00: Q25 first native/CI gate START, failed gate counter0. Final root whole-file and independent reviews0 remaining findings: test AB673023(666lines), CPU D04A546C(337/AST0), GUI1AE4FA00(457/AST0), benchmark C8689776(405/AST0). Allfour bytes frozen and review receipt retained before fresh exact tree capture. Actual static inventory17classes/164methods/199totalcases; original159 native/oldfive preview method bodies retained. Root-only Full KeepNativeTemp/private six roots/PID ledger, then localCI only after five postcleanup native proofs verified. Full18/77-image review and paired67×5 remain pending; no previous result reuse. NOTES empty.

- 2026-10-04 09:06: Q25 FAILED gate1, CPU attempt1 receipt type check after actual Full199/199(164native/7bridge/22shortcut/6workflows405), zero skips/failures/errors. Native raw A825F6B27504C79BDF04B2E288E6C4E7859091EBFA766E51051B34A6FEC98D65; failed receipt115145B448EC8D46F262F6667D9112A70ACD3C267D65D879358C08CA21054507. Allfive fresh lifecycle proofs passed with source/cleanup true; actual proof schema1 parses System.Int64 in PowerShell7, while new CPU wrapper mistakenly required Int32 only. Exact test_id/PID69572 otherwise match. No application/test assertion failed or changed. Source/tree76bc0720...5740f/environment exact; native owned child ledger retained, no localCI/GUI/bench launched. NOTES empty. Preserve allfirst helpers/reports/capture immutable. Before retry author NEW attempt2 orchestration copies accepting either integral CLR JSON type with value exactly1, fresh receipt/tree and common old+new helper bindings; nativeFull must rerun fresh. Failed counter1, two further failed gates maximum.

- 2026-10-04 09:14: Before Q25 CPU retry, failure counter1. NEW CPU9CF260E3/GUI986A0CDF/benchmark07D09703 complete root delta/source controls and two independent whole/delta reviews0; AST0 and exact inverse reproduce original helpers. Common117 keys match acrossall3; everyoriginal112 source entry, failedreceipt115145...54507 and tree01C92...4EA7 are immutable/pinned. Actualfive schema1 Int64 reports pass corrected metadata guard; wrongvalues, bool/string/float/decimal/null reject. TestAB673 bytes/original assertions unchanged. Fresh tree/serial root-owned Full KeepNativeTemp START now, then localCI only after full raw/everyfiveproof reverified; no reused native result. Firstnativeactual LRU sourcegeneration40 remained40 throughsaveCopy, exacteviction11 evaluations, geometry/source/cleanup alltrue. Allfirstowned PIDs closed; NOTESempty. Two further failed gates maximum before mandatorypark.

- 2026-10-04 09:18: Q25 retry Full completed199/199(164native/7bridge/22shortcut/6workflows405), no skips/failures/errors. Five NEW nativePID53100 proofs verified by CPU and independent actual-file review0; allocation/source/env/fixture/doc/receipt cleanup alltrue, originalsavedbytes exact, genuineLRU11/stale/retry/name-reuse consequences repeat. Fresh runner regression-run-20261004-091447-63952-2fc69b8c; localCI now executing in run-20261004-161648-c35b4c93a7d14bf1a6d506cab36d8dd8 after verifiedFull. Consolidated gate remains in progress until nativeCI/source/tree/env completion. Failed counter remains1; no GUI/pairedbench/publication started.

- 2026-10-04 09:21: Q25 CPU attempt2 ACCEPTED: receipt3125F3FB753584DC9260D99E4967851A476C824ACD01C98083CDE16839C3A33F, freshnativeA7D62981...17DE, localCI71A2FEA9...066B; Full199/199+405, fiveactualproofs, localCI3checks/20hole39metrics×3, all117sourcebytes/tree76bc...5740f/exactenvironmentrestoration true. All11owned native/CI PIDs closed; firstfailedattempt immutable, counter1. Full GUI cadence START now with reviewed986A0CDF wrapper, actualmain18 recipes/freshprivateUUIDs/77expectedimages, separateRecovery10/11 andAssembly4. Root willreadallreports/classifywarnings/inspectallimages beforebenchmark; rawcarrier baseline exception remainsexact17+finalerror only. No parkedControls/Display code invoked; no pairedbenchmark/publication/tag yet. NOTESempty.

- 2026-10-04 09:37: Resume read full unchanged577-line program/STATUS/NOTES/brief5–6/Q25plan and Git health; main77af50c, known test/plan/STATUS only, reports unchanged,48.80GiB. Full18 GUI completed accepted SHA274A49B3E0FB6914849F304A4DDF586B236D643FCC7847F8A1E3364FD7EC419C:17pass+exactcarrier17rawfalse, source117/tree/environment exact. Root8images viewed, delegated69images in progress; actual framing/clipping limits retained. New exact-line variants onlypart-studio scope warnings require original-class/source review; no rawwarning flags changed. No benchmark/publication started; failed counter1. Allparked artifacts immutable.

- 2026-10-04 09:51: Q25 visual complete: all77 actual original images viewed/rehashed,8 exclusive chunks/0 material findings; receipt q25-full-gui-visual-review-1a51c3a8237b49b2aba20e19b817dba2.json SHAF1E276E378E6021716756CBEA640532E3C8CE914C8505635F5DABCC5B3EB1689, rawGUI274A49B3 unchanged. Existing framing/crop/label limits retained.35 unmatched PartStudio scope-warning variants reviewed (16 complete equal-membership/order differences,19 truncated membership unproved), same class and unchanged source8/99assertions; no rawflag rewrite. Independent final tests/gates/publisher reviews0. All20owned GUI/proof PIDs absent. Combining receipt caught one copied hash typo before any output/launch; actual immutable chunks unchanged, no failed native gate. Paired60hole/studio five-repeat benchmark START next with frozen07D09703, root-ownedserial/private6roots; counter1/NOTESempty.

- 2026-10-04 10:16: Resume read whole unchanged program/STATUS/NOTES/brief5–6/Q25plan and Git health; main77af50c with expected Q25 files, report inventories unchanged,48.54GiB. Both benchmark processes59704/6172 exited0/absent: aggregate9C0292D5CF91228C55A371945DA10DA3D773E0A04BA67FF64B4CC5FB6A62DFC3, plate rawA09CB1A3/studio9BA9A47F. Root recomputed all67 medians/p95/worst from335samples and historical min/limits; no suspects/confirmation, six open targets. All117source/hashbindings/env exact. Final living docs written after benchmarks closed; production source unchanged. Publisher/plain-log prelaunch finding fixed before use; plan translated-only wording corrected; copied visual hash typo caught before writes. Final independent benchmark/docs reviews in progress; failure counter1, NOTESempty; no public output/commit yet.
