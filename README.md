# KurtShape

A local Windows CAD app built on **FreeCAD 1.1.4 / OCCT 7.8.1**, with native editable sketches and features, a shared Part Studio history, and an assistant bridge for agents. Your `.FCStd` file is the authoritative model; export STEP or STL when needed.

**Preview for friends testing on Windows x64.** Modeling is functional, but this is an actively developed app with known rough edges. See [current status and limits](docs/SHARING_STATUS.md).

## Install and launch

Prerequisites: **Git for Windows** and **7-Zip**. No separate FreeCAD, Python, CAD account or AI subscription is needed to run the app.

```powershell
git clone https://github.com/kazzurt/KurtShape.git "$env:USERPROFILE\KurtShape"
Set-Location "$env:USERPROFILE\KurtShape"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
.\KurtShape.cmd
```

Setup verifies the official runtime download and runs a disposable modeling check. It does not open or restart your CAD window. Save projects under `projects/<part-name>/` or choose another folder in the app. Projects and runtime data are excluded from Git.

[Full Windows setup and troubleshooting](docs/WINDOWS_SETUP.md) · [Agent installation prompt and bridge quickstart](docs/AGENT_QUICKSTART.md)

## Try it

- **Sketch:** Shift+S, choose a plane or planar face, then G for rectangle, C for circle or L for connected lines. Finish accepts the sketch; Cancel discards the edit.
- **Extrude:** Shift+E opens New / Add / Cut / Intersect with an exact preview.
- **Parameters:** type a value in the left Parameters section and press Enter; `=` starts a formula; Esc discards. "+" adds one; Copy reference gives the text for a feature's Formula field.
- **Edit:** double-click a sketch, Extrude, Fillet or Chamfer history row. Fillet/Chamfer let you change edges and value. Ctrl+Z / Ctrl+Y undo and redo.
- **Navigate:** middle-drag orbits, Ctrl+middle pans, Shift+middle zooms. Alt+C searches all tools; Shift+/ shows shortcuts.
- **Files:** Ctrl+S saves native FCStd. Open accepts FCStd and STEP; export produces STEP/STL. Messages retains error details for troubleshooting.

[Part Studio walkthrough](docs/U2_WALKTHROUGH.md) · [Extrude editing](docs/EXTRUSION_EDIT.md) · [Fillet/Chamfer editing](docs/FILLET_CHAMFER_EDIT.md) · [Assembly workflow](docs/assembly-workflow/WORKFLOW.md)

## Agents and developers

Start with [AGENTS.md](AGENTS.md) and the [operation contract](docs/OPERATION_CONTRACT.md). Agents use the token-authenticated loopback bridge, with native transactions and revision checks. Never publish `runtime/assistant-session.json`.

```powershell
# App must be running for this read-only connection check:
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\assistant.ps1
# Quick isolated native check; does not need a running app:
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\check-install.ps1
# Full ordinary regression run:
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run-checks.ps1
```

The regression runner skips unavailable external example files and opt-in performance tests. `run-checks.ps1 -Full` requires both. Headless checks do not prove viewport behavior on your hardware.

[Architecture](ARCHITECTURE.md) · [Fable review](docs/fable-deep-review/FABLE_REVIEW.md) · [Improvement backlog](docs/fable-deep-review/IMPROVEMENT_BACKLOG.md) · [Historical development notes](docs/DEVELOPMENT_HISTORY.md)

## License

KurtShape's original code is available under the [MIT license](LICENSE). FreeCAD and other third-party components retain their own licenses; see [third-party notices](THIRD_PARTY_NOTICES.md).
