"""Installed native modeling and sketch tools for compact toolbar menus.

This catalog contains command metadata only. The native workbench owns every
feature, geometry editor and transaction. IDs were checked against the bundled
FreeCAD 1.1.4 command inventory; runtime filtering handles other installations.
"""
from __future__ import annotations

from dataclasses import dataclass
import re


# Resource names from Gui.Command.get(command).getInfo()['pixmap'] in 1.1.4.
# Constraint resources in particular are not named after their command IDs.
_NATIVE_PIXMAPS = {
    'Part_Boolean': 'Part_Booleans',
    'Sketcher_CreateEllipseBy3Points': 'Sketcher_CreateEllipse_3points',
    'Sketcher_CreateArcOfEllipse': 'Sketcher_CreateElliptical_Arc',
    'Sketcher_CreateArcOfHyperbola': 'Sketcher_CreateHyperbolic_Arc',
    'Sketcher_CreateArcOfParabola': 'Sketcher_CreateParabolic_Arc',
    'Sketcher_CreatePeriodicBSpline': 'Sketcher_Create_Periodic_BSpline',
    'Sketcher_Dimension': 'Constraint_Dimension',
    'Sketcher_ConstrainHorizontal': 'Constraint_Horizontal',
    'Sketcher_ConstrainVertical': 'Constraint_Vertical',
    'Sketcher_ConstrainCoincident': 'Constraint_PointOnPoint',
    'Sketcher_ConstrainPointOnObject': 'Constraint_PointOnObject',
    'Sketcher_ConstrainParallel': 'Constraint_Parallel',
    'Sketcher_ConstrainPerpendicular': 'Constraint_Perpendicular',
    'Sketcher_ConstrainTangent': 'Constraint_Tangent',
    'Sketcher_ConstrainEqual': 'Constraint_EqualLength',
    'Sketcher_ConstrainSymmetric': 'Constraint_Symmetric',
    'Sketcher_ConstrainBlock': 'Constraint_Block',
    'Sketcher_ConstrainDistance': 'Constraint_Length',
    'Sketcher_ConstrainDistanceX': 'Constraint_HorizontalDistance',
    'Sketcher_ConstrainDistanceY': 'Constraint_VerticalDistance',
    'Sketcher_ConstrainAngle': 'Constraint_InternalAngle',
    'Sketcher_ConstrainRadius': 'Constraint_Radius',
    'Sketcher_ConstrainDiameter': 'Constraint_Diameter',
    'Sketcher_ToggleDrivingConstraint': 'Sketcher_ToggleConstraint',
}

@dataclass(frozen=True)
class NativeTool:
    key: str
    label: str
    command: str
    workbench: str
    icon: str
    tip: str
    category: str


def _tool(key, label, command, tip, category, workbench='PartDesignWorkbench', icon=None):
    # Engine provenance belongs in the contract/docs, not modeling hover help.
    tip = re.sub(r'\bnative\s+', '', tip, flags=re.IGNORECASE)
    return NativeTool(key, label, command, workbench, icon or _NATIVE_PIXMAPS.get(command, command), tip, category)


