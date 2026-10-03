# Implement the first KurtShape assembly workflow

Kurt has authorized a working first assembly increment. Design, implement and validate it in the existing app; do not stop at a plan or merely expose the native workbench. Make routine reversible decisions autonomously, explain consequential choices, and finish with a runnable result and a short hands-on walkthrough.

## Workspace and verified starting point

The saved project is `C:\Users\Kurtz\Documents\KURT\CADkz`. The app's actual Git repository is its `Codex\kurtshape` subfolder. Start by inspecting status and local instructions; preserve other work. The last verified commit is `565566b` (native STEP/STP import); its checkout was clean before this new task brief was added. Preserve/include this brief in the assembly handoff. Use the user's configured model. Work in this local checkout; no new worktree or branch was requested.

Portable FreeCAD 1.1.4, revision `4fd3bf320d9566a27e60069fc8387448aaa3a094`, with OCCT 7.8.1 is installed at `runtime\freecad-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311`. Native FCStd, native feature objects and native transactions are authoritative. Keep this foundation; do not create a parallel editable CAD graph or a custom joint solver. The installed Assembly workbench includes `Assembly::AssemblyObject`, `Assembly::JointGroup`, insert, grounded, fixed, revolute, slider and solve commands. These were found in its local source, but KurtShape has not integrated or validated them. Prove their actual API and solver behavior in this exact runtime before choosing wrappers.

Read `README.md`, `PRODUCT.md`, `DESIGN.md`, `docs/FOUNDATION_DECISION.md`, `docs/OPERATION_CONTRACT.md`, `docs/M1_PROGRESS.md`, `docs/STEP_IMPORT.md`, and the relevant Claude-review implementation notes. Inspect core, body resolution, observer/cache, native task guards, request ledger, UI, recovery and export code before changing them. Keep concise project continuity in existing docs; use descriptive folders and reproducible validation recipes.

## User outcome and scope

Provide a discoverable Assembly workflow within KurtShape's current compact native interface:

1. Create and activate a single-level assembly, with a clear way to return to Part Studio modeling.
2. Insert parts from saved FCStd projects, selecting the intended Body/solid when several exist. STEP parts can use the existing geometry import path. Support repeated instances of the same source part, each with its own placement and identity.
3. Ground/fix one instance as the assembly reference and let the user change which instance is grounded.
4. Fasten two instances with a fixed joint, or connect them with a revolute or slider joint using native references. Give useful selection guidance and visible solver feedback; exercise the permitted movement rather than only creating joint objects.
5. Select, edit, rename and remove joints/instances safely. Undo/redo must restore placements, references and solved state as one understandable command.
6. Save/reopen the assembly as FCStd with instances, joints, grounding and placements intact. Current-solid STEP export must include every assembly occurrence at its solved global placement without missing, duplicating or fusing parts.

This new request supersedes the earlier deferral of assemblies/mates for this bounded increment. Preserve existing Pierce on Shift+G and Perpendicular on Shift+L. Expose only shortcuts whose behavior is implemented and context-appropriate; ordinary Ctrl+S/Escape must work. Defer drawings, BOMs, animation/simulation, nested assemblies, advanced joint families, assembly snap mode and broad mate-connector tooling. Onshape FeatureScript interpretation and parametric source conversion are separate work and remain incomplete (0/2 real conversions). A multi-solid STEP import is not evidence of reconstructed assembly relationships.

## Architecture and failure behavior

Use the native Assembly implementation and solver behind a shared typed, argument-whitelisted controller path available to both GUI and loopback clients. Extend capabilities and inspection accurately. Retain UUID/revision checks, request-ID replay/unknown-outcome handling, exclusive busy/edit guards, staged native save and geometry/provenance exports. Reject stale or invalid requests before mutation. Failed creation, insertion or joint edits must roll back without corrupting accepted parts, placements or history; solver failures must remain visible and must never label unresolved intent as a valid current assembly.

Decide and document whether inserted sources are embedded or external links. Favor a reliable first workflow and native representations. Explain update/portability behavior, handle missing or changed external sources explicitly if links are used, and preserve every original source file. Audit `bodies.results`, ownership/reference resolution, placements, inspection/build status, save/recovery and export: the existing Body/standalone-solid traversal does not establish correct Assembly/App::Link instance handling. Native assembly objects or bundled Python view providers may need narrowly scoped support; do not weaken arbitrary script/proxy or cross-document safeguards globally. Existing arbitrary FCStd inspection/adoption policies must remain honest.

Keep idle work cheap: no per-poll full geometry validation, source re-reading or solver execution. Invalidate caches at native command/recompute boundaries. Solve on meaningful commands and show failures in the existing visible Messages UI. Preserve native Tasks and active-edit ownership. Do not restart, close or drive Kurt's open modeling window; use separate hidden processes and isolated profiles for GUI validation.

## Acceptance and handoff

Build a small reproducible native fixture with repeated part instances, a grounded part, and fixed/revolute/slider cases. Verify actual solved placements and each joint's allowed movement. Test edit/removal, undo/redo, stale tokens, identical request replay, invalid/conflicting references, solver failure rollback, save/reopen and instance-aware STEP export. Verify the chosen source-link/embedding policy after a fresh reopen and relocation. Use the two original STEP files in `CADkz\Onshape examples` for a realistic insertion/multi-solid case without overwriting them or claiming recovered mates.

Run appropriate existing regressions. Handoff baseline: 68 offline native tests, 22 shortcut tests, 4 bridge tests, and 19 STEP GUI checks pass. Recipes include `run-checks.ps1`, `tools/validate_offline.py` and `validate-review-gui.ps1 -Scenario step`. Add an isolated actual-GUI assembly workflow and inspect the rendered app, not just reports. The STEP handoff records a recovered native `GUIApplication::notify` startup access-violation warning before import; distinguish pre-existing/runtime warnings from new failures and do not claim clean startup without evidence.

Complete the implementation and required checks, update operation/user/continuity documentation, and commit the focused change in the app repository. Report what works, evidence and remaining limitations, plus concise steps for Kurt to create, insert, ground, mate, move, save and reopen his first assembly. Ask only for missing information or genuinely necessary approval; the implementation described above is authorized.
