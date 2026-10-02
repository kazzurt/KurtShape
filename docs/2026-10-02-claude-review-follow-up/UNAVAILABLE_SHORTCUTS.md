# What KurtShape currently marks unavailable

Checked October 2, 2026 against [shortcuts.json](../../shortcuts.json). **35 registered Onshape actions are explicitly marked unsupported.** They are grouped below by workflow; the Context column retains the registry's actual routing context.

Eight entries concern modeling/sketch work: two analysis actions, two rollback-bar actions and four sketch actions. The remaining 27 concern assemblies/mates, Feature Studio code editing and drawings. FeatureScript search belongs to Feature Studio, not the ordinary Part Studio workflow.

This is a shortcut-action inventory, not a claim that FreeCAD's kernel cannot perform a related operation. Native equivalents elsewhere may have different workflows. The live help also checks installed commands and current context. Press **Shift+/** for shortcut help, or **Alt+C** for tool search. The missing rebind UI is part of the proposed update plan.

## Modeling analysis and history — 4

| Key | Unavailable action | Context |
|---|---|---|
| Shift+C | Curve and surface analysis | general |
| Shift+D | Dihedral analysis | general |
| Up | Move selected rollback bar up | rollback |
| Down | Move selected rollback bar down | rollback |

Rollback means an Onshape-style history bar for temporarily evaluating an earlier point. Ordinary KurtShape undo/redo is already available.

## Sketching — 4

| Key | Unavailable action | Context |
|---|---|---|
| Shift+U | Curvature constraint | sketch |
| Shift+A | Switch line and tangent arc | sketch |
| Shift+K | Normal constraint | sketch |
| Shift+G | Pierce constraint | sketch |

These do not mean that all sketch constraints or arcs are unavailable. The registry and menus already route many native Sketcher tools; these four Onshape actions have no implemented registered equivalent.

## Assemblies and mates — 8

| Key | Unavailable action | Context |
|---|---|---|
| A | Flip mate primary axis | mate_edit |
| K | Show or hide mate connectors | general |
| Ctrl+M | Create mate connector | general |
| J | Show or hide mates | assembly |
| I | Insert parts and assemblies | assembly |
| M | Fasten mate | assembly |
| H | Show mates mode | assembly |
| Shift+S | Assembly snap mode | assembly |

## Feature Studio code editing — 7

| Key | Unavailable action | Context |
|---|---|---|
| Ctrl+Shift+F | Find FeatureScript | feature_studio |
| Ctrl+] | Previous cursor position | feature_studio |
| Ctrl+S | Commit Feature Studio | feature_studio |
| Ctrl+Shift+S | Commit all Feature Studios | feature_studio |
| Escape | Dismiss autocomplete | feature_studio |
| Ctrl+[ | Next cursor position | feature_studio |
| Ctrl+Shift+O | Top-level symbol outline | feature_studio |

## Drawings — 12

| Key | Unavailable action | Context |
|---|---|---|
| Shift+D | Diameter dimension | drawing |
| Ctrl+S | Show or hide drawing sheets | drawing |
| Home | First drawing sheet | drawing |
| End | Last drawing sheet | drawing |
| Ctrl+M | Minimum / maximum dimension | drawing |
| PageDown | Next drawing sheet | drawing |
| N | Drawing note | drawing |
| PageUp | Previous drawing sheet | drawing |
| P | Projected drawing view | drawing |
| Shift+Q | Drawing midpoint / quadrant points | drawing |
| Shift+R | Drawing radial dimension | drawing |
| Ctrl+Q | Update drawing views and properties | drawing |

## Keys remain contextual

An unavailable action does not disable that key everywhere. **Ctrl+S saves a local project**, **Shift+S starts a sketch outside sketch mode and Point inside it**, **N changes to a normal view**, and **D invokes the native sketch dimension tool**. Text inputs and dialogs also retain their own keys. For example, the unavailable drawing diameter shortcut does not imply sketch diameter dimensions are missing.

Six mouse/held-modifier entries are separately recorded as passive gestures with partial equivalence; they are not included in these 35 unsupported entries. Preview, multiple-body management and unmanaged FCStd adoption are separate contract/workflow gaps described in the update plan, rather than entries in this shortcut count.

No favorite/missing-tool priorities have been inferred for Kurt. This inventory answers his request for the list before selecting priorities.
