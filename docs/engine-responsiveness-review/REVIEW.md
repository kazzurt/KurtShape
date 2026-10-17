# KurtShape engine and responsiveness review

October 5, 2026, America/Los_Angeles. Review of the current `Codex/kurtshape` working tree, based on commit `559e034` plus the uncommitted October 4–5 workflow and presentation changes. FreeCAD 1.1.4 / OCCT 7.8.1. Requested scope: sketching, picking/tool behavior, previews/edits, and viewport responsiveness.

**Recommendation.** Make responsive modeling the next milestone. The app needs substantial changes to its command, preview, document-indexing and presentation machinery. Keep the current native modeling/document foundation while doing that work, and evaluate a runtime upgrade against measured remaining geometry bottlenecks. The evidence does not justify assuming a new kernel would fix the whole experience. It also does not justify claiming the native engine is already fast enough for all models.

This review changes no application implementation. It includes source inspection, three independent subsystem reviews, official Onshape/FreeCAD/OCCT documentation, and isolated native benchmarks. The running user session and source projects were not used. No side-by-side Onshape latency test or current viewport frame-time capture was performed.

**What “engine” means here.** KurtShape has several relevant layers: OCCT constructs and modifies precise geometry; FreeCAD supplies document dependencies, native features, Sketcher, undo and persistence; KurtShape coordinates multi-part history, references, tool sessions and summaries; Qt/Coin/FreeCAD render and handle input. Slow or awkward behavior in any of those layers can feel like a slow engine. Improvements must identify which layer owns each delay.

**Current measurements.** The fresh Plate60 run used the existing native benchmark, `measure=false`, three repetitions and a private profile. It exercised a 600 × 600 mm plate with 60 separate holes, 132 native objects and 66 final faces. Timings below are medians, in milliseconds. They exclude Qt input, first paint and Coin overlay rendering, and must not be presented as direct onscreen response times.

| Plate60 operation | Current run median, ms | Largest of three samples, ms |
|---|---:|---:|
| Edit last hole, complete controller operation | 513.1 | 515.7 |
| Native recompute within that edit | 426.9 | 445.6 |
| Non-native-recompute overhead within that edit | 85.0 | 86.2 |
| Edit upstream plate thickness, complete operation | 8,859.4 | 9,332.7 |
| Native recompute within upstream edit | 8,767.6 | 9,266.0 |
| Inspection, unchanged document | 37.5 | 44.3 |
| Inspection after native change | 48.4 | 60.1 |
| Forced recovery checkpoint | 1,683.7 | 1,930.7 |
| First exact extrusion preview | 8,995.9 | 9,694.6 |
| Change preview depth | 7,175.1 | 7,506.6 |

Component medians do not necessarily sum to the total median because they are calculated independently. Three samples establish the order of magnitude, not a reliable tail-latency distribution. This is not a paired before/after performance study; differences from Q03 do not establish a regression. Native and managed opening both completed around 1.8–1.9 seconds with zero measured modeled-feature recompute; ordering/cache noise makes their difference unsuitable as an overhead estimate.

The fresh multi-part run used the same current source, policy and three repetitions. Its fixture contains 30 base features, four parts, eleven selector consumers and two scoped operations; the built document reports 34 Studio features and 162 native objects.

| Multi-part operation | Current run median, ms | Largest of three samples, ms |
|---|---:|---:|
| Automatic-scope profile edit, 1↔4 target parts | 3,720.3 | 4,291.4 |
| Native recompute within that scope edit | 284.5 | 334.8 |
| Non-native-recompute overhead within that scope edit | 3,491.4 | 3,956.6 |
| Upstream edit, complete operation | 3,152.7 | 3,395.6 |
| Inspection, unchanged document | 390.1 | 409.3 |
| Inspection after native change | 1,404.8 | 1,423.7 |
| Forced recovery checkpoint | 584.1 | 635.8 |
| First exact extrusion preview | 2,574.5 | 2,637.8 |
| Change preview depth | 2,413.8 | 2,633.1 |
| Complete rebuild operation | 1,248.4 | 1,534.2 |

This demonstrates two different bottlenecks: native recomputation dominates the plate's upstream edit, while work outside timed native recomputation dominates the multi-part automatic-scope edit. The benchmark labels the latter `tip_edit`, but it changes `BenchAutoProfile.Width` between 5 and 125 mm and verifies that scope changes between one and four target parts. It is more demanding than a simple single-feature dimension change. The overhead category includes orchestration and exact query/scope geometry work outside `doc.recompute`; it is not all pure Python or UI rendering. Repeated explicit rebuild is a different workload without the same scope/topology change, so its lower time does not by itself localize the edit overhead.

