# S12B safety completion — further-limited assessment

October 8, 2026. **Callback fault proof and scoped native row-preservation proof pass. Independent dirty-history equivalence remains unproved; timing and activation remain blocked.** The exact S12 candidate is unchanged and production remains S09B. No performance benefit or regression is established.

## Completed native proof

The candidate adapter remains SHA-256 `8b064a3e4c13511a565d74d2d9677212dab1b9e6d090b728dc00e075d18952dd`. Its production epoch, identity, ordered dependency, unknown/full-invalidation and read-stability barriers are unchanged. All 110 accepted source hashes remain intact.

`runtime/test-tmp/s12b-callbacks-ea0c6e34/` passes **19 cases and 59 exact row comparisons**, PID53036, exit0,2.43s native/2.67s total, no timeout. During an actual outer native `doc.recompute`, the harness injects guarded Python observer-callback reentry, or raises the same named sentinel before/after the original callback. The fault cases receive zero credit, advance taint, restore depth to zero, force a subsequent rebuild with no stale hit, and recover exact rows and warm reuse after a normal recompute. Nested callback depth is[1,2], with two taints. This is **Python observer reentry**, not recursive native-engine recomputation.

Both unchanged-original controls and candidate wrappers preserve the same sentinel object to the observer boundary. FreeCAD consumes those observer exceptions and returns0 from `doc.recompute` in both paths; no outward Python exception is claimed. FreeCAD caches bound callbacks when an observer is registered, so the test re-registers the same observer after installing/restoring each boundary. All ten registrations preserve observer/state/index identities and clocks. The initial failed harness attempt is retained and is not a candidate failure.

Twelve final-read/fallback cases also pass, including hit/miss copy mutation, first/final identity-lookup mutation, and authoritative-state replacement while the old dictionary's clock remains unchanged. Each records a retry and zero stale hits. Exact executed callback helper SHA: `30994ab81adebedf0c1b8439473a5f8f72a8a45b8238af540662dd220243e872`; launcher SHA: `9e496525b35e3f893dff7ea2c2685024f067f4690061a07ed5a52bc113fcbb80`. The later launcher changes concern snapshot evidence, compact serialization and comparison; this result belongs to its retained executed version.

`runtime/test-tmp/s12b-row-preservation-e083af53/` passes the S12 adversarial module's **14 cases**, with29 exact actual/oracle rows and **60 completed read boundaries**, PID84400, exit0,41.04s native/41.34s total, no timeout. It retains complete raw BReps, ElementMaps/reverse maps/versions, mapped identities and element history, property schema/values, placements, ordered references, native State, metadata and native undo/redo/transaction state. Snapshots are prepared identically around each read and must repeat exactly. Map/history/placement/BRep rereads and non-intrinsic model hashes are checked within each snapshot, between repeated snapshots and across each read segment. Intrinsic Origin shape hashes have the pre-existing allocation-dependent observation limitation; their raw geometry/maps remain exact.

The replay covers dependency rebind/order, invalid/Touched states, dynamic fields, proxy/foreign/Sketcher fallback, journal overflow, state replacement, callback-native-mutation rejection, eligible Pad replacement/restore and document replacement. Four read boundaries include the live foreign document as well as the local document. The deliberately saved `foreign.FCStd`, `identity.FCStd` and `restore.FCStd` archives are hashed at each read boundary and remain unchanged by those reads. Their final contents and hashes are retained.

There are26 fault-seam visits, of which two intentionally change a native Label. The executed harness permits only that object's Label, its narrowly bounded Touched/valid state/status and the resulting intent digest to differ. Geometry, maps, placements, native model identity and unrelated fields must remain unchanged. Other read segments compare exactly; arbitrary seam changes are not accepted as an expected baseline. New unmanaged fixtures receive project metadata before these observations, explicitly recorded as setup. This proves preservation of those prepared fixtures, not untouched unmanaged documents or GUI/camera state. Executed preservation helper SHA: `98442b392f6c1b91454a334ae1b2660d54a3e6908cc5de047f9ed7cb0bb82735`.

