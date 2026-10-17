# S12 private summary-reuse feasibility

October 8, 2026. **Incomplete feasibility proof; no production activation and no timing claim.** The runtime-only candidate demonstrates selective reuse and passes the exercised native cases. Missing callback and dirty-history equivalence proofs keep the timing gate closed. Production remains accepted S09B; the existing inspection budgets remain open.

## Candidate and controls

The candidate is confined to `runtime/architecture-upgrade-working/s12-summary-reuse-feasibility/`. It admits only exact built-in `PartDesign::Pad` and `PartDesign::Pocket` types without Proxy or KurtShapeTool, in a document whose dependencies are local. Foreign dependencies, proxy dependencies, Sketcher rows and other types use the existing path. It does not alter native recompute scheduling.

The production `summary_epoch` remains intact. An external ledger credits exactly one epoch increment only when the original recompute callback changes the expected serial/epoch/generation, leaves intent/full-invalidation clocks unchanged, and ends with the exact recompute journal entry. Unproved events taint the ledger. The token retains actual document/object/index identity, strong wrapper references, own and ordered dependency versions and native State, full/unknown invalidation barriers, and read stability. It does not use `recomputed_objects` as an unchanged-object oracle or substitute `full_change_serial` for unknown invalidation.

Read-only review found and repaired final-native-lookup ordering, miss-copy validation, authoritative-state fallback validation, post-fence native accounting, and diagnostic exception-masking gaps before the first native run. Both executed runs use the same adapter SHA-256: `8b064a3e4c13511a565d74d2d9677212dab1b9e6d090b728dc00e075d18952dd`.

All 110 accepted production/test/budget hashes remain frozen. The retained S11 Plate60 archive (`e955151c65ff5c48dd45604145bda169ede2b014792a65d39023c3bb8b4ba2f2`) is an explicit immutable input. No fixture is silently regenerated. Native authority is FreeCAD 1.1.4 / OCCT 7.8.1. Root alone launched two sequential private jobs, each bounded to 300 seconds with owned-process reaping. User FreeCAD PID 40888 was untouched.

## Observed results

The first run, `runtime/test-tmp/s12-summary-reuse-40558d03/`, exited 0 in 14.15 seconds total; its native child took 13.56 seconds. It passed 17 recorded cases plus all 11 unmodified `IncrementalDocumentStateTests`, with no skips, failures or errors. Its exact recipe is preserved as `validate_summary_reuse.first-executed.py`, SHA-256 `ed18b05cbf4c2cf6756ae002b4f21efb250e87f2d0f4572501d8ec3042a0be1a`.

| Plate60 inspection | Eligible hits | Eligible builds | Existing-path fallbacks |
|---|---:|---:|---:|
| Warm | 61 | 0 | 63 |
| After terminal H59 diameter 30→31 | 60 | 1 | 63 |
| After upstream Pad length 12→13 | 0 | 61 | 63 |

For H59, the one rebuilt eligible row is P59; Pad and P0–P58 are reused. After the upstream edit all eligible rows rebuild. No hit intersects the recorded set of changed rows or rows with a changed direct dependency. Ordered row content is compared with the original `native_feature_summary`, without sorting or normalization. Full candidate inspection outputs match `KURTSHAPE_FULL_INSPECTION=1` replay. That flag bypasses feature summaries only; it is not a globally uncached inspection oracle.

The existing tests exercise expressions, constraints, native dimensions and labels, transactions/undo/abort, dynamic properties, intent and reference metadata. Targeted cases additionally verify QueryHealth/QueryInputs content, nested copy isolation, malformed-JSON exception parity, Proxy/KurtShapeTool exclusion, unknown `invalidate(changed=None, intent=False)` while `full_change_serial` remains unchanged, and real native Label mutations during token/build/copy/final-identity-lookup seams.

