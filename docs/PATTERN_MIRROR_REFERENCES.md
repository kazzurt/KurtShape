# Pattern references and cross-body Mirror

## What it does

**Linear pattern.** Direction is either *Selected edge or line* or *Manual direction*.
- Click a straight model edge or a sketch line in the viewport. The dialog switches to that reference, and the row names it, for example `Rail · Edge4 · line`.
- Use **×** or *Clear all* to remove the reference, or click another edge to replace it.
- **Reverse direction** flips the pattern.

**Circular pattern.** Axis is either *Selected edge, line, circle or arc* or *Manual axis* (origin and direction).
- A straight edge or line is the axis itself.
- A circle or arc defines the axis through its center, along its normal.

**Mirror.** You can mirror about a datum plane or a planar face, including a face on another part.

**Associativity.**
- References stay native and associative. Editing the referenced sketch or feature, or moving or rotating the referenced part's Body, updates the pattern: its direction, and its axis position and orientation. The same holds for the mirror plane.
- The reference can be on the patterned part or on another part.

**Unchanged behavior.**
- Count, spacing, angle, result operation (New/Add/Remove/Intersect), preview, Cancel and one-step Confirm/Undo/Redo work as before.
- Manual patterns work as before.
- References survive save and reopen.

**Rejected input.** These are rejected with a message, and the model is unchanged:
- a face, B-spline or other unsupported edge;
- a circle chosen as a linear direction;
- a missing edge or feature;
- a nonplanar mirror face;
- geometry behind the rollback bar;
- a *selected* reference that has been cleared, which blocks Confirm.

## How it stays associative

1. A root-level native datum (`PartDesign::Line` or `PartDesign::Plane`) is attached to the referenced element.
   - Tangent mode is used for straight edges, AxisOfCurvature for circles and arcs, and FlatFace for mirror faces.
   - Attachment links are document-wide, so they do not trip FreeCAD's link-scope check.
2. A root-level driver composes the containing Body placements with the datum's placement by expression.
3. Each pattern copy's Link placement is the native expression `Driver · Step_i · minvert(Driver) · Source`. The Mirror links the driver plane.

No vector or center is copied once; everything recomputes natively. Helpers are internal and belong to their operation.

## The reported Mirror warning

**Cause.** `Part::Mirroring.MirrorPlane` is a local-scope link. A Studio Mirror lives at the document root, so linking `Shell.Face11` inside `Body` leaves its scope: *Link(s) to object(s) 'Shell' go out of the allowed scope 'Mirror'*.

**Fix.** New mirrors about a face inside a Body now link the root driver plane described above.

**Compatibility repair.** On open, saved Studio mirrors with a direct face link are relinked to a driver that follows the same face.
- The Mirror keeps its name, Source and outputs, so downstream references are kept, and its geometry is unchanged.
- No Undo step is added. Save to persist the repair.
- The first load of an unrepaired file still prints the warning once, because FreeCAD restores the link before any repair can run.
- A nonplanar or missing face is left unchanged, and the model's build status reports it.

## Evidence (Windows, FreeCAD 1.1.4 / OCCT 7.8.1)

**`tests/test_pattern_mirror_references.py`** (native, 11 tests). Each test checks the operation itself; fixture edits assert that they changed the sketch.
- Linear by an edge on another part; following a 90° Body rotation; Undo/Redo.
- Sketch-line direction with Reverse; an upstream line edit.
- Manual patterns.
- Circle axis following translation, tilt and an upstream circle move.
- Straight-edge axis with Reverse, save/reopen and a Body move after reopen.
- A reference on the patterned part itself.
- Invalid and future references.
- Mirror about another part's face: live plane and source, Undo, no warning after save.
- Nonplanar and broken mirror faces.
- Legacy direct-link migration: same identity and geometry, no Undo step, no warning after save.
- The saved example: the Mirror follows `Shell.Face11` and the Body placement.

Warnings are checked in a fresh native process with console output enabled.

**`pattern-mirror` GUI recipe** (35 checks, real viewport clicks):
- The saved example migrates in the GUI.
- Linear, circular and mirror references are picked and labeled.
- Reverse changes the preview.
- Preview and Cancel leave the model unchanged; Confirm is one Undo step.
- Moving the referenced parts updates the results.
- A cleared reference gives guidance.
- Manual fallbacks work.
- The pattern still follows its reference after save and reopen.

The runner fails on any link-scope warning after its strict marker. It also requires a deliberate canary warning before the marker, so the check cannot pass vacuously.

## Limitations

- A straight reference's positive direction is the attached datum's tangent, which can run opposite to the edge's drawing direction. The preview shows the result, and Reverse flips it.
- The Studio "moves with its Body" behavior applies to the part's own Body placement and upstream edits. A Transform operation later in history does not move references used earlier in history, as history order requires.
- In the GUI, FreeCAD shows restore-time warnings as notifications, not in the log. The recompute-time check is in the GUI recipe; the restore-time check is in the native tests.
