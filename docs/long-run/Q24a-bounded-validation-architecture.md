# Q24a — Bounded validation fixtures and current architecture

Started 2026-10-03 America/Los_Angeles from main 7a20a63 (longrun/Q01).

## Scope and eligibility

All earlier unfinished queue items are parked or depend on the parked Q00b/Q02a increments. Section 7 directs never-started dependent work to be marked blocked, rather than given a parked branch. Treat those transitive blocks as the remaining parked work for Q24 eligibility; this independent hardening slice can land the blocker required to resume Q00b. Q24b retains hidden-control hardening, display measurements, the final stale-statement sweep and final handoff. Do not retry either parked increment until its blocker is on main.

Keep complete SHA-256 identifiers and unchanged native fingerprint, geometry, relocation, save/export, revision and undo assertions. Shorten the Assembly GUI recipe's descriptive working path or diagnostic BREP filename so the new full-UUID private profiles do not produce the observed 264-character path. Record actual path lengths and demonstrate the same full native assembly workflow in a fresh profile with the runner's longest supported basename. No production save, export, assembly geometry or shortcut behavior change.

Write a contributor ARCHITECTURE.md describing current main, including the controller, current command and dispatch paths, observers and intent, existing preview/recovery, native assemblies and GUI-thread/GIL restrictions. Clearly identify forthcoming registries/caches/workers as future work if absent. Add living-doc records without changing the contract revision.

## Touch points found on main

- tools/assembly-gui-validation.FCMacro: record_fingerprint writes snapshot-fingerprint-gui-<64hex>.brep below assembly-gui-projects-working. This instrumentation is not the production fingerprint algorithm.
- src/kurtshape/assembly.py: _geometry_fingerprint hashes a mesh-free native copy with canonical_brep; leave unchanged.
- tools/kurtshape_evidence.py: private-session evidence and created-folder ledger; retain isolation.
- validate-review-gui.ps1 -Scenario assembly launches tools/assembly-gui-validation.FCMacro; tools/validate_assembly_reopen.py performs the independent native relocated reopen. Its diagnostic BREP filename has an even longer headless prefix, so shorten that filename as well. Preserve hidden launch and six private environment roots.
- tools/check-local-tree.ps1, run-checks.ps1 and tools/record_evidence.py: existing Q00a tree/regression/evidence policy.
- README.md, docs/OPERATION_CONTRACT.md, docs/M1_PROGRESS.md, ARCHITECTURE.md.

## Spec adjustments and contract

Brief increment 18 is a final hardening/handoff item, but the queue currently cannot advance through parked validation failures. Land only a coherent independent validation repair and architecture overview now; defer display changes and final handoff. The Q00b WIP runner/CI/perf are absent from main and must not be imported into this slice. The full native GUI workflow is the regression test; no mirrored trivial unit test or weakened assertion. Contract remains 2.0, no new operation or profile format.

## Gates and budgets

1. Exact ignored status and binary diff SHA-256 before and after all checks, excluding docs/long-run and documented Kurt-owned paths.
2. Full run-checks.ps1 on final source: expected main 147 native / 7 bridge / 22 shortcut plus 405 workflow checks, no skips with examples; source hashes unchanged.
3. Complete hidden Assembly recipe in a fresh private full-UUID session, strict passed=true report, owned PID exit and screenshots inspected. Run native relocation verifier if the existing recipe requires it. Preserve all original checks.
4. Independent full diff review and living docs/evidence in the same commit. Publish only small JSON through record_evidence.py.
5. CI and five-repeat plate/studio gates are unavailable until Q00b lands; report NotRun with this reason. This recipe-only repair changes no measured application path or display setting; claim no performance improvement.
6. This is the third prospective finished increment, so run the full current-main GUI set before tagging: baseline sixteen recipes plus Messages; bench-GUI is absent with parked Q00b. Reuse the already completed Assembly gate on the same frozen source. Retain the named baseline carrier failure exactly; strengthen intentional recovery process acceptance with a fresh independent native checkpoint/draft/Cancel proof. All waits use owned PIDs and private environments.
7. Keep green copy at Q01 until Q24a is tagged; update with the existing guarded updater afterward.

## Required probe

Reproduce the long session pathname structure without using Kurt's live profile. Prove new BREP fixture uses the full digest and that the original fingerprint algorithm and all native assembly consequences pass. Keep path/click diagnostics in private evidence, never raw fixtures in Git.

## Implementation record

Completed on 2026-10-03. Shortened only diagnostic fixture paths: assembly-fixtures, fp-gui-/fp-native- followed by the complete 64-character digest, PID-qualified source/solved/links files, and relocated. PID qualification retains repeated-run uniqueness. The production fingerprint still receives the original native source and uses its unchanged algorithm. Added report-only serialization readback/hash and actual staging-path diagnostics. No existing assertion changed: all 58 GUI and four native reopen conditions remain intact. No application operation, save/export protocol, profile format or contract revision changed.

