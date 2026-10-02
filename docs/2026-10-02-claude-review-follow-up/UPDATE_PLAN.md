# KurtShape update plan after Claude's October 2 review

Prepared October 2, 2026, America/Los_Angeles. **Proposed sequence; implementation has not started under this review request.** This plan supplements the existing M1 scope. It does not mark M1 complete, change the foundation decision, or assign Claude work.

Inputs: [Claude's review](../../../../Claude/reviews/2026-10-02_kurtshape-app-review.md), the current app, tests and validation records, [M1 execution plan](../../../cadkz-project-planning/M1_EXECUTION_PLAN.md), and [project continuity](../M1_PROGRESS.md). [Review evidence](REVIEW_EVIDENCE.md) distinguishes code findings, existing recorded results and the small probe run for this assessment. [Response to Claude](RESPONSE_TO_CLAUDE.md) gives the qualifications and answers his questions.

## Recommendation

Keep FreeCAD 1.1.4 / OCCT 7.8.1 and native FCStd. Address the five immediate issues before asking Kurt to assess normal modeling comfort. Prioritize preservation of sketch work first, then idle performance. Include useful errors, command-based sketch undo, timing and a minimal shortcut override layer in that same readiness pass. These directly affect the test's usefulness.

Follow with reliable assistant retries and isolated preview, then explicit body selection and unmanaged-document adoption before source conversion. MCP preparation and kernel fixtures can proceed against documented interfaces if Kurt accepts the proposed collaboration split. Source migration stays at **0/2** until its separate gates pass.

No dates or broad feature-parity promise: each increment ends with reviewable changes and evidence. A failed gate leads to a specific repair or scope decision.

## Increment 0 — establish a reproducible baseline

Initialize an application-scoped Git repository at `Codex/kurtshape`, after checking the intended file set. Commit app source, tools, tests, docs, pinned runtime installation/hash recipe, curated native fixtures and small acceptance reports. Exclude the portable runtime, session credentials, caches, temporary configs, recovery copies and generated scratch artifacts. Keep reproducible recipes for larger evidence. Preserve `Claude/` and original `Onshape examples/` in place.

Record the app baseline commit and runtime versions in subsequent validation reports. Use small commits organized by the increments below. Update `M1_PROGRESS.md` at meaningful milestones; update operation/sketch contracts in the same commit as behavior changes. Historical plans and results remain historical evidence.

**Gate:** a clean baseline commit and documented regeneration of excluded material. No remote repository or public publishing is required.

## Increment 1 — make the hands-on test safe and representative

### 1A. Preserve work on failed Finish — findings 2 and 9

Change `core.py`'s lease failure handling and `ui.py`'s finish paths together. Ordinary typed operations outside a sketch lease retain reject-and-rollback behavior. Within a lease, reject an invalid typed edit without destroying the user's earlier draft; a failed Finish retains the current sketch, its initial Cancel checkpoint and its edit history.

Treat the lease as a session that can survive native transaction commits, rather than assuming one transaction stays open. Capture the current native buffer before `resetEdit` and before history grouping. Validate before destructive grouping. If finalization or grouped recomputation fails, restore the current draft, retain the lease and reopen the editor. If unrelated native history crossed the checkpoint, report it and preserve a recoverable draft rather than undo unrelated accepted features.

Show persistent solver/rebuild errors in the editor with **Continue editing** and **Cancel sketch**. Explicit Cancel restores the accepted starting state; successful Finish still creates one document undo step. Keep failed/retained geometry clearly labeled and block export. Do not add a separate "accept failed feature" workflow in this first fix.

Apply the same preservation behavior to the toolbar Finish, native Tasks Close, extrusion launched from a sketch, and app-window close. A rejected close leaves the draft available. Guard automatic finalization so the timer does not repeatedly attempt Finish or loop between closing and reopening the editor.

Add a persistent Messages area. Capture native errors through a supported mechanism verified in the pinned runtime; showing the native Report view on errors is an acceptable first implementation. Keep unexpected-exception tracebacks in a local log and correlate them with the operation. Avoid re-hiding the error display immediately after `Gui.runCommand`.

**Gate:** draw several entities, add a conflicting constraint, try each Finish path, remove the conflict and finish successfully. The draft survives each failure; Cancel alone discards it; successful Finish undoes/redoes as one step. Cover native `resetEdit` auto-commit, downstream rebuild failure, failed grouping, and an invalid typed edit midway through a longer draft. Replace both failed-finish rollback expectations in `test_sketch_planes.py`, while retaining explicit Cancel and external-history protections. Exercise actual native GUI paths in an isolated hidden validation instance.

### 1B. Remove idle document scanning and fix undo boundaries — findings 1 and 11

Add a controller-owned document observer for object/property changes, creation/deletion, recompute, transactions, undo/redo and document lifecycle. The existing `GeneralActions` observer handles tab lifecycle only. Observer callbacks should mark state dirty and schedule/coalesce work; they should not serialize the whole model or recompute it.

Separate modeling-intent changes from evaluated-shape and view changes. Exclude KurtShape's own revision/status metadata from invalidation loops. Preserve the exact native signature as the correctness check, computed when relevant state is dirty and before a revision-dependent operation. An immediate assistant request after a native edit must flush dirty intent before checking `expected_revision`; it must not wait for the next UI refresh.

Cache validity and measurements by native document/body and evaluation generation. Invalidate on relevant Shape replacement, recompute, undo/redo and reopen. Use `hashCode()` only as an additional diagnostic, not the sole cache key or evidence of equivalent geometry. A touched feature must immediately yield `needs_rebuild`, even while previous geometry remains cached. Export must verify it is using current evaluated geometry.

Use cached inspection for unchanged panels. Keep a lightweight queue/lifecycle service timer, with queue wakeup or a shorter cheap service interval so assistant calls do not inherit a 350 ms wait. Benchmark the interval; maintain serialized GUI-thread mutations. Do not move a live native document to a worker thread as part of this fix.

Record sketch snapshots at completed typed commands and verified native command/transaction boundaries. Use transaction notifications and gesture completion where needed; a change in `UndoNames` alone is insufficient while commands share a pending transaction. Coalesce a drag into one undo action without losing separate drawing commands. Signature flushing for stale-client rejection must not itself create undo entries.

**Gate:** after cache warm-up, 30 seconds of idle timer service causes zero full intent serializations and zero repeated solid-validity checks. Native dimensions, spline pole changes, construction flags, deletion, undo/redo and reopen still invalidate stale requests correctly. View/selection changes do not invalidate modeling revisions. One drag is one sketch undo step; successive tools remain independently undoable; completed Finish remains one document step. Validate native recompute and shape-replacement invalidation, including failure paths.

### 1C. Let projects live in user-selected folders — finding 3

Replace the hard-coded `WRITE_ROOT` product rule with remembered project locations. A human Save As/Export dialog authorizes its selected destination directly. Save continues at the project's existing location. Assistant file operations use the selected project location and explicit configured grants; a bridge request must not silently grant itself a new root. Resolve destinations consistently, retaining suffix checks and staged-save/export recovery.

Start with a blank document and recent-project list, plus an explicit **Open example** action. Remember the last useful directory; default a first project to a descriptive folder such as `CADkz/projects`. Keep automatic demo opening behind a development option. Task tooling continues to obey its own filesystem permissions; the app's policy is not an agent sandbox rule.

**Gate:** Save As, reopen, relocate and export in a user-selected directory outside `CADkz/Codex`; test permitted and ungranted assistant destinations, read-only targets and failed replacement recovery. Use a designated validation destination within the executing harness's permissions. Launching normally does not open or overwrite the acceptance fixture.

### 1D. Units and formulas through the shared contract — finding 4

Replace Value/Depth fields with the native quantity widget, using the pinned runtime's actual API. Accept finite numbers in the existing canonical units and quantity strings through `set_parameter`, Pad/Pocket depth and the bounded dimension-entry operations. Unitless arithmetic takes the target parameter's declared unit. Validate dimension type, finiteness, sign and range after parsing.

Keep numeric angles in radians for contract compatibility. Convert explicit `deg`/`rad` quantities deliberately: FreeCAD quantity `.Value` uses degrees, whereas the current Sketcher contract uses radians.

Add an explicit validated expression operation, for example `set_expression {feature, parameter, expression}`, with an explicit clear action. Resolve formulas through native document expression semantics, with a bounded supported grammar, unit validation and missing/cyclic-reference diagnostics. Retain the guard against numeric edits silently replacing existing expressions. Expressions such as `Plate.Constraints.Width/2` preserve dependencies; `App.Units.Quantity` alone cannot resolve named document references.

The widget stages input; applying a number/formula calls the controller. Verify native expression bindings do not mutate the authoritative object before dispatch. Return both the formula and evaluated quantity to GUI and assistants. Do not use Python `eval`.

**Gate:** GUI/assistant parity for `1/8 in`, `0.25 in`, `12.7/2`, a named upstream formula and angle units. Wrong-dimension input such as seconds in a length field, nonfinite values, missing references and cycles reject while retaining the prior state. Formula dependencies survive upstream changes, undo/redo, save/reopen and relocation. Ordinary typing, Enter and text undo still work in the new widget.

### 1E. Move feature paste into dispatch — finding 5

Add a bounded `duplicate_feature` operation for the currently supported sketch/Pad/Pocket types. Preserve the documented shallow-copy semantics: independent copied parameters, shared original support/profile references, no recursive graph copy. Carry source identity/fingerprint and destination body explicitly, with revision/lease/task guards, native transaction, recomputation, validation and rollback in the controller. The GUI retains clipboard/placement/view responsibilities and calls this operation.

Audit other app-authored modeling mutations. Native Sketcher and native feature Tasks remain legitimate writers to the same FreeCAD document, guarded by editing ownership and revision invalidation; this project does not need to reimplement all native commands in Python. Persistent view preferences may remain outside modeling dispatch under the documented view-state policy.

**Gate:** matching GUI/assistant normalized intent and relevant geometry; changed/deleted clipboard source, stale revision, active native task, unsupported/cross-document copy and failed rebuild reject without partial features. One paste is one undo step. Existing native sketch clipboard placement still works within the managed lease.

### 1F. Make the test informative — findings 10 and P3 timing/recovery

Provide a minimal `shortcuts.user.json` override layer keyed by action ID, with context conflict validation, visible overrides and reset-to-default. Expose rebind from shortcut help; generate palette entries from actual registered/capable actions. Do not implement all 35 unavailable entries merely to reduce the count. Kurt requested the inventory before selecting priorities; [the full list with keys and contexts](UNAVAILABLE_SHORTCUTS.md) is now supplied. Eight entries concern modeling/sketch work and 27 concern other workspaces. Usage priorities remain unestablished.

Record input-to-visible-feedback, queue wait, intent/inspection, native recompute and total operation times separately. Use plate, supplied STEP geometry labeled as references, and a generated larger native history fixture. The latter is a performance fixture, not a hub conversion. Report sample count, runtime/hardware, median/p95 and worst stalls. Proposed first interaction target: p95 under 100 ms for ordinary selection/tool feedback; exact recompute has a separate measured budget. This is a target, not a measured claim or manufacturing tolerance.

Verify and explicitly configure native autosave in the isolated normal app profile, identify its actual recovery directory, and perform controlled crash/reopen checks on disposable projects, including an active sketch. A `.FCBak` from an ordinary save is not proof of autosave. Add a draft recovery mechanism if native recovery does not retain active edits. Add FreeCAD version/revision and OCCT version to export provenance.

**Gate:** invalid shortcut overrides are rejected without losing usable defaults; text fields/dialogs retain their keys. Errors are visible, timing is reported, and recovery of a saved project plus unfinished work is demonstrated or its remaining limitation clearly blocks the reliability claim.

### Readiness walkthrough

Run the existing offline/core, bridge and routing suites appropriate to the changes, then the targeted native GUI recipes. Update contracts and evidence without claiming earlier test reports cover the new behavior. Kurt then performs a roughly 30-minute create/edit/repair/undo/save/reopen/export workflow in his project folder, including units/formulas and navigation. Record comfortable and uncomfortable transitions alongside timing.

Comfort is the immediate foundation gate. Broader M1 completion still requires the real conversions, reference behavior, actual edits through both assistants and physical offline workflow.

## Increment 2 — make assistant proposals and retries dependable

**Finding 8: request identity.** Introduce a contract/capabilities version and `request_id` for mutating clients, plus a read-only `request_status` lookup. Record queued/started/completed/failed/cancelled status and the original result with its produced revision. A replay with the same ID and identical canonical payload returns the original result before ordinary stale-revision checking; reuse with different payload rejects. Never execute a second mutation on replay, including after unrelated edits or undo.

Scope guarantees to the app session initially. Define ledger lifetime/eviction and distinguish expired or restarted-session records from "never executed." Recovery after a process crash requires reconciliation; do not promise cross-crash exactly-once behavior based on an in-memory map. Keep the 64 KB cap until a specified bulk operation requires a bounded change.

**Finding 7: isolated preview.** Start with `set_parameter`/expression previews. Copy the authoritative native state into a disposable native document or verified snapshot, preserving references while excluding it from live managed-document registration. This is temporary evaluation, not a second editable model. Return base revision, proposed operation, build diagnostics and measurements. Preview may fail without altering the live document.

Do not use a simple live apply/inspect/abort as the initial implementation: observers, revision metadata, recompute caches and undo/redo can escape the intended rollback. Verify the chosen clone includes required native intent and references. Block previews during active native tasks/leases initially. Discard destroys temporary state. Commit executes the original operation afresh against the unchanged base revision, with a new request ID; stale proposals reject.

**Gate:** timeout-after-start followed by lookup/replay changes the model exactly once within a session. Different-payload reuse rejects. Preview/discard preserves normalized live intent, revision, undo and redo stacks, modified flag, selection, camera, file and source mapping. Preview success followed by an intervening edit cannot commit against the old revision. Successful commit has one ordinary undo step.

## Increment 3 — handle real documents and multiple bodies

**Finding 6:** replace every literal `doc.Body` assumption with body resolution shared by core/UI/export. Inspection lists native bodies and standalone shapes with per-result validity, measurements and supported operations. Resolve an operation's explicit `body` ID first, otherwise the target feature's unambiguous owning body, otherwise the sole eligible body. GUI requests may supply the active native body; assistants must not inherit changing GUI focus when several bodies exist. Ambiguous requests reject.

Use native owning-Body origins, not globally guessed `XY_Plane` names. Validate feature/support membership; preserve cross-body dependency guards. Specify selected-body versus document export, with included body IDs and engine/settings provenance. Preserve all intended solids rather than enforcing one solid for an entire document. Body and aggregate build status must clearly expose failed/unrecomputed results.

Open unmanaged FCStd for inspection first; offer an explicit **Adopt a copy** operation after showing supported/unsupported objects. Adoption adds metadata transactionally, preserves native IDs/links, assigns project identity, and saves to a selected new path. Do not silently overwrite the original or imply metadata makes proxies, external dependencies or arbitrary objects supported.

**Gate:** renamed internal Body IDs, two Bodies with different origin planes, three-solid inspection/export, nondefault active Body, ambiguous assistant requests, unsupported objects and external links. Save/reopen/relocate a disposable adopted copy without modifying the input. Keep STEP-only reference inspection separate from editable reconstruction.

Then extend source-driven feature/reference tests: pattern-count edits, suppress/restore and split/merge as required by the actual fixtures. Run kernel capability checks on the preserved real STEP parts and declare failure/indeterminate comparisons explicitly. Frozen authenticated source/configuration capture and Kurt's deferred edited STEP variants remain prerequisites for conversion equivalence, not blockers for these independent fixes.

## Proposed collaboration and later cleanup

If Kurt accepts Claude's split: Codex owns app/controller/UI and their tests; Claude owns the MCP wrapper/skill, OCCT capability fixtures and review. Freeze/review contract changes together, keep one app repository with bounded branches, and require a shared schema/interface review for changes crossing ownership. A read-only MCP wrapper can be prepared now; mutation retry behavior should consume Increment 2's published semantics. Each actual assistant must later demonstrate a real edit on the same document, plus stale-client rejection and normalized GUI/assistant parity. Writing a wrapper alone does not pass that gate.

Keep ADR-0 provisional. If Kurt's measured workflow exposes a named reuse blocker, reconsider FreeCAD versus the own-core option while retaining operation schemas, shortcut data, fixtures and useful validation. Bridge/controller implementations may need adaptation; do not promise they move unchanged.

Later: configurable STL deflection with provenance and bounded validation, theme/string consolidation and diagnostics polish. Archival bundles can start from already preserved originals with hashes/manifests; additional online revision capture depends on access and known source identity. Neither archival capture nor a metadata adoption counts as a converted design.

**Next implementation step:** baseline Git, then Increment 1A. Approval of this proposed plan and work split remains separate from the completed planning request.
