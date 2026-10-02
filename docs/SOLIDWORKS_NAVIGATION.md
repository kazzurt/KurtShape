# SolidWorks navigation in KurtShape

Verified on 2026-10-02 against the bundled FreeCAD 1.1.4 Windows runtime, revision `4fd3bf320d9566a27e60069fc8387448aaa3a094`. The package directory retains the upstream `py311` name, but this build provides PySide6. Validation uses an independent hidden GUI process with isolated configuration under `runtime/navigation-validation`; it does not start the assistant bridge or touch the user's open model.

## Controls

| Input | Result |
| --- | --- |
| Middle button drag | Orbit in 3D, including while a native sketch is being edited |
| Ctrl + middle button drag | Pan without changing orientation or scale |
| Shift + middle button drag | Zoom without changing orientation |
| Wheel forward/backward | Zoom out/in, using the cursor position |
| Double middle click | Fit the current view without changing orientation or leaving the sketch |
| Middle click on an entity | Recenter the view on the picked point |
| Begin orbit over a face/edge/vertex | Use the picked scene point as pivot |
| Begin orbit over empty space | Use a point on the camera's focal plane |

The mappings follow [SolidWorks middle mouse documentation](https://help.solidworks.com/2024/english/SolidWorks/sldworks/r_Middle_Mouse_Button.htm) and [SolidWorks' navigation explanation](https://blogs.solidworks.com/products/solidworks/how-do-i-manipulate-my-model-view-let-me-count-the-ways/). [SolidWorks' shortcuts guide](https://blogs.solidworks.com/products/solidworks/shortcuts-for-solidworks-beginners/) specifies double wheel click for fit. Selection itself does not move the camera or override the hover pivot.

## Implementation contract

`src/kurtshape/navigation.py` uses FreeCAD's native `Gui::SolidWorksNavigationStyle`, verified by `getNavigationType()`. FreeCAD [implements the modifier mappings in this class](https://raw.githubusercontent.com/FreeCAD/FreeCAD/main/src/Gui/Navigation/SolidWorksNavigationStyle.cpp). A Qt application event filter supplies double middle fit only inside native 3D viewport widgets. Other widgets and mouse events retain their normal handling.

- `apply_navigation(view=None)` configures the native style and preferences without fitting or changing orientation. Call at startup and for new/opened views. It is idempotent.
- `allow_sketch_3d(sketch=None, view=None, camera=None)` keeps the native sketch's projection, camera, and model context. Native Sketcher already allows orbit; it needs no substitute navigation mode.
- To preserve the camera on sketch entry: capture `camera = view.getCamera()`, call `allow_sketch_3d(sketch, view)`, enter edit, then call `allow_sketch_3d(sketch, view, camera)`. Navigation animation is disabled before entry so no delayed camera reset can undo the user's orbit.
- `normal_to_sketch(sketch, view=None)` changes orientation to the sketch's global plane normal, preserving zoom, focus, and edit state.
- `view_isometric_keep_sketch(view=None)` changes to isometric without fitting or closing Sketcher.
- `sketch_plane_point(view, pixel_position, sketch_or_placement)` returns local sketch coordinates from the camera's actual projection ray. Near edge-on rays return `None`, which the caller should handle with a request to orbit or look normal.

Native viewport callback positions and `getPointOnViewport` use **physical pixels with bottom-left origin**. Qt mouse positions use logical pixels with top-left origin. Convert Qt positions with the viewport's `devicePixelRatioF()` and native viewport height. This computer was verified at a 1.5 device pixel ratio. Do not feed Qt coordinates directly into the native projection helper.

The [native view settings source](https://raw.githubusercontent.com/FreeCAD/FreeCAD/main/src/Gui/View3DSettings.cpp) provides `InvertZoom`, `ZoomAtCursor`, `RotationMode`, `UseNavigationAnimations`, and `UseSpinningAnimations`. KurtShape uses default SolidWorks wheel direction, cursor rotation, immediate camera orientation changes, and no inertial spinning. Sketch `ForceOrtho`, `RestoreCamera`, and `SectionView` are false so 3D view and model context remain available. Users can still deliberately look normal to draw precisely.

Preference and sketch view-property setters run only when their current value
differs. The persisted-view roundtrip probe verifies that repeated navigation
setup on a reopened project leaves `Gui.Document.Modified` false.

## Evidence and reproducibility

`tests/test_navigation.py` has five passing geometric tests covering oblique rays, translated/tilted planes, direction scaling, native ray delegation, and edge-on/non-finite rejection. `tools/navigation-validation.FCMacro` sends QtTest presses/releases and direct Qt movement/wheel events to FreeCAD's native viewport. Its 16 checks cover picked-face pivot, 3D sketch entry, controls and double middle fit inside Sketcher, perspective projection on a tilted plane, and the tilted sketch's normal view. `validation/navigation-test-result.json` records camera quaternions, positions, scale, native style, runtime revision, and assertions. `validation/navigation-sketch-3d.png` captures a native sketch remaining in edit from an isometric view.

Run the macro using the bundled `bin/freecad.exe` with `-u` and `-s` pointing to independent config files under `runtime/navigation-validation`; set `KURTSHAPE_ROOT`, `FREECAD_USER_HOME`, `TEMP`, `TMP`, `APPDATA`, and `LOCALAPPDATA` under that directory. Launch the helper with PowerShell `Start-Process -WindowStyle Hidden`. The macro additionally uses `WA_DontShowOnScreen` and closes only its own documents/window.

The script proves camera behavior and projection calculations in the installed native viewport. Physical mouse comfort, driver behavior, and the combined KurtShape workflow still need a hands-on check. This does not claim exact SolidWorks camera sensitivity or every optional SolidWorks mouse mode; Alt roll and Ctrl+Alt camera-view motion are outside this pass's declared controls.
