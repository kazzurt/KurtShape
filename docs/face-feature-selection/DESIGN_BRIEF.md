# Face selection → last modifier in the design tree

Status: implemented 2026-10-20; selection interaction revised with Kurt's approval
on 2026-10-21. Kurt confirmed the interaction fixes and requested publication
on 2026-10-21.
Target: KurtShape's existing native Qt Part Studio, FreeCAD 1.1.4 / OCCT 7.8.1.
Mode: Operate. Preserve the compact history tree and existing design system.

## Intended behavior

When Kurt selects a face in the graphics window, reveal and mark the feature
in the design tree that last changed that face. Keep the face selected so it
remains usable by subsequent modeling commands.

“Last” means feature order in the evaluated model, not the most recent feature
edited by the user. “Changed” includes changing the bounded face's surface,
outer boundary, or holes, and splitting or merging it. Merely carrying an
unchanged face through a later result does not make that result its modifier.

| Selected face | Feature to mark |
| --- | --- |
| Untouched face of an extruded block | Original extrusion |
| Block's top face after a pocket cuts a hole through it | Pocket |
| Cylindrical wall made by that pocket | Pocket |
| New rounded face, or neighboring face trimmed by a fillet | Fillet |
| Face modified by a later cut after that fillet | Later cut |
| Face merged from two inputs by a Boolean | Boolean that merged it |
| New copy made by a pattern or mirror | Pattern or mirror |
| Unchanged original face retained by a pattern | Its earlier modifier |
| Face moved by a Part Studio transform | Transform |
| Untouched face of an imported STEP solid | Import/base feature, with “Earlier history unavailable” |

These are the behavior requirements; operation coverage and evidence are
recorded below.

## Interaction

- Enable this behavior by default for deliberate face selection in an idle
  Part Studio. Hover retains ordinary preselection without moving the tree.
- Highlight the matching row with ordinary tree selection styling. Do not show
  a “Last modifier” label or badge. Retain accessible text and a feature tooltip.
- Reveal the row with the minimum necessary scroll and expand its ancestors.
  Keep keyboard focus in the graphics window. Do not open an editor or change
  the active part, rollback position, visibility, camera, or native face pick.
- Replace the old Qt selected/current row when a face selects another feature.
  Block tree signals while doing so to keep the native face selected. Clearing
  native selection clears selected/current rows. Deliberate whole-feature tree
  selections retain their normal command behavior.
- Clicking the marked row deliberately selects the feature using the existing
  tree behavior; double-clicking retains the existing editing behavior.
- With Ctrl multi-selection, mark each distinct last modifier. Scroll only
  for the newly added face. Removing a face updates markers without scrolling;
  clearing face selection clears all linked markers.
- Preserve a typed feature filter. If it hides the matching row, show a Reveal
  button. Reveal explicitly clears the filter and shows the highlighted row.
- Sketch editing, armed reference fields, section-plane picking, native Tasks,
  previews, and active modeling tools keep their selection priority. Suspend
  automatic tree navigation and clear linked markers for those modes; resolve
  any surviving face selection again on return to idle.
- Clear on document switch/close or invalidated face selection. After a model
  change, undo, redo, or rollback, discard stale results and resolve surviving
  picks against the current evaluated state. Do not scroll on these refreshes.

Assembly face selection keeps its existing occurrence behavior in the first
release. Embedded snapshots must not imply access to the source part's feature
history. Edges and vertices are outside this initial feature.

## Resolution and integration

Use a separate read-only face-history resolver. Preserve the existing
`created_by` selector's creator semantics: its tests deliberately distinguish
creation from a later one-to-one trim.

1. Capture the document identity, current geometry generation, selected result
   and exact face path. Resolve a Body pick to its displayed result, accounting
   for wrappers and placement without changing the document.
2. Walk the actual operation boundaries: recorded Part Studio input-part IDs
   and their historical results, or a native feature's Base/BaseFeature and
   preceding Body solid. Use Part Studio order, never document object
   allocation order or the highest feature number. Preserve merged branches.
