---
name: "KurtShape"
description: "A bright, compact native Windows CAD workspace."
colors:
  workspace: "#f5f6f7"
  surface: "#ffffff"
  viewport: "#ffffff"
  chrome: "#f5f6f7"
  alternate: "#fafafa"
  ink: "#2d3338"
  muted: "#59636c"
  placeholder: "#65717c"
  disabled_ink: "#646f78"
  disabled: "#f1f3f5"
  divider: "#d6dadf"
  border: "#8a949e"
  hover: "#edf2f6"
  selection: "#e6f1fa"
  active_field_fill: "#e6f1fa"
  selection_ink: "#204f79"
  accent: "#185fa5"
  accent_pressed: "#124b83"
  error: "#bd3039"
  warning: "#8c6005"
  success: "#247a43"
  tooltip: "#353a40"
  tooltip_border: "#242a30"
  icon_ink: "#51575d"
  icon_light: "#dedfe1"
  icon_mid: "#b8bdc2"
  icon_dark: "#899198"
typography:
  body:
    fontFamily: "Segoe UI"
    fontSize: "13px"
  label:
    fontFamily: "Segoe UI"
    fontSize: "13px"
    fontWeight: 600
  title:
    fontFamily: "Segoe UI"
    fontSize: "14px"
    fontWeight: 600
  brand:
    fontFamily: "Segoe UI"
    fontSize: "16px"
    fontWeight: 600
  active_part:
    fontFamily: "Segoe UI"
    fontSize: "13px"
    fontWeight: 700
rounded:
  control: "2px"
spacing:
  zero: "0px"
  micro: "2px"
  compact: "4px"
  field: "6px"
  panel: "8px"
  canvas: "12px"
components:
  toolbar-command:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "4px"
  toolbar-command-hover:
    backgroundColor: "{colors.hover}"
    textColor: "{colors.ink}"
  toolbar-command-active:
    backgroundColor: "{colors.selection}"
    textColor: "{colors.selection_ink}"
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.surface}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "4px 8px"
  button-primary-hover:
    backgroundColor: "{colors.accent_pressed}"
    textColor: "{colors.surface}"
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "4px 8px"
  quantity-input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "4px 6px"
  document-navigation:
    backgroundColor: "{colors.chrome}"
    textColor: "{colors.ink}"
    typography: "{typography.title}"
    padding: "0px 4px"
  feature-editor:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    padding: "8px"
  reference-picker-active:
    backgroundColor: "{colors.active_field_fill}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "0px"
  history-active-part:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.active_part}"
    padding: "3px 2px"
  toolbar-label:
    backgroundColor: "{colors.tooltip}"
    textColor: "{colors.surface}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "5px 8px"
---

# Design System: KurtShape

## Overview

**Creative North Star: "The Modeling Desk"**

KurtShape follows the user's light desktop Onshape reference: a compact document bar, dense command symbols, left history and parts, and a large white modeling canvas. Shaded grayscale CAD glyphs, pale neutral chrome and readable system type make geometry and parameter entry the focus.

The system is implemented in native Qt around the FreeCAD viewport. KurtShape aligns its active local FreeCAD appearance profile with FreeCAD Light and owns the application palette and stylesheet together, including native Tasks, menus, popups and floating quantity editors. It preserves local document identity, explicit Save, existing modeling transactions, user part appearances, geometry selection and the established SolidWorks mouse gestures.

**Key Characteristics:**

- Dense icon-only command rows with names available on hover, focus, menus and search.
- Light neutral surfaces with blue selection and active reference fields.
- Compact modeless feature editors with fixed acceptance controls and visible preview verdicts.
- Resizable history and parts beside the native white canvas.

This records the approved October 2026 system change and native appearance repair. Reusable values come from [the theme](src/kurtshape/theme.py), [appearance preferences](src/kurtshape/workspace_preferences.py), [the icon generator](tools/generate-presentation-icons.py) and the native shell/editor sources. The frontmatter owns primitives; [.impeccable/design.json](.impeccable/design.json) adds metadata and self-contained visual specimens of native Qt components.

## Colors

The palette is cool and restrained: white work surfaces, pale gray chrome, dark text and a single blue interaction accent. The frontmatter retains the source's semantic names and exact hex values.

### Primary

- **Action Blue** (`accent`) and **Pressed Action Blue** (`accent_pressed`) identify primary actions and focused boundaries.
- **Selected Row Blue** (`selection`) and **Selection Ink** (`selection_ink`) distinguish selected controls and rows.
- **Receiving Field Blue** (`active_field_fill`) identifies the geometry field receiving the next pick; it is separate from text-entry focus.

### Neutral

