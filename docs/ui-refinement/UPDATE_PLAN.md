# Modeling workflow refinement — October 2, 2026

Kurt reported missing extrusion preview, an unreadable popup when selecting a surface, unfamiliar tool names and visibility, an unexplained New Body control, and an unnecessary bottom mouse-navigation selector. He wants familiar Onshape modeling tools, including patterns, planes, sweep and loft. Hole wizard and sheet metal are deferred. Implementation of these fixes is authorized by his instructions; he separately authorized coordination with the ongoing assembly conversation.

## Current pass

- Evaluate Pad/Pocket intent in a disposable native document and render a transient preview in the live viewport. Update depth, reverse and end type; remove the preview on cancel, acceptance, document switch or shutdown. Failed preview must preserve live geometry, identity, history and selection. Accept still uses the shared controller.
- Reproduce surface selection in an isolated GUI and correct the actual unreadable popup's foreground/background, including dynamically created widgets. The initial audit found a dark native notification label with dark app text; a clean-profile face click itself did not open another popup. Keep this distinction until verified with the user's profile/preferences.
- Make Sweep, Loft, Linear pattern, Circular pattern, Mirror and Plane directly discoverable from the top toolbar. Remove Hole from the default buttons. Preserve compact toolbar overflow and access to the remaining tools in named dropdowns; command registration alone does not establish a working feature workflow.
- Remove “native” from everyday labels/help. Use modeling terms: Extrude, Extrude remove, Linear pattern, Circular pattern and Plane; use Show planes for visibility. Rename New Body to New part with guidance that it starts a separate solid and feature history within the project, rather than inserting an assembly instance.
- Hide the bottom NavigationIndicator while retaining the existing SolidWorks controls. Expose mouse-navigation choices from Settings rather than the modeling status bar.

The assembly conversation completed its focused integration as commit `10c333f` and released the shared files through `docs/assembly-workflow/COORDINATION.md`. Refinement changes preserve Assembly mode, tools, selection, dialogs and controller behavior. No user modeling window is controlled or restarted.

## Major upgrades after this pass and assemblies

1. Expand the verified core tool workflows: previews while editing features, curved sweep paths, richer loft sections, and part/face pattern scopes. Six native fixtures now establish accepted/editable feature patterns, offset/angled planes, straight-path sweep and loft, including upstream edits and persistence. This evidence does not establish every operation or scope available in Onshape.
2. Shared variables and configurations: named dimensions driving multiple features, then explicit size variants. Existing dimensional expressions are a foundation.
3. Imported-part editing: Split, Transform and direct face changes would make STEP imports much more useful. These are missing app workflows, not claims about absent kernel capability.
4. Feature editing and reference repair: clear downstream failure reporting, repair attachment references, expanded previews, and better history/selection navigation.
5. Broaden the shared assistant operation contract to sweep, loft, planes and patterns, then source-backed Onshape conversion. Frozen source capture and FeatureScript interpretation remain separate incomplete work; real parametric conversions remain 0/2.

Default Onshape tools use dropdown sets; exposing a familiar top toolbar does not require every advanced tool to occupy a separate button. A command with similar naming is not necessarily equivalent: Onshape can pattern parts/features/faces and offers solid/surface/thin and New/Add/Remove/Intersect modes beyond the validated KurtShape slice.

Primary references: [Feature toolbar](https://cad.onshape.com/help/Content/PartStudio/feature_basics.htm), [Extrude](https://cad.onshape.com/help/Content/PartStudio/extrude.htm), [Sweep](https://cad.onshape.com/help/Content/PartStudio/sweep.htm), [Loft](https://cad.onshape.com/help/Content/PartStudio/loft.htm), [Linear pattern](https://cad.onshape.com/help/Content/PartStudio/linear_pattern.htm), [Plane](https://cad.onshape.com/help/Content/PartStudio/plane.htm), [Transform](https://cad.onshape.com/help/Content/PartStudio/transform.htm), [Variable](https://cad.onshape.com/help/Content/PartStudio/variable.htm).

## Acceptance

Run focused native modeling fixtures for count/spacing/upstream edits, history and save/reopen. Validate live preview success/failure and cleanup against unchanged live intent/UUID/history/modified/camera/selection. Exercise actual face hover/click popups, settings/navigation behavior, default toolbar discovery and compact-width overflow in an isolated native GUI. Inspect actual screenshots in bounded passes. Record relevant regressions, source-preserving reproduction recipes, native runtime warnings and practical limits before a focused refinement commit.
