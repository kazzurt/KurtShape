# Surface selection popup and mouse navigation audit

October 2, 2026. Read-only app audit against committed KurtShape `565566b` and portable FreeCAD 1.1.4 (`4fd3bf320d9566a27e60069fc8387448aaa3a094`), Qt 6. Independent hidden GUI processes used an isolated profile and baseline source snapshot. The user's open process, original projects, and application source were not changed.

## Verified popup findings

Actual Qt mouse events selected a Pad face. A clean-profile face hover/click did not create a new popup. The native right-click menu was readable. Therefore identifying the user's exact surface-triggered popup remains an inference.

An unreadable real native popup was reproduced and captured: class `Gui::NotificationLabel`, object name `NotificationBox_label`, parentless tooltip window. A notification constructed before KurtShape's theme retained a black background while the app's `QLabel` rule painted `#243447` text. Contrast was 1.66:1. It remained visible during the surface-selection steps. [Screenshot](created-solid-popup-63.png), [face-click and palette record](surface-selection-probe.json).

Native source at the installed revision verifies that `src/Gui/NotificationBox.cpp` lines 121–123 set `ToolTipText`, `ToolTipBase`, and the separate static `NotificationBox::palette()`. Lines 206–213 paint the tooltip panel and then the QLabel. The window has no parent, so the existing `apply_theme()` pass over `main.findChildren()` misses an already-visible instance. Native source copies reside in the ignored diagnostic folder for reproducibility.

The narrow correction is an explicit `QLabel#NotificationBox_label` foreground/background rule plus consistent tooltip palette roles. It applies to existing QApplication top-level widgets as well as future Show/Polish events. Keep native dimensions/margins: additional stylesheet padding clipped a native fixed-height warning, so the diagnostic recipe omits extra padding. Light colors `#243447` on `#ffffff` provide 12.67:1 contrast. [Proposed colors screenshot](notification-readable-proposal.png), [proposal rendering record](palette-contrast-probe.json).

The ordinary real Qt tooltip, class `QTipLabel`, object name `qtooltip_label`, rendered rich text correctly with white glyphs on `#243447`. [Screenshot](ordinary-rich-tooltip.png). This tooltip was explicitly shown for a contrast probe; it was not triggered automatically by surface selection.

## Verified navigation findings

The bottom selector is native `IndicatorButton`, object name `NavigationIndicator`, under `QStatusBar`, created by `Mod/Tux/NavigationIndicatorGui.py` lines 665–676 and attached to the status bar near line 934. `NavigationIndicator.hide()` leaves the view's navigation style unchanged at `Gui::SolidWorksNavigationStyle`; see `navigation_before`/`navigation_after` in the face-click record. Its existing menu is accessible with `.menu()`, so Settings can open the same controls while the bottom button stays hidden.

The runtime user profile and current application navigation preferences specify SolidWorks. The user's native theme preference is FreeCAD Dark; the app separately establishes a light Qt theme. No selection tooltip override was found in the user's View preference group.

`navigation.apply_navigation()` currently forces SolidWorks into both the native preference and every new/opened view. Moving the native style menu into Settings by itself would not preserve a different chosen style on the next document. If Settings permits rebinding the style, persist a validated style ID and pass it through `apply_navigation()` with SolidWorks as the fallback, maintaining existing SolidWorks zoom/pivot behavior by default. Hiding the indicator alone requires no change to the navigation behavior.

## Reproduction

The macro is `runtime/ui-refresh-diagnostics/surface-selection-probe.FCMacro`. The source snapshot was extracted with `git archive 565566b src shortcuts.json`, and `core.ROOT`/`WRITE_ROOT` were reset to the real app paths. Launch the bundled `freecad.exe` hidden with an isolated user/system config and `KURTSHAPE_SESSION_DIR`, `FREECAD_USER_HOME`, TEMP/TMP, APPDATA/LOCALAPPDATA all under `runtime/ui-refresh-diagnostics/isolated-profile`. Set `KURTSHAPE_ROOT` to the app directory. Set `KURTSHAPE_PROBE_CONTRAST=1` for the targeted palette and ordinary rich-tooltip probe. The macro closes its own documents and exits automatically.

One draft of the helper passed a document name to `Selection.setPreselection`; native FreeCAD requires a DocumentObject. That helper was corrected and the final face-selection probe passed. One draft added padding to a fixed-size warning; the final proposed rule removes the padding. These failures did not modify app code or user projects.

## Production correction and validation

The correction was then implemented only in `src/kurtshape/theme.py`: explicit notification colors without padding, separate notification tooltip palette roles, an initial QApplication top-level pass, and class/name identification in the existing Show/Polish filter. Native preferences and navigation were not changed by this correction. No Git staging was performed by the audit agent.

An independent hidden native GUI loaded the production theme file into the committed baseline shell. Theme SHA256: `d9e39de76678e54d7366313f81c7e1931896fbc617c58ab87c5bfc3423559fe7`. **17 checks passed**, recorded in [production-popup-validation.json](production-popup-validation.json). Actual parentless native notifications created before and after theme application render white panels and dark ink, with no added padding. The preexisting popup retained its exact 800 × 42 logical-pixel size through both initial correction and hostile-palette Show repair. A newly constructed native popup retained its native 800 × 38 logical-pixel size. Surface selection remained functional. The ordinary real rich-text QTipLabel retained dark background and white glyphs. Native General theme preferences were identical before/after.

Screenshots: [existing native notification after production theme](production-existing-after.png), [future native notification](production-future-notification.png), [ordinary tooltip](production-ordinary-rich-tooltip.png). The exact user's surface-triggered popup remains unconfirmed; this fixes the independently verified unreadable native notification path.

For deterministic native notification construction in the disposable validation profile, set NotificationArea `DeveloperWarningSubscriptionEnabled=true`, `PreventNonIntrusiveNotificationsWhenWindowNotActive=false`, `HideNonIntrusiveNotificationsWhenWindowDeactivated=false`, and `NonIntrusiveNotificationsEnabled=true`; then call `App.Console.PrintWarning` with a unique message ending in a newline and wait 350 ms. These diagnostic settings exist only under `runtime/ui-refresh-diagnostics/production-theme-profile`. No user profile settings were changed. An earlier generic Qt warning trigger was not repeatable in inactive hidden profiles; the native console trigger with these isolated preferences resolves that test limitation.

The retained production recipe is [production-popup-validation.FCMacro](production-popup-validation.FCMacro), also run from `runtime/ui-refresh-diagnostics/production-popup-validation.FCMacro`; it uses the same launch isolation described above, explicitly imports current `src/kurtshape/theme.py` into the baseline shell, and closes only its own documents/process. All production validation helpers exited normally.