- **Control White** (`surface`) and **Canvas White** (`viewport`) keep form controls and the actual native viewer bright.
- **Workspace Gray** (`workspace`), **Toolbar Gray** (`chrome`) and **Row Off-white** (`alternate`) separate chrome and collections without large tonal blocks.
- **Modeling Ink**, **Quiet Ink**, **Prompt Ink** and **Disabled Ink** (`ink`, `muted`, `placeholder`, `disabled_ink`) provide readable semantic text pairs.
- **Control Outline**, **Soft Divider**, **Hover Gray** and **Disabled Gray** (`border`, `divider`, `hover`, `disabled`) express boundaries and control states.
- **Command Charcoal** and **Command Outline** (`tooltip`, `tooltip_border`) support the small white-text command label.
- **Glyph Outline**, **Light Glyph Face**, **Middle Glyph Face** and **Dark Glyph Face** (`icon_ink`, `icon_light`, `icon_mid`, `icon_dark`) are the shared shading vocabulary of the original SVG assets.

Failure Red, Caution Ochre and Valid Preview Green (`error`, `warning`, `success`) communicate actual severity alongside readable text. Native sketch, annotation, editor, measurement and grid colors use the bundled Light configuration's established roles; selection and model appearances retain their existing native owners.

Sketch-specific overrides use black dimension annotations, blue free geometry/points, black fixed geometry/points and red geometry errors. Closed defining regions receive a light gray (`#ebebeb`) unpickable display fill; holes remain empty. Native selection/preselection highlights stay distinct. The dimension cursor combines a crosshair hotspot with extension lines and a double-headed arrow.

**The Model Color Rule.** Theme the workspace and viewer background without overwriting part appearances, geometry selection or native solver states.

## Typography

Use Segoe UI throughout the native interface. There is no external font dependency, display-type scale or authored line-height/tracking system.

- **Body** (13px): fields, menus, tool labels, history and status text.
- **Label** (13px, weight 600): section titles and primary text-button emphasis.
- **Title** (14px, weight 600): document identity and feature-editor titles.
- **Brand** (16px, weight 600): the compact KurtShape name.
- **Active part** (13px, bold): the target part for new sketches/features, independent of selection.

Preserve native Windows scaling. Elide long document and reference names with full-name tooltips rather than increasing the type size or widening the command row.

**The Icon Row Rule.** Persistent top command buttons show symbols only. Preserve descriptive action names for menus, accessibility, search and delayed labels.

## Layout

The persistent shell has a compact document row, one contextual command row, left history/parts, the central native MDI viewer, local-document tabs and a quiet footer. The document row carries the brand, icon-only document menu, elastic identity, workspace-mode choice, Save, Help and Settings. Undo/Redo begin the contextual row; a search field (175px) opens the command search.

The history dock uses a bounded width (235–430px). A vertical, noncollapsing splitter gives feature history and parts independently scrollable space, with an initial 3:1 stretch. Part choice and bold active-part text identify the modeling target without changing the viewport selection or camera.

Feature editors float modelessly beside the canvas by default, request a compact width (320px) within their width bounds (280–440px), and can move or dock left/right. Placement and height are bounded to the screen's available area and the canvas. Long form rows wrap; only the form content scrolls. The title/acceptance header and preview verdict remain outside that scroll region.

Use the observed compact spacing scale. Standard editor content uses panel padding (8px) and field gaps (6px); generic tool forms can use canvas spacing (12px). At narrow widths, keep command buttons icon-only and retain supported actions through native overflow, named menus and search. Desktop adaptation follows available native screen space rather than web breakpoints.

## Elevation & Depth

The application owns no decorative shadow scale. White controls, pale chrome, thin dividers and outlined focus states supply most separation. Native floating editors, menus and tooltip windows provide platform depth; the delayed command label is a small shaded surface, not a large help card.

**The Flat Chrome Rule.** Use tonal surfaces, thin boundaries and native floating-window separation. Do not introduce decorative card shadows into the modeling workspace.

## Shapes

Controls, inputs and command labels have modest square-adjacent corners (2px). Boundaries and dividers are thin (1px). Keep layouts compact and rectilinear.

The command vocabulary uses 74 original grayscale shaded SVGs with CAD-specific silhouettes. Toolbar icon requests are compact (20px); the artwork's native view box is 24px. Unmapped installed commands retain their native geometry, alpha and shading through grayscale fallback; a neutral tools symbol covers an unavailable icon. Do not erase action names to make a symbol-only row.

## Components

### Command buttons and menus

Top command buttons are icon-only in every workspace context, including menu/toolset triggers and overflow. The native toolbar stylesheet establishes minimum inner dimensions (22px) and compact padding (4px); these are minimums, not a fixed rendered footprint. Thin separators and small native chevrons organize tools.

