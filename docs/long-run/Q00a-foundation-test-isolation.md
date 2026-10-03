# Q00a: Foundation fixes and isolated test execution

October 3, 2026, America/Los_Angeles. Base longrun/start: 0454cbb. Spec: review brief increment 0 items 1 to 9, amended by the long-run program. Program SHA-256: BFD1820915CDEDE335C2FF421163F1A404E666211402E81DB8E936631D3C2995.

## Plan

Fix assembly runtime path and pinned version, Panel.tick missing-state guard, shared contract constants, quantity-error units and bridge JSON charset handling. Preserve Origin rejection and existing transport guards. Touch points are assembly._native/NATIVE_PATH, core.number/capabilities, bridge.Handler/session JSON and Panel.tick. Both assembly and carrier probes derive the runtime from running FreeCAD. Contract stays 2.0; no modeling or profile format change.

Add tests/support.py and isolate every controller/session/temp/evidence write, including U2 and fresh-process proofs. Add five runtime-layout tests, one quantity-unit test and three bridge tests. Preserve existing assertions except explicitly authorized root-membership replacements and external fixture guards; list replacements in the implementation record.

Add a fresh-process native/bridge/shortcut/workflow runner, omitted-TestCase detection, native networking denial, unchanged-source proof, JSON/JUnit and skip enforcement. Add evidence_dir/external helpers and record_evidence. Route reports, screenshots and fixtures through isolated evidence by default; only explicit WriteEvidence writes tracked reports. Keep committed fixture readers. Source tools reject missing inputs; assistant client honors isolated session env. Rewrite run-checks with its own profile/temp and add a before/after local status/diff-hash check. Q00b owns CI, generic GUI runner, benchmarks, installer, lint and attributes.

Every process uses all six isolated environment variables, hidden GUI input stays inside Qt, and PID/command recording stays under runtime/longrun. No live bridge, normal launcher, write-root expansion, dependency install, runtime extraction, push or CI claim.

## Verified baseline and spec adjustments

- Native baseline passed 141/4/22 with zero skips; native suite 170.872 s. Expected after additions: 147/7/22, re-derive from discovery. Brief counts and line anchors are stale.
- Preserve all fourteen native classes, including four U2 classes. SelectorTests has no Controller but still needs scratch isolation. Fresh-process proofs inherit all profile variables.
- Windows probe verified App.getHomePath exactly the pinned runtime, OCCT 7.8.1 and JointObject under Mod/Assembly. Runtime can be derived without source-relative hardcoding.
- Evidence helpers need tools on macro sys.path. Committed shortcut probe stays an input; recovery/reopen readers resolve incoming evidence before replacing session env.
- Empty Origin currently passes; presence rejection follows the existing invariant. External inventory labels need a safe fallback outside CADkz.
- Native baseline rewrote exactly four tracked report paths, restored. Three reports needed index-stat refresh despite an empty content diff; exact-path add staged no changes.
- All existing GUI recipe scripts ran before source/script/macro edits: 14 passed, 2 baseline-red, plus Messages passed 34 checks earlier. Interface failed at Confirm creates valid native solid (11 completed checks); historical carrier spike failed its pre-U2 history expectation (17 completed). U2 passed 99; refinement 106; preview 20; sketch 28; copy 25; lifecycle/recovery/startup completed; interaction 10; STEP 19; Assembly 58; direct STEP 35. Detail: runtime/longrun/gui-baseline-results.json.
- Plan/STATUS writes during the baseline raced with its exact-path evidence cleanup. The wrapper restored/deleted them; records were recreated after it exited. No source changes occurred during U2 hashes.

## Gates and budgets

run-checks -Full: all native/bridge/shortcut/workflow tests, no skips. A nonexistent KURTSHAPE_ONSHAPE_EXAMPLES override: exactly three external skips, no other skips. Do not move examples. RuntimeLayoutTests and tracked-source grep prove runtime layout; no FreeCAD_1.1.4-Windows literal remains under src. Local ignored-aware status and diff SHA-256 stay identical across checks, excluding long-run docs and documented Kurt-owned paths. Probe deliberate temporary mutation detection, never clean automatically.

Review-interaction must pass the managed/unmanaged/reactivated tick regression. Existing baseline-red failures remain individually identified; never weaken them. Targeted rendered checks are inspected. Use record_evidence for small JSON, review full diff and record findings, commit/tag longrun/Q00a. No wall-clock budget in Q00a; Q00b measures Windows plate/studio baselines.

## Implementation record

Assembly and both probes now resolve the running runtime. The tick regression preserves managed state after an unmanaged tab. Shared constants publish contract 2/revision 0; quantity errors name the target unit and JSON charset headers work while every Origin header is rejected. The assistant CLI honors an isolated session override.

