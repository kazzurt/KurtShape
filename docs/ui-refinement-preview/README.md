# Extrusion preview implementation and integration

FreeCAD 1.1.4 / OCCT 7.8.1, 2026-10-02.

`src/kurtshape/extrusion_preview.py` evaluates the same controller Pad/Pocket
operation in a hidden, temporary native FCStd and closes it before returning.
Only detached BRep results and an unpickable Coin overlay survive evaluation.
The source project gains no object, transaction, feature, metadata or document
registration. Acceptance still uses the normal controller operation, a fresh
feature ID, and the current expected revision.

The overlay displays added material in blue, removed material in orange, and
actual result edges. It uses native tessellation; it does not approximate a
sketch with a manually drawn prism. Original object visibility stays intact.
Pocket ghosts use a local Coin `SoDepthBuffer` with depth testing/writing
disabled and function `ALWAYS`, so removed material is visible through the
opaque original solid. The additive ghost keeps normal occlusion. The depth
state stays inside the transient separator; every ghost remains unpickable.
Native FCStd loading clears selection even in hidden mode; the evaluator
restores selected native references/picked points, camera and modified state.

## UI hooks

1. Construct `DebouncedExtrusionPreview(core, parent=panel, status=callback,
   allowed=lambda: panel.task in {'pad','pocket'} and panel.editor.isVisible())`.
2. On opening/reselecting an extrusion task, `begin(document, state['revision'])`.
3. On profile/depth/direction/end-type changes, `schedule(proposal)`. Use depth
   line-edit text so invalid intermediate input can clear the ghost and return
   a useful validation message. Pad uses explicit `reversed`; Pocket preserves
   the current acceptance convention: omit `reversed` when the default direction
   fallback is intended, otherwise provide the chosen boolean. `through_all`
   ignores depth. The proposal resolves the profile's owning Body explicitly.
4. Display `result.error['message']` next to the editor fields for invalid
   results; avoid repeated status-bar toasts. `None` means preview was cleared.
5. `clear()` before the controller acceptance call, on explicit Cancel, on a
   task/profile/document switch, and before entering a sketch/native editor.
   `close()` on panel/window shutdown. Failed acceptance can begin/schedule a
   new preview for the retained editor. Closing/hiding the editor or activating
   or closing its document also triggers automatic cleanup within 200 ms.

Updates debounce by 160 ms. One native source snapshot per generation and eight
recent detached results are cached. Semantically equivalent field normalization
(`7 mm` to `7.00 mm`, or an equivalent quantity in another unit) preserves the
current result/ghost and reports validity synchronously. This keeps a Confirm
click enabled while the quantity widget normalizes its text on losing focus.
Source lifetime/revision/generation guards still apply; invalid or changed input
discards the prior result. Evaluation remains synchronous on the GUI
thread because FreeCAD document operations are not thread-safe. First GUI
evaluation measured about 631 ms on the initial controlled run; this is not a
claim that all updates, large models or visible input latency meet a 100 ms goal.

## Reproduction and evidence

Run `powershell -ExecutionPolicy Bypass -File tools/validate-extrusion-preview.ps1`
from the repository. It runs five focused native tests, then launches a hidden
independent GUI/profile, preserving the user's application. Wait for
`validation/ui-refinement-preview/gui-result.json` to show `passed: true`.

Five native tests pass: quantity/reversed depth, cache/cancel disposal,
attached-face Pad and blind/through-all Pocket, default/reversed cut direction,
second Body and placement, acceptance equivalence, and invalid/open/stale
proposals. Each compares live intent, UUID/revision, native undo/redo, pending
transaction, filename, App/controller documents and observer/evaluation caches.

The separate GUI recipe passes 20 checks: rendering and unpickability,
debounced final value, immediate ghost removal for invalid text, preserved
modified/visibility/selection/camera pose and native invariants, equivalent text
and unit deduplication, blind vs
through-all cut geometry, controller acceptance, explicit cancel, editor hide,
local cut-only depth state, new accepted revision invalidation, document
switch/close and timer/resource shutdown. View animation is allowed
to settle before camera comparison. Camera position, orientation, focal distance,
zoom and other pose fields are compared; derived near/far clipping distances may
expand on redraw to accommodate the ghost geometry.
The last isolated GUI run measured 554 ms for the first Pad evaluation, 70 ms
for a new blind Pocket, and 64 ms for Through all, excluding debounce and
compositor latency. These are small-fixture measurements, not large-part bounds.

The GUI recipe is isolated from `ui.py` so it can run while assembly and toolbar
integration are being coordinated. The production Panel's
`tools/ui-refinement-validation.FCMacro` also passes 106 assertions. Its
projected removed-cylinder interior sample is orange in 625/625 pixels during
a blind cut preview and 0/625 after Cancel, while source visibility, geometry,
history and selection stay unchanged. Screenshots and measured patches are
under `validation/ui-refinement/`.

Arbitrary end conditions, previewing edits to
existing extrusion features, and feature tools beyond Pad/Pocket are outside
this change.