## Independent-history attempt and limit

The intended matrix uses identical private `fixture/plate.FCStd` bytes and path in fresh processes, with two unchanged-current controls before a candidate arm. Only the core module UUID binding supplies the same recorded valid v4 session sequence; global/observer UUIDs remain original. Names, native IDs, filenames, revision, all ordered dependencies, raw BReps, maps and signed-zero values remain in the comparator. Native hashCode is separated only as process-local evidence and checked within each arm. Direct first-inspection returns precede any uncached-summary replay. Planned histories include warm, H59 terminal edit, upstream Pad edit, committed edit, undo, redo, abort and restore.

The complete reader initially failed on native `Materials.Material`, then nested `Materials.MaterialProperty`. Explicit typed serializers were added; failures and exact executed sources are preserved. It then exposed the cost of fully expanded element lineage: one Plate60 checkpoint was604.77MB, of which565.48MB was element history. The first current-only run was stopped by its owner after preserving complete repeated initial snapshots. It never completed the history matrix.

The final reader pools identical typed history subtrees without removing values or native queries. Full node bytes, field presence, native types, child order and map/history associations are recoverable. Validation checks digests, missing references, cycles and reachability; comparison resolves actual child data rather than trusting matching hashes alone. Every history query still executes twice, followed by map/version/placement/BRep rereads. Helper SHA: `76815d498afc45b13e3662b7a8bfadead9dab0ff1ae98d2982868b4219afe404`.

The pooled current-only run `s12b-history-current-84751673` retains two104.73MB priming snapshots. Independent review verifies exact complete strict equality,132 objects,374 shape records,41,310 valid pool nodes, all reread flags, and367 non-intrinsic raw shape hashes stable within/between snapshots (plus306 legacy model hashes). This is a **same-process snapshot positive control**, not a completed current/current history comparison or candidate proof.

Capture still takes approximately one minute per checkpoint. The complete multi-process matrix cannot fit this finite batch. Root stopped owned PIDs62032 and63644 after checking their saved PID/command identities. Their launcher receipts report unsuccessful owner termination and missing terminal child reports; they are not successful cleanup/hook-restoration receipts. Partial snapshots, exact executed sources and explicit `owner-stop.json` records remain. Other jobs finish normally. User FreeCAD40888 remains untouched.

## Gate and handoff

| Gate | S12B outcome |
|---|---|
| Exact-adapter nested/throwing observer-callback fault proof | Pass for explicit Python callback injection |
| Final read/copy/state-replacement fences | Pass in exercised native cases |
| Prepared adversarial native row/source/archive preservation | Pass within documented setup and headless scope |
| Independent current/current complete dirty histories | Unproved; current-only runs stopped during priming |
| Independent current/candidate complete dirty histories | Not run |
| Balanced unprofiled timing and useful benefit | Not run; gate remains closed |
| Production activation | Not authorized or performed |

No field normalization or weakened equality was used to force a pass. The machine coverage matrix retains these distinctions. No complete safety gate exists, so candidate timing and activation remain blocked. S10/S11 measurements and official open inspection targets are unchanged. The later private authoritative-process vertical slice remains outside S12B; no new batch starts automatically.

Working recipes and final manifests are under `runtime/architecture-upgrade-working/s12b-summary-reuse-safety/`. Every native run retains its `executed-sources`, process receipt, available raw evidence and failures. Reproduction uses bundled native Python with `-B run_safety_batch.py --mode callbacks`, `--mode row-preservation`, or the explicitly incomplete `--mode history-current`/`history-candidate` recipes; full history needs a separately bounded plan that can afford its evidence cost. `compare_histories.py` rehashes executed inputs before import and fails closed on any unexplained control/candidate difference; it has not run against completed histories and never authorizes timing by itself.

The [execution record](EXECUTION.md), `coverage-matrix.json`, `final-verification.json`, evidence manifest and final process inventory define the handoff. No production/test/budget edit, allowance/reset action, automation/restart, publication or authority migration occurred.