Raw evidence: [Plate60 benchmark](evidence/plate60-benchmark.json), [multi-part benchmark](evidence/studio-benchmark.json), and the corresponding [plate](evidence/plate60-source-manifest.json) and [studio](evidence/studio-source-manifest.json) source manifests. Both runs completed all requested sections; 43 source/benchmark files were verified unchanged against each run's manifest afterward. The retained [post-run verification](evidence/source-verification.json) records the expected and actual hashes.

The October 4 Q03 multi-part timings were materially slower than this run. Different working-tree state, run conditions and fixture object counts prevent attributing that difference to a particular improvement. Its diagnostic profile remains useful supporting context: 6.674 seconds in Body enumeration and 3.161 seconds in ownership matching, versus 1.220 seconds in native recomputation across the profiled workload. Those historical profile totals are not individual edit timings or a current breakdown. See [Q03 evidence](../long-run/Q03-fast-status-geometry-open.md).

**Finding 1: exact preview is serving as the immediate interaction response.** `ExtrusionEvaluator.evaluate` snapshots the live document when necessary, opens a temporary FCStd clone, creates the real native operation, reconciles the Studio, recomputes, checks build status and calculates the exact material difference. It closes the clone after returning detached geometry. The result cache holds eight proposals; changing to a new depth still requires evaluation. This is robust source isolation, but expensive for an interaction repeated while typing. See [extrusion_preview.py](../../src/kurtshape/extrusion_preview.py), lines 185–298.

`DebouncedExtrusionPreview` adds 160 ms before evaluation. On changed input it clears the old ghost; the UI disables confirmation until a fresh verdict returns. Evaluation, tessellation, edge discretization and overlay creation then run synchronously on the GUI thread. Confirm eventually performs the real operation again in the authoritative document. A cache hit can save geometry evaluation without eliminating overlay reconstruction or final commit. See the same module, lines 315–491, and [ui.py](../../src/kurtshape/ui.py), lines 2155–2164 and 2738–2792.

Provide a cheap provisional visual response for supported profiles immediately, then refine it with exact evaluation. A simple extrusion can often reuse the profile mesh and change its depth; boolean scope, up-to-face, fillets and shells need their own strategies. Make approximate versus exact state visible. Keep exact revision-checked validation for commitment. The current queue's Q07 already aims at this missing architectural change; Q25 tested clone/cache safety and did not implement it.

**Finding 2: multi-part bookkeeping repeatedly rediscovers the same document structure.** [bodies.py](../../src/kurtshape/bodies.py), lines 5–13, scans all document objects to find Bodies and scans their membership for each ownership lookup. [studio.py](../../src/kurtshape/studio.py), lines 249–267 and 304–317, repeatedly rebuilds history-prefix part states and active membership. Preparation and validation repeat these operations for individual features.

Inspection constructs all feature rows, parameters, dependencies, expressions, sketch data, active flags and result summaries again ([core.py](../../src/kurtshape/core.py), lines 746–820). Dirty intent still triggers whole-document serialization/hashing, including authored sketch content. The observer has useful generation/version data, but the authored-intent layer primarily exposes one dirty flag.

Add transient indexes for object ownership, history positions, active results and prefix states. Cache authored intent and summaries per object, invalidate only affected data, and send deltas to the UI. Retain full reconciliation for open, undo, unknown native edits or suspected invalidation gaps. These indexes describe FCStd; they should not become a competing editable model. This is the clearest supported reason to prioritize Q11 and the remaining Q27 ownership work.

**Finding 3: query-backed references broaden the regeneration workload.** With no active stored selector consumers, `selectors.recompute` delegates one recompute to FreeCAD. With consumers in a transaction, it walks the dependencies of every document object, refreshes consumer queries and calls `doc.recompute([obj])` per visited object ([selectors.py](../../src/kurtshape/selectors.py), lines 985–1032). FreeCAD can still skip unchanged native execution, so this is not proof that every feature is geometrically rebuilt. It does prove the orchestration traverses the entire document.

Each input resolution builds a new query context, scans object element maps and constructs result face/edge/vertex records (lines 240–274, 729–735 and 937–944). Pairwise geometry memoization does not remove that indexing cost. Use shared versioned contexts, lazy entity enumeration and a dirty consumer/dependency scheduler. Batch proven-safe native recompute stages. Some intermediate recomputes materialize a shape needed by the next feature; removing all of them blindly would break dependencies.

**Finding 4: recent presentation improvements still consume the input thread while idle or hovering.** `Panel.tick` fires every 25 ms. It applies sketch history, point colors, region visibility and plane visibility before the unchanged-document early return ([ui.py](../../src/kurtshape/ui.py), lines 179–181 and 1105–1147). Point coloring reconstructs geometry/constraint/dependency signatures and searches scene nodes even when no new material writes are needed ([sketch_colors.py](../../src/kurtshape/sketch_colors.py), lines 121–135 and 178–205). Region face construction is correctly dirty-driven, but region visibility still walks document objects. “No idle writes” is weaker than “negligible idle work.”

