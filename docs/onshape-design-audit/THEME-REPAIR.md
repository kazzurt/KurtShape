# Saved dark-theme compatibility repair

October 4, 2026, America/Los_Angeles. Kurt confirmed launching `Codex/KurtShape-design-update.cmd` and reported that the interface differed from the supplied preview and contained unreadable text. Read-only inspection found `FreeCAD Dark` saved under `BaseApp/Preferences/MainWindow` in both local profiles. KurtShape's Settings previously offered only navigation. The user's running windows, profile files and model files were not directly edited or closed during investigation.

The initial presentation owned the light Qt palette and CSS, but native sketch/annotation colors and report highlighter formats come from independent preferences. The saved Dark pack supplied pale drawing/report colors suitable for dark backgrounds. FreeCAD can also replace application CSS after a delayed native preference update. Diagnostic theme inspection incorrectly read `General` rather than `MainWindow`.

`theme.py` now aligns the active local FreeCAD profile with `FreeCAD Light` on startup. It reads only selected sketch/annotation, editor, measurement and grid colors from the installed Light pack; it owns native report colors using the existing ink/muted/warning/error tokens. It preserves navigation, selection/highlight preferences, default model material settings and model ViewObjects. These appearance preferences are saved to the active local profile; this intentionally supersedes the earlier process-only appearance policy. No Windows theme setting is changed.

Existing rich report fragments matching their old preference colors are recolored. The native `QSyntaxHighlighter` is then refreshed through its verified `rehighlight()` method. Updating native report parameters alone left old layout ranges cached; fragment formatting also failed to replace those rendered ranges. Native rehighlighting retains the C++ warning/error severity metadata without guessing from text or cross-theme color aliases.

The coalesced Qt style/palette guard restores application CSS and relevant active/inactive/disabled palette roles after later native replacement. Shutdown and retired-filter callbacks are guarded. **Settings → Appearance** now shows **Light (Onshape)** and provides **Restore light appearance**, which reapplies the native/Qt appearance and white background to native 3D views. Other document view types are skipped safely; failures use the existing error notification.

To load the correction, save and close the affected KurtShape window, then reopen the same design-update launcher. The old process retains its already-imported Python code until restart. The launcher continues using `runtime/design-workspace`; no new launcher or profile reset is required.

Acceptance uses a fresh hidden native process seeded with the complete bundled FreeCAD Dark pack before GUI initialization, with no user document or recovery paths. The final startup recipe passes **30 checks**: saved Dark reproduction, native Light correction, preserved model defaults/selection preferences, sketch-text preference contrast, five-second deferred startup, hostile stylesheet/input-palette recovery, actual Settings recovery click, unchanged sketch/solid BReps and retained report highlighter ranges. All checked retained report ranges—including real startup warning/error lines—have at least **5.54:1** foreground contrast against white. Native finish review first identified those old warnings as a narrow P2, then scored the corrected report **resolved; ship within this bounded repair scope**.

The design surface recipe passes **420 checks** after the final repair; Messages passes **34 checks** after native rehighlighting. UI refinement passes **106 checks** before the final report-only refresh addition. The earlier 244 native regression report remains the model-engine baseline; model-engine source was not changed by this repair. Raw reports, current source hashes and byte-identical selected captures are identified in [THEME-REPAIR-EVIDENCE.json](THEME-REPAIR-EVIDENCE.json) and preserved under [validation/onshape-theme-repair](../../validation/onshape-theme-repair/).

Reproduce from the canonical repository:

```powershell
.\tools\run_gui_recipe.ps1 -Recipe theme-startup -TimeoutSeconds 600
.\tools\run_gui_recipe.ps1 -Recipe messages -TimeoutSeconds 600
.\tools\run_gui_recipe.ps1 -Recipe design-surface -TimeoutSeconds 600
```

Evidence limits: actual scaling was 150%. The native sketch capture shows readable Tasks/chrome, but no visible sketch dimensions in its center; sketch stroke/text recovery is preference contrast evidence, not rendered-dimension acceptance. Report contrast checks inspect actual native highlighter layout formats, which override rich fragment formats. Tests do not establish hands-on acceptance of Kurt's actual window or other DPI settings. Native startup thumbnail warnings in the isolated capture are test-process diagnostics, not evidence of corruption in the user's model.
