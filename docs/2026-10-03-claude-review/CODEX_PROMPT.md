# Upgrade KurtShape for speed and Onshape-style modeling (October 2026)

This is your implementation brief. Read all of it before you change anything. It is self-contained: you have the repository but not the conversation that produced it. Background and raw evidence are in `docs/2026-10-03-claude-review/REVIEW.md` and `docs/2026-10-03-claude-review/evidence/`. Every number that an acceptance gate depends on is restated here.

Line anchors (`path:line`) refer to commit `c36d0a2` ("Record Kurt's decisions in the October 3 review"). The app source has not changed since `d9efdcc`, so the anchors are valid for both. Anchors drift as you edit. Find the symbol by name, and treat the line number as a hint.

Facts marked **(verified)** were probed on FreeCAD 1.1.4 / OCCT 7.8.1, the same versions as the pinned Windows runtime, mostly with the Linux AppImage build. Facts marked **(unverified)** were not probed. Before you build on an unverified fact, verify it with a small probe on Kurt's Windows runtime and record the result. All timings were measured on a 4-vCPU Linux container. Re-baseline them on Kurt's machine before treating them as gates.

---

## 1. Mission and outcome

KurtShape should feel at least as fast and seamless as Onshape for Kurt's Part Studio and Assembly work. It is a local Windows CAD app: a Python/PySide shell (`src/kurtshape`, about 7.6k lines) around portable FreeCAD 1.1.4 (OCCT 7.8.1). The native FCStd document stays the single source of truth.

Concretely:

- **Interaction overhead.** Time outside FreeCAD's own recompute must drop:
  - dimension-edit overhead from 5.3 s to ≤ 150 ms, then ≤ 50 ms;
  - inspection after a shape change from 4.95 s to ≤ 20 ms;
  - first frame of the extrude preview from 15.7 s (first evaluation; 15.1 s for each later one) to ≤ 50 ms;
  - open overhead from +12.7 s to ≤ max(300 ms, 10 % of native open);
  - recovery stalls from 1.27 s every 30 s to none during input.
- **Onshape-parity features:**
  - a unified Extrude (New/Add/Remove/Intersect, every end condition that maps to native Pad/Pocket, depth handle; Up to part is deferred, see increment 4);
  - a rollback bar with insert, suppress and reorder;
  - variables;
  - measure and mass properties;
  - hover highlight, and inline failures shown in the history;
  - live-linked assemblies that update automatically when a part changes, with all native joint types, solver drag, sub-assemblies, BOM and exploded views.
- **Platform.** Windows 10/11 x64 is the only product platform.

Deliver this as a sequence of interleaved, individually shippable increments (§8). Each ends with a runnable app, green checks, recorded evidence and a short report to Kurt. Do not stop at a plan. Do not merely expose native workbenches.

## 2. Workspace and verified starting point

- **Checkout and remote.** Kurt's checkout is `C:\Users\Kurtz\Documents\KURT\CADkz\Codex\kurtshape`. The remote is `github.com/kazzurt/KurtShape` (public).
- **Branches.** `origin/main` is at `d9efdcc`. The review commits (`0611c3a`, `c36d0a2`, and the commit that adds this file) are on `origin/claude/clever-cerf-fe9sjf`, which is a fast-forward of `main`.
- **First steps:**
  1. Run `git status` and preserve any local work.
  2. Run `git fetch`.
  3. On `main`, run `git merge --ff-only origin/claude/clever-cerf-fe9sjf`.
  4. If the tree is dirty or the merge is not a fast-forward, stop and ask Kurt.
- **Runtime.** Portable FreeCAD 1.1.4 (revision `4fd3bf320d9566a27e60069fc8387448aaa3a094`), OCCT 7.8.1, PySide6 6.8.3 (verified from the archive listing), at `runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311`.
  - `install-runtime.ps1` installs it from an archive pinned to SHA-256 `4828741fc91ee37fafcdb97a1abacb18b04ba451ac4372d9ff7a7349b36f4d6d` (418,088,341 bytes).
  - The archive has one top folder, `FreeCAD_1.1.4-Windows-x86_64-py311`. Its `bin\` holds `python.exe`, `pythonw.exe`, `freecadcmd.exe`, `freecad.exe` (lowercase) and `FreeCAD.pyd`. Its `lib\` holds `Part.pyd`, `Sketcher.pyd` and `AssemblyApp.pyd`. Its `Mod\Assembly` holds `JointObject.py`. There is no `._pth` file, so `PYTHONPATH` and `-m` behave normally.
  - The top-level `FreeCAD.exe`/`FreeCADCmd.exe` are .NET launcher stubs. Do not use them.
- **Python launcher.** Run headless code with `bin\python.exe -B`. **Never** use `freecadcmd` to run tests or benchmarks: it exits 0 on uncaught exceptions and ignores `PYTHONDONTWRITEBYTECODE` (verified).
- **Kurt's machine.** Windows build 26200, 32 logical processors (`validation/review-followup/performance.json`). Performance budgets are judged there.
- **Baseline.** Before changing anything, run `.\run-checks.ps1`. On Kurt's machine the expected result is 92 offline native tests (89 runnable + 3 that need the external Onshape examples), 4 bridge tests and 22 shortcut tests. Then:
  1. Copy the console counts into the plan doc (§7.2), separating pre-existing failures from new ones.
  2. Today's `run-checks.ps1` rewrites tracked evidence (`validation/offline-test-result.json` via `tools/validate_offline.py:37`, `validation/core-acceptance/*` via `tests/test_core.py:54`, and the source inventory JSON via `run-checks.ps1:10-13`). Run `git status --porcelain` and restore every tracked file the run modified: `git restore --source=HEAD -- validation`. Review `git clean -n validation` and delete only files the run created. Never commit regenerated legacy evidence from the baseline.

## 3. Read first (in this order)

1. `docs/2026-10-03-claude-review/REVIEW.md` (all of it) and `docs/2026-10-03-claude-review/evidence/`: `bench_core.py`, `bench_gui.FCMacro`, `fix_probe.py`, `profile_op.py`, `bench-core-60-holes.json`, `bench-gui-40-holes.json`, `fix-probe-60-holes.json`.
2. `README.md`, `PRODUCT.md`, `DESIGN.md`, `docs/FOUNDATION_DECISION.md`.
3. `docs/OPERATION_CONTRACT.md` and `docs/SKETCH_PLANE_CONTRACT.md`.
4. `docs/M1_PROGRESS.md`: the top three sections and "Outstanding M1 gates" (around lines 103–112).
5. `docs/assembly-workflow/WORKFLOW.md`, `NATIVE_API.md`, `VALIDATION.md`, `START_PROMPT.md`, `COORDINATION.md`.
6. `docs/2026-10-02-claude-review-follow-up/UPDATE_PLAN.md` and `IMPLEMENTATION.md`. These are the format to follow for plan and implementation records.
7. `docs/ui-refinement/IMPLEMENTATION.md`, `docs/ui-refinement-preview/README.md`, `docs/workspace-behavior/IMPLEMENTATION.md`.
8. `docs/ONSHAPE_SHORTCUTS.md`, `docs/STEP_IMPORT.md`, `docs/INTERFACE_PASS.md`, `shortcuts.json`.
9. Code before you change it:
   - `src/kurtshape/core.py`: `Controller.dispatch`/`_dispatch`, `_model_operation`, `_inspect`, `_build_status`, `_export`, `_save`, `_adopt`, `write_path`;
   - `src/kurtshape/document_state.py`, `extrusion_preview.py`, `assembly.py`, `bodies.py`, `recovery.py`, `bridge.py`, `request_ledger.py`, `settings.py`;
   - `src/kurtshape/ui.py` (`Panel`);
   - `tests/` and `tools/validate_offline.py`, `run-checks.ps1`, `validate-review-gui.ps1`, `install-runtime.ps1`, `launch-kurtshape.ps1`.

## 4. Kurt's four decisions

Verbatim from `REVIEW.md` §6 (October 3, 2026):

> 1. **Validation:** yes. Geometry validity is checked at export and on explicit request, not after every edit.
> 2. **Assemblies:** live links that update like Onshape. Pinning to a snapshot may remain as an option.
> 3. **Platform:** Windows only. CI runs on Windows with the pinned portable runtime; the Linux AppImage remains a convenient probe tool, not a product target.
> 4. **Order of work:** both. Speed work and new Onshape-parity tools are interleaved rather than speed-only first.

### 4.1 What each decision means for the work

**Decision 1: validate at export and on request.**

- Interactive build status comes only from native feature state: the `Touched`/`Invalid`/`Error` flags, null shapes, solid counts and the metadata `RebuildReason`.
- Interactive paths never call `Shape.isValid()` or `Shape.check()`. The interactive path is: new, sketch ops, pad/pocket/extrude, set_parameter/expression, undo/redo, finish_sketch_edit, inspect, tick, checkpoint, preview.
- Volume integration on the interactive path is limited to:
  - the empty-cut, empty-extrude and intersect postconditions (about 47 ms per affected body at 60 holes, F6/F7);
  - API callers that pass `measure: true` (the API default). The GUI always passes `measure: false`.
- BRepCheck runs only in:
  - the new read op `check_geometry`;
  - before every export, which rejects with `invalid_geometry` and writes nothing;
  - the explicit import boundaries, which keep their `isValid()` checks: STEP import at `core.py:997`, and assembly STEP read/insert at `assembly.py:238` and `assembly.py:370`.
- Opening a file trusts the stored BReps. It does not touch or recompute everything.

**Decision 2: live assemblies like Onshape.**

- The primary model mirrors an Onshape document. One KurtShape project FCStd holds the Part Studio Bodies and one or more Assemblies. Each occurrence is a native `App::Link` to a Body in the same file.
- A part edit and one recompute update links, joint frames and solved placements in one native transaction. One undo restores both (verified). This holds for **every** path that changes part geometry (typed ops, sketch Finish, undo/redo, rebuild, native task-panel edits), not only `set_parameter` (increment 13).
- Pinning (relinking an occurrence to a hidden snapshot) stays as an explicit per-instance option.
- STEP sources stay pinned snapshots. An external FCStd source is either imported into the project as a parametric copy (then live-linked) or inserted as a pinned snapshot with an explicit "Update from source".
- Cross-document live links (one FCStd per part) are deferred. They have verified pitfalls, listed in §8 increment 17. Do not build them without Kurt's go-ahead (see §7.6).

**Decision 3: Windows only.**

- The only product target is Windows 10/11 x64 with the pinned portable runtime installed by `install-runtime.ps1`.
- CI runs on GitHub-hosted Windows runners using that same archive (increment 0). CI runs only after Kurt pushes (§7.2 step 7).
- Do not add macOS/Linux support, packaging or CI. The Linux AppImage is only a probe tool.
- Still replace the hard-coded runtime path in `assembly.py:23` with `Path(App.getHomePath()).resolve() / "Mod" / "Assembly"` and an explicit FreeCAD 1.1.4 version guard. This is correct on Windows too, and it lets the same tests run in CI.
- No global installs and no pip into the runtime.

**Decision 4: interleave speed and features.**

- The increment order in §8 alternates speed increments and Onshape-parity increments. It respects real code dependencies:
  - CI and test hygiene come first;
  - then the status/measurement redesign;
  - the operation registry comes before new typed ops;
  - preview v2 comes before the unified Extrude UI;
  - the event-driven shell's incremental intent and delta summaries come before the model/view history tree and the rollback bar UI;
  - live-link assemblies come after the status redesign, preview v2 and the registry.
- Each increment pairs naturally with the code it touches.

### 4.2 Where these decisions override REVIEW.md text

- REVIEW.md lines 139 and 206 and Appendix B describe **Linux** CI. They are replaced by the Windows workflow in increment 0.
- REVIEW.md line 199 says "Phases 0 and 1 add no new tools". It is replaced by decision 4.
- The Phase 3 gate in REVIEW.md ("save, relocate and reopen a multi-file project") is replaced by:
  - save, relocate and reopen a single-file project with live links;
  - plus pinned external sources that relocate without their source files.
  - Cross-document live links are deferred (see decision 2).
- The REVIEW.md:241 foundation checkpoint on the "reconstructed hub" cannot be run as written, because the hub is not reconstructed. Report synthetic-fixture numbers only.

### 4.3 Defaults for questions that are still open

These are listed for Kurt. Implement the default and do not block on them.

- **Feature dialogs** (REVIEW.md:252): hybrid.
  - KurtShape-styled right-dock panels with live preview for Extrude (all operations). Revolve, Fillet, Chamfer, Shell, patterns, Mirror and Plane may follow later only with Kurt's sign-off.
  - Every other tool keeps FreeCAD's task panel, shown in the same right-hand dock area under a KurtShape header with Confirm/Cancel.
- **Remove default end type:** keep KurtShape's current *Through all*.
- **Initial extrude depth:** remember the last depth used in the session. Start at the current GUI default if one exists; otherwise 25 mm. The Onshape metric default of 25 mm is **unverified**.
- **Toolbar Extrude on a sketch whose part already has a solid:** default to Add (current behavior).
- **Up to part:** deferred. A same-body Up to part equals Up to next/last, and a cross-body one needs a binder design that has not been probed (increment 4).
- **Export while a Body is rolled back:** reject with `history_rolled_back` ("Roll the history to the end before exporting").
- **Rollback insertion rule:** accept FreeCAD's native rule. New objects land before the next solid feature after the Tip. Do not enforce strict Onshape ordering.
- **Status line volume:** show solid count and check state. Show volume only once it has been measured. No idle background mass integration.
- **Legacy projects without an engine stamp:** open as `needs_rebuild` / `engine_unrecorded` and require one explicit Rebuild.
- **Adopting a native file:** `_adopt` does not rebuild. The adopted copy is stamped only when its `ProgramVersion` equals this runtime's build string and no expected shape is missing; otherwise it opens as `needs_rebuild` (increment 1).
- **Engine mismatch:** block export until Rebuild.
- **Native FreeCAD AutoSave:** disable it. KurtShape idle checkpoints become the single recovery mechanism.
- **Light checkpoints:** accept them. Crash recovery then rebuilds the model, about 12 s at 60 holes, which is the same as recovery today.
- **User saves:** keep FreeCAD's default save settings (no fast-save).
- **Default STL preset:** Medium.
- **Recovery idle defaults:** checkpoint after 2 s without input, at most every 10 s, and after 120 s of continuous work at the next 0.5 s pause.
- **Background STEP import that finishes during a sketch or task:** keep it pending with a "STEP ready" notice, and open it when the edit ends.
- **History during a sketch lease:** frozen until Finish or Cancel.
- **History scroll and expansion:** kept per document.
- **Assistant bursts:** one bridge request per event-loop turn.
- **Variables:** accept and display `#name`, stored as `Variables.name`.
- **Proposed shortcuts:** Shift+U (suppress, history focused), Up/Down (move a selected rollback bar), Alt+V (Variables). These are unconfirmed by Kurt; keep them easy to change in `shortcuts.json`.
- **Sketcher "Dimensions while drawing":** sizes only (`OnViewParameterVisibility=1`). Write it only if the user has not set it.
- **Unnamed second pad or pocket from the API:** give it an automatic unique id (`Pocket002`) instead of failing with `duplicate_feature`.
- **Breaking a mate through a part edit:** accept the part edit and show the assembly as failed, with the broken mate listed (Onshape behavior).
- **Undo:** one history per project.
- **Assembly ids:** several assemblies per document are allowed. Ops then need an explicit `assembly` id, and omitting it with more than one present gives `missing_assembly`.
- **Parameter/expression preview:** the assistant `preview` op for `set_parameter`/`set_expression` (`core.py:889-940`) keeps its hidden clone in this plan. Converting it to the traceless transaction (F11) is out of scope unless Kurt asks.
- **Assistant write roots (REVIEW P1-12):** unchanged until Kurt decides (§7.6). Proposed design, implemented only after his OK: grants scoped to chosen project folders, a Settings list with Revoke, `WRITE_ROOT` (`core.py:25`) narrowed to the projects folder, and the bridge still unable to grant.
- **Branch, push and attribution:** commit on local `main`, one commit per increment (increment 0 may use up to 5 commits), using Kurt's git identity with no AI trailers (the existing Codex style). No push and no PR unless Kurt asks. Ask him to push in each report (§7.7).

## 5. Non-negotiable invariants

Break none of these. Every increment's tests must keep them provable.

1. **Native FCStd is authoritative.**
   - History order is `Body.Group`, rollback is `Body.Tip`, suppression is `Feature.Suppressed`, and variables are `App::VarSet` properties.
   - Occurrences are native `App::Link`/`Assembly::AssemblyLink`, joints are native `JointObject.Joint`/`GroundedJoint`, and the solver is native.
   - No parallel editable feature or assembly graph, no custom kernel or joint solver, no deep FreeCAD fork, no persisted derived facts (volumes, verdicts) in features.
   - No new properties on Sketcher or PartDesign features. The only allowed additions are:
     - `KurtShapeProject` metadata: `EngineFreeCAD`, `EngineOCCT`, `RebuildReason` (increment 1);
     - KurtShape-owned snapshot objects, group "KurtShape Assembly": the existing `Source*` properties plus `SourceKind`, `SourceIntent`, `PinnedAt` (increment 15);
     - `ImportedFrom` on Bodies imported in increment 15;
     - property-status changes on assembly objects as specified in increment 13.
2. **One mutation path.**
   - App-authored mutations go through `Controller.dispatch`, which the GUI and the loopback bridge share.
   - Native Sketcher and task panels stay legitimate writers, guarded by edit ownership and revision invalidation.
3. **Revision tokens.**
   - Mutations of an existing document need `document_id` plus the current `expected_revision` (an opaque UUID). A stale or invalid request is rejected before any mutation.
   - Every native intent edit changes the revision before the next mutation is accepted.
   - A no-op property assignment, which FreeCAD still signals, must not change the revision. Revision stays content-based.
   - Read ops, `check_geometry`, measure levels, cache fills and hover/measure never change the revision.
4. **Request ledger and replay.**
   - Bridge mutations need `request_id` (1–128 chars).
   - An identical canonical replay returns the original result before the stale check. The same id with a different payload gives `request_id_reused`.
   - The ledger keeps 512 results and 4096 session ids, with `expired`/`not_recorded` semantics. Requests are capped at 64 KiB. A started timeout returns `outcome_unknown`.
   - Async jobs register `started` once and complete exactly once. A replay never starts a second job.
5. **Failure rollback.**
   - A failed typed mutation aborts its transaction. Intent signature, revision, UndoCount/RedoCount and geometry stay exactly as before.
   - One user command is one undo step, including New (Body + binder + Pad) and Intersect (tool Body + binder + Pad + Boolean).
6. **Staged save and export pair.**
   - Save stays staged, with verification and a `.recovery.FCStd` copy.
   - Exports publish only through `_replace_export_pair` (`core.py:1454-1490`), with rollback and provenance (engine, revision, settings, SHA-256, shape).
   - Export is blocked unless the build is valid, and it now also BRepChecks every included result.
7. **Sketch lease preservation.**
   - The edit lease is exclusive, with a snapshot undo/redo stack.
   - A failed Finish keeps the draft and reopens Sketcher. Explicit Cancel restores the accepted sketch. A completed Finish is one undo step. The lease auto-finishes when the native editor closes.
8. **Recovery of unfinished sketches.**
   - Checkpoints restore the draft and the accepted (Cancel) buffer.
   - Recovered and imported documents open unsaved: `FileName == ''`, native_file None, GUI Modified True. Recovery never overwrites the original file. From increment 5, the Label also equals the original name (at HEAD, recover sets only `FileName`, `core.py:655-657`).
   - Schema-1 recovery manifests on disk stay listable and recoverable.
   - At every instant at least one complete, SHA-256-verified checkpoint pair exists per document.
9. **GUI-thread-only document mutation.**
   - FreeCAD and OCCT APIs are called only on the GUI thread.
   - FreeCAD Python calls hold the GIL for their whole duration (verified: `saveCopy` 774 ms, `exportStep` 997 ms, `isValid` 1,710 ms, worst main-loop gap). Worker threads may do only pure file work: hashing, ZIP verification, renames, deletes, reading a child process's stdout. Heavy FreeCAD work off the GUI thread goes to a separate process (`bin\python.exe` worker).
   - Bridge HTTP threads only enqueue, signal and wait. Cross-thread delivery uses a bound `@Slot` with `Qt.QueuedConnection`, never a lambda.
   - Observer callbacks never hash, validate, rebuild or start timers. They update counters and sets only, and are exception-safe.
10. **Pinned runtime and no global installs.**
    - FreeCAD 1.1.4 / OCCT 7.8.1 only. `install-runtime.ps1` verifies the SHA-256 before extraction.
    - No pip and no new third-party Python dependencies. `jsonschema` is not bundled (verified on Linux; the in-repo validator is used anyway).
    - Everything stays under the checkout, and `runtime/` stays out of Git. Never publish `runtime/assistant-session.json` or other credentials.
11. **Never touch Kurt's live state.**
    - Never drive, restart or close Kurt's open KurtShape/FreeCAD window.
    - GUI validation runs in separate hidden processes, isolating `KURTSHAPE_SESSION_DIR`, `FREECAD_USER_HOME`, `TEMP`/`TMP`, `APPDATA`, `LOCALAPPDATA` and `-u`/`-s` config files, as `validate-review-gui.ps1` does. Use `Start-Process -WindowStyle Hidden`, never FreeCAD `--hidden`.
    - Never run `install-runtime.ps1` against `runtime\freecad-1.1.4` on Kurt's machine: it extracts with `7z x … -y` over the runtime Kurt's open app runs from (`install-runtime.ps1:16-17`). Test it only with `-RuntimeRoot runtime\install-test` (increment 0) and delete that folder afterwards.
    - Never run `launch-kurtshape.ps1` or `KurtShape.cmd` without `-Validation`. Without it the session directory is `runtime\` (`launch-kurtshape.ps1:4-10`), which holds Kurt's live `assistant-session.json`, recovery directory, `settings.json` and `user-data\user.cfg`.
    - Stop only processes you verified you started.
    - Never modify the original Onshape examples (`CADkz/Onshape examples`), the Claude reference directory (`CADkz/Claude`) or `cadkz-project-planning`. Read them in place.
12. **Assistant contract versioning** (§7.5).
    - `capabilities.contract` and the bridge session file's `contract` must read one constant.
    - A semantic change bumps the contract (to 3 in increment 1). Additive changes after that bump `contract_revision` and get a subsection in `docs/OPERATION_CONTRACT.md`.
    - Error codes stay stable. New codes are additive.
13. **User-facing naming and theme.**
    - New labels, tooltips, help and messages never say "native". Use modeling names: Extrude, Remove, Revolve, Linear pattern, Plane, Check geometry, Roll back, Suppress, Pin to version, Update from source, Variables, Measure.
    - Do not mass-rewrite existing error strings that tests assert. Fix `ui.py:1102` when you touch it.
    - Light theme owned by `theme.py` (palette hex at `theme.py:11-16`, Segoe UI 12px at `:20`).
    - 24 px icons, 28–34 px controls, 4/8/12 spacing. Green success, red failure, blue selection.
    - Compact icon tools with named hover help. No decorative cards or empty dashboards.
    - SolidWorks navigation stays the default.
    - Selection never resets the camera. History stays visible while sketching. Messages stays closed until opened. Errors show red status text and are kept in Messages.
14. **Shortcut registry honesty.**
    - Every key lives in `shortcuts.json` with id, contexts and status (`native`, `callback`, `unsupported`, `pass_through`). Change a status only when the behavior ships.
    - Any `native_command` must exist in the SketcherWorkbench command list of `validation/onshape-shortcuts-command-probe.json` (`tests/test_shortcuts.py:98`). The probe has no AssemblyWorkbench entry. When you add Assembly or other commands, add that workbench to `tools/shortcut-command-probe.FCMacro`, regenerate the probe, and make the test check the union of the workbench command lists.
    - Keep Shift+G Pierce, Shift+L Perpendicular and ordinary Ctrl+S/Escape.
    - `runtime\shortcuts.user.json` overrides keep working.
15. **Idle stays idle.**
    - No per-poll validation, source reads, solver runs, intent hashing or BRep serialization while nothing changes.
    - After increment 11, there are no active KurtShape QTimers while idle.
16. **Honesty gates.**
    - M1 stays incomplete and real parametric conversions stay **0/2**. No increment may claim otherwise.
    - Never claim overall Onshape parity, hub performance (the hub is not reconstructed), that GUI automation equals Kurt's hands-on comfort test, that a Claude client edit happened, that CI ran when it did not, or clean native startup without evidence.
17. **Local access and write safety.** Keep each of these exactly; any rewrite of the code must keep them and their tests.
    - (a) Bridge: binds `127.0.0.1` only (`bridge.py:78`); per-session bearer token and path `/operation` (`bridge.py:28-30`); any request carrying an `Origin` header is rejected with 403 (`bridge.py:32-34`, anti-browser CSRF); the media type must be `application/json` (from increment 0 parameters such as `; charset=utf-8` are allowed, P2-15); body 1–65,536 bytes else 413 (`bridge.py:36-39`); queue capacity 32, else `queue_full` (`bridge.py:17`, `:49-56`).
    - (b) `write_path` (`core.py:58-69`): the destination is absolute, inside a granted root, with an allowed suffix and an existing parent. The bridge can never grant a root (`settings.py`, `tests/test_review_followup.py:248` `test_user_granted_project_folder_persists_and_bridge_cannot_self_grant`). Every new disk-writing op (export stages, worker job outputs placed next to a destination, `export_bom`) resolves its destination through `write_path`.
    - (c) `attach` gives every opened or copied file a fresh session Revision (ABA protection) and rejects a second open copy with `duplicate_document_id` (`core.py:304`, `:311`); sketch leases are dropped on reopen. Every new path that opens a document as a project (increment 5 `attach_external`, increment 9 `finish_step_import`) must go through `attach`.
    - (d) Unmanaged documents are read-only except for `adopt` (`core.py:678` `unmanaged_document`), and `adopt` never overwrites an existing file or the original (`core.py:945` `adoption_destination_exists`).
    - (e) `RecoveryStore.read` accepts only manifests and snapshots inside the project recovery directory and checks SHA-256 before opening (`recovery.py:50-56`), although `recover` takes a path from the bridge.

## 6. Shared FreeCAD 1.1.4 facts and traps

All verified unless marked otherwise. Increments refer back to this list.

- **F1. Open without recompute.**
  - Opening a saved FCStd without recompute restores every feature and sketch shape, all up to date. A following `doc.recompute()` recomputes 0 objects.
  - Editing one dimension afterwards recomputes only its dependents, correctly.
  - FreeCAD persists `Touched="1"`, `Invalid="1"` and `Error="msg"` in `Document.xml` and restores them. `Body.Shape` keeps the last good result.
  - A feature that had already failed when saved (for example a Pocket with Length 0: State `['Touched','Invalid']`, "Cannot create a pocket with a total length of zero.") reopens with the same flags and a **null Shape**, and a Body whose Tip failed reopens `['Touched']`. A shape removed from the archive (for example `Pad.Shape.brp`) reopens as `['Up-to-date']` with a null Shape.
  - Only `KurtShapeProject` comes back Touched (harmless; recompute 0.8 ms).
- **F2. Program version.** `Document.xml` `ProgramVersion` / `doc.getProgramVersion()` holds only `major.minor` + build (`"1.1R20260928 (Git shallow)"`), with no patch level and no OCCT. `App.Version()` gives `['1','1','4','20260928 …']`, and `doc.getProgramVersion() == f"{v[0]}.{v[1]}R{v[3]}"` for a file saved by this runtime. `Part.OCC_VERSION` is `'7.8.1'`.
- **F3. Observer notifications.**
  - Shape notifications fire exactly for objects whose shapes change, including undo, redo and abort.
  - Tip dimension edit at 60 holes: Shape for the edited sketch, its pocket and the Body.
  - Upstream Pad edit: 62 objects.
  - Writing an equal value still fires `slotChangedObject`.
  - `obj.touch()` fires **no** callback. A failing recompute fires only `slotRecomputedDocument` plus a `SuppressedShape` change, so flags must come from a `State` scan.
  - Opening a 132-object file fires about 4,332 `slotChangedObject`.
  - PartDesign Pad/Pocket rewrite `Placement`, `AddSubShape` and `SuppressedShape` on every execute.
- **F4. Undo semantics.** With `UndoMode=1` (set in `attach`, `core.py:321`), undo/redo/abort restore shapes without recompute and leave restored objects Touched. Documents created in `freecadcmd` default to `UndoMode 0`.
- **F5. Cheap reads.**
  - `Shape.hashCode()` is stable across reads (about 5 µs). `Body.Shape` hash ≠ `Tip.Shape` hash. Origin datum shapes give a new hash on every access.
  - Python `DocumentObject` has no `mustExecute()`. `obj.State == ['Up-to-date']` when clean.
- **F6. Empty cuts are not flagged natively.**
  - A pocket that removes nothing, or a pad that adds nothing, stays Valid with volume delta about −2.3e−13.
  - Face TShape identity, face count and bbox cannot detect it. A volume comparison is required.
  - `Body.AllowCompound` defaults True, so a disjoint pad gives 2 solids, still Valid.
- **F7. Geometry query costs on the 60-hole body (66 faces), Linux probe.**
  - `isValid` 1,834 ms in this probe (1,871 ms median in `bench-core-60-holes.json`; no speed-up on repeat), `check(False)` 2,152 ms, `check(True)` 5,562 ms.
  - Volume 46.9 ms, Area 50.2 ms, per-solid CenterOfMass 51.3 ms, BoundBox 8.8 ms (not cached by FreeCAD), deep copy 126 ms.
  - `isNull`/`hashCode`/Shape getattr about 0.005 ms, `len(Solids)` 0.020 ms.
  - `obj.State` for all 132 objects 0.18 ms, flag scan 0.37 ms, `native_results(doc)` 0.71 ms.
- **F8. Bow-tie shapes.** `TopoShape.check(False)` raises `ValueError` listing BRepCheck statuses ("Self-intersecting wire", "Unorientable shape", "No error" lines). `isValid()` is False for a bow-tie extrusion.
- **F9. Pad/Pocket enumerations.**
  - Pad `Type`/`Type2` = [Length, UpToLast, UpToFirst, UpToFace, ?TwoLengths, UpToShape]. Pocket = [Length, ThroughAll, UpToFirst, UpToFace, ?TwoLengths, UpToShape].
  - Pad has no ThroughAll and Pocket has no UpToLast. Setting `Type='TwoLengths'` raises.
  - `SideType` ∈ {One side, Two sides, Symmetric}, with per-side Length/Length2, Offset/Offset2, TaperAngle/TaperAngle2, UpToFace/UpToFace2, UpToShape/UpToShape2.
  - `Midplane=True` maps to `SideType='Symmetric'`. `Refine` defaults True.
  - Pad extrudes along the sketch normal, Pocket against it. `Reversed` flips. Positive Offset extends past the face.
  - Pocket ThroughAll tool length = 2.02 × base bbox diagonal. This was verified only on axis-aligned fixtures; inclined sketches are **unverified**.
  - UpToFirst with no face ahead → Invalid "SketchBased: No faces found in this direction". Pocket UpToShape with a whole solid fails ("Resulting fused extrusion is null"); with a face it works.
  - **Cross-body up-to references are silently wrong.** A Pad in Body A with `UpToFace=(PadB, ['Face5'])` from another Body B (placed at z=30) stays Valid but evaluates the face in B's local frame (AddSubShape Z 0..10 instead of 10..30) and only logs "Link(s) to object(s) 'PadB' go out of the allowed scope". Through a `PartDesign::SubShapeBinder` in Body A with `Support=[(B, ('PadB.Face5',))]` and `UpToFace=(binder, ['Face1'])` the result is correct (10..30). `UpToShape=[(wholeBodyBinder, [])]` is Valid with an **empty** AddSubShape. `body.newObject` of a binder created after its consuming Pad lands after that Pad in `Group`.
- **F10. Fast extrusion prism.**
  - `Part.makeFace(closedWires, "Part::FaceMakerBullseye")` reproduces the native Pad profile face, including nested islands, holes and overlaps. Extruding it matches `AddSubShape` exactly in all probes (60-circle profile 15079.6447 = 15079.6447).
  - FaceMakerCheese and FaceMakerSimple are wrong for some cases.
  - Taper: `Part.makeLoft([w, w.makeOffset2D(L·tanθ, 2, False, False, False).translated(d·L)], True, True)` per outer wire, with same-sign offset lofts cut for holes. This is exact at ±10° for circle, rectangle and ring. Other angles are **unverified**: fall back to the native path on any exception.
  - Copying `AddSubShape` costs about 0.5 ms. Copying `feature.Shape` at 60 holes costs 160–250 ms.
- **F11. Traceless transactional evaluation.**
  - Sequence: `doc.openTransaction` → `body.newObject(...)` → `feature.recompute()` → `doc.abortTransaction()` → `body.purgeTouched()` → restore the GUI document `Modified`. This leaves no trace.
  - `feature.recompute()` processes no Qt events (0 timer ticks over 1.18 s). `doc.recompute()` does process events (re-entrancy hazard).
  - Replacing `DocumentState` slot methods on the instance after `addDocumentObserver` has no effect, so suspension must be an attribute check inside each slot.
- **F12. Booleans hold the GIL** (`tip.common(prism)` 364–431 ms at 60 holes; 1 main-thread tick in 398 ms). No booleans, `isInside` or `distToShape` against the tip in any preview.
- **F13. Draggers.**
  - pivy `SoTranslate1Dragger` works only via `view.addDraggerCallback(dragger, "addStartCallback"|"addMotionCallback"|"addFinishCallback", fn)` and `view.removeDraggerCallback`. A real Qt drag delivered start 1 / motion 8 / finish 1.
  - `dragger.addValueChangedCallback` **crashed FreeCAD (SIGSEGV)** during a real drag. Never use it or any other pivy callback or sensor API.
- **F14. GUI observer crash.**
  - Reading `vp.Object` in a Gui observer `slotBeforeChangeObject` segfaulted 1.1.4. A Gui observer may define only `slotActivateDocument`, `slotInEdit`, `slotResetEdit`, `slotCreatedDocument`, `slotDeletedDocument`.
  - `Gui.ActiveDocument = …` neither activates nor signals. `App.setActiveDocument` does.
  - Python task dialogs fire no observer callback on open or close. `Gui::TaskView::*` Show events do arrive.
- **F15. Never read `ViewProviderAssembly.DraggerPlacement`.** Not even via `hasattr`, outside an active drag: it segfaults 1.1.4.
- **F16. PySide6 6.8.3** (AppImage probes; the Windows archive ships the same `PySide6-6.8.3`, verified from its listing).
  - `QStandardItem.insertRow(int, item)` (single-item overload) does not transfer ownership: the item becomes None. Always use `insertRow(i, [item])`.
  - AutoConnection to a lambda from a thread took 2.4 s. A bound `@Slot` takes 0.35 ms.
  - A zero-interval single-shot QTimer coalesces 500 `start()` calls into 1 timeout.
- **F17. Cross-document links.**
  - Need a saved owner and a saved source ("Owner document not saved" / "Linked document not saved").
  - Stored as a relative XLink path.
  - `saveAs`/`saveCopy` to another folder keep the stale relative path.
  - Sources load `Partial=True` without the `KurtShapeProject` object. Edits there silently do nothing and `saveAs` writes nothing.
  - Undo is per document, with `-> name` entries in dependents.
  - `doc.openTransaction` sets an app-wide active transaction that records changes in other open documents. `abortTransaction` with no pending changes leaves it set.
- **F18. Same-document links.**
  - `App::Link` (LinkTransform False) replaces the source Body's Placement. `Part.getShape(asm, link.Name + ".", transform=True)` returns link-correct global geometry.
  - `App::Link` has no `getGlobalPlacement`.
  - Joint references are `[link, ['Face6','Face6']]`. FreeCAD remaps them after topology changes, and prefixes `?` when the face disappears; the joint then becomes Invalid with "Broken link in: Reference1".
  - The native solver returns 0 for conflicting fixed joints and for broken references.
  - `SolveOnRecompute` is effectively on by default.
  - A property with `setPropertyStatus(name, 'Output')` does not touch its owner when written.
  - `asm.Group` also lists joints, exploded views and moves.
  - `ViewObject.Visibility` written **outside** a transaction creates no undo entry but sets GUI `Modified` (Linux GUI probe); inside a transaction it creates an undo entry.
  - `Gui.getDocument(doc.Name).setEdit(asm)` opens no transaction and no task dialog; a typed transaction during this edit mode commits normally (Linux GUI probe).
- **F19. `setPropertyStatus(name,'Transient')`.** On Shape/AddSubShape/SuppressedShape it makes `saveCopy` omit them. `'-Transient'` restores. Toggling changes no State, UndoCount, GUI Modified or observer generation. This is undocumented FreeCAD behavior, guarded by a test.
- **F20. Native AutoSave.**
  - Its interval is read only at GUI startup (`StartupProcess.cpp:262-272`), so `ui.start()`'s `AutoSaveTimeout=1` (`ui.py:2035-2036`) does nothing in the running session.
  - The default compressed mode stalls the GUI 389 ms at 60 holes.
  - It fires during input.
  - Restore sets `FileName` to the original path.
  - It writes `fc_recovery_file.xml`/`.fcstd` under each document's `TransientDir`, whose root is `App.getTempPath()` (`<FREECAD_USER_HOME>/temp/` on Linux; the Windows location is **unverified**, so always resolve it with `App.getTempPath()`).
- **F21. Expressions.**
  - `App::VarSet` is C++ with no proxy. Expressions accept `Variables.Width` and `<<Label>>.Width`; bare `Width` works only inside the VarSet. `#Width` and `=Variables.Width` fail to parse.
  - FreeCAD does **not** check units: an angle bound to `Pad.Length` reads "30.0 deg" and stays Valid.
  - `obj.evalExpression` evaluates without mutating. It accepts unit syntax such as `30°` (returns 30.0 deg).
  - `addProperty` accepts `mm`, `in`, `pi`, `e`, which then cannot be referenced.
  - `App::PropertyLength` clamps negatives to 0. `App::PropertyDistance` does not.
  - `renameProperty` rewrites dependents in both syntaxes, with undo.
- **F22. Tip and history.**
  - `Body.Tip` set to an earlier feature changes no visibility.
  - Features after the Tip still recompute on upstream edits.
  - `body.newObject` inserts before the next solid feature after the Tip.
  - Tip set to a sketch or datum makes the Body Invalid. `Tip=None` gives a null Body shape.
  - `Body.removeObject` relinks BaseFeature and moves Tip off a removed tip. `Body.insertObject(f, target, after)` never changes Tip.
  - FreeCAD accepts a Group order in which a feature comes before its profile. A cycle order only leaves objects Touched.
  - `inspect()['features']` follows document creation order, not `Body.Group`.
- **F23. Measure objects and the `Measure` module.** `Measure::*` objects and `Std_Measure` create persistent document objects, which would change the revision. `Measure.Measurement.addReference3D` accepts only an object **name** and resolves it in `App.ActiveDocument`: with another document active it raises `ValueError`, and with no active document FreeCAD **crashes (SIGSEGV)**. Never use the `Measure` module. Compute measurements transiently from `Part.getShape(obj, sub, needSubElement=True, transform=True)`, which is independent of the active document and returns global coordinates.
- **F24. `bodies.results()`** returns only assembly links when an assembly exists, hiding Part Studio Bodies (`bodies.py:21-33`).
- **F25. The pinned Windows archive** bundles `bin\opengl32sw.dll` and the Qt platform plugins `qwindows`, `qoffscreen`, `qminimal`.
- **F26. FreeCAD file APIs take `str`, not `pathlib.Path`.** `exportBinary(Path)` and `exportStep(Path)` raise `TypeError`. Always pass `str(path)` to `exportStep`, `exportBinary`, `importBinary`, `Mesh.write`, `saveCopy`, `saveAs` and `openDocument`.
- **F27. `Body.Shape` after a subtractive feature is a `Compound`**, which has no `CenterOfMass`, `MatrixOfInertia` or `PrincipalProperties` (only `Solid` has them). Compute these over `shape.Solids`.
- **F28. Writing a metadata property sets GUI `Modified`.** `addProperty` alone leaves `Gui.getDocument().Modified` False, but assigning a value (`meta.EngineFreeCAD='1.1.4'`) sets it True (UndoCount unchanged). Restore `Modified` after any bookkeeping write during open.
- **F29. `Document.xml` ends with a newline** after `</Document>` (`b'…</Document>\n'`).

## 7. Working method

### 7.1 One increment at a time

Implement the increments in §8 in order. Do not start increment N+1 until increment N is committed with green checks and reported. Unless Kurt says otherwise, wait for his OK after each report before you start the next increment. Increments 9 and 12 are split into sub-increments (9a/9b, 12a/12b/12c); each sub-increment is its own commit and report. Within an increment, make routine, reversible decisions yourself. Record consequential choices in the plan and implementation docs.

### 7.2 Definition of done for every increment (in order)

1. **Plan first.** Append the increment to `docs/2026-10-03-claude-review-follow-up/UPDATE_PLAN.md` (create the folder in increment 0, following `docs/2026-10-02-claude-review-follow-up/`). Include:
   - scope, touch points and contract changes;
   - the gate and budgets;
   - anything from §6 or Appendix B you must probe.

   Where you disagree with this brief on evidence, record it there (or in an optional `RESPONSE_TO_CLAUDE.md`, as on October 2) and proceed with the better-evidenced choice. "Do not block" applies to design choices only. It never permits weakening an existing test assertion or a §5 invariant (see §7.6).
2. **Code and regression tests in the same commit.**
   - Tests assert consequences, not return codes: geometry, undo/redo counts, revision unchanged on rejection, save/reopen/relocation, failure rollback.
   - Keep every existing assertion unless this brief lists a test as updated.
3. **Living docs in the same commit as the behavior change:** `README.md`, `docs/OPERATION_CONTRACT.md`, `docs/SKETCH_PLANE_CONTRACT.md` and the others in Appendix A.
4. **Evidence.** Write small JSON reports under `validation/2026-10-03-upgrade/<increment-slug>/` with `tools/record_evidence.py` (added in increment 0). Tests and tools write tracked files only with `KURTSHAPE_WRITE_EVIDENCE=1` / `-WriteEvidence`. Keys:
   - `passed`, `checks[]`, `method`;
   - `engine{FreeCAD, OCCT}`;
   - `base_commit` (HEAD before the increment's commit) and `worktree_diff_sha256` (SHA-256 of `git diff HEAD` over the increment files). The commit hash in the §7.7 report is the authoritative identifier;
   - `hardware` (read from the OS) for performance;
   - `timings{median,p95,worst,samples}` and `limits`;
   - `ci{status, reason, run_url}`: `status` is `not_run` with reason `push not authorized` until Kurt pushes.

   Screenshots, profiles and fixtures go under `runtime/` or a `validation/**/<name>-working/` folder (both ignored by `.gitignore`).
5. **Implementation record.** Add the increment to `docs/2026-10-03-claude-review-follow-up/IMPLEMENTATION.md`:
   - delivered behavior;
   - an evidence table linking each JSON with its counts;
   - PowerShell reproduction commands from the repo root;
   - limits and the next step.
6. **Progress record.** Add a new dated section at the top of `docs/M1_PROGRESS.md`: `## October N <increment> — implemented`. Include the request, behavior, counts, links, a "Next:" line, and the sentence "**M1 remains incomplete and real parametric conversions remain 0/2.**" Update the header line "Updated <date>, America/Los_Angeles".
7. **Checks (§7.3).**
   - `.\run-checks.ps1` must be green.
   - `.\tools\ci\run-local.ps1` (increment 0) must be green. It reproduces the CI steps locally. GitHub CI runs only after Kurt pushes. Until then, "green Windows CI" in this brief means the local equivalents, and the report marks the CI rows "not run — awaiting push". After a push, read the runs with `gh run view` and record the run URLs in a follow-up evidence update.
   - For any UI change, run the targeted isolated GUI recipe and wait for the process to exit. Launching is not success. Read the JSON, inspect the screenshots, and classify warnings as pre-existing (for example the `GUIApplication::notify` access violation in `docs/STEP_IMPORT.md`) or new.
   - Use real clicks for selection. Schedule menu inspection before clicking an InstantPopup.
   - For increments with budgets, also run the native suite with `KURTSHAPE_PERF=1` on Kurt's machine (§7.4).
