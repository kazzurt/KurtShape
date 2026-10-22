"""Contextual constraints on native sketch selections."""
from __future__ import annotations

import re


COINCIDENT_COMMANDS = frozenset({"Sketcher_ConstrainCoincident", "Sketcher_ConstrainCoincidentUnified"})


def coincident_lines(sketch, command, selections):
    """Handle two whole lines; point selections retain native coincidence."""
    if command not in COINCIDENT_COMMANDS:
        return False
    lines = []
    for selection in selections:
        if selection.Object != sketch or not selection.SubElementNames:
            return False
        for name in selection.SubElementNames:
            match = re.fullmatch(r"(External)?Edge([1-9][0-9]*)", name)
            if match is None:
                return False
            index = -int(match[2]) - 2 if match[1] else int(match[2]) - 1
            try:
                curve = _geometry(sketch, index)
            except IndexError:
                return False
            if curve.TypeId != "Part::GeomLineSegment":
                return False
            lines.append(index)
    if len(lines) != 2 or lines[0] == lines[1]:
        return False
    constrain_collinear(sketch, *lines)
    return True


def constrain_collinear(sketch, first, second):
    """Make two finite segments share their supporting line, keeping ends free."""
    import Sketcher
    from .core import OperationError
    from .sketch_tools import restore_sketch_content

    if first < 0 and second < 0:
        raise OperationError("constraint_conflict", "Choose at least one editable sketch line")
    if first < 0:
        first, second = second, first
    kind = _missing_relation(sketch, first, second)
    if kind is None:
        raise OperationError("constraint_conflict", "These lines are already coincident")
    original = bytes(sketch.dumpContent())
    blocked = {constraint.First: sketch.Geometry[constraint.First]
               for constraint in sketch.Constraints
               if constraint.Type == "Block" and constraint.IsActive and constraint.First in {first, second}}
    try:
        # Sketcher's line/line tangent constraint is its native collinearity
        # representation: parallel directions and zero normal separation.
        constraint = (Sketcher.Constraint("PointOnObject", first, 1, second)
                      if kind == "PointOnObject" else Sketcher.Constraint(kind, first, second))
        sketch.addConstraint(constraint)
        if sketch.solve() != 0:
            raise OperationError("constraint_conflict", "These lines cannot be made coincident with the current constraints")
        diagnostics = ("ConflictingConstraints", "RedundantConstraints", "PartiallyRedundantConstraints", "MalformedConstraints")
        if any(getattr(sketch, name) for name in diagnostics):
            raise OperationError("constraint_conflict", "These lines are already coincident or conflict with existing constraints")
        # Native line tangency can align a Blocked curve before solving and
        # silently redefine its fixed location. The user's fixed geometry is
        # authoritative; reject that change and restore its original intent.
        for index, curve in blocked.items():
            current = sketch.Geometry[index]
            if any(getattr(curve, name).distanceToPoint(getattr(current, name)) > 1e-7
                   for name in ("StartPoint", "EndPoint")):
                raise OperationError("constraint_conflict", "Fixed geometry prevents these lines from being coincident")
        a, b = (_geometry(sketch, index) for index in (first, second))
        direction = a.EndPoint - a.StartPoint
        if direction.Length < 1e-7 or any(direction.cross(point - a.StartPoint).Length / direction.Length > 1e-7
                                         for point in (b.StartPoint, b.EndPoint)):
            raise OperationError("constraint_conflict", "The sketch solver could not make these lines coincident")
    except Exception:
        restore_sketch_content(sketch, original)
        raise


def _geometry(sketch, index):
    return sketch.Geometry[index] if index >= 0 else sketch.ExternalGeo[-index - 1]


def _missing_relation(sketch, first, second):
    """Avoid re-constraining a shared point or an existing parallel direction."""
    pair = {first, second}
    joined = parallel = collinear = False
    horizontal, vertical = set(), set()
    for constraint in sketch.Constraints:
        if not constraint.IsActive or not constraint.Driving:
            continue
        if {constraint.First, constraint.Second} == pair:
            joined |= (constraint.Type == "Coincident" and constraint.FirstPos in (1, 2)
                       and constraint.SecondPos in (1, 2) or constraint.Type == "PointOnObject")
            parallel |= constraint.Type == "Parallel"
            collinear |= constraint.Type == "Tangent"
        if constraint.Type == "Horizontal" and constraint.FirstPos == 0:
            horizontal.add(constraint.First)
        if constraint.Type == "Vertical" and constraint.FirstPos == 0:
            vertical.add(constraint.First)
    # Projected lines are immutable inputs. Their directions are already fixed
    # even though this sketch has no Horizontal/Vertical constraint on them.
    for index in pair:
        if index >= 0:
            continue
        curve = _geometry(sketch, index)
        direction = curve.EndPoint - curve.StartPoint
        tolerance = direction.Length * 1e-12
        if abs(direction.y) <= tolerance:
            horizontal.add(index)
        if abs(direction.x) <= tolerance:
            vertical.add(index)
    parallel |= pair <= horizontal or pair <= vertical
    if collinear or joined and parallel:
        return None
    # A shared endpoint already supplies zero separation; two horizontal or
    # vertical lines already supply the parallel direction. Use only the
    # missing native equation, leaving the endpoint positions unconstrained.
    return "Parallel" if joined else "PointOnObject" if parallel else "Tangent"
