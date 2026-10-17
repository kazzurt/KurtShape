# Onshape-inspired presentation execution

Completed October 4, 2026, America/Los_Angeles, against the canonical native KurtShape checkout (HEAD Q03 `559e034`, with the completed modeling workflow upgrades retained). Kurt approved execution after specifying icon-only top toolbars and small shaded labels below every hovered symbol. His preserved [Onshape screenshot](onshape-reference/onshape-user-workspace-2026-10-04.png) remains the visual reference. [PLAN.md](PLAN.md) and [EVIDENCE.json](EVIDENCE.json) describe the earlier planning snapshot.

## Delivered behavior

- Model, Sketch and Assembly context toolbars use compact icon-only buttons, narrow separators and dropdowns. Undo/Redo lead the row; tool search remains available. Original graphite CAD silhouettes retain distinct command meanings, with a grayscale native fallback for unmapped commands. QAction names, shortcuts, search and accessible labels remain intact.
- Each registered toolbar/editor symbol shows a small dark shaded label after 350 ms, normally 5 logical pixels below its button. Labels include shortcuts when available, stay on screen, dismiss on leave/click/menu/document change, and do not steal focus or alter selection. At the bottom screen boundary, the label moves above the button to remain visible.
- The document bar has compact identity, mode, save and utility controls. The light Qt palette uses neutral chrome, a white native viewport, 13 px Segoe UI body text, blue active fields and explicit readable states. History and Parts are resizable; the active part is bold.
- Sketch, Extrude and typed feature editors share a bounded movable modeless panel, with Confirm/Cancel fixed in its header. Invalid previews disable acceptance. Valid/invalid preview messages are copyable and remain visible in a footer outside the scrolling fields. Reference fields show compact selected rows with individual removal and Clear all.
- Ordinary footer notifications clear after 4.5 seconds and restore the actual task/document state. Errors persist. Messages use a quiet unread dot with a count tooltip. Existing SolidWorks navigation, native quantities, selection, preview, revision checks, transactions and FCStd authority are retained.

The native renderer continues to own geometry selection colors and shading. Future planning packages for richer rendering, element tabs, cloud collaboration or unsupported tools are not delivered by this presentation pass.

## Launch and source

From the parent `Codex` folder, open **`KurtShape-design-update.cmd`**. It launches this canonical source using `runtime/design-workspace` as its separate session/profile. The user's already-open process and existing workflow profile were not manipulated. The existing workflow launcher still points to the canonical source with its original profile.

The main presentation sources are `src/kurtshape/theme.py`, `ui.py`, `feature_panel.py`, `presentation_icons.py` and `toolbar_labels.py`. `shortcuts.py` now checks both the Qt event receiver and focused widget before routing global keys, preserving text entry during floating-editor focus transitions. Original SVGs are under `resources/icons/`; regenerate them with `tools/generate-presentation-icons.py`. [DESIGN.md](../../DESIGN.md) and `.impeccable/design.json` record the implemented system.

## Acceptance evidence

| Verification | Result | Scope |
|---|---:|---|
| Full native regression | 244/244; zero skips | Real geometry, selectors, edits, persistence, rollback and shortcuts; source frozen during the run |
| Design surface recipe | 420 checks | Real Qt actions/timers, icon-only controls, below-symbol labels, overflow, reference removal, modeless editors, visible verdicts and native preview invariants |
| UI refinement recipe | 106 checks | Quantity entry, selection preservation, confirmation/cancellation, history, settings and native notification behavior |
| Messages recipe | 34 checks | Messages, copy, close, unread count and clipboard restoration |
| Modeling workflow recipe | 45 checks | Completed parallel workflow upgrades integrated with the new editor headers |
| Part Studio recipe | 99 checks | Native multi-part and scoped editor workflows integrated with the new headers |
| Literal token contrast | 18 checks | Semantic theme text/control contrast; separate from native rendering acceptance |

Reports and 11 native captures are preserved under [validation/onshape-design](../../validation/onshape-design/). [EXECUTION-EVIDENCE.json](EXECUTION-EVIDENCE.json) contains raw session paths, engine version, hashes, capture metadata and exact source differences after the native suite. Two recovery-message strings in `ui.py` were clarified after the frozen 244-test run; the final 420/106/34 GUI runs cover those final presentation sources. Native model implementation hashes remain identical to the native-suite snapshot. Earlier workflow/Part Studio GUI reports precede the persistent footer correction; the final design recipe checks that footer directly.

The pinned engine is FreeCAD 1.1.4 (`4fd3bf320d9566a27e60069fc8387448aaa3a094`), OCCT 7.8.1. Actual Windows device pixel ratio was **1.5**. Client sizes were **1440×920** and **1024×768 logical pixels**, producing 2160×1380 and 1536×1152 image pixels. Captures use real `main.grab()` plus real floating widget grabs composited at their actual global positions; they do not fabricate geometry or UI. Test processes ran hidden with independent profiles, never through the user's window.

The fresh finish reviewer inspected all 11 initial captures and identified one material issue: preview verdicts below the form's initial scroll viewport. A bounded correction placed the copyable verdict outside the scrolling fields. The same reviewer inspected the four corrected Fillet/Extrude states and scored that finding **resolved; ship within the reviewed scope**. The follow-up was a verdict pass on that finding, not a new whole-surface review. Native history/task glyphs were considered secondary and not material to shipping. [finish-review.md](finish-review.md) records the review scope.

## Reproduction and continuity

Run from the canonical repository:

```powershell
.\run-checks.ps1 -Full -KeepNativeTemp
.\tools\run_gui_recipe.ps1 -Recipe design-surface -TimeoutSeconds 600
.\tools\run_gui_recipe.ps1 -Recipe ui-refinement -TimeoutSeconds 600
.\tools\run_gui_recipe.ps1 -Recipe messages -TimeoutSeconds 600
.\tools\run_gui_recipe.ps1 -Recipe onshape-workflows -TimeoutSeconds 600
.\tools\run_gui_recipe.ps1 -Recipe part-studio -TimeoutSeconds 600
& 'C:\Python314\python.exe' .\tools\theme-presentation-contract.py --report .\validation\onshape-design\contrast-contract.json
.\launch-kurtshape.ps1 -PrintOnly -SessionRoot .\runtime\design-workspace
```

`capture-execution-evidence.py` retains the exact accepted raw run paths and publishes byte-identical reports/captures plus their hash manifest. Run it with `C:\Python314\python.exe` from any directory to recreate this evidence package while those raw sessions remain available. Edit its input run paths deliberately for a subsequent acceptance milestone; retain this milestone's original records. The supplied screenshot is unchanged and referenced in place. No original model or media was rewritten by this presentation pass.

Development regressions resolved during execution: an early Qt filter ran before Panel fields existed; event filtering now installs after initialization. Floating quantity text could route Space to global Clear Selection; both event receiver and focus are now guarded. A test-only Extrude fixture initially added entirely inside an existing solid and was corrected to produce real added material. The finish review caught a hidden preview verdict, now fixed with a persistent footer. Failed probes remain separate under runtime and are not passing acceptance evidence.

Coverage limits: automated hidden-window mechanics do not establish physical mouse comfort, full screen-reader behavior, very long histories, or all scaling factors. No 100%, 125% or 200% acceptance is claimed. The earlier empty Impeccable HTML/CSS detector output was not used as native Qt accessibility proof. No performance improvement or new engine capability is inferred from this design pass.
