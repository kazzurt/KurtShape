# S16B — validate the preserved STEP candidate's lifecycle

Status: **closed, candidate activation declined**. The GUI gate passes with observed native exit and natural cleanup. The full native run has clean process accounting but fails functional validation. At 16:47:34 UTC, only the five reapplied candidate files were restored/removed; all 111 accepted S14 hashes match. The exact 113-file S16 candidate remains preserved privately.

S16's eighteen focused tests, four-process timing comparison, 421 native passes with four existing performance skips, and 76 GUI assertions remain valid historical functional evidence. Its failed outer lifecycle receipts remain unchanged. S16B introduces no optimization, feature, pending-feedback, benchmark or candidate-test changes.

## Preserved inputs

Initial root control at 16:26:08 UTC reports 75% used, the original 10080-minute window/reset 1791958350, ordinary usage allowed and 62500 credits unchanged. Independent preflight verifies all 111 restored S14 files, all 113 preserved S16 candidate files and all 1082 S16 evidence entries. The S14 sources and living documentation are copied before changes under `runtime/architecture-upgrade-working/s16b-lifecycle-validation-working/`.

At 16:29:04 UTC, root reapplies exactly the three changed originals (`core.py`, existing STEP tests and native-suite registration) and two new S16 files (`step_capture.py` and its tests) from S16's `source-after/`. All 113 live hashes match the preserved final freeze. No candidate bytes are edited. The historical S16 measured helper's docstring distinction remains as previously documented; S16B uses the exact final candidate bytes.

## Validator scope

The GUI validator directly creates the native FreeCAD process suspended, retains its original process handle, assigns its owned Job Object before resuming, and uses the unchanged existing STEP GUI macro with a private profile and frozen bootstrap. Acceptance requires a successful wait, actual native exit code 0 from the retained handle, agreement with Popen's return code, and exact GUI report PID/handle PID agreement. A passing JSON report, null exit code, PowerShell wrapper exit or empty Job cannot substitute for native exit evidence.

The historical null PowerShell `ExitCode` cause remains unproved. No S09B-versus-S16 shell-version claim is made, and acquiring a handle after process creation is not used to resolve the fast-exit race.

The validator keeps its Job handle open through a bounded natural drain and records initial/final active counts and elapsed time. If processes remain, it terminates only that owned Job and boundedly confirms zero before closure. Natural completion, forced termination and post-termination zero are separate receipt fields. Forced cleanup establishes containment and cannot qualify as clean acceptance. Query failures or expired deadlines remain failures. Kill-on-close stays the fallback.

Four small controls cover immediate zero exit, nonzero exit, delayed exit and timeout cleanup. Their expected-outcome assertions are separate from native/GUI acceptance. The unchanged full native suite may run once to validate its many-child natural drain; the unchanged STEP GUI recipe may run once for actual native exit and complete cleanup. No passed candidate tests or timing campaign are repeated.

## Finite bounds and result

S16B stops new validator implementation at 16:40 UTC, finishes all owned jobs by 16:50, and closes by 16:55. Each job's full timeout plus cleanup must fit. The batch usage ceiling is 80%, overall 90%, with the original October 14 06:12:30 UTC weekly deadline unchanged. Root alone launches sequential private jobs and preserves user FreeCAD 40888. No global process enumeration, reset/account/paid allowance action, automation, publication or automatic next batch is authorized.

## Final evidence and scoped rollback

The four tiny controls pass their expected outcomes: immediate zero exit, nonzero exit23, delayed zero exit and timeout containment. The first three drain naturally; the timeout control requires forced termination and confirms zero afterward. All four explicitly have `clean_acceptance=false`; a successful timeout control does not qualify a native/GUI run for acceptance. Their executed validator hash is `7084f18c76be74642646bc78d9577a2c8558ac81fcabf64a7653d3d057d90cfe`. Final wait-failure, deadline and report-freshness guards were source-reviewed before the implementation cutoff; their patch and review are retained.

