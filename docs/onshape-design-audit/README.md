# Onshape design audit continuity

Date: October 4, 2026, America/Los_Angeles. This folder retains the original planning audit and the subsequently approved native interface implementation. The modeling workflow chat completed its handoff before presentation integration.

Execution is complete: dense icon-only context toolbars, shaded labels below hovered symbols, compact light chrome, bounded modeless editors, compact reference fields and persistent preview verdicts. [EXECUTION.md](EXECUTION.md) records the implementation, launch path, verification and remaining coverage limits. [EXECUTION-EVIDENCE.json](EXECUTION-EVIDENCE.json) identifies the final source, captures and reports; [native interface captures](../../validation/onshape-design/) show the implemented surface. The original PLAN/EVIDENCE and schematic below remain historical planning artifacts.

Follow-up: Kurt used the correct design launcher but reported unreadable text. The saved native FreeCAD Dark appearance conflicted with the white shell/canvas. [THEME-REPAIR.md](THEME-REPAIR.md) records the subsequent selective native appearance correction, Settings recovery action and dark-startup acceptance. The original execution manifest remains historical; [THEME-REPAIR-EVIDENCE.json](THEME-REPAIR-EVIDENCE.json) identifies the repair source and new captures.

Revision: Kurt supplied his actual Onshape workspace and requested a dense row of toolbar symbols with no adjacent labels. The revised plan/schematic remove command captions and group headings from the modeling/sketch row; names and shortcuts stay in tooltips, menus, search and accessibility. The screenshot is now the primary visual reference. Its Sketch text label does not override Kurt's explicit icon-only instruction.

- [PLAN.md](PLAN.md): evidence-backed findings, close Onshape direction, tokens, surface specifications, work packages and native acceptance gates.
- [EVIDENCE.json](EVIDENCE.json): source/report hashes and reference URLs at audit capture. A changing checkout is not a frozen release baseline.
- [proposed-shell-layout.png](proposed-shell-layout.png): a labeled schematic of the proposed compact shell; not a running build or a mock geometry result.
- [render-layout.py](render-layout.py): editable deterministic diagram recipe; illustrative names/content only.
- [Onshape workspace reference](onshape-reference/onshape-user-workspace-2026-10-04.png): untransformed copy of Kurt's supplied screenshot; retained for future implementation comparison.

Confirmed decision: Kurt wants a close match to Onshape's layout, density, colors and editing feel. Retain the native FreeCAD/Qt app, authoritative FCStd, current modeless workflow work and established SolidWorks mouse controls. Current official header evidence is light. Exact chrome values/dimensions in the plan are proposals; documented selection/sketch colors are identified separately.

Observed baseline: STATUS records canonical Q03 559e034 and green Q24a 660acc5; active October 4 modeling changes are uncommitted/in progress at inspection. Current 44-check workflow and view-interaction reports were read, not rerun. Do not substitute older modal screenshots or theme checks for acceptance of current source.

During the original planning audit, no application code, model, launcher, user profile, original evidence/media, or existing design record was edited and no CAD process was launched. Execution later changed the presentation source and design record and used private hidden native validation processes. The user's existing window/profile, original models/media and older green checkout were preserved. The native detector's empty result is a coverage limitation. Browser inspection during planning was limited to public official reference images, with temporary tabs closed.

Next step: use `Codex/KurtShape-design-update.cmd` to review the updated interface in its separate profile. Verification covered actual 150% scaling at two client sizes; other scaling factors and hands-on comfort remain separate review work. No message was sent to the other user-owned chat.

Recreate the diagram from this folder:

```powershell
& 'C:\Python314\python.exe' .\render-layout.py
```

The recipe uses Pillow 12.1.1 and Windows Segoe UI. Native validation screenshots remain referenced in place under `../../validation/`. Kurt's supplied temporary attachment is also retained byte-for-byte in `onshape-reference/`; no source image was edited. The schematic is redrawn from its Python recipe.
