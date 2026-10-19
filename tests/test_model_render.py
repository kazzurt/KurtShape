"""Contract 3.2 model images: the pure software renderer (kurtshape.model_render).

In-process, synthetic shapes, small images. The owner-side service, worker
process and bridge paths are covered by test_render_jobs.
"""
import ast
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App
import Part
import numpy as np
from PIL import Image, ImageDraw
from kurtshape import model_render as mr

V = App.Vector
ALLOWED_IMPORTS = {"__future__", "functools", "hashlib", "importlib", "itertools", "math", "os", "pathlib", "sys",
                   "time", "numpy", "PIL", "FreeCAD", "Part", "MeshPart"}
CAP_TAN = (237, 204, 140)


def box_faces(shape):
    faces = {}
    for face in shape.Faces:
        n = face.normalAt(0, 0)
        faces[(round(n.x), round(n.y), round(n.z))] = face
    return faces


def project(camera, point):
    m = np.asarray(camera["pixel_from_world"], float)
    return m @ np.array([*point, 1.0])


def luminance(rgb):
    rgb = np.asarray(rgb, float)
    return 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]


def window(img, xy, radius=2):
    x, y = int(math.floor(xy[0])), int(math.floor(xy[1]))
    return img[max(y - radius, 0):y + radius + 1, max(x - radius, 0):x + radius + 1].reshape(-1, 3)


def hue_match(pixels, color, cos=0.985, min_chroma=40):
    """Pixels whose chroma direction matches ``color`` (shading scales brightness, not hue)."""
    p = np.asarray(pixels, float).reshape(-1, 3)
    c = np.asarray(color, float)
    pc, cc = p - p.mean(1, keepdims=True), c - c.mean()
    norm = np.linalg.norm(pc, axis=1) * np.linalg.norm(cc)
    with np.errstate(invalid="ignore", divide="ignore"):
        sim = (pc @ cc) / norm
    return (np.linalg.norm(pc, axis=1) >= min_chroma) & (sim >= cos)


def is_background(pixels):
    return np.all(np.asarray(pixels).reshape(-1, 3) >= 250, axis=1)


def welded_boundary_edges(prepared):
    """Edges used by one triangle after welding the part mesh by position (0 = watertight)."""
    part = prepared.tri_tag == mr.TAG_PART
    key = np.round(prepared.V / 1e-7).astype(np.int64)
    _, inverse = np.unique(key, axis=0, return_inverse=True)
    tri = inverse.ravel()[prepared.T[part]]
    edges = np.sort(np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]), axis=1)
    edges = edges[edges[:, 0] != edges[:, 1]]
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return int((counts == 1).sum())