3. Find the latest operation whose input solids do not contain an equivalent
   complete bounded face. Acceptance of pass-through requires full native
   face-intersection coverage and full physical boundary-curve overlap with matching
   physical normals (linear tolerance 1e-7 mm). Areas and bounding boxes only
   reject candidates. Do not infer lineage from nearest face, area, center,
   bounding box, or normal alone. Copies are new occurrences; identity
   transforms of an existing part retain earlier attribution. Periodic
   parameterization seams are excluded from physical boundary comparisons.
4. Normalize internal tools/results to their user-visible operation through
   `KurtShapeOperationOwner`. Return a resolved feature ID and reason, an
   ambiguous candidate set, or unavailable with a reason. Only a uniquely
   supported result receives a last-modifier marker.
5. Coalesce selection callbacks and cache by document, geometry generation,
   result identity and exact face identity. Invalidate on any relevant native
   model change, including undo/redo. Discard work completed for an obsolete
   selection or generation. A click must never trigger a rebuild or alter
   `UseHasher`, model properties, document revision, dirty state, or Undo.

Integrate selection add/remove/clear handling beside `SelectionObserver` in
`src/kurtshape/ui.py`, retaining existing picker priority. Maintain linked IDs
separately in `history_selection.py`; render them through `HistoryDelegate`
and reapply them after `HistoryModel` reconciliation. Do not route this through
`sync_native_selection()`, which clears face picks and selects whole objects.

Keep expensive history preparation off the click path where practical. Start
with a bounded resolver spike on small native fixtures; measure both cold and
cached clicks on a larger history before choosing a latency budget. Never
recompute model geometry to prepare provenance.

## Missing or ambiguous history

When exact history is missing, unsupported, stale or ambiguous, keep the face
selection usable and clear the old history highlight. Do not choose the
latest feature as a fallback. For ambiguous history, diagnostic details may
list candidates without presenting one as the answer.

Native element maps are not universally reliable. Existing probes show that
`getElementHistory()` includes downstream operations on untouched faces, and
some refined results have missing branches or invalid face mappings. Hashed
names and unsupported native operation grammars also need explicit coverage.
The implemented resolver therefore uses recorded predecessor solids rather
than depending on modification-marker parsing. Native Hole and tested refined
Booleans work through complete face comparisons. Missing or unsupported
operation boundaries, unavailable predecessor results and failed equivalence
proofs still return unavailable.

## Implementation gates

1. Prove the resolver on extrusion → pocket → fillet fixtures, distinguishing
   untouched faces from newly generated and one-to-one trimmed faces. Include
   a later upstream dimension edit to prove model order, not edit time, wins.
2. Add split/merge/refine, native Hole, transform, pattern/mirror, multi-part
   Boolean, imported base and unsupported-history fixtures. Test the actual
   public operation paths and helper-to-visible-operation attribution. Unknown
   cases must return unavailable until their adapters are verified.
3. Verify edit/rebuild, rollback, undo/redo and save/reopen invalidate or rebuild
   the transient cache correctly, including part placement and face renumbering.
4. Validate the real Qt behavior in a private hidden session through code:
   linked marker/reveal/filter behavior, multi-picks, clearing, tool priority,
   unchanged native face selection and focus, and no unintended Delete target.
   Assert unchanged revision, dirty state, visibility, camera and Undo count.
5. Run the applicable native/GUI checks and review the marker's contrast at
   normal and enlarged Windows scaling. Do not access Kurt's live window or
   restart his app. Loading an implemented change later needs a new app process.

Implementation: `src/kurtshape/face_provenance.py` owns the read-only resolver;
`face_history_links.py` owns transient selection linking and feedback;
`history_selection.py` retains normal tree selection rendering; `ui.py` connects native
selection callbacks, tool priority and generation invalidation. No model
properties or persisted face maps were added. The existing `created_by`
selector is unchanged.

## Source evidence reviewed

- `src/kurtshape/ui.py`: `SelectionObserver`, `capture_feature_selection`,
  `geometry_references`, `history_selection`, and `filter_features`.
- `src/kurtshape/history_selection.py`: `HistoryDelegate`, `HistorySelection`,
  `sync_native_selection`, and feature deletion.
- `src/kurtshape/history_model.py`: identity-based reconciliation and retained
  selection/current-row/scroll state.