MODEL_TOOLS = (
    _tool('pad', 'Extrude', 'PartDesign_Pad', 'Extrude a closed sketch to create a solid or add material to the selected part.', 'Add material'),
    _tool('revolve', 'Revolve', 'PartDesign_Revolution', 'Revolve a closed sketch around an axis to create or add material.', 'Add material'),
    _tool('sweep', 'Sweep', 'PartDesign_AdditivePipe', 'Sweep a sketch profile along a path to create or add material.', 'Add material'),
    _tool('loft', 'Loft', 'PartDesign_AdditiveLoft', 'Connect two or more sketch sections to create or add material.', 'Add material'),
    _tool('additive_helix', 'Helical sweep', 'PartDesign_AdditiveHelix', 'Native Additive Helix: sweep a sketch along a parametric helix.', 'Add material'),
    _tool('additive_primitive', 'Additive primitives', 'PartDesign_CompPrimitiveAdditive', 'Native additive primitive controls: create a primitive feature in the active Body.', 'Add material', icon='PartDesign_AdditiveBox'),
    _tool('pocket', 'Extrude remove', 'PartDesign_Pocket', 'Extrude a closed sketch to remove material from the selected part.', 'Remove material'),
    _tool('groove', 'Revolve remove', 'PartDesign_Groove', 'Revolve a closed sketch around an axis to remove material.', 'Remove material'),
    _tool('subtractive_sweep', 'Sweep remove', 'PartDesign_SubtractivePipe', 'Sweep a sketch profile along a path to remove material.', 'Remove material'),
    _tool('subtractive_loft', 'Loft remove', 'PartDesign_SubtractiveLoft', 'Remove material between two or more sketch sections.', 'Remove material'),
    _tool('subtractive_helix', 'Helical remove', 'PartDesign_SubtractiveHelix', 'Native Subtractive Helix: remove material along a parametric helical sweep.', 'Remove material'),
    _tool('subtractive_primitive', 'Subtractive primitives', 'PartDesign_CompPrimitiveSubtractive', 'Native subtractive primitive controls: cut a primitive volume from the active Body.', 'Remove material', icon='PartDesign_SubtractiveBox'),
    _tool('hole', 'Hole', 'PartDesign_Hole', 'Native Hole: select a positioning sketch to define holes, countersinks or counterbores.', 'Remove material'),
    _tool('fillet', 'Fillet', 'PartDesign_Fillet', 'Round selected edges of a part.', 'Modify'),
    _tool('chamfer', 'Chamfer', 'PartDesign_Chamfer', 'Bevel selected edges of a part.', 'Modify'),
    _tool('shell', 'Shell', 'PartDesign_Thickness', 'Remove selected faces and hollow a part with a specified wall thickness.', 'Modify'),
    _tool('draft', 'Draft', 'PartDesign_Draft', 'Taper selected faces relative to a neutral plane and pull direction.', 'Modify'),
    _tool('boolean', 'Boolean', 'PartDesign_Boolean', 'Combine parts by adding, subtracting or intersecting their solids.', 'Modify'),
    _tool('mirror', 'Mirror', 'PartDesign_Mirrored', 'Mirror selected features across a plane within the selected part.', 'Pattern'),
    _tool('linear_pattern', 'Linear pattern', 'PartDesign_LinearPattern', 'Repeat selected features along a direction within the selected part.', 'Pattern'),
    _tool('circular_pattern', 'Circular pattern', 'PartDesign_PolarPattern', 'Repeat selected features around an axis within the selected part.', 'Pattern'),
    _tool('multi_transform', 'Multiple transforms', 'PartDesign_MultiTransform', 'Native MultiTransform: combine mirror, linear and polar transforms of Body features.', 'Pattern'),
    _tool('datum_plane', 'Plane', 'PartDesign_Plane', 'Create an attached, offset or angled sketch plane in the selected part.', 'Reference'),
    _tool('datum_line', 'Axis', 'PartDesign_Line', 'Native datum line: create an attached reference axis in the active Body.', 'Reference'),
    _tool('datum_point', 'Point', 'PartDesign_Point', 'Native datum point: create an attached reference point in the active Body.', 'Reference'),
    _tool('datum_coordinates', 'Coordinate system', 'PartDesign_CoordinateSystem', 'Native datum coordinate system: define an attached reference frame.', 'Reference'),
    _tool('shape_binder', 'Shape binder', 'PartDesign_ShapeBinder', 'Native ShapeBinder: reference selected geometry from another object for Body modeling.', 'Reference'),
    _tool('subshape_binder', 'Subshape binder', 'PartDesign_SubShapeBinder', 'Native SubShapeBinder: bind selected subelements, with native support and offset options.', 'Reference'),
    _tool('part_extrude', 'Part extrude', 'Part_Extrude', 'Standalone Part extrusion of selected wires or faces; creates a result outside the active Body.', 'Part tools', 'PartWorkbench'),
    _tool('part_revolve', 'Part revolve', 'Part_Revolve', 'Standalone Part revolution of selected wires or faces; creates a result outside the active Body.', 'Part tools', 'PartWorkbench'),
    _tool('part_sweep', 'Part sweep', 'Part_Sweep', 'Standalone Part sweep using sections and a path; creates a result outside the active Body.', 'Part tools', 'PartWorkbench'),
    _tool('part_loft', 'Part loft', 'Part_Loft', 'Standalone Part loft between selected sections; creates a result outside the active Body.', 'Part tools', 'PartWorkbench'),
    _tool('part_boolean', 'Part Boolean', 'Part_Boolean', 'Standalone Part Boolean controls for selected shapes; creates a result outside the active Body.', 'Part tools', 'PartWorkbench'),
    _tool('part_offset', 'Offset surface', 'Part_Offset', 'Native 3D Part offset of a selected shape; creates a result outside the active Body.', 'Part tools', 'PartWorkbench'),
    _tool('part_offset_2d', 'Offset wire', 'Part_Offset2D', 'Native 2D Part offset of selected planar edges or wires; creates a result outside the active Body.', 'Part tools', 'PartWorkbench'),
    _tool('ruled_surface', 'Ruled surface', 'Part_RuledSurface', 'Native Part ruled surface between two selected edges or wires, outside the active Body.', 'Part tools', 'PartWorkbench'),
    _tool('part_thickness', 'Part thickness', 'Part_Thickness', 'Native Part thickness on a selected solid; creates a result outside the active Body.', 'Part tools', 'PartWorkbench'),
    _tool('part_section', 'Intersect shapes', 'Part_Section', 'Native Part section: compute intersection edges of two selected shapes, outside the active Body.', 'Part tools', 'PartWorkbench'),
    _tool('part_check', 'Check geometry', 'Part_CheckGeometry', 'Native Part geometry validation and BOP checks on selected shapes.', 'Part tools', 'PartWorkbench'),
)


