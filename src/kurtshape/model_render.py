"""Deterministic software renderer for Contract 3.2 ``render_view`` model images.

Productionised from the F2 render-probe prototype ``softrender.py``. Detached
OCCT shapes are drawn with a numpy z-buffer: whole-shape BRepMesh tessellation
through MeshPart (crack free, with an angular deflection; coarsened by doubling
tolerance and angle) read back per face with outward orientation and smooth
in-face normals, chunked front-to-back scanline rasterization with
hierarchical-z rejection, one-pass seam detection for exact BREP feature edges,
slope-aware image-space silhouettes, planar section caps per solid with
hatching, highlight overlays with per-highlight visibility and honest labels,
and status bands that keep the retained-geometry banner and the validity note
at every size the contract allows. Pillow writes deterministic PNGs. A job has
a wall-clock budget below the worker's time limit.

This module is pure: no OpenGL, Qt, GUI or document access and no KurtShape
import (in particular never ``kurtshape.core``). FreeCAD, Part and MeshPart are
imported lazily by the functions that handle shapes. The render worker child
calls :func:`render_job` on a :class:`Scene` (usually :meth:`Scene.from_capture`);
the owner-side service validates requests, resolves highlights and decides the
banners. Request limits (image size, view count, highlight count) belong to
that service; the triangle, raster and time limits below belong to the renderer.

Conventions (OPERATION_CONTRACT Contract 3.2, model images):

* Orthographic cameras. ``VIEWS`` maps each view to (direction the camera
  looks along, up). Front looks along +Y with +X right and +Z up; top looks
  along -Z with +Y up; right looks along -X with +Y right; iso looks along
  (-1, 1, -1) and shows the +X, -Y and +Z faces.
* A section removes the material on the +normal side. Named planes use
  FreeCAD's origin-plane normals (XY +Z, XZ -Y, YZ +X) and ``offset`` is
  measured along that normal, as ``create_plane`` does. The ``"section"`` view
  looks along -normal (from the removed side) with up +Z, or +Y when the normal
  is parallel to Z. The cut applies to every view of a job.
* Pixel coordinates are continuous output-image coordinates with (0, 0) at the
  top-left corner; pixel (i, j) covers [i, i+1) x [j, j+1). Each camera's
  ``pixel_from_world`` maps homogeneous world millimetres (x, y, z, 1) to them.
* Images show tessellated display meshes. They never establish geometric
  validity; every image says so in its caption.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import importlib.util
import itertools
import math
import os
from pathlib import Path
import sys
import time

import numpy as np
import PIL
from PIL import Image, ImageDraw, ImageFont, PngImagePlugin

RENDERER = "kurtshape-soft"
RENDERER_VERSION = 1

VIEWS = {
    "iso": ((-1.0, 1.0, -1.0), (0.0, 0.0, 1.0)),
    "front": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "back": ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
    "right": ((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "left": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "top": ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
    "bottom": ((0.0, 0.0, 1.0), (0.0, -1.0, 0.0)),
}
STANDARD_VIEWS = ("front", "back", "right", "left", "top", "bottom")
VIEW_NAMES = (*VIEWS, "section")
SECTION_PLANES = {"XY": (0.0, 0.0, 1.0), "XZ": (0.0, -1.0, 0.0), "YZ": (1.0, 0.0, 0.0)}
PARALLEL_COS = 0.999
LAYOUTS = ("separate", "sheet")
QUALITIES = ("standard", "draft")
FRAMES = ("included", "model", "highlights")
DEFAULT_SIZE = (1024, 768)
DEFAULT_SHEET_SIZE = (1536, 1152)

# Renderer-owned limits. A job may override them through ``limits`` (tests, or an owner
# that needs a tighter time budget).
DEFAULT_LIMITS = {
    "coarsen_triangles": 1_500_000,   # above this, coarsen the mesh (double tolerance and angle) ...
    "coarsen_steps": 3,               # ... at most this many times ...
    "max_triangles": 2_500_000,       # ... and refuse above this, caps and highlights included.
    "fragment_budget": 2_000_000,     # sum of triangle bounding-box pixels per raster chunk
    "chunk_triangles": 32_768,        # triangles per raster chunk (hierarchical-z granularity)
    "deadline_seconds": 18.0,         # wall-clock budget of render_job (worker limit 25 s); None = off
}
SHADE_CHUNK = 262_144
SPAN_EPS = 1e-6                       # px; scanline spans include pixel centres on an edge
SUPERSAMPLE_MAX_PIXELS = 1_100_000    # standard quality: 2x supersampling up to 1.1 MP per raster
TOLERANCE_PX = 0.6
TOLERANCE_MIN_DIAG = 1e-4
TOLERANCE_MAX_DIAG = 2e-3
# BRepMesh angular deflection (rad). The linear tolerance bounds the silhouette error; the
# angle only refines curved faces for shading. Part's tessellate() fixes it at 0.1 rad,
# which multiplies the triangles of curved faces about seven times (drill capture: 70148
# at 0.1 rad, 15576 at 0.25 rad, same 0.0625 mm tolerance) and makes linear coarsening
# almost ineffective. Coarsening doubles it up to OCCT's default 0.5 rad.
ANGULAR_DEFLECTION = 0.25
ANGULAR_DEFLECTION_MAX = 0.5
COARSEN_MIN_REDUCTION = 0.10          # a coarsening step that removes less stops the ladder

HEADER_PX = 30
FOOTER_PX = 24
MARGIN = 0.06
OVERLAY_BIAS_PX = 3.0                 # supersampled px: highlight faces and caps win over coplanar faces
CAP_TIE_PX = 0.02                     # coplanar caps of overlapping solids: earlier part (then solid) wins
HIGHLIGHT_TIE_PX = 0.02               # highlights sharing a face: the one with fewer faces is drawn on top
SILHOUETTE_JUMP_PX = 12.0
EDGE_MIN_PX = 0.3
EDGE_END_ON_DEGREES = 2.0
LABEL_MIN_VISIBLE_PX = 6
LABEL_OFFSETS = ((44, -34), (-44, -34), (44, 34), (-44, 34), (70, 0), (-70, 0))
HIGHLIGHT_FRAME_SCALE = 1.6
HIGHLIGHT_FRAME_PAD_MM = 1.0
GHOST_ALPHA = 0.6
GHOST_WIDTH_PX = 1.5
GHOST_DASH_PX = 5.0
VERTEX_RADIUS_PX = 4
SHEET_GAP_PX = 4
SHEET_FOOTER_PX = 22
LEGEND_ROW_PX = 16
PNG_COMPRESS_LEVEL = 6

BACKGROUND = (255, 255, 255)
BAND = (245, 246, 248)
SHEET_BACKGROUND = (200, 200, 205)
TEXT = (20, 24, 30)
MUTED_TEXT = (70, 70, 70)
EDGE_COLOR = (35, 38, 45)
SKETCH_COLOR = (25, 55, 160)
CAP_COLOR = (0.93, 0.80, 0.55)
DEFAULT_PART_COLOR = (0.78, 0.80, 0.84)
PART_PALETTE = ((0.62, 0.70, 0.82), (0.82, 0.72, 0.58), (0.66, 0.80, 0.64), (0.82, 0.64, 0.70),
                (0.72, 0.68, 0.84), (0.60, 0.78, 0.80))
HIGHLIGHT_COLORS = ((230, 110, 0), (0, 150, 210), (200, 30, 120), (40, 160, 60),
                    (150, 80, 220), (210, 170, 0), (0, 170, 160), (220, 50, 50))
CAPTION_NOTE = "display mesh, not a validity check"
RESPONSE_NOTE = ("Images show tessellated display meshes of the listed parts in the selector world frame. "
                 "They do not establish geometric validity; rely on build_status, validation, "
                 "geometry_check/check_geometry and result_report.")

BANNER_COLORS = {"red": (178, 34, 34), "amber": (176, 110, 0), "slate": (71, 85, 105), "gray": (110, 112, 118)}
# Precedence order (Contract 3.2 geometry status rules). Templates use str.format fields.
BANNERS = {
    "build_failed": ("RETAINED GEOMETRY \u00b7 BUILD FAILED", "red"),
    "needs_rebuild": ("RETAINED GEOMETRY \u00b7 NEEDS REBUILD", "amber"),
    "validation_failed": ("VALIDATION FAILED", "red"),
    "validation_pending": ("VALIDATION PENDING", "amber"),
    "check_invalid": ("BREPCHECK INVALID", "red"),
    "non_solid": ("NOT A SOLID: {count} PART{plural}", "amber"),
    "rolled_back": ("ROLLED BACK {index}/{length}", "slate"),
    "unmanaged": ("UNMANAGED FILE", "gray"),
}
BANNER_ORDER = tuple(BANNERS)

TAG_PART, TAG_CAP = -1, -2
_NO_TAG = -9
_NO_TRIANGLE = np.iinfo(np.int32).max
_COS_END_ON = math.cos(math.radians(EDGE_END_ON_DEGREES))
FONT_FILES = {False: "DejaVuSans.ttf", True: "DejaVuSans-Bold.ttf"}


class RenderError(Exception):
    """A deterministic render refusal with a wire error code and detail fields."""

    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_error(self):
        return {"code": self.code, "message": self.message, **self.details}


class Deadline:
    """Wall-clock budget of one job, checked between faces, parts, raster chunks and views.

    Calling it (optionally with the triangle count reached so far) raises
    ``render_too_large`` with reason ``triangles`` once the budget is spent: the
    budget is spent on meshing and rasterizing triangles, and the remedy is the
    same (fewer parts or views, a smaller image, draft quality). Details carry
    ``budget_seconds`` so clients can tell it from the count limit. ``seconds``
    None disables the check.
    """

    def __init__(self, seconds, began=None):
        self.seconds = None if seconds is None else float(seconds)
        self.began = time.perf_counter() if began is None else float(began)
        self.triangles = 0
        self.views = 1

    def __call__(self, triangles=None):
        if triangles is not None:
            self.triangles = max(self.triangles, int(triangles))
        if self.seconds is not None and time.perf_counter() - self.began > self.seconds:
            raise RenderError("render_too_large",
                              f"The render did not finish within its {self.seconds:g} s budget "
                              f"({self.triangles} triangles, {self.views} view(s)). Render fewer parts or views, "
                              "a smaller image or draft quality.",
                              reason="triangles", triangles=self.triangles, views=self.views,
                              budget_seconds=self.seconds)


def _no_deadline(triangles=None):
    return None


# ---------------------------------------------------------------- fonts

@lru_cache(maxsize=1)
def font_dir():
    """Folder holding the bundled DejaVu fonts (matplotlib's mpl-data), or None."""
    candidates = []
    try:
        spec = importlib.util.find_spec("matplotlib")  # locates the package without importing it
        if spec is not None and spec.origin:
            candidates.append(Path(spec.origin).parent / "mpl-data" / "fonts" / "ttf")
    except (ImportError, ValueError):
        pass
    candidates.append(Path(sys.executable).resolve().parent / "Lib" / "site-packages" / "matplotlib"
                      / "mpl-data" / "fonts" / "ttf")
    for folder in candidates:
        if all((folder / name).is_file() for name in FONT_FILES.values()):
            return folder
    return None


@lru_cache(maxsize=None)
def _font(size, bold=False):
    folder = font_dir()
    if folder is not None:
        try:
            return ImageFont.truetype(str(folder / FONT_FILES[bold]), size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


@lru_cache(maxsize=1)
def font_id():
    """Stable identity of the fonts in use; part of the owner's image cache key."""
    folder = font_dir()
    if folder is None:
        return "pil-default-" + PIL.__version__
    digest = hashlib.sha256()
    for bold in (False, True):
        digest.update((folder / FONT_FILES[bold]).read_bytes())
    return "dejavu-sans-" + digest.hexdigest()[:16]


def engine():
    """Renderer identity for responses and capabilities (no FreeCAD import)."""
    return {"renderer": RENDERER, "renderer_version": RENDERER_VERSION, "font": font_id(),
            "numpy": np.__version__, "pillow": PIL.__version__}


# ---------------------------------------------------------------- small helpers

def _unit(v):
    v = np.asarray(v, dtype=float)
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def _vector3(value, name):
    try:
        v = np.asarray(value, dtype=float).reshape(3)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be three numbers") from None
    if not np.all(np.isfinite(v)):
        raise ValueError(f"{name} must be finite")
    return v


def _plain(value, digits=9):
    """JSON-safe copy: numpy scalars/arrays become Python floats rounded to ``digits``."""
    if isinstance(value, dict):
        return {k: _plain(v, digits) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v, digits) for v in value]
    if isinstance(value, np.ndarray):
        return _plain(value.tolist(), digits)
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        value = float(value)
        return round(value, digits) + 0.0 if math.isfinite(value) else None
    return value


def highlight_color(index):
    return HIGHLIGHT_COLORS[index % len(HIGHLIGHT_COLORS)]


# ---------------------------------------------------------------- cameras and sections

def camera_basis(direction, up=None):
    """Return (d, u, r): view direction, screen up and screen right (r = d x u)."""
    d = _vector3(direction, "view direction")
    length = float(np.linalg.norm(d))
    if length < 1e-12:
        raise ValueError("view direction must be nonzero")
    d = d / length
    if up is None:
        up = (0.0, 1.0, 0.0) if abs(d[2]) >= PARALLEL_COS else (0.0, 0.0, 1.0)
    u = _vector3(up, "view up")
    if float(np.linalg.norm(u)) < 1e-12:
        raise ValueError("view up must be nonzero")
    if abs(float(np.dot(_unit(u), d))) >= PARALLEL_COS:
        raise ValueError("view up must not be parallel to the view direction")
    u = _unit(u - np.dot(u, d) * d)
    return d, u, np.cross(d, u)


def section_from_plane(plane, offset=0.0):
    """Named section plane with FreeCAD's origin-plane normal; offset along that normal."""
    key = str(plane).upper()
    if key not in SECTION_PLANES:
        raise ValueError("section plane must be one of " + ", ".join(SECTION_PLANES))
    normal = SECTION_PLANES[key]
    offset = float(offset)
    if not math.isfinite(offset):
        raise ValueError("section offset must be finite")
    return {"origin": [offset * c + 0.0 for c in normal], "normal": list(normal)}


def normalize_section(section):
    """``{"origin", "normal"}`` or ``{"plane", "offset"}`` -> {"origin": array, "normal": unit array}."""
    if section is None:
        return None
    if isinstance(section, dict) and "plane" in section:
        section = section_from_plane(section["plane"], section.get("offset", 0.0))
    origin = _vector3(section["origin"], "section origin")
    normal = _vector3(section["normal"], "section normal")
    length = float(np.linalg.norm(normal))
    if length < 1e-12:
        raise ValueError("section normal must be nonzero")
    return {"origin": origin, "normal": normal / length}


def view_camera(view, section=None):
    """Return (name, d, u, r) for a view name or ``{"direction", "up"?, "name"?}``."""
    if isinstance(view, str):
        if view == "section":
            sec = normalize_section(section)
            if sec is None:
                raise ValueError('view "section" needs a section')
            n = sec["normal"]
            up = (0.0, 1.0, 0.0) if abs(n[2]) >= PARALLEL_COS else (0.0, 0.0, 1.0)
            return ("section", *camera_basis(-n, up))
        if view not in VIEWS:
            raise ValueError("unknown view " + repr(view))
        return (view, *camera_basis(*VIEWS[view]))
    if not isinstance(view, dict) or "direction" not in view:
        raise ValueError("a custom view needs a direction")
    return (str(view.get("name") or "custom"), *camera_basis(view["direction"], view.get("up")))


def _clip_box_points(lo, hi, section):
    """Vertices of the box [lo, hi] intersected with the kept half-space of ``section``."""
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    if section is None:
        return corners
    s = (corners - section["origin"]) @ section["normal"]
    points = [corners[s <= 0]]
    for i in range(8):
        for j in range(i + 1, 8):
            if bin(i ^ j).count("1") == 1 and (s[i] < 0 < s[j] or s[j] < 0 < s[i]):
                t = s[i] / (s[i] - s[j])
                points.append((corners[i] + t * (corners[j] - corners[i]))[None, :])
    return np.concatenate(points)


# ---------------------------------------------------------------- banners

def banner(kind, **fields):
    """Banner dict {"kind", "text", "color"} for one of ``BANNERS``."""
    if kind not in BANNERS:
        raise ValueError("unknown banner " + repr(kind))
    template, color = BANNERS[kind]
    if kind == "non_solid":
        count = int(fields.get("count", 1))
        fields = dict(fields, count=count, plural="" if count == 1 else "S")
    return {"kind": kind, "text": template.format(**fields), "color": color}


def normalize_banners(banners, non_solid=0):
    """Order banners by precedence; add NOT A SOLID when drawn parts are not solids."""
    rows, kinds = [], set()
    for item in banners or ():
        if isinstance(item, str):
            item = banner(item)
        elif "kind" in item and item["kind"] in BANNERS and "text" not in item:
            item = banner(item["kind"], **{k: v for k, v in item.items() if k != "kind"})
        else:
            if "text" not in item:
                raise ValueError("a banner needs a known kind or a text")
            item = {"kind": item.get("kind", "custom"), "text": str(item["text"]),
                    "color": item.get("color", "gray")}
        if item["kind"] in kinds and item["kind"] != "custom":
            continue
        kinds.add(item["kind"])
        rows.append(item)
    if non_solid and "non_solid" not in kinds:
        rows.append(banner("non_solid", count=non_solid))
    rank = {kind: i for i, kind in enumerate(BANNER_ORDER)}
    order = sorted(range(len(rows)), key=lambda i: (rank.get(rows[i]["kind"], len(rank)), i))
    return [rows[i] for i in order]


def _banner_rgb(color):
    if isinstance(color, (tuple, list)):
        return tuple(int(c) for c in color[:3])
    return BANNER_COLORS.get(color, BANNER_COLORS["gray"])


# ---------------------------------------------------------------- scene

class ScenePart:
    """One detached result shape in world millimetres."""

    def __init__(self, shape, name="", id=None, color=None, solid=None):
        self.shape = shape
        self.name = str(name or "")
        self.id = id
        self.color = tuple(float(c) for c in (color if color is not None else DEFAULT_PART_COLOR))[:3]
        self.solid = bool(shape.Solids) if solid is None else bool(solid)

    @property
    def key(self):
        """Report key: the part id, else the name, else None (callers then use the index)."""
        return self.id if self.id is not None else (self.name or None)


class SceneHighlight:
    """A labelled highlight: ``shapes`` are drawn in place; ``ghosts`` are not in the shown
    geometry (sketch, filtered part or history) and are drawn as dashed outlines only."""

    def __init__(self, label, shapes=(), note="", ghosts=(), two_sided=False):
        self.label = str(label)
        self.note = str(note or "")
        self.shapes = list(shapes)
        self.ghosts = list(ghosts)
        self.two_sided = bool(two_sided)


class Scene:
    """Everything a job draws. ``sketches`` are wire shapes drawn as dark-blue lines;
    ``banners`` are kinds (or banner dicts) in any order; ``model_bounds`` is the
    [[xmin, ymin, zmin], [xmax, ymax, zmax]] box used by ``frame:"model"``."""

    def __init__(self, parts=(), highlights=(), sketches=(), title="", revision="", banners=(),
                 model_bounds=None):
        self.parts = [p if isinstance(p, ScenePart) else ScenePart(**p) for p in parts]
        self.highlights = [h if isinstance(h, SceneHighlight) else SceneHighlight(**h) for h in highlights]
        self.sketches = list(sketches)
        self.title = str(title or "")
        self.revision = str(revision or "")
        self.banners = list(banners or ())
        self.model_bounds = None if model_bounds is None else [list(map(float, model_bounds[0])),
                                                               list(map(float, model_bounds[1]))]

    @classmethod
    def from_capture(cls, folder, document):
        """Load a capture folder described by a ``scene.json`` document::

            {"title": str, "revision": str, "banners": [...], "model_bounds": [[...], [...]] | null,
             "parts": [{"brep": "part-0.brep", "name": str, "id": str, "color": [r, g, b], "solid": bool}],
             "sketches": ["sketches.brep", ...],
             "highlights": [{"label": "A", "note": str, "rendered": "hl-0-r.brep" | null,
                             "ghost": "hl-0-g.brep" | null, "two_sided": bool}]}

        File names must name files directly inside ``folder``. Compounds are split
        into their sub-shapes. The caller verifies file digests before loading.
        """
        folder = Path(folder).resolve()

        def load(name):
            path = (folder / str(name)).resolve()
            if path.parent != folder:
                raise ValueError("capture file outside the capture folder: " + str(name))
            import Part
            shape = Part.Shape()
            shape.importBrep(str(path))
            return shape

        def split(name):
            if not name:
                return []
            shape = load(name)
            if shape.isNull():
                return []
            return list(shape.SubShapes) if shape.ShapeType == "Compound" else [shape]

        parts = [ScenePart(load(p["brep"]), name=p.get("name", ""), id=p.get("id"), color=p.get("color"),
                           solid=p.get("solid")) for p in document.get("parts", [])]
        sketches = [shape for name in document.get("sketches") or () for shape in split(name)]
        highlights = [SceneHighlight(h.get("label", chr(65 + i)), split(h.get("rendered")), note=h.get("note", ""),
                                     ghosts=split(h.get("ghost")), two_sided=h.get("two_sided", False))
                      for i, h in enumerate(document.get("highlights", []))]
        return cls(parts, highlights, sketches, title=document.get("title", ""),
                   revision=document.get("revision", ""), banners=document.get("banners", ()),
                   model_bounds=document.get("model_bounds"))


def _decompose(shapes):
    """Split shapes into (faces, edges, vertices) by their own dimension."""
    faces, edges, vertices = [], [], []
    stack = list(reversed(list(shapes)))
    while stack:
        shape = stack.pop()
        if shape is None or shape.isNull():
            continue
        kind = shape.ShapeType
        if kind == "Compound":
            stack.extend(reversed(list(shape.SubShapes)))
        elif kind == "Face":
            faces.append(shape)
        elif kind == "Edge":
            edges.append(shape)
        elif kind == "Vertex":
            vertices.append(shape)
        elif shape.Faces:
            faces.extend(shape.Faces)
        elif shape.Edges:
            edges.extend(shape.Edges)
        else:
            vertices.extend(shape.Vertexes)
    return faces, edges, vertices


def _scene_bounds(scene):
    boxes = [p.shape.BoundBox for p in scene.parts if not p.shape.isNull()]
    boxes += [s.BoundBox for s in scene.sketches if not s.isNull()]
    boxes = [b for b in boxes if b.isValid()]
    if not boxes:
        return None
    lo = np.array([min(b.XMin for b in boxes), min(b.YMin for b in boxes), min(b.ZMin for b in boxes)])
    hi = np.array([max(b.XMax for b in boxes), max(b.YMax for b in boxes), max(b.ZMax for b in boxes)])
    return lo, hi


def _highlight_bounds(scene):
    boxes = [s.BoundBox for h in scene.highlights for s in h.shapes if not s.isNull()]
    boxes = [b for b in boxes if b.isValid()]
    if not boxes:
        return None
    lo = np.array([min(b.XMin for b in boxes), min(b.YMin for b in boxes), min(b.ZMin for b in boxes)])
    hi = np.array([max(b.XMax for b in boxes), max(b.YMax for b in boxes), max(b.ZMax for b in boxes)])
    return lo, hi


def _expanded_box(lo, hi):
    center, half = (lo + hi) / 2, (hi - lo) / 2 * HIGHLIGHT_FRAME_SCALE + HIGHLIGHT_FRAME_PAD_MM
    return center - half, center + half


# ---------------------------------------------------------------- tessellation

class FaceMesh:
    __slots__ = ("points", "triangles", "normals", "facet_normals", "oriented")

    def __init__(self, points, triangles, normals, facet_normals, oriented):
        self.points, self.triangles, self.normals = points, triangles, normals
        self.facet_normals, self.oriented = facet_normals, oriented


def face_mesh(face, tolerance):
    """Triangles of one face, oriented outward by one exact normal sample.

    Returns None for faces without triangles. ``oriented`` is False when the
    sample failed; such faces must never be back-face culled. Vertex normals
    are smooth within the face only.
    """
    points, tris = face.tessellate(tolerance)
    if not tris:
        return None
    P = np.fromiter(itertools.chain.from_iterable(points), float, 3 * len(points)).reshape(-1, 3)
    T = np.fromiter(itertools.chain.from_iterable(tris), np.int64, 3 * len(tris)).reshape(-1, 3)
    a, b, c = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    tn = np.cross(b - a, c - a)
    oriented = False
    try:
        import FreeCAD as App
        k = int(np.argmax(np.einsum("ij,ij->i", tn, tn)))
        center = (a[k] + b[k] + c[k]) / 3
        u, v = face.Surface.parameter(App.Vector(*center))
        n = face.normalAt(u, v)
        if float(np.dot(tn[k], (n.x, n.y, n.z))) < 0:
            T = T[:, [0, 2, 1]]
            tn = -tn
        oriented = True
    except Exception:  # noqa: BLE001 - an unknown orientation only disables culling
        pass
    vn = np.empty_like(P)
    flat = T.ravel()
    for j in range(3):
        vn[:, j] = np.bincount(flat, weights=np.repeat(tn[:, j], 3), minlength=len(P))
    lengths = np.linalg.norm(vn, axis=1, keepdims=True)
    vn = np.divide(vn, lengths, out=np.zeros_like(vn), where=lengths > 0)
    tl = np.linalg.norm(tn, axis=1, keepdims=True)
    fn = np.divide(tn, tl, out=np.zeros_like(tn), where=tl > 0)
    return FaceMesh(P, T, vn, fn, oriented)


def mesh_shape(shape, tolerance, angular=ANGULAR_DEFLECTION):
    """Mesh ``shape`` in place and return its triangle count.

    BRepMesh through MeshPart, with linear deflection ``tolerance`` (mm) and
    angular deflection ``angular`` (rad). Whole-shape meshing keeps shared edges
    consistent (no cracks), and the triangulation stays on the faces, so
    :func:`face_mesh` reads it back without meshing again. The count comes from
    the C++ mesh; no Python point or facet lists are built. Without MeshPart,
    Part's own tessellation is used (0.1 rad: finer and slower).
    """
    if shape.isNull() or not shape.countElement("Face"):
        return 0
    try:
        import MeshPart
    except ImportError:  # pragma: no cover - MeshPart ships with every FreeCAD build
        return len(shape.tessellate(float(tolerance))[1])
    mesh = MeshPart.meshFromShape(Shape=shape, LinearDeflection=float(tolerance), AngularDeflection=float(angular),
                                  Relative=False)
    return int(mesh.CountFacets)


def _tessellate_parts(scene, tolerance, limits, deadline=_no_deadline):
    """Mesh fresh copies of every part and coarsen while over the coarsen limit.

    Copies drop any triangulation stored in the capture BREP. Each coarsening step
    doubles the linear tolerance and the angular deflection (up to
    ANGULAR_DEFLECTION_MAX) and meshes fresh copies. The ladder stops when the
    count is at most ``coarsen_triangles``, after ``coarsen_steps`` steps, or when
    a step removes less than COARSEN_MIN_REDUCTION of the triangles (more steps
    would not pay); the smallest mesh is kept. Above ``max_triangles`` ->
    render_too_large{reason: triangles}. Returns (meshed copies, tolerance,
    angular deflection, coarsen steps, triangles, triangle count per step).
    """
    lin, ang = float(tolerance), ANGULAR_DEFLECTION
    best, previous, ladder = None, None, []
    for step in range(int(limits["coarsen_steps"]) + 1):
        meshed, total = [], 0
        for part in scene.parts:
            deadline(total)
            shape = part.shape.copy()
            total += mesh_shape(shape, lin, ang)
            meshed.append(shape)
        ladder.append(total)
        if best is None or total < best[1]:
            best = (meshed, total, lin, ang, step)
        del meshed
        if best[1] <= limits["coarsen_triangles"]:
            break
        if previous is not None and total > previous * (1 - COARSEN_MIN_REDUCTION):
            break
        previous = total
        lin, ang = lin * 2.0, min(ang * 2.0, ANGULAR_DEFLECTION_MAX)
    meshed, total, lin, ang, step = best
    if total > limits["max_triangles"]:
        raise RenderError("render_too_large",
                          f"The display mesh needs {total} triangles, more than {limits['max_triangles']}, "
                          f"even at a {lin:g} mm tolerance.",
                          reason="triangles", triangles=total, limit=limits["max_triangles"], tolerance_mm=lin)
    return meshed, lin, ang, step, total, ladder


def _solid_faces(shape, solid):
    """None when every face bounds a solid; otherwise the hash set of faces that do."""
    if not solid:
        return set()
    if shape.ShapeType in ("Solid", "CompSolid"):
        return None
    return {face.hashCode() for body in shape.Solids for face in body.Faces}


def feature_edges(shape, solid_faces=None, solid=True):
    """Edges drawn as feature lines, by one pass over face/edge incidences.

    In a solid, an edge used by exactly one face is a seam (cylinder, cone,
    torus, sphere) and is skipped. Faces outside solids (``solid_faces``) are
    open: their one-face edges are boundaries and are drawn, except true seams.
    """
    entries, order = {}, []
    for face in shape.Faces:
        face_solid = solid and (solid_faces is None or face.hashCode() in solid_faces)
        for edge in face.Edges:
            key = edge.hashCode()
            entry = entries.get(key)
            if entry is None:
                entry = entries[key] = [edge, 0, face_solid, face]
                order.append(key)
            entry[1] += 1
    drawn = []
    for key in order:
        edge, count, face_solid, face = entries[key]
        if getattr(edge, "Degenerated", False):
            continue
        if count == 1:
            if face_solid:
                continue
            try:
                if edge.isSeam(face):
                    continue
            except Exception:  # noqa: BLE001 - keep the boundary when the seam test fails
                pass
        drawn.append(edge)
    return drawn


def _discretize(edge, deflection):
    try:
        if getattr(edge, "Degenerated", False):
            return None
        points = edge.discretize(Deflection=max(float(deflection), 1e-9))
    except Exception:  # noqa: BLE001 - an undiscretizable edge is simply not drawn
        return None
    if len(points) < 2:
        return None
    return np.fromiter(itertools.chain.from_iterable(points), float, 3 * len(points)).reshape(-1, 3)


def _part_colors(parts):
    default = tuple(round(c, 2) for c in DEFAULT_PART_COLOR)
    defaults = sum(1 for p in parts if tuple(round(c, 2) for c in p.color) == default)
    colors = []
    for i, part in enumerate(parts):
        color = part.color
        if defaults > 1 and tuple(round(c, 2) for c in color) == default:
            color = PART_PALETTE[i % len(PART_PALETTE)]
        colors.append(np.array(color, dtype=np.float32))
    return colors


class Prepared:
    """A job's tessellated scene at one tolerance (and one section variant).

    Shared by every view of the job. Triangles carry a tag: ``TAG_PART`` for
    part faces, ``TAG_CAP`` for section caps and the highlight index (>= 0) for
    rendered highlight faces. Caps are built per solid; ``tri_cap`` holds each
    cap triangle's cap group (one per sliced solid, in part then solid order) and
    ``cap_groups`` maps a group to its part index. Every triangle (caps and
    highlights included) counts toward ``max_triangles``. ``deadline`` (a
    :class:`Deadline`) is checked between faces.
    """

    def __init__(self, scene, tolerance, section=None, *, limits=None, phases=None, deadline=None):
        import FreeCAD as App
        import Part
        lim = dict(DEFAULT_LIMITS, **(limits or {}))
        phases = {} if phases is None else phases
        check = _no_deadline if deadline is None else deadline
        self.scene = scene
        self.section = normalize_section(section)
        self.limits = lim
        self.requested_tolerance = float(tolerance)
        began = time.perf_counter()
        (meshed, self.tolerance, self.angular_deflection, self.coarsen_steps, _,
         self.coarsen_ladder) = _tessellate_parts(scene, tolerance, lim, check)
        self.coarsened = self.coarsen_steps > 0
        tol, ang = self.tolerance, self.angular_deflection
        self.part_colors = _part_colors(scene.parts)
        V, N, FN, T, tpart, ttag, tcull, trgb, tcap, vtag, vpart, vcap = ([] for _ in range(12))
        count, total = 0, 0

        def add(mesh, part_index, tag, cull, rgb, group=-1):
            nonlocal count, total
            n = len(mesh.triangles)
            V.append(mesh.points)
            N.append(mesh.normals.astype(np.float32))
            FN.append(mesh.facet_normals.astype(np.float32))
            T.append((mesh.triangles + count).astype(np.int32))
            tpart.append(np.full(n, part_index, np.int32))
            ttag.append(np.full(n, tag, np.int32))
            tcull.append(np.full(n, bool(cull)))
            trgb.append(np.tile(np.asarray(rgb, np.float32), (n, 1)))
            tcap.append(np.full(n, group, np.int32))
            vtag.append(np.full(len(mesh.points), tag, np.int32))
            vpart.append(np.full(len(mesh.points), part_index, np.int32))
            vcap.append(np.full(len(mesh.points), group, np.int32))
            count += len(mesh.points)
            total += n
            check(total)

        # Part by part: read the faces' triangles, then the feature edges, then release the
        # meshed copy (its triangulation is no longer needed).
        self.part_info, self.edges, seams_ms = [], [], 0.0
        for pi, part in enumerate(scene.parts):
            shape, meshed[pi] = meshed[pi], None
            solid_faces = _solid_faces(shape, part.solid)
            faces = shape.Faces if not shape.isNull() else []
            triangles = 0
            for face in faces:
                mesh = face_mesh(face, tol)
                if mesh is None:
                    continue
                face_solid = part.solid and (solid_faces is None or face.hashCode() in solid_faces)
                add(mesh, pi, TAG_PART, mesh.oriented and face_solid, self.part_colors[pi])
                triangles += len(mesh.triangles)
            self.part_info.append({"index": pi, "id": part.id, "faces": len(faces), "triangles": triangles,
                                   "solid": part.solid})
            started = time.perf_counter()
            if not shape.isNull():
                for edge in feature_edges(shape, solid_faces, part.solid):
                    points = _discretize(edge, tol * 0.5)
                    if points is not None:
                        self.edges.append(points)
            seams_ms += (time.perf_counter() - started) * 1000
            del shape, faces, solid_faces
        del meshed
        phases["tessellate"] = phases.get("tessellate", 0.0) + (time.perf_counter() - began) * 1000 - seams_ms

        began = time.perf_counter() - seams_ms / 1000
        self.sketch_polylines = []
        for sketch in scene.sketches:
            for edge in ([] if sketch.isNull() else sketch.Edges):
                points = _discretize(edge, tol * 0.5)
                if points is not None:
                    self.sketch_polylines.append(points)
        phases["seams"] = phases.get("seams", 0.0) + (time.perf_counter() - began) * 1000

        began = time.perf_counter()
        self.cap_faces, self.cap_failures, self.cap_skipped, self.cap_groups = 0, [], [], []
        if self.section is not None:
            n, o = self.section["normal"], self.section["origin"]
            for pi, part in enumerate(scene.parts):
                shape = part.shape
                if shape.isNull() or not shape.countElement("Face"):
                    continue
                if not part.solid:
                    self.cap_skipped.append(part.key if part.key is not None else pi)
                    continue
                # One cap per solid: slicing a compound of overlapping solids at once
                # nests one solid's section inside another's as a false hole.
                solids = [shape] if shape.ShapeType == "Solid" else list(shape.Solids)
                failed = False
                for solid in solids:
                    check(total)
                    try:
                        wires = solid.slice(App.Vector(*n), float(np.dot(o, n)))
                    except Exception:  # noqa: BLE001 - reported as a cap failure
                        failed = True
                        continue
                    closed = [w for w in wires if w.isClosed()]
                    failed = failed or len(closed) != len(wires)
                    if not closed:
                        continue
                    try:
                        cap = Part.makeFace(closed, "Part::FaceMakerBullseye")
                        mesh_shape(cap, tol, ang)
                        group, drawn = len(self.cap_groups), 0
                        for face in cap.Faces:
                            mesh = face_mesh(face, tol)
                            if mesh is not None:
                                add(mesh, pi, TAG_CAP, False, CAP_COLOR, group)
                                self.cap_faces += 1
                                drawn += 1
                        if drawn:
                            self.cap_groups.append(pi)
                    except RenderError:
                        raise
                    except Exception:  # noqa: BLE001 - reported as a cap failure
                        failed = True
                if failed:
                    self.cap_failures.append(part.key if part.key is not None else pi)
        phases["caps"] = phases.get("caps", 0.0) + (time.perf_counter() - began) * 1000

        began = time.perf_counter()
        self.highlights = []
        for hi, item in enumerate(scene.highlights):
            entry = {"faces": 0, "edges": [], "points": [], "ghost_edges": [], "ghost_points": [],
                     "reference": None, "ghost_reference": None}
            faces, edges, vertices = _decompose(item.shapes)
            color = np.array(highlight_color(hi), np.float32) / 255
            if faces:
                copies = Part.makeCompound([face.copy() for face in faces])
                mesh_shape(copies, tol, ang)
                for face in copies.Faces:
                    mesh = face_mesh(face, tol)
                    if mesh is not None:
                        add(mesh, -1, hi, mesh.oriented and not item.two_sided, color)
                        entry["faces"] += 1
            for edge in edges:
                points = _discretize(edge, tol * 0.5)
                if points is not None:
                    entry["edges"].append(points)
            entry["points"] = [np.array([v.Point.x, v.Point.y, v.Point.z]) for v in vertices]
            gfaces, gedges, gvertices = _decompose(item.ghosts)
            for face in gfaces:
                for edge in face.Edges:
                    try:
                        if edge.isSeam(face):
                            continue
                    except Exception:  # noqa: BLE001
                        pass
                    gedges.append(edge)
            for edge in gedges:
                points = _discretize(edge, tol * 0.5)
                if points is not None:
                    entry["ghost_edges"].append(points)
            entry["ghost_points"] = [np.array([v.Point.x, v.Point.y, v.Point.z]) for v in gvertices]
            entry["rendered"] = bool(entry["faces"] or entry["edges"] or entry["points"])
            entry["ghost"] = bool(entry["ghost_edges"] or entry["ghost_points"])
            for key, shapes in (("reference", item.shapes), ("ghost_reference", item.ghosts)):
                boxes = [s.BoundBox for s in shapes if not s.isNull() and s.BoundBox.isValid()]
                if boxes:
                    entry[key] = np.array([(min(b.XMin for b in boxes) + max(b.XMax for b in boxes)) / 2,
                                           (min(b.YMin for b in boxes) + max(b.YMax for b in boxes)) / 2,
                                           (min(b.ZMin for b in boxes) + max(b.ZMax for b in boxes)) / 2])
            self.highlights.append(entry)
        # Highlights sharing a face: the one with fewer rendered faces (the more specific
        # one) is drawn on top, the later one on a tie. highlight_tie[i] is i's depth step.
        order = sorted(range(len(self.highlights)), key=lambda i: (-self.highlights[i]["faces"], i))
        self.highlight_tie = np.zeros(len(self.highlights), np.float64)
        for rank, i in enumerate(order):
            self.highlight_tie[i] = rank + 1
        phases["highlights"] = phases.get("highlights", 0.0) + (time.perf_counter() - began) * 1000

        def cat(chunks, shape, dtype):  # one array at a time, freeing its pieces (lower peak)
            joined = np.concatenate(chunks) if chunks else np.zeros(shape, dtype)
            chunks.clear()
            return joined

        self.V = cat(V, (0, 3), float)
        self.N = cat(N, (0, 3), np.float32)
        self.FN = cat(FN, (0, 3), np.float32)
        self.T = cat(T, (0, 3), np.int32)
        self.tri_part = cat(tpart, (0,), np.int32)
        self.tri_tag = cat(ttag, (0,), np.int32)
        self.tri_cull = cat(tcull, (0,), bool)
        self.tri_rgb = cat(trgb, (0, 3), np.float32)
        self.tri_cap = cat(tcap, (0,), np.int32)
        self.vtag = cat(vtag, (0,), np.int32)
        self.vpart = cat(vpart, (0,), np.int32)
        self.vcap = cat(vcap, (0,), np.int32)
        if self.section is not None and self.cap_failures:
            self.tri_cull[:] = False  # the interior may show through a missing cap: keep back faces
        # Silhouette owners: part faces 4 * part, highlight faces -4, each cap group its
        # own id (>= 4 * parts); render() gives the background -1.
        self.tri_owner = np.where(self.tri_tag == TAG_CAP, 4 * len(scene.parts) + self.tri_cap,
                                  self.tri_part * 4).astype(np.int32)
        self.triangles = int(sum(p["triangles"] for p in self.part_info))
        self.cap_triangles = int((self.tri_tag == TAG_CAP).sum())
        self.highlight_triangles = int((self.tri_tag >= 0).sum())
        if len(self.T) > lim["max_triangles"]:
            raise RenderError("render_too_large",
                              f"The display mesh needs {len(self.T)} triangles with section caps and highlights, "
                              f"more than {lim['max_triangles']}.",
                              reason="triangles", triangles=int(len(self.T)), limit=lim["max_triangles"],
                              tolerance_mm=tol)
        clouds = [self.V] + self.sketch_polylines + self.edges
        clouds += [np.asarray(e["points"]).reshape(-1, 3) for e in self.highlights]
        clouds += [p for e in self.highlights for p in e["edges"]]
        clouds = [c for c in clouds if len(c)]
        if clouds:  # per-cloud extremes: no concatenated copy of every vertex
            self.bounds = (np.min([c.min(0) for c in clouds], axis=0), np.max([c.max(0) for c in clouds], axis=0))
            self.diag = max(float(np.linalg.norm(self.bounds[1] - self.bounds[0])), 1e-6)
        else:
            self.bounds, self.diag = None, 1.0
        self.non_solid = [p.key if p.key is not None else i for i, p in enumerate(scene.parts)
                          if not p.solid and not p.shape.isNull() and p.shape.countElement("Face")]

    def kept(self, points):
        if self.section is None or len(points) == 0:
            return np.ones(len(points), bool)
        return (points - self.section["origin"]) @ self.section["normal"] <= 1e-7 * self.diag


# ---------------------------------------------------------------- rasterization

def _fragments(xs, ys, x0, x1, y0, y1, area, idx, PW):
    """Scanline spans of triangles ``idx``: (padded pixel index, triangle, x, y) per fragment."""
    rows = y1[idx] - y0[idx] + 1
    tri_row = np.repeat(idx, rows)
    starts = np.repeat(np.cumsum(rows) - rows, rows)
    y = y0[tri_row] + (np.arange(len(tri_row)) - starts)
    yc = y + 0.5
    sign = -np.sign(area[tri_row])
    lo = x0[tri_row].astype(float)
    hi = x1[tri_row].astype(float)
    for i, j in ((0, 1), (1, 2), (2, 0)):
        xi, yi, xj, yj = xs[tri_row, i], ys[tri_row, i], xs[tri_row, j], ys[tri_row, j]
        A = (yj - yi) * sign
        B = (-xi * (yj - yi) - (yc - yi) * (xj - xi)) * sign
        with np.errstate(divide="ignore", invalid="ignore"):
            root = -B / A
        pos, neg = A > 1e-15, A < -1e-15
        # inclusive by SPAN_EPS: a pixel centre on a shared edge is covered by both
        # triangles (the z-test picks one) instead of rounding out of both (cracks)
        lo = np.where(pos, np.maximum(lo, np.ceil(root - 0.5 - SPAN_EPS)), lo)
        hi = np.where(neg, np.minimum(hi, np.floor(root - 0.5 + SPAN_EPS)), hi)
        hi = np.where(~(pos | neg) & (B < -SPAN_EPS), lo - 1, hi)
    lo, hi = lo.astype(np.int64), hi.astype(np.int64)
    count = np.maximum(hi - lo + 1, 0)
    keep = count > 0
    tri_row, y, lo, count = tri_row[keep], y[keep], lo[keep], count[keep]
    ftri = np.repeat(tri_row, count)
    fstart = np.repeat(np.cumsum(count) - count, count)
    fx = np.repeat(lo, count) + (np.arange(len(ftri)) - fstart)
    fy = np.repeat(y, count)
    return fy * PW + fx, ftri, fx, fy


def _plane(values, xs, ys, area):
    """Per-triangle affine screen-space interpolation coefficients (c, gx, gy)."""
    ax, ay = xs[:, 0], ys[:, 0]
    e1x, e1y, e2x, e2y = xs[:, 1] - ax, ys[:, 1] - ay, xs[:, 2] - ax, ys[:, 2] - ay
    v1, v2 = values[:, 1] - values[:, 0], values[:, 2] - values[:, 0]
    with np.errstate(divide="ignore", invalid="ignore"):
        gx = (v1 * e2y - v2 * e1y) / area
        gy = (v2 * e1x - v1 * e2x) / area
    gx = np.nan_to_num(gx, nan=0.0, posinf=0.0, neginf=0.0)
    gy = np.nan_to_num(gy, nan=0.0, posinf=0.0, neginf=0.0)
    return values[:, 0] - gx * ax - gy * ay, gx, gy


def rasterize(xy, z, sd, T, cullable, facing, W, H, *, fragment_budget=None, chunk_triangles=None, tile=8,
              deadline=None):
    """Front-to-back z-buffer with back-face culling and hierarchical-z rejection.

    ``xy`` are supersampled screen positions, ``z`` view depths (smaller is
    nearer), ``sd`` signed distances to the section plane (> 0 is removed) or
    None. Fragments are interpolated from per-triangle depth planes and clamped
    to the triangle's depth range. Chunks hold at most ``chunk_triangles``
    triangles and ``fragment_budget`` bounding-box pixels. Returns float32
    zbuf, int32 tbuf (triangle index or -1), stats and the winners' float32
    screen-space depth gradients (dz/dx, dz/dy per supersampled pixel).
    ``deadline`` (a :class:`Deadline`) is checked before every chunk.
    """
    check = _no_deadline if deadline is None else deadline
    fragment_budget = int(fragment_budget or DEFAULT_LIMITS["fragment_budget"])
    chunk_triangles = int(chunk_triangles or DEFAULT_LIMITS["chunk_triangles"])
    stats = {"triangles": int(len(T)), "backface_culled": 0, "occlusion_culled": 0, "fragments": 0, "chunks": 0}
    TH, TW = -(-H // tile), -(-W // tile)
    PW = TW * tile
    zbuf = np.full(TH * tile * PW, np.inf, np.float32)
    tbuf = np.full(len(zbuf), -1, np.int32)
    gxbuf = np.zeros(len(zbuf), np.float32)
    gybuf = np.zeros(len(zbuf), np.float32)
    tie = np.full(len(zbuf), _NO_TRIANGLE, np.int32)  # per-chunk tie-break scratch, reset after use

    def crop():
        cut = (lambda b: b.reshape(TH * tile, PW)[:H, :W].ravel().copy())
        return cut(zbuf), cut(tbuf), stats, (cut(gxbuf), cut(gybuf))

    if len(T) == 0:
        return crop()
    xs, ys = xy[:, 0][T], xy[:, 1][T]
    area = (xs[:, 1] - xs[:, 0]) * (ys[:, 2] - ys[:, 0]) - (ys[:, 1] - ys[:, 0]) * (xs[:, 2] - xs[:, 0])
    x0 = np.maximum(np.ceil(xs.min(1) - 0.5), 0)
    x1 = np.minimum(np.floor(xs.max(1) - 0.5), W - 1)
    y0 = np.maximum(np.ceil(ys.min(1) - 0.5), 0)
    y1 = np.minimum(np.floor(ys.max(1) - 0.5), H - 1)
    ok = (np.abs(area) > 1e-12) & (x1 >= x0) & (y1 >= y0)
    back = cullable & (facing > 0)
    stats["backface_culled"] = int((ok & back).sum())
    ok &= ~back
    zt = z[T]
    st = None
    if sd is not None:
        st = sd[T]
        ok &= st.min(1) <= 0  # wholly on the removed side: never drawn
    zmin = zt.min(1)
    order = np.flatnonzero(ok)
    order = order[np.argsort(zmin[order], kind="stable")]
    del zmin, ok, back
    if len(order) == 0:
        return crop()
    # local (drawn, depth-ordered) triangle arrays; the full-size ones are released as we go
    xs, ys, area, zt = xs[order], ys[order], area[order], zt[order]
    x0, x1 = x0[order].astype(np.int64), x1[order].astype(np.int64)
    y0, y1 = y0[order].astype(np.int64), y1[order].astype(np.int64)
    zlo, zhi = zt.min(1), zt.max(1)
    zc, zgx, zgy = _plane(zt, xs, ys, area)
    del zt
    if st is not None:
        sc, sgx, sgy = _plane(st[order], xs, ys, area)
    del st
    gidx = order.astype(np.int32)
    tx0, tx1, ty0, ty1 = x0 // tile, x1 // tile, y0 // tile, y1 // tile
    lev = np.ceil(np.log2(np.maximum(np.maximum(tx1 - tx0 + 1, ty1 - ty0 + 1), 1))).astype(np.int64)
    boxes = np.cumsum((x1 - x0 + 1) * (y1 - y0 + 1))
    levels = None

    def pyramid():
        m = zbuf.reshape(TH, tile, TW, tile).max(axis=(1, 3))
        out = [m]
        while out[-1].shape[0] > 1 or out[-1].shape[1] > 1:
            p = out[-1]
            h2, w2 = -(-p.shape[0] // 2), -(-p.shape[1] // 2)
            q = np.full((h2 * 2, w2 * 2), -np.inf, np.float32)
            q[:p.shape[0], :p.shape[1]] = p
            out.append(q.reshape(h2, 2, w2, 2).max(axis=(1, 3)))
        return out

    start, total = 0, len(order)
    while start < total:
        base = boxes[start - 1] if start else 0
        end = int(np.searchsorted(boxes, base + fragment_budget, side="right"))
        end = min(max(end, start + 1), start + chunk_triangles, total)
        check()
        idx = np.arange(start, end)
        start = end
        stats["chunks"] += 1
        if levels is not None:
            k = np.minimum(lev[idx], len(levels) - 1)
            occluded = np.zeros(len(idx), bool)
            for kk in np.unique(k):
                sel = np.flatnonzero(k == kk)
                L = levels[kk]
                i0, i1 = ty0[idx[sel]] >> kk, np.minimum(ty1[idx[sel]] >> kk, L.shape[0] - 1)
                j0, j1 = tx0[idx[sel]] >> kk, np.minimum(tx1[idx[sel]] >> kk, L.shape[1] - 1)
                mx = np.maximum.reduce([L[i0, j0], L[i0, j1], L[i1, j0], L[i1, j1]])
                occluded[sel] = zlo[idx[sel]] > mx
            stats["occlusion_culled"] += int(occluded.sum())
            idx = idx[~occluded]
            if len(idx) == 0:
                continue
        pix, ftri, fx, fy = _fragments(xs, ys, x0, x1, y0, y1, area, idx, PW)
        px, py = fx + 0.5, fy + 0.5
        del fx, fy
        depth = np.clip(zc[ftri] + zgx[ftri] * px + zgy[ftri] * py, zlo[ftri], zhi[ftri]).astype(np.float32)
        keep = depth < zbuf[pix]
        if sd is not None:
            keep &= (sc[ftri] + sgx[ftri] * px + sgy[ftri] * py) <= 0
        del px, py
        pix, ftri, depth = pix[keep], ftri[keep].astype(np.int32), depth[keep]
        stats["fragments"] += int(len(pix))
        if len(pix) == 0:
            continue
        # nearest fragment per pixel; ties go to the earliest triangle in depth order
        np.minimum.at(zbuf, pix, depth)
        won = depth == zbuf[pix]
        wp, wf = pix[won], ftri[won]
        np.minimum.at(tie, wp, wf)
        first = wf == tie[wp]
        tie[wp] = _NO_TRIANGLE
        wp, wf = wp[first], wf[first]
        tbuf[wp] = gidx[wf]
        gxbuf[wp] = zgx[wf]
        gybuf[wp] = zgy[wf]
        del pix, ftri, depth, won, wp, wf, first
        levels = pyramid()
    return crop()


def _erode(mask):
    """4-neighbour erosion of a 2D bool mask by one pixel (the border erodes)."""
    out = mask.copy()
    out[1:, :] &= mask[:-1, :]
    out[:-1, :] &= mask[1:, :]
    out[:, 1:] &= mask[:, :-1]
    out[:, :-1] &= mask[:, 1:]
    out[0, :] = out[-1, :] = False
    out[:, 0] = out[:, -1] = False
    return out


def _dilate(mask):
    out = mask.copy()
    out[1:, :] |= mask[:-1, :]
    out[:-1, :] |= mask[1:, :]
    out[:, 1:] |= mask[:, :-1]
    out[:, :-1] |= mask[:, 1:]
    return out


def _cap_overlap(xy, T, tri_cap, cap_groups, cap_index, tbuf, tri_tag, W, H, fragment_budget):
    """Pixels where two or more cap groups (sliced solids) coincide, and the part pairs.

    Only pixels where a cap wins count. Scanline spans include pixel centres on a
    shared edge, so solids that merely touch would overlap along a line of pixels:
    the overlap is opened (eroded then dilated by one supersampled pixel), and a
    pair is reported only where the eroded overlap holds. Returns (hatch mask,
    sorted part-index pairs); a pair naming one part twice means two solids of
    that part overlap.
    """
    mask = np.zeros(W * H, bool)
    if len(cap_index) == 0:
        return mask, []
    Tc = T[cap_index]
    xs, ys = xy[:, 0][Tc], xy[:, 1][Tc]
    area = (xs[:, 1] - xs[:, 0]) * (ys[:, 2] - ys[:, 0]) - (ys[:, 1] - ys[:, 0]) * (xs[:, 2] - xs[:, 0])
    x0 = np.maximum(np.ceil(xs.min(1) - 0.5), 0).astype(np.int64)
    x1 = np.minimum(np.floor(xs.max(1) - 0.5), W - 1).astype(np.int64)
    y0 = np.maximum(np.ceil(ys.min(1) - 0.5), 0).astype(np.int64)
    y1 = np.minimum(np.floor(ys.max(1) - 0.5), H - 1).astype(np.int64)
    ok = np.flatnonzero((np.abs(area) > 1e-12) & (x1 >= x0) & (y1 >= y0))
    if len(ok) == 0:
        return mask, []
    boxes = np.cumsum((x1[ok] - x0[ok] + 1) * (y1[ok] - y0[ok] + 1))
    groups_all = tri_cap[cap_index].astype(np.int64)
    G = int(groups_all.max()) + 1
    pairs, start = [], 0
    while start < len(ok):
        base = boxes[start - 1] if start else 0
        end = max(int(np.searchsorted(boxes, base + fragment_budget, side="right")), start + 1)
        pix, ftri, _, _ = _fragments(xs, ys, x0, x1, y0, y1, area, ok[start:end], W)
        start = end
        pairs.append(np.unique(pix.astype(np.int64) * G + groups_all[ftri]))
    combined = np.unique(np.concatenate(pairs))
    pix, group = combined // G, combined % G
    winner = tbuf[pix]
    on_cap = (winner >= 0) & (tri_tag[np.maximum(winner, 0)] == TAG_CAP)
    pix, group = pix[on_cap], group[on_cap]
    same = np.zeros(len(pix), bool)
    same[1:] = pix[1:] == pix[:-1]
    if not same.any():
        return mask, []
    mask[pix[1:][same[1:]]] = True
    grid = mask.reshape(H, W)
    core = _erode(grid)
    if not core.any():
        return np.zeros(W * H, bool), []
    core_flat = core.ravel()
    part_of = np.asarray(cap_groups, np.int64)
    found = set()
    for offset in range(1, 16):
        sel = np.flatnonzero(pix[offset:] == pix[:-offset]) if offset < len(pix) else np.zeros(0, int)
        if len(sel) == 0:
            break
        sel = sel[core_flat[pix[sel]]]
        for a, b in set(zip(part_of[group[sel]].tolist(), part_of[group[sel + offset]].tolist())):
            found.add((min(a, b), max(a, b)))
    return (_dilate(core) & grid).ravel(), sorted(found)


# ---------------------------------------------------------------- edges and overlays

class _Camera:
    def __init__(self, name, d, u, r, cx, cy, cz, scale, W, H, mid_y, ss):
        self.name, self.d, self.u, self.r = name, d, u, r
        self.cx, self.cy, self.cz, self.scale = cx, cy, cz, scale
        self.W, self.H, self.mid_y, self.ss = W, H, mid_y, ss

    def project(self, P):
        P = np.asarray(P, float).reshape(-1, 3)
        return ((P @ self.r - self.cx) * self.scale + self.W / 2, self.mid_y - (P @ self.u - self.cy) * self.scale,
                P @ self.d - self.cz)

    def out(self, p):
        X, Y, _ = self.project(p)
        return float(X[0]) / self.ss, float(Y[0]) / self.ss

    @property
    def mm_per_px(self):
        return self.ss / self.scale

    def describe(self, offset=(0.0, 0.0)):
        k = self.scale / self.ss
        row0 = [*(self.r * k), (self.W / 2 - self.cx * self.scale) / self.ss + offset[0]]
        row1 = [*(-self.u * k), (self.mid_y + self.cy * self.scale) / self.ss + offset[1]]
        center = self.cx * self.r + self.cy * self.u + self.cz * self.d
        return _plain({"projection": "orthographic", "direction": self.d, "up": self.u, "right": self.r,
                       "center_mm": center, "mm_per_px": self.mm_per_px, "pixel_from_world": [row0, row1]})


def _runs(cam, polylines, *, depth=None, eps=0.0, prepared=None, drop=False, dash_px=None):
    """Visible runs of 3D polylines in supersampled screen space.

    Points are first thinned to >= EDGE_MIN_PX of projected arc length. With
    ``drop`` a chord is skipped when its projected length is under EDGE_MIN_PX
    or its direction is within EDGE_END_ON_DEGREES of the view direction (end-on
    hairline clusters). Samples (~1 output px apart) are kept when on the kept
    side of the section, in front of ``depth`` (3x3-min z-buffer) + ``eps``, and
    on a dash when ``dash_px`` is set. Returns (runs, visible output px, stats).
    """
    stats = {"chords": 0, "end_on": 0, "short": 0}
    polylines = [p for p in polylines if len(p) >= 2]
    if not polylines:
        return [], 0.0, stats
    lengths = np.array([len(p) for p in polylines])
    P = np.concatenate(polylines)
    pid = np.repeat(np.arange(len(polylines)), lengths)
    X, Y, Z = cam.project(P)
    ss = cam.ss
    first = np.ones(len(P), bool)
    first[1:] = pid[1:] != pid[:-1]
    last = np.ones(len(P), bool)
    last[:-1] = pid[1:] != pid[:-1]
    seg = np.hypot(np.diff(X), np.diff(Y)) / ss
    seg[~(pid[1:] == pid[:-1])] = 0.0
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    arc = cum - cum[np.flatnonzero(first)][pid]
    bucket = np.floor(arc / EDGE_MIN_PX).astype(np.int64)
    thin = first | last
    thin[1:] |= bucket[1:] != bucket[:-1]
    k = np.flatnonzero(thin)
    a, b = k[:-1], k[1:]
    valid = pid[a] == pid[b]
    a, b = a[valid], b[valid]
    if len(a) == 0:
        return [], 0.0, stats
    L = np.hypot(X[b] - X[a], Y[b] - Y[a]) / ss
    stats["projected_px"] = float(L.sum())
    kept = np.ones(len(a), bool)
    if drop:
        v3 = P[b] - P[a]
        l3 = np.linalg.norm(v3, axis=1)
        end_on = (l3 > 0) & (np.abs(v3 @ cam.d) >= _COS_END_ON * l3)
        short = (L < EDGE_MIN_PX) & ~end_on
        stats["end_on"], stats["short"] = int(end_on.sum()), int(short.sum())
        kept = ~(end_on | short)
    stats["chords"] = int(kept.sum())
    chain_start = kept.copy()
    chain_start[1:] &= ~kept[:-1] | (pid[a][1:] != pid[a][:-1])
    chain = np.cumsum(chain_start)
    a, b, L, chain = a[kept], b[kept], L[kept], chain[kept]
    if len(a) == 0:
        return [], 0.0, stats
    n = np.maximum(np.ceil(L), 1).astype(np.int64)
    cidx = np.repeat(np.arange(len(a)), n + 1)
    t = (np.arange(len(cidx)) - np.repeat(np.cumsum(n + 1) - (n + 1), n + 1)) / n[cidx]
    ia, ib = a[cidx], b[cidx]
    SX = X[ia] + t * (X[ib] - X[ia])
    SY = Y[ia] + t * (Y[ib] - Y[ia])
    vis = np.ones(len(SX), bool)
    if prepared is not None and prepared.section is not None:
        s = (P - prepared.section["origin"]) @ prepared.section["normal"]
        vis &= s[ia] + t * (s[ib] - s[ia]) <= 1e-7 * prepared.diag
    if depth is not None:
        SZ = Z[ia] + t * (Z[ib] - Z[ia])
        ix = np.clip(np.floor(SX).astype(np.int64), 0, cam.W - 1)
        iy = np.clip(np.floor(SY).astype(np.int64), 0, cam.H - 1)
        vis &= SZ <= depth[iy, ix] + eps
    if dash_px:
        sample_arc = arc[ia] + t * L[cidx]
        vis &= (np.floor(sample_arc / dash_px).astype(np.int64) % 2) == 0
    stats["visible_samples"] = int(vis.sum())
    sample_chain = chain[cidx]
    start = vis.copy()
    start[1:] &= ~vis[:-1] | (sample_chain[1:] != sample_chain[:-1])
    run_id = np.cumsum(start)[vis]
    pts = np.stack([SX[vis], SY[vis]], 1)
    if len(pts) == 0:
        return [], 0.0, stats
    cuts = np.flatnonzero(run_id[1:] != run_id[:-1]) + 1
    runs = np.split(pts, cuts)
    visible = float(sum(np.hypot(*np.diff(r, axis=0).T).sum() for r in runs if len(r) > 1)) / ss
    return runs, visible, stats


def _draw_runs(draw, runs, fill, width, dots=False):
    drawn = 0
    for run in runs:
        extent = float(np.ptp(run, axis=0).max()) if len(run) > 1 else 0.0
        if len(run) >= 2 and extent >= 0.5:
            draw.line([tuple(p) for p in run.tolist()], fill=fill, width=width, joint="curve" if width > 2 else None)
            drawn += 1
        elif dots:  # a single sample or an end-on run: mark it with a dot
            x, y = run[0]
            rad = max(width / 2, 1)
            draw.ellipse((x - rad, y - rad, x + rad, y + rad), fill=fill)
            drawn += 1
    return drawn


def _fit_text(draw, text, font, width):
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "\u2026", font=font) > width:
        text = text[:-1]
    return text + "\u2026" if text else ""


def _hollow_or_solid_label(draw, anchor, text, color, font, solid, taken, w_out, h_out):
    box = None
    for dx, dy in LABEL_OFFSETS:
        tx, ty = anchor[0] + dx, anchor[1] + dy
        bb = draw.textbbox((tx, ty), text, font=font, anchor="mm")
        cand = (bb[0] - 6, bb[1] - 4, bb[2] + 6, bb[3] + 4)
        inside = cand[0] > 2 and cand[2] < w_out - 2 and cand[1] > HEADER_PX and cand[3] < h_out - FOOTER_PX
        if inside and not any(not (cand[2] < o[0] or cand[0] > o[2] or cand[3] < o[1] or cand[1] > o[3])
                              for o in taken):
            box = cand
            break
    if box is None:  # nothing fits: first candidate, clamped into the drawable band
        dx, dy = LABEL_OFFSETS[0]
        bb = draw.textbbox((0, 0), text, font=font, anchor="mm")
        half_w, half_h = (bb[2] - bb[0]) / 2 + 6, (bb[3] - bb[1]) / 2 + 4
        tx = min(max(anchor[0] + dx, half_w + 2), w_out - half_w - 2)
        ty = min(max(anchor[1] + dy, HEADER_PX + half_h + 1), h_out - FOOTER_PX - half_h - 1)
        box = (tx - half_w, ty - half_h, tx + half_w, ty + half_h)
    tx, ty = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    taken.append(box)
    if solid:  # white halo and rim keep the label readable on a face of the same colour
        draw.line([anchor, (tx, ty)], fill=(255, 255, 255), width=4)
        draw.line([anchor, (tx, ty)], fill=color, width=2)
        draw.ellipse((anchor[0] - 4, anchor[1] - 4, anchor[0] + 4, anchor[1] + 4), fill=(255, 255, 255))
        draw.ellipse((anchor[0] - 3, anchor[1] - 3, anchor[0] + 3, anchor[1] + 3), fill=color)
        draw.rounded_rectangle(box, radius=4, fill=color, outline=(255, 255, 255), width=2)
        draw.text((tx, ty), text, font=font, fill=(255, 255, 255), anchor="mm")
    else:  # hidden or not in the shown geometry: dashed leader, hollow label
        n_dash = max(int(math.hypot(tx - anchor[0], ty - anchor[1]) // 6), 1)
        for k in range(0, n_dash, 2):
            a0, a1 = k / n_dash, min((k + 1) / n_dash, 1)
            draw.line([(anchor[0] + (tx - anchor[0]) * a0, anchor[1] + (ty - anchor[1]) * a0),
                       (anchor[0] + (tx - anchor[0]) * a1, anchor[1] + (ty - anchor[1]) * a1)], fill=color, width=2)
        draw.ellipse((anchor[0] - 3, anchor[1] - 3, anchor[0] + 3, anchor[1] + 3), outline=color, width=2)
        draw.rounded_rectangle(box, radius=4, fill=(255, 255, 255), outline=color, width=2)
        draw.text((tx, ty), text, font=font, fill=color, anchor="mm")
    return [round(v, 1) for v in box]


def _legend_rows(highlights, rows_info, prepared):
    rows = []
    for hi, item in enumerate(highlights):
        entry = prepared.highlights[hi]
        status = ""
        if not entry["rendered"]:
            status = " (not in shown geometry)"
        elif rows_info is not None and not rows_info[hi]["visible"]:
            status = " (hidden)"
        text = item.label + ("  " + item.note if item.note else "") + status
        rows.append((highlight_color(hi), text))
    return rows


def _draw_legend(draw, rows, x, bottom, width, max_rows, font):
    if not rows or max_rows <= 0:
        return 0
    shown = rows if len(rows) <= max_rows else rows[:max_rows - 1] + [((90, 90, 90), f"+{len(rows) - max_rows + 1} more")]
    y = bottom
    for color, text in reversed(shown):
        draw.rectangle((x, y - 6, x + 10, y + 4), fill=color)
        draw.text((x + 16, y - 1), _fit_text(draw, text, font, width - 20), font=font, fill=(30, 30, 30), anchor="lm")
        y -= LEGEND_ROW_PX
    return len(shown)


def banner_forms(text):
    """A banner text, then shorter forms of the same statement for narrow images."""
    forms = [str(text)]
    for old, new in (("RETAINED GEOMETRY", "RETAINED"), ("BUILD FAILED", "FAILED"), ("NEEDS REBUILD", "REBUILD")):
        shorter = forms[-1].replace(old, new)
        if shorter != forms[-1]:
            forms.append(shorter)
    if forms[-1].startswith("NOT A SOLID: "):
        forms.append("NOT SOLID: " + forms[-1][len("NOT A SOLID: "):].split()[0])
    return forms


# Header banner layouts tried in order: (banners shown, text form, share of the width).
# The first banner always stays text: shorter forms and smaller fonts come before "+n".
HEADER_PLANS = ((2, 0, 0.6), (1, 0, 0.75), (2, 1, 0.75), (1, 1, 0.85), (2, 2, 0.85), (1, 2, 1.0))


def _draw_header(draw, w_out, title, view_name, revision, sectioned, banners):
    draw.rectangle((0, 0, w_out, HEADER_PX - 2), fill=BAND)
    wide = w_out >= 400
    bold = _font(13 if wide else 11, True)
    sizes = (13, 11, 9) if wide else (11, 9, 8)
    pad = 8 if wide else 4
    avail = w_out - 8
    forms = [banner_forms(b["text"]) for b in banners]

    def layout(count, tier, size, plus):
        font = _font(size, True)
        items = [(forms[i][min(tier, len(forms[i]) - 1)], False) for i in range(min(count, len(banners)))]
        extra = len(banners) - len(items)
        if extra and plus:
            items.append((f"+{extra}", True))
        return font, [(text, draw.textlength(text, font=font) + 2 * (max(pad // 2, 2) if more else pad), more)
                      for text, more in items]

    chosen, font = [], bold
    if banners:
        for count, tier, share, plus in [(*plan, True) for plan in HEADER_PLANS] + [(1, 2, 1.0, False)]:
            for size in sizes:
                candidate, items = layout(count, tier, size, plus)
                if sum(width + 4 for _, width, _ in items) <= avail * share:
                    chosen, font = items, candidate
                    break
            if chosen:
                break
        if not chosen:  # below the contract's minimum width: the first banner, cut to fit
            font = _font(sizes[-1], True)
            text = _fit_text(draw, forms[0][-1], font, avail - 4 - 2 * pad) or forms[0][-1][:1]
            chosen = [(text, draw.textlength(text, font=font) + 2 * pad, False)]
    x = w_out - 2 - sum(width + 4 for _, width, _ in chosen)
    left_limit = x
    for i, (text, width, more) in enumerate(chosen):
        fill = (90, 90, 90) if more else _banner_rgb(banners[i]["color"])
        draw.rectangle((x, 2, x + width, HEADER_PX - 4), fill=fill)
        draw.text((x + width / 2, (HEADER_PX - 2) / 2), text, font=font, fill=(255, 255, 255), anchor="mm")
        x += width + 4
    parts = ([view_name.upper()] + ([f"rev {revision[:8]}"] if revision else [])
             + (["SECTION"] if sectioned and view_name != "section" else []))
    available = left_limit - 12
    tail = "  |  " + "  |  ".join(parts)
    title_width = available - draw.textlength(tail, font=bold)
    if title and title_width > draw.textlength("…", font=bold) + 4:
        text = _fit_text(draw, title, bold, title_width) + tail
    else:
        text = _fit_text(draw, "  |  ".join(parts), bold, available)
        if not text.startswith(parts[0]) and not wide:  # narrow: the whole view name, smaller, or nothing
            bold = _font(9, True)
            text = parts[0] if draw.textlength(parts[0], font=bold) <= available else ""
    if text:
        draw.text((8, (HEADER_PX - 2) / 2), text, font=bold, fill=TEXT, anchor="lm")


def _draw_footer(draw, w_out, h_out, mm_per_px, sectioned, cam):
    """Scale bar, axis triad and caption. The caption always carries the validity note:
    when the band is too narrow the triad goes first, then the scale bar and its label,
    then the caption font shrinks; the caption is never empty."""
    draw.rectangle((0, h_out - FOOTER_PX + 2, w_out, h_out), fill=BAND)
    base = 12 if w_out >= 520 else 10
    target = mm_per_px * min(120, w_out / 5)
    mag = 10 ** math.floor(math.log10(target))
    bar_mm = max(m * mag for m in (1, 2, 5) if m * mag <= target)
    bar_px = bar_mm / mm_per_px
    xb = w_out - 12 - bar_px
    yb = h_out - 8
    label = f"{bar_mm:g} mm"
    scale_text = f"1 px = {mm_per_px:.4g} mm"
    options = [("hatched = cut face  |  " if sectioned else "") + f"orthographic  |  {scale_text}  |  {CAPTION_NOTE}",
               f"{scale_text}  |  {CAPTION_NOTE}", f"{scale_text}  |  not a validity check",
               CAPTION_NOTE, "not a validity check"]
    caption, triad, bar, small = None, False, False, _font(base)
    for triad, bar, sizes in ((True, True, (base,)), (False, True, (base,)), (False, False, (base, 9, 8))):
        for size in sizes:
            small = _font(size)
            # the triad sits 24 px left of the scale label; its arms and names need ~24 px more
            right = (xb - 6 - draw.textlength(label, font=small) - (48 if triad else 10)) if bar else w_out - 8
            caption = next((c for c in options if draw.textlength(c, font=small) <= right - 8), None)
            if caption is not None:
                break
        if caption is not None:
            break
    if caption is None:  # narrower than the contract allows: the note, cut to fit
        caption = _fit_text(draw, "not a validity check", small, w_out - 16) or "…"
    if bar:
        draw.line([(xb, yb), (w_out - 12, yb)], fill=(20, 20, 20), width=3)
        draw.text((xb - 6, yb - 3), label, font=small, fill=(20, 20, 20), anchor="rm")
    if triad:  # compact axis triad inside the footer band, left of the scale label (never over the model)
        ox, oy = xb - 6 - draw.textlength(label, font=small) - 24, h_out - FOOTER_PX / 2 + 1
        tiny = _font(9)
        for axis, color, name in ((np.array([1.0, 0, 0]), (210, 40, 40), "X"),
                                  (np.array([0, 1.0, 0]), (30, 150, 30), "Y"),
                                  (np.array([0, 0, 1.0]), (40, 80, 220), "Z")):
            vx, vy = float(axis @ cam.r), float(-(axis @ cam.u))
            if math.hypot(vx, vy) < 0.2:  # along the view: a dot, "+" when it points at the viewer
                sign = "+" if float(axis @ (-cam.d)) > 0 else "-"
                draw.ellipse((ox - 3, oy - 3, ox + 3, oy + 3), outline=color, width=1)
                draw.text((ox - 6, oy), sign + name, font=tiny, fill=color, anchor="rm")
                continue
            draw.line([(ox, oy), (ox + 7 * vx, oy + 7 * vy)], fill=color, width=2)
            draw.text((ox + 11 * vx, oy + 11 * vy), name, font=tiny, fill=color, anchor="mm")
    draw.text((8, yb - 3), caption, font=small, fill=MUTED_TEXT, anchor="lm")


# ---------------------------------------------------------------- one view

def _frame(scene, pr, frame, d, u, r, sx, sy, sz):
    """Projected framing extents (x0, x1, y0, y1, z0, z1) in camera coordinates, or an explicit frame."""
    if isinstance(frame, dict):
        center = _vector3(frame["center_mm"], "frame center_mm")
        width = float(frame["width_mm"])
        if not (math.isfinite(width) and width > 0):
            raise ValueError("frame width_mm must be > 0")
        return ("explicit", center, width)
    if frame == "model" and scene.model_bounds is not None:
        points = _clip_box_points(scene.model_bounds[0], scene.model_bounds[1], pr.section)
        if len(points):
            return ("points", points @ r, points @ u, points @ d)
    if frame == "highlights":
        clouds = [pr.V[pr.vtag >= 0]] + [p for e in pr.highlights for p in e["edges"]]
        clouds += [np.asarray(e["points"]).reshape(-1, 3) for e in pr.highlights]
        clouds = [c[pr.kept(c)] for c in clouds if len(c)]
        clouds = [c for c in clouds if len(c)]
        if not clouds:
            raise RenderError("highlight_not_rendered",
                              'frame "highlights" needs at least one highlight match in the shown geometry.')
        points = np.concatenate(clouds)
        lo, hi = _expanded_box(points.min(0), points.max(0))
        box = _clip_box_points(lo, hi, None)
        return ("points", box @ r, box @ u, box @ d)
    mask = (pr.vtag == TAG_PART) | (pr.vtag == TAG_CAP)
    sel = mask & pr.kept(pr.V)
    extra = [p for p in pr.sketch_polylines] + [p for e in pr.highlights for p in e["edges"]]
    extra = np.concatenate(extra) if extra else np.zeros((0, 3))
    extra_kept = extra[pr.kept(extra)]
    if not sel.any() and not len(extra_kept):
        sel, extra_kept = mask, extra
    if not sel.any() and not len(extra_kept):
        raise RenderError("render_failed", "There is no geometry to draw.", reason="no_geometry")
    return ("points", np.concatenate([sx[sel], extra_kept @ r]), np.concatenate([sy[sel], extra_kept @ u]),
            np.concatenate([sz[sel], extra_kept @ d]))


def render(scene, prepared, view="iso", size=DEFAULT_SIZE, *, supersample=2, labels=True, part_labels=False,
           edges=True, frame="included", legend=True, phases=None, deadline=None):
    """Render one orthographic view of ``prepared``; returns (PIL RGB image, info dict).

    ``info`` is deterministic for identical inputs (no timings); timings go to ``phases``.
    ``deadline`` (a :class:`Deadline`) is checked between raster chunks.
    """
    phases = {} if phases is None else phases
    check = _no_deadline if deadline is None else deadline
    pr = prepared
    began = time.perf_counter()
    name, d, u, r = view_camera(view, pr.section)
    w_out, h_out = int(size[0]), int(size[1])
    if w_out < 64 or h_out < HEADER_PX + FOOTER_PX + 16:
        raise ValueError("image too small")
    ss = max(int(supersample), 1)
    W, H = w_out * ss, h_out * ss
    header, footer = HEADER_PX * ss, FOOTER_PX * ss
    mid_y = header + (H - header - footer) / 2
    V, T = pr.V, pr.T
    sx, sy, sz = V @ r, V @ u, V @ d
    framing = _frame(scene, pr, frame, d, u, r, sx, sy, sz)
    if framing[0] == "explicit":
        center, width = framing[1], framing[2]
        scale = W / width
        cx, cy, cz = float(center @ r), float(center @ u), float(center @ d)
    else:
        fx, fy, fz = framing[1], framing[2], framing[3]
        span_x, span_y = float(fx.max() - fx.min()), float(fy.max() - fy.min())
        if max(span_x, span_y) < 1e-6:
            span_x = span_y = 1.0
        span_x, span_y = max(span_x, 1e-6), max(span_y, 1e-6)
        scale = min(W * (1 - 2 * MARGIN) / span_x, (H - header - footer) * (1 - 2 * MARGIN) / span_y)
        cx, cy = float(fx.max() + fx.min()) / 2, float(fy.max() + fy.min()) / 2
        cz = float(fz.max() + fz.min()) / 2
    cam = _Camera(name, d, u, r, cx, cy, cz, scale, W, H, mid_y, ss)
    mm_per_px = cam.mm_per_px
    xy = np.stack([(sx - cx) * scale + W / 2, mid_y - (sy - cy) * scale], 1)
    z = sz - cz - (pr.vtag != TAG_PART) * (OVERLAY_BIAS_PX / scale)
    highlight_v = pr.vtag >= 0
    if highlight_v.any():  # shared faces: the more specific highlight wins the tie (Prepared.highlight_tie)
        z = z - np.where(highlight_v, pr.highlight_tie[np.maximum(pr.vtag, 0)], 0.0) * (HIGHLIGHT_TIE_PX / scale)
    sd = None
    if pr.section is not None:
        caps_v = pr.vtag == TAG_CAP
        z = z - caps_v * (len(pr.cap_groups) - pr.vcap) * (CAP_TIE_PX / scale)
        sd = (V - pr.section["origin"]) @ pr.section["normal"] - 1e-7 * pr.diag
        sd = np.where(caps_v, -1.0, sd)
    del sx, sy, sz, highlight_v
    facing = pr.FN @ d.astype(np.float32)
    phases["project"] = phases.get("project", 0.0) + (time.perf_counter() - began) * 1000

    began = time.perf_counter()
    raster_limits = {"fragment_budget": pr.limits["fragment_budget"], "chunk_triangles": pr.limits["chunk_triangles"]}
    zbuf, tbuf, stats, (gxbuf, gybuf) = rasterize(xy, z, sd, T, pr.tri_cull, facing, W, H, deadline=check,
                                                  **raster_limits)
    # Face highlights: each one is rasterized alone and counted where its own fragments
    # reach the front (within the highlight tie span), so highlights that share a face are
    # all visible although only one colour wins each pixel.
    highlight_masks = {}
    slack = (len(pr.highlights) + 1) * HIGHLIGHT_TIE_PX / scale
    for hi, entry in enumerate(pr.highlights):
        if entry["faces"]:
            sel = np.flatnonzero(pr.tri_tag == hi)
            zh, th, _, _ = rasterize(xy, z, sd, T[sel], pr.tri_cull[sel], facing[sel], W, H, deadline=check,
                                     **raster_limits)
            highlight_masks[hi] = ((th >= 0) & (zh <= zbuf + slack)).reshape(H, W)
            del zh, th, sel
    del z, sd, facing
    cap_index = np.flatnonzero(pr.tri_tag == TAG_CAP) if pr.section is not None else np.zeros(0, np.int64)
    if len(np.unique(pr.tri_cap[cap_index])) < 2:
        cap_index = cap_index[:0]  # a single cap group cannot overlap another
    overlap, overlap_pairs = _cap_overlap(xy, T, pr.tri_cap, pr.cap_groups, cap_index, tbuf, pr.tri_tag, W, H,
                                          pr.limits["fragment_budget"])
    covered = np.flatnonzero(tbuf >= 0)
    img = np.empty((W * H, 3), np.float32)
    img[:] = np.asarray(BACKGROUND, np.float32) / 255
    key = _unit(-d + 0.6 * u - 0.5 * r).astype(np.float32)
    fill = _unit(-d - 0.4 * u + 0.7 * r).astype(np.float32)
    half = _unit(key - d).astype(np.float32)
    d32 = d.astype(np.float32)
    period = 5 * ss
    # Smooth normals are affine across a triangle in screen space: one plane per normal
    # component for each triangle that won a pixel, then three gathers per pixel.
    if len(covered):
        used = np.zeros(len(T), bool)
        used[tbuf[covered]] = True
        winners = np.flatnonzero(used)
        slot = np.zeros(len(T), np.int32)
        slot[winners] = np.arange(len(winners), dtype=np.int32)
        Tu = T[winners]
        xs_u, ys_u = xy[:, 0][Tu], xy[:, 1][Tu]
        area_u = ((xs_u[:, 1] - xs_u[:, 0]) * (ys_u[:, 2] - ys_u[:, 0])
                  - (ys_u[:, 1] - ys_u[:, 0]) * (xs_u[:, 2] - xs_u[:, 0]))
        planes = [_plane(pr.N[Tu][:, :, j], xs_u, ys_u, area_u) for j in range(3)]
        n_c = np.stack([p[0] for p in planes], 1).astype(np.float32)
        n_gx = np.stack([p[1] for p in planes], 1).astype(np.float32)
        n_gy = np.stack([p[2] for p in planes], 1).astype(np.float32)
        del used, Tu, xs_u, ys_u, area_u, planes
    for s0 in range(0, len(covered), SHADE_CHUNK):
        check()
        pix = covered[s0:s0 + SHADE_CHUNK]
        wt = tbuf[pix]
        k = slot[wt]
        px = (pix % W + 0.5).astype(np.float32)[:, None]
        py = (pix // W + 0.5).astype(np.float32)[:, None]
        n = n_c[k] + n_gx[k] * px + n_gy[k] * py
        del px, py, k
        n /= np.maximum(np.sqrt(np.einsum("ij,ij->i", n, n)), 1e-12)[:, None]
        back = (n @ (-d32)) < 0
        n[back] *= -1
        lam = 0.30 + 0.55 * np.clip(n @ key, 0, 1) + 0.22 * np.clip(n @ fill, 0, 1)
        col = pr.tri_rgb[wt] * lam[:, None]
        hv = n @ half
        shiny = np.flatnonzero(hv > 0.8)  # 0.8 ** 40 * 0.25 < 4e-5: invisible below
        if len(shiny):
            col[shiny] += (hv[shiny] ** 40 * 0.25)[:, None]
        del hv, shiny, lam
        tags = pr.tri_tag[wt]
        cap = tags == TAG_CAP
        col[back & ~cap] *= 0.55
        if cap.any():
            hx, hy = (pix[cap] % W).astype(np.int64), (pix[cap] // W).astype(np.int64)
            odd = (pr.tri_part[wt[cap]] % 2) == 1
            d1 = (hx + hy) // period % 2 == 0
            d2 = (hx - hy + 1_000_000) // period % 2 == 0
            dark = np.where(odd, d2, d1) | (overlap[pix[cap]] & (d1 | d2))
            capc = np.tile(np.asarray(CAP_COLOR, np.float32), (int(cap.sum()), 1))
            capc[dark] *= 0.72
            col[cap] = capc
        img[pix] = np.clip(col, 0, 1)
    img = img.reshape(H, W, 3)
    tb = tbuf.reshape(H, W)
    zb = zbuf.reshape(H, W)
    has_triangles = len(T) > 0
    # Silhouettes: owner changes, or depth steps that break the local depth plane
    # extrapolated from either neighbour by more than SILHOUETTE_JUMP_PX. A steep but
    # continuous surface seen nearly edge-on is not a silhouette (no hairline clusters).
    jump = SILHOUETTE_JUMP_PX / scale
    if len(covered):  # only the covered window (+1 px) can hold silhouettes
        rows, cols = covered // W, covered % W
        r0, r1 = max(int(rows.min()) - 1, 0), min(int(rows.max()) + 2, H)
        c0, c1 = max(int(cols.min()) - 1, 0), min(int(cols.max()) + 2, W)
        del rows, cols
        tw = tb[r0:r1, c0:c1]
        ow = np.where(tw >= 0, pr.tri_owner[np.maximum(tw, 0)], -1)
        zw = zb[r0:r1, c0:c1]
        hh, ww = r1 - r0, c1 - c0
        sil = np.zeros((hh, ww), bool)
        with np.errstate(invalid="ignore"):
            for dy, dx, grad in ((0, 1, gxbuf.reshape(H, W)[r0:r1, c0:c1]), (1, 0, gybuf.reshape(H, W)[r0:r1, c0:c1])):
                o1, o2 = ow[: hh - dy, : ww - dx], ow[dy:, dx:]
                z1, z2 = zw[: hh - dy, : ww - dx], zw[dy:, dx:]
                g1, g2 = grad[: hh - dy, : ww - dx], grad[dy:, dx:]
                diff = z2 - z1
                step = np.maximum(np.abs(diff - g1), np.abs(diff - g2))
                e = (o1 != o2) | (step > jump)
                e &= (o1 != -1) | (o2 != -1)  # not between two background pixels
                sil[: hh - dy, : ww - dx] |= e
        img[r0:r1, c0:c1][sil] *= 0.15
        del sil, ow, zw, tw
    del gxbuf, gybuf
    pil = Image.fromarray((img * 255 + 0.5).astype(np.uint8), "RGB")
    del img
    phases["raster"] = phases.get("raster", 0.0) + (time.perf_counter() - began) * 1000

    began = time.perf_counter()
    draw = ImageDraw.Draw(pil)
    padded = np.pad(zb, 1, constant_values=np.inf)
    zmin3 = padded[1:-1, 1:-1].copy()
    for oy in (0, 1, 2):
        for ox in (0, 1, 2):
            np.minimum(zmin3, padded[oy:oy + H, ox:ox + W], out=zmin3)
    del padded
    eps = max(4 * mm_per_px, 1e-5 * pr.diag)
    edge_stats = {"edges_drawn": 0, "edge_segments_end_on": 0, "edge_segments_short": 0}
    if edges and pr.edges:
        runs, _, st = _runs(cam, pr.edges, depth=zmin3, eps=eps, prepared=pr, drop=True)
        edge_stats["edges_drawn"] = _draw_runs(draw, runs, EDGE_COLOR, max(1, int(ss * 0.9)))
        edge_stats["edge_segments_end_on"], edge_stats["edge_segments_short"] = st["end_on"], st["short"]
    if pr.sketch_polylines:
        runs, _, st = _runs(cam, pr.sketch_polylines, depth=zmin3, eps=eps, prepared=pr, drop=True)
        edge_stats["sketch_runs_drawn"] = _draw_runs(draw, runs, SKETCH_COLOR, max(1, round(1.5 * ss)))
    edge_info = []
    for hi, entry in enumerate(pr.highlights):
        runs, visible, st = _runs(cam, entry["edges"], depth=zmin3, eps=eps, prepared=pr)
        _draw_runs(draw, runs, highlight_color(hi), max(1, round(3 * ss)), dots=True)
        longest = max(runs, key=len) if runs else None
        # visible: >= 1 output px of visible length, or (edges seen end-on, under 2 px
        # projected) any sample that passes the depth test
        ok = bool(runs) and (visible >= 1.0 or st.get("projected_px", 0.0) < 2.0)
        edge_info.append((visible, longest, ok))
    ghost_px = [0] * len(pr.highlights)
    if any(e["ghost"] for e in pr.highlights):
        arr = np.asarray(pil, dtype=np.float32)
        width = max(1, round(GHOST_WIDTH_PX * ss))
        for hi, entry in enumerate(pr.highlights):
            if not entry["ghost"]:
                continue
            mask = Image.new("L", (W, H), 0)
            mdraw = ImageDraw.Draw(mask)
            runs, _, _ = _runs(cam, entry["ghost_edges"], prepared=pr, dash_px=GHOST_DASH_PX)
            _draw_runs(mdraw, runs, 255, width, dots=True)
            for p in entry["ghost_points"]:
                X, Y, _ = cam.project(p)
                rad = VERTEX_RADIUS_PX * ss
                mdraw.ellipse((X[0] - rad, Y[0] - rad, X[0] + rad, Y[0] + rad), outline=255, width=width)
            m = np.asarray(mask, dtype=np.float32) / 255 * GHOST_ALPHA
            arr = arr * (1 - m[..., None]) + np.asarray(highlight_color(hi), np.float32) * m[..., None]
            small = np.asarray(mask.resize((w_out, h_out), Image.Resampling.BOX) if ss > 1 else mask)
            ghost_px[hi] = int((small >= 64).sum())
        pil = Image.fromarray(np.clip(arr + 0.5, 0, 255).astype(np.uint8), "RGB")
        del arr
    phases["edges"] = phases.get("edges", 0.0) + (time.perf_counter() - began) * 1000

    began = time.perf_counter()
    out = pil.resize((w_out, h_out), Image.Resampling.LANCZOS) if ss > 1 else pil
    del pil
    draw = ImageDraw.Draw(out)
    bold, small = _font(13 if w_out >= 400 else 11, True), _font(12 if w_out >= 400 else 10)
    tagbuf = (np.where(tb >= 0, pr.tri_tag[np.maximum(tb, 0)], _NO_TAG) if has_triangles
              else np.full((H, W), _NO_TAG, np.int32))
    rows, taken = [], []
    for hi, (item, entry) in enumerate(zip(scene.highlights, pr.highlights)):
        color = highlight_color(hi)
        anchor, face_px, face_anchor = None, 0.0, None
        if entry["faces"]:
            er = highlight_masks[hi]
            for _ in range(ss):  # erode ~1 output px: ignore silhouette leaks
                e2 = er.copy()
                e2[1:, :] &= er[:-1, :]
                e2[:-1, :] &= er[1:, :]
                e2[:, 1:] &= er[:, :-1]
                e2[:, :-1] &= er[:, 1:]
                er = e2
            ys_, xs_ = np.nonzero(er)
            face_px = len(xs_) / (ss * ss)
            if face_px >= LABEL_MIN_VISIBLE_PX:
                axp, ayp = (xs_ + 0.5) / ss, (ys_ + 0.5) / ss
                k = int(np.argmin((axp - axp.mean()) ** 2 + (ayp - ayp.mean()) ** 2))
                face_anchor = (float(axp[k]), float(ayp[k]))
        # faces need >= 6 eroded px; edges see edge_info; vertices the depth test
        edge_visible, longest, edges_ok = edge_info[hi]
        point_visible = []
        for p in entry["points"]:
            X, Y, Z = cam.project(p)
            ix, iy = int(np.floor(X[0])), int(np.floor(Y[0]))
            inside = 0 <= ix < W and 0 <= iy < H
            alive = bool(pr.kept(p[None, :])[0])
            vis = inside and alive and bool(Z[0] <= zmin3[iy, ix] + eps)
            point_visible.append(vis)
            qx, qy = float(X[0]) / ss, float(Y[0]) / ss
            rad = VERTEX_RADIUS_PX
            if not (inside and alive):
                continue
            if vis:
                draw.ellipse((qx - rad, qy - rad, qx + rad, qy + rad), fill=color, outline=(0, 0, 0))
            else:
                draw.ellipse((qx - rad, qy - rad, qx + rad, qy + rad), outline=color, width=2)
        visible = bool(face_anchor is not None or edges_ok or any(point_visible))
        if face_anchor is not None:
            anchor = face_anchor
        elif edges_ok:
            mid = longest[len(longest) // 2]
            anchor = (float(mid[0]) / ss, float(mid[1]) / ss)
        elif any(point_visible):
            p = entry["points"][point_visible.index(True)]
            anchor = cam.out(p)
        elif entry["reference"] is not None:
            anchor = cam.out(entry["reference"])
        elif entry["ghost_reference"] is not None:
            anchor = cam.out(entry["ghost_reference"])
        visible_px = face_px + (max(edge_visible, 1.0) if edges_ok else 0.0) + sum(point_visible)
        label_box = None
        if labels and anchor is not None:
            inside = 0 <= anchor[0] < w_out and HEADER_PX <= anchor[1] < h_out - FOOTER_PX
            if inside:
                text = item.label + ("" if visible else (" (hidden)" if entry["rendered"] else ""))
                label_box = _hollow_or_solid_label(draw, anchor, text, color, bold, visible, taken, w_out, h_out)
        rows.append({"label": item.label, "visible": visible, "visible_px": round(float(visible_px), 1),
                     "ghost_px": int(ghost_px[hi]), "rendered": entry["rendered"],
                     "anchor_px": None if anchor is None else [round(anchor[0], 1), round(anchor[1], 1)],
                     "label_box_px": label_box})
    if part_labels and scene.parts:
        partbuf = np.where((tb >= 0) & (tagbuf == TAG_PART), pr.tri_part[np.maximum(tb, 0)], -1)
        for pi, part in enumerate(scene.parts[:24]):
            ys_, xs_ = np.nonzero(partbuf == pi)
            if len(xs_) < 20 * ss * ss:
                continue
            axp, ayp = (xs_ + 0.5) / ss, (ys_ + 0.5) / ss
            k = int(np.argmin((axp - axp.mean()) ** 2 + (ayp - ayp.mean()) ** 2))
            text = _fit_text(draw, part.name or str(part.key), small, 140)
            bb = draw.textbbox((float(axp[k]), float(ayp[k])), text, font=small, anchor="mm")
            box = (bb[0] - 4, bb[1] - 2, bb[2] + 4, bb[3] + 2)
            rim = tuple(int(c * 160) for c in pr.part_colors[pi])
            draw.rounded_rectangle(box, radius=3, fill=(255, 255, 255), outline=rim, width=1)
            draw.text((float(axp[k]), float(ayp[k])), text, font=small, fill=TEXT, anchor="mm")
    banners = normalize_banners(scene.banners, len(pr.non_solid))
    _draw_header(draw, w_out, scene.title, name, scene.revision, pr.section is not None, banners)
    if labels and legend and scene.highlights:
        max_rows = max(1, int(0.3 * (h_out - HEADER_PX - FOOTER_PX)) // LEGEND_ROW_PX)
        _draw_legend(draw, _legend_rows(scene.highlights, rows, pr), 8, h_out - FOOTER_PX - 8,
                     w_out - 100, max_rows, small)
    _draw_footer(draw, w_out, h_out, mm_per_px, pr.section is not None, cam)
    phases["overlay"] = phases.get("overlay", 0.0) + (time.perf_counter() - began) * 1000

    section_info = None
    if pr.section is not None:
        keys = [p.key if p.key is not None else i for i, p in enumerate(scene.parts)]
        section_info = _plain({"origin": pr.section["origin"], "normal": pr.section["normal"],
                               "cap_faces": pr.cap_faces, "cap_failures": list(pr.cap_failures),
                               "cap_skipped_not_solid": list(pr.cap_skipped),
                               "overlapping_parts": [[keys[a], keys[b]] for a, b in overlap_pairs]})
    stats.update(edge_stats)
    info = {"view": name, "width": w_out, "height": h_out, "supersample": ss, "camera": cam.describe(),
            "highlights": rows, "section": section_info, "banners": [b["text"] for b in banners],
            "stats": stats}
    return out, info


# ---------------------------------------------------------------- jobs

def normalize_settings(settings):
    """Fill renderer defaults; the owner validates request limits beforehand."""
    s = dict(settings or {})
    section = s.get("section")
    views = list(s.get("views") or (["section"] if section else ["iso"]))
    if not views:
        raise ValueError("at least one view is required")
    layout = s.get("layout", "separate")
    if layout not in LAYOUTS:
        raise ValueError("layout must be one of " + ", ".join(LAYOUTS))
    if layout == "sheet" and len(views) < 2:
        raise ValueError("a sheet needs at least two views")
    size = s.get("size") or (DEFAULT_SHEET_SIZE if layout == "sheet" and len(views) >= 5 else DEFAULT_SIZE)
    quality = s.get("quality", "standard")
    if quality not in QUALITIES:
        raise ValueError("quality must be one of " + ", ".join(QUALITIES))
    frame = s.get("frame", "included")
    if not isinstance(frame, dict) and frame not in FRAMES:
        raise ValueError("frame must be one of " + ", ".join(FRAMES) + " or {center_mm, width_mm}")
    return {"views": views, "layout": layout, "size": [int(size[0]), int(size[1])], "frame": frame,
            "labels": bool(s.get("labels", True)), "part_labels": bool(s.get("part_labels", False)),
            "section": section, "edges": bool(s.get("edges", True)), "quality": quality}


def sheet_geometry(view_count, size, legend_rows=0):
    """(columns, rows, tile_w, tile_h, footer_h) for a sheet of ``view_count`` tiles filling ``size``."""
    columns = 2 if view_count <= 4 else 3
    rows = -(-view_count // columns)
    footer = SHEET_FOOTER_PX + LEGEND_ROW_PX * legend_rows
    tile_w = (int(size[0]) - (columns - 1) * SHEET_GAP_PX) // columns
    tile_h = (int(size[1]) - footer - (rows - 1) * SHEET_GAP_PX) // rows
    if tile_w < 64 or tile_h < HEADER_PX + FOOTER_PX + 16:
        raise ValueError("sheet tiles would be too small")
    return columns, rows, tile_w, tile_h, footer


def supersample_for(size, quality):
    if quality == "draft":
        return 1
    return 2 if int(size[0]) * int(size[1]) <= SUPERSAMPLE_MAX_PIXELS else 1


def estimate_tolerance(scene, cameras, sizes, frame="included", section=None, quality="standard"):
    """One tessellation tolerance per job (mm): 0.6 x the finest output mm/px, clamped
    to [1e-4, 2e-3] x the scene diagonal, rounded down to a power of two; doubled for draft."""
    bounds = _scene_bounds(scene)
    if bounds is None:
        raise RenderError("render_failed", "There is no geometry to draw.", reason="no_geometry")
    lo, hi = bounds
    diag = max(float(np.linalg.norm(hi - lo)), 1e-6)
    sec = normalize_section(section)
    box = _clip_box_points(lo, hi, sec)
    if not len(box):
        box = _clip_box_points(lo, hi, None)
    if frame == "model" and scene.model_bounds is not None:
        clipped = _clip_box_points(scene.model_bounds[0], scene.model_bounds[1], sec)
        box = clipped if len(clipped) else box
    elif frame == "highlights":
        hb = _highlight_bounds(scene)
        if hb is not None:
            box = _clip_box_points(*_expanded_box(*hb), None)
    finest = math.inf
    for (_, d, u, r), (w, h) in zip(cameras, sizes):
        if isinstance(frame, dict):
            mmpp = float(frame["width_mm"]) / int(w)
        else:
            span_x, span_y = float(np.ptp(box @ r)), float(np.ptp(box @ u))
            mmpp = max(span_x / (int(w) * (1 - 2 * MARGIN)),
                       span_y / ((int(h) - HEADER_PX - FOOTER_PX) * (1 - 2 * MARGIN)), 1e-12)
        finest = min(finest, mmpp)
    tol = min(max(TOLERANCE_PX * finest, TOLERANCE_MIN_DIAG * diag), TOLERANCE_MAX_DIAG * diag)
    tol = 2.0 ** math.floor(math.log2(tol))
    return tol * 2 if quality == "draft" else tol


def compose_sheet(tiles, size, columns, *, legend=(), note=CAPTION_NOTE):
    """Paste equal tiles into an image of exactly ``size`` with one shared legend/footer.

    Returns (image, [(x0, y0) per tile])."""
    W, H = int(size[0]), int(size[1])
    tw, th = tiles[0].size
    rows = -(-len(tiles) // columns)
    out = Image.new("RGB", (W, H), SHEET_BACKGROUND)
    origins = []
    for i, tile in enumerate(tiles):
        x0, y0 = (i % columns) * (tw + SHEET_GAP_PX), (i // columns) * (th + SHEET_GAP_PX)
        out.paste(tile, (x0, y0))
        origins.append((x0, y0))
    draw = ImageDraw.Draw(out)
    top = rows * th + (rows - 1) * SHEET_GAP_PX
    draw.rectangle((0, top, W, H), fill=BAND)
    small = _font(12)
    _draw_legend(draw, list(legend), 8, H - SHEET_FOOTER_PX + 2 - LEGEND_ROW_PX // 2 - 2, W - 16,
                 (H - top - SHEET_FOOTER_PX) // LEGEND_ROW_PX, small)
    draw.text((8, H - SHEET_FOOTER_PX / 2), _fit_text(draw, "orthographic tiles  |  " + note, small, W - 16),
              font=small, fill=MUTED_TEXT, anchor="lm")
    return out, origins


def write_png(image, path, metadata=None):
    """Write an RGB PNG with tEXt metadata; returns (bytes, sha256). Deterministic bytes."""
    path = Path(path)
    info = PngImagePlugin.PngInfo()
    for key, value in (metadata or {}).items():
        if value is not None:
            info.add_text(str(key), str(value))
    temporary = path.with_name(path.name + ".writing")
    image.convert("RGB").save(temporary, format="PNG", compress_level=PNG_COMPRESS_LEVEL, pnginfo=info)
    os.replace(temporary, path)
    data = path.read_bytes()
    return len(data), hashlib.sha256(data).hexdigest()


def _view_label(view):
    return view if isinstance(view, str) else str(view.get("name") or "custom")


def render_job(scene, settings, out_dir, *, metadata=None, limits=None):
    """Render every view of a job into ``out_dir`` (``view-<k>.png`` or ``sheet.png``).

    ``metadata`` supplies PNG tEXt values: ``document``, ``revision``,
    ``render_id`` and ``note`` (the image's ``view`` is added). Returns a
    JSON-safe result with images (file name relative to ``out_dir``, size,
    sha256, camera, tiles, highlight rows, section), tessellation, per-part
    triangle counts, banners and phases. Raises RenderError (``render_too_large``
    with reason ``triangles`` -- over ``max_triangles`` after coarsening, caps and
    highlights included, or past ``deadline_seconds`` with ``budget_seconds`` set --
    or ``memory``; ``highlight_not_rendered``; ``render_failed`` with reason
    ``no_geometry``) or ValueError for malformed settings.

    ``highlight_not_rendered`` and ``no_geometry`` are backstops: the owner checks
    both before it starts a worker, and the worker forwards only
    ``render_too_large`` with its details, so from a worker they arrive as plain
    ``render_failed``.
    """
    began = time.perf_counter()
    try:
        return _render_job(scene, settings, Path(out_dir), metadata or {}, limits, began)
    except MemoryError:
        raise RenderError("render_too_large", "The render ran out of memory.", reason="memory") from None


def _render_job(scene, settings, out_dir, metadata, limits, began):
    s = normalize_settings(settings)
    section = normalize_section(s["section"])
    views = s["views"]
    sheet = s["layout"] == "sheet"
    legend_rows = min(len(scene.highlights), 8) if s["labels"] and scene.highlights else 0
    if sheet:
        columns, _, tile_w, tile_h, _ = sheet_geometry(len(views), s["size"], legend_rows)
        sizes = [(tile_w, tile_h)] * len(views)
    else:
        sizes = [tuple(s["size"])] * len(views)
    cameras = [view_camera(v, section) for v in views]
    tolerance = estimate_tolerance(scene, cameras, sizes, s["frame"], section, s["quality"])
    phases = {}
    deadline = Deadline(dict(DEFAULT_LIMITS, **(limits or {})).get("deadline_seconds"), began)
    deadline.views = len(views)
    prepared = Prepared(scene, tolerance, section, limits=limits, phases=phases, deadline=deadline)
    if not len(prepared.T) and not prepared.sketch_polylines and not any(
            e["edges"] or e["points"] for e in prepared.highlights):
        raise RenderError("render_failed", "There is no geometry to draw.", reason="no_geometry")
    base_meta = {"KurtShape-document": metadata.get("document"), "revision": metadata.get("revision"),
                 "render_id": metadata.get("render_id"), "note": metadata.get("note", CAPTION_NOTE)}
    images, tiles = [], []
    for k, (view, size) in enumerate(zip(views, sizes)):
        deadline(len(prepared.T))
        image, info = render(scene, prepared, view, size, supersample=supersample_for(size, s["quality"]),
                             labels=s["labels"], part_labels=s["part_labels"], edges=s["edges"],
                             frame=s["frame"], legend=not sheet, phases=phases, deadline=deadline)
        if sheet:
            tiles.append((image, info))
            continue
        t = time.perf_counter()
        name = f"view-{k}.png"
        size_bytes, digest = write_png(image, out_dir / name, dict(base_meta, view=info["view"]))
        phases["png"] = phases.get("png", 0.0) + (time.perf_counter() - t) * 1000
        images.append({"view": info["view"], "file": name, "media_type": "image/png", "width": info["width"],
                       "height": info["height"], "bytes": size_bytes, "sha256": digest, "camera": info["camera"],
                       "tiles": None, "highlights": info["highlights"], "section": info["section"],
                       "supersample": info["supersample"], "stats": info["stats"]})
    if sheet:
        t = time.perf_counter()
        hidden_everywhere = [{"visible": any(info["highlights"][i]["visible"] for _, info in tiles)}
                             for i in range(len(scene.highlights))]
        legend = _legend_rows(scene.highlights, hidden_everywhere, prepared) if legend_rows else []
        composed, origins = compose_sheet([image for image, _ in tiles], s["size"], columns, legend=legend)
        tile_rows = []
        for (image, info), (x0, y0), view in zip(tiles, origins, views):
            camera = dict(info["camera"])
            camera["pixel_from_world"] = [[*row[:3], round(row[3] + off, 9)]
                                          for row, off in zip(camera["pixel_from_world"], (x0, y0))]
            rows = []
            for row in info["highlights"]:
                row = dict(row)
                if row["anchor_px"] is not None:
                    row["anchor_px"] = [round(row["anchor_px"][0] + x0, 1), round(row["anchor_px"][1] + y0, 1)]
                if row["label_box_px"] is not None:
                    b = row["label_box_px"]
                    row["label_box_px"] = [round(b[0] + x0, 1), round(b[1] + y0, 1),
                                           round(b[2] + x0, 1), round(b[3] + y0, 1)]
                rows.append(row)
            tile_rows.append({"view": info["view"], "box_px": [x0, y0, x0 + image.size[0], y0 + image.size[1]],
                              "camera": camera, "highlights": rows, "supersample": info["supersample"],
                              "stats": info["stats"]})
        size_bytes, digest = write_png(composed, out_dir / "sheet.png",
                                       dict(base_meta, view=",".join(t["view"] for t in tile_rows)))
        phases["png"] = phases.get("png", 0.0) + (time.perf_counter() - t) * 1000
        images.append({"view": "sheet", "file": "sheet.png", "media_type": "image/png", "width": composed.size[0],
                       "height": composed.size[1], "bytes": size_bytes, "sha256": digest, "camera": None,
                       "tiles": tile_rows, "highlights": None, "section": tiles[0][1]["section"],
                       "supersample": None, "stats": None})
    banners = normalize_banners(scene.banners, len(prepared.non_solid))
    phases["total"] = (time.perf_counter() - began) * 1000
    return {
        "renderer": RENDERER, "renderer_version": RENDERER_VERSION, "font": font_id(),
        "settings": _plain({k: v for k, v in s.items() if k != "section"}),
        "images": images,
        "tessellation": {"tolerance_mm": prepared.tolerance, "requested_tolerance_mm": prepared.requested_tolerance,
                         "angular_deflection_rad": prepared.angular_deflection,
                         "triangles": prepared.triangles, "cap_triangles": prepared.cap_triangles,
                         "highlight_triangles": prepared.highlight_triangles, "coarsened": prepared.coarsened,
                         "coarsen_steps": prepared.coarsen_steps, "coarsen_ladder": list(prepared.coarsen_ladder)},
        "parts": [_plain(p) for p in prepared.part_info],
        "non_solid_parts": list(prepared.non_solid),
        "highlights": [{"label": h.label, "rendered": e["rendered"], "ghost": e["ghost"]}
                       for h, e in zip(scene.highlights, prepared.highlights)],
        "banners": banners,
        "note": RESPONSE_NOTE,
        "phases": {k: round(v, 1) for k, v in phases.items()},
    }