8. **Clean tree.** `git status --porcelain` must be empty after the checks, apart from your staged increment files. No test or tool may write tracked files.
9. **Commit.**
   - One focused commit per increment (increment 0: up to 5 commits, each with green `run-checks`, reported once), with an imperative subject of 45–75 characters in the existing style ("Implement …", "Add …", "Fix …").
   - Stage only increment files. Do not use `git add -A` when other work is present.
   - Do not push.
10. **Report to Kurt** in the format of §7.7.

### 7.3 Commands (Windows PowerShell, repo root)

```powershell
$FC = "runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin"

# Full regression gate (after increment 0)
.\run-checks.ps1                     # sources if the Onshape examples exist, then all native/bridge/shortcut/workflow suites
.\run-checks.ps1 -Full               # also requires the external Onshape examples (0 skips)
.\run-checks.ps1 -WriteEvidence      # refresh tracked validation JSON
.\run-checks.ps1 -Lint               # ruff check if ruff is on PATH

# Local reproduction of the CI jobs (added in increment 0; the workflow calls the same scripts)
.\tools\ci\run-local.ps1             # layout check, native tests with CI env, clean-tree check, 20-hole bench

# Single entry point used by run-checks and CI
& "$FC\python.exe" -B tools\run_native_tests.py --require-native
& "$FC\python.exe" -B tools\run_native_tests.py --suite native --report runtime\reports\native.json --junit runtime\reports\junit.xml

# Evidence (added in increment 0)
& "$FC\python.exe" -B tools\record_evidence.py --slug <slug> --from runtime\reports\native.json [--bench runtime\bench\bench-60.json] [--gui <report.json>]

# Performance (increment 0 harness; increment 1 adds the gated StatusPerformanceTests)
& "$FC\python.exe" -B tools\perf\bench_core.py --holes 60 --scratch runtime\bench --out runtime\bench\bench-60.json
& "$FC\python.exe" -B tools\perf\report.py runtime\bench\bench-60.json --baseline <previous bench-60.json> --phase phase0 [--enforce]
$env:KURTSHAPE_PERF = '1'; & "$FC\python.exe" -B tools\run_native_tests.py --suite native; Remove-Item Env:KURTSHAPE_PERF

# Isolated hidden GUI recipes (never Kurt's window)
.\validate-review-gui.ps1 -Scenario interaction     # existing: copy|lifecycle|recovery|interaction|startup|baseline|step|assembly (returns a PID)
.\tools\run_gui_recipe.ps1 -Recipe interface -TimeoutSeconds 600   # added in increment 0; blocking, exit code reflects the report
```

Until increment 0 lands, `run-checks.ps1` (`run-checks.ps1:1-20`) runs `tools/inventory_sources.py`, `tools/validate_sources.py`, `tools/validate_offline.py` and the bridge and shortcut unittest discovery with `bin\python.exe -B`. The two source steps need `..\..\Onshape examples`.

For every grep gate in this brief, use `git grep -n "<text>" -- <paths>`, which searches tracked files only. A plain `grep -r` also matches stale `__pycache__/*.pyc` files.

### 7.4 Evidence and benchmarks

- **Fixture.** The 60-hole plate: 600 × 600 × 12 mm with 60 through holes on an 8 × 8 grid, pitch = 600/(ceil(√N)+1) = 66.67 mm, hole diameter 0.45 × pitch (Ø30 mm); 132 objects, 66 faces. This is exactly the layout of `docs/2026-10-03-claude-review/evidence/bench_core.py:64-76`; tip edits there set the diameter to 0.40–0.42 × pitch (`bench_core.py:85`).
- **Builder.** Build it with the native API and one recompute (`tests/perf_fixture.py:build_plate`, added in increment 1; 12–13 s), with the same layout and diameters. Building it through dispatch takes 65 s.
- **Benchmark scope.** `tools/perf/bench_core.py --holes N` measures controller hot paths through `Controller.dispatch`. `tools/perf/bench_gui.FCMacro` measures GUI paths.
- **Hardware.** Record every budget measurement with the machine, FreeCAD/OCCT versions and commit.
- **Wall-clock assertions are opt-in.** Every wall-clock budget assertion in a test is skipped unless `KURTSHAPE_PERF=1`, with a skip reason starting `perf:`. `run_native_tests.py --require-native` treats that prefix as allowed. Counter and structural assertions (0 BRepChecks, 0 `saveCopy`, `evaluations == 2`, exactly one app filter) always run.

### 7.5 Assistant contract rules

- **Contract 2 was semantic** (`request_id` required). It bumped `capabilities.contract` (`core.py:584`) and the session file (`bridge.py:81`) and added a doc section.
- **The Assembly increment was additive.** It added a `capabilities.assembly` key with no bump. Follow the same rule:
  - **Increment 0:** add a new stdlib-only module `src/kurtshape/contract.py` with `CONTRACT_VERSION = 2` and `CONTRACT_REVISION = 0`. Both `core.py:584` and `bridge.py:81` import from it. (`bridge.py` is FreeCAD-free and its tests use a `DummyController`; do not import the constants from `core.py`.)
  - **Increment 1:** bump to **Contract 3**. Changes:
    - `measure` envelope field;
    - `measurements.valid` becomes null until checked;
    - new `check_geometry` op;
    - export can fail with `invalid_geometry`;
    - open no longer rebuilds, and reports `rebuild_reason`.

    Add a "## Contract 3 — October 2026 upgrade" section to `docs/OPERATION_CONTRACT.md` and update README "Assistant access" (`README.md:66`).
  - **Later changes** (additive ops, and the semantic ones: extrude preview no longer clones, live-link insert default, async import/export, linked-source edits advancing the assembly revision) are listed under Contract 3 with `CONTRACT_REVISION += 1` and a "Contract 3.N additions" subsection.
- **Expected revision sequence.** Each new op's registry `since` equals its increment's value. If an increment not in this table turns out to change the contract, bump there and shift the later values; a registry test asserts `max(since) == f"3.{CONTRACT_REVISION}"`.

  | Increment | Contract | New `since` values |
  |---|---|---|
  | 1 | 3.0 | `check_geometry` = 3.0 |
  | 2 | 3.0 (no bump; registry rollout) | `describe_operations` = 3.0 |
  | 3 | 3.0 (GUI evaluator only; no bump) | — |
  | 4 | 3.1 | `extrude` |
  | 6 | 3.2 | (extrude New/Intersect) |
  | 6b | 3.3 | `edit_extrude` |
  | 8 | 3.4 | `set_tip`, `suppress_feature`, `reorder_feature` |
  | 9b | 3.5 | (async import/export, STL presets) |
  | 10 | 3.6 | variable ops, `evaluate_expression` |
  | 13 | 3.7 | (live insert default) |
  | 14 | 3.8 | `measure`, `mass_properties` |
  | 15 | 3.9 | pin/unpin/relink/update ops |
  | 16 | 3.10 | (joint types and parameters) |
  | 17 | 3.11 | sub-assembly, BOM, exploded-view ops |

- **Unchanged:** `request_id`, `expected_revision` and ledger semantics.
- No Claude client is connected yet (`README.md:66`), so the cut-over is cheap but must be documented. Flag schema changes for Claude review in the plan.
- Do not build the MCP server unless Kurt assigns it. The registry's `tool_definitions()` is as far as you go.

### 7.6 Stop and ask Kurt when

- The git state is not a clean fast-forward, or the tree has unexplained local changes.
- A change would modify files outside the repo or any original source.
- A global install, a new dependency or a FreeCAD runtime change seems needed.
- Disk space runs short. Delete only verified reproducible caches, and record it.
- A gate fails twice for a named reason and needs a scope decision.
- An existing test assertion that this brief does not list as Updated would have to be changed, removed or skipped. Stop, report the failing assertion and the behavior that conflicts with it, and wait.
- The live-link design hits a case not covered here: cross-document live links, STEP sources linked live, unsaved owner, moved or missing external sources beyond what is specified.
- A contract change would break `tools/assistant_client.py` users beyond Contract 3.
- Assistant write-root scoping (REVIEW P1-12) is needed; implement the §4.3 proposal only after his OK.
- Work needs Kurt's hands-on walkthrough or real-part sign-off.
- You would push, open a PR, publish, register a self-hosted runner, or message or assign work to Claude. (Ask in the report instead; see §7.7.)
- Kurt's deferred edited STEP variants are needed. Continue independent work meanwhile, and do not re-ask.

### 7.7 Report format at the end of each increment

1. Increment name and commit hash.
2. What works (bullets).
3. Evidence table: suite/recipe → passed/total → report path. CI rows read "not run — awaiting push" until Kurt pushes.
4. Budget table: metric | before | after | target | fixture | machine.
5. Contract changes (contract and revision).
6. Docs updated, and stale statements removed.
7. Limits, unverified items probed (with results), and pre-existing warnings.
8. "M1 remains incomplete; real parametric conversions remain 0/2."
9. Push request: "May I push `main` to origin?" (increment 0 also: "and push a throwaway branch `ci-clean-tree-probe` for the negative clean-tree check, then delete it?").
10. Steps for Kurt:
    - save and close the older window;
    - launch `KurtShape.cmd`;
    - then 5–8 concrete actions to try.

## 8. Increments

Order: 0 (foundation), then alternating speed (S) and feature (F) increments. Estimated days are guidance only.

### Increment 0: Foundation. Windows CI, test hygiene, runtime path, P1-11/P2-13/P2-15 fixes, perf harness, lint (≈ 4.5 days)

**Goal.** An automated Windows gate (reproducible locally), tests that never dirty the tree, a portable runtime path, the one real UI crash and two small contract bugs fixed, and a performance trend. Everything later builds on this.

**Scope and design.** Commit in this order, as one increment of up to 5 commits; each must pass.

1. **Assembly path (P1-9).**
   - In `src/kurtshape/assembly.py:23`, replace the hard-coded path with `NATIVE_PATH = Path(App.getHomePath()).resolve() / "Mod" / "Assembly"`. Use `.resolve()` because `getHomePath()` returns a trailing separator, doubled on Linux.
   - Add `PINNED_FREECAD = ("1","1","4")`. At the top of `_native()` (`assembly.py:41`), raise `assembly_runtime` ("KurtShape requires the pinned FreeCAD 1.1.4 runtime", `found=…`) when `tuple(App.Version()[:3]) != PINNED_FREECAD`. Keep the check that `JointObject.__file__` lies inside `NATIVE_PATH`.
   - In `tools/assembly-native-probe.py`, move `import FreeCAD as App` (line 11) above the `RUNTIME` line (line 9), then set `RUNTIME = Path(App.getHomePath()).resolve()` before the `sys.path.insert` (line 10). A literal one-line replacement at line 9 raises `NameError`.
   - On Windows this resolves to exactly today's path. That is inferred from the archive layout, not executed on Windows: verify it with the new test below.
2. **P1-11 hotfix in `Panel.tick`.** Reproduced 5/5 under Xvfb: after an unattached document becomes active and the managed one is re-activated, every tick raises `AttributeError: 'NoneType' object has no attribute 'get'`.
   - In `src/kurtshape/ui.py`, change the early-return guard (around line 862) to `if self.state is not None and not processed and not self.core.needs_refresh(doc) and self.last_document == doc.Name:`.
   - In the `elif self.state is not None:` branch (around 881–891), after `self.state = None`, add `self.last_document = self.last_status = None`.
   - Add a regression check to `tools/gui-review-validation.FCMacro`:
     1. `App.newDocument('NativeOnly')`, activate it, tick.
     2. `App.setActiveDocument(managed)`, tick ×3.
     3. Assert no exception and that `panel.state['document_id']` is the managed id.
3. **Contract constants.** New `src/kurtshape/contract.py` (stdlib only) with `CONTRACT_VERSION = 2` and `CONTRACT_REVISION = 0`. Use them at `core.py:584` and `bridge.py:81`.
4. **P2-13 and P2-15.**
   - P2-13: `number()` (`core.py:46-50`) says "must be a finite number in mm" for angle parameters. Use the target unit in the message.
   - P2-15: the bridge compares the whole `Content-Type` header (`bridge.py:32`) and so rejects `application/json; charset=utf-8`. Compare only the media type (`split(";")[0].strip().lower() == "application/json"`), still rejecting any `Origin` header.