Face hover performs native picking on mouse movement. On a new face it copies the face, discretizes its boundaries, searches native selection nodes and builds an overlay. Only the currently hovered face is cached ([hover_outline.py](../../src/kurtshape/hover_outline.py), lines 77–99 and 172–189). Moving back and forth can repeat that work.

Cache overlay geometry and scene bindings by shape generation/placement, coalesce hover work per frame, and drive presentation updates from model/selection/editor events. Keep a slow reconciliation fallback for native integration. These are source-backed performance candidates, not proven causes of a particular dropped orbit frame. Measure event-loop delay, CPU/GPU frame times, triangle counts and picking time before choosing a renderer replacement or lowering display quality.

**Finding 5: tool behavior has several owners.** Custom feature panels, the older extrusion task, native workbench task dialogs, native Sketcher and global shortcut handlers have separate state. `Panel` reconciles `task`, `studio_dialog`, `entering_sketch`, `finishing_sketch`, document/revision ownership and native `getInEdit()/activeDialog()` state. Its periodic loop can close a feature task when the revision changes, restore the active sketch's document, or finish a disappeared native editor. These guards protect data but also demonstrate the integration burden.

Create one tool-session coordinator with explicit phase, selected input role, provisional parameters, document instance/revision, preview generation, native edit lease and accept/cancel/undo rules. Give the toolbar, keyboard and assistant the same operation descriptors. Keep native Sketcher behind an adapter while unifying picking, repeat-tool behavior, focus restoration and error handling. A shared modeless panel is a useful start; common appearance alone does not make behavior consistent.

Every accepted operation also clears and reconstructs feature and part trees before restoring selection/expansion ([ui.py](../../src/kurtshape/ui.py), lines 1310–1437). A persistent Qt model with stable row IDs and delta updates would reduce both work and state-restoration complexity.

**Finding 6: background work is still foreground work.** Recovery calls native `saveCopy`, checks the ZIP, reads and hashes the file, and replaces the snapshot/manifest pair synchronously ([recovery.py](../../src/kurtshape/recovery.py), lines 20–49). The timer checks periodically; unchanged revisions and the ordinary 30-second interval suppress many captures. The measured 1.7-second forced capture therefore does not mean it freezes every second, but it can explain intermittent pauses after changes. Save, import and export also remain synchronous.

Finish idle recovery and move pure file verification/hashing off the GUI thread. Use separate native processes for heavy CAD work on private snapshots when that preserves semantics. A Python thread touching live FreeCAD objects is not a safe or sufficient substitute. Process workers do not remove the cost of taking a native snapshot, committing a native feature, solving the active Sketcher or uploading/drawing the returned mesh. Those costs need separate measurement and design.

**Finding 7: responsiveness instrumentation currently hides some of the evidence we need.** `feedback_complete` discards durations of five seconds or more. Its global timestamp is overwritten on key/mouse input, and `notify` records completion before setting the notification text ([ui.py](../../src/kurtshape/ui.py), lines 604–609, 2325–2332 and 3188–3190). It is neither command-correlated latency nor input-to-present timing.

Record command/session-correlated input acknowledgment, provisional preview, exact preview, committed result and presented frame separately. Retain long stalls, cancellations and failures. Add event-loop stall traces and per-feature recompute times. Measure enough interactions for useful percentiles. Existing tests are valuable correctness evidence; they do not certify comfortable interaction. The benchmark regression gate can pass with an unmet absolute latency target because it also requires a confirmed historical regression before failing. Keep correctness, regression and absolute responsiveness gates distinct.

**What Onshape provides as a comparison.** Onshape's published architecture separates geometry computation from a client that renders triangles and handles interaction; its geometry servers use Parasolid and D-Cubed. This 2018 explanation is architectural context, not a complete current implementation specification. The useful lesson for a local app is separation of interaction from long computations; it does not require adopting cloud storage or networking. [Onshape architecture](https://www.onshape.com/en/blog/how-does-onshape-really-work).

