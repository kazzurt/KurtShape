# KurtShape architecture and responsiveness status

Prepared October 8, 2026 (America/Los_Angeles). Accepted implementation checkpoint: **S18, October 8, 2026**. Preparation draft for review; publication remains pending. Code paths below are relative to the repository root.

## Executive summary

KurtShape has accepted improvements to derived-state reuse, preview snapshot transport, selector preparation, sketch-tool ownership, geometry checks and eligible STEP export. FreeCAD 1.1.4 / OCCT 7.8.1 and editable FCStd remain authoritative. Live application documents and native graphical tools still belong to the Qt thread; private worker processes own separate documents. No second editable CAD model or production authority migration was introduced.

The latest production is **S09B plus S14 canonical request status, S16 STEP digest reuse accepted through S16C, and S17 preparation cancellation**. S18 changes only the STEP GUI regression recipe. Its fresh GUI gate passes 91 checks; the retained S17 native gate passes 426 cases with four expected opt-in performance skips. These are scoped correctness and lifecycle results, not a claim that all responsiveness targets have been met.

Two isolated experiments support specific performance improvements: S08 reduces repeated body-icon work during parts refresh, and S16 reduces warm preparation time for an eligible single-target STEP export. Synchronous preparation, acceptance/publication, Save and committed native recomputation can still block the interface. General input-to-paint targets remain unproved. The separate M1 source-conversion work remains incomplete; neither supplied Onshape design has been converted. See [project continuity](../M1_PROGRESS.md).

## Accepted improvements

| Area | Accepted behavior and boundary |
| --- | --- |
| Derived document state | Observer-driven intent, indexes and inspection summaries reuse validated derived data. Full reconciliation/oracle paths remain; complete inspection is not constant-time. |
| Preview archives — S01/S02 | Compatible immutable recovery archives can be leased by preview workers, avoiding redundant native capture in proved matching-key cases. The complete accepted-state key and file identity are checked; leases remain pinned until child exit. Fresh operation clones and owned capture fallback remain. This proves work elimination, not a general speed ratio. |
| Selectors and scope — S03/S03B | Literal membership and map-owner preparation are lazy. A bounded 64-entry scope-membership cache returns fresh lists and rejects foreign dependencies or unstable reads. Native traversal and recompute order are unchanged. |
| Sketch tools — S04 | One owner/generation governs transient tools. Reentrant tool changes suppress deferred work; foreign pointer events and stale hover callbacks cannot affect the current tool or replacement highlight. Existing keyboard/dialog behavior is retained. |
| Geometry checks — S07/S07B | Eligible uncached UI checks run on detached shapes in a private native process, with guarded verdict import and cleanup. Cached and conservative contexts retain synchronous behavior. Representative evidence proves GUI event delivery during actual child checking; capture and completion still run synchronously. |
| Parts refresh — S08 | The legacy non-Studio branch reads presentation and native icon once per nonempty body per refresh, then builds the same ordered solid rows and performs full reconciliation. No persistent cache is added. Empty results avoid icon reads; Studio behavior is unchanged. |
| STEP export — S09B | Eligible UI STEP/.stp work runs in a private child. The parent alone owns the destination and verifies child exit, source, artifact, provenance and destination identities before staged publication. Clean metadata, unstable/uncertain sources, assembly/Link exclusions and STL retain conservative synchronous fallback. Save remains synchronous. The two-file output replacement has rollback/recovery semantics, not atomic pair replacement. |
| Canonical request status — S14 | An exact `request_status` payload can read the locked JSON ledger without the CAD queue or native access. Original replay data and timing remain intact. Noncanonical payloads retain queued validation; Python GIL and lock scheduling still apply. |
| STEP preparation — S16/S16C, S17 | Eligible single-target preparation carries a one-use canonical BRep digest from admission into its initial fingerprint. Fresh shape/metadata/map reads and independent final/child guards remain. S17 stops later preparation work after observed ownership loss or callback failure, with dedicated cancellation and exact worker/lease cleanup. It cannot interrupt a native call that does not yield. |