The second run, `runtime/test-tmp/s12-summary-reuse-3a434ee8/`, exited 0 in 1.04 seconds total; its native child took 0.51 seconds. It passed 14 further adversarial cases, retaining actual and oracle rows in `adversarial-native-rows.json`. Its recipe is preserved as `validate_summary_reuse.second-executed.py`, SHA-256 `e0c6e6b448f4cf47410d3075189e71e92da1cb73d5941586f1c71d835f1a85f8`; the supplemental module hash is `f92e8e33eed44aec3e08cec36eaac8480468dcffd95d31c24333c7573b8fc8c5`.

Those cases cover mutations during both hit and miss copies, native Profile rebinding, actual OutList order changes (including duplicate native dependencies), Touched/Invalid/recovered State, Reversed and dynamic source fields, proxy-dependency and saved foreign-XLink fallback, Sketcher fallback, full invalidation and 4,200 native Label changes followed by a summary read, authoritative observer-state replacement during a fallback build, same-name eligible Pad replacement, eligible Pad save/close/restore, and same-name document replacement. A real native Label mutation injected inside the original recompute callback prevents credit and still yields row parity. The state-mapping replacement is explicit fault injection; native mutations use real observer callbacks.

Both reports confirm accepted source preservation, native document cleanup, hook restoration and successful process exit without timeout. Archive-preservation checks cover the retained original Plate60 and the first run's copied Plate archive. The deliberately saved adversarial documents are retained evidence; their final hashes identify their saved contents and do not establish preservation across intentional edits. Wall-clock job durations above are lifecycle receipts, not performance comparisons.

## Proof limits and decision

The candidate's whole-inspection snapshots are captured **after** candidate inspection, then compared with the uncached-summary replay on the already synchronized document. They establish exact accepted-state stability and output parity. They do not establish independent current-path equivalence from the same dirty starting history, or pre→post native preservation across the first candidate inspection with explicitly justified synchronization changes. No native field was removed to force equality. The snapshot helper also does not separately serialize full ElementMaps/property schemas, and headless runs provide no GUI/camera proof.

Nested and failed native recompute callbacks were not exercised. The uncomplicated callback credits and one mutation-tainted callback do not replace those cases. The first receipt's listed blockers are historical: the second run closes its eligible replacement, dependency-order, foreign fallback and fallback-state replacement cases, but the complete gate remains open. Individual `passed=true` receipts mean their exercised assertions passed; they are not activation approval.

The current-cached third inspection mode and balanced, equivalent-history, unprofiled timing arms were **not executed**. No useful speed benefit, regression, statistical confidence, global cache correctness, GUI responsiveness improvement or production readiness is claimed. Candidate bookkeeping and revalidation costs are unmeasured. Existing S10 instrumented inspection targets remain unchanged.

S12 stops without activating the candidate or launching timing from this partial proof. The next recommended architecture task is the previously identified **private authoritative-process vertical slice**, under a separate finite authorization, to assess ownership, command/revision/undo semantics and Sketcher/GUI boundaries. It is not started here. Resuming this summary candidate instead would first require a separately authorized complete callback/dirty-history proof, then matched current/candidate/uncached-summary timing bound to exact source, adapter, recipe, fixture and evidence hashes.

## Reproduction and evidence

Use bundled native Python with `-B` and the retained executed recipe. The first recipe supports `--phase parity`; the second supports `--phase adversarial`. Each launcher creates a new descriptive private run directory, verifies the 110-source freeze and original archive, bounds/reaps its child, retains output and records recipe hashes. Preserve the associated adapter and supplemental-module versions when reproducing. No tests or budgets were edited and no full production regression suite was rerun for this private-only experiment.

`runtime/architecture-upgrade-working/s12-summary-reuse-feasibility/final-verification.json` records the combined conclusion, evidence/source identities and cleanup. `artifact-manifest.json` preserves the final document and recipe hashes; `evidence-manifest.json` identifies all retained files in both native run folders. The [execution record](EXECUTION.md) contains the finite-batch controls and handoff.
