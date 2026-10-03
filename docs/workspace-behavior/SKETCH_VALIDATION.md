# Sketch drawing and floating widget validation

October 2, 2026. Native FreeCAD 1.1.4, revision
`4fd3bf320d9566a27e60069fc8387448aaa3a094`, in an independent hidden process.

The main Line toolbar button and default L binding now use native Polyline:
four successive canvas clicks draw three connected line segments. Single line
remains in the Geometry menu for separate two-point segments. Both native
handlers activate with continuous creation enabled, while the application's
helper restores the stored native preference immediately after activation.
Sketcher caches this setting in the active handler. No artificial transactions
or mouse-event interception are introduced.

`tools/sketch-behavior-validation.FCMacro` exercises the production Panel through
actual toolbar clicks, canvas mouse events, and keyboard L/Escape. It checks
connected endpoints, Escape/right-click termination, Finish followed by one
document Undo/Redo, Cancel restoration without discarded geometry returning,
repeated independent Single line creation, and restoration of both explicit
False and absent continuous-creation preferences.

The final run passed 28 checks, including the guarded, deferred theme updates.
The independently launched process exited normally after reporting its result.

The user's stored View and Sketcher visual preferences are read without edits
and copied into the isolated profile. No projects, recovery data, recent files,
application window state, or assistant credentials are copied. Native floating
Line length/angle controls are `Gui::QuantitySpinBox` widgets inside
`QStackedWidget -> Gui::View3DInventor`. Their original rendered text is readable
under this app theme, but a native local white-on-white stylesheet defeats an
application palette alone. The baseline probe records zero rendered ink pixels
in `validation/sketch-behavior/floating-style-baseline.json`.

The repaired app owns text/background colors locally for floating viewport
inputs and the parentless `Gui::NotificationLabel`. The validation deliberately
applies a hostile local stylesheet and palette to actual native widgets, then
re-shows them and checks rendered dark ink pixels and unchanged widget sizes.
It also checks that a long rich-text native notification fits its contents
rectangle. The notification already sizes itself correctly; no resizing patch
was needed.

Run from this repository in PowerShell:

```powershell
.\validate-sketch-behavior.ps1 -FreshProfile
```

The launcher returns its independent FreeCAD process ID and creates a descriptive
timestamped profile under `runtime`. The macro exits that process after saving
`validation/sketch-behavior/native-behavior.json`; its watchdog is 45 seconds.
Screenshots beside the report are ignored by Git. Python networking is disabled
and the bridge is replaced with a queue-only transport. Native C++ networking is
not intercepted.

Limitations: these are small synthetic sketches. Plane-support and sketch-axis
hover probes did not reproduce the user's exact original floating message, so
the recorded result establishes native surface readability rather than claiming
that exact trigger was captured. Native snapshot undo/redo can emit empty
`Sketch.InternalShape.bin` and constraint-index diagnostics in this runtime;
geometry, endpoint connectivity, undo, and cancellation checks still pass.
One reused isolated GUI profile exited with native access violations during
startup; a fresh profile passed. Theme event-filter local stylesheet updates
are now deferred with a widget-liveness guard to avoid reentering native widget
construction.