- `src/kurtshape/selectors.py`: `result_source`, mapped-name decoding,
  `lineage`, `creators`, and unsupported-history checks.
- `tests/test_selectors.py`: original creator versus pocket trim, split faces,
  and Boolean merged faces.
- `tools/probe_query_history.py`: downstream-history false attribution and
  native refinement mapping limitations.

The feature received an independent provenance/interaction review. Native
tests are registered as `test_face_provenance.FaceProvenanceTests`; hidden Qt
acceptance runs with `tools/run_gui_recipe.ps1 -Recipe face-feature-selection`.
The implementation record and final evidence below supersede the initial
planning-only status. Kurt's running app and documents were never accessed.

## Verification record (FreeCAD 1.1.4 / OCCT 7.8.1)

- Regression: **1,051 passed, five optional performance cases skipped**, across
  the full run and an isolated bridge rerun against identical application
  source. Native modeling was 938 passed/five skipped; bridge 73 passed;
  shortcuts 34 passed; six workflows passed 415 checks. All 16 new resolver
  cases passed. Every suite verified unchanged source. See the durable
  [regression summary](evidence/regression-summary.json).
- Hidden GUI acceptance: **86 checks passed in 14.43 s**, including full
  model/revision/Undo/dirty/camera/appearance equality, face/tree selection and
  focus preservation, auto-scroll, filtering/Reveal, accessibility, multi-picks,
  unknown/ambiguous feedback, actual Cut and Section View routing, undo,
  recompute and document switching. See [the complete checks and source
  hashes](evidence/hidden-gui-acceptance.json) and [normal owned-process
  exit](evidence/hidden-gui-process.json). An independent [confirmation
  run](evidence/hidden-gui-confirmation.json) passed the same 86 checks in
  15.32 s with unchanged sources and [normal process
  exit](evidence/hidden-gui-confirmation-process.json). Both private processes
  were closed; neither final run recorded a state mismatch.
- Focused resolver suite: 16/16 cases passed in 9.58 s. The 27-history-entry,
  13-solid-operation, 30-face fixture measured 149 ms for a cold unchanged-face
  lookup and 0.036 ms for cached lookups. These are local fixture measurements,
  not a latency guarantee for arbitrary large parts. The same measurement
  within the full suite was 317 ms cold/0.084 ms cached; its raw measurements
  are retained in [resolver-performance.json](evidence/resolver-performance.json).
- Changed Python/macro files pass Ruff. Repository-wide Ruff reports 16
  existing unused imports/variables in unrelated files; none were changed.
- `run-checks.ps1` now uses bundled `pythonw.exe` with its existing redirected
  process logs, following the standing no-console rule. Raw native and hidden
  GUI reports remain in isolated runtime sessions; final evidence is linked
  from the verification summary in this directory.

The first full run had 53 bridge nonpasses under sandbox restrictions:
loopback sockets were denied (`WinError 10013`) and an owned child-process
cleanup check failed. Rerunning the complete bridge suite with private
loopback/process access passed 73/73, including that cleanup check. The raw
failed full report was retained rather than rewritten; the summary identifies
the independent confirmation and matching application-source digest.

Restricted GUI attempts were much slower and hit the original 90 s bound. One
longer attempt reached 83 checks and failed the complete post-Undo state
snapshot; that version did not record the differing fields, so its cause is
unconfirmed. Diagnostics were added without changing application code or
assertions, and two private unrestricted runs passed all 86 checks in 14.43 s
and 15.32 s, including the exact post-Undo state comparison.
The recipe now allows 180 s internally/240 s in its runner for host load. Keep
GUI acceptance separate from the heavy native suite and retain the earlier
failed reports under `runtime/ci-gui/face-feature-selection/` as evidence of
this nonreproduced test failure.

Reproduce the native cases with `tools/run_native_tests.py --require-native
--only test_face_provenance.FaceProvenanceTests` under the isolated environment
used by `run-checks.ps1`. Run the actual Qt acceptance with
`tools/run_gui_recipe.ps1 -Recipe face-feature-selection -TimeoutSeconds 240`.
The recipe uses native `Gui.Selection` picks, actual tree scrolling and the
Reveal button, with no screen capture or rendered-pixel mouse hit tests.
