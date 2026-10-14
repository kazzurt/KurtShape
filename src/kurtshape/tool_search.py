"""Search every toolbar/menu tool and shortcut action, with the toolbar's behavior.

Entries come from the live QActions the toolbars and menus already trigger, so
a search result does exactly what its button does. Shortcut-only registry
actions are merged by label (keeping user key overrides) or listed on their
own. Aliases let common CAD names find the tool KurtShape uses.
"""
from __future__ import annotations

import re

ALIASES = {
    "extrude": ["pad", "boss", "extrude add", "extrude new", "intersect"],
    "extrude · cut": ["remove material", "cut", "pocket", "extrude remove", "cut extrude"],
    "sketch": ["new sketch", "create sketch", "draw"],
    "revolve": ["revolution", "lathe", "turn"],
    "fillet": ["round", "blend"],
    "chamfer": ["bevel"],
    "shell": ["hollow", "thickness"],
    "mirror": ["reflect", "symmetric copy"],
    "linear pattern": ["array", "rectangular pattern"],
    "circular pattern": ["polar pattern", "radial array"],
    "boolean parts": ["union", "subtract", "combine"],
    "split": ["slice", "divide"],
    "transform": ["move part", "rotate part", "copy part"],
    "dimension": ["constraint", "measure dimension", "size"],
    "line": ["polyline"],
    "rectangle": ["box sketch"],
    "use": ["project", "projection", "convert entities", "external geometry"],
    "undo": ["back", "revert"],
    "redo": ["again", "repeat"],
    "check geometry": ["validate", "verify solid"],
    "plane": ["datum plane", "work plane", "construction plane"],
}


def normalize(text):
    text = (text or "").lower().replace("…", " ").replace("·", " ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+ ]", " ", text)).strip()


ALIASES = {normalize(label): aliases for label, aliases in ALIASES.items()}


def shortcut_from_tip(tip):
    """Toolbar tips end with "· Key" when the tool has a default shortcut."""
    tail = (tip or "").split("·")[-1].strip() if "·" in (tip or "") else ""
    return tail if tail and len(tail) <= 14 and (len(tail) == 1 or "+" in tail or tail.isupper()) else ""


def build_entries(actions, shortcuts):
    """Merge tool actions and shortcut registry actions into unique entries.

    ``actions``: dicts with label, command, group, context, tip and trigger.
    ``shortcuts``: router entries with id, label, key, contexts and status.
    One entry per command (or per label when there is no command).
    """
    entries, by_key, by_label = [], {}, {}
    for action in actions:
        label = action["label"].strip()
        if not label:
            continue
        key = action.get("command") or "label:" + normalize(label)
        existing = by_key.get(key) or by_label.get(normalize(label))
        if existing is not None:
            # The first (toolbar) action wins; menus add where else it lives.
            if action["group"] not in existing["groups"]:
                existing["groups"].append(action["group"])
            if action.get("context", "model") not in existing["contexts"]:
                existing["contexts"].append(action.get("context", "model"))
            existing["shortcut"] = existing["shortcut"] or shortcut_from_tip(action.get("tip"))
            by_key.setdefault(key, existing)
            continue
        entry = {"label": label, "command": action.get("command"), "groups": [action["group"]],
                 "contexts": [action.get("context", "model")], "enabled": action.get("enabled", True),
                 "shortcut": shortcut_from_tip(action.get("tip")),
                 "tip": action.get("tip", ""), "trigger": action.get("trigger"), "shortcut_id": None,
                 "aliases": list(ALIASES.get(normalize(label), []))}
        by_key[key] = entry
        by_label.setdefault(normalize(label), entry)
        entries.append(entry)
    for item in shortcuts:
        existing = by_label.get(normalize(item["label"]))
        if existing is not None:
            existing["shortcut"] = item["key"]  # the user's current binding
            existing["shortcut_id"] = item["id"]
            continue
        entry = {"label": item["label"], "command": None, "groups": ["Shortcut"],
                 "contexts": list(item.get("contexts") or ["general"]), "shortcut": item["key"],
                 "tip": item.get("note", ""), "trigger": None, "shortcut_id": item["id"],
                 "aliases": list(ALIASES.get(normalize(item["label"]), [])),
                 "registry_status": item.get("resolved_status")}
        by_label[normalize(item["label"])] = entry
        entries.append(entry)
    return entries


def score(entry, query):
    """Lower is better; None excludes the entry. Every word must match."""
    words = normalize(query).split()
    if not words:
        return 5
    label = normalize(entry["label"])
    aliases = [normalize(alias) for alias in entry["aliases"]]
    haystack = " ".join([label, *aliases, *(normalize(group) for group in entry["groups"]),
                         normalize(entry.get("shortcut", "")), normalize(entry.get("tip", ""))])
    if not all(word in haystack for word in words):
        return None
    phrase = " ".join(words)
    if label == phrase or phrase in aliases:
        return 0
    if label.startswith(phrase):
        return 1
    if any(alias.startswith(phrase) for alias in aliases):
        return 2
    return 3 if phrase in label else 4


def search(entries, query):
    ranked = [(score(entry, query), index, entry) for index, entry in enumerate(entries)]
    return [entry for value, index, entry in sorted((item for item in ranked if item[0] is not None),
                                                    key=lambda item: (item[0], item[1]))]


def availability(entry, sketching, workspace):
    """Plain-language reason a tool cannot run here, or an empty string."""
    if entry.get("enabled") is False:
        return "Unavailable right now"
    reasons = [_context_reason(entry, context, sketching, workspace) for context in entry["contexts"]]
    return "" if "" in reasons else reasons[0]


def _context_reason(entry, context, sketching, workspace):
    if context == "sketch" and not sketching:
        return "Start or edit a sketch first"
    if context == "model" and sketching and entry.get("command") not in {"PartDesign_Pad"}:
        return "Finish the sketch first"
    if context == "assembly" and workspace != "assembly":
        return "Switch to Assembly"
    if context == "model" and workspace == "assembly":
        return "Switch to Part Studio"
    if entry.get("registry_status") not in {None, "available", "native equivalent"}:
        return "Not available in KurtShape"
    return ""