[ARCHITECTURE.md](../../ARCHITECTURE.md) describes the current ownership and fallback boundaries. The local-only execution record and milestone reports preserve unsuccessful attempts and detailed acceptance decisions; they are not part of the public document set.

## Baseline foundation

The upgrade builds on the preserved October 5–6 working tree, which contains changes absent from its original Git HEAD. The baseline was copied and hash-verified before architecture work; no reset to HEAD was used. Earlier README test totals describe their dated releases and are not current acceptance totals.

The existing interface supports native sketch drawing and constraints, tool-first reference picking, linked sketch Use, dimensions kept outside extrusion profiles, feature preview and guarded Finish/Cancel. Drawing cancellation releases selection ownership; snapping accounts for display scale and competing endpoints; accepted and draft geometry retain their separate lifecycle. Shared Part Studio history includes scoped operations, retained rows, rollback insertion and stored reference queries. The assembly workflow remains limited to embedded part snapshots and supported single-level joints.

Earlier responsiveness work supplied provisional extrusion visuals, exact private previews, document indexes, retained history rows, reduced idle hover/region work and idle recovery publication. These are foundations for the later accepted changes above, not new S18 implementations. Native snapshot capture and committed recompute still run on the UI thread. Importing STEP preserves supported geometry but does not reconstruct external sketches, feature history or live assembly relationships; source-conversion acceptance remains separate.

## Validation and source versions

The accepted S18 manifest contains **113 frozen source, test, recipe and helper inputs**. Its local relative path is `runtime/architecture-upgrade-working/s18-step-callback-regression-working/accepted-s18-sources.json`; SHA-256 is `cb1b49441bdc8335852790dec2b7defd5b3527289de2899ae6d050d361b25757`. These local artifacts identify the reviewed working tree; a Git revision alone does not identify the preserved changes.

| Evidence | Version and result | Fresh or retained |
| --- | --- | --- |
| STEP GUI | S18: 91 checks, six preparation scenarios, 19 returned workers and three abandoned allocations. Actual native exit is zero; the contained Job drains naturally, with no forced termination or timeout. | Fresh S18 run; only the GUI recipe changed. |
| Focused preparation tests | S17: five exact native methods pass, covering real admission/allocation/lease cancellation, callback errors and compatible default behavior. | Original S17 receipts and process/source proof retained and reverified. |
| Full native regression | S17: 430 methods, 426 passes and four unchanged opt-in performance skips; zero failures/errors. | All 98 executed native inputs match S18. This is not a new S18 native run. |
| Earlier status/performance suite | S10: 407 passes, zero skips, including the four opt-in methods. Two recorded inspection timing targets remain open. | Historical S09B-source run, not validation of every later change. |

S18's recipe SHA-256 is `2d56432754f7c19f8354b2637a030669ea252296cd84c5728a67b0a6bc18f8a5`; the other 112 accepted inputs match S17. The two new cases inject a unique OSError through the real supplied ownership predicate after actual admission/cancellation or allocation/document switch. Both observe false ownership, exactly one exception, `cancelled_step_export` with the identical cause, and a later normal stale-context result. Strict source/camera state, destination bytes and newer feedback are preserved. No abandoned case captures, borrows, submits or falls back synchronously; allocated workers close exactly once at the tested boundary.

These cases establish one-shot callback-exception regression coverage. They do not establish a general persistent-native-exception fix, queued-Escape interruption or pending-feedback scheduling. The original S17 and S18 receipts retain these distinctions. Historical failed receipts remain failed and preserved locally.

## Performance evidence