Onshape's current Performance Panel separates feature regeneration, assembly mate solve and graphics/tessellation statistics. KurtShape needs similarly distinguishable observations. [Official Performance Panel documentation](https://cad.onshape.com/help/Content/Home/performance_panel.htm). FeatureScript exposes query-based references, including robust identity-preserving and split/merge-aware query tools. KurtShape's declarative selectors pursue a useful related goal, but its present scheduling/indexing and operation coverage are narrower. This comparison does not establish equal reference robustness. [FeatureScript query documentation](https://cad.onshape.com/FsDoc/library.html#makeRobustQuery-Context-Query).

**How far to upgrade the engine.** Three options deserve different treatment:

| Option | What it could improve | Main limitation | Recommendation |
|---|---|---|---|
| Refactor KurtShape on current FreeCAD | Preview feedback, status/indexing, tool consistency, idle/hover work | Native solve and committed recompute can still block | Start here |
| Test a newer compatible native runtime | Native modeling defects, some geometry/recompute costs, selected native UI defects | Compatibility and topology/reference behavior need proof | Bounded comparison after isolating native bottlenecks |
| Replace the kernel or build a separate custom CAD application | Greater control of evaluation, rendering and interaction contracts | Must replace/integrate native features, Sketcher, naming, undo, files and editing | Consider only against named blockers and a representative prototype |

There are real native bottlenecks: the current upstream Plate60 edit spends about 8.77 of 8.86 seconds in native recomputation. That timing includes FreeCAD's native feature/document machinery and OCCT; it does not isolate OCCT alone. Profile the costly features, feature-history structure, boolean/pattern choices and native recompute boundaries before deciding which native component to replace.

Runtime upgrades are not drop-in here. Creator queries explicitly require FreeCAD 1.1.4, and the decoder interprets its native element-history grammar; the Studio uses `UseHasher=false` to retain ancestry ([selectors.py](../../src/kurtshape/selectors.py), lines 140–175 and 360–362; [part-model decision](../PART_MODEL_DECISION.md)). Put that interpretation behind a versioned native adapter first. Official OCCT releases now include 8.x with substantial API/build changes, which is reason to test a compatible application build, not swap DLLs into the existing runtime. [OCCT releases](https://github.com/Open-Cascade-SAS/OCCT/releases). FreeCAD also documents continuing topological-naming mitigation; an upgrade is not a blanket guarantee of reference stability. [FreeCAD 1.1 notes](https://freecad.github.io/Website/download/releases/1-1/).

The deferred native Sketcher endpoint-diagnosis fix already recorded in project continuity remains a separate, useful narrow upstream patch candidate. This review does not resume that implementation or infer that a major fork is necessary.

**Recommended next milestone.** Freeze broad feature expansion long enough to deliver a measurable responsive modeling slice:

1. Add honest interaction tracing and reproduce one representative workflow on Plate60, the multi-part query fixture, and an editable real design. Preserve the current working tree's provenance. Establish action counts/focus errors as well as speed.
2. Implement immediate preview feedback and reusable render geometry; remove whole-document clone work from the simple visual update path. Build ownership/history/summary indexes in parallel, then selective query regeneration.
3. Replace frequent presentation polling and full tree reconstruction with event-driven updates. Unify tool-session and selection ownership while doing it.
4. Finish idle recovery and introduce a bounded process-worker service for exact disposable evaluation/exchange where appropriate. Tag every result with document instance, session, revision and proposal sequence; discard stale results and coalesce queued proposals.
5. Reprofile native commit and Sketcher. Compare a compatible runtime or feature strategy only against the remaining demonstrated bottlenecks. Moving the authoritative engine into another process is a later architecture decision because native Sketcher currently couples solve, rendering and edit handlers tightly.

Proposed acceptance targets, not current guarantees: visible input acknowledgment within 50 ms at p95; provisional simple preview within 100 ms initially, with a 50 ms stretch target; interactive orbit targeting a 16.7 ms frame budget at a fixed resolution/model/display quality; no recurring background GUI task over 50 ms during ordinary interaction. Long exact calculations must expose progress and preserve navigation/cancellation where the architecture allows it. Exact preview and commit have separate per-fixture budgets; do not silently exclude hard cases or label approximate geometry accepted.

Also require predictable tool-first and selection-first flows, one understandable undo step, no lost draft on failure, and a hands-on modeling session. The two supplied Onshape designs remain 0/2 fully reconstructed native parametric histories; STEP geometry checks alone do not prove behavior on their 28- and 145-feature source histories. See [conversion coverage](../CONVERSION_COVERAGE.md).

**Preserve the work that is already sound.** Q03 removed expensive automatic BRep checking from ordinary status and enabled stored-shape opening. Q25 verified preview lifecycle safety. The current native document authority, explicit revisions, source-safe previews, undo/draft preservation, guarded exports, modeless panels and mapped sketch references are assets to keep. The next step is to make those mechanisms cheaper and better coordinated.

**Reproduction and continuity.** [run-review-benchmark.ps1](run-review-benchmark.ps1) invokes the existing isolated native runner with `--measure false`; pass `-Fixture plate -Holes 60 -Repeat 3` or `-Fixture studio -Repeat 3`. It uses a fresh descriptive directory under `runtime/engine-responsiveness-review-working`, captures source SHA256 hashes and retains its synthetic FCStd fixtures/logs. Raw reports and manifests are retained beside this review under `evidence/` after each completed run. The JSON `passed` flag means requested benchmark sections completed, not that responsiveness targets were met. Application code was not changed as part of the audit. The next implementation step is the bounded responsiveness milestone above, subject to the user's choice after this review.