Both full gates use unchanged validator SHA-256 `196504664c05566c368aaa9feb201edfa73bc1607514a367fc9e25374f0e83b9` and exact S16 candidate hashes. No validator implementation followed the 16:40 cutoff. Administrative rollback, receipt aggregation and documentation followed the completed jobs.

| Gate | Functional result | Observed process result | Acceptance |
| --- | --- | --- | --- |
| Native `native-a5baec27` | 425 methods:383 pass,4 existing performance skips,5 failures,33 errors | Aggregator87844 and suite27924 exit1; Job42 total,0 active naturally; no force/timeout;172.844s | Failed; clean lifecycle of a failed functional run only |
| GUI `gui-ce3d71d8` | 76 assertions pass;19 worker records all cleaned up | Native FreeCAD65924 retained handle660 signaled, Win32 and Popen exit0; Job38 total,0 active naturally; no force/timeout;72.653s | Valid independent GUI gate retained |

The GUI report PID matches the direct native creation PID; its seven source/recipe hashes, parent113-file freezes, executed inputs and fresh report hash match. Exit was observed at16:46:22.447109 UTC. Independent receipt review is saved in `gui-receipt-review.json`. This new valid GUI gate does not retroactively alter S16's failed PowerShell receipt.

The native wrapper sets `KURTSHAPE_TEST_TMP` to a private `s16b-native-.../test-tmp` directory. The existing runner appends its normal `regression-run-.../native` layer, lengthening the test paths. All33 `FileNotFoundError` destinations are260–282 characters long. This strongly supports a harness path-length diagnosis. The five assertion failures occur at native save (`Failed to open file`); reconstructed staged filenames are224–236 characters, so their exact causes remain unresolved. `native-failure-diagnosis.json` and `.md` retain individual cases, paths, source locations and this uncertainty. No functional failure is relabeled as passed, and no native rerun occurred after the implementation cutoff.

At16:47:34, `restore_s14.py` first verified all113 live candidate hashes and preserved copies, then restored exactly `core.py`, the existing STEP tests and the native-suite runner from S14 backups, and removed only the two hash-matched S16 additions. `scoped-rollback.json` verifies all111 accepted baseline hashes and both added files absent. No accepted S16B manifest is created. S16's1082 evidence entries and113 candidate source files remain preserved; living documentation from before S16B supplies the historical documentation hashes.

At16:48:25, exact-PID inventory found all30 recorded S16B PIDs absent. User FreeCAD40888 remains present with its original October3 00:55:26 PDT start. Owned Jobs had already reached zero before handle closure; no global process enumeration was used. Root controls progressed75→76→77→78% in the unchanged10080-minute window, reset1791958350, ordinary usage allowed and62500 credits unchanged. The pre-GUI check was77% at16:45:04; the closeout check was78% at16:47:57, below the80% batch cap. No account/reset/paid allowance action occurred.

`verify_private_closeout.py` verifies rollback, preserved historical evidence, exact executed inputs, four control outcomes and the distinct native/GUI results. It writes `final-verification.json` and the S16B evidence manifest with `candidate_activation=false`; the strict acceptance verifier remains unchanged. Recipe: ordinary Python3.14 runs `run_validation.py control CASE`, then sequential `native` and `gui` modes; native mode uses bundled FreeCAD Python and GUI mode uses the direct native executable. The exact commands, environments, copied recipes and executable/source hashes are retained with each receipt. Reproduction requires a newly authorized finite checkpoint and fresh usage/time controls.

Final controls at16:51:04 UTC remain78%, with the original weekly window/reset and credits unchanged. The private closeout verifier passes, including all111 restored source hashes,113 preserved candidate hashes and1082 prior evidence entries. Documentation whitespace validation also passes. No native/GUI jobs remain.

Next step, only if separately authorized: repair the private native profile nesting and validate only the missing native gate against the same preserved candidate. Retain the valid GUI gate, historical timing and focused-test evidence; no repeat GUI or benchmark campaign is justified while candidate bytes are unchanged. This batch is idle with no automatic continuation, publication or production activation.
