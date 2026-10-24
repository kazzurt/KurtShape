"""Measurements of the current selection, in global coordinates (assembly UX item 6).

FreeCAD-only (no Qt): the GUI's live readout and the bridge's ``measure``
operation share it. ``element_shape`` turns a selected object/sub-element into
its world-frame shape (an occurrence's face where it sits in the assembly, not
in its source frame); ``describe`` measures one or more such shapes and
returns ``{"kind", "text", "values"}``. Lengths are mm with 3 decimals, angles
degrees with 2. Parallel/perpendicular tolerance 0.5°, coaxial 1 µm radial.
"""
from __future__ import annotations

import math

import FreeCAD as App

ANGLE_TOLERANCE_DEG = 0.5
COAXIAL_TOLERANCE_MM = 0.001


class MeasureError(ValueError):
    pass


# Shapes ---------------------------------------------------------------
def element_shape(obj, subelement=""):
    """World-frame shape of ``obj`` (or its ``subelement``) with every parent placement applied."""
    import Part
    if obj is None:
        raise MeasureError("Unknown object")
    shape = Part.getShape(obj, subelement or "", needSubElement=bool(subelement), transform=True)
    if shape is None or shape.isNull():
        raise MeasureError("Nothing measurable at " + obj.Name + ("." + subelement if subelement else ""))
    shape = shape.copy()
    # getShape applies obj's own placement; add its parents' (an assembly's, a part container's).
    # App::Link has no getGlobalPlacement, so take the enclosing GeoFeature group's.
    group = obj.getParentGeoFeatureGroup() if hasattr(obj, "getParentGeoFeatureGroup") else None
    if group is not None:
        parent = group.getGlobalPlacement()
        if not parent.isIdentity():
            shape.transformShape(parent.toMatrix(), True)
    return shape


def _fmt(value, digits=3):
    text = f"{value:.{digits}f}"
    return "0." + "0" * digits if text in {"-0." + "0" * digits} else text


def length(value):
    return _fmt(value) + " mm"


def angle(value):
    return _fmt(value, 2) + "°"


def _vector(value):
    return [round(value.x, 9), round(value.y, 9), round(value.z, 9)]


def _delta_text(delta):
    return f"ΔX {_fmt(delta.x)} · ΔY {_fmt(delta.y)} · ΔZ {_fmt(delta.z)} mm"


def _delta_values(delta):
    return {"dx_mm": delta.x, "dy_mm": delta.y, "dz_mm": delta.z}


def _acute(a, b):
    """Acute angle in degrees between two directions (lines, normals)."""
    cosine = abs(a.normalize().dot(b.normalize()))
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _parallel(a, b):
    return _acute(a, b) <= ANGLE_TOLERANCE_DEG


# Classification ---------------------------------------------------------
def classify(shape):
    """A small description of a shape: kind and the analytic data the cases need."""
    import Part
    kind = shape.ShapeType
    if kind == "Vertex":
        return {"type": "point", "point": shape.Point, "shape": shape}
    if kind == "Edge":
        curve = shape.Curve
        if isinstance(curve, (Part.Line, Part.LineSegment)):
            first, last = shape.valueAt(shape.FirstParameter), shape.valueAt(shape.LastParameter)
            return {"type": "line", "point": first, "direction": (last - first).normalize()
                    if (last - first).Length > 1e-12 else App.Vector(curve.Direction), "shape": shape}
        if isinstance(curve, Part.Circle):
            return {"type": "circle", "point": App.Vector(curve.Center), "direction": App.Vector(curve.Axis),
                    "radius": curve.Radius, "shape": shape}
        return {"type": "edge", "shape": shape}
    if kind == "Face":
        surface = shape.Surface
        if isinstance(surface, Part.Plane):
            normal = shape.normalAt(*_middle(shape))
            return {"type": "plane", "point": shape.CenterOfMass, "normal": normal, "shape": shape}
        if isinstance(surface, Part.Cylinder):
            axis = App.Vector(surface.Axis).normalize()
            centre = App.Vector(surface.Center)
            heights = [(vertex.Point - centre).dot(axis) for vertex in shape.Vertexes] or [0.0]
            return {"type": "cylinder", "point": centre, "direction": axis, "radius": surface.Radius,
                    "axis_length": max(heights) - min(heights), "shape": shape}
        if isinstance(surface, (Part.Cone, Part.Toroid)):
            data = {"type": "cone" if isinstance(surface, Part.Cone) else "torus",
                    "point": App.Vector(surface.Apex if isinstance(surface, Part.Cone) else surface.Center),
                    "direction": App.Vector(surface.Axis).normalize(), "shape": shape}
            if isinstance(surface, Part.Toroid):
                data["radius"] = surface.MajorRadius
            return data
        return {"type": "face", "shape": shape}
    return {"type": "solid", "shape": shape}