| Experiment | Matched observation | Supported scope |
| --- | --- | --- |
| S08 body-icon reuse | Three before and three after GUI runs: median full refresh **1823.87 → 102.92 ms**; completion polling **2058.25 → 337.08 ms**. Icon evaluations fall **1003 → 4**. | Instrumented, isolated per-refresh work reduction on a 1,000-solid fixture. Parts reconciliation itself did not improve. Parent preparation remains synchronous. |
| S16 initial STEP digest reuse | Four fresh native processes in baseline/candidate/candidate/baseline order, three calls each: median full preparation **2043.4025 → 1670.3853 ms**, a **373.0172 ms / 18.25%** reduction. Every candidate sample is below every baseline sample. | Warm geometry cache and a borrowed accepted snapshot, one target containing 1,000 solids. Two independent processes per mode; no measured worker was submitted. This is not a total-export, GUI-paint, memory or kernel speed claim. |

S16's measured candidate was later accepted semantically unchanged through S16C, after separate lifecycle/configuration repairs to private validation. The measured core remains byte-identical; the helper received a documented docstring correction. S17 subsequently adds ownership callbacks; S18 adds tests. Neither reruns or extends the S16 performance result. The local S16 measurement record retains the original incomplete-acceptance checkpoint; S16C is the later acceptance decision.

S10's combined-revision Plate60/Studio comparison uses three operations within each process. Most totals improve descriptively, but slower inspection/reopen observations remain. It cannot attribute changes to a particular optimization or establish statistical, cold-start or application-wide benefit. Its official instrumented idle/changed inspection medians, **27.58/47.89 ms against 20 ms targets**, remain open. S11 found substantial profiler cost in matched diagnostics; that cost is not subtracted to turn the original targets into passes.

## Private and disabled experiments

| Investigation | Disposition |
| --- | --- |
| Resident clone reset — S05 | Transaction abort plus cache clearing fails strict reset: native Body state becomes Touched and its shape hash changes. Fresh clones remain required. Later retry, multipart, memory and matched timing gates were not reached. |
| Staged recompute — S06/S06B | Not activated. Fewer explicit calls did not establish less native work or speed. Dependency-order differences also occur in oracle-only histories, so candidate-only attribution is unsupported. Production retains its original traversal. |
| Finer summary reuse — S12/S12B | Scoped row preservation, callback injection and final-read fences pass. Independent complete current/current/candidate dirty histories remain unfinished; timing and production activation remain blocked. |
| Authoritative process — S13/S13B | Private saved-model proof covers one committed history, ledger/replay, undo/redo and save/reopen. The original positional native comparison remains failed; a separately justified API association assessment passes while preserving required ordered data. General creation, GUI/Sketcher authority, wider models and crash/recovery behavior remain unproved. No production migration occurred. |
| Pending painted feedback — S15 | Private Qt-paint-before-capture feasibility passes scoped cases. Unpaintable-feedback policy and untested races remain unresolved; the helper is not installed. S17/S18 do not activate it. |

The local S12B, S13B and S15 reports retain their exact coverage limits. References to their then-current production version are historical evidence, not the current checkpoint.

## Open gaps and next steps

1. Measure and reduce remaining synchronous admission, capture, acceptance/publication and native recompute stalls. Keep whole-action timing separate from nested phase timings; the proposed acknowledgment and provisional-feedback targets remain unproved.
2. Extend representative evidence to dense sketches, assemblies, private project shapes, independent cold processes, memory growth and input-to-paint behavior. Revalidate performance after subsequent production changes rather than carrying forward speed claims automatically.
3. Complete independent dirty-history equivalence before timing or activating the private summary candidate. Resolve native ordering contracts before reconsidering staged recompute, without discarding preserved counterexamples.
4. Extend the private authority investigation to new-document identity, native Sketcher/GUI integration and interrupted-command/save/recovery behavior before proposing migration.
5. Design pending-feedback behavior for both paintable and unpaintable interfaces, with bounded ownership/cancellation tests, before promoting the private helper. General import/export process migration, including STL and STEP import, remains incomplete.

These are proposed next steps, not authorization for new implementation or external publication. M1 conversion and edited-reference acceptance remain separate project requirements.

## Reproduction and evidence

