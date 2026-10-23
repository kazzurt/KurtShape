"""Confirm gating for the Extrude / Remove dialog.

One pure decision shared by the dialog (button state) and the preview adapter
(what ``flush``/``current_result`` may hand to the commit). It has no Qt or
FreeCAD dependency, so the rule is testable headlessly.

Rule (slice A/B, unit U1):

    Confirm enabled  <=>  (an exact result exists for the current normalized fields and is valid)
                          or (provisional acceptance is allowed for this task,
                              no exact or commit rejection is remembered for the current fields,
                              a provisional result exists for them, and it carries a mesh)

A *valid provisional* is a provisional result carrying a mesh: the provisional
path only returns one for a closed profile and a usable blind depth. An exact
result that is invalid for the current fields disables Confirm with its error,
because a commit known to fail is not offered; that rejection is remembered
for those fields until they change or the task restarts.

Provisional acceptance is allowed only where the commit itself validates the
geometry: a Part Studio document (Add / Remove / Intersect run result checks),
a legacy Remove material (the native pocket requires removed material:
``empty_cut``) and, since slice A/B U9, a legacy Extrude (the native pad must
add material: ``empty_add``). So every new Extrude / Remove task qualifies and
edits keep the exact gate. Where the provisional path produces nothing (Up to
face, Through all, an edit, a face extrusion, a legacy Remove without a
direction) the exact gate is unchanged as well.
"""

EXACT = "exact"
PROVISIONAL = "provisional"

# Rejections that describe the session rather than the fields: a later
# identical proposal may succeed, so they are never remembered per fields.
TRANSIENT_CODES = frozenset({
    "busy", "preview_failed", "preview_closed", "stale_revision", "stale_preview_snapshot",
    "invalid_preview_snapshot", "invalid_preview_clone", "unknown_document", "unmanaged_document",
    "sketch_edit_active", "document_changed",
    # Session-state codes a pad/pocket commit can return; none is a verdict about the fields.
    "unmanaged_transaction", "sketch_history_changed", "sketch_editor_open", "user_editing", "checkpoint_failed",
})


def provisional_allowed(op, studio=False, editing=False, proposal=None):
    """Whether Confirm may commit from a provisional preview for this task.

    ``op`` is the task kind (``"pad"`` or ``"pocket"``), ``studio`` the
    document's Part Studio flag, ``editing`` whether an existing feature is
    being edited, ``proposal`` the dialog's proposal when available. Every new
    pad or pocket commit validates its geometry (Part Studio result checks, the
    legacy pocket's removed material, the legacy pad's added material since
    slice A/B U9), so ``studio`` and ``proposal`` no longer change the answer;
    they stay in the signature for the callers.
    """
    return not editing and op in {"pad", "pocket"}


def remembers_rejection(error):
    """Whether an exact or commit rejection is a verdict about the fields.

    Geometric and argument rejections (``empty_cut``, ``empty_add``,
    ``empty_preview``, ``build_failed``, ``invalid_geometry``, ``open_profile``,
    ``invalid_argument``, …) are remembered per normalized fields; worker,
    transport and revision failures stay retryable.
    """
    if not isinstance(error, dict):
        return False
    code = error.get("code")
    return isinstance(code, str) and bool(code) and code not in TRANSIENT_CODES


def verdict(result, proposal=None, provisional=False):
    """Return ``EXACT``, ``PROVISIONAL`` or ``None`` for the result shown for the current fields.

    ``proposal`` is the current normalized proposal when the caller has one; a
    result computed for other fields never authorizes a commit. ``provisional``
    is ``provisional_allowed(...)`` for the task; False keeps the exact-only gate.
    """
    if result is None:
        return None
    if proposal is not None and result.proposal != proposal:
        return None
    if result.provisional:
        if provisional and result.mesh is not None and result.error is None:
            return PROVISIONAL
        return None
    return EXACT if result.valid else None


def accept_enabled(result, proposal=None, provisional=False):
    """Button state for the current verdict."""
    return verdict(result, proposal, provisional) is not None