All fifteen native classes, bridge and both shortcut classes are cataloged. Fresh children have six private profile variables and evidence inside their scratch grant. Existing U2 native proof subprocesses record their actual owned PIDs. Source tools fail before writing empty evidence. Twenty-three macros and validation scripts route default output to isolated evidence. Embedded GUI bytecode suppression precedes the helper import; all tracked input readers remain in place.

Existing assertion replacements: the scratch-root checks in CoreSafetyTests.test_native_touched_edit_blocks_current_geometry_and_export_until_rebuild, test_open_live_relocated_copy_rejects_duplicate_uuid_preserves_original_mapping and test_readonly_export_sidecar_failure_preserves_both_outputs_and_retry_hash; and NativeConversionTests.test_save_reopen_relocate_preserves_native_mapping_and_dependencies. Each now asserts membership in configured write roots, as authorized. The general-actions GUI assertion uses its mocked private report root and retains the exact transport-credential exclusions. The three named external guards are the only new skips. Every other existing assertion remains unchanged.

Review corrected ten infrastructure findings: fixture-error accounting, child-exit JUnit diagnostics, parent source-hash JUnit diagnostics, conditional/inherited/imported class coverage, exceptional child cleanup, private child evidence, colliding class declarations, exact-byte tree hashes, literal path exclusions and fresh-proof PID recording. The first Full gate failed a new Windows rejected-header transport test; header-only requests preserve all HTTP status and no-mutation assertions while avoiding unread-body resets. The first tree gate caught only a newly generated helper cache; its exact file and verified-empty folder were removed. No legacy cache or user material was removed. Full attempt 2 passed; the final inventory correction was then probed and the gates repeated on the final source.

| Gate | Result | Evidence |
|---|---|---|
| Full | 147 native, 7 bridge, 22 shortcut; 6 workflows/405 checks; zero skips | validation/2026-10-03-upgrade/foundation-test-isolation/native-tests.json |
| Missing examples | 144 native passed, exactly 3 external skips; bridge/shortcut/workflows passed | validation/2026-10-03-upgrade/foundation-test-isolation-without-examples/native-tests.json |
| Runtime layout | Five tests passed; source runtime-folder grep empty | Native suite and runtime/longrun/runtime-layout-probe.json |
| Interaction | 11 checks, owned process exited; screenshot inspected | validation/2026-10-03-upgrade/foundation-test-isolation/gui.json |
| Copy / U2 | 25 / 99 checks; owned processes exited, clipboard restored, source unchanged | Private session evidence under runtime/review-copy-validation and runtime/u2-part-model-gui-validation |
| Runner failure injection | 10 checks, including class collisions, fixture errors, JUnit failures and owned-child cleanup | runtime/longrun/runner-failure-probes-result.json |
| Source guards | Both tools returned 2 for missing sources before writing reports | runtime/longrun/source-guard-probe-session/process-logs |
| Local tree | Exact status and diff bytes unchanged; deliberate untracked JSON rejected | runtime/longrun/q00a-tree-final.json; SHA256 dff506781293741634eff0f038b41acf13e1ffd2cc1140dc87e056ae18e4fc60 |

Reproduce Full with `./run-checks.ps1 -Full`. Reproduce the external skip gate by setting KURTSHAPE_ONSHAPE_EXAMPLES to a nonexistent scratch path and running `./run-checks.ps1`, then remove that override. Run `./validate-review-gui.ps1 -Scenario interaction` and `-Scenario copy`, and `./tools/validate-u2-part-model-gui.ps1`; wait for each printed owned PID and read the printed private report. Capture/Compare with `./tools/check-local-tree.ps1 -Mode Capture` then `-Mode Compare`. Stage explicit new increment files before capture so their content enters the hash. Record small reports through record_evidence with explicit --write-evidence. Python tools/probes use tools/validation-session.ps1 to set all six private variables before hidden Start-Process.

Rendered inspection covered review-gui.png, u2-parts-final.png and explicit-merge-scope-preview.png. Thumbnail reads and the caught native GUI notification Access violation match historical STEP evidence; no new warning class appeared. Baseline interface and historical carrier failures remain red and unchanged. No benchmark or CI claim is made; Q00b owns benchmarks/CI/lint. No live session, pinned runtime or original sources were written. Automated synthetic checks do not establish hands-on comfort or overall parity. M1 remains incomplete and real parametric conversions remain 0/2.

Final independent read-only review: zero remaining actionable findings. The full source/test/tool/doc diff was reviewed, including error paths, write roots, profile isolation, child ownership and retained assertions.
