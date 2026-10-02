# KurtShape product context

KurtShape is Kurt's local, editable Windows CAD workspace. The primary user is moving familiar Onshape modeling workflows into an offline application backed by native FreeCAD documents. The same native model must support direct graphical editing and revision-checked assistant operations.

The current task is an Onshape-style organization and functionality pass: document controls and modeling tools across the top, design history and parts on the left, a large central 3D viewport, and contextual editing controls. SolidWorks mouse navigation is an explicit preference. Shift+S begins sketch placement; one face or plane selection starts the sketch. Sketches remain inspectable in 3D while editing.

The interface should feel familiar, precise and functional. Dense modeling controls are appropriate. Use compact native tool icons with named hover help and visible group-menu labels, restrained blue selection accents, readable system typography, and clear errors. Avoid decorative cards, large empty dashboard layouts, or marketing language in modeling flows. Keyboard navigation and readable contrast are engineering defaults; no special accessibility requirements have been supplied.

Editable FCStd is authoritative. Original Onshape exports remain unchanged. Full conversion of the two supplied designs is a separate incomplete milestone. Shortcut registration must not imply that unsupported assembly or drawing functionality has been implemented.

All task files and dependencies remain under CADkz/Codex. Existing project continuity is maintained in docs/M1_PROGRESS.md and the interface validation records.