def _sketch(key, label, command, tip, category, icon=None):
    return _tool(key, label, command, tip, category, 'SketcherWorkbench', icon)


SKETCH_TOOLS = (
    _sketch('sk_line', 'Line', 'Sketcher_CreateLine', 'Draw a native sketch line.', 'Geometry'),
    _sketch('sk_polyline', 'Polyline', 'Sketcher_CreatePolyline', 'Draw a connected series of native sketch segments.', 'Geometry'),
    _sketch('sk_point', 'Point', 'Sketcher_CreatePoint', 'Create a native sketch point.', 'Geometry'),
    _sketch('sk_circle', 'Circle', 'Sketcher_CreateCircle', 'Draw a circle by center and radius.', 'Geometry'),
    _sketch('sk_three_point_circle', 'Three-point circle', 'Sketcher_Create3PointCircle', 'Draw a circle through three points.', 'Geometry'),
    _sketch('sk_arc', 'Center arc', 'Sketcher_CreateArc', 'Draw an arc by center and endpoints.', 'Geometry'),
    _sketch('sk_three_point_arc', 'Three-point arc', 'Sketcher_Create3PointArc', 'Draw an arc through three points.', 'Geometry'),
    _sketch('sk_rectangle', 'Rectangle', 'Sketcher_CreateRectangle', 'Draw a native corner rectangle.', 'Geometry'),
    _sketch('sk_center_rectangle', 'Center rectangle', 'Sketcher_CreateRectangle_Center', 'Draw a native rectangle about a selected center.', 'Geometry'),
    _sketch('sk_ellipse', 'Center ellipse', 'Sketcher_CreateEllipseByCenter', 'Draw an ellipse by center and axes.', 'Geometry'),
    _sketch('sk_three_point_ellipse', 'Three-point ellipse', 'Sketcher_CreateEllipseBy3Points', 'Draw an ellipse through its native three-point definition.', 'Geometry'),
    _sketch('sk_ellipse_arc', 'Elliptical arc', 'Sketcher_CreateArcOfEllipse', 'Draw a native arc of an ellipse.', 'Geometry'),
    _sketch('sk_hyperbola_arc', 'Hyperbolic arc', 'Sketcher_CreateArcOfHyperbola', 'Draw a native arc of a hyperbola.', 'Geometry'),
    _sketch('sk_parabola_arc', 'Parabolic arc', 'Sketcher_CreateArcOfParabola', 'Draw a native arc of a parabola.', 'Geometry'),
    _sketch('sk_bspline', 'Spline control points', 'Sketcher_CreateBSpline', 'Draw a B-spline using its native control-point construction.', 'Geometry'),
    _sketch('sk_interpolated_spline', 'Spline through points', 'Sketcher_CreateBSplineByInterpolation', 'Draw a native interpolating B-spline through selected points.', 'Geometry'),
    _sketch('sk_periodic_spline', 'Closed spline control points', 'Sketcher_CreatePeriodicBSpline', 'Draw a periodic B-spline by control points.', 'Geometry'),
    _sketch('sk_periodic_interpolated_spline', 'Closed spline through points', 'Sketcher_CreatePeriodicBSplineByInterpolation', 'Draw a periodic interpolating B-spline through points.', 'Geometry'),
    _sketch('sk_slot', 'Slot', 'Sketcher_CreateSlot', 'Draw a native straight slot.', 'Geometry'),
    _sketch('sk_arc_slot', 'Arc slot', 'Sketcher_CreateArcSlot', 'Draw a native curved slot.', 'Geometry'),
    _sketch('sk_oblong', 'Oblong', 'Sketcher_CreateOblong', 'Draw a native oblong profile.', 'Geometry'),
    _sketch('sk_polygon', 'Regular polygon', 'Sketcher_CreateRegularPolygon', 'Draw a regular polygon with a chosen side count.', 'Geometry'),
    _sketch('sk_square', 'Square', 'Sketcher_CreateSquare', 'Draw a native four-sided regular polygon.', 'Geometry'),
    _sketch('sk_triangle', 'Triangle', 'Sketcher_CreateTriangle', 'Draw a native three-sided regular polygon.', 'Geometry'),
    _sketch('sk_pentagon', 'Pentagon', 'Sketcher_CreatePentagon', 'Draw a native five-sided regular polygon.', 'Geometry'),
    _sketch('sk_hexagon', 'Hexagon', 'Sketcher_CreateHexagon', 'Draw a native six-sided regular polygon.', 'Geometry'),
    _sketch('sk_heptagon', 'Heptagon', 'Sketcher_CreateHeptagon', 'Draw a native seven-sided regular polygon.', 'Geometry'),
    _sketch('sk_octagon', 'Octagon', 'Sketcher_CreateOctagon', 'Draw a native eight-sided regular polygon.', 'Geometry'),
    _sketch('sk_dimension', 'Dimension', 'Sketcher_Dimension', 'Apply the native contextual dimension tool to selected sketch elements.', 'Constraints'),
    _sketch('sk_horizontal', 'Horizontal', 'Sketcher_ConstrainHorizontal', 'Constrain selected sketch elements horizontally.', 'Constraints'),
    _sketch('sk_vertical', 'Vertical', 'Sketcher_ConstrainVertical', 'Constrain selected sketch elements vertically.', 'Constraints'),
    _sketch('sk_coincident', 'Coincident', 'Sketcher_ConstrainCoincident', 'Make selected sketch points coincident.', 'Constraints'),
    _sketch('sk_point_on_object', 'Point on object', 'Sketcher_ConstrainPointOnObject', 'Constrain a sketch point onto selected geometry.', 'Constraints'),
    _sketch('sk_parallel', 'Parallel', 'Sketcher_ConstrainParallel', 'Make selected sketch lines parallel.', 'Constraints'),
    _sketch('sk_perpendicular', 'Perpendicular', 'Sketcher_ConstrainPerpendicular', 'Make selected sketch elements perpendicular.', 'Constraints'),
    _sketch('sk_tangent', 'Tangent', 'Sketcher_ConstrainTangent', 'Apply native tangency to selected sketch geometry.', 'Constraints'),
    _sketch('sk_equal', 'Equal', 'Sketcher_ConstrainEqual', 'Make selected sketch lengths or radii equal.', 'Constraints'),
    _sketch('sk_symmetric', 'Symmetric', 'Sketcher_ConstrainSymmetric', 'Constrain sketch elements symmetrically about a line or point.', 'Constraints'),
    _sketch('sk_block', 'Fix geometry', 'Sketcher_ConstrainBlock', 'Native Block constraint: lock selected geometry against solver movement.', 'Constraints'),
    _sketch('sk_distance', 'Distance', 'Sketcher_ConstrainDistance', 'Apply a native length or distance dimension.', 'Constraints'),
    _sketch('sk_distance_x', 'Horizontal distance', 'Sketcher_ConstrainDistanceX', 'Apply a horizontal native distance dimension.', 'Constraints'),
    _sketch('sk_distance_y', 'Vertical distance', 'Sketcher_ConstrainDistanceY', 'Apply a vertical native distance dimension.', 'Constraints'),
    _sketch('sk_angle', 'Angle', 'Sketcher_ConstrainAngle', 'Apply a native angle dimension.', 'Constraints'),
    _sketch('sk_radius', 'Radius', 'Sketcher_ConstrainRadius', 'Apply a native radius dimension.', 'Constraints'),
    _sketch('sk_diameter', 'Diameter', 'Sketcher_ConstrainDiameter', 'Apply a native diameter dimension.', 'Constraints'),
    _sketch('sk_reference_dimension', 'Driving / reference', 'Sketcher_ToggleDrivingConstraint', 'Switch selected native dimensions between driving and reference mode.', 'Constraints'),
    _sketch('sk_active_constraint', 'Enable / disable constraint', 'Sketcher_ToggleActiveConstraint', 'Toggle selected native constraints active or inactive.', 'Constraints'),
    _sketch('sk_construction', 'Construction', 'Sketcher_ToggleConstruction', 'Toggle selected sketch geometry between normal and construction mode.', 'Edit'),
    _sketch('sk_trim', 'Trim', 'Sketcher_Trimming', 'Trim native sketch geometry at intersections.', 'Edit'),
    _sketch('sk_extend', 'Extend', 'Sketcher_Extend', 'Extend native sketch geometry to a selected target.', 'Edit'),
    _sketch('sk_split', 'Split', 'Sketcher_Split', 'Split native sketch geometry at a picked point.', 'Edit'),
    _sketch('sk_offset', 'Offset', 'Sketcher_Offset', 'Create a native offset of selected sketch geometry.', 'Edit'),
    _sketch('sk_fillet', 'Sketch fillet', 'Sketcher_CreateFillet', 'Create a native fillet between sketch elements.', 'Edit'),
    _sketch('sk_chamfer', 'Sketch chamfer', 'Sketcher_CreateChamfer', 'Create a native chamfer between sketch elements.', 'Edit'),
    _sketch('sk_join', 'Join curves', 'Sketcher_JoinCurves', 'Use native curve-join editing on selected sketch geometry.', 'Edit'),
    _sketch('sk_projection', 'Project external geometry', 'Sketcher_Projection', 'Project geometry from another native object into the active sketch.', 'Edit'),
    _sketch('sk_intersection', 'Intersect external geometry', 'Sketcher_Intersection', 'Reference the native intersection of another object with the sketch plane.', 'Edit'),
    _sketch('sk_carbon_copy', 'Carbon copy', 'Sketcher_CarbonCopy', 'Copy geometry from another native sketch with the native dependency behavior.', 'Edit'),
    _sketch('sk_mirror', 'Mirror geometry', 'Sketcher_Symmetry', 'Create symmetric geometry using native sketch symmetry.', 'Edit'),
    _sketch('sk_move', 'Move geometry', 'Sketcher_Move', 'Move selected geometry using native sketch editing.', 'Edit'),
    _sketch('sk_rotate', 'Rotate geometry', 'Sketcher_Rotate', 'Rotate selected geometry using native sketch editing.', 'Edit'),
    _sketch('sk_scale', 'Scale geometry', 'Sketcher_Scale', 'Scale selected geometry using native sketch editing.', 'Edit'),
    _sketch('sk_array', 'Rectangular array', 'Sketcher_RectangularArray', 'Create a native rectangular array of selected sketch geometry.', 'Edit'),
    _sketch('sk_validate', 'Validate sketch', 'Sketcher_ValidateSketch', 'Open native sketch validation and repair controls.', 'Edit'),
)

