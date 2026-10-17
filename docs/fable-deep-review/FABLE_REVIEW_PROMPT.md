# Fable: deep review of KurtShape

Review KurtShape deeply and independently. I want improvements big and small across the frontend, viewport graphics, CAD workflows, backend, reliability, performance, and maintainability. Help make it feel like a polished, professional CAD application that is pleasant to use every day. Be candid and specific. Produce a review and implementation roadmap; do not implement application changes in this pass.

## Project and constraints

Repository: `C:\Users\Kurtz\Documents\KURT\CADkz\Codex\kurtshape`.
Workspace instructions: `C:\Users\Kurtz\Documents\KURT\CADkz\AGENTS.md`.

KurtShape is a native Windows Qt/PySide application layered over FreeCAD 1.1.4 / OCCT 7.8.1. Native FCStd documents are authoritative. It combines direct graphical modeling with a token-authenticated, revision-checked assistant bridge. This is a desktop CAD editor, not a web dashboard.

Preserve the established light, compact, Onshape-inspired workspace and SolidWorks mouse navigation as the baseline. Geometry should dominate the screen. Persistent toolbars intentionally use icons, with names in hover/focus labels, menus, and search. Judge discoverability within that constraint. You may propose a more ambitious visual direction, but show it separately, explain the benefit, and identify which existing design decisions it would change.

Read the applicable instructions before acting. Do not screenshot, click, restore, type into, or otherwise take over Kurt's KurtShape or BumpMesh windows with desktop tools. Do not restart his session or alter his open models. Use existing image evidence and source inspection. If you need reproducible native experiments, use the documented isolated Controller or private validation harness, with separate profiles, session directories, documents, and outputs. Do not capture Kurt's live desktop. Use the assistant bridge for interaction with his CAD app; never bypass its model ownership rules. Never overwrite an FCStd open in the app. Do not expose bridge tokens or session-file contents.

Preserve existing edits and original models. No commits, publishing, installs, dependency upgrades, or broad refactors as part of this review. Keep new review materials in descriptive folders under `docs/fable-deep-review/`. If repository/runtime access is unavailable, list the missing evidence and provide a conditional review without inventing observations.

## Establish the actual baseline

Record the checkout revision, working-tree differences, runtime version if verified, and evidence dates. Distinguish checked-out code from whatever version a running app may have loaded. Do not infer current behavior from a historical pass count or screenshot alone.

Start with:

- `README.md`, `PRODUCT.md`, `DESIGN.md`, `ARCHITECTURE.md`.
- `docs/OPERATION_CONTRACT.md` and `docs/M1_PROGRESS.md`.
- `docs/architecture-responsiveness-upgrade/STATUS_REPORT.md`, then the relevant detailed records.
- `docs/ui-refinement/`, `docs/onshape-design-audit/`, `docs/sketch-interaction-reliability/`, and `docs/assembly-workflow/` as needed.
- Existing images in `validation/onshape-theme-repair/`, `validation/ui-refinement/`, `validation/sketch-presentation/`, and `docs/sketch-interaction-reliability/evidence/screenshots/`.

Map the architecture and examine the implementation before treating prior review conclusions as current facts. Read `PRELIMINARY_REVIEW.md` as starting leads, not as an answer to reproduce. Identify already-solved issues and preserve working strengths.

## 1. Professional appearance and viewport graphics

Review the shell, feature history, parts list, document tabs, modeling toolbars, native Tasks, floating editors, menus, settings, messages, empty states, and transitions between modeling contexts.

Inspect typography, alignment, spacing, information density, borders, contrast, focus, disabled states, selected states, long labels, and visual hierarchy. Examine the consistency of original grayscale SVGs, native fallback icons, and colored history/task icons. Find ambiguous silhouettes and visually mismatched weights at actual toolbar sizes. Recommend a coherent icon strategy and distinguish useful semantic color from accidental inconsistency.

Evaluate native task-panel integration: width, wasted space, truncated solver messages, competing Finish/Close/Confirm controls, scrolling, and viewport obstruction. Check saved layout restoration, multiple monitors, small windows, Windows scaling at 100/125/150/200%, and keyboard accessibility. Do not assume a browser accessibility detector validates native Qt behavior.