5. **`tests/support.py` (new, stdlib).**
   - `ROOT`.
   - `EXTERNAL_SKIP_PREFIX = "external fixture:"`, `PERF_SKIP_PREFIX = "perf:"`, and a `perf_only(testcase)` helper that skips unless `KURTSHAPE_PERF == "1"`.
   - `WRITE_EVIDENCE` (env `KURTSHAPE_WRITE_EVIDENCE == "1"`).
   - `EXTERNAL_EXAMPLES` (env `KURTSHAPE_ONSHAPE_EXAMPLES`, else `ROOT.parents[1]/"Onshape examples"`).
   - `TEST_TMP`: env `KURTSHAPE_TEST_RUN_DIR` if set; else `(KURTSHAPE_TEST_TMP or tempfile.gettempdir()/"kurtshape-tests")/run-<stamp>-<pid>`, created and resolved.
   - `scratch(testcase, prefix)`: `TemporaryDirectory(dir=TEST_TMP, ignore_cleanup_errors=True)`, cleaned up via `addCleanup`.
   - `isolated_session(testcase, prefix)`:
     - writes `settings.json = {"project_roots": [str(TEST_TMP)]}`, which is the existing grant mechanism in `settings.py:17-21`;
     - patches `KURTSHAPE_SESSION_DIR`;
     - must be called before `Controller()`.
   - `ungranted_scratch(testcase, roots, prefix)`:
     - candidates, in order: `KURTSHAPE_TEST_OUTSIDE`, `tempfile.gettempdir()`, `ROOT.parents[1]`;
     - uses the first existing directory not under any root;
     - otherwise calls `skipTest("environment: …")`. This reason is not an external skip, so CI fails.
   - `external(*names)`, `requires_external(*filenames)` (skip reason starts with `external fixture:`), `evidence_dir(name)`.
   - Do **not** add any env var that widens `write_path` roots.
6. **Per-test edits.** Keep every assertion. Change only temp locations, sessions and skip guards.
   - `tests/test_core.py`:
     - `setUp` (17–19) calls `isolated_session` before `Controller()`.
     - Line 54 uses `support.evidence_dir("core-acceptance")`.
     - The `__main__` block (103) writes via `evidence_dir`.
   - `tests/test_bridge.py`: `create()` (46–52) uses `support.scratch`.
   - `tests/test_core_safety.py`:
     - `isolated_session` in `setUp`.
     - Lines 57, 73 and 97 use `dir=support.TEST_TMP`.
     - Lines 59, 75 and 99 assert `any(p.is_relative_to(r) for r in self.core.settings.roots)` instead of `is_relative_to(ROOT)`.
   - `tests/test_onshape.py`: `isolated_session` in setUp (before 122). Line 191 uses `TEST_TMP`. Line 193 asserts on the roots.
   - `tests/test_sketch_planes.py`: setUp (before 20). Lines 93, 307 and 339 use `TEST_TMP`.
   - `tests/test_assembly.py` (24–29, 37–38), `tests/test_extrusion_preview.py` (20–24, 34–35), `tests/test_review_followup.py` (25–30, 37–38), `tests/test_step_import.py` (22–27, 35–36): replace the TemporaryDirectory + `patch.dict` block with `self.folder = support.isolated_session(self, prefix=…)`. Remove the now-unused imports.
   - `tests/test_review_followup.py:248-257` (`test_user_granted_project_folder_persists_and_bridge_cannot_self_grant`): use `support.ungranted_scratch(self, self.core.settings.roots, …)`.
   - Add `@support.requires_external("Dodec pipe mount.step", "Dodec Hub Conformal.step")` and `support.external(...)` to:
     - `test_assembly.py:323` `test_original_three_solid_steps_insert_explicit_bodies_and_preserve_sources`;
     - `test_assembly.py:368` `test_original_steps_insert_directly_as_three_solid_choices`;
     - `test_step_import.py:57` `test_real_three_solid_parts_preserve_geometry_source_and_native_roundtrip`.
   - New `tests/test_runtime_layout.py` with `RuntimeLayoutTests`:
     - `test_pinned_engine_versions`;
     - `test_assembly_module_comes_from_running_runtime`;
     - `test_other_runtime_version_is_rejected` (patches `App.Version` to `['1','2','0','x']` and expects `assembly_runtime`);
     - `test_scratch_never_targets_tracked_folders`;
     - `test_capabilities_report_shared_contract_constant` (`capabilities.contract == contract.CONTRACT_VERSION`).
   - Add to `tests/test_core_safety.py`: `test_number_error_names_target_unit` (an angle parameter error names deg/rad, not mm; P2-13).
   - Add to `tests/test_bridge.py` (FreeCAD-free, `DummyController`):
     - `test_rejects_missing_token_wrong_path_origin_header_non_json_and_oversize` (403/403/403/403/413, and the controller is never called);
     - `test_accepts_json_media_type_with_charset` (P2-15);
     - `test_session_file_reports_shared_contract_constant`.
7. **`tools/run_native_tests.py` (new, stdlib, run with `bin\python.exe`).**
   - Suites:
     - `native`: `test_core.NativeCoreTests`, `test_onshape.NativeConversionTests`, `test_onshape.PreflightTests`, `test_core_safety.CoreSafetyTests`, `test_sketch_planes.SketchPlaneTests`, `test_navigation.SketchProjectionTests`, `test_review_followup.ReviewFollowupTests`, `test_step_import.StepImportTests`, `test_assembly.AssemblyWorkflowTests`, `test_extrusion_preview.ExtrusionPreviewTests`, `test_runtime_layout.RuntimeLayoutTests`, plus every new test class added by later increments;
     - `bridge`: `test_bridge.BridgeTimeoutTests` (and any new bridge class);
     - `shortcuts`: `test_shortcuts.RouterTests`, `test_shortcuts.QtRoutingTests`;
     - `workflows`: `tools/validate_modeling_workflows.py`, judged by exit code.
   - CLI: `--suite` (repeatable), `--report`, `--junit`, `--require-native`, `--require-external`, `--timeout` (default 1800 s per suite), `--keep-temp`, and a hidden `--in-process NAME`.
   - Parent process:
     1. Set `PYTHONDONTWRITEBYTECODE=1`, `QT_QPA_PLATFORM=offscreen`, `FREECAD_USER_HOME` and `KURTSHAPE_TEST_RUN_DIR` before any FreeCAD import.
     2. Run each suite in a fresh child process.
     3. Aggregate results and write JSON, JUnit and `$GITHUB_STEP_SUMMARY`.
     4. Fail on a nonzero child exit, or under `--require-native` on any skip whose reason starts with neither `external fixture:` nor `perf:`. Under `--require-external`, fail on any external skip.
     5. Remove the run dir on success.
   - The native child denies networking exactly as `validate_offline.py:16-21` does (patch `socket.socket.connect`, `create_connection`, `getaddrinfo`).
   - Write the legacy `validation/offline-test-result.json` only with `KURTSHAPE_WRITE_EVIDENCE=1`.
   - `tools/validate_offline.py` becomes a shim that runs `run_native_tests.py --suite native`.
   - `tools/validate_modeling_workflows.py` takes its run base from `KURTSHAPE_TEST_RUN_DIR`, writes a `settings.json` grant before `Controller()`, and reports through the evidence helper.
8. **Evidence policy for tools and macros.**
   - New `tools/kurtshape_evidence.py` with `evidence_dir(name)`. Resolution order:
     1. `KURTSHAPE_WRITE_EVIDENCE=1` → `ROOT/validation/name`;
     2. else `KURTSHAPE_EVIDENCE_DIR/name`;
     3. else `KURTSHAPE_SESSION_DIR/evidence/name`;
     4. else `ROOT/runtime/evidence/name`.
   - Also add `external_examples()` and `require_external()` (exit 2).
   - Route every `validation/` write in `tools/*.py` and the GUI `*.FCMacro` files through it. Readers of GUI reports read from the same place (`validate_review_recovery.py:11`, `validate_assembly_reopen.py:40`).
   - `inventory_sources.py` and `validate_sources.py` exit 2 with a clear message when the examples folder is missing or empty. Today they overwrite tracked JSON with `[]`.
   - `gui-validation.FCMacro:69` uses `os.environ["KURTSHAPE_SESSION_DIR"]`.
   - `sketch-behavior-validation.FCMacro:216` must tolerate a missing `runtime/user-data/user.cfg`.
   - Launch and validate scripts get a `-WriteEvidence` switch; otherwise they set `KURTSHAPE_EVIDENCE_DIR=<session>\evidence`. Print correct report paths.
   - New `tools/record_evidence.py` (stdlib): `--slug <slug> --from <run_native_tests report> [--bench …] [--gui …]`. It writes `validation/2026-10-03-upgrade/<slug>/<name>.json` with the keys of §7.2 step 4.
9. **`run-checks.ps1` rewrite.**
   - Parameters: `-Full`, `-WriteEvidence`, `-Lint`.
   - Set `KURTSHAPE_TEST_TMP=runtime\test-tmp`, and `FREECAD_USER_HOME`/`TEMP` under `runtime\`.
   - Run the source tools only when the examples folder exists. With `-Full`, a missing folder is an error; otherwise warn that 3 real-part tests are skipped.
   - Run `tools\run_native_tests.py --require-native`, adding `--require-external` with `-Full`.
   - Run optional ruff.
10. **`install-runtime.ps1` hardening.**
    - Add `param([string]$RuntimeRoot = (Join-Path $PSScriptRoot 'runtime'))` and derive the download, temporary and extract paths from it. The default behavior is unchanged.
    - Set `$ProgressPreference='SilentlyContinue'` before `Invoke-WebRequest`.
    - Find 7-Zip via `$env:KURTSHAPE_7Z`, then `(Get-Command 7z.exe -ErrorAction SilentlyContinue).Source`, then `C:\Program Files\7-Zip\7z.exe`.
    - Keep the hash check before extraction.
    - Test it locally only with `-RuntimeRoot runtime\install-test` (copy the cached archive into its `downloads\` first), then delete that folder. Never re-extract over `runtime\freecad-1.1.4` (invariant 11).
    - Hosted runner images list 7-Zip on PATH (image source). The exact path is **unverified**.
11. **`tools/ci/` scripts (new) and `.github/workflows/windows-ci.yml`.**
    - `tools/ci/check-runtime-layout.ps1 [-RuntimeRoot]`: asserts `bin\{python.exe,freecadcmd.exe,freecad.exe,FreeCAD.pyd,opengl32sw.dll}`, `Version()[:3]==['1','1','4']`, `OCC_VERSION=='7.8.1'`, `Mod/Assembly/JointObject.py` under the home path, and prints `['1','1','4'] 7.8.1 <home>`.
    - `tools/ci/assert-clean-tree.ps1`: `git status --porcelain --ignored=matching --untracked-files=normal`; the only allowed ignored line is `!! runtime/`; any other line fails.
    - `tools/ci/run-local.ps1`: runs the layout check, `run_native_tests.py --require-native` with `KURTSHAPE_TEST_TMP`/`KURTSHAPE_TEST_OUTSIDE`/`FREECAD_USER_HOME` under `runtime\ci-local`, the clean-tree check, and `bench_core.py --holes 20`.
    - The workflow:
      - Triggers: push to main, pull_request, nightly schedule, workflow_dispatch.
      - `defaults.run.shell: pwsh`. `git config --global core.autocrlf false` before checkout.
      - Jobs:
        - **`lint`** (windows-latest): setup-python 3.11, `pip install ruff==0.16.10` into the runner's Python (not the FreeCAD runtime), `ruff check --output-format=github .`.
        - **`native-tests`** (matrix windows-latest and windows-2022):
          - `actions/cache` of `runtime/downloads/FreeCAD_1.1.4-Windows-x86_64-py311.7z`, keyed `freecad-win64-<sha256>`;
          - `./install-runtime.ps1`;
          - `tools/ci/check-runtime-layout.ps1`;
          - `run_native_tests.py --require-native` with `KURTSHAPE_TEST_TMP`/`KURTSHAPE_TEST_OUTSIDE`/`FREECAD_USER_HOME` under `runner.temp`;
          - "Repository stays clean": `tools/ci/assert-clean-tree.ps1`;
          - upload reports.
        - **`perf`** (windows-2025, `needs: native-tests`, `continue-on-error: true`): 20 holes per push, 60 nightly; baseline restored from cache and saved on main.
        - **`gui-recipes`** (nightly or manual, `continue-on-error`, `QT_OPENGL=software`): matrix over `run_gui_recipe.ps1` recipes.
12. **`tools/run_gui_recipe.ps1` (new, blocking).**
    - Recipe map:
      - `interface`→`gui-validation.FCMacro`
      - `ui-refinement`→`ui-refinement-validation.FCMacro`
      - `extrusion-preview`→`extrusion-preview-validation.FCMacro`
      - `sketch-behavior`→`sketch-behavior-validation.FCMacro`
      - `review-interaction`→`gui-review-validation.FCMacro`
      - `review-lifecycle`→`sketch-lifecycle-validation.FCMacro`
      - `review-copy`→`general-actions-validation.FCMacro`
      - `messages`→`messages-validation.FCMacro`
      - `assembly`→`assembly-gui-validation.FCMacro`
      - `bench-gui`→`tools/perf/bench_gui.FCMacro`
    - Session under `runtime\ci-gui\<recipe>`. Several macros assert that the session is under `root/runtime`.
    - Same env isolation as `validate-review-gui.ps1` (`KURTSHAPE_ROOT`, `KURTSHAPE_SESSION_DIR`, `FREECAD_USER_HOME`, `TEMP`/`TMP`, `APPDATA`, `LOCALAPPDATA`, `-u`/`-s`). Remove `Env:KURTSHAPE_DEMO` so `ui.start()` does not open the example (`ui.py:2050`); the app ignores `KURTSHAPE_NO_DEMO`.
    - `Start-Process -WindowStyle Hidden -PassThru`, then `WaitForExit(timeout)`, killing the process on timeout.
    - Then require the report's `passed` to be true.
    - Whether hosted runners can render the FreeCAD viewport (desktop session, software GL) is **unverified**. This job is informational. If it fails, report it and propose a self-hosted runner, which needs Kurt's approval.
13. **Perf harness `tools/perf/`.**
    - `bench_core.py` is a parameterized move of `docs/2026-10-03-claude-review/evidence/bench_core.py`, and `bench_gui.FCMacro` a parameterized move of the evidence `bench_gui.FCMacro` (output path via `kurtshape_evidence`, run through `run_gui_recipe.ps1 -Recipe bench-gui`, not xvfb). Leave the evidence copies untouched as a historical record.
    - Arguments: `--holes` (default 20), `--repeat 3`, `--out`, `--scratch`, `--sections edits,inspect,checkpoint,preview,open`.
    - Same fixture layout as §7.4 (diameter 0.45 × pitch).
    - Session isolation with a `settings.json` grant.
    - Each section is wrapped in try/except and records `status: ok|unavailable`, so later internal changes degrade instead of crashing.
    - The inspect-after-change metric uses a native edit (`doc.Pad.Length += 0.5` in a transaction) followed by one inspect.
    - The preview profile sits at `(pitch/2, pitch/2)`, diameter `min(20, 0.3·pitch)`. The original `(300,300)` falls inside a hole at N=20 (verified).
    - Metrics:
      - `add_sketch.*`, `add_pocket.*`;
      - `tip_edit.{total,overhead,native_recompute}_ms`, `upstream_edit.*`;
      - `inspect_warm_ms`, `inspect_after_change_ms`;
      - `checkpoint_ms`;
      - `preview_first_ms`, `preview_update_ms`;
      - `native_open_ms`, `kurtshape_open_ms`.
    - `budgets.json`:
      - phase0: `tip_edit.overhead_ms ≤ 150`, `inspect_after_change_ms ≤ 20`;
      - phase1: `tip_edit.overhead_ms ≤ 50`, `inspect_after_change_ms ≤ 20`, `preview_first_ms ≤ 50`, `checkpoint_ms ≤ 16`.
    - `report.py` prints a Markdown table. Budgets are evaluated only at ≥ 60 holes, and the exit code is 1 only with `--enforce`.
    - Every later increment that replaces an internal API (`Controller.timings` `native_recompute` at `core.py:231`, `Controller.checkpoint` at `core.py:221`, `ExtrusionEvaluator`) updates this harness in the same commit.
14. **Lint-only ruff.**
    - `ruff.toml`:
      ```toml
      required-version = "==0.16.10"
      target-version = "py311"
      line-length = 160
      extend-include = ["*.FCMacro"]
      extend-exclude = ["runtime", "validation", "docs/2026-10-03-claude-review/evidence"]

      [lint]
      select = ["F", "E9", "PLE"]
      unfixable = ["F401"]
      ```
    - Fix the 17 findings at HEAD with no behavior change:
      - add `# noqa: F401` for side-effect imports: `assembly.py:44` Assembly, `bodies.py:2` FreeCAD, `extrusion_preview.py:17` Part, `test_shortcuts.py:105`, `assembly-native-probe.py:13`, and the PySide/pivy imports in `assembly-step-validation:36`, `toolbar-validation:9`, `viewport-actions-validation:13`, `extrusion-preview-validation:15`, `navigation-validation:11`;
      - delete unused stdlib imports: `general_actions.py:12` Path, `validate_live_bridge.py:4` Path, `general-actions-select-other-probe:5` sys, `review-recovery-crash:6` time;
      - delete `test_core.py:13` `metadata`;
      - `core.py:830`: ruff's F841 here is a **false positive** caused by the rebinding `exc = rollback_error` at `core.py:851`; `exc` is used at 861, 862 and 871. Change line 830 to `except Exception as caught:` and make `exc = caught` the first statement of the handler, so the rebinding and later uses are unchanged. **Do not** remove the binding: `except Exception:` makes every rejected operation raise `UnboundLocalError` instead of returning `{ok: false}` (verified on a scratch copy);
      - `appearance-validation.FCMacro:435`: drop the unused `compact` binding but keep the call.
    - No formatting churn in this increment.
15. **`.gitattributes`.**
    ```
    *.FCStd binary
    *.step -text
    *.stp -text
    *.stl -text
    *.png binary
    ```
16. **Docs.** Create `docs/2026-10-03-claude-review-follow-up/UPDATE_PLAN.md` and `IMPLEMENTATION.md` with the baseline. Update `README.md:69-77` (the new `-Full`/`-WriteEvidence`/`-Lint` switches, conditional source checks, evidence under `<session>\evidence` unless `-WriteEvidence`), `docs/INTERFACE_PASS.md:21-23` and `docs/STEP_IMPORT.md:16` (use `tools\run_native_tests.py --suite native`).

**Tests.**
- Added: `tests/test_runtime_layout.py` (5 tests), 1 in `test_core_safety.py`, 3 in `test_bridge.py`.
- Updated: the temp/session/skip edits above. All assertions are kept.

