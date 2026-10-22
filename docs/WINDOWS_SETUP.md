# Windows setup

This is a preview for friends testing KurtShape. Use Windows x64 and a writable,
short local path outside Program Files and cloud-synced folders. Windows ARM,
macOS and Linux are not validated installation targets. The runtime is several
GB after extraction; allow 10 GB free for download, engine and test scratch.

## Install

1. Install **Git for Windows** and **7-Zip** if absent. With Windows Package Manager:

   ```powershell
   winget install --id Git.Git --exact
   winget install --id 7zip.7zip --exact
   ```

   Then open a new terminal. If winget is unavailable, use the official
   [Git](https://git-scm.com/downloads/win) and [7-Zip](https://www.7-zip.org/) installers.
   The CAD runtime itself needs no administrator privileges or separate Python.

2. Clone into a folder you own (the following example is under your user profile):

   ```powershell
   git clone https://github.com/kazzurt/KurtShape.git "$env:USERPROFILE\KurtShape"
   Set-Location "$env:USERPROFILE\KurtShape"
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
   ```

   Setup downloads the pinned official FreeCAD archive, verifies SHA256, extracts
   it locally, and runs a private headless modeling check. Re-running reuses an
   installed runtime and runs the check again. The command-specific policy flag
   does not change your machine's execution policy. If organizational policy
   blocks scripts, use your administrator's approved process.

3. After **Setup passed**, double-click `KurtShape.cmd`. An empty Part Studio
   should open. Make a rectangle, finish the sketch, Extrude, then try Undo/Redo
   and Save. This checks the interactive display and input on your hardware;
   the automated setup check does not establish those.

4. Connect an agent using [AGENT_QUICKSTART.md](AGENT_QUICKSTART.md).

## Files and privacy

- `runtime/`: downloaded engine, application profile, recovery and local logs.
- `projects/<part-name>/`: recommended location for native FCStd and exports;
  created by setup and excluded from Git. Back up your projects separately.
- `runtime/installation-check/<id>/`: disposable modeling files and an
  `evidence/installation.json` report identifying source hashes, checkout commit
  (when Git is available), and actual engine version. This reports the checked
  source, not the build already loaded by a separate running app.
- `runtime/assistant-session.json`: live loopback address and authentication token.
  Never share this file. Only give trusted agents access to your checkout/profile.

New profiles default to this checkout's `projects` folder. Existing profiles
retain their previous save locations. Using the app's Save dialog grants the
chosen destination folder to the assistant. There is no cloud account or model
subscription required to run KurtShape; any agent subscription is separate.

## Updating

Save and close KurtShape yourself first, then:

```powershell
git status --short
git pull --ff-only
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
.\KurtShape.cmd
```

If Git reports local changes or divergence, preserve them and ask your agent to
resolve the update. Do not reset or clean the checkout to force an update.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| 7-Zip not found | Install it, or set `$env:KURTSHAPE_7Z` to the full path to `7z.exe`, then rerun setup. |
| Download interrupted | Rerun setup. A `.partial` download is not accepted as a verified archive. |
| Cached archive hash mismatch | Delete only the archive named in the error, then rerun setup; never bypass the checksum. |
| Engine files missing or damaged | Close processes using this runtime, then run `setup.ps1 -RepairRuntime`. |
| Setup check fails | Read the printed report and process logs. The failure does not affect an already-open app or your CAD files. |
| Bridge connection refused | Launch this checkout and retry `tools/assistant.ps1`. A stale session file is not proof the app is running. |
| Bridge authentication fails / wrong document list | Confirm you selected the correct checkout/session; do not print the token or connect to a different instance by guessing. |
| Black or broken viewport | Close the app after saving and update the graphics driver; FreeCAD needs OpenGL 2.0 or later and logs `OpenGL version is` at startup. `QT_OPENGL=software` has no effect: FreeCAD 1.1.4 forces desktop OpenGL before Qt reads it. |
| Old behavior after updating | Save, close and relaunch. A running app cannot hot-reload the new checkout. |

For an existing engine at another location, use `setup.ps1 -RuntimeRoot <folder>`
where `<folder>` contains `freecad-1.1.4`. Pass that same `-RuntimeRoot` to
`launch-kurtshape.ps1` and `tools/assistant.ps1`; the double-click launcher uses
the default local runtime. `launch-kurtshape.ps1 -PrintOnly` prints resolved paths
without launching anything.

Report problems with the Git commit (`git rev-parse HEAD`), Windows version,
steps, expected/actual behavior and relevant Messages text. Review reports for
private paths before sharing; never include session tokens or private CAD files.
