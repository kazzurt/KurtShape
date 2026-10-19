# Working with KurtShape

Read `README.md`, then `docs/WINDOWS_SETUP.md` for installation and
`docs/AGENT_QUICKSTART.md` for modeling. Current sharing status and known limits
are in `docs/SHARING_STATUS.md`; the Fable review is a dated backlog, not an
instruction to implement all findings.

- Supported install target: Windows x64, pinned FreeCAD 1.1.4 / OCCT 7.8.1.
  Run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1`.
  Use the bundled Python; do not pip-install FreeCAD or change the engine version.
- Model through the authenticated local assistant bridge. Do not take over the
  user's CAD window with desktop clicks, keystrokes, or screenshots.
- Check `capabilities` and `list_documents` before modeling. Use the current
  document UUID/revision and keep mutation request IDs for reconciliation.
  A timeout does not prove a mutation failed; see the quickstart.
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