Treat viewport quality as its own workstream: tessellation, anti-aliasing, edge contrast and thickness, lighting, material response, depth cues, transparency, selection/preselection, preview shading, sketch dimensions and constraints, construction geometry, origin planes, navigation cube, and section views. Determine what the pinned native renderer actually supports. Do not promise rendering effects based on familiarity with another engine.

Assess whether draft/standard/presentation quality presets would improve usability beyond the existing high-quality tessellation toggle. Keep display quality separate from model precision and exported mesh settings. Preserve per-part appearances and accurate picking. Estimate GPU/memory cost and dense-model behavior; identify platform limitations and fallbacks.

Deliver concrete visual proposals: annotated existing images or clearly labeled concept mockups for the main workspace, sketch editing, and a feature editor with pending/valid/error states. Use actual CAD controls and plausible content. For each proposal, specify what changes, why it helps, and the likely Qt/FreeCAD implementation path. Include both a restrained polish option and a more ambitious option. Do not present concepts as screenshots of implemented functionality.

## 2. Everyday modeling and interaction

Trace the user's journey through new/open/import, sketch plane selection, drawing and constraints, dimension editing, extrusion/pocket, fillet/chamfer, sweep/loft, patterns, reference planes, multipart operations, assembly, save/reopen, and STEP/STL export.

Evaluate active-part versus selected-part clarity; sketch versus model mode; current versus historical geometry; rollback; hidden versus suppressed features; reference selection; preview versus committed results; and modified versus saved document status. Find places where the user must remember invisible state or cannot tell why a tool is unavailable.

Inspect hover/click consistency, selection ownership, ambiguous references, picking thin edges or overlapping objects, snapping, geometric constraints, units/expressions, keyboard focus, Escape, Enter, undo/redo, and cancellation. A matching coordinate is not automatically a maintained parametric relationship: investigate bridge-created line-to-line endpoint continuity when dimensions change.

Assess recovery from invalid geometry, broken references, failed recomputes, unsupported commands, import problems, and abandoned edits. Errors should identify the problem and a useful next step while retaining entered values. Inspect notification priority and Messages discoverability without demanding that every technical detail appear in the main workflow.

Consider both Kurt's expert workflow and someone familiar with Onshape/SolidWorks but new to KurtShape. Recommend high-value missing capabilities based on concrete modeling tasks. Separate absent functionality, difficult-to-discover functionality, and functionality already present only through native UI or only through the bridge.

## 3. Architecture and code quality

Trace request flow from UI/shortcuts and HTTP through Controller, native transactions, observers, caches, recompute, worker processes, result acceptance, and refresh. Identify ownership boundaries and where state can diverge.

Key sources include `src/kurtshape/ui.py`, `core.py`, `studio.py`, `selectors.py`, `document_state.py`, `document_index.py`, `incremental_intent.py`, `inspection_cache.py`, `geometry.py`, `feature_panel.py`, `extrusion_preview.py`, `tool_session.py`, `history_model.py`, `shortcuts.py`, and `feature_tools.py`.

Review the large UI/controller modules for responsibilities that can be extracted incrementally. File size alone is not a defect: connect each proposed boundary to a real testing, lifecycle, consistency, or maintenance problem. Investigate a shared command descriptor/registry for toolbar actions, menus, shortcuts, search, availability, help, and bridge capabilities; define which semantic distinctions must remain separate.

Review duplicated validation, operation schemas, error taxonomy, state-machine clarity, exception handling, settings persistence, resource ownership, observer invalidation, transaction boundaries, temporary files, shutdown, and dependency/version assumptions. Avoid proposing a second authoritative model or moving live FreeCAD handles between threads/processes.

For any architectural redesign, compare it with a smaller change. State migration steps, compatibility costs, failure modes, rollback, and evidence required before promotion. Prior authoritative-process and cache/recompute experiments include incomplete or failed gates; do not call them production-ready.

## 4. Responsiveness and scalability

Workers already exist for previews, geometry checking, and eligible STEP exports. Investigate the remaining synchronous admission, snapshot preparation, hashing, capture, acceptance/publication, save/import, rebuild, and fallback paths. “Use background threads” is not an adequate proposal for native calls that retain the GIL or require Qt ownership.