class ModelRenderTests(unittest.TestCase):
    def job(self, scene, settings, *, limits=None, metadata=None):
        folder = support.scratch(self, prefix="model-render-")
        result = mr.render_job(scene, settings, folder, metadata=metadata, limits=limits)
        images = [np.asarray(Image.open(folder / image["file"]).convert("RGB")) for image in result["images"]]
        return result, images, folder

    def drawn_job(self, scene, settings, **kwargs):
        """``job`` that also records every string drawn with ImageDraw.text."""
        texts, original = [], ImageDraw.ImageDraw.text

        def spy(draw, xy, text, *args, **kw):
            texts.append(text)
            return original(draw, xy, text, *args, **kw)

        with patch.object(ImageDraw.ImageDraw, "text", spy):
            result, images, folder = self.job(scene, settings, **kwargs)
        return texts, result, images

    def box_scene(self, highlights=(), **kwargs):
        box = Part.makeBox(20, 10, 8)
        return box, mr.Scene([mr.ScenePart(box, name="Block", id="B")], highlights, title="Block", **kwargs)

    # ------------------------------------------------------------ purity and conventions

    def test_module_is_pure_and_never_imports_kurtshape(self):
        tree = ast.parse((ROOT / "src" / "kurtshape" / "model_render.py").read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0, "relative import in model_render")
                imported.add((node.module or "").split(".")[0])
        self.assertNotIn("kurtshape", imported)
        self.assertLessEqual(imported, ALLOWED_IMPORTS, imported - ALLOWED_IMPORTS)

    def test_section_and_camera_conventions_match_create_plane(self):
        xz = mr.section_from_plane("XZ", 5)
        self.assertEqual(xz, {"origin": [0.0, -5.0, 0.0], "normal": [0.0, -1.0, 0.0]})
        self.assertEqual(mr.section_from_plane("xy", 2)["origin"], [0.0, 0.0, 2.0])
        self.assertEqual(mr.section_from_plane("YZ", -3)["origin"], [-3.0, 0.0, 0.0])
        name, d, u, r = mr.view_camera("section", xz)
        self.assertEqual(name, "section")
        np.testing.assert_allclose(d, [0, 1, 0])  # looks along -normal: the front view
        np.testing.assert_allclose(u, [0, 0, 1])
        _, d, u, r = mr.view_camera("section", mr.section_from_plane("XY", 0))
        np.testing.assert_allclose(d, [0, 0, -1])  # the top view, up = Y
        np.testing.assert_allclose(u, [0, 1, 0])
        _, d, u, r = mr.view_camera({"direction": [0, 0, 5]})
        np.testing.assert_allclose(u, [0, 1, 0])  # default up becomes Y when looking along Z
        with self.assertRaises(ValueError):
            mr.view_camera({"direction": [1, 0, 0], "up": [2, 0, 0.01]})
        with self.assertRaises(ValueError):
            mr.view_camera({"direction": [0, 0, 0]})
        with self.assertRaises(ValueError):
            mr.normalize_section({"origin": [0, 0, 0], "normal": [0, 0, 0]})
        with self.assertRaises(ValueError):
            mr.view_camera("section")

    def test_box_iso_silhouette_and_three_shades(self):
        box, scene = self.box_scene()
        result, (img,), _ = self.job(scene, {"views": ["iso"], "size": [400, 300], "edges": False})
        camera = result["images"][0]["camera"]
        np.testing.assert_allclose(camera["direction"], np.array([-1, 1, -1]) / math.sqrt(3), atol=1e-9)
        shades = []
        for center in ((20, 5, 4), (10, 0, 4), (10, 5, 8)):  # +X, -Y and +Z face centres
            pixels = window(img, project(camera, center), 2)
            self.assertFalse(is_background(pixels).any())
            shades.append(float(np.median(luminance(pixels))))
        for a in range(3):
            for b in range(a + 1, 3):
                self.assertGreater(abs(shades[a] - shades[b]), 6, shades)
        # walking left from the image centre, the first non-background pixel is a dark silhouette
        cx, cy = project(camera, (10, 5, 4))
        row = img[int(cy)]
        first = next(x for x in range(int(cx), -1, -1) if is_background(row[x])[0]) + 1
        self.assertLess(float(luminance(row[first:first + 2]).min()), 100)

    def test_standard_view_conventions(self):
        base = Part.makeBox(20, 10, 8)
        marker = Part.makeBox(3, 3, 3, V(17, 0, 8))  # asymmetric: +X, -Y end, on top
        faces = box_faces(base)
        labels = {(1, 0, 0): "A", (0, -1, 0): "B", (0, 0, 1): "C", (-1, 0, 0): "D", (0, 1, 0): "E", (0, 0, -1): "F"}
        highlights = [mr.SceneHighlight(label, [faces[normal]]) for normal, label in labels.items()]
        scene = mr.Scene([mr.ScenePart(base, id="L"), mr.ScenePart(marker, id="M", color=(0.85, 0.1, 0.1))],
                         highlights, title="Conventions")
        views = ["front", "back", "right", "left", "top", "bottom", "iso"]
        result, images, _ = self.job(scene, {"views": views, "size": [320, 240], "quality": "draft", "labels": False})
        expected_visible = {"front": {"B"}, "back": {"E"}, "right": {"A"}, "left": {"D"}, "top": {"C"},
                            "bottom": {"F"}, "iso": {"A", "B", "C"}}
        axes = {"front": ((1, 0, 0), (0, 0, 1)), "back": ((-1, 0, 0), (0, 0, 1)), "right": ((0, 1, 0), (0, 0, 1)),
                "left": ((0, -1, 0), (0, 0, 1)), "top": ((1, 0, 0), (0, 1, 0)), "bottom": ((1, 0, 0), (0, -1, 0))}
        # centre of the marker face turned to each camera (the bottom view looks at the block instead)
        marker_probe = {"front": (18.5, 0, 9.5), "back": (18.5, 3, 9.5), "right": (20, 1.5, 9.5),
                        "left": (17, 1.5, 9.5), "top": (18.5, 1.5, 11), "bottom": (18.5, 1.5, 8),
                        "iso": (18.5, 1.5, 11)}
        marker_center = (18.5, 1.5, 9.5)
        for image, img in zip(result["images"], images):
            view, camera = image["view"], image["camera"]
            visible = {row["label"] for row in image["highlights"] if row["visible"]}
            self.assertEqual(visible, expected_visible[view], view)
            if view in axes:
                right, up = axes[view]
                np.testing.assert_allclose(camera["right"], right, atol=1e-9, err_msg=view)
                np.testing.assert_allclose(camera["up"], up, atol=1e-9, err_msg=view)
                origin = project(camera, (0, 0, 0))
                self.assertGreater(project(camera, right)[0] - origin[0], 0, view)   # +right is to the right
                self.assertLess(project(camera, up)[1] - origin[1], 0, view)         # +up is up the image
            marker_px = window(img, project(camera, marker_probe[view]), 1)
            self.assertEqual(bool(hue_match(marker_px, (220, 30, 30), cos=0.95).all()), view != "bottom", view)
        front = result["images"][0]["camera"]
        mx, my = project(front, marker_center)
        bx, by = project(front, (10, 0, 4))
        self.assertGreater(mx, bx)  # front: marker (+X end) on the right ...
        self.assertLess(my, by)     # ... and above the block (+Z up)

    # ------------------------------------------------------------ highlights and labels

    def test_occluded_highlight_hidden_label(self):
        box = Part.makeBox(20, 10, 8)
        faces = box_faces(box)
        scene = mr.Scene([mr.ScenePart(box, id="B")],
                         [mr.SceneHighlight("A", [faces[(1, 0, 0)]]), mr.SceneHighlight("D", [faces[(-1, 0, 0)]])],
                         title="Labels")
        result, (img,), _ = self.job(scene, {"views": ["iso"], "size": [480, 360]})
        rows = {row["label"]: row for row in result["images"][0]["highlights"]}
        self.assertEqual(mr.LABEL_MIN_VISIBLE_PX, 6)  # F2 §4.11: a face label needs >= 6 eroded px
        self.assertTrue(rows["A"]["visible"])
        self.assertGreaterEqual(rows["A"]["visible_px"], 6)
        self.assertFalse(rows["D"]["visible"])
        self.assertEqual(rows["D"]["visible_px"], 0.0)
        for label, solid in (("A", True), ("D", False)):
            x0, y0, x1, y1 = rows[label]["label_box_px"]
            center = img[int((y0 + y1) / 2) - 1:int((y0 + y1) / 2) + 2, int(x0) + 4:int(x0) + 7].reshape(-1, 3)
            color = mr.highlight_color(0 if label == "A" else 1)
            if solid:  # filled with the highlight colour
                self.assertTrue(hue_match(center, color, cos=0.95).any(), center)
            else:      # hollow: white fill, never a solid label on an occluded entity
                self.assertTrue(is_background(center).all(), center)

    def test_highlights_sharing_a_face_are_all_visible(self):
        box = Part.makeBox(20, 10, 8)
        top = box_faces(box)[(0, 0, 1)]
        every_face = mr.SceneHighlight("A", list(box.Faces), note="all faces")
        top_face = mr.SceneHighlight("B", [top], note="top face")
        settings = {"views": ["top", "iso"], "size": [480, 360]}
        for order in ((every_face, top_face), (top_face, every_face)):
            scene = mr.Scene([mr.ScenePart(box, id="B")], list(order), title="Shared")
            texts, result, images = self.drawn_job(scene, settings)
            specific = [h.label for h in order].index("B")  # the one-face highlight's colour index
            for image, img in zip(result["images"], images):
                rows = {row["label"]: row for row in image["highlights"]}
                self.assertTrue(rows["A"]["visible"] and rows["B"]["visible"], (image["view"], rows))
                self.assertGreater(rows["B"]["visible_px"], 1000)
                # the more specific highlight is drawn on top of the face both match, whatever the
                # order (probed away from the label anchors at the face centre)
                pixels = window(img, project(image["camera"], (3, 2, 8)), 3)
                self.assertTrue(hue_match(pixels, mr.highlight_color(specific)).all(), image["view"])
            top_rows = {row["label"]: row for row in result["images"][0]["highlights"]}
            self.assertEqual(top_rows["A"]["visible_px"], top_rows["B"]["visible_px"])  # the same face in the top view
            iso_camera, iso_img = result["images"][1]["camera"], images[1]
            self.assertTrue(hue_match(window(iso_img, project(iso_camera, (20, 5, 4)), 2),
                                      mr.highlight_color(1 - specific)).all())  # +X face: only A
            self.assertFalse(any("(hidden)" in text for text in texts), texts)

    def test_edge_and_vertex_highlights_depth_tested(self):
        box = Part.makeBox(20, 10, 8)
        visible_edge = next(e for e in box.Edges if e.BoundBox.YMax < 1e-9 and e.BoundBox.ZMin > 7.9
                            and e.BoundBox.XLength > 19)          # front-top edge (y=0, z=8)
        hidden_edge = next(e for e in box.Edges if e.BoundBox.YMin > 9.9 and e.BoundBox.ZMax < 1e-9
                           and e.BoundBox.XLength > 19)           # back-bottom edge (y=10, z=0)
        visible_vertex = next(v for v in box.Vertexes if (v.X, v.Y, v.Z) == (20, 0, 8))
        hidden_vertex = next(v for v in box.Vertexes if (v.X, v.Y, v.Z) == (0, 10, 0))
        highlights = [mr.SceneHighlight("E1", [visible_edge]), mr.SceneHighlight("E2", [hidden_edge]),
                      mr.SceneHighlight("V1", [visible_vertex]), mr.SceneHighlight("V2", [hidden_vertex])]
        scene = mr.Scene([mr.ScenePart(box, id="B")], highlights, title="Edges")
        result, (img,), _ = self.job(scene, {"views": ["iso"], "size": [480, 360], "labels": False})
        rows = {row["label"]: row for row in result["images"][0]["highlights"]}
        self.assertTrue(rows["E1"]["visible"])
        self.assertGreater(rows["E1"]["visible_px"], 20)
        self.assertFalse(rows["E2"]["visible"])
        self.assertTrue(rows["V1"]["visible"])
        self.assertFalse(rows["V2"]["visible"])
        camera = result["images"][0]["camera"]
        self.assertTrue(hue_match(window(img, project(camera, (10, 0, 8)), 1), mr.highlight_color(0)).any())
        self.assertFalse(hue_match(window(img, project(camera, (10, 10, 0)), 2), mr.highlight_color(1)).any())
        # a vertical edge seen end-on (top view) is a visible point, drawn as a dot ...
        vertical = next(e for e in box.Edges if e.BoundBox.ZLength > 7.9 and e.BoundBox.XMin > 19.9
                        and e.BoundBox.YMax < 1e-9)                 # x=20, y=0, z 0..8
        settings = {"views": ["top"], "size": [320, 240], "quality": "draft", "labels": False}
        end_on, (img,), _ = self.job(mr.Scene([mr.ScenePart(box, id="B")], [mr.SceneHighlight("E", [vertical])],
                                              title="End-on"), settings)
        row, camera = end_on["images"][0]["highlights"][0], end_on["images"][0]["camera"]
        self.assertTrue(row["visible"])
        self.assertGreaterEqual(row["visible_px"], 1)
        self.assertTrue(hue_match(window(img, project(camera, (20, 0, 8)), 2), mr.highlight_color(0)).any())
        # ... and stays hidden end-on under a plate that covers it
        plate = Part.makeBox(8, 6, 1, V(16, -3, 12))
        covered, (img,), _ = self.job(mr.Scene([mr.ScenePart(box, id="B"), mr.ScenePart(plate, id="P")],
                                               [mr.SceneHighlight("E", [vertical])], title="End-on"), settings)
        row, camera = covered["images"][0]["highlights"][0], covered["images"][0]["camera"]
        self.assertFalse(row["visible"])
        self.assertEqual(row["visible_px"], 0.0)
        self.assertFalse(hue_match(window(img, project(camera, (20, 0, 8)), 2), mr.highlight_color(0)).any())

    def test_highlight_face_outline_against_background(self):
        box = Part.makeBox(20, 10, 8)
        scene = mr.Scene([mr.ScenePart(box, id="B")], [mr.SceneHighlight("T", [box_faces(box)[(0, 0, 1)]])],
                         title="Outline")
        result, (img,), _ = self.job(scene, {"views": ["top"], "size": [320, 240], "quality": "draft",
                                             "edges": False, "labels": False})
        camera = result["images"][0]["camera"]
        # in the top view the highlighted face meets the background along the whole outline:
        # that boundary is a silhouette like any part's (owner -4 is not background)
        for corner_side in ((0, 5, 8), (20, 5, 8), (10, 0, 8), (10, 10, 8)):
            self.assertLess(float(luminance(window(img, project(camera, corner_side), 1)).min()), 60, corner_side)
        self.assertTrue(hue_match(window(img, project(camera, (10, 5, 8)), 3), mr.highlight_color(0)).all())

    def test_ghost_highlight_drawn_not_counted_visible(self):
        box = Part.makeBox(20, 10, 8)
        ghost_face = Part.makeBox(4, 4, 4, V(8, 3, 9)).Faces[0]  # history geometry above the block
        plain = mr.Scene([mr.ScenePart(box, id="B")], title="Ghost")
        ghosted = mr.Scene([mr.ScenePart(box, id="B")], [mr.SceneHighlight("G", ghosts=[ghost_face], note="pad face")],
                           title="Ghost")
        settings = {"views": ["iso"], "size": [480, 360]}
        base, (base_img,), _ = self.job(plain, settings)
        result, (img,), _ = self.job(ghosted, settings)
        row = result["images"][0]["highlights"][0]
        self.assertFalse(row["visible"])
        self.assertFalse(row["rendered"])
        self.assertEqual(row["visible_px"], 0.0)
        self.assertGreater(row["ghost_px"], 0)
        self.assertEqual(result["highlights"], [{"label": "G", "rendered": False, "ghost": True}])
        self.assertEqual(result["images"][0]["camera"], base["images"][0]["camera"])  # framing unchanged
        self.assertGreater(int((np.abs(img.astype(int) - base_img.astype(int)).sum(2) > 30).sum()), 50)
        with self.assertRaises(mr.RenderError) as caught:
            self.job(ghosted, dict(settings, frame="highlights"))
        self.assertEqual(caught.exception.code, "highlight_not_rendered")

    # ------------------------------------------------------------ sections

    def tube(self):
        return Part.makeCylinder(10, 30).cut(Part.makeCylinder(6, 30))

    def test_section_caps_clip_and_hatch(self):
        scene = mr.Scene([mr.ScenePart(self.tube(), name="Tube", id="T")], title="Tube")
        section = {"plane": "XZ", "offset": 0}
        result, (img, iso_img), _ = self.job(scene, {"views": ["section", "iso"], "section": section,
                                                     "size": [400, 300]})
        whole, (whole_img,), _ = self.job(scene, {"views": ["front"], "size": [400, 300]})
        info = result["images"][0]["section"]
        self.assertEqual(info["cap_faces"], 2)
        self.assertEqual((info["cap_failures"], info["cap_skipped_not_solid"], info["overlapping_parts"]), ([], [], []))
        np.testing.assert_allclose(info["normal"], [0, -1, 0])
        self.assertEqual(result["images"][1]["section"], info)  # the cut applies to every view
        camera = result["images"][0]["camera"]
        np.testing.assert_allclose(camera["direction"], [0, 1, 0])
        for x in (8, -8):  # the cut walls: hatched caps (two tan shades)
            pixels = window(img, project(camera, (x, 0, 15)), 4)
            tan = hue_match(pixels, (237, 204, 140), cos=0.97, min_chroma=20)
            self.assertGreater(int(tan.sum()), len(pixels) * 0.9)
            self.assertGreaterEqual(len(np.unique(luminance(pixels[tan]).round(-1))), 2)
            whole_px = window(whole_img, project(whole["images"][0]["camera"], (x, 0, 15)), 2)
            self.assertFalse(hue_match(whole_px, (237, 204, 140), cos=0.97, min_chroma=20).any())
        inner = window(img, project(camera, (0, 0, 15)), 2)  # the far half's inner surface, not a cap
        self.assertFalse(is_background(inner).any())
        self.assertFalse(hue_match(inner, (237, 204, 140), cos=0.97, min_chroma=20).any())

    def test_section_cap_failure_reported_and_no_culling(self):
        scene = mr.Scene([mr.ScenePart(self.tube(), id="T")], title="Tube")
        settings = {"views": ["section"], "section": {"plane": "XZ", "offset": 0}, "size": [400, 300]}
        with patch.object(Part, "makeFace", side_effect=RuntimeError("injected cap failure")):
            prepared = mr.Prepared(scene, 0.125, mr.section_from_plane("XZ", 0))
            result, (img,), _ = self.job(scene, settings)
        self.assertEqual(prepared.cap_failures, ["T"])
        self.assertEqual(prepared.cap_faces, 0)
        self.assertFalse(prepared.tri_cull.any())
        info = result["images"][0]["section"]
        self.assertEqual((info["cap_failures"], info["cap_faces"]), (["T"], 0))
        # without a cap the wall interior shows the (darkened) back side of the far outer wall
        wall = window(img, project(result["images"][0]["camera"], (8, 0, 15)), 1)
        self.assertFalse(is_background(wall).any())
        self.assertLess(float(luminance(wall).mean()), 160)

    def cap_dark_fraction(self, img, camera, point, radius=6):
        """Share of darker (hatch) pixels among the cap-coloured pixels around ``point``."""
        pixels = window(img, project(camera, point), radius)
        tan = hue_match(pixels, CAP_TAN, cos=0.97, min_chroma=20)
        self.assertGreater(int(tan.sum()), len(pixels) * 0.8, point)
        lum = luminance(pixels[tan])
        return float((lum < lum.max() - 20).mean())

    def test_overlapping_caps_deterministic(self):
        first, second = Part.makeBox(10, 10, 10), Part.makeBox(10, 10, 10, V(5, 5, 0))
        scene = mr.Scene([mr.ScenePart(first, id="P1"), mr.ScenePart(second, id="P2")], title="Overlap")
        settings = {"views": ["section"], "section": {"plane": "XY", "offset": 5}, "size": [400, 300]}
        result, (img,), _ = self.job(scene, settings)
        again, _, _ = self.job(scene, settings)
        self.assertEqual(result["images"][0]["sha256"], again["images"][0]["sha256"])
        self.assertEqual(result["images"][0]["section"]["overlapping_parts"], [["P1", "P2"]])
        swapped, _, _ = self.job(mr.Scene([mr.ScenePart(second, id="P2"), mr.ScenePart(first, id="P1")],
                                          title="Overlap"), settings)
        self.assertEqual(swapped["images"][0]["section"]["overlapping_parts"], [["P2", "P1"]])
        camera = result["images"][0]["camera"]
        self.assertGreater(self.cap_dark_fraction(img, camera, (7.5, 7.5, 5)),
                           self.cap_dark_fraction(img, camera, (2.5, 2.5, 5)) + 0.1)  # cross-hatched
        # The earlier part's cap is on top where both coincide: its outline inside the other
        # cap is a dark silhouette, the later part's outline there is not drawn (draft: crisp lines).
        draft = dict(settings, quality="draft")
        ordered, (ordered_img,), _ = self.job(scene, draft)
        reverse, (reverse_img,), _ = self.job(mr.Scene([mr.ScenePart(second, id="P2"), mr.ScenePart(first, id="P1")],
                                                       title="Overlap"), draft)
        for image, picture, winner_x, loser_x in ((ordered, ordered_img, 10, 5), (reverse, reverse_img, 5, 10)):
            cam = image["images"][0]["camera"]

            def darkest(x):  # across the outline x = const at y = 7.5, inside the overlap's y range
                left, right = project(cam, (x - 0.4, 7.5, 5)), project(cam, (x + 0.4, 7.5, 5))
                row = picture[int(left[1]), int(left[0]):int(right[0]) + 1]
                return float(luminance(row).min())

            self.assertLess(darkest(winner_x), 60, (image["images"][0]["section"], winner_x))
            self.assertGreater(darkest(loser_x), 100, (image["images"][0]["section"], loser_x))

    def test_compound_of_overlapping_solids_capped_per_solid(self):
        plate, pin = Part.makeBox(40, 40, 6, V(-20, -20, 0)), Part.makeCylinder(4, 20, V(0, 0, -7))
        cases = {"pin pressed through a plate": ([plate, pin], (0, 0), (12, 12)),
                 "box nested in a box": ([Part.makeBox(30, 30, 10), Part.makeBox(10, 10, 10, V(10, 10, 0))],
                                         (15, 15), (5, 5))}
        settings = {"views": ["section"], "size": [480, 360], "section": {"plane": "XY", "offset": 3}}
        for name, (solids, inside, outside) in cases.items():
            scene = mr.Scene([mr.ScenePart(Part.makeCompound(solids), id="C")], title="Compound")
            result, (img,), _ = self.job(scene, settings)
            info, camera = result["images"][0]["section"], result["images"][0]["camera"]
            # one cap per solid: the inner solid's section is material, not a hole in the outer cap
            self.assertEqual((info["cap_faces"], info["cap_failures"]), (2, []), name)
            self.assertEqual(info["overlapping_parts"], [["C", "C"]], name)  # one part, two overlapping solids
            self.assertFalse(is_background(window(img, project(camera, (*inside, 3)), 4)).any(), name)
            self.assertGreater(self.cap_dark_fraction(img, camera, (*inside, 3)),
                               self.cap_dark_fraction(img, camera, (*outside, 3)) + 0.1, name)  # cross-hatched
        # solids and parts that only touch share a cap boundary: no overlap is reported, even when
        # the boundary falls on pixel centres (x = 10 maps to supersampled pixel centres here)
        a, b = Part.makeBox(10, 10, 10), Part.makeBox(10, 10, 10, V(10, 0, 0))
        touching = {"parts": [mr.ScenePart(a, id="A"), mr.ScenePart(b, id="B")],
                    "solids": [mr.ScenePart(Part.makeCompound([a, b]), id="AB")]}
        for name, parts in touching.items():
            result, (img,), _ = self.job(mr.Scene(parts, title="Touching"),
                                         {"views": ["section"], "size": [1024, 768],
                                          "section": {"plane": "XY", "offset": 5},
                                          "frame": {"center_mm": [10.484375, 5, 5], "width_mm": 64}})
            info, camera = result["images"][0]["section"], result["images"][0]["camera"]
            self.assertEqual((info["cap_faces"], info["overlapping_parts"]), (2, []), name)
            x = project(camera, (10, 5, 5))[0] * 2  # supersampled coordinate of the shared boundary
            self.assertAlmostEqual(x - math.floor(x), 0.5, places=6)
            near, far = (self.cap_dark_fraction(img, camera, (x, 5, 5), radius=3) for x in (10.5, 15))
            self.assertLess(abs(near - far), 0.15, name)  # beside the boundary: B's own hatch only

    def test_non_solid_shell_two_sided_and_no_caps(self):
        shell = Part.Shell([f for f in Part.makeBox(10, 10, 10).Faces if f.normalAt(0, 0).z < 0.5])  # open top
        self.assertFalse(shell.Solids)
        scene = mr.Scene([mr.ScenePart(shell, id="S")], title="Open shell")
        result, (img,), _ = self.job(scene, {"views": ["top"], "size": [400, 300]})
        inside = window(img, project(result["images"][0]["camera"], (5, 5, 0)), 2)
        self.assertFalse(is_background(inside).any())  # the floor's back side is still drawn
        self.assertLess(float(luminance(inside).mean()), 200)
        self.assertEqual(result["non_solid_parts"], ["S"])
        self.assertEqual([b["text"] for b in result["banners"]], ["NOT A SOLID: 1 PART"])
        sectioned, _, _ = self.job(scene, {"views": ["top"], "size": [400, 300],
                                           "section": {"plane": "XY", "offset": 5}})
        info = sectioned["images"][0]["section"]
        self.assertEqual((info["cap_faces"], info["cap_skipped_not_solid"], info["cap_failures"]), (0, ["S"], []))

    # ------------------------------------------------------------ edges

    def test_seam_detection_one_pass_matches_ancestors(self):
        block = Part.makeBox(10, 10, 10)
        shapes = {"cylinder": Part.makeCylinder(3, 8), "cone": Part.makeCone(3, 0, 8), "torus": Part.makeTorus(8, 2),
                  "sphere": Part.makeSphere(4), "box": Part.makeBox(4, 5, 6),
                  "filleted": block.makeFillet(2, block.Edges[:4]),
                  "drilled": Part.makeBox(10, 10, 10).cut(Part.makeCylinder(2, 10, V(5, 5, 0)))}
        for name, shape in shapes.items():
            drawn = {edge.hashCode() for edge in mr.feature_edges(shape)}
            oracle = {edge.hashCode() for edge in shape.Edges
                      if len(shape.ancestorsOfType(edge, Part.Face)) != 1 and not edge.Degenerated}
            self.assertEqual(drawn, oracle, name)
        self.assertEqual(len(mr.feature_edges(shapes["cylinder"])), 2)  # two rims, no seam
        self.assertEqual(mr.feature_edges(shapes["torus"]), [])
        open_tube = Part.Shell([f for f in Part.makeCylinder(3, 8).Faces if f.Surface.__class__.__name__ == "Cylinder"])
        boundaries = mr.feature_edges(open_tube, solid_faces=set(), solid=False)
        self.assertEqual(len(boundaries), 2)  # open boundaries drawn, the seam is not
        self.assertTrue(all(edge.Curve.__class__.__name__ == "Circle" for edge in boundaries))

    def test_end_on_edge_segments_dropped(self):
        helix = Part.makeHelix(400, 100, 1)  # tangent within 1 degree of +Z
        points = np.array([(p.x, p.y, p.z) for p in helix.discretize(Deflection=0.001)])
        for view, end_on in (("top", True), ("front", False)):
            _, d, u, r = mr.view_camera(view)
            camera = mr._Camera(view, d, u, r, 0.0, 0.0, 50.0, 20.0, 800, 600, 300.0, 1)
            runs, _, stats = mr._runs(camera, [points], drop=True)
            if end_on:
                self.assertEqual(runs, [])
                self.assertGreater(stats["end_on"], 0)
            else:
                self.assertTrue(runs)
                self.assertEqual(stats["end_on"], 0)
        # a tall pyramid: its lateral edges converge end-on in the top view
        apex, base = V(0, 0, 200), [V(-2, -2, 0), V(2, -2, 0), V(2, 2, 0), V(-2, 2, 0)]
        faces = [Part.Face(Part.makePolygon(base + [base[0]]))]
        faces += [Part.Face(Part.makePolygon([base[i], base[(i + 1) % 4], apex, base[i]])) for i in range(4)]
        pyramid = Part.Solid(Part.Shell(faces))
        scene = mr.Scene([mr.ScenePart(pyramid, id="P")], title="Pyramid")
        result, images, _ = self.job(scene, {"views": ["top", "front", "iso"], "size": [320, 240], "quality": "draft"})
        top, front, iso = (image["stats"] for image in result["images"])
        self.assertGreaterEqual(top["edge_segments_end_on"], 4)   # the four lateral edges
        self.assertEqual(front["edge_segments_end_on"], 2)        # the two base edges parallel to Y
        self.assertEqual(iso["edge_segments_end_on"], 0)
        # The rendered end-on view has no line cluster: the steep lateral faces converge on the
        # apex, but a continuous surface seen nearly edge-on is not a silhouette (slope-aware
        # depth test), so the footprint stays shaded instead of turning black.
        camera, img = result["images"][0]["camera"], images[0]
        (x0, y0), (x1, y1) = project(camera, (-2, 2, 0)), project(camera, (2, -2, 0))
        footprint = img[int(y0) + 2:int(y1) - 2, int(x0) + 2:int(x1) - 2]
        self.assertGreater(footprint.size, 3 * 100 * 100)
        self.assertLess(float((luminance(footprint) < 60).mean()), 0.1)
        for centre in ((0, -1.2, 0), (1.2, 0, 0), (0, 1.2, 0), (-1.2, 0, 0)):  # the four lateral faces
            self.assertGreater(float(luminance(window(img, project(camera, centre), 3)).mean()), 50, centre)
        # ... while a true self-occlusion inside one part stays a dark line, also when the
        # occluding face is seen at a grazing angle: a channel's low front wall hides part of
        # its back wall in a low view (edges off, so only the silhouette rule draws it).
        channel = Part.makeBox(20, 12, 1).fuse([Part.makeBox(20, 2, 6), Part.makeBox(20, 2, 12, V(0, 10, 0))])
        low, (img,), _ = self.job(mr.Scene([mr.ScenePart(channel.removeSplitter(), id="U")], title="Channel"),
                                  {"views": [{"direction": [0, 1, -0.2], "name": "low"}], "size": [400, 300],
                                   "quality": "draft", "edges": False})
        camera = low["images"][0]["camera"]
        x, y = project(camera, (10, 2, 6))  # the front wall's top-back edge, in front of the back wall
        self.assertLess(float(luminance(img[int(y) - 3:int(y) + 4, int(x)]).min()), 60)
        self.assertGreater(float(luminance(window(img, project(camera, (10, 10, 10)), 2)).min()), 60)

    def test_sketch_wires_drawn_depth_tested(self):
        box = Part.makeBox(20, 10, 8)
        behind = Part.makePolygon([V(-6, 20, 2), V(26, 20, 2), V(26, 20, 6), V(-6, 20, 6), V(-6, 20, 2)])
        front = Part.makePolygon([V(4, -5, 1), V(16, -5, 1)])
        scene = mr.Scene([mr.ScenePart(box, id="B")], sketches=[behind, front], title="Sketch")
        result, (img,), _ = self.job(scene, {"views": ["front"], "size": [480, 360]})
        camera = result["images"][0]["camera"]
        blue = mr.SKETCH_COLOR
        self.assertTrue(hue_match(window(img, project(camera, (-4, 20, 2)), 2), blue, cos=0.97).any())
        self.assertFalse(hue_match(window(img, project(camera, (10, 20, 2)), 2), blue, cos=0.97).any())
        self.assertTrue(hue_match(window(img, project(camera, (10, -5, 1)), 2), blue, cos=0.97).any())
        sketch_only, (sk_img,), _ = self.job(mr.Scene([], sketches=[Part.makeCircle(5)], title="Sketch only"),
                                             {"views": ["top"], "size": [320, 240]})
        self.assertEqual(sketch_only["tessellation"]["triangles"], 0)
        self.assertTrue(hue_match(window(sk_img, project(sketch_only["images"][0]["camera"], (5, 0, 0)), 2),
                                  blue, cos=0.97).any())

    # ------------------------------------------------------------ bands, output and limits

    def test_banner_and_caption_bands_drawn(self):
        _, scene = self.box_scene(banners=["validation_pending", {"kind": "rolled_back", "index": 2, "length": 5},
                                           "build_failed"], revision="0123456789abcdef")
        drawn, result, (img,) = self.drawn_job(scene, {"views": ["iso"], "size": [640, 360]})
        texts = [b["text"] for b in result["banners"]]
        self.assertEqual(texts, ["RETAINED GEOMETRY \u00b7 BUILD FAILED", "VALIDATION PENDING", "ROLLED BACK 2/5"])
        self.assertEqual(result["note"], mr.RESPONSE_NOTE)
        self.assertIn("do not establish geometric validity", result["note"])
        self.assertEqual(mr.CAPTION_NOTE, "display mesh, not a validity check")
        self.assertIn("RETAINED GEOMETRY \u00b7 BUILD FAILED", drawn)  # the first two banners, then "+1"
        self.assertIn("VALIDATION PENDING", drawn)
        self.assertIn("+1", drawn)
        self.assertTrue(any(text.endswith("|  " + mr.CAPTION_NOTE) for text in drawn), drawn)
        self.assertEqual(result["images"][0]["camera"]["projection"], "orthographic")
        header, footer = img[:mr.HEADER_PX - 2], img[-(mr.FOOTER_PX - 3):]
        self.assertTrue((header[2:5, 2:5] == mr.BAND).all())
        red = np.all(np.abs(header.astype(int) - mr.BANNER_COLORS["red"]) <= 2, axis=2)
        amber = np.all(np.abs(header.astype(int) - mr.BANNER_COLORS["amber"]) <= 2, axis=2)
        self.assertGreater(int(red.sum()), 200)
        self.assertGreater(int(amber.sum()), 200)
        self.assertGreater(float(np.flatnonzero(red.any(0)).mean()), img.shape[1] / 2)  # right-aligned
        self.assertTrue((footer[-3:, 2:5] == mr.BAND).all())
        caption = luminance(footer[:, : img.shape[1] // 2]) < 150
        self.assertGreater(int(caption.sum()), 60)  # caption text, including the validity note
        self.assertEqual(mr.normalize_banners([], non_solid=2)[0]["text"], "NOT A SOLID: 2 PARTS")
        with self.assertRaises(ValueError):
            mr.banner("unknown_kind")

    def test_small_images_keep_banner_and_validity_note(self):
        _, scene = self.box_scene(banners=["build_failed", "validation_pending"], revision="0123456789abcdef")
        self.assertEqual(mr.banner_forms("RETAINED GEOMETRY · BUILD FAILED"),
                         ["RETAINED GEOMETRY · BUILD FAILED", "RETAINED · BUILD FAILED", "RETAINED · FAILED"])
        self.assertEqual(mr.banner_forms("RETAINED GEOMETRY · NEEDS REBUILD")[-1], "RETAINED · REBUILD")
        self.assertEqual(mr.banner_forms("NOT A SOLID: 3 PARTS")[-1], "NOT SOLID: 3")
        # every size the contract allows (>= 128 px a side) states the retained geometry in the
        # header and carries the validity note in the caption; the scale bar and triad go first
        for size in ((128, 128), (160, 128), (200, 150), (256, 192), (320, 240), (1024, 768)):
            drawn, result, _ = self.drawn_job(scene, {"views": ["iso"], "size": list(size), "quality": "draft"})
            self.assertNotIn("", drawn, size)
            self.assertTrue(any(t.startswith("RETAINED") and t.endswith("FAILED") for t in drawn), (size, drawn))
            self.assertTrue("+1" in drawn or "VALIDATION PENDING" in drawn, (size, drawn))  # the second banner
            self.assertTrue(any(t.endswith("not a validity check") for t in drawn), (size, drawn))
            scale_labels = [text for text in drawn if re.fullmatch(r"[0-9.e+-]+ mm", text)]
            if size[0] <= 160:  # the scale bar and its label make room for the note first
                self.assertEqual(scale_labels, [], (size, drawn))
            if size[0] >= 320:
                self.assertEqual(len(scale_labels), 1, (size, drawn))
                self.assertIn("RETAINED GEOMETRY · BUILD FAILED", drawn, size)
            if size[0] >= 1024:
                self.assertTrue(any(t.endswith(mr.CAPTION_NOTE) and "orthographic" in t for t in drawn), drawn)
        # a sheet's shared footer carries the note too
        drawn, result, _ = self.drawn_job(scene, {"views": ["iso", "top"], "layout": "sheet", "size": [640, 360],
                                                  "quality": "draft"})
        self.assertTrue(any(t.endswith(mr.CAPTION_NOTE) and t.startswith("orthographic tiles") for t in drawn), drawn)
        self.assertEqual(result["note"], mr.RESPONSE_NOTE)

    def test_deterministic_bytes(self):
        box = Part.makeBox(20, 10, 8)
        faces = box_faces(box)
        scene = mr.Scene([mr.ScenePart(box, id="B")], [mr.SceneHighlight("A", [faces[(0, 0, 1)]], note="top")],
                         title="Determinism", revision="feedface")
        metadata = {"document": "doc-1", "revision": "feedface", "render_id": "0123456789abcdef"}
        settings = {"views": ["iso", "section"], "section": {"plane": "YZ", "offset": 10}, "size": [320, 240]}
        first, _, folder_a = self.job(scene, settings, metadata=metadata)
        second, _, folder_b = self.job(scene, settings, metadata=metadata)
        for a, b in zip(first["images"], second["images"]):
            self.assertEqual(a["sha256"], b["sha256"])
            data = (folder_a / a["file"]).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), a["sha256"])
            self.assertEqual(len(data), a["bytes"])
            self.assertEqual((folder_a / a["file"]).read_bytes(), (folder_b / b["file"]).read_bytes())
        strip = (lambda r: {k: v for k, v in r.items() if k != "phases"})
        self.assertEqual(json.dumps(strip(first), sort_keys=True), json.dumps(strip(second), sort_keys=True))
        png = Image.open(folder_a / first["images"][0]["file"])
        self.assertEqual(png.mode, "RGB")
        self.assertEqual(png.size, (320, 240))
        self.assertEqual(png.text["KurtShape-document"], "doc-1")
        self.assertEqual(png.text["revision"], "feedface")
        self.assertEqual(png.text["view"], "iso")
        self.assertEqual(png.text["render_id"], "0123456789abcdef")
        self.assertIn("not a validity check", png.text["note"])
        self.assertEqual(sorted(p.name for p in folder_a.iterdir()), ["view-0.png", "view-1.png"])

    def test_tolerance_coarsening_and_too_large(self):
        # F2 §4.2 / §6 numbers, pinned here rather than read back from the module
        self.assertEqual(mr.DEFAULT_LIMITS, {"coarsen_triangles": 1_500_000, "coarsen_steps": 3,
                                             "max_triangles": 2_500_000, "fragment_budget": 2_000_000,
                                             "chunk_triangles": 32_768, "deadline_seconds": 18.0})
        self.assertEqual((mr.ANGULAR_DEFLECTION, mr.ANGULAR_DEFLECTION_MAX, mr.COARSEN_MIN_REDUCTION), (0.25, 0.5, 0.1))
        from kurtshape import render_worker  # the job budget ends well inside the worker's limit
        self.assertLessEqual(mr.DEFAULT_LIMITS["deadline_seconds"], render_worker.JOB_TIMEOUT_SECONDS - 5)
        torus = Part.makeTorus(10, 3)
        scene = mr.Scene([mr.ScenePart(torus, id="T")], title="Torus")
        settings = {"views": ["iso"], "size": [320, 240], "quality": "draft"}
        plain, _, _ = self.job(scene, settings)
        tess = plain["tessellation"]
        self.assertEqual(math.log2(tess["tolerance_mm"]), round(math.log2(tess["tolerance_mm"])))  # a power of two
        self.assertEqual((tess["coarsened"], tess["angular_deflection_rad"]), (False, 0.25))
        self.assertEqual(tess["coarsen_ladder"], [tess["triangles"]])
        # The mesh is whole-shape BRepMesh output read back face by face: watertight, with the
        # angular deflection applied (Part.tessellate fixes 0.1 rad and makes several times more).
        block = Part.makeBox(10, 10, 10)
        for name, shape in (("torus", torus), ("filleted", block.makeFillet(2, block.Edges[:4])),
                            ("drilled", block.cut(Part.makeCylinder(2, 10, V(5, 5, 0)))),
                            ("torus and box", Part.makeTorus(8, 3).fuse(Part.makeBox(4, 4, 8, V(6, -2, -4))))):
            prepared = mr.Prepared(mr.Scene([mr.ScenePart(shape, id=name)]), 0.01)
            self.assertEqual(welded_boundary_edges(prepared), 0, name)
            self.assertLess(prepared.triangles * 2, len(shape.copy().tessellate(0.01)[1]), name)
        # Coarsening doubles tolerance and angle (decoupled from the job's clamp: explicit tolerance)
        fine = mr.Prepared(scene, 0.01)
        coarse = mr.Prepared(scene, 0.01, limits={"coarsen_triangles": fine.coarsen_ladder[0] - 1})
        self.assertEqual((coarse.coarsened, coarse.coarsen_steps, coarse.tolerance, coarse.angular_deflection),
                         (True, 1, 0.02, 0.5))
        self.assertLess(coarse.triangles, fine.triangles * 0.7)  # a step that pays
        self.assertEqual(len(coarse.coarsen_ladder), 2)
        wide = mr.Scene([mr.ScenePart(Part.makeCylinder(100, 20), id="W")])  # bound by the linear tolerance
        fine = mr.Prepared(wide, 0.004)
        coarser = mr.Prepared(wide, 0.004, limits={"coarsen_triangles": fine.coarsen_ladder[0] - 1})
        self.assertEqual((coarser.coarsened, coarser.coarsen_steps, coarser.tolerance), (True, 1, 0.008))
        self.assertLess(coarser.triangles, fine.triangles)
        # A step that removes < 10 % stops the ladder: planar faces never shrink, so the box is
        # meshed twice (not four times) and keeps its finer mesh; above the hard limit it refuses.
        boxes = mr.Scene([mr.ScenePart(Part.makeBox(20, 10, 8), id="B")])
        calls, real = [], mr.mesh_shape
        with patch.object(mr, "mesh_shape", side_effect=lambda shape, *a: calls.append(a) or real(shape, *a)):
            flat = mr.Prepared(boxes, 0.01, limits={"coarsen_triangles": 1})
            self.assertEqual(calls, [(0.01, 0.25), (0.02, 0.5)])
            self.assertEqual((flat.coarsened, flat.coarsen_steps, flat.tolerance, flat.coarsen_ladder),
                             (False, 0, 0.01, [12, 12]))
            calls.clear()
            with self.assertRaises(mr.RenderError) as caught:
                mr.Prepared(boxes, 0.01, limits={"coarsen_triangles": 1, "max_triangles": 11})
            self.assertEqual(len(calls), 2)
        error = caught.exception.as_error()
        self.assertEqual((error["code"], error["reason"], error["triangles"], error["limit"]),
                         ("render_too_large", "triangles", 12, 11))
        with self.assertRaises(mr.RenderError) as caught:
            self.job(scene, settings, limits={"coarsen_triangles": 10, "max_triangles": 20})
        error = caught.exception.as_error()
        self.assertEqual((error["code"], error["reason"], error["limit"]), ("render_too_large", "triangles", 20))
        # section caps and highlight faces count toward the limit too (12 part + 12 highlight triangles)
        _, highlighted = self.box_scene([mr.SceneHighlight("A", list(Part.makeBox(20, 10, 8).Faces))])
        with self.assertRaises(mr.RenderError) as caught:
            mr.Prepared(highlighted, 0.01, limits={"coarsen_triangles": 20, "max_triangles": 20})
        self.assertEqual((caught.exception.details["reason"], caught.exception.details["triangles"]), ("triangles", 24))
        # the job's time budget fails the same deterministic way (reason triangles, with the budget)
        with self.assertRaises(mr.RenderError) as caught:
            self.job(scene, dict(settings, views=["iso", "top"]), limits={"deadline_seconds": 0.0})
        error = caught.exception.as_error()
        self.assertEqual((error["code"], error["reason"], error["budget_seconds"], error["views"]),
                         ("render_too_large", "triangles", 0.0, 2))
        # the job tolerance: 0.6 x the finest mm/px, rounded down to a power of two (unclamped here) ...
        cube = mr.Scene([mr.ScenePart(Part.makeBox(100, 100, 100), id="C")])
        _, d, u, r = iso = mr.view_camera("iso")
        corners = np.array([[x, y, z] for x in (0, 100) for y in (0, 100) for z in (0, 100)], float)
        mm_per_px = max(np.ptp(corners @ r) / (1024 * 0.88), np.ptp(corners @ u) / ((768 - 30 - 24) * 0.88))
        expected = 2.0 ** math.floor(math.log2(0.6 * mm_per_px))
        self.assertTrue(1e-4 * 100 * math.sqrt(3) < 0.6 * mm_per_px < 2e-3 * 100 * math.sqrt(3))
        self.assertEqual(mr.estimate_tolerance(cube, [iso], [(1024, 768)]), expected)
        self.assertEqual(expected, 0.125)
        # ... clamped to [1e-4, 2e-3] x the diagonal, and doubled for draft
        cameras = [mr.view_camera("iso")]
        standard = mr.estimate_tolerance(scene, cameras, [(320, 240)])
        self.assertEqual(mr.estimate_tolerance(scene, cameras, [(320, 240)], quality="draft"), standard * 2)
        diag = torus.BoundBox.DiagonalLength
        self.assertLessEqual(standard, 2e-3 * diag)
        tiny = mr.estimate_tolerance(scene, cameras, [(320, 240)], frame={"center_mm": [0, 0, 0], "width_mm": 0.01})
        self.assertEqual(tiny, 2.0 ** math.floor(math.log2(1e-4 * diag)))

    def test_memory_error_maps_to_render_too_large(self):
        _, scene = self.box_scene()
        with patch.object(mr, "rasterize", side_effect=MemoryError):
            with self.assertRaises(mr.RenderError) as caught:
                self.job(scene, {"views": ["iso"], "size": [320, 240], "quality": "draft"})
        self.assertEqual((caught.exception.code, caught.exception.details), ("render_too_large", {"reason": "memory"}))

    def test_renderer_errors_on_the_worker_wire(self):
        """Pins what reaches the owner through render_worker (N3): render_too_large with its
        details; the renderer's backstops highlight_not_rendered and no_geometry arrive as plain
        render_failed, so the owner checks both itself before starting a worker (F2 §2.2, §3)."""
        from kurtshape import render_worker
        box = Part.makeBox(20, 10, 8)
        ghost_only = mr.Scene([mr.ScenePart(box, id="B")], [mr.SceneHighlight("G", ghosts=[box.Faces[0]])])
        wire_only = mr.Scene([mr.ScenePart(Part.makeCompound([box.Edges[0]]), id="W")])
        settings = {"views": ["iso"], "size": [320, 240], "quality": "draft"}
        failures = {}
        for name, scene, extra, limits in (("highlight_not_rendered", ghost_only, {"frame": "highlights"}, None),
                                           ("no_geometry", wire_only, {}, None),
                                           ("triangles", ghost_only, {}, {"max_triangles": 5, "coarsen_triangles": 5}),
                                           ("budget", ghost_only, {}, {"deadline_seconds": 0.0})):
            with self.assertRaises(mr.RenderError) as caught:
                self.job(scene, dict(settings, **extra), limits=limits)
            failures[name] = caught.exception
        self.assertEqual(failures["highlight_not_rendered"].code, "highlight_not_rendered")
        self.assertEqual((failures["no_geometry"].code, failures["no_geometry"].details), ("render_failed",
                                                                                          {"reason": "no_geometry"}))
        for name in ("highlight_not_rendered", "no_geometry"):
            wire = render_worker._child_error(failures[name], "render")
            self.assertEqual((wire["code"], wire["phase"]), ("render_failed", "render"), name)
            self.assertNotIn("reason", wire)
            self.assertIn(failures[name].message, wire["message"])
        wire = render_worker._child_error(failures["triangles"], "render")
        self.assertEqual((wire["code"], wire["reason"], wire["triangles"], wire["limit"]),
                         ("render_too_large", "triangles", 12, 5))
        wire = render_worker._child_error(failures["budget"], "render")
        self.assertEqual((wire["code"], wire["reason"], wire["budget_seconds"], wire["views"]),
                         ("render_too_large", "triangles", 0.0, 1))
        parent = render_worker._child_error_from({"ok": False, "error": wire})
        self.assertEqual((parent.code, parent.deterministic, parent.details["budget_seconds"]),
                         ("render_too_large", True, 0.0))

    def test_sheet_tiles_and_shared_legend(self):
        box = Part.makeBox(20, 10, 8)
        faces = box_faces(box)
        scene = mr.Scene([mr.ScenePart(box, id="B")],
                         [mr.SceneHighlight("A", [faces[(0, 0, 1)]], note="top face"),
                          mr.SceneHighlight("B", [faces[(1, 0, 0)]], note="end face")], title="Sheet")
        # F2 §3: 2 columns up to 4 views, else 3; sheet tiles share one footer and legend
        self.assertEqual([mr.sheet_geometry(n, (1536, 1152))[0] for n in (2, 3, 4, 5, 6, 7)], [2, 2, 2, 3, 3, 3])
        self.assertEqual(mr.normalize_settings({"views": ["iso"] * 5, "layout": "sheet"})["size"], [1536, 1152])
        result, (img,), folder = self.job(scene, {"views": ["iso", "front", "top"], "layout": "sheet",
                                                  "size": [960, 720]})
        self.assertEqual(len(result["images"]), 1)
        sheet = result["images"][0]
        self.assertEqual((sheet["file"], sheet["view"], sheet["width"], sheet["height"]), ("sheet.png", "sheet", 960, 720))
        self.assertEqual(img.shape, (720, 960, 3))
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["sheet.png"])
        tiles = sheet["tiles"]
        self.assertEqual([t["view"] for t in tiles], ["iso", "front", "top"])
        boxes = [t["box_px"] for t in tiles]
        self.assertEqual(boxes[0][0], 0)
        self.assertEqual(boxes[1][1], 0)          # two columns
        self.assertGreater(boxes[2][1], boxes[0][3])
        for tile in tiles:                        # tile cameras are in sheet pixels
            x0, y0, x1, y1 = tile["box_px"]
            px, py = project(tile["camera"], (10, 5, 4))
            self.assertTrue(x0 <= px < x1 and y0 <= py < y1, tile)
            for row in tile["highlights"]:
                if row["anchor_px"] is not None:
                    self.assertTrue(x0 <= row["anchor_px"][0] < x1 and y0 <= row["anchor_px"][1] < y1)
        footer_top = max(b[3] for b in boxes)
        self.assertGreaterEqual(720 - footer_top, mr.SHEET_FOOTER_PX + 2 * mr.LEGEND_ROW_PX)
        footer = img[footer_top:, :40]
        for i in range(2):  # one shared legend with both swatches
            swatch = np.all(np.abs(footer.astype(int) - mr.highlight_color(i)) <= 2, axis=2)
            self.assertGreater(int(swatch.sum()), 50)
        for tile in tiles:  # tiles carry no legend of their own
            x0, y0, x1, y1 = tile["box_px"]
            corner = img[y1 - mr.FOOTER_PX - 30:y1 - mr.FOOTER_PX, x0:x0 + 20]
            self.assertFalse(np.all(np.abs(corner.astype(int) - mr.highlight_color(0)) <= 2, axis=2).any())
        with self.assertRaises(ValueError):
            self.job(scene, {"views": ["iso"], "layout": "sheet"})

    def test_frame_modes(self):
        box = Part.makeBox(20, 10, 8)
        faces = box_faces(box)
        scene = mr.Scene([mr.ScenePart(box, id="B")], [mr.SceneHighlight("A", [faces[(0, 0, 1)].Edges[0]])],
                         title="Frames", model_bounds=[[-40, -40, -40], [60, 50, 48]])
        settings = {"views": ["iso"], "size": [320, 240], "quality": "draft", "labels": False}
        cams = {}
        for frame in ("included", "model", "highlights"):
            result, _, _ = self.job(scene, dict(settings, frame=frame))
            cams[frame] = result["images"][0]["camera"]
        self.assertGreater(cams["model"]["mm_per_px"], cams["included"]["mm_per_px"] * 2)
        self.assertLess(cams["highlights"]["mm_per_px"], cams["included"]["mm_per_px"])
        explicit, _, _ = self.job(scene, dict(settings, frame={"center_mm": [5, 5, 4], "width_mm": 64}))
        camera = explicit["images"][0]["camera"]
        self.assertAlmostEqual(camera["mm_per_px"], 64 / 320, places=9)
        np.testing.assert_allclose(camera["center_mm"], [5, 5, 4], atol=1e-6)
        px, py = project(camera, (5, 5, 4))
        self.assertAlmostEqual(px, 160, places=6)
        self.assertAlmostEqual(py, mr.HEADER_PX + (240 - mr.HEADER_PX - mr.FOOTER_PX) / 2, places=6)
        # frame "model" with a section follows the kept part of the model box (z <= 4 here)
        front = dict(settings, views=["front"], frame="model")
        whole, _, _ = self.job(scene, front)
        cut, _, _ = self.job(scene, dict(front, section={"plane": "XY", "offset": 4}))
        whole_cam, cut_cam = whole["images"][0]["camera"], cut["images"][0]["camera"]
        np.testing.assert_allclose(whole_cam["center_mm"], [10, 5, 4], atol=1e-6)   # x -40..60, z -40..48
        np.testing.assert_allclose(cut_cam["center_mm"], [10, 5, -18], atol=1e-6)   # z -40..4
        self.assertAlmostEqual(whole_cam["mm_per_px"], 88 / ((240 - 30 - 24) * 0.88), places=9)  # height-bound
        self.assertAlmostEqual(cut_cam["mm_per_px"], 100 / (320 * 0.88), places=9)               # width-bound

    def test_two_sided_highlights_and_unknown_orientation_never_culled(self):
        sheet = Part.makePlane(10, 10)  # one face, normal +Z: an open, non-solid part
        settings = {"views": ["bottom"], "size": [320, 240], "quality": "draft", "labels": False}
        for two_sided in (True, False):
            scene = mr.Scene([mr.ScenePart(sheet, id="S")], [mr.SceneHighlight("A", [sheet], two_sided=two_sided)],
                             title="Sheet")
            result, (img,), _ = self.job(scene, settings)
            row, camera = result["images"][0]["highlights"][0], result["images"][0]["camera"]
            pixels = window(img, project(camera, (5, 5, 0)), 3)
            self.assertFalse(is_background(pixels).any())  # the part itself is two-sided
            self.assertEqual(row["visible"], two_sided)
            # seen from behind, a two-sided highlight shows its colour; a one-sided one is culled
            self.assertEqual(bool(hue_match(pixels, mr.highlight_color(0), cos=0.95).all()), two_sided)
            if not two_sided:
                self.assertFalse(hue_match(pixels, mr.highlight_color(0), cos=0.95).any())
        # a face whose orientation sample fails is never back-face culled
        box_scene = mr.Scene([mr.ScenePart(Part.makeBox(20, 10, 8), id="B")])
        self.assertTrue(mr.Prepared(box_scene, 0.25).tri_cull.all())
        with patch.object(App, "Vector", side_effect=RuntimeError("no orientation sample")):
            unknown = mr.Prepared(box_scene, 0.25)
        self.assertEqual(len(unknown.T), 12)
        self.assertFalse(unknown.tri_cull.any())

    def test_scene_from_capture_round_trip(self):
        folder = support.scratch(self, prefix="model-render-capture-")
        box = Part.makeBox(20, 10, 8)
        box.exportBrep(str(folder / "part-0.brep"))
        Part.makeCompound([box.Faces[0], box.Edges[0]]).exportBrep(str(folder / "hl-0-r.brep"))
        Part.makeCompound([Part.makeBox(2, 2, 2).Faces[0]]).exportBrep(str(folder / "hl-0-g.brep"))
        Part.makeCompound([Part.makeCircle(3)]).exportBrep(str(folder / "sketches.brep"))
        document = {"title": "Captured", "revision": "rev-1", "banners": ["needs_rebuild"],
                    "model_bounds": [[0, 0, 0], [20, 10, 8]],
                    "parts": [{"brep": "part-0.brep", "name": "Block", "id": "B", "color": [0.5, 0.6, 0.7],
                               "solid": True}],
                    "sketches": ["sketches.brep"],
                    "highlights": [{"label": "A", "note": "n", "rendered": "hl-0-r.brep", "ghost": "hl-0-g.brep"},
                                   {"label": "B", "rendered": None, "ghost": None}]}
        scene = mr.Scene.from_capture(folder, document)
        self.assertEqual([p.id for p in scene.parts], ["B"])
        self.assertTrue(scene.parts[0].solid)
        self.assertEqual(scene.parts[0].color, (0.5, 0.6, 0.7))
        self.assertEqual([s.ShapeType for s in scene.highlights[0].shapes], ["Face", "Edge"])
        self.assertEqual(len(scene.highlights[0].ghosts), 1)
        self.assertEqual((scene.highlights[1].shapes, scene.highlights[1].ghosts), ([], []))
        self.assertEqual(len(scene.sketches), 1)
        self.assertEqual(scene.model_bounds, [[0.0, 0.0, 0.0], [20.0, 10.0, 8.0]])
        result, _, _ = self.job(scene, {"views": ["iso"], "size": [320, 240], "quality": "draft"})
        self.assertEqual(result["banners"][0]["kind"], "needs_rebuild")
        self.assertEqual(result["parts"][0]["faces"], 6)
        with self.assertRaises(ValueError):
            mr.Scene.from_capture(folder, dict(document, parts=[{"brep": "../part-0.brep"}]))

    def test_normalize_settings_defaults_and_rejections(self):
        self.assertEqual(mr.normalize_settings({})["views"], ["iso"])
        self.assertEqual(mr.normalize_settings({"section": {"plane": "XY"}})["views"], ["section"])
        self.assertEqual(mr.normalize_settings({})["size"], list(mr.DEFAULT_SIZE))
        five = mr.normalize_settings({"views": ["iso", "front", "top", "right", "left"], "layout": "sheet"})
        self.assertEqual(five["size"], list(mr.DEFAULT_SHEET_SIZE))
        for bad in ({"layout": "grid"}, {"quality": "best"}, {"frame": "everything"},
                    {"views": ["iso"], "layout": "sheet"}):
            with self.assertRaises(ValueError):
                mr.normalize_settings(bad)
        self.assertEqual(mr.supersample_for((1024, 768), "standard"), 2)
        self.assertEqual(mr.supersample_for((2048, 1536), "standard"), 1)
        self.assertEqual(mr.supersample_for((320, 240), "draft"), 1)
        identity = mr.engine()
        self.assertEqual((identity["renderer"], identity["renderer_version"]), ("kurtshape-soft", 1))
        self.assertTrue(identity["font"])
        self.assertIsNone(mr.ScenePart(Part.makeBox(1, 1, 1)).key)  # reports fall back to the part index
        self.assertEqual(mr.ScenePart(Part.makeBox(1, 1, 1), name="Pin").key, "Pin")
        with self.assertRaises(ValueError):
            mr.normalize_banners([{"color": "red"}])


if __name__ == "__main__":
    unittest.main()
