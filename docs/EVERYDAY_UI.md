# Everyday modeling UI (stage 2)

## Behavior changes

### Search tools (Alt+C, or the toolbar search field)

The dialog lists every tool in one place:
- the Part Studio bar and its **More** menus;
- the sketch bar and its menus;
- the assembly bar;
- the Document menu, including Undo/Redo;
- every shortcut-only action from the registry.

How results behave:
- Each tool appears once. Entries are merged by command or name, and the dialog shows where else the tool lives.
- Activating a result triggers the same `QAction` as its button, so it behaves exactly like the toolbar.
- Common CAD names find tools: *remove material, pocket, cut* → **Extrude · Cut**; *pad, boss* → Extrude; *round* → Fillet; *bevel* → Chamfer; *project, convert entities* → Use; and more.
- The shortcut column shows the user's current binding, so overrides are kept.
- An **Availability** column explains context: *Start or edit a sketch first*, *Finish the sketch first*, *Switch to Assembly*. Tools that cannot run in the current workspace explain why instead of running.

### Toolbar

- The Undo/Redo arrow buttons are gone from the Part Studio, Sketch and Assembly bars.
- Ctrl+Z / Ctrl+Y, custom bindings, **Document → Undo / Redo** and search still work.

### One Extrude tool

- The primary toolbar has a single **Extrude**. Its Operation choice is **New / Add / Cut / Intersect**.
- **Remove material** is now a searchable alias and the **More → Cut → Extrude · Cut** preset of the same tool. The separate Remove button is gone.
- In a native Body, Add and Cut create native Pad and Pocket, as before. New and Intersect, an explicit scope or an already-enabled Part Studio use Studio operations.
- Existing features are not converted. Reopening still shows their real native settings and keeps the existing limits on changing operation or end condition.

### Direction

**Measured:**
- For a sketch on a planar face, the default Extrude goes outward and the default Cut inward. This holds on top, bottom and side faces, for native and Studio features, for direct face extrusion, and for native features in a placed and rotated Body.
- A deliberate **Reverse** is respected: the solid goes into the material.

**Changed:** switching a face extrusion between Add and Cut now keeps a deliberate Reverse choice. It previously always overwrote it.

### Sketch fill

- Closed regions get a light translucent blue tint instead of an opaque light gray that could read as a hole.
- A small polygon offset with a `LEQUAL` depth test keeps the fill on a coplanar face without z-fighting, while solids still occlude it.
- The fill writes no depth and stays unpickable. Native outlines are unchanged. Only rendering changed; sketch geometry is untouched.

## Evidence

Fresh cloud runs: Linux, FreeCAD 1.1.4 / OCCT 7.8.1. **Windows not run.**

| Check | Kind | Result |
|---|---|---|
| `test_tool_search` (4) | headless, pure Python | pass: dedupe, aliases, user binding, availability |
| `test_everyday_modeling` (5) | headless native | 4 pass plus 1 expected failure (below): defaults on four faces, native, Studio, face extrusion, rotated native |
| `everyday-ui` GUI recipe | hidden GUI (Xvfb) | 23/23. Real search dialog (194 tools, no duplicates); `cut` + Enter opens Cut mode; preview inward, Add outward; Cut creates a native Pocket in one Undo step; toolbar and menu checks; rendered pixels |
| Visual inspection | screenshots of the same run | from above: translucent blue square on the face with a readable outline, face visible through it. From below: uniform bottom face, fill occluded (identical pixels at the sketch location and a bare area) |
| `extrusion-edit` / `history-lifecycle` GUI recipes | hidden GUI | 43/43, 29/29 |
| `sketch-regions` GUI recipe | hidden GUI | Not run here: segfaults during setup in this harness on the baseline too. Its "light gray" pixel checks now expect a translucent tint. Needs Windows. |

**Windows validation (October 15, FreeCAD 1.1.4 / OCCT 7.8.1):**

- **`everyday-ui`: 46/46.** Adds repeated search open, search, activate, close and reopen after native deletion. This reproduced and now fixes *Internal C++ object already deleted*. It also adds rotated-Body Studio Add/Cut preview = Confirm.
- **`sketch-regions`: 34/34.** The recipe now faces the sketch front, compares the on-face tint with the bare face, and samples the unselected boundary.
- **Other GUI recipes:** `extrusion-edit` 43/43; `part-studio` 101/101; `design-surface` 408/408; `history-lifecycle` 29/29; `rollback-history` 45/45.
- **`run-checks.ps1`:** 522 passed and 4 opt-in perf skips, with 0 failures and 0 expected failures.

## Limitations

- **Corrected on Windows (October 15):** the reported placed/rotated Body Studio Add/Remove preview failure was a test defect, not a product defect. The expected-failure test looked for a global +Z face. A rotated Studio part has no such face, because its output faces are global, so the test failed before it reached the preview. With rotated face normals, every face previews validly for Add and Cut, and Confirm produces exactly the previewed solid, in native tests and in the real GUI (`everyday-ui` recipe: Add 1204 = 1204 mm³, Cut 1196 = 1196 mm³, Reverse override honored). The test is now an ordinary passing regression. The transformed-Body Up-to-face limitation is separate and unchanged.
- Translucent blending depends on the native Coin blend mode. The exact blended color is not asserted, only the tint and occlusion.
- The search dialog lists Part Studio tools in Assembly with *Switch to Part Studio*. It does not switch workspaces automatically.

## Windows acceptance walkthrough

1. Launch `.\launch-kurtshape.ps1` on this branch. The Part Studio bar has no Undo/Redo arrows and one **Extrude**. Ctrl+Z / Ctrl+Y still work, and **Document → Undo/Redo** exist.
2. Press **Alt+C** and type `remove material`: **Extrude · Cut** is first. Try `pocket`, `round`, `spline` (it shows *Start or edit a sketch first*) and `undo` (it shows *Ctrl+Z*). If you rebind Extrude under **Help → Shortcuts**, search shows the new key.
3. Pad a block. Sketch a small rectangle on its top face; the region shows a light translucent tint and you can still see the face. Orbit underneath: the tint is hidden by the solid. Zoom in and out: no flicker.
4. Select the sketch, search `cut` and press Enter. Extrude opens in **Cut**, and the preview removes material. Switch Operation to **Add**: the preview goes outward. Confirm in Cut: a native Pocket is created, and one Ctrl+Z removes it.
5. Repeat on a bottom face and a side face, and with **Extrude** on a selected face. Tick **Reverse** and then switch Add↔Cut: the Reverse choice stays.
6. Reopen an existing Pad, Pocket and Studio feature by double-click. Their settings and limits are unchanged.
7. Run the automated checks:

```powershell
.\run-checks.ps1
.\tools\run_gui_recipe.ps1 -Recipe everyday-ui
.\tools\run_gui_recipe.ps1 -Recipe sketch-regions
.\tools\run_gui_recipe.ps1 -Recipe extrusion-edit
.\tools\run_gui_recipe.ps1 -Recipe history-lifecycle
```
