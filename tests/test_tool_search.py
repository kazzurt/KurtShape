"""Unified tool search: coverage, deduplication, aliases and availability."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from kurtshape import tool_search


def action(label, group, context="model", command=None, tip=""):
    return {"label": label, "group": group, "context": context, "command": command, "tip": tip,
            "enabled": True, "trigger": lambda: label}


ACTIONS = [
    action("Sketch", "Part Studio", tip="Create sketch · Shift+S"),
    action("Extrude", "Part Studio", command="PartDesign_Pad", tip="Extrude · New, Add, Cut or Intersect · Shift+E"),
    action("Fillet", "Part Studio", command="PartDesign_Fillet"),
    action("Extrude", "Build", command="PartDesign_Pad"),
    action("Extrude · Cut", "Cut", command="PartDesign_Pocket"),
    action("Spline", "Sketch", context="sketch", command="Sketcher_CreateBSpline", tip="Spline"),
    action("Extrude", "Sketch", context="sketch", tip="Finish this sketch and extrude · Shift+E"),
    action("Undo", "Document", context="general", tip="Undo · Ctrl+Z"),
    action("Joints", "Assembly", context="assembly"),
]
SHORTCUTS = [
    {"id": "feature.extrude", "label": "Extrude", "key": "Ctrl+Alt+E", "contexts": ["part_studio"], "resolved_status": "available"},
    {"id": "view.section", "label": "Section view", "key": "Shift+X", "contexts": ["general"], "resolved_status": "available"},
]


class ToolSearchTests(unittest.TestCase):
    def setUp(self):
        self.entries = tool_search.build_entries(ACTIONS, SHORTCUTS)

    def labels(self, query):
        return [entry["label"] for entry in tool_search.search(self.entries, query)]

    def test_every_tool_once_including_shortcutless_and_shortcut_only(self):
        labels = [entry["label"] for entry in self.entries]
        self.assertEqual(labels.count("Extrude"), 1)
        for name in ("Fillet", "Spline", "Extrude · Cut", "Undo", "Joints", "Section view"):
            self.assertIn(name, labels)
        extrude = next(entry for entry in self.entries if entry["label"] == "Extrude")
        self.assertEqual(set(extrude["groups"]), {"Part Studio", "Build", "Sketch"})
        self.assertEqual(set(extrude["contexts"]), {"model", "sketch"})

    def test_user_binding_overrides_tip_shortcut_and_toolbar_trigger_is_kept(self):
        extrude = next(entry for entry in self.entries if entry["label"] == "Extrude")
        self.assertEqual(extrude["shortcut"], "Ctrl+Alt+E")
        self.assertEqual(extrude["trigger"](), "Extrude")
        undo = next(entry for entry in self.entries if entry["label"] == "Undo")
        self.assertEqual(undo["shortcut"], "Ctrl+Z")

    def test_aliases_find_the_cut_preset_and_common_names(self):
        self.assertEqual(self.labels("remove material")[0], "Extrude · Cut")
        self.assertEqual(self.labels("pocket")[0], "Extrude · Cut")
        self.assertEqual(self.labels("cut")[0], "Extrude · Cut")
        self.assertEqual(self.labels("round")[0], "Fillet")
        self.assertEqual(self.labels("pad")[0], "Extrude")
        self.assertEqual(self.labels("shift+e")[0], "Extrude")
        self.assertEqual(self.labels("nonexistent tool"), [])

    def test_contextual_unavailability_is_explained(self):
        spline = next(entry for entry in self.entries if entry["label"] == "Spline")
        fillet = next(entry for entry in self.entries if entry["label"] == "Fillet")
        extrude = next(entry for entry in self.entries if entry["label"] == "Extrude")
        joints = next(entry for entry in self.entries if entry["label"] == "Joints")
        self.assertEqual(tool_search.availability(spline, False, "part_studio"), "Start or edit a sketch first")
        self.assertEqual(tool_search.availability(spline, True, "part_studio"), "")
        self.assertEqual(tool_search.availability(fillet, True, "part_studio"), "Finish the sketch first")
        self.assertEqual(tool_search.availability(extrude, True, "part_studio"), "")
        self.assertEqual(tool_search.availability(joints, False, "part_studio"), "Switch to Assembly")


if __name__ == "__main__":
    unittest.main()
