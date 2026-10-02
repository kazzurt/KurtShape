# KurtShape desktop interface decisions

The October 2026 pass adopts the organizational conventions described by Onshape's official interface documentation: a document bar, contextual modeling toolbar, left feature history and parts list, central graphics area, and contextual feature dialogs. It preserves the native FreeCAD viewport, solver, selection and feature graph.

Kurt models at a Windows desk with dimensions and reference geometry beside a bright 3D viewport. Light neutral chrome and dark text keep repeated parameter entry readable. Use Segoe UI at the system desktop scale, 24-pixel native feature icons, 28–34-pixel controls, and modest 4/8/12-pixel spacing. The system palette uses white and pale neutral surfaces, dark gray text, blue selection/action emphasis, muted status text, green successful builds and red failures. Qt widgets implement these colors with hex values. No external font or theme dependency is needed.

The appearance follow-up owns both the QApplication palette and stylesheet, including active/inactive/disabled text and backgrounds. A stylesheet that paints white controls while inheriting a dark text palette is invalid. Explicit text/background pairs cover native Tasks, popup lists, menus, tooltips and dialogs. Theme changes apply to this app process; user/OS preferences remain intact.

The feature toolbar uses compact icons, named hover help and six labeled menus for Build, Cut, Modify, Patterns, Reference and Shape tools. The sketch toolbar adds Geometry, Constraints and Edit menus, plus Extrude and Revolve without leaving the sketch manually. Icons come from each installed command's actual pixmap metadata. All tools remain accessible through native toolbar overflow at compact widths. This placement follows [Onshape's feature-toolbar organization](https://cad.onshape.com/help/Content/PartStudio/feature_basics.htm). The central document view is maximized after creation, opening and tab switching.

Feature history stays visible during modeling and sketch editing. Dimensions and feature settings occupy a separate contextual dock. Native Sketcher task controls remain available while editing. Default planes are selectable from the history and can be shown in the viewport for one-click sketch placement. Selection changes never reset the camera.

SolidWorks navigation means middle-button drag orbits, Ctrl+middle drag pans, Shift+middle drag zooms, wheel zooms, and double-middle fits. A normal-to-sketch control changes orientation without finishing the sketch. Isometric view likewise preserves the editing session.

Validation uses an isolated FreeCAD process and configuration. Capture the actual Qt window and exercise commands, selection, sketch transactions, persistence, undo/redo and native geometry. Preserve the user's already-open modeling window.