def _middle(face):
    u0, u1, v0, v1 = face.ParameterRange
    return (u0 + u1) / 2, (v0 + v1) / 2


AXIAL = {"cylinder", "cone", "torus", "circle"}


# Cases -------------------------------------------------------------------
def single(entry):
    shape, kind = entry["shape"], entry["type"]
    if kind == "point":
        p = entry["point"]
        return {"kind": "point", "text": f"X {_fmt(p.x)} · Y {_fmt(p.y)} · Z {_fmt(p.z)} mm",
                "values": {"point_mm": _vector(p)}}
    if kind == "circle":
        radius = entry["radius"]
        return {"kind": "circle", "text": f"Ø {length(2 * radius)} · R {length(radius)}",
                "values": {"diameter_mm": 2 * radius, "radius_mm": radius, "length_mm": shape.Length,
                           "center_mm": _vector(entry["point"]), "axis": _vector(entry["direction"])}}
    if kind in {"line", "edge"}:
        return {"kind": "edge", "text": "Length " + length(shape.Length), "values": {"length_mm": shape.Length}}
    if kind == "plane":
        n = entry["normal"]
        return {"kind": "plane", "text": f"Area {_fmt(shape.Area)} mm² · Normal ({_fmt(n.x)}, {_fmt(n.y)}, {_fmt(n.z)})",
                "values": {"area_mm2": shape.Area, "normal": _vector(n)}}
    if kind == "cylinder":
        radius = entry["radius"]
        return {"kind": "cylinder",
                "text": f"Ø {length(2 * radius)} · R {length(radius)} · Axis length {length(entry['axis_length'])}",
                "values": {"diameter_mm": 2 * radius, "radius_mm": radius, "axis_length_mm": entry["axis_length"],
                           "area_mm2": shape.Area, "axis": _vector(entry["direction"])}}
    if shape.ShapeType == "Face":
        return {"kind": "face", "text": f"Area {_fmt(shape.Area)} mm²", "values": {"area_mm2": shape.Area}}
    box = shape.BoundBox
    volume = shape.Volume if shape.Solids else 0.0
    return {"kind": "body",
            "text": f"ΔX {_fmt(box.XLength)} · ΔY {_fmt(box.YLength)} · ΔZ {_fmt(box.ZLength)} mm · Volume {_fmt(volume)} mm³",
            "values": {"dx_mm": box.XLength, "dy_mm": box.YLength, "dz_mm": box.ZLength, "volume_mm3": volume}}


def _minimum(a, b):
    distance, pairs, _ = a.distToShape(b)
    return distance, pairs[0][0], pairs[0][1]


def point_to(point_entry, other, point_first=True):
    """Point to anything: minimum distance and the signed delta, first selection → second."""
    distance, near, far = _minimum(point_entry["shape"], other["shape"])
    delta = far - near if point_first else near - far
    kind = "distance" if other["type"] == "point" else "point_distance"
    label = "Distance" if other["type"] == "point" else "Minimum distance"
    return {"kind": kind, "text": f"{label} {length(distance)} · " + _delta_text(delta),
            "values": {"distance_mm": distance, **_delta_values(delta),
                       "closest_point_mm": _vector(far)}}