Use the pinned native runtime and the maintained repository runners described in [README.md](../../README.md). For a future isolated native check, invoke the bundled `runtime/freecad-1.1.4/FreeCAD_1.1.4-Windows-x86_64-py311/bin/python.exe` with `-B tools/run_native_tests.py --suite native --require-native --keep-temp --timeout 210 --report <new-private-report.json>`. Use a new report path and preserve its source hashes and suite receipts. The four opt-in performance methods require `KURTSHAPE_PERF=1`; their timing interpretation is separate from correctness. Recorded native totals also reflect available local external-source fixtures. A public checkout without those originals can report additional skips; `--require-external` explicitly requires them.

`tools/run_gui_recipe.ps1 -Recipe step-export -TimeoutSeconds 240` runs the affected GUI recipe. A future acceptance must also verify the actual native process exit, unchanged source/recipe hashes and complete owned-worker cleanup. A functional check count alone is insufficient. The historical S16–S18 wrappers retain absolute deadlines and must not be presented as immediately runnable future launchers.

Local-only evidence locators, shown as repository-relative code paths rather than public links:

- Current source and closeout: `runtime/architecture-upgrade-working/s18-step-callback-regression-working/` (`accepted-s18-sources.json`, `final-verification.json`, source copies and original receipts).
- Isolated icon comparison: `runtime/architecture-upgrade-working/s08-timing-comparison.md`.
- STEP timing and preserved failures: `runtime/architecture-upgrade-working/s16-step-digest-working/` (`timing-assessment.json` and executed inputs); later acceptance: `s16c-native-validation-working/` under the same parent.
- Full milestone history: `docs/architecture-responsiveness-upgrade/EXECUTION.md` and its local `Sxx` reports.

The new documentation set includes this report, the project README/architecture/operation contract, two user guides, and the architecture-upgrade index/scope. No new raw FCStd/STEP fixture, process log, private profile, session credential, detailed execution record or runtime receipt is added. Existing committed project records and validation metadata remain in the legitimate history; leaving their current edits unstaged does not remove those versions. Reproducing private experiments requires the retained inputs; a public source checkout alone does not contain those artifacts.

## Completion state

S18 is an accepted, closed implementation checkpoint. S19 prepares documentation and a narrow timing-helper packaging correction: the macro's helper path and the copied helper's repository-root lookup. Application production, all 98 native-run inputs and the STEP GUI recipe remain exact S18. Native and GUI gates are retained without rerun; packaging checks are separate and must not be described as fresh CAD validation.

S19 preparation checks pass: 146 Python/macro files parse, 19 PowerShell scripts parse, all 74 SVG icons and 39 advertised GUI recipes are present, 96 public-document links resolve, and the relocated helper imports and forwards the expected child command in a smoke check that starts no child. Launcher `-PrintOnly` returns valid JSON with exit zero. All 389 S18 evidence hashes remain preserved. The proposal contains 245 required files and 186 new changed paths relative to local HEAD (144 additions and 42 modifications) after text normalization; unrelated local work remains outside it. The original index is unchanged and empty of staged changes. Independent review checks the proposed file set and privacy boundaries.

The latest completion control on October 8 at 9:40 p.m. PDT reports 89% used in the original weekly window, with its reset still October 13 at 11:12:30 p.m. PDT. Ordinary usage remains allowed and credits are unchanged; no reset/account/credit action occurred. This finite preparation pass is complete and returns idle without automatic continuation. Detailed control receipts remain local.

The recommended publication target is an ordinary reviewed fast-forward of local `main` to `origin/main`, preserving its 18 existing KurtShape commits plus the proposed new changes. No alternate branch, synthetic commit or history rewrite is needed or created. Independent content review classified the existing history as legitimate project work; machine paths and operational receipt metadata are disclosed, not mislabeled as secrets. A bounded credential scan found no hits. The preferred review snapshot models local HEAD plus only the selected current files; other tracked HEAD content remains. [Exact inventories and publication boundaries](PUBLICATION_SCOPE.md) distinguish the existing history from the 186 new changes. Direct publication authorization remains unresolved, so no commit or push has been performed.