Hover uses the neutral hover fill; checked/pressed states use the blue selection pair; keyboard focus uses an accent boundary. Transient menus retain readable command/category text and original action names. Ordinary dialog/form text buttons keep the primary and secondary button treatments recorded in the frontmatter.

### Delayed command labels

After hover or keyboard focus (350ms), show the command name and available shortcut in a small dark box with white text. Center it below its symbol with a short gap (5px), and clamp it to the monitor's available area. It takes no focus or pointer events and dismisses on interaction, leaving the control, document changes or popup/modal activation. Only screen-edge placement requires an above-symbol fallback.

### Inputs and quantities

Use white fill, a neutral outline, compact corners and an accent focus boundary. Keep native dropdown arrows, popup-list contrast, disabled pairs and selection colors readable. Preserve QuantityField units, expressions, pending input and commit behavior. Keyboard focus in a quantity and an armed geometry receiver are independent states.

### Feature editor

The header carries a compact title plus icon-only Confirm/Cancel controls (28px targets, 16px icon requests). For operations that stage a preview, header and keyboard acceptance follow the current valid result. Sketch Finish retains its native editing rules. Cancellation retains the established native transaction behavior.

The persistent verdict below the scroll host is word-wrapped and copyable. Pending, valid and error feedback describe the current preview, with semantic success/error text and no stale ready state. Both the generic studio editor and extrusion editor use this shared pattern. Native Tasks stay available for operations outside the owned editor framework.

### Reference picker

An armed geometry field uses a blue fill and accent outline. Empty fields reserve no blank collection box. A single reference occupies one compact row; multi-reference fields grow to three rows, then scroll. Rows use a minimum height (28px), elided names with full tooltips, per-row removal, selected-reference removal and a Clear all menu action.

Keep explicit empty, active, filled and disabled states. The theme also supplies an invalid-outline treatment; applying it requires a real validation state, not a guess based on collection size. Removing references preserves their native selection ownership.

### Native appearance and Settings

The active local FreeCAD user-parameter profile uses `FreeCAD Light`. Readability also depends on native drawing and rich-text colors beyond the Qt palette. Copy the selected sketch/annotation, editor, measurement and grid colors from the bundled `FreeCAD Light.cfg`, while preserving selection/navigation preferences and model ViewObjects. Native report text, logging, warning and error colors use the existing theme tokens; existing rich report fragments are recolored when their foreground matches a previous native report color. Refresh the native report highlighter after changing its parameters so retained warning/error ranges use the new colors and preserve their native severity metadata.

A coalesced style/palette guard restores the owned application CSS and palette after delayed native preference observers replace them. Settings explicitly identifies the appearance as **Light (Onshape)** and provides **Restore light appearance** to reapply the native/Qt appearance and white backgrounds to active views of open documents. Mouse navigation keeps its separate Save workflow.

### History, tabs and messages

History and parts use white collections, compact rows, pale hover/selected fills and readable failed/held indicators and subdued hidden-row text. Bold text identifies the active part; selection remains a separate state. Local document tabs use an accent active indicator and native local-file identity.

Ordinary completion text yields back to the actual edit/document state after a short interval (4500ms). Errors remain until subsequent feedback replaces them. The Messages area stays collapsed by default, uses a quiet unread dot and retains copyable diagnostics; reading it clears the dot.

## Do's and Don'ts

### Do:

- **Do** keep the document identity elastic and show its full name on hover.
- **Do** provide original command icons, grayscale native fallback, accessible names and real menu/search routes.
- **Do** show a small white-text label below the symbol after the established hover or keyboard-focus delay.
- **Do** keep the receiving reference field blue while preserving independent quantity-entry focus.
- **Do** keep Confirm, Cancel and the current preview verdict outside the scrolling form.
- **Do** use the adjustable history/parts split and bold active-part text without changing selection or camera.
- **Do** keep local Unsaved/Modified wording, explicit Save and copyable errors tied to the current edit.

- **Do** keep native appearance preferences and report text compatible with the owned light palette.

### Don't:

- **Don't** add inline command captions or category headings to persistent top toolbars.
- **Don't** replace the native viewport, solver, quantity parsing or existing SolidWorks navigation to achieve the appearance.
- **Don't** recolor user parts or alter authoritative geometry for hover, selection or preview styling.
- **Don't** show cloud-save claims or make local document tabs imply cloud element semantics.
- **Don't** let stale completion text appear to be the current preview verdict.
- **Don't** let long form labels or reference names force controls beyond the available screen.
- **Don't** invent unsupported commands, progress percentages or acceptance states.
- **Don't** apply the entire native preference pack to repair appearance; preserve selection, navigation and model colors.