Measure whole user actions and input-to-feedback latency separately from internal phases. Distinguish pending state from feedback actually painted. Check whether cancellation stops only future work or can interrupt a current operation. Inspect rapid edits, stale results, document switching, tab closure, shutdown, concurrent bridge activity, repeated sessions, memory growth, and worker cleanup.

Use small models, dense sketches, deep feature histories, multipart/large imported models, and assemblies. Report fixture size, machine/runtime, repetitions, warm/cold conditions, measurement overhead, and observed distributions. Treat historical benchmarks as scoped evidence. Do not turn a microbenchmark improvement into an application-wide speed claim.

## 5. Reliability, bridge, and data safety

Review `bridge.py`, `request_ledger.py`, `tools/assistant_client.py`, `recovery.py`, `snapshots.py`, preview/check/export workers, save/export paths, and the operation contract.

Inspect revision conflicts, idempotent retries, unknown outcomes, ledger eviction/capacity, session identity, request validation, queue backpressure, connection/thread bounds, malformed or partial HTTP bodies, Origin/authentication handling, token-file handling, path validation, and diagnostics. Tie security findings to an explicit local threat model and a reproducible path; avoid generic vulnerability claims.

Check atomicity and recovery assumptions around save and paired geometry/provenance publication, destination collisions, cancellation, worker crashes, disk errors, read-only destinations, and application interruption. Verify geometry validity, export ownership, preserved originals, undo integrity, and reopened editability.

Evaluate assistant ergonomics: discoverable typed operation schemas, build/contract identity, capability parity, structured actionable errors, cheap status, unsaved-state visibility, safe document closing, feature visibility, constraints, spline/helix/Hole support, and geometric selector filters. Confirm actual gaps in current source/capabilities before recommending them. Prioritize by the real projects they unblock.

## 6. Testing, packaging, and maintenance

Inspect tests, `tools/run_native_tests.py`, `run-checks.ps1`, private GUI recipes, performance tools, and `.github/workflows/`. Assess whether the tests catch realistic regressions in topology, edits, rollback, cancellation, rendering/layout, focus, DPI, and lifecycle behavior.

Separate unit/native tests, private GUI checks, historical receipts, and fresh runs. Missing external fixtures and skipped tests must stay visible. Do not count existence of CI configuration as a passing hosted run. Prioritize missing tests that protect consequential behavior, not tests that mirror implementation.

Review launch/setup, runtime pinning/integrity, upgrade and rollback paths, preference migration, support diagnostics, evidence freshness, and developer onboarding. Identify documentation that is inconsistent with code or fragments the current truth across milestone reports. Recommend a manageable maintenance process.

## Required output

Write `FABLE_REVIEW.md` and a prioritized `IMPROVEMENT_BACKLOG.md` under `docs/fable-deep-review/`, with visual proposals in a descriptive subfolder.

1. Give a candid overall assessment, the strongest existing foundations, and the five improvements with the highest user value.
2. Map the architecture and explain the principal sources of visual inconsistency, user confusion, latency, and maintenance risk.
3. Provide an evidence-backed findings table. Each finding needs an ID, category, classification (verified defect / observed design weakness / hypothesis / opportunity), severity, confidence, source file and symbol or exact image, affected scenario, consequence, proposed change, effort range, dependencies, risk, and acceptance criteria. Use current line numbers when available. Show reproduction steps or the verification needed. Do not inflate opportunities into proven bugs.
4. Cover small polish fixes, medium workflow improvements, and ambitious investments. Do not stop at five generic recommendations; do not pad to a quota. Give the visual/graphics review comparable attention to backend architecture.
5. Supply the concrete visual proposals described above, including implementation feasibility and accessibility/performance tradeoffs.
6. Sequence work into quick wins, the next coherent release, and longer-term experiments. Rank by user impact, confidence, effort, and dependency order. Keep severity distinct from implementation priority. Include success measures and regression gates.
7. Recommend the first three implementation slices with specific modules, scope boundaries, and validation. State what to preserve and which attractive proposals are not yet worth their cost.
8. Finish with tested facts, tests actually run and results, unverified assumptions, unavailable evidence, and a small set of questions only where answers would materially change the roadmap.

The goal is a practical, ambitious improvement plan for this actual native CAD application. Every major recommendation should explain what Kurt will notice, what changes in the implementation, and how we will know the result is better.