**Acceptance.**
- Local (`tools\ci\run-local.ps1` on Kurt's machine):
  - the layout check prints `['1','1','4'] 7.8.1` and a home ending in `FreeCAD_1.1.4-Windows-x86_64-py311`;
  - `run_native_tests.py --require-native` reports native 95 passed (89 existing + 6 new) and 3 skipped with `external fixture:` reasons, bridge 7/7, shortcuts 22/22, workflows passed (405 checks);
  - the clean-tree check prints only `!! runtime/`; a deliberate local write into `validation/` makes it fail (verify once, then restore).
- On Kurt's machine:
  - `.\run-checks.ps1 -Full` with the examples present gives native 98/98, 0 skips.
  - Without the examples it warns and passes with 3 external skips.
  - Neither modifies tracked files.
- `git grep -n "FreeCAD_1.1.4-Windows" -- src` returns nothing.
- The 17 non-external `AssemblyWorkflowTests` pass.
- The P1-11 GUI check passes in `.\validate-review-gui.ps1 -Scenario interaction`.
- `bench_core.py --holes 20` writes `bench-20.json` with all metric names and sections `ok` (Linux prototype: 29 s at 20 holes).
- `ruff check .` (0.16.10) passes, and the diff has no formatting-only churn.
- `install-runtime.ps1 -RuntimeRoot runtime\install-test` extracts from the cached archive and passes `check-runtime-layout.ps1 -RuntimeRoot runtime\install-test`; the folder is then deleted.
- **CI (pending push).** After Kurt pushes: both native-tests legs green with the same counts; the second run restores the archive from cache, install < 3 min, native-tests job < 15 min per leg; the throwaway-branch negative test fails the clean-tree step; the lint and perf jobs pass. Record these in a follow-up evidence update.

**Evidence.** `validation/2026-10-03-upgrade/foundation/` holds the local run-checks and run-local results and the bench-60 baseline on Kurt's machine (this is the "before" column for all later budgets); CI run URLs are added after the push.

**Risks and fallbacks.**
- Hosted GUI rendering may fail. The job is informational.
- A cache miss re-downloads 418 MB.
- Windows TemporaryDirectory cleanup races are handled by `ignore_cleanup_errors`.
- If `getHomePath()` differs on Windows, which `test_runtime_layout` would show, stop and report before changing anything else.

### Increment 1 (S): Fast build status, explicit geometry checks, open without rebuild (P0-1, P0-3, decision 1). Contract 3 (≈ 5 days)

**Goal.** Interactive status costs milliseconds. BRepCheck runs only on request, at export and at import boundaries. Opening a file trusts stored BReps.

Today the 60-hole plate spends (`bench-core-60-holes.json`):
- 1.87 s in BRepCheck per body (`isValid`);
- 2.33 s in the full `measurements()` per body;
- whole-document cache invalidation on any shape change;
- about 12.7 s of touch-all + recompute on open.

**Scope.**
- New module `src/kurtshape/geometry.py`. This is the **only** module that runs BRepCheck or mass integration (import boundaries keep their existing `isValid()` calls).
- `src/kurtshape/core.py`:
  - `measurements` (157–165);
  - `READ_OPS`/`ARGS`/`OPS` (169–205);
  - `Controller.__init__` (207–219, `evaluations` at 214);
  - `_geometry` (257–274), `_evaluated_shape` (285–292);
  - `attach`/`sync` (294–323, 351–364);
  - `_build_status` (479–499), `inspect`/`_inspect` (501–550);
  - the dispatch envelope (580), capabilities (583–599), final inspect (815);
  - open/recover (626–672: touch + recompute at 642–646);
  - the MODEL_OPS branch (766–789), `_preview` (889–940), `_adopt` (942–967), `_import_step` (969–1049);
  - pad/pocket `cut_valid` (1273–1307), rebuild (1384–1387), `_export` (1420–1452), `metadata` (71–82).
- `src/kurtshape/document_state.py` (11–13, 22–34, 36–40, 62–67).
- `src/kurtshape/extrusion_preview.py` (19, 115, 195–206, 216–220).
- `src/kurtshape/ui.py`:
  - inspect and dispatch call sites 531, 559, 867, 917, 931, 934, 1603;
  - the status line (1049–1052; also 958, 872–876, 1103);
  - the model bar (355–356);
  - `Panel.measure` (1896–1911).
- `src/kurtshape/general_actions.py` (70, 262).
- `docs/OPERATION_CONTRACT.md` and `README.md:66`.

**Design.**

1. **`geometry.py`.**
   - Levels:
     ```python
     LEVELS = {
         False: (),
         True: ("bbox", "volume", "area"),
         "full": ("bbox", "volume", "area", "center_of_mass"),
     }
     ```
   - `bounding_box(shape)` returns `{min, max, size}`.
   - `center_of_mass(shape)`: over `shape.Solids` (F27): one `CenterOfMass` for a single solid; volume-weighted over solids otherwise.
   - `check_shape(shape, details=True)` returns `{valid, issues, ms}`. It calls `shape.isValid()`. Only when invalid, it calls `shape.check(False)` and parses the `ValueError` lines, dropping "No error".
   - `COMPUTE` maps each field to its function.
   - `class GeometryCache(observer, shape_of=assembly.global_shape, dependencies_of=Controller._shape_dependencies)`:
     - `key(obj)` = tuple of `(doc, name, observer.version(doc, name))` for the object and its dependencies, plus the source `Shape.hashCode()`. Versions guard against hashCode reuse when OCCT frees a shape.
     - `check_key(obj)` = `(source doc, source name, source version, source hashCode)`. Validity is placement-invariant, so repeated occurrences share a verdict.
     - `facts(obj, fields)` computes only missing fields, always including `solid_count = len(source.Shape.Solids)`. It counts work in `stats['computed'][field]`.
     - `check(obj, compute=False)` returns the cached verdict, or None. With `compute=True` it runs `check_shape` and caches the verdict.
     - Also `seed(obj, field, value)`, `drop_document(name)`, `documents()`.
   - `measurement_dict(facts, check)` returns `{valid: None|bool, solid_count, volume_mm3, area_mm2, bbox_mm, center_of_mass_mm}`. Fields not computed are None.
   - `aggregate(facts_list, checks)`: sums, bbox union, volume-weighted centre; `valid = all(checks)`, or None if any is unchecked.
2. **Controller.**
   - Replace `self.evaluations` with `self.geometry = geometry.GeometryCache(...)`, created before `DocumentState`, and add `self.default_measure = True`.
   - Add `_shape_dependencies(obj)`: for an `App::Link` with a `LinkedObject`, return `[obj.LinkedObject] + assembly.assemblies(obj.Document)`; otherwise `[]`.
   - Add `_measure_level(m)`: accepts exactly `True`, `False` or `"full"`, else `invalid_argument`. None means the default.
   - Add `_volume(obj)`.
   - Delete `Controller.evaluations` and its pops (`core.py:938`, `document_state.py:66`, `extrusion_preview.py:219`). Use `geometry.drop_document`.
   - `measurements()` (157–165) stays as an explicit full-measurement helper for detached shapes, built on `check_shape`/`COMPUTE`. Tests and `tools/assembly-step-validation.FCMacro:39,192` use it. Nothing interactive calls it.
3. **Per-object versions (`document_state.py`).**
   - `state()` gains a `versions` dict. `version(doc, name)` returns 0 when unknown.
   - Bump an object's version on its own `Shape`, `InternalShape`, `Placement`, `LinkPlacement`, `LinkedObject` or `Group` change, and on create and delete. Keep the existing invalidate call.
   - Keep `generation` only for `assembly._source_fingerprints` (`assembly.py:698-708`) and the extrusion snapshot.
   - `slotDeletedDocument` calls `controller.geometry.drop_document`.
4. **`_build_status`** (replace the BRepCheck loop at 490–494):
   ```python
   errors = assembly.validation_errors(doc, generation)  # unchanged
   for obj in doc.Objects (skip METADATA):
       flags = set(obj.State)
       # Touched on a modeling TypeId → pending
       # Invalid/Error → errors.append({feature, message: obj.getStatusString()})
       # missing: Up-to-date, _expects_shape(obj), obj.Shape.isNull()  (cheap, F7)
   for obj in native_results(doc):
       # skip null / solid-less shapes; solid = True
       # cached verdict invalid → errors.append({feature, message: 'Invalid solid (geometry check)', issues})
   status = ('failed' if errors
             else 'needs_rebuild' if pending or missing or meta.RebuildReason
             else 'valid' if solid
             else 'sketch_only')
   ```
   - Write `meta.BuildStatus` only on change.
   - `sync(doc)` returns the errors, and `_inspect` uses them (computed once, not at both 505 and 543). Compute `native_results` once per inspect.
5. **Contract 3 inspect.**
   - `inspect(doc, measure=None)`.
   - `measurements` is filled per level when `BuildStatus=='valid'`. `retained_geometry_measurements` is filled when the status is `failed` or `needs_rebuild`.
   - New top-level fields:
     - `rebuild_reason`: None | `engine_changed` | `saved_by_other_build` | `engine_unrecorded` | `missing_shapes`;
     - `geometry_check`: `not_applicable` | `not_checked` | `valid` | `invalid`.
   - Per body: `geometry_check`.
   - `measurements.valid` = the cached verdict, or null.
   - Envelope field `measure` is accepted at `core.py:580`, validated once per request, part of the canonical ledger payload, and passed to `list_documents` and the final inspect.
   - capabilities: `contract: 3` (via `contract.py`), plus:
     - `measurement: {levels:[false,true,"full"], default, fields}`;
     - `geometry_check: {operation:"check_geometry", export:"required", interactive:"native feature state only"}`.
   - The default stays `measure: true` for API, assistant and test callers, so `state["measurements"]["volume_mm3"]`, `area_mm2`, `bbox_mm` and `solid_count` keep working. `center_of_mass_mm` now needs `"full"`.
6. **New read op `check_geometry`** (`READ_OPS`, args `{"body"}`, no `expected_revision`).
   - Targets: solid results, or the one named (`missing_body`/`no_solid`).
   - `geometry.check(obj, compute=True)` for each target, then `_build_status` so an invalid verdict flips the status to `failed`.
   - Result: `{status: valid|invalid, revision, engine, bodies:[{id, valid, issues, check_ms}], ms}`, attached to the final inspect as `geometry_check_report`.
   - Verdicts are cached per shape, so a repeat costs nothing.
7. **Export gate.**
   - After the existing BuildStatus gate (1422), compute `verdicts = {obj.Name: self.geometry.check(obj, compute=True) for obj in included}`.
   - If any verdict is invalid: call `_build_status`, then raise `OperationError("invalid_geometry", "Geometry check failed; nothing was exported", features=[{feature, issues}])` before staging any file.
   - Provenance `shape = self._geometry(doc, included, "full")`, plus `geometry_check: {status:"valid", bodies:[{id, check_ms}]}`.
8. **Pocket `cut_valid`** (1296–1299):
   - `prior_volume = self._volume(body)` (pocket only).
   - `cut_valid` = `not s.isNull() and len(s.Solids)==1 and not set(feature.State) & {'Error','Invalid'} and self._volume(body) < prior_volume - 1e-7`.
   - Keep the auto-reverse retry. Empty cuts are not flagged natively (F6).
9. **`extrusion_preview.py`.**
   - Remove `material.isValid()` (203).
   - Replace `measurements(shape)` (206) with `geometry.measurement_dict({...solid_count, volume, bbox})`.
   - Cleanup calls `geometry.drop_document`.
   - Increment 3 replaces this evaluator anyway.
10. **Open without rebuild.**
    - Replace the touch + recompute at `core.py:642-646` with `self._rebuild_reason_on_open(doc)`. Keep the assembly solve-on-open block (647–654) as it is; increment 13 owns it.
    - `_expects_shape(obj)`: True for a Body with a Tip, a sketch with non-construction geometry, or a non-suppressed PartDesign feature; but **False** when `set(obj.State) & {'Touched','Invalid','Error'}`, and False for a Body whose Tip carries any of those flags. A feature that had already failed when saved reopens with a null Shape (F1); it reports `failed` through its flags, not `missing_shapes`.
    - `_rebuild_reason_on_open` runs `ensure_engine_properties(meta)` (adds `EngineFreeCAD`, `EngineOCCT`, `RebuildReason` as read-only strings in group KurtShape), then picks the first matching **persisted** reason:
      1. `engine_changed` if a stored stamp differs from `engine_stamp() = ('.'.join(App.Version()[:3]), Part.OCC_VERSION)`.
      2. `saved_by_other_build` if `doc.getProgramVersion() != f"{v[0]}.{v[1]}R{v[3]}"`.
      3. `engine_unrecorded` if no stamp is stored.
      4. Otherwise the persisted reason.
    - `missing_shapes` is **not persisted**. `_build_status` computes it live from the cheap `isNull` scan (an Up-to-date object for which `_expects_shape` is True has a null Shape) and reports it as `rebuild_reason` when no persisted reason applies. It clears itself once the shapes exist.
    - Write the reason only on change. In the GUI, store `Gui.getDocument(doc.Name).Modified` before `ensure_engine_properties`/the reason write during open and restore it afterwards (F28), so merely opening a legacy file does not prompt to save.
    - `_mark_rebuilt(doc)` stamps the engine and clears `RebuildReason`. Call it inside the rebuild op's transaction (dispatch MODEL_OPS branch, after the recompute, before `_build_status`).
    - `metadata()` stamps the engine on creation only for `new` and `import_step`, whose shapes were just computed by this engine.
    - **`_adopt` (`core.py:942-967`) does not rebuild today**: it does `saveCopy` → `App.openDocument` → `metadata(clone)` → `_recompute(clone)` (which recomputes only the Touched metadata object) → attach → save. Do not add an implicit rebuild. After `metadata(clone)`, call `_rebuild_reason_on_open(clone)` with one adopt-specific rule: stamp the engine when `ProgramVersion` equals this runtime's build string and no expected shape is missing; otherwise leave `saved_by_other_build` (or the live `missing_shapes`) so the adopted copy needs one Rebuild before export. This keeps `test_unmanaged_inspection_and_adoption_preserve_original_and_native_ids` (a same-build file; asserts `volume_mm3 == 48` after adopt) unchanged.
    - The recover path (655–672) is unchanged in this increment.
11. **GUI.**
    - One `Panel.MEASURE = False` used by every inspect and dispatch (`ui.py` 531, 559, 867, 917, 931, 934, 1603; `general_actions.py:70`).
    - Status line:
      - valid: `"{n} solid(s)"`, plus `" · {v:,.2f} mm³"` when the volume is measured, plus `" · checked"` when the check is valid;
      - needs_rebuild: `"Rebuild required · <reason text>"`, notified once on open;
      - failed: "Build failed", or "Invalid geometry — see Messages".
    - Add a "Check geometry" tool beside Rebuild (`ui.py:355`, icon `Part_CheckGeometry`). It calls `operation("check_geometry")` under a wait cursor and lists per-body issues in Messages.
    - `Panel.measure()` with no selection calls `inspect(doc, measure="full")` and reports the active Body's volume, area and centre of mass.
12. **Docs.**
    - Add the "Contract 3" section.
    - Rewrite `OPERATION_CONTRACT.md` lines 5, 12, 27, 36, 63 ("BRep validity is cached until geometry/recompute invalidation" is now false), 65 ("Open freshly rebuilds native features" is now false) and 90, plus `README.md:66`.

**Tests.**
- Updated:
  - `tests/test_onshape.py` `NativeConversionTests.assert_volume`: replace `assertTrue(state['measurements']['valid'])` with `assertIn(state['geometry_check'], {'not_checked','valid'})`, then dispatch `check_geometry` and assert status `valid`, revision unchanged and `measurements.valid` True.
  - `tests/test_review_followup.py` `test_idle_inspection_uses_cached_intent_and_brep_then_native_edit_invalidates`: spy on `geometry.check_shape` (0 calls throughout). `geometry.stats['computed']` stays unchanged over 25 idle inspects and the pending Touched inspect, then goes up by exactly +1 `volume` after the recompute.
  - `tests/test_assembly.py` `test_idle_inspection_does_not_resolve_sources_or_run_native_solver`: spy on `kurtshape.geometry.check_shape`, with stats unchanged over 25 inspects.
  - `tests/test_extrusion_preview.py` `invariant` helper (line 59): `tuple(sorted(self.core.geometry.documents()))` instead of `tuple(self.core.evaluations)`.
  - GUI macros:
    - `tools/gui-review-validation.FCMacro:90-93` spies on `geometry.check_shape`/stats;
    - `tools/gui-validation.FCMacro:179` becomes "Saved native features reopen valid without rebuild", asserting no `native_recompute` samples during open and GUI `Modified` False after opening;
    - `tools/general-actions-validation.FCMacro:141` calls `rebuild` first;
    - `tools/assembly-step-validation.FCMacro:205-233` reads from `panel.core.inspect(doc, measure=True)`;
    - `tools/extrusion-preview-validation.FCMacro:57` uses `core.geometry.documents()`.
- Added: new `tests/test_build_status.py`, `BuildStatusTests`:
  - `test_interactive_operations_never_run_brepcheck`;
  - `test_check_geometry_reports_invalid_solid_and_export_rejects_it` (bow-tie `Part::Feature` → `invalid` with "Self-intersecting wire", `build_status` failed);
  - `test_export_checks_once_per_shape_and_rechecks_after_change`;
  - `test_export_rejects_invalid_geometry_before_writing`;
  - `test_measure_levels_and_per_object_cache`;
  - `test_open_trusts_stored_shapes_without_recompute`;
  - `test_open_with_different_engine_offers_rebuild_and_blocks_export`;
  - `test_open_legacy_project_without_engine_stamp_is_unrecorded`;
  - `test_open_persisted_touched_and_failed_states_without_rebuilding` (a saved failed Pocket of Length 0 reopens as `build_status` `failed` with `rebuild_reason` None; then `set_parameter Length=2` gives `valid` without Rebuild);
  - `test_open_missing_stored_shape_offers_rebuild` (remove `Pad.Shape.brp` from the archive → `missing_shapes`; Rebuild clears it);
  - `test_open_saved_by_other_program_build_offers_rebuild` (rewrite the `ProgramVersion` attribute inside `Document.xml`);
  - `test_adopt_of_file_saved_by_other_build_requires_rebuild` (rewrite `ProgramVersion`, adopt, assert `rebuild_reason == 'saved_by_other_build'` and export rejected until Rebuild);
  - `test_capabilities_contract_3_reports_measurement_and_check_policy`.
- Added: `StatusPerformanceTests` (wall-clock; skipped unless `KURTSHAPE_PERF=1`), using new `tests/perf_fixture.py` `build_plate`:
  - `test_open_does_not_rebuild`;
  - `test_idle_and_post_change_inspection_budget`;
  - `test_tip_edit_overhead_budget`;
  - `test_explicit_check_and_measure_cost_reported`.

  Each prints one `PERFREPORT {json}` line.
- Kept unchanged: `test_core.py` (both), `test_core_safety.py` (all existing), the listed `test_sketch_planes.py` and `test_review_followup.py` tests (including `test_unmanaged_inspection_and_adoption_preserve_original_and_native_ids`), and the assembly reopen/STEP tests. External-fixture aggregate tolerances (1e-9/1e-10 relative, now sums of per-body integrations) are **unverified**. Run them on Kurt's machine with `-Full`.

**Acceptance.** All on the 60-hole fixture, `measure=false`, on Kurt's machine. Linux prototype values are in parentheses.
- Dimension-edit overhead ≤ 150 ms (59 ms; HEAD 5.3 s).
- Add-pocket overhead ≤ 300 ms (238 ms; HEAD 12,419 ms total).
- Inspection after an operation-driven change ≤ 20 ms (14.2 ms).
- Idle inspection ≤ 20 ms (13.5 ms).
- Open overhead ≤ max(300 ms, 10 % of native open), with zero `native_recompute` samples during open (115 ms on a 1,913 ms native open).
- The `check_shape` spy records 0 calls across new, `sketch_rectangle`, `sketch_circle`, pad, pocket, `set_parameter`, `set_expression`, undo, redo, `finish_sketch_edit`, inspect, `Panel.tick` and checkpoint.
- Bow-tie: `check_geometry` → `invalid` + "Self-intersecting wire" + `failed`. Export then rejects, leaving neither the file nor the `.json` sidecar.
- STEP then STL of the same shape runs BRepCheck once, and once more after an edit. Provenance has `geometry_check.status 'valid'`, `shape.valid true` and `center_of_mass_mm`.
- Editing one of two Bodies raises `stats['computed']['volume']` by exactly 1.
- An `EngineOCCT` mismatch gives `needs_rebuild`/`engine_changed`, `measurements` null with retained values, and export rejected. Rebuild restores valid and the stamp. Undo restores the reason.
- A project saved with a failed feature reopens as `failed` (not `needs_rebuild`), and fixing the feature returns it to `valid` without Rebuild.
- `capabilities.contract == 3`. A `measure` value outside {false, true, "full"} gives `invalid_argument`.
- All suites green with only the listed test updates. The listed GUI recipes pass.
- `bench_core --holes 60`: `tip_edit.overhead_ms` and `inspect_after_change_ms` meet the phase0 budgets. Turn on `--enforce --phase phase0` for the nightly perf job only after 5 stable samples (after Kurt pushes).

**Risks.**
- Invalid-but-unflagged PartDesign geometry is now caught only at export or by Check geometry.
- Callers that relied on `measurements.valid` after every mutation see null; this is documented under Contract 3.
- Legacy files need one Rebuild (12.7 s at 60 holes).
- The API default `measure:true` costs about 106 ms per changed body. Assistants may pass `false`.
- Native undo leaves restored objects Touched, and the controller's post-undo recompute still costs 761 ms at 60 holes. That is out of scope here; note it.

### Increment 2: Operation registry (enabler for every new typed op) (≈ 4 days)

**Goal.** One source of operation metadata. It produces today's op sets exactly, runs per-op guards, transaction policy and postconditions, and generates capabilities, `describe_operations` and assistant tool schemas.

**Scope.**
- New `src/kurtshape/operations.py` (stdlib only, no FreeCAD import).
- `core.py`:
  - the op sets and `ARGS` (168–205);
  - `_dispatch` (566–878);
  - capabilities (583–593);
  - `_model_operation` (1226–1398) arms become `_op_*` methods.
- `bridge.py:81` (the session file adds `read_operations` and `contract_revision`; keep `controller.READ_OPS` at `bridge.py:43`).
- `tools/assistant_client.py:16` (use `session['read_operations']` with the static set as fallback; add `--list-tools`).
- `ui.py` op-set uses at 844, 897, 899, 904, 910, 912, 926, 943, 949, 960.

**Design.**
- Data classes:
  ```python
  @dataclass(frozen=True)
  class Guards:
      document: bool
      revision: bool
      managed: bool
      busy: bool
      lease: str          # 'reject' | 'allow_target' | 'any_document_reject' | 'none'
      lease_target: str | None
      native_edit: str    # 'reject' | 'allow_managed_sketch' | 'none'
      owns_busy: bool

  @dataclass(frozen=True)
  class Operation:
      name: str
      category: str       # read | create | model | sketch | history | assembly | disk
      summary: str
      properties: dict    # JSON Schema fragments
      required: tuple
      one_of: tuple
      handler: str
      guards: Guards
      transaction: str    # 'none' | 'model' | 'assembly' | 'custom'
      undo_label: str
      accepts_body: bool
      tracked: bool
      result: str         # 'inspect' | 'handler'
      postcondition: str  # 'none' | 'build' | 'one_solid' | 'one_solid_if_solid_tip' | 'history' | 'assembly'
      preview: str | None # 'clone' | 'overlay' | 'evaluate'
      gui_feedback: str
      lease_allowed: bool
      since: str
  ```
- `Registry` methods:
  - `get`, `names`;
  - `legacy_sets()` gives `READ_OPS`/`ASSEMBLY_OPS`/`MODEL_OPS`/`EDIT_OPS`/`CREATE_OPS`/`OPS`. `MODEL_OPS` covers category model with `since=='2.0'` only, so `ui.py:926` body injection never sees new ops;
  - `legacy_args()`;
  - `request_schema(name)`;
  - `check(request)`, which raises `unsupported_operation`, `unknown_argument` or `invalid_argument`;
  - `describe()`, `tool_definitions()` (`kurtshape_<name>`).
- An in-repo subset validator (about 100 lines): `type` (bool is not number; numbers finite), `const`, `enum`, `pattern`, `min/maxLength`, `minimum`/`maximum`, `required`, `properties`, `additionalProperties: false`, `items`, `min/maxItems`, `uniqueItems`, `anyOf`.
- Register all existing ops (43 at HEAD, `since='2.0'`, plus `check_geometry` from increment 1 with `since='3.0'`) with exactly today's argument names (`core.py:177-205`). `Q(unit)` accepts number or string; semantic parsing stays in `core.number()`. `describe_operations` is `since='3.0'`.
- Migration that keeps every test green:
  - **M0.** `tests/test_operation_registry.py` with literal copies of the sets and `ARGS` as they are after increment 1, and `test_legacy_operation_sets_and_args_match_contract_2_snapshot`. Name it as listed even though the contract is now 3; it pins the legacy derivation.
  - **M1.** Add `operations.py`. The Controller sets and `ARGS` are derived from it. Schema validation runs in **shadow** mode, counting mismatches in diagnostics.
  - **M2.** Split `_dispatch` behavior-identically, moving code verbatim:
    - `_resolve`;
    - `_check_global_guards` (607–615);
    - `_check_document_guards` (677–703);
    - `_transaction_policy` (`model` = 767–789, `assembly` = 747–765);
    - `_postcondition`;
    - `_finish` (815–829);
    - `_failure` (830–875).

    The split must preserve the HEAD check order exactly (`core.py:552-564` and `576-703`):
    1. ledger register/replay (only when `request_id` is present; a replay returns before any later check, including `stale_revision`);
    2. `unsupported_operation` (577–578);
    3. `unknown_argument` (580–582);
    4. read-op early returns (583–606);
    5. `busy` for non-read ops (607–608);
    6. CREATE_OPS lease and native-edit checks (609–615);
    7. `unknown_document` via `_doc` (674);
    8. preview (675–676);
    9. `unmanaged_document` (677–678);
    10. `stale_revision` (680–682);
    11. `busy` (683–684);
    12. `sketch_edit_active`/`managed_sketch_mismatch` (685–691);
    13. assembly native edit (694–695);
    14. native-edit `sketch_edit_active` (696–701);
    15. the handler.

    Then switch to **enforcing** validation. Schema errors take the slot of `unknown_argument` (step 3). `open` without `path` becomes `invalid_argument` (P2-14).
  - **M3.** `ui.py` reads registry metadata (`gui_feedback`, category, `accepts_body`).
  - **M4/M5.** New ops land in later increments with `since` from the §7.5 table. Add `tools/export_operation_schemas.py`, which writes `docs/operation-schemas.json`, and a test that keeps it current.
- `capabilities` keeps every existing key and value and adds `contract_revision`, `operation_schema_version: 1`, and the new read op `describe_operations`.
- The `history` postcondition additionally rejects any object left Touched in the affected body after recompute (`build_failed`, "Could not rebuild in this order"). This is needed because FreeCAD leaves cycle members Touched rather than in Error (F22).
- Also fix the duplicate-id fallback (default in §4.3): `pad`/`pocket` without `id` (`core.py:1051-1057`, `1280`) pick the next free `Pad`/`Pocket002`-style id.

**Tests.**
- Added, all in `tests/test_operation_registry.py`:
  - `test_legacy_operation_sets_and_args_match_contract_2_snapshot`;
  - `test_every_operation_has_handler_schema_category_and_guards`;
  - `test_schema_validation_maps_unknown_missing_and_wrong_types_without_mutation`;
  - `test_capabilities_keeps_contract_2_keys_and_lists_registry_operations`;
  - `test_describe_operations_and_tool_definitions_cover_every_operation`;
  - `test_generated_schema_file_is_current`;
  - `test_since_values_match_contract_revision` (`max(since) == f"3.{CONTRACT_REVISION}"`).
- Kept: everything else, notably `test_request_replay_precedes_stale_revision_and_never_repeats_undo`, `test_invalid_inputs_and_failed_publication_leave_current_project_intact`, `test_import_rejects_active_lease_and_busy_operations`, `test_replay_stale_unknown_arguments_and_invalid_inputs_do_not_mutate`, `test_queued_timeout_cancels_before_any_mutation` and `test_stale_native_edit_and_failure_rollback`.

**Acceptance.**
- All suites pass unchanged after each of M0–M3.
- Shadow mode records 0 mismatches across the whole suite before enforcement is enabled.
- `len(describe_operations.operations) == len(capabilities.operations)` = registry size.
- capabilities keeps every previous key and value.
- No op-set literal remains in `ui.py` (`git grep -n 'op in {' -- src/kurtshape/ui.py` is empty).

**Risks.** Splitting the 310-line `_dispatch` is the riskiest refactor. Use the snapshot test, shadow mode and verbatim moves.

### Increment 3 (S): Preview v2. Fast tool prism, no clone (P0-2) (≈ 4 days)

**Goal.** Today every preview evaluation saves the live project, reopens it, runs the real Pad/Pocket, rebuilds, validates and runs a boolean (`extrusion_preview.py:151-224`): 15.7 s for the first evaluation and 15.1 s for each later one on the 60-hole plate. Replace this with a ghost of the tool prism that never touches the document.

**Scope.**
- New `src/kurtshape/extrude.py` (pure App/Part, no Qt), with legacy `pad`/`pocket` normalization only in this increment.
- `extrusion_preview.py`:
  - `ExtrusionResult` (22–33);
  - `_guard` (102–121);
  - `_proposal` (123–149);
  - `evaluate` (151–224);
  - `CoinExtrusionOverlay.show` (235–313);
  - `DebouncedExtrusionPreview` (316–427).
- `document_state.py`: add `suspended`.
- `ui.py`:
  - `Panel.extrude`/`extrusion_proposal`/`begin_preview`/`schedule_preview`/`preview_status` (1560–1635);
  - `accept_task` (1637–1689; drop the synchronous flush at 1651–1652).
- No contract change (the assistant `preview` op is rerouted in increment 4).

**Design.**
- **`extrude.normalize_extrude(controller, doc, request)`** returns a JSON-safe dict with sorted keys and floats rounded to 1e-9. It is both the cache key and the Confirm payload.
  - Legacy `pad` → `{operation:"add", end:"blind", length, reversed}`.
  - Legacy `pocket` → `{operation:"remove", end:"through_all" if through_all (default True) else "blind", …}`.
  - Validate types exactly as `extrusion_preview.py:131-145` does.
  - `profile = controller._profile(...)`. No closed wires, or any open wire, raises `open_profile` ("Sketch must contain a closed profile").
  - `body = controller._body(...)` (`cross_body_reference` as today). Remove needs a solid, else `missing_body`.
  - For remove with `reversed` omitted, set it explicitly with `default_remove_reversed()`: `(tip_bbox_center - O)·n > 0`. O is a point inside the profile face (the centroid of its first tessellation triangle) and n is the world sketch normal.
  - The normalized proposal always carries an explicit `reversed`. The controller keeps the legacy auto-flip (`core.py:1300-1305`) only for raw requests that omit `reversed`.
- **`tool_prism(spec, geo)`** returns `(tool_shape, display_shape)` in world coordinates.
  - Profile face: `Part.Face(w)` for one wire, else `Part.makeFace(wires, "Part::FaceMakerBullseye")` (F10). Placement = `sk.getGlobalPlacement()*sk.Placement.inverse()*shape.Placement`.
  - `n` = global sketch normal. `d = n` for add/new/intersect, `-n` for remove. `-d` if `reversed`.
  - `L1` = length, or `geo.native_through_length` (2.02 × tip bbox diagonal), or a planar up-to distance (increment 4).
  - Symmetric: `face.translated(-d*L1/2).extrude(d*L1)`. Otherwise `face.extrude(d*L1)`.
  - Through-all display shape: `face.extrude(d*through_far(d))`, with `through_far(d)` = the max of `(corner−O)·d` over the 8 tip bbox corners + 1e-3.
- **Emptiness.** If the max projection of the tip bbox corners on d (relative to O) is ≤ 1e-7, or the prism bbox does not overlap the tip bbox, the error is `empty_cut` (remove). No booleans (F12).
- **Geo cache.** Per task: the profile face per profile name, and the tip bbox, through lengths and centre per body. BoundBox costs about 9 ms per access and is uncached.
- **`ExtrusionResult`** (frozen): `valid`, `base_revision`, `proposal`, `body_id`, `tool_shape`, `display_shape`, `path` ("fast" | "native" | "provisional"), `measurements = {tool_volume_mm3, tool_bbox_mm}`, `warnings`, `error`, `cached`, `milliseconds`. Remove `shape` and `material_shape`.
- **`ExtrusionEvaluator`.**
  - `_guard` keeps the closed/open/busy/managed/revision/sketch-edit/native-edit guards and calls `core.sync` only when `observer.state(doc)["intent_dirty"]`.
  - LRU of 8 entries keyed by the normalized JSON. `self.evaluations` counts uncached evaluations.
  - It never calls `saveCopy`, `openDocument`, `newDocument` or `doc.recompute()`.
- **`DocumentState.suspended`.** A `suspended` set plus a `suspended(doc)` context manager. Every slot returns early for suspended documents; this must be an attribute check inside each slot (F11). Increment 4 uses it.
- **`CoinExtrusionOverlay` v2.**
  - Scene: `SoSeparator[SoPickStyle UNPICKABLE, SoDepthBuffer x-ray for remove/intersect (test=false, write=false, function ALWAYS, as at 252–260), SoTransform xf, SoShapeHints, SoMaterial, SoCoordinate3 + SoIndexedFaceSet of the UNIT prism face.extrude(d*1.0), unit-prism edge outline only]`.
  - `set_depth(L, offset_back)` sets `xf.center = O`, `xf.scaleOrientation = SbRotation((0,0,1), d)`, `xf.scaleFactor = (1,1,L)`, `xf.translation = -d*offset_back`. This costs 0.04–0.09 ms with an exact bbox, verified.
  - Rebuild the mesh only when profile, operation, direction, draft or end family changes.
  - Deflection = `clamp(profile_diag*0.002, 0.05, 0.5)`.
  - Colours: add (0.25,0.72,0.96), remove (0.96,0.48,0.20), new (0.30,0.78,0.45), intersect (0.62,0.45,0.90). Transparency 0.38; provisional 0.8.
- **`DebouncedExtrusionPreview` v2.**
  - `schedule()` normalizes synchronously.
  - Invalid → clear the ghost and set the error status.
  - Equivalent to the current valid result → keep it. Keep the behavior at 356–372, for example "7 mm" vs "7.00 mm".
  - Fast end → evaluate now. When only the length changed, call `set_depth`.
  - `current_result(proposal)` returns the result for an equal normalized proposal at an unchanged revision.
  - Keep the 200 ms lifetime timer.
- **`accept_task`** dispatches exactly `result.proposal` plus `id` and `_expected_revision=result.base_revision`, with no synchronous re-evaluation.
- **Confirm equivalence.** `world(created.AddSubShape)` must equal `result.tool_shape` within 1e-6 relative volume and 1e-6 mm bbox.
- **Benchmark.** Update `tools/perf/bench_core.py` `preview_*` to the new evaluator.

**Tests** (`tests/test_extrusion_preview.py`).
- Updated:
  - `test_initial_pad_quantity_reverse_cache_and_cancel_are_disposable`: tool volume `20*10*3.175`, ZMin 0/−3.175, `path=='fast'`, cached, `evaluations==2`; drop the `_snapshot` folder assertions; keep `invariant()`.
  - `test_attached_pad_and_blind_through_all_pockets_match_actual_acceptance`: tool volumes π·4·2; `through.display_shape.Volume == π·4·6`; reversed through-all → `empty_cut`; after accept compare `world(doc.Accepted.AddSubShape)` with `blind.tool_shape`; keep UndoCount+1 and Length 2.
  - `test_origin_plane_pocket_follows_default_direction_and_reversed_changes`: `automatic.proposal['reversed'] is True`; the opposite direction → `empty_cut`.
  - `test_second_body_preview_uses_profile_owner_and_world_placement`: `result.tool_shape` volume 60, XMin 40, XMax 43; keep `body_id=='Housing'` and the cross-body mismatch.
  - `test_bad_text_missing_profile_open_geometry_and_stale_task_keep_live_model`: the open-profile code becomes `open_profile`.
- Added:
  - `test_preview_never_saves_or_opens_documents` (patch `App.openDocument`/`App.newDocument`/`Document.saveCopy`/`Document.recompute` to raise);
  - `test_first_evaluation_budget_on_60_hole_plate` (one-sketch native 60-hole plate; `evaluate()` ≤ 10 ms; second depth update ≤ 5 ms; wall-clock, `KURTSHAPE_PERF=1` only).
- Added: `tests/test_document_state.py` `test_suspended_document_state_ignores_preview_callbacks`.
- Kept: `test_geometry_edits_history_and_fresh_relocation`, `test_stale_native_edit_and_failure_rollback`, `test_face_attachment_follows_upstream_thickness_and_cuts_inward`, `test_explicit_pocket_direction_is_respected_and_auto_origin_cut_works`.
- GUI macros:
  - `tools/extrusion-preview-validation.FCMacro`:
    - evaluation counting replaces the debounce check (L90, L121, L135, L138, L153);
    - keep the invariant snapshot (L48–57), the unpickable ghost (L102), the x-ray depth buffer (L127–129), the lifetime clears and the timers;
    - add a first-frame check: ≤ 50 ms including one synchronous `gl.repaint()`.
  - `tools/ui-refinement-validation.FCMacro` extrusion section (123–145, 362–466): tool/display volumes (1400, 1600, π·4·7, π·4·2), ZMin −7, select the end type by text.

**Acceptance** (60-hole plate, single Ø20 circle profile).
- Blind, Reverse and Through all: `evaluate()` ≤ 10 ms headless (0.42–1.13 ms). First GUI frame ≤ 50 ms including one synchronous repaint (5.9–8.5 ms Python + 16–26 ms render, software GL).
- Depth change ≤ 5 ms, with no re-tessellation and no document access.
- Before Confirm, all of these are unchanged: UndoCount/RedoCount, HasPendingTransaction, object list, `Body.Tip`, Body BRep, intent signature, revision, BuildStatus, visibility, selection, camera, GUI Modified, `App.listDocuments()`, observer generation.
- Committed `AddSubShape` equals `tool_shape` (1e-6). Each Confirm is one undo step.
- An out-of-band revision change clears the ghost within 250 ms and disables Confirm. A stale accept is rejected with `stale_revision` and no change.
- Legacy `pad`/`pocket` requests and the core, sketch-plane and Onshape suites are unchanged.

**Risks.**
- The ghost shows the tool, not the resulting body. This is deliberate: an exact boolean costs about 0.4 s and holds the GIL.
- The default Remove direction heuristic can pick the empty side. The user flips, and Confirm rejects empty cuts.

### Increment 4 (F): Unified `extrude` contract, native end conditions, native-path preview (≈ 5 days)

**Goal.** One typed `extrude` operation covering operation add/remove (New/Intersect come in increment 6) and every native end condition except Up to part, with offsets, draft and second end. Preview the up-to conditions exactly without leaving a trace.

**Scope.**
- `extrude.py`: `OPERATIONS`, `ENDS`, `ALLOWED_ENDS`, `SECOND_ENDS`, `NATIVE_TYPE`, `normalize_extrude` (full), `apply_extrude`, `face_reference`, `up_to_binder`, `execute_extrude`.
- Registry: `extrude` (category model, `accepts_body`, postcondition `one_solid`, preview `overlay`, `since='3.1'`).
- `core.py`:
  - `_model_operation` pad/pocket branch (1273–1305) routes through `execute_extrude`;
  - the one-solid check (783–785) includes `extrude`;
  - `_preview` (889–940) routes `extrude`/`pad`/`pocket` to `ExtrusionEvaluator` (`set_parameter`/`set_expression` keep the clone, §4.3);
  - `native_parameters` (85–99) and `set_parameter` (1309–1339);
  - `_sketch_support` (1077–1112): extract `face_reference`;
  - `_inspect` gains an `extrude` block.

**Design.**
- End rules:
  ```python
  ALLOWED_ENDS = {
      "add":       {"blind", "symmetric", "up_to_next", "up_to_last", "up_to_face"},
      "new":       {"blind", "symmetric", "up_to_face"},
      "remove":    {"blind", "symmetric", "through_all", "up_to_next", "up_to_face"},
      "intersect": {"blind", "symmetric"},
  }
  SECOND_ENDS = {
      "add":       {"blind", "up_to_next", "up_to_last", "up_to_face"},
      "new":       {"blind"},
      "remove":    {"blind", "through_all", "up_to_next", "up_to_face"},
      "intersect": {"blind"},
  }
  NATIVE_TYPE = {
      "blind": "Length", "symmetric": "Length", "through_all": "ThroughAll",
      "up_to_next": "UpToFirst", "up_to_last": "UpToLast",
      "up_to_face": "UpToFace",
  }
  ```
  - `up_to_part` is **deferred** (§10): within one body it equals up to next/last, a cross-body one needs a binder with first-hit semantics that has not been probed, and a whole binder with an empty subelement list gives a silently empty Valid result (F9). `up_to_part` gives `unsupported_end_condition`.
  - A disallowed end gives `unsupported_end_condition`.
  - `length` is positive for blind and symmetric.
  - `offset` is allowed only for `up_to_*`.
  - `draft` is in rad, |draft| < 89°, and allowed with blind, symmetric and second ends.
  - `second` = `{end, length, offset, up_to, draft}`. `second` combined with symmetric is `invalid_argument`.
  - `up_to` = `{feature, subelement}` via `face_reference`.
- **`face_reference(doc, body, ref, allow_planes)`** is moved from `core.py:1086-1112` without the planar requirement.
  - Body + FaceN resolves to the Tip (the existing convention at `core.py:1092-1095`).
  - Allowed objects: anything in the doc's PartDesign Bodies (`bodies.bodies(doc)`), the Origin features, or a `PartDesign::Plane`.
  - Datum planes take subelement `""`. Solids take `Face\d+` in range.
  - It returns `(obj, element, owner_body)`.
- **Cross-body up-to faces need a binder** (F9). Writing a foreign body's face directly into `UpToFace` is evaluated in the foreign body's local frame and gives wrong geometry. When `owner_body` differs from the feature's body (always the case for New):
  - inside the same transaction, **before** creating the Pad/Pocket, create `binder = body.newObject("PartDesign::SubShapeBinder", id + "UpTo")` with `Support=[(owner_body, (f"{tip_or_feature.Name}.{element}",))]`;
  - set `UpToFace=(binder, ['Face1'])`; hide the binder in the GUI;
  - include the binder in the delete cascade, inspect (`extrude.up_to.binder`) and the Confirm-equivalence check.
  - Same-body faces and datum planes are written directly.
- **`apply_extrude(feature, spec, doc)`** sets `SideType`, `Type`, `Type2`, `Reversed`, then the values, in that order:
  - symmetric → `SideType="Symmetric"`;
  - second → `SideType="Two sides"`, `Type2`, `Length2`/`UpToFace2`/`Offset2`/`TaperAngle2`;
  - `up_to_face` → `UpToFace=(obj,[element])`, `Offset`;
  - draft → `TaperAngle = degrees(draft)`.

  Never write `Midplane`, and leave `Refine` alone. The same function is used in the preview's native path and in the controller.
- **`execute_extrude` for add/remove.**
  - Create any up-to binder first, then the feature with `body.newObject("PartDesign::Pad"|"PartDesign::Pocket", id)`, set `Profile`, call `apply_extrude`, recompute.
  - Remove keeps the volume-based `cut_valid` (increment 1).
  - Add needs added volume > 1e-7, else `empty_extrude`. This also catches any silently empty up-to result.
  - It runs inside the existing single dispatch transaction.
- **Native path preview** (up_to_next, up_to_last, non-parallel or curved up_to_face, any cross-body up_to_face, two-sided draft, non-blind second end):
  - `core.busy = True` and a re-entrancy flag.
  - Inside `with core.observer.suspended(doc)`:
    1. `doc.openTransaction("KurtShape preview")`;
    2. any up-to binder, then `body.newObject(...)` → `apply_extrude`;
    3. `ok = f.recompute()` (never `doc.recompute()`);
    4. copy only `f.AddSubShape` (0.5 ms);
    5. in `finally`: `doc.abortTransaction()`; `body.purgeTouched()` if Touched; restore the GUI document `Modified`.
  - Then compare `(UndoCount, RedoCount, object names, Body.Tip)` with the values from before. On any difference, call `observer.invalidate(doc)` and raise `preview_leak`.
  - A failure maps to `build_failed` carrying `f.getStatusString()`.
  - The first frame is a provisional ghost (≤ 50 ms): the prism to the far side of the tip bbox (or the face bbox), at 0.8 transparency with a dashed outline. The native evaluation runs after a 350 ms pause. Confirm does not wait for it.
- **Fast path additions.**
  - A planar same-body up_to_face parallel to the profile plane (`|n·d| > 1-1e-9`): `L = (P_face−O)·d + offset`.
  - One-side draft via `tapered()` (F10), falling back to the native path on any exception.
  - Second blind end: `face.translated(-d*L2).extrude(d*(L1+L2))`.
- **Parameters.**
  - `native_parameters` exposes `Length2` (Two sides + Type2 Length), `Offset`/`Offset2` (UpTo types) and `TaperAngle`/`TaperAngle2` (unit rad, value `radians(TaperAngle)`). Pocket ThroughAll still exposes no Length.
  - `set_parameter` uses a whitelist `{Length, Length2, Offset, Offset2, TaperAngle, TaperAngle2}` and converts rad to deg for taper. This replaces `feature.Length=value` at `core.py:1339`.
- **Inspect** adds `features[].extrude = {operation, end, length, reversed, side_type, type2, length2, offset, draft, up_to}` for Pad and Pocket.
- **capabilities.** `preview_operations` gets `pad`, `pocket` and `extrude` (it keeps `set_parameter`, `set_expression`). Add an `extrude` block with operations, ends per operation and units (`length: mm`, `draft: rad`). `CONTRACT_REVISION` → 1 (3.1). This is where "extrude preview no longer clones" lands for assistants; list it under Contract 3.1.

**Tests.**
- Added to `tests/test_extrusion_preview.py`:
  - `test_fast_path_end_conditions_match_committed_native_tool` (blind, reversed, symmetric, second blind, through_all, ±10° draft, ring and nested-island profiles, multi-region: path fast, then the committed `AddSubShape` matches within 1e-6, then undo; the ≤ 10 ms bound only under `KURTSHAPE_PERF=1`);
  - `test_up_to_conditions_use_native_path_without_trace`;
  - `test_native_path_failure_reports_native_status` ("No faces found in this direction");
  - `test_planar_parallel_up_to_face_uses_fast_path`.
- Added in new `tests/test_extrude_contract.py`:
  - `test_extrude_operations_map_to_native_properties` (add and remove only for now);
  - `test_extrude_argument_validation` (through_all with add, up_to_last with remove, up_to_part with any operation, symmetric + second, offset with blind, draft ≥ 89°, non-positive length, unknown end/operation);
  - `test_cross_body_up_to_face_uses_binder_and_world_geometry` (a foreign Body placed at z=30: the AddSubShape Z range ends at the foreign face in world coordinates, the binder precedes the Pad in `Group`, one undo step removes both);
  - `test_set_parameter_length2_offset_taper`.

**Acceptance.**
- Native-path ends show a provisional ghost within 50 ms, and the exact tool within 1.5 s on the 60-hole plate after the pause (UpToFirst 0.89–1.25 s measured).
- The full no-trace snapshot holds, including observer generation under suspension. `core.busy` is False afterwards.
- `AddSubShape` matches `tool_shape` for every end.
- Cross-body up-to faces give world-correct geometry through a binder; no "out of the allowed scope" warning appears in the log.
- Legacy pad and pocket are unchanged.

**Risks.**
- UpToFace references are topological FaceN names. Build status reports a native failure if they break.
- Taper beyond the verified ±10° falls back to the native path.

### Increment 5 (S): Idle recovery, cheap verification, native AutoSave off (P0-4, IO-1 to IO-3) (≈ 6 days)

**Goal.** No checkpoint ever runs during input. The GUI-thread checkpoint cost at 60 holes drops from about 0.8–1.27 s to ≤ 50 ms. One KurtShape-owned mechanism covers managed documents (with the sketch lease), modified unmanaged documents and foreign documents.

**Scope.**
- New `src/kurtshape/fcstd.py`:
  - `verify_fcstd(path)`: open `ZipFile`, require `Document.xml` in `namelist()`, read it fully (CRC check), require `data.rstrip().endswith(b"</Document>")` (the file ends with a newline, F29). 3.5 ms vs `testzip` 40 ms (median in `bench-core-60-holes.json`) at 60 holes.
  - `sha256_file(path)`.
  - `replace_with_retry(src, dst, attempts=5, delay_s=0.05)`, which retries `PermissionError`. Sharing violations on Windows are **unverified** but cheap to guard.
- Rewrite `src/kurtshape/recovery.py` (11–72), keeping the `read()` containment and SHA-256 checks (invariant 17e).
- New `src/kurtshape/recovery_scheduler.py`.
- `core.py`:
  - `checkpoint` (221–225);
  - open/recover (626–672);
  - failed-finish capture (831–838);
  - `_save` (1400–1418);
  - capabilities and diagnostics.
- `ui.py`:
  - `recovery_timer` (103–105);
  - `checkpoint_projects` (1271–1279);
  - `fill_recovery` (1260–1269);
  - `eventFilter` (1986–2014);
  - `shutdown`/`start()` (2016–2036; AutoSave at 2035–2036).
- `launch-kurtshape.ps1` (21–26) and `validate-review-gui.ps1` (21).

**Design.**
- **`RecoveryStore` schema 2.**
  - Constants:
    - `RECOMPUTABLE_SHAPE_TYPES` = {`PartDesign::Body`, `Sketcher::SketchObject`, and PartDesign `Pad`, `Pocket`, `Revolution`, `Groove`, `Hole`, `Fillet`, `Chamfer`, `Draft`, `Thickness`, `LinearPattern`, `PolarPattern`, `Mirrored`, `MultiTransform`, `Boolean`, `AdditivePipe`, `SubtractivePipe`, `AdditiveLoft`, `SubtractiveLoft`, `AdditiveHelix`, `SubtractiveHelix`};
    - `SHAPE_PROPERTIES = ('Shape','AddSubShape','SuppressedShape')`;
    - checkpoint save prefs `CompressionLevel=1`, `SaveBinaryBrep=True`, `SaveThumbnail=False`.
  - Never omit shapes of exact `PartDesign::Feature` (imported solids), `Part::Feature`, `App::Link`, Assembly objects or FeaturePython.
  - `_checkpoint_prefs()` is a context manager that restores each pref's previous value, or removes the key if it was absent.
  - `light_mode_allowed(doc, managed)`: managed, and no `App::Link` whose `LinkedObject.Document` is another document.
  - `snapshot(doc, meta, editing, draft, mode='light', trigger, managed)` runs on the GUI thread only:
    1. Stage path: `<id>.<uuid12>.saving.FCStd`.
    2. Mark the shape properties of recomputable objects `Transient` (F19).
    3. `saveCopy(str(stage))` under the checkpoint prefs, restoring `-Transient` in `finally`.
    4. Record `{schema:2, document_id, revision, name: doc.Label, source_file, saved_at, managed, mode, trigger, shapes:'recomputable_omitted'|'stored', gui_ms, engine, sketch, accepted_sketch, draft_sketch}`.

    No hashing here.
  - `commit(pending)` is pure file work, safe on any thread:
    1. Verify the stage and hash it.
    2. Rename it to a unique snapshot name.
    3. Write `<id>.saving.json`.
    4. Rotate the current manifest to `<id>.previous.json` and promote the staged manifest.
    5. GC unreferenced `<id>.*.FCStd` files and `*.saving.*` older than 1 h.

    A valid pair exists at every step.
  - `capture(...)` is a synchronous snapshot + commit for forced paths and tests, keeping the old non-force guard.
  - `read()` accepts schema 1 and 2 (`setdefault('shapes','stored')`, `setdefault('managed',True)`), raises on schema > 2, and keeps rejecting manifests or snapshots outside the recovery directory and SHA-256 mismatches (`recovery.py:50-56`).
  - `available()` skips `*.saving.json` and adds `role` (current/previous).
- **Controller.**
  - `recovery_key(doc)` returns `(Revision, lease signature, lease undo length)`. It runs the intent sync only if `intent_dirty`, and **never** calls `_build_status`; today a checkpoint runs sync/`_build_status` every second.
  - `checkpoint_snapshot(doc, mode, trigger)`, and `checkpoint(doc, force=False, mode='light', wait=True)`, which keeps the existing API.
  - The failed-finish capture is forced and light.
  - Recover:
    1. `doc.Label = record['name']`. At HEAD a recovered document shows its UUID, because `openDocument` labels by file stem (verified).
    2. Attach managed or unmanaged per the record (through `attach`, invariant 17c).
    3. If `shapes=='recomputable_omitted'`, touch the recomputable objects and recompute. Increment 1's open no longer rebuilds, so recover must. This costs 12.4 s at 60 holes, the same as today.
    4. `FileName=''`.
  - `_save`:
    - `verify_fcstd` replaces `testzip`;
    - `replace_with_retry`;
    - delete stale `<stem>.saving.FCStd.*` files older than 1 h;
    - record timings `save_savecopy_ms` and `save_verify_ms`.
- **`recovery_scheduler.py`.**
  - `IdlePolicy(idle_seconds=2.0, micro_idle_seconds=0.5, min_interval_seconds=10.0, max_staleness_seconds=120.0, inactive_full_seconds=5.0, tick_ms=500)`, read via `Settings.recovery_policy()` (idle clamped to 1–30 s).
  - Pure `checkpoint_due(now, last_input, dirty_since, last_commit_end, gates, policy)` returns `'idle' | 'stale_micro_idle' | 'inactive_full' | None`. Any of these gates blocks: buttons/modifiers down, modal/popup, busy, native task, IO finishing, preview pending, in-flight, backoff.
  - `RecoveryScheduler`:
    - `note_input()` is a single float store, called from the event filter for key, mouse, wheel, touch, tablet, drag and context-menu events;
    - `tick()` polls futures, computes the gates once, and starts at most one snapshot per tick (active document first). The commit runs on a 1-worker `ThreadPoolExecutor`;
    - failures back off as `min(600, 30·2^n)` s and notify once;
    - `stop()`.
  - **Timer policy.** The 500 ms tick runs only while a document is dirty, or a commit is in flight. Arm it from the observer listener, or from Panel tick until increment 11. Increment 11 makes it purely event-armed.
  - `panel.recovery_timer` stays as an alias for macros.
- **AutoSave off.**
  - `ui.start()`: `SetBool('AutoSaveEnabled', False)`, keep `RecoveryEnabled`, remove the `AutoSaveTimeout` write, record `native_autosave_enabled_at_startup`.
  - The launchers patch `user.cfg` before `Start-Process`, setting `<FCBool Name="AutoSaveEnabled" Value="0"/>` under `Root/BaseApp/Preferences/Document`, or write a minimal file. This takes effect on the first launch (F20).
  - Add a `-SessionRoot` parameter to `launch-kurtshape.ps1` (default unchanged). Test the `user.cfg` patch only against a copied profile under `runtime\launcher-test` via `-SessionRoot`, and assert the patched XML **without starting FreeCAD**. Never run the launcher against `runtime\` (invariant 11).
  - `core.attach_external(doc)` handles documents FreeCAD's recovery dialog restores: attach, `FileName=''`, record `recovered_from`.
- **Recovery menu.** Group entries by document: "Name · checkpoint" or "Name · unfinished sketch", with "· rebuilds on open" for light checkpoints, and an "Older checkpoint" submenu.
- **Diagnostics.** `recovery: {mechanism:'kurtshape_idle', idle_seconds, min_interval_seconds, max_staleness_seconds, modes, native_autosave_enabled_at_startup, last:{…}}`. Keep `checkpoint_interval_seconds` (= min interval) and `recovery_directory`. Diagnostics are additive and not versioned; no contract bump.

**Tests.**
- Updated:
  - `test_corrupt_checkpoint_is_rejected_and_previous_pair_remains_readable`: the previous snapshot comes from `json.loads(previous.read_text())['snapshot']`.
  - `test_checkpoint_restores_unfinished_draft_and_explicit_cancel_restores_accepted_sketch`: keep it; add a recovered Label assertion.
- Kept: `test_fcstd_reopen_relocation_embedded_policy_and_instance_export`.
- Added in new `tests/test_recovery.py`:
  - `test_light_checkpoint_omits_only_recomputable_shapes_and_recover_rebuilds`;
  - `test_light_checkpoint_has_no_side_effects_and_restores_status_on_failure`;
  - `test_checkpoint_preferences_are_restored`;
  - `test_verify_fcstd_rejects_truncated_missing_document_xml_and_crc_errors` (and accepts a real saved file with the trailing newline);
  - `test_commit_fault_injection_always_leaves_one_valid_pair`;
  - `test_schema1_manifests_remain_listable_recoverable_and_migrate`;
  - `test_snapshot_does_no_hashing_and_commit_runs_on_worker_thread`;
  - `test_unmanaged_modified_document_checkpoint_recovers_as_unsaved_unmanaged`;
  - `test_checkpoint_due_never_fires_during_input_and_fires_after_idle`;
  - `test_recovery_key_does_not_run_build_status`;
  - `test_read_rejects_manifest_or_snapshot_outside_recovery_directory`;
  - `test_save_uses_cheap_verification`.
- GUI: rewrite `tools/review-recovery-crash.FCMacro` and `tools/validate_review_recovery.py`:
  1. edits, then idle ≥ idle+1 s → a light manifest exists;
  2. synthetic input every 250 ms for 20 s → no checkpoint;
  3. a modified unmanaged document is checkpointed;
  4. `native_autosave_enabled_at_startup == false`;
  5. no `fc_recovery_file*` anywhere under `App.getTempPath()` (searched recursively from inside the session; record the resolved path in the report);
  6. `os._exit`, then recover: Label is the original name and `FileName==''`.
- GUI: `tools/ui-refinement-validation.FCMacro:358` uses the alias or `recovery_scheduler.stop()`.

**Acceptance.**
- Synthetic input every 250 ms for 60 s after edits on the 60-hole plate gives zero snapshots and 0 ms of recovery GUI time.
- Steps other than `saveCopy` cost < 1 ms on the GUI thread, or run on the worker. Measured main-thread gap ≤ 16 ms (4.9 ms prototype).
- `recovery_snapshot_gui_ms` p95 ≤ 50 ms light at 60 holes (35.5–36.7 ms Linux/Xvfb).
- A checkpoint commits within idle + 1 s after input stops.
- No `fc_recovery_file*` under `App.getTempPath()` during a 3-minute session.
- Crash recovery restores volume, draft and Cancel buffer, plus the unmanaged document. The original file's SHA-256 is unchanged.
- Schema-1 manifests are still recoverable.
- Save verification ≤ 5 ms, with no `testzip` anywhere.

**Risks.**
- Light recovery relies on a rebuild. Mitigations: an allow-list of types, a full checkpoint when the app is in the background, and the previous pair kept.
- The `Transient` trick is undocumented (guarded by a test).
- The 36 ms snapshot grows by about 0.27 ms per object.

### Increment 6 (F): Extrude New and Intersect, and the unified Extrude dock UI (≈ 6 days)

**Goal.** An Onshape-style Extrude task in the right dock: operation New/Add/Remove/Intersect, end conditions, flip, depth, up-to picking, offset, draft, second end and merge scope. Enter confirms, and Shift+Enter confirms and repeats.

**Scope.**
- `extrude.py` `execute_extrude` new/intersect.
- `bodies.py` (5–33).
- New `src/kurtshape/extrude_task.py` (`ExtrudeTask(QtCore.QObject)`).
- `ui.py`:
  - `make_editor` (173–185, 190–193);
  - `__init__` preview wiring (85–90);
  - 1560–1689;
  - `eventFilter` Enter handling (1997–2003);
  - `configure_editor` (1209–1228);
  - `SelectionObserver.addSelection` (45–55);
  - `history_click` (1143–1158);
  - `operation` preview cancel/resume (903–910, 939–940, 966–967).
- `feature_tools.py` `MODEL_TOOLS` (59–66).

**Design.**
- **New** (when the owner body has a solid; otherwise degrade to an in-place Pad, today's behavior):
  1. `nb = doc.addObject("PartDesign::Body", unique "Body")`, Label from `name` or "Part N".
  2. `binder = nb.newObject("PartDesign::SubShapeBinder", id+"Profile")`, `binder.Support=[(profile,("",))]`.
  3. Any up-to binder (increment 4; New's up-to faces always belong to another body).
  4. `pad = nb.newObject("PartDesign::Pad", id)`, `pad.Profile = binder`, then `apply_extrude`.
  5. Hide the binders in the GUI. `created_feature = pad.Name`, and the affected body is `nb`.

  Verified: pointing a Pad directly at a foreign sketch logs an out-of-scope warning, while the binder follows sketch edits (1570.80 → 1005.31 mm³).
- **Intersect.**
  1. A tool Body as in New, with Label `id+" tool"` and Visibility False.
  2. `boolean = body.newObject("PartDesign::Boolean", id)`, `Type="Common"`, `Group=[tool_body]`.
  3. Volume must decrease, and the result must stay one solid.
- **`bodies.py`.**
  - `is_tool_body(b)` = any `PartDesign::Boolean` in `b.InList` with `b` in its Group.
  - `bodies()` and `results()` exclude tool bodies. `owner()` still sees them.
  - Tool bodies never count toward `ambiguous_body` and are never exported.
- **Inspect.** A Boolean whose Group is a single binder-based tool body reports `operation: "intersect"`.
- **`ExtrudeTask` widgets** (objectNames `KurtShapeExtrudeNew|Add|Remove|Intersect` for the operation buttons):
  - `end_type` combo with **Blind always at index 0**, so `gui-validation` `setCurrentIndex(0)` keeps working. Items per operation:
    - Add: Blind, Symmetric, Up to next, Up to last, Up to face;
    - New: Blind, Symmetric, Up to face;
    - Remove: Blind, Symmetric, Up to next, Up to face, Through all;
    - Intersect: Blind, Symmetric.
  - Flip button. `panel.reverse` stays as a hidden synced QCheckBox.
  - `depth` (reuses `panel.depth`).
  - Read-only `up_to_field`, armed while focused or empty.
  - Offset, draft and second-end groups.
  - "Merge scope" `target_body` combo (default: the profile owner).
  - Existing `preview_hint` and Confirm/Cancel.
  - Keep the aliases `panel.depth`, `panel.end_type`, `panel.reverse`, `panel.preview_hint`, `panel.confirm`.
- **Defaults** (§4.3):
  - Toolbar Extrude: Add if the owner has a solid, else New. Toolbar Remove: Remove, with Through all.
  - Sticky last depth.
  - Flip initialized from `default_remove_reversed()` for Remove.
- **Picking.** While `panel.task == "extrude"`, `SelectionObserver.addSelection` forwards to `task.pick`:
  - sketches set the profile (also via the history click at `ui.py:1155-1158`);
  - when armed, Face/datum picks set `up_to`;
  - the selection is cleared after a pick.
- **Keys.**
  - Enter in depth, offset, draft or second depth runs `accept_task`. Shift+Enter runs `accept_repeat`, which reopens with the same settings, no profile, and the hint "Select the next sketch". Esc cancels.
  - `Panel.tick` returns early while `core.busy`.
- **Confirm ids.** `panel.unique("Extrude" | "ExtrudeRemove" | "ExtrudeNew" | "Intersect")`. After success, hide the profile sketch as today (`ui.py:1662-1663`) and select the created feature.
- **capabilities.** The extrude block lists new/intersect. `CONTRACT_REVISION` → 2.

**Tests.**
- Added to `tests/test_extrude_contract.py`:
  - `test_new_extrude_uses_linked_profile_and_follows_sketch`;
  - `test_intersect_tool_body_is_hidden_and_excluded`;
  - extend `test_extrude_operations_map_to_native_properties` to new/intersect (including New up to face through a binder), one undo step each.
- GUI:
  - `tools/extrusion-preview-validation.FCMacro`: operation buttons, end combo per operation, Enter in each field, Shift+Enter repeat, face picking for Up to face.
  - `tools/gui-validation.FCMacro`: the blind face pocket via `panel.extrude(True)`/index 0 is kept.

**Acceptance.**
- New creates Body + binder + Pad that follows later sketch edits.
- Intersect creates a Boolean Common whose tool Body is hidden and excluded from `bodies()`, `results()`, export and `ambiguous_body`.
- Each Confirm is one undo step.
- Enter in any extrude field confirms. Shift+Enter confirms and reopens.
- No user-facing string contains "native".

**Risks.**
- Extra objects (binders, tool body) appear in history. The tree, inspect, duplicate and delete cascade must handle them.

### Increment 6b (F): Viewport depth handle and editing an existing extrude (≈ 4 days)

**Goal.** Drag the extrude depth in the viewport. Reopen an existing Pad, Pocket or Intersect in the same dialog.

**Scope.**
- `extrusion_preview.py`: new `DepthHandle`, wired next to `CoinExtrusionOverlay`.
- `extrude_task.py`: handle lifecycle and prefill from inspect.
- `extrude.py`: `edit_extrude` (reuses `normalize_extrude`/`apply_extrude`).
- Registry: `edit_extrude` (`since='3.3'`).
- `ui.py`: double-click handler near `history_click` (1143–1158).

**Design.**
- **`DepthHandle`** in `extrusion_preview.py`:
  - Node: `SoSeparator[SoTransform hx, coin.SoTranslate1Dragger()]`, added to `view.getSceneGraph()` next to the ghost, not inside it. `hx.translation = O + d*anchor` (anchor = L for blind, L/2 for symmetric), `rotation = SbRotation((1,0,0), d)`, `scaleFactor = (s,s,s)`.
  - Callbacks only via `view.addDraggerCallback(dragger, "addStartCallback"|"addMotionCallback"|"addFinishCallback", fn)`, removed with `view.removeDraggerCallback` in `clear()` (F13).
  - Motion: `L = max(0.01, L0 + dragger.translation.getValue()[0]*s*k)`, with k = 1 for blind and 2 for symmetric. Then `depth.setValue(round(L,3))`, which reaches `overlay.set_depth` with no re-tessellation and no document access.
  - Finish: reset the dragger translation and move the anchor.
  - Screen-constant size: a 100 ms QTimer, active only while the handle is visible, sets `s = 0.08*camera.height` (orthographic) or `0.08*2*dist*tan(heightAngle/2)` (perspective). Do not use a pivy `SoFieldSensor`.
  - Hidden for through_all and up_to_*.
  - FreeCAD's `SoLinearDragger` is an optional later upgrade; its interaction from Python is **unverified**.
- **New registry op `edit_extrude {feature, …same args as extrude}`.**
  - Applies via `apply_extrude` in one transaction, with the same postconditions (creating or removing an up-to binder as needed).
  - Double-clicking a Pad, Pocket or intersect Boolean opens ExtrudeTask prefilled from `inspect.features[].extrude` and previews the replacement tool.
  - `CONTRACT_REVISION` → 3.

**Tests.**
- `tests/test_extrude_contract.py`: add `test_edit_extrude_changes_end_condition_in_one_undo_step`.
- GUI (`tools/extrusion-preview-validation.FCMacro`):
  - the dragger is pickable and the ghost is not;
  - a real Qt drag updates the depth field and the ghost transform;
  - Enter commits the dragged depth.

**Acceptance.**
- A real mouse drag changes Depth and the ghost. Each depth update ≤ 5 ms.
- `git grep -n addValueChangedCallback -- src` is empty.
- An edit is one undo step, and its committed `AddSubShape` matches the preview.

### Increment 7 (S): Incremental intent, delta summaries, one inspection per GUI operation (P1-5, P2-8 intent) (≈ 5.5 days)

**Goal.**
- After an edit, intent hashing costs 1–3 ms instead of 34–40 ms at 132 objects.
- Each GUI operation makes one cheap revision read plus one delta summary instead of 2–3 full inspections.
- Recovery and idle paths never rehash.

**Scope.**
- New `src/kurtshape/intent.py` (`IntentIndex`).
- `document_state.py` (all).
- `core.py`:
  - `native_intent`/`intent_signature` (124–154);
  - `sync`/`_signature`/`_sketch_edit_signature`/`_record_sketch_edit`/`_new_revision`/`attach` (351–364, 227–228, 366–368, 370–384, 880–887, 294–323);
  - `_inspect`/`dispatch` (501–564, 815, 858);
  - `checkpoint`/`needs_refresh` (221–225, 279–283).
- `ui.py`:
  - `operation` (893–968);
  - `assembly_ready` (531), `create_assembly` (559), `begin_preview` (1603).

**Design.**
- **`Controller.attached_names`** (new): a set of `doc.Name`, added in `attach()` and removed in `slotDeletedDocument`. The Controller today tracks attached documents only through `self.documents` (DocumentId → doc, `core.py:208`).
- **`DocumentState` v2.** Per document: `seq`, `object_seq`, `deleted_seq`, `dirty: {name: set[prop] | None}`, `full_rehash` (True initially), `shape_gen`, `scheduled`. Constants:
  - `DERIVED = {Shape, InternalShape, Proxy, PlacementList, Visibility}`;
  - `GEOMETRY` = the props that bump versions (increment 1).

  Slots:
  - `slotChangedObject`:
    - return for METADATA;
    - if the document is not in `controller.attached_names` (still restoring, or a parameter-preview clone): set `full_rehash`, bump generation, set `refresh`, return. This keeps the 4,332-callback open storm cheap;
    - otherwise bump `seq` and `object_seq`;
    - a non-derived prop sets `intent_dirty` and adds the prop to `dirty[name]`;
    - geometry props bump generation and `shape_gen`;
    - keep the `KurtShapeEmbeddedSource` special case;
    - call `_notify(doc)`.
  - `slotCreatedObject`: `dirty[name]=None`. `slotDeletedObject`: record `deleted_seq`.
  - `slotAppendDynamicProperty(obj, prop)` and `slotRemoveDynamicProperty(obj, prop)` (signatures per `Mod/Test/Document.py:1903-1911`): `dirty[name]=None`.
  - `slotChangedDocument(doc,'Label')`.
  - `slotAbortTransaction`, `slotUndoDocument`, `slotRedoDocument`: `full_rehash`.
  - `slotDeletedDocument`: also `controller.intent.forget(name)` and remove the name from `attached_names`.
  - `_notify` calls listeners once on the clean→dirty transition. Also add `add_listener`, `remove_listener`, `consume(doc)`, `bump(doc, names)`.
  - Prune `deleted_seq` above 4096 entries and raise the floor; older cursors then get a full summary.
- **`IntentIndex`.**
  - Canonical form:
    - doc signature = sha256 of `doc.Label` plus `name + object_digest` over the included objects in `doc.Objects` order (exclude METADATA, `App::Origin`/`App::Line`/`App::Plane`);
    - object digest = sha256 over the sorted `(component_key, component_digest)`;
    - component digest = sha256 of `json.dumps(value, sort_keys=True)`.
  - Component keys mirror `native_intent`: `@label`, `@type`, `@expressions`, and each property minus `SKIP = {Shape, InternalShape, ExpressionEngine, Geometry, Constraints, Proxy, PlacementList, Visibility}`. Shape-typed properties are skipped, with `(TypeId, prop) → is_shape` cached. Sketches add `@geometry`, `@construction` and `@constraints`.
  - Prop → components map:
    - `Label` → {`@label`,`Label`};
    - `ExpressionEngine` → {`@expressions`};
    - sketch `Geometry` → {`@geometry`,`@construction`}, `Constraints` → {`@constraints`}.
  - API: `signature(doc, dirty, full)`, `object_digest`, `full_signature`, `reset`, `forget`, `counters`.
  - Fall back to a full rehash on attach/open/recover/adopt, undo, redo, abort, verification mismatch, or any exception.
  - `KURTSHAPE_VERIFY_INTENT=1` asserts incremental == full after every signature. Set it in CI and in `tools/ci/run-local.ps1`.
  - The module-level `intent_signature(doc)` becomes `IntentIndex.full_signature(doc)`.
- **Controller.**
  - Split `sync` into `_sync_intent`, `_sync_snapshot` and the cached `_build_status` errors.
  - `revision(doc)` is about 1 µs when clean.
  - `_sketch_edit_signature` uses `intent.object_digest`.
  - `checkpoint` exits early via `revision()`.
  - `_feature_row(obj)` is extracted from `_inspect` (the dict at 509–524).
  - `summary(doc, since=None)`:
    1. `sync`.
    2. A State-flag diff, so `touch()` and failed recomputes appear (F3).
    3. Order, the changed rows since the cursor, removed rows.
    4. Header fields, assembly, geometry (cheap cached accessors from increment 1).
    5. `cursor`, and `full` when `since` is None.
  - `dispatch(request, view=None)`: with a `view` and an op that is not a create op or `adopt`, return the summary instead of a full inspect. The bridge passes no view, so the JSON contract is unchanged.
- **Panel read model.**
  - `read_models[doc.Name] = {cursor, rows, header}`.
  - `apply_summary` rebuilds `self.state` as a full inspect-shaped dict. Macros read every key; `adopt` calls `core.inspect` explicitly.
  - `operation()`:
    1. `revision = core.revision(doc)` replaces the pre-inspect (916–922);
    2. dispatch with `view={'since': cursor}`;
    3. on failure, apply the summary;
    4. `consume` so the next tick finds nothing.

**Tests.**
- Added in new `tests/test_intent_index.py`:
  - `test_incremental_signature_matches_full_for_native_edit_matrix` (30 edit kinds);
  - `test_change_detection_matches_full_signature_including_no_op_assignments`;
  - `test_tip_edit_rehashes_only_dirty_components`;
  - `test_undo_redo_abort_and_reopen_use_full_rehash`;
  - `test_verify_mode_detects_unobserved_mutation`.

  The 30 edit kinds are: setDatum, setDriving, add/delConstraint, renameConstraint, toggleConstruction, spline-pole Geometry, delGeometry, moveGeometry (`movePoint` does not exist in 1.1.4), Label, Reversed, Suppressed, ExpressionEngine, AttachmentOffset, Body.Tip, addProperty, removeObject, doc.Label, undo/redo/abort and others.
- Added to `tests/test_core.py`:
  - `test_revision_accessor_matches_inspect_after_each_native_edit`;
  - `test_summary_deltas_merge_to_full_inspection_features`;
  - `test_delta_view_dispatch_builds_one_summary_and_no_full_inspection`;
  - `test_summary_reports_failed_and_touched_flags_without_property_callbacks`.
- Added to `tests/test_core_safety.py`: `test_checkpoint_skips_sync_when_revision_unchanged`.
- Updated: `test_idle_inspection_uses_cached_intent_and_brep_then_native_edit_invalidates` gets intent component counter 0 when idle, and > 0 but below the total after `Pad.Length = 9`.
- Kept: `test_arbitrary_spline_native_edits_and_construction_change_revision`, `test_failed_managed_edit_does_not_reuse_pre_edit_revision`, `test_cancel_after_native_auto_commit_preserves_prior_history_and_shape`, `test_failed_finish_after_native_auto_commit_preserves_draft_and_can_repair`, `test_external_native_history_change_rejects_without_undoing_prior_features`, `test_stale_native_edit_and_failure_rollback`.

**Acceptance.**
- Incremental == full for all 30 kinds with verify mode on.
- The revision changes iff the full signature changes. `Reversed True→True` does not bump.
- Intent cost ≤ 3 ms after a tip edit and ≤ 10 ms after a root edit at 132 objects (1.1–2.5 / 5.4 ms prototype).
- `Panel.operation('set_parameter')` on the 60-hole model: `_inspect` called 0 times, `summary` once, `revision` at most once, and no summary in the next event-loop turn.
- Summary after a single-feature change ≤ 5 ms at 132 objects and ≤ 8 ms at 257 (full inspect floor 14.9 / 29.4 ms).
- `bench_core` `tip_edit.overhead_ms` ≤ 50 ms (phase1).

**Risks.**
- A native path that mutates without signalling would leave a stale revision. Mitigated by verify mode, full rehash on risky events, and a fallback on exceptions.
- A full rehash costs 52–58 ms (1.5× today's full signature). That is acceptable only off the ordinary edit path.

### Increment 8 (F): Part history. Rollback/insert, suppress, reorder (backend) (≈ 4 days)

**Goal.** Typed, undoable history operations on native `Body.Tip`, `Suppressed` and `Body.Group`.

**Scope.**
- `bodies.py` helpers.
- New registry ops `set_tip`, `suppress_feature`, `reorder_feature` (category model, `accepts_body`, postcondition `history`, `since='3.4'`, user-facing undo labels "Roll back to Pocket", "Suppress Pocket", "Move Pocket 2").
- `core.py`:
  - `_delete_feature` Tip rule (1212–1221);
  - `_inspect` (504–550);
  - `_export` (1420–1452).

**Design.**
- **`bodies.py`.**
  - `is_solid_feature(o) = o.isDerivedFrom('PartDesign::Feature') and o.TypeId != 'PartDesign::Body'`. Sketches, binders and `PartDesign::Plane` are not solid features.
  - `solid_features(body)`.
  - `insertion_index(body)`: the index of the next solid after Tip; the first solid if Tip is None; else `len(Group)`.
  - `semantic_dependencies(obj, members)` = OutList minus one BaseFeature entry, within members.
  - `order_violation(order)`, `reorder_window(body, objs)`.
  - `set_tip_display(body, tip)` makes only the tip visible, because Tip changes no visibility (F22). A visibility change inside a transaction is undoable.
- **`set_tip`** (`feature`, or `end: true`, or `null` for the start).
  - The target must be a solid feature in `body.Group`, else `unsupported_feature` ("Roll back to a solid feature; a sketch stays with the feature above it").
  - A target that already is the Tip gives `no_change`.
  - Insert-here needs no op: typed and native creation already insert at `insertion_index`, and the new solid becomes Tip (verified with the controller).
- **`suppress_feature`** (`feature` or `features` 1–64, `suppressed` bool, default true).
  - Targets must have a `Suppressed` property and not be script-owned, else `unsupported_feature`.
  - Downstream failures (suppressing the first Pad gives "Base feature's TopoShape is invalid") are rejected by the postcondition with `build_failed` and rolled back.
- **`reorder_feature`** (`feature`/`features` as a block, `before`/`after`).
  1. Compute the new order. Unchanged → `no_change`.
  2. If `order_violation(new_order)` finds a pair, reject with `dependency_order` ("{A} uses {B}; {B} must stay above it") before mutation.
  3. Otherwise `body.removeObject(m)` for each moved object, then `insertObject(first, target, after)` and `insertObject(rest, previous, True)`.
  4. Restore the Tip: the last solid if it was at the end, else the old Tip. Then `set_tip_display`.
  5. Assert the Group equals the new order, else `reorder_failed`.

  A cycle order is caught by the history postcondition.
- **`_delete_feature` fix.**
  - Keep a surviving Tip.
  - Otherwise use the nearest earlier surviving solid in the old order, or None.
  - Today the code rolls a rolled-back body forward (verified). The three existing deletion tests keep their results.
- **`_export`.** After the `build_failed` gate, reject `history_rolled_back` for any exported Body whose Tip is not its last solid.
- **Inspect.**
  - Per feature: `suppressed`, `rolled_back`, `status_message` (`getStatusString()` when Invalid/Error), `body`.
  - Per PartDesign body: `history` (Group order), `tip`, `insertion_index`, `rolled_back`.
  - The UI must order the tree by `history` (F22).
- **capabilities.** `history: {rollback:'Body.Tip', insertion:'before next solid feature after Tip', suppress:'PartDesign features only'}`. `CONTRACT_REVISION` → 4.

**Tests** (new `tests/test_part_history.py`).
- `test_rollback_insert_mid_history_and_roll_forward_each_one_undo`
- `test_upstream_edit_while_rolled_back_keeps_tip_and_rebuilds_later_features`
- `test_delete_while_rolled_back_preserves_tip`
- `test_set_tip_rejects_sketch_datum_foreign_body_and_no_change`
- `test_suppress_middle_and_tip_features_undo_redo_and_reopen`
- `test_suppress_base_feature_rejects_with_downstream_failures_and_rolls_back`
- `test_suppress_rejects_sketches_planes_and_script_features`
- `test_reorder_independent_features_relinks_base_chain_keeps_tip_and_undo`
- `test_reorder_rejects_profile_after_consumer_before_mutation`
- `test_reorder_cycle_through_face_support_rejects_build_failed`
- `test_history_ops_reject_during_lease_native_edit_busy_and_stale`
- `test_history_ops_request_replay_returns_original_result`
- `test_inspect_history_order_matches_body_group_after_insert_and_reorder`
- `test_export_rejects_rolled_back_body`

Kept: `test_rename_and_dependency_safe_delete_restore_native_tip_with_undo`, `test_native_fillet_chamfer_deletion_dependencies_cascade_and_undo`, `test_native_revolution_delete_keeps_profile_and_restores_tip_geometry_with_undo`.

**Acceptance.**
- Each op is one undo step. Undo restores Group order, Tip, Suppressed flags and volume within 1e-7 mm³.
- A stale revision leaves intent and UndoCount/RedoCount unchanged.
- A replay returns the original response.
- Delete while rolled back keeps a surviving Tip.
- A dependency violation is rejected before mutation.
- KurtShape overhead beyond native recompute ≤ 150 ms on the 60-hole plate.

**Risks.**
- Rolled-back features keep recomputing (F22), so rollback is not a speed tool.
- Native suppress and Set Tip commands bypass KurtShape's visibility and dependency checks. The observer still invalidates the revision.

### Increment 9 (S): STEP import and export in a worker process, STL presets, busy indicator (IO-4 to IO-6) (≈ 8 days, as 9a + 9b)

**Goal.**
- STEP import keeps the UI responsive. 25 bodies block the GUI for 13.3 s today; target ≤ 400 ms of GUI time.
- Export blocks the GUI ≤ 50 ms, with the export-time BRepCheck running in the worker.
- STL resolution is relative to part size.
- Save, open and recover show a painted busy indicator.

**Delivery split.** Two commits and two reports:
- **9a:** `step_import.py`, `io_worker.py`/`io_jobs.py` with the import job, `finish_step_import`, `JobStrip`, `run_blocking`, the import tests and the import half of `io-jobs-gui-validation`. No contract bump (the bridge still dispatches `import_step` synchronously).
- **9b:** worker export with check-cache reconciliation, STL presets, `ASYNC_OPS`/`dispatch_async` and the bridge async path, the export tests and the export half of the GUI recipe. `CONTRACT_REVISION` → 5.

**Scope.**
- New modules:
  - `src/kurtshape/step_import.py` (`build_import_document`, moved verbatim from `core.py:984-1036`);
  - `src/kurtshape/io_worker.py`;
  - `src/kurtshape/io_jobs.py` (`runtime_python`, `IoJobSpec`, `IoJob`, `IoJobRunner`).
- `core.py`:
  - `_import_step` (969–1046) → `prepare_step_import` / `begin_step_import` / `finish_step_import`;
  - `_export` → `_export_plan` / `_export_publish` / `begin_export` / `finish_export`;
  - `ASYNC_OPS = {'import_step','export'}`, `dispatch_async`;
  - the `stl` argument.
- `bridge.py` `tick` (85–101).
- `settings.py` (`stl_settings`, `recovery_policy`) and `workspace_preferences.py` (a Files section).
- `ui.py`:
  - `open_path` (1341–1360), `save`/`adopt`/`export` (1367–1407);
  - factor `apply_create_result` out of `operation` (893–960);
  - new `JobStrip`, `run_blocking`.

**Design.**
- **Worker launch.** `io_worker.py` is a module of the `kurtshape` package, which uses relative imports (`core.py:16-22`), so it must run with `-m`, not as a script:
  ```python
  subprocess.Popen(
      [str(runtime_python()), "-B", "-X", "utf8", "-m", "kurtshape.io_worker", str(job_json)],
      cwd=str(ROOT / "src"), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
      creationflags=subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS)
  ```
  - Stdout protocol: `KSIO <json>` lines (events `started`, `progress{stage,done,total}`, `result`). A daemon thread reads the pipe (pure I/O) and delivers each line through a bound `@Slot` with `Qt.QueuedConnection`.
  - Environment: private `FREECAD_USER_HOME`/`TEMP` in the job dir; remove `PYTHONHOME`/`PYTHONPATH`; `PYTHONUNBUFFERED=1`.
  - Do not use QProcess or `setCreateProcessArgumentsModifier`.
  - `runtime_python()` = `Path(App.getHomePath())/'bin'/'python.exe'`. If it is missing, fall back to synchronous in-process dispatch.
  - Pass `str(path)` to every FreeCAD file API in the worker and the GUI (F26).
- **Import (9a).**
  - The worker builds the document with the shared builder (source hash before and after the read, `isValid` boundary) and saves `<job_dir>/KurtShapeSTEP.FCStd` at level 1 with binary BRep.
  - `finish_step_import`:
    1. Re-check the create guards; return `sketch_edit_active` and keep the result pending if they fail.
    2. `verify_fcstd` and compare the sha.
    3. Open the file. The `ImportSource` sha and path must match, else close it and return `import_result_invalid`.
    4. `FileName=''`, `Label` = source stem.
    5. Attach (invariant 17c) and build status.
    6. Schedule job-dir cleanup.
  - Error codes stay unchanged. Only `cancelled`, `import_worker_failed` and `import_result_invalid` are added.
  - The in-process headless path stays synchronous and identical for tests.
- **Export (9b).**
  - `_export_plan` on the GUI thread: path (through `write_path`), gate, included list, compound, stage path, STL settings, provenance base.
  - `compound.exportBinary(str(job_dir / 'export.bin'))` (12 ms at 60 holes, bit-exact round trip).
  - **Reconciliation with increment 1's check cache.** Objects whose cached verdict for the current shape is already valid are not rechecked. The plan sends each unchecked object as its own binary BRep. The worker runs `check_shape` on each and returns verdicts. On any invalid verdict it returns `invalid_geometry` and touches no files. `finish_export` seeds the GUI cache only if the object's cache key is unchanged since begin.
  - The worker writes the pre-validated stage file next to the destination: `shape.exportStep(str(stage))` for STEP, or `MeshPart.meshFromShape(Shape=…, LinearDeflection=…, AngularDeflection=…, Relative=False).write(str(stage))` for STL.
  - `finish_export` publishes via `_replace_export_pair`.
  - Headless `dispatch('export')` stays in process through the same plan and publish helpers, so `test_core_safety` keeps covering publication.
  - The recorded revision is the one at begin.
- **STL presets (9b)** (`resolve_stl`). Chord = bbox diagonal × factor, clamped:
  - coarse: factor 2e-3, clamp [0.01, 2.0] mm, 30°;
  - **medium** (default): factor 5e-4, clamp [0.005, 0.5] mm, 15°;
  - fine: factor 1e-4, clamp [0.001, 0.1] mm, 5°;
  - custom: `linear_deflection_mm` in [0.001, 10] and `angular_deflection_deg` in [0.5, 45], else `invalid_argument`.

  Provenance settings record mesher, preset, basis, `bbox_diagonal_mm`, `relative_factor`, `linear_deflection_mm`, `angular_deflection_rad`/`deg`, `relative:false` and facets, and keep the legacy keys.
- **Bridge (9b).**
  - `ASYNC_OPS` go to `controller.dispatch_async(request, done)` when an io_runner exists.
  - The ledger registers `started` once and completes once.
  - Clients see `outcome_unknown` after the 30 s HTTP timeout and poll `request_status`.
  - capabilities `io: {import_step:'background_subprocess', export:'background_subprocess', cancel:'ui', stl_presets:[…]}`. This is a semantic change in practice; list it under Contract 3.5.
- **UI (9a).**
  - `JobStrip` in the status bar: name, stage, elapsed, progress bar, Cancel. Escape does not cancel; only the button does.
  - `run_blocking(label, op, **args)`: show the label, set the wait cursor, call `repaint()` synchronously (no `processEvents`), run the op, record `blocking_<op>_ms`. Used for save, adopt, FCStd open and recover.
  - After an import: "STEP imported · N solids · geometry only. Save as FCStd to keep your project."
- **Docs.** README and `docs/STEP_IMPORT.md`, plus a note on the GIL rule (later moved into `ARCHITECTURE.md`, increment 18).

**Tests.**
- Updated: `tests/test_step_import.py` `test_empty_shape_and_source_changed_are_rejected_before_new_document` patches `kurtshape.step_import.Part.read`.
- Kept: the other STEP import tests, `test_readonly_export_sidecar_failure_preserves_both_outputs_and_retry_hash`, `test_geometry_edits_history_and_fresh_relocation`.
- Added in new `tests/test_io_worker.py`:
  - 9a: `test_worker_import_matches_in_process_import`, `test_worker_errors_keep_import_codes`, `test_worker_cancel_leaves_no_document_and_removes_job_dir`, `test_finish_import_rejects_tampered_result`;
  - 9b: `test_worker_export_step_and_stl_match_in_process_and_publish_pair`, `test_export_rejects_invalid_geometry`, `test_stl_presets_are_relative_and_recorded_in_provenance`.
- Added to `tests/test_bridge.py` (9b): `test_async_operation_completes_after_timeout_via_request_status`.
- GUI:
  - `tools/step-import-gui-validation.FCMacro:87-111`: wait on `panel.io_runner.wait_for(job, 60000)`.
  - New `tools/io-jobs-gui-validation.FCMacro`, added to the `run_gui_recipe.ps1` map as `io`: a 2 ms heartbeat during a generated many-body import gives max gap ≤ 50 ms, the job strip shows stages, Cancel ends the job ≤ 500 ms (9a), and STEP/STL export of the 60-hole plate blocks ≤ 50 ms (9b). Take a screenshot to prove that no console window appears.

**Acceptance.**
- 9a. Import: heartbeat gap ≤ 50 ms during the worker phase (25-body fixture: 4.5 s in the worker). GUI share ≤ 400 ms (321 ms measured) for 25 bodies and ≤ 50 ms for one body.
- 9a. Cancel ≤ 500 ms, with no new document and the job dir removed or queued.
- 9a. Worker parity with in-process import: `body_ids`, `reference_ids`, `ImportSource`, volumes (1e-9) and `build_status`.
- 9a. Save verification ≤ 5 ms, and the busy indicator is painted before `saveCopy`.
- 9b. Export GUI time ≤ 50 ms. Invalid geometry gives `invalid_geometry`, and no files change. The sidecar sha matches.
- 9b. The medium preset exports the 60-hole plate in ≤ 15,000 facets (11,772 measured vs 30,492 today).

**Risks.**
- Two code paths: shared helpers and the parity tests are mandatory.
- Windows process and handle specifics (**unverified**): handle cleanup retries, console flashes (screenshot check).
- Async completion during a sketch is deferred.

### Increment 10 (F): Variables (≈ 6 days)

**Goal.** Onshape-style variables (`#width`), stored natively as an `App::VarSet` named `Variables`. Expressions are unit-checked, and fields are expression-aware with autocomplete.

**Scope.**
- Registry ops (`since='3.6'`):
  - `create_variable`, `set_variable`, `rename_variable`, `delete_variable` (model, postcondition `build`);
  - `evaluate_expression` (read, result `handler`, document required, no revision).
- `core.py`:
  - `set_expression` validation (1323–1331) → shared `normalize_expression`;
  - `native_parameters` (85–100): a per-type table covering `Fillet.Radius`, `Chamfer.Size`, `Revolution`/`Groove.Angle`, `Thickness.Value`, LinearPattern/PolarPattern `Length`/`Angle`/`Occurrences`, `Draft.Angle`;
  - `_inspect` gains `variables`.
- `quantity_field.py` (1–43).
- `ui.py`:
  - the editor's separate Formula row is removed: the `formula` widget (182–184), its form row (187), the Clear formula button (197–199) and the formula uses at 1239–1240, 1245–1246 and 2007–2009;
  - new Variables dock;
  - shortcut `view.variables` (Alt+V).

**Design.**
- **Container.** VarSet `Variables`, created by the first `create_variable` in the same transaction. Kinds:
  - length → `App::PropertyDistance` (not Length, which clamps negatives);
  - angle → `App::PropertyAngle` (rad in the contract, deg stored);
  - number → `App::PropertyFloat`;
  - count → `App::PropertyInteger`.

  Property group "Variables". The description goes into the property docs.
- **`create_variable`.**
  - The name must match `^[A-Za-z][A-Za-z0-9_]{0,63}$` and be new (`duplicate_variable`).
  - After `addProperty`, parse-test `vs.evalExpression(f"{vs.Name}.{name}")`. A `ParserError` gives `invalid_variable_name`: `mm`, `in`, `pi` and `e` are accepted by `addProperty` but not referenceable.
- **`set_variable`** (value, or expression; null clears it).
- **`rename_variable`** uses `renameProperty`, which rewrites dependents in both syntaxes (F21), plus the parse test.
- **`delete_variable {name, detach=false}`.**
  - Find dependents by scanning every `ExpressionEngine` for `(?<![\w.])(?:Variables|<<Label>>)\.name\b`, plus bare `name` inside the VarSet.
  - With dependents and no detach: `variable_in_use` listing `[{feature, parameter}]`.
  - With detach: `setExpression(path, None)` on each dependent (keeps the current values), then `removeProperty`.
- **`normalize_expression(doc, target, text, unit)`.**
  1. String ≤ 512 chars. Reject only `__`, control characters and newlines; FreeCAD unit syntax (`30°`, `5 µm`, feet/inch with `'` and `"`) must pass. `evalExpression` validates the syntax.
  2. `#name` → `Variables.name` when it exists, else `invalid_expression` ("Unknown variable #name").
  3. `target.evalExpression(expr)`. `ParserError`/`RuntimeError` → `invalid_expression`.
  4. Unit check: the unit must match mm or deg, or be dimensionless, else `unit_mismatch` (F21).
  5. `setExpression` + recompute. Invalid/Error → `invalid_expression`.

  Inspect parameters show `expression_display` with `#X`. Consider rejecting `.Shape.` paths in typed expressions, because they create hidden slow dependencies; record your choice.
- **UI.**
  - Variables dock (`KurtShapeVariables`), tabified with Feature settings: Name | Value | Used by, an Add menu (Length/Angle/Number/Count), and a delete dialog that offers detach.
  - `QuantityField` expression mode: `QCompleter` over `#vars`, `Variables.vars` and feature parameter paths; a muted "= 25 mm" label from `evaluate_expression` with a 150 ms debounce; `staged()` returns `('value'|'expression', text)`.
  - Do not use `Gui.ExpressionBinding`: it writes directly and bypasses revision checks.
- **capabilities** `variables: {container:'App::VarSet Variables', kinds:[…], syntax:['#name','Variables.name','<<Label>>.name']}`. `CONTRACT_REVISION` → 6.

**Tests.**
- Added in new `tests/test_variables.py`:
  - `test_create_length_angle_number_count_variables_units_and_reopen`;
  - `test_expressions_by_name_label_and_hash_drive_sketch_and_pad`;
  - `test_unit_mismatch_rejects_before_mutation`;
  - `test_unit_symbols_in_expressions_are_accepted` (`30°` on an angle, `5 µm` on a length);
  - `test_rename_variable_updates_dependents_and_undo`;
  - `test_delete_used_variable_rejects_and_detach_keeps_values`;
  - `test_reserved_and_invalid_variable_names_reject`;
  - `test_evaluate_expression_is_read_only`.
- Kept: `test_quantities_formulas_wrong_units_cycles_and_clear`.

**Acceptance.**
- An angle variable bound to a length gives `unit_mismatch`.
- `#Width`, `Variables.Width` and `<<Variables>>.Width` all bind.
- Rename updates all dependents.
- Deleting a used variable is rejected without detach, and keeps the values with detach.
- Everything survives save/reopen.
- Each op is one undo step.
- `evaluate_expression` ≤ 20 ms and changes nothing.

### Increment 11 (S): Event-driven shell. No 25 ms poll, bridge wake, one event filter, sketch fast path (P1-6, P2-7) (≈ 5.5 days)

**Goal.** Zero timers and zero work while idle. Bridge queue wait median ≤ 1 ms. One application event filter. A sketch mouse release costs < 1 ms.

**Scope.**
- New `src/kurtshape/shell_events.py` (`ShellScheduler`, `GuiLifecycleObserver`, reason flags `DOC_DIRTY=1`, `BRIDGE=2`, `LIFECYCLE=4`, `SKETCH_BOUNDARY=8`, `FORCE=16`).
- New `src/kurtshape/app_events.py` (`AppEventRouter`, `install(app)`).
- `ui.py`:
  - `__init__` (58–108: timer 100–102, main filter 75, line-edit filters 184–186, app filter 108);
  - `tick` (836–891) becomes `shell_pass` + `tick()=flush()`;
  - `eventFilter` (1986–2013), `edit_sketch`/`finish_sketch`/`sync_edit_ui`/`shutdown`.
- `bridge.py` (15–20, 53, 85–101).
- `core.py`: new public `Controller.record_sketch_boundary(doc)`.
- `navigation.py` (23–25, 28–47, 58–86, 89–128).
- `shortcuts.py` (187–240).
- `workspace_preferences.py` (12, 20–23, 73–76).
- `theme.py` `NativePaletteFilter` (239–254).
- `extrusion_preview.py` lifetime timer (338–341, 399–427).
- The recovery scheduler arming.

**Design.**
- **`ShellScheduler(run_pass, parent, watchdog_ms=250, watch_needed)`.**
  - A zero-interval single-shot timer coalesces requests (F16).
  - `documentDirty` is a direct signal. `bridgeWake` is connected with `Qt.QueuedConnection` to a bound `@Slot`.
  - Also `request(reasons)`, `flush(reasons)` (used by `Panel.tick()`), `suspend`/`resume` (replace `panel.timer.stop()` in macros), and `defer` (no re-arm while deferred).
  - The watchdog runs only while `watch_needed()` returns True: `Gui.Control.activeDialog()`, or a sketch lease, or a task.
- **Wiring.**
  - `core.observer.add_listener(shell.documentDirty.emit)`.
  - `Gui.addDocumentObserver(GuiLifecycleObserver(shell))` with only the slots allowed by F14.
  - The router's Show handler requests `LIFECYCLE` for `Gui::TaskView::*` widgets.
- **`Controller.record_sketch_boundary(doc)`** (new, public) calls `_record_sketch_edit` (`core.py:370`). The existing `record_edit_boundary` (`core.py:282`) only sets `snapshot_pending`.
- **`Panel.shell_pass(reasons)`:**
  1. Defer while `_in_operation`, entering/finishing a sketch, or busy.
  2. On `BRIDGE`, drain exactly one bridge request and re-request if more are queued. The assembly-failure notifications from `tick` 839–850 move here verbatim.
  3. Lifecycle snapshot `(active doc, in-edit object, dialog, lease ids)`. On a change: enforce the sketch owner, cancel the task on a document change, auto-finish the lease using `core.sketch_edits`, `extrusion_preview.check_lifetime()`.
  4. During a lease: only `core.record_sketch_boundary(doc)`. No summary, no tree.
  5. Otherwise `apply_summary` when needed.
  6. Else clear the document UI, including the P1-11 reset.
  7. `sync_edit_ui`.
- **Bridge.**
  - `Bridge(..., wake=None)`. In `do_POST`, after a successful `put_nowait` (line 53): `if w: try: w() except RuntimeError: pass`.
  - Keep every check of invariant 17a, including the media-type comparison from increment 0.
  - `tick()` stays drain-one.
  - Shutdown order: `bridge.wake = None`, `shell.suspend()`, teardown, `bridge.close()`.
- **Sketch fast path.** On `MouseButtonRelease` during a lease: `core.record_edit_boundary(doc)` plus `request(SKETCH_BOUNDARY)`. Delete the `['refresh'] = True` line. Snapshots come from `slotCommitTransaction`; the native rectangle tool commits per command (verified). Point drags are **unverified**, so the release boundary stays as a fallback.
- **`AppEventRouter`.**
  - One filter, with handlers per event type in priority order: NAVIGATION=10 (DoubleMiddleFit), PANEL=20, SHORTCUTS=30, WORKSPACE=40, THEME=50.
  - A handler returning True stops the chain.
  - Cache the navigation style; no `ParamGet` per event.
  - `ShortcutRouter.handle_event` holds the logic, and `Filter.eventFilter` delegates to it so `install()`/`uninstall()` still work for tests.
  - Remove all other filter installs.
- **Extrusion preview.** `lifetime_timer` starts only in `begin()` and stops in `clear()`.
- **Recovery scheduler.** Armed by `shell.revisionChanged` and the dirty listener. No standing timer.

**Tests.**
- Added in new `tests/test_shell_events.py`:
  - `test_http_thread_wake_runs_pass_on_gui_thread_within_5ms` (the 5 ms bound only under `KURTSHAPE_PERF=1`; otherwise assert the pass ran on the GUI thread);
  - `test_many_dirty_notifications_coalesce_into_one_pass`;
  - `test_no_shell_timer_active_when_idle`;
  - `test_pass_deferred_during_operation_runs_once_after`;
  - `test_watchdog_runs_only_while_dialog_or_lease_active`.
- Added in new `tests/test_app_events.py`:
  - `test_single_filter_dispatches_by_type_in_priority_order`;
  - `test_unregistered_event_types_stay_under_budget` (≤ 25 µs per MouseMove offscreen; `KURTSHAPE_PERF=1` only);
  - `test_navigation_style_cached_and_refreshed_on_save`.
- Added to `tests/test_bridge.py`:
  - `test_enqueue_calls_wake_once_per_queued_request`;
  - `test_wake_errors_do_not_break_request_handling`.
- Kept: the existing bridge (including the increment-0 security tests) and shortcut tests.
- GUI:
  - `tools/gui-review-validation.FCMacro`: replace the "25 idle GUI ticks" check with a 1 s idle loop asserting 0 passes, 0 intent components, 0 measurements and no active KurtShape QTimer.
  - `tools/gui-validation.FCMacro` (176, 235, 246): add event-driven variants with `QTest.qWait(50)`.
  - `panel.timer.stop()` → `panel.shell.suspend()` in `tools/view-selection-validation.FCMacro:84`, `tools/toolbar-validation.FCMacro:461`, `tools/theme-validation.FCMacro:127`.
  - New `tools/shell-events-validation.FCMacro` (bridge without poll, MDI switch, resetEdit auto-finish, task dialog toolbars, P1-11, 20 releases → 0 tree rebuilds, one summary per operation, exactly one app filter), added to the GUI recipe map as `shell-events`.

**Acceptance.**
- 10 s idle with the 60-hole document: 0 shell passes, 0 intent digests, 0 measurement calls, no active KurtShape QTimer (Panel, watchdog, preview lifetime, recovery).
- Bridge inspect `queue_wait` median ≤ 1 ms and p95 ≤ 3 ms (0.8 ms vs 8.9 ms with the poll).
- Each sketch release ≤ 1 ms, with 0 summaries over 20 releases. Finish produces exactly one summary.
- Exactly one KurtShape app filter. ≤ 25 µs per synthetic MouseMove (168 µs today: 407 vs 239 µs per event with and without the filters).
- Task dialog open/close updates the toolbars within 300 ms.

**Risks.**
- Re-entrancy from nested event loops: handled by deferral without re-arming.
- Dialogs that open with no Show event are covered by the watchdog and `slotInEdit`.

### Increment 12 (F): History tree model/view, rollback bar UI, suppress/reorder UI, inline failures, hover highlight (≈ 9 days, as 12a + 12b + 12c)

**Goal.**
- An Onshape-style feature list in Body.Group order with a draggable rollback bar, suppressed/rolled-back/failed styles and failure messages inline.
- Drag-to-reorder with legal zones.
- Hover highlight.
- Incremental tree updates that keep selection and scroll.

**Delivery split.** Three commits and three reports:
- **12a:** `HistoryModel`/`HistoryFilterProxy`, the `QTreeView`, rows and inline failures, scroll/selection preservation, the macro tree-helper updates, `tools/perf/bench_gui.FCMacro` history apply.
- **12b:** rollback bar, context menu, drag reorder, suppress UI and shortcuts, `tools/part-history-gui-validation.FCMacro`.
- **12c:** hover `ShapeOverlay`.

**Scope.**
- New `src/kurtshape/history_model.py` (`HistoryRow`, `HistoryModel(QStandardItemModel)`, `HistoryFilterProxy`).
- New `src/kurtshape/overlay.py` (`ShapeOverlay`, generalized from `CoinExtrusionOverlay` at `extrusion_preview.py:235-313`) (12c).
- `ui.py`:
  - `make_history` (110–149), `refresh`/`refresh_assembly`/`filter_features`/`selected`/`select_feature`/`history_*` (970–1178);
  - `history_menu` (1795–1828), `context` (477–478), `shortcut_callbacks` (1956–1984).
- `shortcuts.json` (12b):
  - `history.rollback_up`/`down` change from `unsupported` to `callback`;
  - add `history.toggle_suppress` (Shift+U, context history) and `view.variables` (Alt+V) if increment 10 did not.

**Design.**
- **`HistoryModel.apply(rows)`.**
  - A keyed diff: remove missing rows bottom-up, move rows with `root.insertRow(i, root.takeRow(j))`, insert with `parent.insertRow(i, [item])` (list overload only, F16).
  - Update only changed fields. `setIcon` only on a type/flags change, using an icon cache keyed by `(TypeId, flags)` from `ViewObject.Icon`.
  - Fixed rows: `origin` with `plane:XY/XZ/YZ`. Assembly two-level group rows.
- **`HistoryFilterProxy`.** `setRecursiveFilteringEnabled(True)`, case-insensitive. Always keeps the origin subtree.
- **`Panel.features`** becomes a `QTreeView` (header hidden, uniform row heights, custom context menu).
  - Compatibility helpers: `self.items` → `history_model.items` (keys stay feature Names), `history_index(key)`, `history_text(key)`.
  - `select_feature` runs only on explicit user actions.
  - `refresh(delta=None)`.
  - Parts list and body combo rebuild only when their key changes.
  - Each document keeps its own scroll value.
- **Rows.**
  - Order by `bodies[i].history` (increment 8). Several Bodies get one "Part" group each.
  - Rolled back: `#9aa5b1` italic. Suppressed: `#748292` strike-out. Failed: `#a2322c`, plus a non-selectable child row with the elided `status_message` (full text in the tooltip, parent auto-expanded).
- **Rollback bar (12b).** An item with data `rollback:<Body>`, 8 px tall, painted by a delegate as a 3 px `#1c5fa8` line with a grip, inserted at `insertion_index`.
  - Dragging it calls `set_tip`.
  - With the bar selected and the tree focused, `context()` returns `['rollback']`. Up/Down move it one solid feature.
- **Context menu (12b).** Roll back to here, Roll to end, Insert after this (= `set_tip` plus the hint "New features will be added here"), Suppress/Unsuppress (multi-select), Move up/down, Edit, Rename, Delete, Feature settings.
- **Drag reorder (12b).** `InternalMove`. On drag start, `bodies.reorder_window` tints illegal rows light red. On drop, `reorder_feature`. On rejection, rebuild from state and explain in the status bar.
- **Hover (12c).**
  - `setMouseTracking(True)`. `itemEntered` with a 60 ms debounce calls `ShapeOverlay.show`: unpickable, translucent `#1c5fa8` faces, lines drawn with depth `ALWAYS`.
  - Shapes: `feature.AddSubShape` × `body.getGlobalPlacement()` for additive/subtractive features; `feature.Shape` edges for dress-ups and patterns; `sketch.Shape` edges.
  - Clear on leave, refresh and edit.
  - No transaction, recompute or revision change.
  - `Gui.Selection.setPreselection` rendering is **unverified** (not visible in `saveImage`). Use it only as a secondary mechanism.
- **Benchmarks (12a).** Extend `tools/perf/bench_gui.FCMacro` (increment 0) with history apply at 250 rows.

**Tests.**
- Added to `tests/test_shortcuts.py` (12b): `test_rollback_history_contexts_resolve_up_down_and_shift_u`.
- Kept: `test_palette_has_one_meaning_per_key_in_current_context`, `test_all_native_ids_exist_in_pinned_runtime_probe`.
- GUI:
  - 12a: update the tree helpers to the QTreeView API (`history_index`/`scrollTo`/`visualRect`) in:
    - `tools/gui-validation.FCMacro:45-48`;
    - `tools/ui-refinement-validation.FCMacro:149-153`;
    - `tools/view-selection-validation.FCMacro:69-72`;
    - `tools/assembly-gui-validation.FCMacro:137,204,282`.
  - 12b/12c: new `tools/part-history-gui-validation.FCMacro` (bar drag, Up/Down, suppress menu and Shift+U, drag reorder legal and illegal; 12c adds the hover overlay created and cleared with an unchanged revision), added to the recipe map as `part-history` and to the `run-checks` docs.

**Acceptance.**
- 12a. One changed or added row applies in ≤ 5 ms at 250 rows; no change ≤ 1 ms (1.3/1.6 ms and 0.87 ms prototype; today's full rebuild is 20.8 ms at 251).
- 12a. Selection, expansion and scroll are unchanged after an assistant edit that does not touch the selected row. Today the scroll jumps 111→158 at 251 items.
- 12b. Tree order equals `history` after insert and reorder, with the bar at `insertion_index`.
- 12c. The hover overlay shows within 100 ms and clears on leave, with an unchanged revision.

### Increment 13 (F): Live-linked assemblies. Foundation and same-document live occurrences (decision 2) (≈ 5.5 days)

**Goal.** Create assemblies in the same project as the Part Studio. Insert Bodies as live `App::Link` occurrences. Any part change updates the assembly in the same transaction, and undo restores both.

**Scope.**
- `assembly.py`:
  - `global_shape` (148–162), `assemblies`/`get`/`create`/`result_objects` (65–76, 103–118, 128–130);
  - `insert` (361–401), `remove` (599–623), `safe_object` (626–663);
  - fingerprints and validation (666–760), stamp and solve (763–854), `inspect` (857–907, policy string at 898), `handle` (910–930).
- `bodies.py` `results` (21–33).
- `core.py`:
  - ARGS and op sets (via the registry);
  - `_geometry`/`_evaluated_shape`;
  - native-edit guards (340–343, 612–615, 692–701);
  - `_build_status`/`_inspect` (479–550; the unsupported rule at 538–540);
  - capabilities (583–606, including the `assembly_candidates` `source_policy` at 606);
  - open/recover solve (642–654);
  - the registry transaction policies `model`/`history`, `finish_sketch_edit` (719–746), undo/redo (790–809), rebuild (1384–1387);
  - rename (1226–1236), `_export` (1420–1452).
- `document_state.py` (`_LinkTouched` is derived).
- `ui.py`:
  - `set_workspace_mode` (480–516), `create_assembly` (544–571), `insert_assembly_part` (573–624);
  - `refresh` (975–976), the parts list (1040), `refresh_assembly` (1062–1115, hint at 1102);
  - `shell_pass` (native commit handling).

**Design.**
- **`global_shape(obj)`** for `App::Link`/`Assembly::AssemblyLink` with an assembly parent P:
  ```python
  shape = Part.getShape(P, obj.Name + ".", transform=True)
  shape.Placement = P.getGlobalPlacement() * P.Placement.inverse() * shape.Placement
  ```
  Other objects: `Part.getShape(obj, '', transform=True)`; non-links keep `obj.Shape`. This fixes two bugs:
  - a placed Body's Placement was applied twice: for a Body at (100,0,0) rotated 90°, the bbox was wrong, verified;
  - an `AttributeError` on unflagged native assemblies (`App::Link` has no `getGlobalPlacement`).
- **`bodies.results(doc, scope=None)`.** `'part_studio'` = Bodies + standalone results. `'assembly'` = `result_objects` of the root/active assembly. None = today's behavior.
- **`assembly.live_source(obj)`.** `TypeId=='PartDesign::Body'`, no Proxy, and no InList parent of type `Assembly::AssemblyObject`, `Assembly::AssemblyLink` or `App::Part`.
- **`insert`** with `body=<id>` (live): require `live_source` with solids, then `asm.newObject('App::Link', id)`, `LinkedObject=body`, auto-ground if first, solve. STEP and FCStd paths stay as today's snapshot code (increment 15 adds modes).
- **`remove()`** deletes `LinkedObject` only when it is an unreferenced snapshot. It never deletes a live Body.
- **`safe_object`.** An `App::Link` in `asm.Group` is allowed when ordinary, `ElementCount==0`, `source.Document == doc`, and the source is `live_source` or a safe snapshot. The `core.py:538-540` unsupported rule stays: same-document links have no cross-document OutList.
- **Status.**
  - Replace the `SolverStamp` acceptance with residual-based validity. Mark `SolverCode`/`SolverStatus` with `setPropertyStatus(name,'Output')` and keep `SolverStamp` for file compatibility only.
  - `validation_errors` returns `{feature, message, code, scope:'assembly', assembly}`:
    - `missing_source` (`LinkedObject` None);
    - `broken_reference` (`?` prefix or joint Invalid/Error);
    - snapshot fingerprint checks only for snapshot sources;
    - exactly one ground; limits rejected;
    - residuals for Fixed/Revolute/Slider (others come in increment 16);
    - last explicit `SolverCode != 0`.

    Cache it per `(doc, generation)`.
- **One hook for every part change: `_after_part_studio_recompute(doc)`.** When assemblies exist and no lease is active:
  1. `assembly.after_source_change(doc)` (try `solve()` per assembly, record codes, never raise);
  2. `self._recompute(doc)` again to clear solver Touched;
  3. gate rejection only on errors without `scope=='assembly'`. The one-solid check (`core.py:784`) uses `errors or affected_body.Shape.isNull() or len(Solids)!=1` over non-assembly errors.

  Call it, inside the same transaction, from:
  - the registry transaction policies `model` and `history` (so every typed model op, extrude, `edit_extrude` and history op is covered);
  - the commit side of `finish_sketch_edit` (`core.py:719-746`);
  - undo/redo (`core.py:790-809`) when no lease is active (native undo already restores placements; the hook re-solves and refreshes status);
  - the `rebuild` op;
  - the shell pass when a native transaction commit is observed on a managed document with assemblies (native task-panel and Sketcher edits; §4.3 makes FreeCAD task panels the editor for every tool except Extrude). There it runs in its own transaction named "Update assemblies" right after the native commit.

  A Part Studio edit is never rejected because of an assembly consequence.
- **`_build_status`.** `part_studio_status` and per-assembly status. `meta.BuildStatus` is the worst of both. Inspect adds `part_studio: {build_status, bodies}`, and `bodies` is scoped to the active workspace.
- **`_export(body=…)`** is allowed with assemblies present when the Part Studio is valid. Assembly export requires that assembly to be valid, uses `global_shape`, and BRepChecks per source (verdicts shared across occurrences).
- **Open/recover.** One recompute plus an explicit solve per assembly, failures recorded.
- **Edit guards.** A KurtShape assembly in native edit mode counts as idle. `getInEdit()` returns `ViewProviderAssembly`, which has no `.Object` (verified). Check `any(a.ViewObject.isInEditMode() for a in assemblies(doc))`.
- **Transactions.** Keep `App.closeActiveTransaction` after assembly ops (762–763). Also close it after failed model ops when the document had no pending transaction (F17).
- **Geometry cache.** `_shape_dependencies` (increment 1) already covers same-document links.
- **UI.**
  - `create_assembly` deletes the "modeled → new document" branch (563–567) and always creates in the current project.
  - Workspace tabs within one document: "Part Studio" plus each assembly label. Toggle `ViewObject.Visibility` **outside** any transaction (no undo entry, verified on the Linux GUI build, F18), then restore GUI Modified. Links stay visible while the source Body is hidden (verified).
  - Stop forcing assembly mode (975–976).
  - The Insert dialog lists the project's Bodies (live, default) plus a "From file…" button. Help text: "Linked live to your Part Studio; edits update this assembly".
  - Fix the `ui.py:1102` hint text.
  - After a Part Studio change that changes assembly status, notify "Assembly 1 updated" or "Assembly 1: mate Pin broken".
- **Contract.** Insert default = live. capabilities `assembly.source_policy:'live_same_document'`, `source_modes`; `assembly_candidates` (`core.py:606`) reports the same policy. List under Contract 3.7 (`CONTRACT_REVISION` → 7).
- **Docs.** Rewrite `README.md:45-49`, `docs/assembly-workflow/WORKFLOW.md` and `NATIVE_API.md` (policy), and `OPERATION_CONTRACT.md:73-90`. Replace the `shortcuts.json` `assembly.insert` note and the `assembly.py:898` and `core.py:606` policy strings. Add Superseded notes to `VALIDATION.md` and `START_PROMPT.md`.

**Tests.**
- Added in new `tests/test_live_assembly.py`:
  - `test_part_edit_updates_live_assembly_in_one_undo_step`;
  - `test_finish_sketch_edit_updates_live_assembly_in_one_undo_step`;
  - `test_native_feature_edit_then_rebuild_updates_assembly_and_status` (set `doc.Pad.Length` natively, then dispatch `rebuild`);
  - `test_undo_after_sketch_finish_restores_assembly_placements`;
  - `test_save_relocate_recover_and_export_single_file`;
  - `test_placed_body_export_uses_link_placement`;
  - `test_breaking_reference_keeps_part_edit_and_reports_assembly`;
  - `test_deleting_last_live_occurrence_keeps_body`;
  - `test_missing_live_source_reports_blocks_export_and_relink_heals` (relink comes in increment 15; until then assert reporting and the export block);
  - `test_part_studio_results_and_export_coexist_with_assembly`;
  - `test_inspect_native_unflagged_assembly_does_not_raise`;
  - `test_live_assembly_part_edit_overhead_budget` (wall-clock, `KURTSHAPE_PERF=1` only).
- Updated (`tests/test_assembly.py`):
  - `test_native_fixed_revolute_slider_solve_and_allowed_motion`: live fixture.
  - `test_edit_rename_delete_joint_and_cascade_instance_restore_native_references`: the Body survives a cascade.
  - `test_replay_stale_unknown_arguments_and_invalid_inputs_do_not_mutate`: also reject body+path together, a body inside an assembly, and an unknown body.
  - `test_fcstd_reopen_relocation_embedded_policy_and_instance_export`: live fixture, single file, `LinkedObject.Document is doc`.
  - `test_idle_inspection_does_not_resolve_sources_or_run_native_solver`: residual evaluation cached per generation.
- Kept (`tests/test_assembly.py`):
  - `test_free_instance_move_and_jointed_placement_are_one_undo_command`;
  - `test_real_solver_conflict_and_injected_solver_failure_rollback`;
  - `test_native_unresolved_placement_blocks_export_until_explicit_solve`;
  - the STEP snapshot tests;
  - `test_native_edge_and_face_connectors_preserve_allowed_motion`.
- GUI: `tools/assembly-gui-validation.FCMacro` (43, 236–248, 322–338) covers tabs in one document, live update after a Part Studio edit and after a native task-panel edit, and occurrence visibility. `tools/validate_assembly_reopen.py` (27, 55) covers a single-file live project.

**Acceptance.**
- Fixture: Body plus assembly occurrences Lower/Upper, fixed top-to-bottom. `set_parameter Pad.Length 5→9` returns ok, `Upper.Placement.Base.z == 9 ±1e-6` in the same response, status valid, UndoCount +1.
- One undo → 5/5 valid. Redo → 9/9.
- A sketch Finish that changes the Pad profile height, and a native edit followed by Rebuild, move Upper the same way.
- Save to `A/project.FCStd`, copy to `B/C/renamed.FCStd`, close, open the copy → valid, placements equal, and a further edit moves Upper. Recover behaves the same.
- Deleting a referenced face via `delete_feature` commits, and the assembly fails with that joint listed. Assembly export is blocked, `body=` export is allowed, and undo restores valid.
- STEP export of the assembly has one solid per occurrence, with a bbox equal to the union of `Part.getShape(asm, link.Name+'.')` boxes ±1e-5, including a non-identity Body Placement.
- Extra Part Studio edit time caused by the assembly ≤ 150 ms on a 20-hole plate with 6 occurrences and 5 fixed joints (+50 to +140 ms measured).
- Idle inspect: 0 solves, 0 file reads.

**Risks.**
- Face-centre connectors drift when a face outline changes (0.15 mm; a solved part moved by (0.18, 0.63)). Prefer circle edges and vertices in the UI, and warn on non-circular planar faces.
- The native solver returns 0 for conflicts and broken references, so residual checks are mandatory.
- Visibility toggles mark the document Modified.

### Increment 14 (F): Measure panel, Sketcher defaults, single right-hand editor (≈ 5 days)

**Goal.** Measure and mass properties on selection, "Dimensions while drawing", and one right-hand editing area. Each part is small, and together they remove friction.

**Scope.**
- New `src/kurtshape/measure.py`.
- Registry read ops `measure {references: [REF] ×1–2}` and `mass_properties {body?, density_g_cm3?}` (`since='3.8'`, `CONTRACT_REVISION` → 8).
- `ui.py`:
  - `Panel.measure`/`SelectionObserver` (1896–1912, 45–55);
  - `edit_native_feature`/`hide_native_panels` (1884–1894, 31–43);
  - `make_editor` (failure banner);
  - `start()` (2031–2060).
- `workspace_preferences.py` (24–70).
- `shortcuts.json` `general.measure` ('[').

**Design.**
- **`measure.py`** (pure functions, global coordinates). Never import or use the FreeCAD `Measure` module (F23). Resolve every reference with `Part.getShape(obj, sub, needSubElement=True, transform=True)` on the document named by the request, never `App.ActiveDocument`.
  - Edge → `Length`, plus radius/diameter/center when `Edge.Curve` is a `Part.Circle`.
  - Face → `Area`, plus normal when `Face.Surface` is a plane, or radius when it is a cylinder.
  - Vertex → position.
  - Two references → minimum distance with closest points (`distToShape`), delta XYZ, and the angle between straight edges or planar faces.
  - `mass_properties` returns volume, area, centre of mass, inertia and principal properties, plus mass when a density is given, computed over `shape.Solids` (F27): with one solid use `Solids[0].CenterOfMass/MatrixOfInertia/PrincipalProperties`; with several, report a volume-weighted centre and the sum of per-solid inertia tensors moved to the common centre (parallel-axis theorem), and mark aggregate principal axes as unavailable. Computed only on request, through the increment 1 cache where possible.
  - Never create `Measure::*` objects.
- **Measure dock.** Tabified on the right. Opened by `[`. Updates on selection change with a 50 ms debounce, with copy buttons. A mass section has a density field persisted in settings. "Check geometry" calls `check_geometry`.
- **Sketcher.**
  - `User parameter:BaseApp/Preferences/Mod/Sketcher/Tools` `OnViewParameterVisibility` (0 off, 1 sizes, 2 sizes+positions; unset = 1). Write it in `start()` only if absent.
  - Settings gains "Dimensions while drawing" (Off / Sizes / Sizes and positions) and "Auto remove redundant constraints" (`Mod/Sketcher/AutoRemoveRedundants`).
  - Auto-constraints on by default (REVIEW Phase 2 item 4): the key `AutoConstraints` exists in `SketcherGui` (found with `strings -a`), but its parameter group and default are **unverified**. Probe them first; if the default is already on, do nothing; otherwise write it on only if absent, and expose it in Settings.
  - Do not touch the snap keys: their group is **unverified**.
  - Verified: a typed on-view value + Enter creates a driving dimension. It must land inside the managed lease, recorded through the commit hook (`document_state.py:51-54`).
- **Right-hand editor** (hybrid default).
  - During `setEdit`, tabify the native "Tasks" dock with "Feature settings" and raise it.
  - Add a KurtShape header row: title "Edit Fillet", help text, and Confirm/Cancel calling `Gui.Control.activeTaskDialog().accept()`/`reject()` (verified methods).
  - Do not reparent `getDialogContent()` widgets.
  - Hiding the native button box is **unverified**. Try it only behind a flag.
  - A red failure banner at the top of Feature settings shows `status_message` with Edit / Suppress / Roll back quick actions.

**Tests.**
- Added in new `tests/test_measure.py`:
  - `test_measure_edge_face_distance_angle_radius_and_mass_properties_on_demand` (no document objects created, revision unchanged);
  - `test_measure_works_while_another_document_is_active`;
  - `test_measure_works_with_no_active_document`;
  - `test_mass_properties_on_pocketed_body` (`Body.Shape` is a Compound).
- GUI: `tools/part-history-gui-validation.FCMacro` gains the Measure panel and an on-view constraint created inside the lease (Cancel removes it, Finish commits it as one undo step).

**Acceptance.**
- The Measure panel updates ≤ 100 ms after a selection change on the example plate, with no document objects created.
- Measuring never depends on the active document; `git grep -n "import Measure\|Measure\." -- src` is empty.
- With Sizes on, typing a circle size and Enter inside a managed sketch creates a driving dimension. Cancel removes it, and Finish commits it as one undo step.
- Native task panels appear in the right dock under the KurtShape header.

### Increment 15 (F): Pin/unpin, source indicators, external sources (≈ 4 days)

**Goal.**
- Pin an occurrence to a frozen snapshot, and unpin it back to live.
- Show source state.
- Bring external FCStd parts in as live parametric copies, or as pinned copies with an explicit update.

**Scope.** `assembly.py` (`insert`, new `pin`/`unpin`/`relink`/`update_source`, `inspect`), registry ops (`since='3.9'`, `CONTRACT_REVISION` → 9), `ui.py` `refresh_assembly`/`insert_assembly_part`/context menu.

**Design.**
- **Snapshot properties.** Keep the existing `SourcePath`, `SourceSHA256`, `SourceObject`, `SourcePlacement`, `SourceGeometryFingerprint`, and add:
  - `SourceKind` ∈ {`part_studio_body`, `step`, `fcstd`};
  - `SourceIntent` (sha256 of `json(native_intent(doc, [body]+body.Group))`, for part_studio_body);
  - `PinnedAt` (ISO 8601).

  All read-only, group "KurtShape Assembly" (allowed by invariant 1). Snapshot geometry = `body.Shape.copy()` with identity Placement. The element map is preserved (26/26), and joint references survive relinking (verified).
- **Ops:**
  - `pin_assembly_instance {assembly, instance}`: reuse a matching snapshot (same `SourceObject` and `SourceIntent`), else create one hidden; relink; solve.
  - `unpin_assembly_instance`: relink to the live Body; remove the snapshot if unreferenced.
  - `relink_assembly_instance {assembly, instance, body}`.
  - `update_assembly_instance_source {assembly, instance}`: external pins only; re-read through `_source_document` with a fresh hash.

  After any relink, re-validate every joint touching the instance with `_reference()`. A broken reference rolls back.
- **Insert modes.**
  - `path=.step` → pinned (`SourceKind 'step'`).
  - `path=.fcstd, mode='pinned'`.
  - `path=.fcstd, mode='import'` (the GUI default for FCStd): inside the existing `_source_document` context (preflight, hash race, unsafe-proxy rejection, disposable hidden document, which is never attached), call `doc.copyObject(selected_body, True)`. Verified parametric, with no cross-document OutList. FreeCAD renames objects on collision. Set an `ImportedFrom` JSON `{path, sha256, source_id}` read-only property (allowed by invariant 1), then live-link.
  - Expression remapping across renamed objects is **unverified**: probe it with a source that has expressions.
- **Inspect, per instance:**
  - `source {kind: part_studio_body|pinned_body|step_snapshot|fcstd_snapshot|subassembly, object, live, pinned, source_changed, missing, path, sha256}`;
  - `connected_to_ground`.

  `source_changed` for `pinned_body` compares `SourceIntent`. For external pins it is reported only after an explicit check (no file I/O on idle).
- **UI.** Suffixes " · pinned", " · source changed", " · missing source", " · broken mate". Context menu: Pin to version, Unpin, Update from source, Relink, Show in Part Studio. The Insert dialog's FCStd options are "Import into project (live, editable)" (default) and "Insert pinned copy".

**Tests.**
- Added to `tests/test_live_assembly.py`:
  - `test_pin_unpin_preserves_joint_references_and_freezes_geometry`;
  - `test_missing_live_source_reports_blocks_export_and_relink_heals` (complete);
  - `test_fcstd_import_into_project_is_parametric_and_live`.
- Updated:
  - `test_candidates_repeated_embedded_occurrences_and_ground_switch` (`mode='pinned'`; `assembly_candidates` with `document_id` lists same-document Bodies);
  - `test_original_three_solid_steps_insert_explicit_bodies_and_preserve_sources` (`mode='import'` or `'pinned'`; external);
  - `test_original_steps_insert_directly_as_three_solid_choices` (asserts `source.kind=='step_snapshot'`);
  - `test_source_script_and_nested_link_safeguards_are_not_weakened` (both modes; preflight before `copyObject`);
  - `test_embedded_source_native_geometry_change_rejects_until_undo_restores_snapshot` (pin first).
- Kept: `test_marked_embedded_source_with_python_property_is_not_trusted_or_adoptable`, `test_direct_step_instances_replay_undo_and_portable_saved_snapshot`, `test_direct_step_invalid_sources_and_read_race_leave_assembly_intact`, `test_step_choices_keep_nested_placements_and_ignore_reference_surfaces`.

**Acceptance.**
- A pinned instance ignores a later Pad edit (bbox unchanged) while live instances update.
- `source_changed=true` is reported.
- Unpin restores live geometry.
- Joints stay valid throughout, and each op is one undo step.
- Import mode leaves the source file's SHA-256 unchanged.

### Increment 16 (F): All native joint types and solver drag (≈ 5.5 days)

**Goal.** All 13 joint types, with parameters and per-type residual checks. Drag parts with the native solver in the assembly tab.

**Scope.**
- `assembly.py`: `KINDS` (24), `create_joint`/`edit_joint` (460–497), `_solution_residuals`, `solve`.
- `core.py` native-edit guards (340–343, 612–615, 692–701).
- `ui.py`: toolbar (358–379), joint dialog (664–727), move dialog (729–784), `set_workspace_mode`.
- Registry: joint parameters (`CONTRACT_REVISION` → 10).

**Design.**
- **Joint types** (`Mod/Assembly/JointObject.py:65-144`): Fixed, Revolute, Cylindrical, Slider, Ball, Distance, Parallel, Perpendicular, Angle, RackPinion, Screw, Gears, Belt.
- **Parameters** (`distance`, `distance2`, `angle`):
  - Angle uses `Angle` (deg).
  - Distance uses `Distance` (mm, may be negative).
  - RackPinion: `Distance` = pitch radius. Screw: `Distance` = pitch.
  - Gears/Belt: `Distance` and `Distance2`, both ≥ 0.
  - Reverse applies to Fixed/Revolute/Cylindrical/Slider/Distance/Parallel.
  - Limits stay rejected.
  - RackPinion, Screw, Gears and Belt need both parts already constrained by a revolute/slider to ground. Otherwise reject with `assembly_motion_locked` or report the part as not connected.
- **Residuals.** With `rel = F1.inverse()*F2` and `z = rel.Rotation.multVec(Z)`:
  - Fixed: `|rel.Base|`, `rel.Rotation.Angle`.
  - Revolute: `|Base|`, z∥Z.
  - Cylindrical: `hypot(x,y)`, z∥Z.
  - Slider: `hypot(x,y)`, Angle.
  - Ball: `|Base|`.
  - Parallel: z∥Z.
  - Perpendicular: `|z·Z|`.
  - Angle: `|acos(|z·Z|) - Angle|`.
  - Distance and the coupling joints: native code 0 plus connectivity, reported with `residual_checked=false`.

  Tolerances 1e-5 mm and 1e-6 rad.
- **`move_assembly_joint`** extends to Cylindrical (value plus axis `rotation`|`translation`) and Ball (`rotation_xyzw`).
- **Drag.**
  - Entering an assembly tab calls `Gui.getDocument(doc.Name).setEdit(asm)`. Verified: no task dialog, no transaction opened, and `EnableMovement` defaults True (F18).
  - Native C++ drag commits a transaction named "Move part". That name was found only in binary strings; it is **unverified** at runtime, so confirm it with a GUI probe. The commit reaches increment 13's native-commit hook.
  - Whitelist this edit mode in the guards.
  - Set the Assembly preference `LeaveEditWithEscape=False` for the session, or re-enter edit after Escape.
  - While a non-KurtShape active transaction exists, reject typed mutations with `busy`.
  - `resetEdit` when leaving the tab or starting a sketch.
  - Never touch `DraggerPlacement` (F15).
- **UI.**
  - A Mate menu with the 13 types. Parameter fields shown per type.
  - The face/edge pick default prefers circle edges and vertices, with a warning for non-circular planar faces.
  - Shortcut statuses for `general.mate_connector(s)`/`mate.flip_axis` change only if implemented. Any new Assembly `native_command` follows invariant 14 (add AssemblyWorkbench to the probe and the test).

**Tests.**
- Added in new `tests/test_assembly_joints.py`: `test_all_native_joint_types_create_solve_and_report_parameters`.
- GUI: the assembly recipe covers native edit mode in the tab, typed ops accepted while idle, a scripted "Move part" commit bumping the revision with status valid, and no `DraggerPlacement` access.

**Acceptance.**
- Each of the 13 types solves with native code 0.
- Residual-checked types meet 1e-5 mm / 1e-6 rad.
- Coupling joints without support are rejected or reported not connected.
- Drag works and stays consistent with the guards.

### Increment 17 (F): Sub-assemblies, BOM, exploded views (≈ 5.5 days)

**Goal.** Multiple assemblies per document, rigid sub-assemblies, a derived BOM with CSV export, and exploded views stored natively and drawn by KurtShape.

**Scope.**
- `assembly.py`: `get`, `create`, `result_objects`, new `root_assemblies`, `insert_subassembly`, `bom_rows`, `exploded_shape`, `safe_object`.
- Registry: `insert_subassembly`, `assembly_bom`, `export_bom`, `create_exploded_view`, `edit_exploded_view` (`since='3.11'`, `CONTRACT_REVISION` → 11).
- `ui.py`: `refresh_assembly`, the assembly toolbar, workspace tabs.
- `overlay.py` (exploded display through `ShapeOverlay`).
- `core.py`: `_export` (`exploded` option).

**Design.**
- **Multiple assemblies.**
  - `get(doc, identifier)`: an explicit id, else the single assembly, else `missing_assembly`.
  - `create` no longer rejects a second assembly; a duplicate id is still rejected.
  - Add `root_assemblies`.
  - `result_objects(doc, asm)` excludes JointGroup, ViewGroup and BomGroup.
- **`insert_subassembly {assembly, subassembly, id, name, rigid}`.**
  - Creates `asm.newObject('Assembly::AssemblyLink', id)` with `LinkedObject = sub` and `Rigid` default True.
  - Flexible mode mirrors links and joint copies into the Group (verified).
  - Reject cycles (`sub == asm` or `sub in asm.InListRecursive`).
  - Solve leaf assemblies first.
  - Export via `Part.getShape(asm, link.Name+'.')` counts sub-assembly solids once.
- **`assembly_bom` (read) and `export_bom {path, assembly}` (disk, `.csv` via `write_path`, invariant 17b).**
  - `bom_rows(doc, asm, detail_subassemblies=True)` groups by resolved source, giving Label, quantity and nested index `n.m`. This matches the native BomObject output.
  - An optional native `Assembly::BomObject` does not refresh on structure changes without `touch()` + `recompute()`, so refresh it before save/export.
- **Exploded views.**
  - `create_exploded_view {assembly, id, name, steps}` / `edit_exploded_view` create native `Assembly::ViewGroup` + `CommandCreateView.ExplodedView`/`ExplodedViewStep` objects. This needs `App.GuiUp` (`gui_required` otherwise): `CommandCreateView` cannot be imported headless (NameError QtCore). A headless reopen restores `Proxy None` with the data intact.
  - `exploded_shape(doc, view)` ports `_calculateExplodedPlacements`:
    - Normal: `MovementTransform * current`.
    - Radial: `factor = 4*|MovementTransform.Base|/size`, `base += (obj_com - asm_com)*factor`.
  - Display uses `ShapeOverlay` (read-only). Do not use the native provider, which mutates link placements temporarily.
  - Export option `exploded=true`.
  - `safe_object` accepts exact `CommandCreateView` proxy types, or `Proxy None` with exactly the native property sets.

**Tests.** Added to `tests/test_assembly_joints.py`:
- `test_subassembly_rigid_link_solves_exports_once_and_rejects_cycles`;
- `test_bom_rows_count_occurrences_and_subassemblies`;
- `test_exploded_shape_from_native_step_data_headless`.

Updated: `test_single_level_busy_and_native_edit_guards_preserve_assembly`. A second assembly is now allowed, a duplicate id is rejected, and ops need an assembly id. Keep the busy and lease guards.

**Acceptance.**
- A rigid sub-assembly solves, exports its solids once, and rejects cycles.
- BOM quantities are right after adding and removing occurrences, with no manual refresh.
- `exploded_shape` with a step of +30 mm z gives zmax 34 on the fixture and leaves link placements unchanged, headless.
- `export_bom` outside a granted root is rejected by `write_path`.

**Cross-document live links (deferred).** Do not implement them unless Kurt asks. If he does, the requirements are:
- both documents saved first;
- open sources fully through controller `open`, never partial;
- map source recomputes to dependents via `Body.InList`;
- coordinated undo through unique transaction names;
- `save_sources`;
- re-assign every cross-document `LinkedObject` after `saveAs` and after recovery to another folder;
- recovery manifests with absolute source maps;
- relax `core.py:538-540`/`946-948` and `assembly.py:626-647` only for `App::Link` → Body in a managed, fully loaded, saved document.

### Increment 18: Final hardening and handoff (≈ 2.5 days)

- Enable `--enforce --phase phase1` on the nightly 60-hole perf job, once ≥ 5 stable samples exist on windows-2025 (or on a self-hosted runner, if Kurt approves one). This needs Kurt to have pushed.
- Display settings (REVIEW Phase 1 item 6): evaluate `UseVBO`, `RenderCache` and tessellation deviation on the 60-hole plate; keep only what measurably improves orbit frame time in an isolated GUI recipe; record before/after.
- Add `ARCHITECTURE.md`, a contributor overview: controller and registry, observer and intent index, geometry cache, preview, recovery and workers, assemblies, the GIL rule.
- Update README Launch and verification, and finish the Appendix A stale-doc grep gate.
- Optional, after all feature work lands and only with Kurt's approval: a formatting-only commit (`ruff format`, line-length 120; about 71 files, +8,492/−3,142), recorded in `.git-blame-ignore-revs`, then add `ruff format --check` to CI and expand rules (E4/E7, I, B, E501 at 160 with per-file E402 ignores for tests and macros).
- Final report: a walkthrough list for Kurt, and the 0/2 statement.

## 9. Performance budgets and how to measure them

"Overhead" means time outside FreeCAD's own recompute. Budgets are judged on Kurt's machine (Windows build 26200, 32 logical processors), on the 60-hole fixture (§7.4) unless noted. CI hosted runners give trends only. HEAD values come from `docs/2026-10-03-claude-review/evidence/` unless marked.

| Interaction | HEAD (60 holes) | Target | Increment | How measured |
|---|---:|---:|---|---|
| Dimension edit, overhead | 5.3 s | ≤ 150 ms; then ≤ 50 ms | 1; 7 | `bench_core tip_edit.overhead_ms`; `StatusPerformanceTests.test_tip_edit_overhead_budget` |
| Add pocket, overhead | ≈ 10 s (12.4 s total) | ≤ 300 ms | 1 | `bench_core add_pocket.overhead_ms` |
| Inspection after a shape change | 4.95 s | ≤ 20 ms | 1 | `inspect_after_change_ms`; `StatusPerformanceTests` |
| Idle inspection | 18 ms | ≤ 20 ms (and 0 work while idle after 11) | 1, 11 | `inspect_warm_ms`; idle GUI check |
| Open, beyond native open | +12.7 s | ≤ max(300 ms, 10 %) with 0 recomputes | 1 | `kurtshape_open_ms - native_open_ms` |
| Extrude preview first frame (blind) | 15.7 s first evaluation; 15.1 s later ones | ≤ 50 ms GUI; `evaluate()` ≤ 10 ms | 3 | GUI macro first-frame check; `test_first_evaluation_budget_on_60_hole_plate` |
| Preview depth update | 15.1 s | ≤ 5 ms | 3 | same |
| Native-path preview (up to next) | — | provisional ≤ 50 ms; exact ≤ 1.5 s | 4 | `test_up_to_conditions_use_native_path_without_trace` |
| Recovery stall | 1.27 s every 30 s | none during input; snapshot p95 ≤ 50 ms; visible gap ≤ 16 ms | 5 | `recovery_snapshot_gui_ms`; synthetic-input GUI check |
| Save verification | 40 ms (testzip median) | ≤ 5 ms | 5 | `save_verify_ms` |
| Intent hash after tip / root edit (132 objects) | 34–40 ms | ≤ 3 ms / ≤ 10 ms | 7 | `IntentIndexTests` counters + timings `intent` |
| GUI summary after a single change | 14.9 ms (132) / 29.4 ms (257) | ≤ 5 ms / ≤ 8 ms | 7 | timings `summary` |
| STEP import, GUI share (25 bodies) | 13.3 s | ≤ 400 ms (1 body ≤ 50 ms); heartbeat gap ≤ 50 ms | 9a | `io-jobs-gui-validation` |
| Export, GUI share | ≈ 1.0–1.4 s write + 1.9 s check | ≤ 50 ms | 9b | `io-jobs-gui-validation` |
| STL default facets | 30,492 | ≤ 15,000 | 9b | `test_stl_presets_are_relative_and_recorded_in_provenance` |
| Bridge queue wait (idle) | median 8.9 ms | median ≤ 1 ms, p95 ≤ 3 ms | 11 | `shell-events-validation` |
| App event filter overhead | 168 µs / MouseMove (407 vs 239 µs, 40-hole GUI bench) | ≤ 25 µs | 11 | `test_unregistered_event_types_stay_under_budget` |
| Sketch mouse release | 6–17 ms + rebuild | ≤ 1 ms, 0 summaries | 11 | GUI check, 20 releases |
| History tree apply, one row at 250 rows | 20.8 ms full rebuild | ≤ 5 ms; no-change ≤ 1 ms | 12a | `tools/perf/bench_gui.FCMacro` |
| History ops overhead | — | ≤ 150 ms | 8 | `test_part_history` timings |
| Part edit extra cost from a live assembly (20 holes, 6 occurrences, 5 joints) | — | ≤ 150 ms | 13 | `test_live_assembly_part_edit_overhead_budget` |
| `evaluate_expression` | — | ≤ 20 ms | 10 | `test_variables` |
| Idle CPU | ≈ 0 | ≈ 0, no active KurtShape timers | 11 | idle GUI check |

**Measurement procedure:**
1. `& "$FC\python.exe" -B tools\perf\bench_core.py --holes 60 --repeat 3 --scratch runtime\bench --out runtime\bench\bench-60.json`.
2. `& "$FC\python.exe" -B tools\perf\report.py runtime\bench\bench-60.json --baseline validation\2026-10-03-upgrade\foundation\bench-60.json --phase phase0|phase1`.
3. `$env:KURTSHAPE_PERF='1'` and run the native suite for `StatusPerformanceTests` and every other wall-clock test (PERFREPORT lines).
4. Run the GUI recipes for GUI budgets (`.\tools\run_gui_recipe.ps1 -Recipe bench-gui`, `io`, `shell-events`, …).

Record medians, p95, worst and sample counts.

**Regression gate:**
- **Local.** An increment may not regress any budgeted metric of an earlier increment by more than 20 % against the previous increment's recorded `bench-60.json` on Kurt's machine. If it does, fix it, or stop and explain.
- **CI (after Kurt pushes).** The perf job is non-blocking at first. After increment 1 plus 5 stable nightly samples, the nightly 60-hole run uses `--enforce --phase phase0`. After increment 11 it uses `--phase phase1`.

## 10. Overall definition of done, and out of scope

**Done when:**
- All increments 0–18 (including 6b, 9a/9b and 12a/12b/12c) are committed in order, each with green `run-checks.ps1` (and `-Full` on Kurt's machine), green `tools\ci\run-local.ps1`, green Windows CI once Kurt has pushed, recorded evidence, and updated plan, implementation and progress docs.
- The §9 budgets are met on Kurt's machine.
- Contract 3 is fully documented (`OPERATION_CONTRACT.md` Contract 3 section and all 3.N additions; README Assistant access; `docs/operation-schemas.json` current).
- The Appendix A grep gate passes.
- No test writes tracked files.
- Kurt has a walkthrough list for each Phase-level gate: hands-on Part Studio workflows; edit part → assembly updates → undo restores both; save/relocate/reopen.
- M1 is still reported as incomplete with 0/2 real conversions.

**Out of scope / deferred (do not start without Kurt):**
- configurations, drawings (TechDraw), named versions and project history;
- MCP server and skill (beyond `tool_definitions()`);
- simulation;
- thin and surface extrude, Up to vertex, and Up to part (no direct native equivalent / unprobed binder design);
- exact (boolean) preview;
- converting the parameter/expression `preview` op from a hidden clone to the traceless transaction;
- KurtShape-styled panels for tools other than Extrude;
- joint limits;
- cross-document live links (increment 17 note);
- assistant write-root scoping (REVIEW P1-12) until Kurt decides;
- idle background geometry check;
- `check(True)` deep BOP checks;
- fast-save settings for user saves;
- the post-undo recompute cost (761 ms at 60 holes);
- macOS/Linux support;
- Linux CI as a gate;
- source reconstruction of the hub and the M1 real-conversion gate (stays 0/2 and must not be claimed);
- Kurt's deferred edited STEP variants.

---

## Appendix A. Stale statements to fix, and grep gates

**Living docs: edit in place, in the commit of the matching increment.**
- Increment 0: `README.md:69-77` (run-checks switches, conditional source checks, evidence location), `docs/INTERFACE_PASS.md:21-23`, `docs/STEP_IMPORT.md:16`.
- `README.md:49` and `README.md:66` (assistant access and contract; snapshot assembly policy).
- `README.md` lines 19, 29, 31, 45–49, 53–55 as affected.
- `docs/OPERATION_CONTRACT.md`:
  - lines 5, 12, 27, 36 (inc 1);
  - 23 and 49 (inc 3–4: extrude preview and pocket/extrude; the parameter-preview clone text at 49 stays true);
  - 53 (inc 1/3);
  - 57 (write roots, if changed);
  - 63 (inc 1/5: BRep validity cache and 30 s checkpoints);
  - 65 (inc 1: open rebuild);
  - 73–90 (inc 13: assembly policy).
- `DESIGN.md:15` (extrusion preview).
- `docs/assembly-workflow/WORKFLOW.md:7`, `:9`, `:48` and `NATIVE_API.md` (inc 13, policy docs).
- `docs/SKETCH_PLANE_CONTRACT.md:43` (inc 1/5, recovery and open).
- `docs/ONSHAPE_SHORTCUTS.md:5`: counts are already stale. The registry has 55 callback / 38 native / 30 unsupported / 6 pass_through = 129. Recompute from `shortcuts.json` whenever a status changes, and update the README shortcut section.
- `docs/STEP_IMPORT.md` (inc 9) and `docs/general-actions-compatibility.md` as affected.
- Code strings:
  - `assembly.py:898` source_policy text;
  - `core.py:584-589` `embedded_shape_snapshot` / `nested_assemblies False`;
  - `core.py:606` `assembly_candidates` `source_policy` (inc 13);
  - `ui.py:1102` hint;
  - `shortcuts.json` notes for `assembly.insert`, `history.rollback_up`/`down`, `general.mate_connector(s)`, `mate.flip_axis`.

**Dated records: keep history.** At the stale paragraph, prepend "Superseded <date> by … (link)". Applies to `docs/ui-refinement/*`, `docs/ui-refinement-preview/README.md`, `docs/workspace-behavior/*`, `docs/2026-10-02-*`, older `M1_PROGRESS.md` sections, `docs/assembly-workflow/VALIDATION.md`, `START_PROMPT.md`, `COORDINATION.md`. Leave REVIEW.md unchanged: §4.2 of this brief records the overrides.

**Grep gate.** After the matching increments, `git grep -n "<phrase>" -- README.md DESIGN.md PRODUCT.md docs/OPERATION_CONTRACT.md docs/SKETCH_PLANE_CONTRACT.md docs/ONSHAPE_SHORTCUTS.md docs/assembly-workflow/WORKFLOW.md src` must find none of these phrases (nor may capabilities report them), except inside explicit "Superseded" notes:
- "source edits do not automatically update"
- "Extrusion preview uses a hidden disposable" (the `DESIGN.md:15` extrusion text; the parameter-preview clone described at `README.md:66` and `OPERATION_CONTRACT.md:49` stays)
- "Open freshly rebuilds"
- "BRep validity is cached"
- "Checkpoints run at up to 30-second"
- "embedded_shape_snapshot"

If an exact phrase differs slightly in a file, match the stale statement, not the literal string, and record the grep you used.

## Appendix B. Verify first (unverified facts this brief relies on)

Probe each item on Kurt's Windows runtime before the increment that depends on it. Record the result in that increment's plan, and fall back as stated.

1. `Path(App.getHomePath()).resolve()` equals today's `NATIVE_PATH` on Windows (inc 0). `test_runtime_layout` proves it. If it fails, stop.
2. Hosted Windows runners: whether 7-Zip is at the default path (it is on PATH per the image source), and whether FreeCAD's GUI renders with `QT_OPENGL=software` in a desktop session (inc 0, after push). The GUI job is informational.
3. Git `core.autocrlf` default on runners (inc 0). The workflow sets it to false anyway.
4. Whether a worker launched with `CREATE_NO_WINDOW` flashes a console window (inc 9a; prove with a screenshot). PySide6 6.8.3 on Windows is verified from the archive listing.
5. `os.replace` sharing violations from Defender or OneDrive (inc 5, 9). `replace_with_retry` covers them.
6. Through-all 2.02 × diagonal on inclined sketches. Taper beyond ±10° (inc 3–4). The display shape is unaffected; fall back to the native path.
7. Onshape's 25 mm default depth (inc 6). Use the sticky last value either way.
8. Whether a Sketcher point drag ends in a transaction commit (inc 11). The release boundary stays as a fallback.
9. Sketcher snap preference group (inc 14). Do not touch the snap keys. Also the `AutoConstraints` parameter group and default (inc 14).
10. Preselection highlight rendering, and hiding the native task button box (inc 12c, 14). Overlay and header are the primary path.
11. `SoLinearDragger` interaction from Python (inc 6b optional upgrade; `SoTranslate1Dragger` is the verified path).
12. A Visibility change outside a transaction creates no undo entry and sets Modified: verified on the Linux GUI build (F18); re-check once on Windows in the inc 13 GUI recipe.
13. The "Move part" transaction name at runtime (inc 16).
14. `copyObject` expression remapping across renamed objects; sources with VarSets or spreadsheets (inc 15).
15. External-fixture aggregate tolerances after per-object volume sums (inc 1; run `-Full` on Kurt's machine).
16. `App.getTempPath()` location on Windows (inc 5); the recovery GUI check resolves it at runtime.
17. Windows timer quantization of the old 25 ms poll. Background only; no action needed.
18. All Linux timings: re-baseline on Kurt's machine in increment 0.
