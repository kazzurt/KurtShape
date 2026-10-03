# Onshape atlas parity ledger

Updated October 3, 2026, America/Los_Angeles. U2 started from `main` at `d9efdcc`; U1 had not landed. Status describes the runnable app. Synthetic local fixtures demonstrate native semantics; they do not count as historical Onshape conversions.

| Atlas keys | Before | U2 status | Evidence / boundary |
|---|---|---|---|
| `ps.part-studio`, `ps.feature-list` | partial | implemented | Shared native order across logical parts; insertion and versioned native dependencies. `test_part_studio.py` |
| `ps.parts-list` | partial | implemented | Current parts only; stable IDs, rename, color and visibility; GUI Parts checks |
| `ps.result-operation-type`, `ps.merge-scope` | partial / missing | partial | New/Add/Remove/Intersect, automatic or explicit current-part scope; preview and shared controller. Extrude/Revolve/Sweep/Loft reevaluate automatic targets during managed rebuild. Unsupported downstream generation migrations and changed automatic pattern target sets fail closed. One valid solid per logical result; empty/disconnected outputs reject |
| `ps.creation-type`, `ps.extrude`, `fs.extrude` | partial | partial | Native finite/through/up-to-face tools and scoped results. Multi-solid New, thin extrusion and every Onshape start/end variation are not implemented |
| `ps.end-types` | partial | partial | Blind, through-all and native up-to-face; no up-to-next/body/vertex or arbitrary offset end |
| `ps.revolve` | gui | implemented for supported solids | Native Revolution with result operation/scope; typed parameters and actual GUI preview |
| Sweep / Loft result operations | gui | implemented for supported solids | Native Sweep/Loft tools, scope/result controls and disposable previews; section/path contracts remain narrower than Onshape |
| `ps.boolean`, `fs.boolean` | gui | implemented for supported solids | Union, subtract, intersect; keep-tools and private per-target native tool carriers |
| `ps.split`, `fs.splitpart` | missing | partial | Plane, planar face or sketch plane produces both editable halves with stable side identities; native datum attachment survives fresh-process reopen. Curved split surfaces and bounded sketch-region splits are unsupported |
| `ps.transform`, `fs.transformCopy` | gui | implemented | Translation/rotation/coordinate system and copy, through native Link/Compound/Body dependencies |
| `fs.deleteBodies` | missing | implemented | Delete intent removes current result; native one-step undo/redo restores it |
| `ps.pattern-types`, `ps.linear-pattern`, `ps.circular-pattern`, `ps.mirror` | partial / gui | implemented for whole parts | Native placed/mirrored copies with all four result operations and merge scope; feature/face pattern equivalence is outside U2 |
| `ps.rollback-bar`, `api.update-rollback` | registered / missing | implemented locally | Drag slider, registered Up/Down, typed rollback; insertion rewires stable native part inputs. No cloud API endpoint |
| `ps.missing-references`, `ps.feature-error-indicators` | partial | implemented | Cached per-input health, bounded resolution log, feature-list indicator/tooltip, inspect and export guard |
| `arch.queries-as-references`, `fs.queries`, `fs.query.Query` | missing | implemented | Native persisted selectors, dependency-ordered transactional rebinding; native names are caches. `test_selector_consumers.py` |
| `arch.operation-ids-and-entity-identity` | partial | partial | Native operation IDs, logical part IDs, full tested raw-name creator branches. No source topology-ID translation |
| `arch.topology-ids-and-id-translation`, `api.topology-ids`, `api.associativity` | missing | missing | Onshape-to-local associativity belongs to U5; no cloud identifiers guessed |
| `fs.query.qCreatedBy` | missing | implemented on pinned native history | Full raw H-trailer branches and verified native instance-generator metadata retain refined merge contributors and whole-part copy creation; generated/modified/split cases tested. Unknown, hashed and stale maps fail closed |
| `fs.query.qCapEntity`, `fs.query.qNonCapEntity` | missing | partial | Finite extrusion, native Part revolve, supported loft and sweep caps; full revolution has no caps. Arbitrary PartDesign revolution axes, non-normal sweep profiles and unsupported cap curves reject |
| `fs.query.qOwnedByBody`, `fs.query.qEntityFilter`, `fs.query.qGeometry` | partial / missing | implemented | Stable ownership, face/edge/vertex type, supported native geometry filters |
| `fs.query.qUnion`, `fs.query.qIntersection`, `fs.query.qSubtraction` | missing | implemented | Set algebra over current native entity identities |
| `fs.query.qAdjacent`, `fs.query.qTangentConnectedEdges`, `fs.query.qParallelPlanes` | missing | implemented | Native incidence, tangent chain, parallel direction; closest-point retains ties rather than choosing an index |
| `fs.query.qLoopEdges` | missing | partial | Adjacency and tangent traversal are available; no dedicated loop-boundary query |
| `fs.query.qNthElement` | missing | intentionally excluded | No index-based selector or nth-element fallback; explicit legacy native references remain supported |

## Evidence and remaining targets

The [carrier decision](PART_MODEL_DECISION.md) compares both carriers on the 30-operation/four-part native fixture, persistence, editability, topology history and rebuild cost. [Operation contract](OPERATION_CONTRACT.md) gives exact typed schemas and failure behavior; [hands-on walkthrough](U2_WALKTHROUGH.md) covers the new tools. Offline native suites include legacy STEP/Assembly regressions plus part-studio, selector and native-consumer tests. The isolated U2 GUI runner exercises real controls, modal previews, parts, rollback and health, with rendered screenshots under `validation/u2-part-model`.

Final acceptance passes 141 native tests, 4 bridge tests, 22 shortcut tests and 99 actual U2 GUI checks; the existing interface regression also passed 106 checks. Offline/U2 GUI source snapshots remain unchanged during their runs. The final small 30-feature/four-part query fixture measured median 293 ms selector evaluation and 431 ms total rebuild across five forced runs, with 11 selector consumers. Native creator ancestry survives a genuinely fresh-process reopen and forced rebuild, including copy, move, pattern and mirror. Reports are under `validation/u2-selector-consumers` and `validation/u2-selector-performance`.

The local pipe-mount FeatureScript's three New extrusions, later Add/Remove, part mirror and feature mirror establish why this model is needed. U2 can express its whole-part/scoped-operation structure, but does not reconstruct all 28 historical features or resolve their source queries. The hub's 145 features/configurations remain a U5 target. Frozen bodydetails/STEP topology captures are absent from this workspace; no Onshape API calls were spent. Full Dodec parametric conversions remain **0/2**. Configurations, source query translation, full feature/face patterns and unsupported split/end cases remain explicit work.