ARCHITECTURE.md describes the current explicit dispatch tables, whole-document intent and generation caches, synchronous disposable preview/recovery/import/export, native assembly boundaries and GUI-thread/GIL rules. It distinguishes parked and forthcoming implementations from shipped behavior. Living docs changed in the same increment; no atlas behavior shipped, so no new parity row is warranted.

| Evidence | Result | Private record |
|---|---|---|
| Full regression | 147 native / 7 bridge / 22 shortcut; 405 workflow checks, zero skips/failures/errors, source unchanged | runtime/test-tmp/checks-20261003-182319-54988/evidence/checks/native.json |
| Long-profile Assembly | Original58 GUI and fresh-native4 passed; owned52480/25444 exited0; all11 images inspected | runtime/longrun/q24a-assembly-long-profile.json |
| Full digest/readback | Two proof groups passed; GUI/native BREP paths234/237 characters; complete64-character identifiers and exact text hash/readback | Same Assembly receipt and its original reports |
| Native staging paths | FCStd176/stage183, relocated186, STEP184/stage194, sidecar stage196; worst10-digit PID staging188/199/201 | Assembly fixture_path_lengths; path arithmetic from actual publication suffixes |
| Full current-main GUI cadence | Complete17 recipes:16 passes, exact known carrier baseline failure after17 checks retained; no unexpected failure | runtime/longrun/q24a-full-gui-attempt1.json |
| Recovery independent proof | Ten checks/eleven explicit consequences; producer4084 Windows abnormal exit, fresh verifier51084 exit0; draft1→Cancel0, unsaved1800mm³ retained, original1200mm³ and bytes unchanged | Sweep recovery proof in its separate post profile |
| Visual review | All76 unique screenshots inspected:19 first-six,11 Assembly,46 remaining | runtime/longrun/q24a-final-visual-proof.json, bound to final aggregate hash |
| Tree check | Exact ignored status and binary diff SHA d80d56ff4e3e3b1758a0eb231c6c2f0c2695478eef119adb7f056b8c94b969e8 unchanged through all gates | runtime/longrun/q24a-tree-before.json |
| CI / five-repeat plate and studio | NotRun: Q00b implementation remains parked and absent from main; GitHub CI also awaits Kurt's push | Explicit benchmark NotRun report; no speed claim |

The GUI results are interface41, ui-refinement106, both preview recipes20 each, sketch28, copy25, lifecycle22 stages, interaction11, startup3, baseline3, STEP19, Assembly58 plus native4, assembly-STEP35, Part Studio99 and Messages34 with clipboard restoration. Carrier remains passed=false with exactly “Shared history retains split composition and output features: Feature canceled”. The aggregate's raw passed=false is preserved; gate_passed=true means no failure beyond that named baseline.

Review found zero remaining source/diff issues. Before launch, three targeted-wrapper cleanup/count guards and repeat-fixture naming were corrected. The sweep helpers corrected receipt initialization/signature and fractional DateTime parsing before their first actual run. Publication review corrected missing-environment restoration before launch. Two independent final helper reviews reported zero remaining findings. These private-helper repairs changed no production assertion and caused no failed Q24a GUI gate.

Recorded reproduction commands, executed from the repository:

```powershell
.\runtime\longrun\q24a-run-full-checks.ps1
.\runtime\longrun\q24a-run-assembly-long-profile.ps1
.\runtime\longrun\q24a-full-gui.ps1
.\runtime\longrun\q24a-publish-evidence.ps1 -ScreenshotProofPath .\runtime\longrun\q24a-final-visual-proof.json
```

The ignored private helpers, original JSON, fixtures, logs and screenshots are retained in place. Sweep/publication helpers intentionally refuse existing result targets: a later reproduction must preserve these receipts and use fresh attempt paths, never overwrite history. The native recovery helper SHA-256 is 25b09f84e574de25f979569e2a130a92e08598f3e9657a15ed736aaa0d3ee408; frozen sweep a69840f15c5e194b663d3753a9a3449086b7ef647b2a57b24781f8783f1a0de2; publication88fc731306cea60e2551fb185485b77d49abfb56654848687864ce677ac3021f. Every launch uses a fresh private profile, all six environment roots and an owned hidden PID ledger. Small public JSON is produced only by the explicit record_evidence.py opt-in.

Limits: this is fixture hardening, not a Windows long-path API change or an application benchmark. Native startup thumbnails, empty sketch/constraint diagnostics, binding deprecation, QStatusBar and deliberately seeded fixture warnings match prior logs. Early sketch geometry, narrow native labels and large U2 previews can be clipped by the retained camera; separate controls remain readable. Overlapping assembly-STEP captures do not prove distinct placement, which the quantitative assertions cover. Native autosave restoration remains NotVerified because no archive exists. This is not hands-on comfort acceptance or overall Onshape parity. Q24b retains hidden-control diagnostics, display measurement and the final stale-doc/handoff work; Q02a remains parked. Q00b can resume only after this blocker is tagged on main.

M1 remains incomplete and real parametric conversions remain 0/2.