def planes(a, b):
    n1, n2 = a["normal"], b["normal"]
    if _parallel(n1, n2):
        signed = (b["point"] - a["point"]).dot(n1.normalize())
        shifted = b["shape"].copy()
        shifted.translate(n1.normalize() * -signed)
        try:
            overlap = a["shape"].common(shifted).Area > 1e-9
        except Exception:
            overlap = False
        return {"kind": "parallel_planes",
                "text": f"Parallel distance {length(signed)} · " + ("overlapping" if overlap else "no overlap in projection"),
                "values": {"distance_mm": signed, "overlap": overlap}}
    theta = _acute(n1, n2)
    distance, _, _ = _minimum(a["shape"], b["shape"])
    return {"kind": "plane_angle", "text": f"Angle {angle(theta)} · Minimum distance {length(distance)}",
            "values": {"angle_deg": theta, "distance_mm": distance}}


def _line_closest(p1, d1, p2, d2):
    """Closest points of two non-parallel lines."""
    w = p1 - p2
    a, b, c = d1.dot(d1), d1.dot(d2), d2.dot(d2)
    d, e = d1.dot(w), d2.dot(w)
    denominator = a * c - b * b
    s = (b * e - c * d) / denominator
    t = (a * e - b * d) / denominator
    return p1 + d1 * s, p2 + d2 * t


def axes(a, b):
    d1, d2 = a["direction"].normalize(), b["direction"].normalize()
    p1, p2 = a["point"], b["point"]
    diameters = [2 * entry["radius"] for entry in (a, b) if "radius" in entry]
    dia_text = (" · " + " · ".join("Ø " + length(value) for value in diameters)) if diameters else ""
    if _parallel(d1, d2):
        foot = p2 + d2 * (p1 - p2).dot(d2)
        delta = foot - p1
        radial = delta - d1 * delta.dot(d1)
        if radial.Length <= COAXIAL_TOLERANCE_MM:
            return {"kind": "coaxial", "text": "Coaxial" + dia_text, "values": {"coaxial": True, "diameters_mm": diameters}}
        return {"kind": "parallel_axes", "text": f"Axis distance {length(radial.Length)} · " + _delta_text(radial) + dia_text,
                "values": {"distance_mm": radial.Length, **_delta_values(radial), "diameters_mm": diameters}}
    theta = _acute(d1, d2)
    c1, c2 = _line_closest(p1, d1, p2, d2)
    return {"kind": "axis_angle", "text": f"Axis angle {angle(theta)} · Axis distance {length((c2 - c1).Length)}" + dia_text,
            "values": {"angle_deg": theta, "distance_mm": (c2 - c1).Length, "diameters_mm": diameters}}


def plane_axis(plane, axial):
    n, d = plane["normal"].normalize(), axial["direction"].normalize()
    tilt = 90.0 - _acute(n, d)  # angle between the axis and the plane
    if tilt <= ANGLE_TOLERANCE_DEG:
        distance = (axial["point"] - plane["point"]).dot(n)
        return {"kind": "axis_to_plane", "text": "Distance (axis to plane) " + length(abs(distance)),
                "values": {"distance_mm": abs(distance), "signed_distance_mm": distance}}
    return {"kind": "axis_plane_angle", "text": "Angle " + angle(tilt), "values": {"angle_deg": tilt}}


