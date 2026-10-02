# Native toolbar catalog

`src/kurtshape/feature_tools.py` supplies metadata for actual bundled FreeCAD
commands. The native workbench owns the feature, parameter editor, geometry and
undo transaction. The catalog stores no model state or substitute geometry.

The model catalog has 39 tools in Build, Cut, Modify, Patterns, Reference and
Shape tools menus. Eleven common commands are suitable for direct buttons:
Revolve, Sweep, Loft, Fillet, Chamfer, Hole, Shell, Draft, Mirror, Linear pattern
and Boolean. The shell also retains its Sketch, Extrude and Remove buttons.

The sketch catalog has 64 commands in Geometry, Constraints and Edit menus,
including arc/ellipse/spline variants, slots and polygons, dimensional and
geometric constraints, projection/intersection, trim, offset, fillet, chamfer
and transforms. The UI may retain direct buttons for common sketch tools.

`available_catalog()` filters against the current registered command list.
Each immutable `NativeTool` supplies `key`, `label`, `command`, `workbench`,
`icon`, `tip` and `category`. `PRIMARY_TOOLS`, `TOOL_GROUPS`, `SKETCH_GROUPS`
and `BY_KEY` can also be read without importing FreeCAD. `icon_name(tool)`
resolves `Gui.Command.get(command).getInfo()['pixmap']`; verified resource
names are also retained as fallbacks, including native Constraint icons.

Tooltips state the engine equivalent where semantics differ: Shell opens
native Thickness, Sweep opens native Additive Pipe, and Revolve remove opens
native Groove. Shape tools use PartWorkbench and describe standalone results
outside the active PartDesign Body. No second Body creation action is exposed.

## Verification and reproduction

Bundled FreeCAD 1.1.4, revision `4fd3bf320d9566a27e60069fc8387448aaa3a094`:
`validation/appearance-pass/feature-catalog-probe.json` confirms all 103 command
IDs are registered after loading the relevant native workbenches and each has
an actual native pixmap resource. The toolbar harness uses real custom toolbar
buttons/menu actions, native Tasks and QtTest; assistant transport is replaced
with a no-op transport so validation starts no bridge or socket.

Run `tools/toolbar-validation.FCMacro` with `KURTSHAPE_ROOT` set to this project
and `KURTSHAPE_TOOLBAR_MODE=catalog` for the command/icon inventory, or
`KURTSHAPE_TOOLBAR_MODE=appearance` for model tools. Optional
`KURTSHAPE_AUDIT_TOOLS` is a comma-separated list of catalog keys;
`KURTSHAPE_AUDIT_MODE` is `cancel`, `accept` or `both`. Reports and editable
accepted FCStd fixtures are saved under `validation/appearance-pass`.

Use the bundled native executable with explicit isolated `-u user.cfg`,
`-s system.cfg`, `--log-file native.log` and the macro filename. Set
`FREECAD_USER_HOME`, `APPDATA`, `LOCALAPPDATA`, `TEMP` and `TMP` to descriptive
folders inside `runtime/appearance-model-validation`. Launch with PowerShell
`Start-Process -WindowStyle Hidden`; do not use FreeCAD's `--hidden` option,
which exits before GUI timers. The macro creates an invisible render-capable
main window and never interacts with existing FreeCAD processes/documents.

Accepted Loft, Hole, Shell and Draft fixtures each produce a valid single
solid, appear in custom history, pass the controller build check and save as
editable FCStd files. These representative tests do not establish all native
parameter combinations or general Onshape feature parity. A rapid mixed
task/document stress attempt hit a caught native C++ Access violation;
priority acceptance was verified in fresh isolated processes with no warnings.

The initial Part Extrude audit exposed a real core guard defect: native Part
Tasks can be active while `Gui.getInEdit()` is empty, permitting direct API New
to switch documents. The failing JSON evidence is retained in
`model-tools-hole_loft_part_extrude_shell.json`; subsequent checks must also
guard native `Gui.Control.activeDialog()` before changing documents or model
state. See final model-tool reports for the corrected guard verification.

`validation/appearance-pass/native-model-tools-final-result.json` consolidates
17 passing scenarios: 12 native dialog cancel/close paths and five accepted
features. Every canonical source report passes in full; it retains the original failed
guard attempt as context. All 48 final direct-core guard checks pass across
New, Open, set_parameter and Save during Part Extrude Tasks, where no native
edit object is present. Closing without applying preserves exact native intent,
Body membership and BRep. The accepted standalone Part extrusion is valid,
500 mm³, visible in history and saved editable. The custom controller continues
to assess/export the scoped Body; a standalone Part result does not change the
Body's build status or become its export target.

| Canonical report in `validation/appearance-pass` | Scenarios |
| --- | --- |
| `model-tools-hole_loft_shell_cancel.json` | Loft, Hole, Shell cancel (3) |
| `model-tools-draft.json` | Draft cancel and accept (2) |
| `model-tools-loft_accept.json` | Loft accept (1) |
| `model-tools-hole_accept.json` | Hole accept (1) |
| `model-tools-shell_accept.json` | Shell accept (1) |
| `model-tools-circular_pattern_groove_multi_transform_sweep_cancel.json` | Sweep, Groove, Circular pattern, MultiTransform cancel (4) |
| `model-tools-datum_line_datum_plane_datum_point_cancel.json` | Plane, Axis, Point cancel (3) |
| `model-tools-part_extrude.json` | Part extrude Close and OK, plus 48 core guard checks (2) |