ALL_TOOLS = MODEL_TOOLS + SKETCH_TOOLS
BY_KEY = {tool.key: tool for tool in ALL_TOOLS}
PRIMARY_TOOLS = tuple(BY_KEY[key] for key in
                      ('revolve', 'sweep', 'loft', 'fillet', 'chamfer',
                       'shell', 'draft', 'linear_pattern', 'circular_pattern', 'mirror', 'boolean', 'datum_plane'))
TOOL_GROUPS = tuple((category, tuple(tool for tool in MODEL_TOOLS if tool.category == category))
                    for category in ('Add material', 'Remove material', 'Modify', 'Pattern', 'Reference', 'Part tools'))
SKETCH_GROUPS = tuple((category, tuple(tool for tool in SKETCH_TOOLS if tool.category == category))
                      for category in ('Geometry', 'Constraints', 'Edit'))


def icon_name(tool):
    """Resolve the command's actual native pixmap; fallback is a resource name."""
    try:
        import FreeCADGui as Gui
        info = Gui.Command.get(tool.command).getInfo()
        return str(info.get('pixmap') or tool.icon)
    except (AttributeError, RuntimeError, KeyError):
        return tool.icon


def available_catalog(commands=None):
    """Return only registered native commands; import does not activate tools."""
    if commands is None:
        import FreeCADGui as Gui
        commands = Gui.listCommands()
    registered = set(commands)
    keep = lambda tools: tuple(tool for tool in tools if tool.command in registered)
    groups = lambda rows: tuple((label, selected) for label, tools in rows
                               if (selected := keep(tools)))
    return {'primary': keep(PRIMARY_TOOLS), 'groups': groups(TOOL_GROUPS),
            'sketch_groups': groups(SKETCH_GROUPS), 'all': keep(ALL_TOOLS)}