def lines(a, b):
    d1, d2 = a["direction"].normalize(), b["direction"].normalize()
    if _parallel(d1, d2):
        offset = b["point"] - a["point"]
        radial = offset - d1 * offset.dot(d1)
        return {"kind": "parallel_lines", "text": "Parallel distance " + length(radial.Length),
                "values": {"distance_mm": radial.Length}}
    theta = _acute(d1, d2)
    distance, _, _ = _minimum(a["shape"], b["shape"])
    return {"kind": "line_angle", "text": f"Angle {angle(theta)} · Minimum distance {length(distance)}",
            "values": {"angle_deg": theta, "distance_mm": distance}}


def pair(a, b):
    ta, tb = a["type"], b["type"]
    if ta == "point":
        return point_to(a, b)
    if tb == "point":
        return point_to(b, a, point_first=False)
    if ta == "plane" and tb == "plane":
        return planes(a, b)
    if ta in AXIAL and tb in AXIAL:
        return axes(a, b)
    if ta == "plane" and tb in AXIAL:
        return plane_axis(a, b)
    if tb == "plane" and ta in AXIAL:
        return plane_axis(b, a)
    if ta == "line" and tb == "line":
        return lines(a, b)
    distance, _, _ = _minimum(a["shape"], b["shape"])
    return {"kind": "minimum_distance", "text": "Minimum distance " + length(distance), "values": {"distance_mm": distance}}


def describe(shapes):
    """Measure world-frame shapes: nothing, one element, a pair, or more."""
    entries = [classify(shape) for shape in shapes]
    if not entries:
        return {"kind": "none", "text": "", "values": {}}
    if len(entries) == 1:
        return single(entries[0])
    result = pair(entries[0], entries[1])
    if len(entries) > 2:
        box = App.BoundBox()
        for entry in entries:
            box.add(entry["shape"].BoundBox)
        distance, _, _ = _minimum(entries[0]["shape"], entries[1]["shape"])
        result = {"kind": "selection", "text": f"Minimum distance {length(distance)} (first two) · "
                                               f"{len(entries)} selected · ΔX {_fmt(box.XLength)} · ΔY {_fmt(box.YLength)} · ΔZ {_fmt(box.ZLength)} mm",
                  "values": {"distance_mm": distance, "count": len(entries),
                             "bbox_mm": {"dx": box.XLength, "dy": box.YLength, "dz": box.ZLength}}}
    return result


def measure_references(doc, references):
    """The bridge's ``measure``: selectors or ``{"object", "subelement"}`` references → describe()."""
    from .core import OperationError
    from . import reference_tools, selectors
    if not isinstance(references, list) or not 1 <= len(references) <= 24:
        raise OperationError("invalid_argument", "references must list 1 to 24 selectors or {object, subelement} references",
                             fields=["references"])
    shapes = []
    for index, reference in enumerate(references):
        if reference_tools.is_selector(reference):
            rows = selectors.resolve(doc, reference_tools.selector_value(reference), shapes=True)
            unique = {(row["feature"], row["subelement"]): row for row in rows}
            if not unique:
                raise OperationError("missing_reference", "Reference %d matches nothing" % index, reference=index)
            if len(unique) > 1:
                raise OperationError("ambiguous_reference", "Reference %d matches %d elements" % (index, len(unique)),
                                     reference=index, matches=sorted("%s.%s" % key for key in unique))
            shapes.append(next(iter(unique.values()))["shape"])
            continue
        if (not isinstance(reference, dict) or not isinstance(reference.get("object"), str)
                or not isinstance(reference.get("subelement", ""), str)):
            raise OperationError("invalid_argument", "Each reference is a selector or {object, subelement}",
                                 fields=["references"], reference=index)
        obj = doc.getObject(reference["object"])
        try:
            shapes.append(element_shape(obj, reference.get("subelement", "")))
        except Exception as exc:
            raise OperationError("missing_reference", "Reference %d: %s" % (index, exc), reference=index) from None
    return describe(shapes)


def measure_selection(entries):
    """``[(object, subelement), ...]`` → describe() of their world-frame shapes."""
    return describe([element_shape(obj, sub) for obj, sub in entries])
