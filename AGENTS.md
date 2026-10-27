# Working with KurtShape

Read `README.md`, then `docs/WINDOWS_SETUP.md` for installation and
`docs/AGENT_QUICKSTART.md` for modeling. Every operation's arguments, defaults and
a runnable example are in `docs/OPERATIONS.md` (generated from the schema); modeling
recipes, headless first, are in `docs/COOKBOOK.md`. The dated 2026-10-17 sharing
handoff is archived in `docs/history/SHARING_STATUS.md`; the Fable review is a dated
backlog, not an instruction to implement all findings.

- Supported install target: Windows x64, pinned FreeCAD 1.1.4 / OCCT 7.8.1.
  Run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1`.
  Use the bundled Python; do not pip-install FreeCAD or change the engine version.
- Model through the authenticated local assistant bridge. Do not take over the
  user's CAD window with desktop clicks, keystrokes, or screenshots.
- Do not open windows on the user's screen unasked. Which app to use is decided by
  [Launching: which app an agent uses](#launching-which-app-an-agent-uses) below;
  save results under `projects/` and give the user the path.
- Check `capabilities` and `list_documents` before modeling. Use the current
  document UUID/revision and keep mutation request IDs for reconciliation.
  A timeout does not prove a mutation failed; see the quickstart.
- Assemblies: organise occurrences into instance folders by function or
  sub-assembly (`Frame`, `Fasteners/M3`, `Electronics`; `folder` on
  `insert_assembly_part`, `move_assembly_instances`) and leave no more than
  about 12 instances at the root.
- Ask before restarting or closing an existing app. It may have unsaved work.
  Code updates require a new app process; a running process keeps its old code.
  `python -B tools/assistant_client.py --build-check` tells whether the running app
  loaded this checkout's current code (`current`) or predates your edits (`stale`).
- Preserve original CAD files. New installs allow assistant writes under
  `<checkout>/projects`; other destinations are granted by the user via Save.
  Never overwrite an FCStd open in another process.
- Use isolated headless sessions for probes. `tools/check-install.ps1` supplies
  a safe example. Do not reuse the live profile for tests.
- Keep changes scoped, preserve other agents' work, and commit only when asked.
  Record consequential changes and evidence in the relevant existing document.
- Add native behavior tests for consequential modeling changes, register classes
  in `tools/run_native_tests.py`, update `docs/OPERATION_CONTRACT.md`, and run
  `run-checks.ps1`. Do not weaken assertions merely to make a run green.
- Do not commit `runtime`, session tokens, private models, profiles, or logs.
  Describe any unverified GUI behavior honestly.

## Launching: which app an agent uses

This is the one launch rule; other documents link here instead of restating it.

1. **Headless Controller: the default for scripted builds**, dry runs and probes.
   Run `kurtshape.core.Controller().dispatch(request)` in-process under the bundled
   `pythonw.exe` (output redirected to a file) in an isolated session: no window and
   no GUI process. The [cookbook](docs/COOKBOOK.md#headless-quickstart) shows the setup.
2. **Hidden app: when the bridge itself is needed** (request ids and reconciliation,
   `request_status`, the app's batch budget and document flags, GUI-only behaviour).
   `tools/assistant.ps1 -Hidden -HiddenSession <name>` starts or reuses a private,
   offscreen KurtShape with its own profile and port and prints its session file;
   `-ProjectRoot <folder>` lets it save there. It loads this checkout's code when it
   starts. Stop it with `tools/assistant.ps1 -Hidden -Stop -HiddenSession <name>`.
3. **The user's running app: only when the user asks to watch, or the document to
   change is open there.** An agent never launches it (`KurtShape.cmd`,
   `KurtShape.exe`, `launch-kurtshape.ps1` or a shortcut); if it is not running, ask
   the user. Confirm the code it loaded with `--build-check` (above) and ask before
   restarting it.
