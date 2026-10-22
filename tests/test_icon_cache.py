"""Slice A/B U2 (A5, review E-11): the grayscale native-icon cache is keyed by pixels and bounded.

FreeCAD hands back a new QIcon (new cacheKey) on every ``ViewObject.Icon`` read. Headless there is
no ViewObject, so each refresh below builds its stand-in native icons afresh (new QIcon, new
cacheKey, same pixels) from the repo's own SVGs and from synthetic pixmaps, exactly the shape the
GUI hands ``icon_for`` and ``HistoryModel``. Rows mirror ``ui.py``'s part-studio refresh over the
studio benchmark fixture (4 parts, 34 features): Origin planes via ``icon_for("Plane", native=...)``,
feature rows with the raw native icon, part rows via ``icon_for("Part", native=...)``.
"""
from pathlib import Path
import sys
import time
import unittest

import support

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import FreeCAD as App  # noqa: F401 — installs the bundled PySide compatibility module.

ICONS = ROOT / "resources" / "icons"
FEATURE_SVGS = {"Sketcher::SketchObject": "sketch", "PartDesign::Pad": "extrude", "PartDesign::Pocket": "remove"}
REFRESHES = 1000


def _image(variant, size=64):
    """A synthetic stand-in for a native body icon: the same pixels for the same variant."""
    from PySide import QtCore, QtGui
    image = QtGui.QImage(size, size, QtGui.QImage.Format_ARGB32)
    image.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(image)
    try:
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setBrush(QtGui.QColor(("#3a6fd8", "#d8823a", "#3ad87a", "#c23ad8")[variant % 4]))
        painter.setPen(QtGui.QPen(QtGui.QColor("#202020"), 3))
        inset = 6 + 4 * variant
        painter.drawRoundedRect(inset, inset, size - 2 * inset, size - 2 * inset, 8, 8)
    finally:
        painter.end()
    return image


class IconCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide import QtGui
        cls.app = QtGui.QApplication.instance() or QtGui.QApplication([])
        cls.images = {variant: _image(variant) for variant in range(4)}

    def setUp(self):
        from kurtshape import presentation_icons
        self.icons = presentation_icons
        presentation_icons.clear_cache()
        self.addCleanup(presentation_icons.clear_cache)

    def fresh_body_icon(self, variant):
        from PySide import QtGui
        return QtGui.QIcon(QtGui.QPixmap.fromImage(self.images[variant]))

    @staticmethod
    def fresh_svg_icon(name):
        from PySide import QtGui
        return QtGui.QIcon(str(ICONS / (name + ".svg")))

    def tree(self):
        from PySide import QtGui
        tree = QtGui.QTreeWidget()
        self.addCleanup(tree.deleteLater)
        return tree

    def studio_spec(self):
        """Feature and part rows of the real studio fixture, read once from its inspection."""
        folder = support.isolated_session(self, prefix="icon-cache-")
        original_path = list(sys.path)
        benchmark = None
        try:
            sys.path.insert(0, str(ROOT / "tools" / "perf"))
            from bench_core import Benchmark
            benchmark = Benchmark(folder / "icon-cache-studio", fixture="studio", repeat=1, measure=False)
            fixture = benchmark.build()
            state = benchmark.state
            # As ui.py: studio features in feature order, Body and origin points left out.
            order = {name: index for index, name in enumerate(state["studio"]["feature_order"])}
            features = sorted(({"id": f["id"], "name": f["name"], "type": f["type"]} for f in state["features"]
                               if f["type"] not in {"PartDesign::Body", "App::Point"} and f["id"] in order),
                              key=lambda feature: order[feature["id"]])
            parts = [{"id": p["id"], "name": p["name"], "body": p["body"], "visible": p.get("visible", True)}
                     for p in state["studio"]["parts"]]
        finally:
            try:
                if benchmark is not None:
                    benchmark.close()
            finally:
                sys.path[:] = original_path
        self.assertEqual(fixture["logical_parts"], 4)
        self.assertEqual(len(parts), 4)
        self.assertEqual(len(features), fixture["studio_features"])
        self.assertEqual(len(features), 34)
        return features, parts

    def rows(self, features, parts, part_variants, feature_override=None):
        """One refresh's rows, every native icon constructed afresh as FreeCAD does."""
        from PySide import QtCore
        icon_for = self.icons.icon_for
        feature_override = feature_override or {}
        origin = {"key": "origin", "text": "Origin", "data": {QtCore.Qt.UserRole: "origin"},
                  "expand_new": True, "children": []}
        for name, plane in (("Top", "XY"), ("Front", "XZ"), ("Right", "YZ")):
            origin["children"].append({"key": "plane:" + plane, "text": name,
                                       "data": {QtCore.Qt.UserRole: "plane:" + plane},
                                       "icon": icon_for("Plane", native=self.fresh_svg_icon("plane"))})
        feature_rows = [origin]
        for feature in features:
            svg = feature_override.get(feature["id"]) or FEATURE_SVGS.get(feature["type"], "tools")
            feature_rows.append({"key": feature["id"], "text": feature["name"],
                                 "data": {QtCore.Qt.UserRole: feature["id"]},
                                 "tooltip": feature["type"].split("::")[-1] + " · " + feature["id"],
                                 "icon": self.fresh_svg_icon(svg)})
        part_rows = [{"key": part["id"], "text": part["name"], "checked": part["visible"],
                      "data": {QtCore.Qt.UserRole: part["id"], QtCore.Qt.UserRole + 1: part["body"]},
                      "icon": icon_for("Part", native=self.fresh_body_icon(part_variants[index]))}
                     for index, part in enumerate(parts)]
        return feature_rows, part_rows

    def test_studio_rows_keep_one_cache_entry_per_image_and_set_icons_only_on_change(self):
        from kurtshape.history_model import HistoryModel
        features, parts = self.studio_spec()
        feature_model, part_model = HistoryModel(self.tree()), HistoryModel(self.tree())
        variants = [index % 2 for index in range(len(parts))]  # two distinct body images
        document = ("studio", "part_studio")
        feature_rows, part_rows = self.rows(features, parts, variants)
        feature_model.reconcile(document, feature_rows)
        part_model.reconcile(document, part_rows)
        # First refresh: exactly one set per row that carries an icon.
        self.assertEqual(feature_model.icon_sets, 3 + len(features))
        self.assertEqual(part_model.icon_sets, len(parts))
        baseline = len(self.icons._native_cache)
        self.assertEqual(baseline, 2, "one grayscale entry per distinct body image")
        lengths, feature_sets, part_sets = set(), set(), set()
        began = time.perf_counter()
        for _ in range(REFRESHES - 1):
            feature_rows, part_rows = self.rows(features, parts, variants)
            feature_model.reconcile(document, feature_rows)
            part_model.reconcile(document, part_rows)
            lengths.add(len(self.icons._native_cache))
            feature_sets.add(feature_model.icon_sets)
            part_sets.add(part_model.icon_sets)
        elapsed = time.perf_counter() - began
        self.assertEqual(lengths, {baseline}, "cache length is constant after the first refresh")
        self.assertLessEqual(max(lengths), self.icons.NATIVE_CACHE_LIMIT)
        self.assertEqual(feature_sets, {3 + len(features)}, "unchanged refreshes perform zero setIcon calls")
        self.assertEqual(part_sets, {len(parts)}, "unchanged refreshes perform zero setIcon calls")
        print(f"\nU2 studio refreshes: {REFRESHES} x ({len(feature_rows) - 1 + 3} feature rows + {len(parts)} part rows); "
              f"cache length {baseline}; icon sets feature={feature_model.icon_sets} part={part_model.icon_sets}; "
              f"{elapsed * 1000 / (REFRESHES - 1):.3f} ms per refresh (rows built with fresh icons + two reconciles)",
              flush=True)
        # A body whose pixels change is set again, that row only.
        part_items = dict(part_model.items)
        variants[1] = 2
        feature_rows, part_rows = self.rows(features, parts, variants)
        feature_model.reconcile(document, feature_rows)
        part_model.reconcile(document, part_rows)
        self.assertEqual(part_model.icon_sets, len(parts) + 1)
        self.assertEqual(feature_model.icon_sets, 3 + len(features))
        self.assertEqual(len(self.icons._native_cache), baseline + 1)
        changed = parts[1]["id"]
        self.assertEqual(self.icons.icon_signature(part_items[changed].icon(0)),
                         self.icons.icon_signature(part_rows[1]["icon"]))
        for index, part in enumerate(parts):
            if index != 1:
                self.assertNotEqual(self.icons.icon_signature(part_items[part["id"]].icon(0)),
                                    self.icons.icon_signature(part_items[changed].icon(0)))
        # A feature whose native image changes is set again, that row only.
        target = features[-1]["id"]
        feature_rows, part_rows = self.rows(features, parts, variants, {target: "fillet"})
        feature_model.reconcile(document, feature_rows)
        part_model.reconcile(document, part_rows)
        self.assertEqual(feature_model.icon_sets, 3 + len(features) + 1)
        self.assertEqual(part_model.icon_sets, len(parts) + 1)
        self.assertEqual(self.icons.icon_signature(feature_model.items[target].icon(0)),
                         self.icons.icon_signature(self.fresh_svg_icon("fillet")))
        # A new document starts over: every row is set once again.
        feature_model.reconcile(("other", "part_studio"), feature_rows)
        self.assertEqual(feature_model.icon_sets, 2 * (3 + len(features)) + 1)

    def test_icon_replaced_outside_the_model_is_restored(self):
        from PySide import QtGui
        from kurtshape.history_model import HistoryModel
        model = HistoryModel(self.tree())
        model.reconcile("doc", [{"key": "a", "text": "A", "icon": self.fresh_body_icon(0)}])
        model.items["a"].setIcon(0, self.fresh_body_icon(3))
        model.reconcile("doc", [{"key": "a", "text": "A", "icon": self.fresh_body_icon(0)}])
        self.assertEqual(model.icon_sets, 2)
        self.assertEqual(self.icons.icon_signature(model.items["a"].icon(0)),
                         self.icons.icon_signature(self.fresh_body_icon(0)))
        # Rows without an icon key keep the existing behaviour: nothing is set or cleared.
        model.reconcile("doc", [{"key": "a", "text": "A"}])
        self.assertEqual(model.icon_sets, 2)
        self.assertFalse(model.items["a"].icon(0).isNull())
        # A removed row forgets its signature and a re-added one is set once.
        model.reconcile("doc", [{"key": "b", "text": "B"}])
        self.assertNotIn("a", model.icon_signatures)
        model.reconcile("doc", [{"key": "a", "text": "A", "icon": self.fresh_body_icon(0)}])
        self.assertEqual(model.icon_sets, 3)
        self.assertIsInstance(model.items["a"].icon(0), QtGui.QIcon)

    def test_signature_is_stable_across_fresh_icons_and_distinguishes_pixels(self):
        signature = self.icons.icon_signature
        self.assertIsNone(signature(None))
        self.assertEqual(signature(self.fresh_svg_icon("extrude")), signature(self.fresh_svg_icon("extrude")))
        self.assertNotEqual(signature(self.fresh_svg_icon("extrude")), signature(self.fresh_svg_icon("remove")))
        first, second = self.fresh_body_icon(0), self.fresh_body_icon(0)
        self.assertNotEqual(first.cacheKey(), second.cacheKey(), "the stand-in really is a new QIcon")
        self.assertEqual(signature(first), signature(second))
        self.assertNotEqual(signature(first), signature(self.fresh_body_icon(1)))
        # A cache hit hands back a copy of one stored icon: the cacheKey is stable between refreshes.
        gray = [self.icons.icon_for("Part", native=self.fresh_body_icon(0)) for _ in range(3)]
        self.assertEqual(len({icon.cacheKey() for icon in gray}), 1)
        self.assertEqual(len(self.icons._native_cache), 1)

    def test_cache_is_bounded_lru_and_clear_cache_empties_it(self):
        from PySide import QtCore, QtGui
        limit = self.icons.NATIVE_CACHE_LIMIT
        self.assertLessEqual(limit, 256)

        def distinct(index):
            image = QtGui.QImage(24, 24, QtGui.QImage.Format_ARGB32)
            image.fill(QtGui.QColor(index % 256, (index * 7) % 256, (index // 256) * 40, 255))
            return QtGui.QIcon(QtGui.QPixmap.fromImage(image))

        keep = self.fresh_body_icon(0)
        self.icons.icon_for("Part", native=keep)
        for index in range(limit + 40):
            self.icons.icon_for("Part", native=distinct(index))
            if index % 8 == 0:  # recently used entries survive eviction
                self.icons.icon_for("Part", native=self.fresh_body_icon(0))
            self.assertLessEqual(len(self.icons._native_cache), limit)
        self.assertEqual(len(self.icons._native_cache), limit)
        self.assertIn(self.icons.icon_signature(keep), self.icons._native_cache)
        self.assertNotIn(self.icons.icon_signature(distinct(0)), self.icons._native_cache)
        self.icons.clear_cache()
        self.assertEqual(len(self.icons._native_cache), 0)
        self.assertEqual(len(self.icons._original_cache), 0)
        # The grayscale result still carries every mode at the raster sizes (unchanged behaviour).
        gray = self.icons.icon_for("Part", native=self.fresh_body_icon(0))
        self.assertFalse(gray.isNull())
        sizes = gray.availableSizes(QtGui.QIcon.Normal, QtGui.QIcon.Off)
        self.assertIn(QtCore.QSize(48, 48), sizes)
        pixel = gray.pixmap(QtCore.QSize(48, 48)).toImage().pixelColor(24, 24)
        self.assertEqual(pixel.red(), pixel.green())
        self.assertEqual(pixel.green(), pixel.blue())

    def test_mapped_label_icon_is_still_the_original_svg(self):
        from PySide import QtCore
        original = self.icons.icon_for("Extrude")
        again = self.icons.icon_for("Extrude", native=self.fresh_body_icon(2))
        self.assertFalse(original.isNull())
        self.assertEqual(original.cacheKey(), again.cacheKey())
        self.assertEqual(len(self.icons._native_cache), 0, "a mapped label never touches the native cache")
        expected = self.fresh_svg_icon("extrude")
        for size in (24, 48):
            self.assertEqual(original.pixmap(QtCore.QSize(size, size)).toImage(),
                             expected.pixmap(QtCore.QSize(size, size)).toImage())
        self.assertEqual(self.icons.icon_for("Pad", command="PartDesign_Pad").cacheKey(), original.cacheKey())

    def test_signature_path_cost_per_call(self):
        """Report the per-call cost of a cache hit (fresh native icon) against a miss (full rebuild)."""
        from PySide import QtGui
        icon_for = self.icons.icon_for
        fresh = [self.fresh_body_icon(0) for _ in range(REFRESHES)]
        icon_for("Part", native=fresh[0])
        began = time.perf_counter()
        for icon in fresh:
            icon_for("Part", native=icon)
        hit = (time.perf_counter() - began) / REFRESHES
        self.assertEqual(len(self.icons._native_cache), 1)
        signature_began = time.perf_counter()
        for icon in fresh:
            self.icons.icon_signature(icon)
        signature = (time.perf_counter() - signature_began) / REFRESHES
        misses = 50
        began = time.perf_counter()
        for icon in fresh[:misses]:
            self.icons.clear_cache()
            icon_for("Part", native=icon)
        miss = (time.perf_counter() - began) / misses
        entry = next(iter(self.icons._native_cache.values()))
        entry_bytes = sum(size.width() * size.height() * 4
                          for mode in self.icons.ICON_MODES
                          for size in entry.availableSizes(mode, QtGui.QIcon.Off))
        svg_fresh = [self.fresh_svg_icon("sketch") for _ in range(200)]
        began = time.perf_counter()
        for icon in svg_fresh:
            self.icons.icon_signature(icon)
        svg_signature = (time.perf_counter() - began) / len(svg_fresh)
        print(f"\nU2 icon_for cost: hit {hit * 1e6:.1f} us/call over {REFRESHES} fresh native icons "
              f"(signature alone {signature * 1e6:.1f} us; SVG-engine signature {svg_signature * 1e6:.1f} us); "
              f"miss (36 rasterizations + grayscale) {miss * 1e6:.1f} us/call; "
              f"one 64px-source entry holds ~{entry_bytes / 1024:.0f} KiB of pixmaps", flush=True)
        self.assertLess(hit * 3, miss, "the signature fast path must cost far less than a rebuild")


if __name__ == "__main__":
    unittest.main()
