"""Instance folders: presentation metadata on the assembly (assembly UX item 3).

Folders group occurrences in the instance lists only. They are stored as one
JSON string property on the native assembly object,

    KurtShapeInstanceFolders = {"folders": [{"name": "Fasteners", "children": [...]}],
                                "membership": {"<instance id>": "Fasteners/M3"}}

so the solver, ``result_objects()``, export and reopen never see them: the
occurrence list stays flat. An instance missing from ``membership`` sits at the
root; a membership entry for a deleted instance is ignored on read and dropped
when the instance is removed. Paths join folder names with ``/``.
"""
from __future__ import annotations

import json

PROPERTY = "KurtShapeInstanceFolders"
MAX_NAME = 120
MAX_DEPTH = 16


class FolderError(ValueError):
    def __init__(self, message, **details):
        super().__init__(message)
        self.details = details


def _name(value):
    if not isinstance(value, str) or not value.strip():
        raise FolderError("Folder names must be non-empty strings")
    value = value.strip()
    if "/" in value or len(value) > MAX_NAME:
        raise FolderError(f"Folder names cannot contain '/' or exceed {MAX_NAME} characters", name=value)
    return value


def split(path):
    """``"A/B"`` → ``["A", "B"]``; None/"" → [] (the root)."""
    if path is None or path == "":
        return []
    if not isinstance(path, str):
        raise FolderError("folder must be a path string such as \"Fasteners/M3\", or null for the root")
    parts = [part.strip() for part in path.split("/")]
    if any(not part for part in parts) or len(parts) > MAX_DEPTH:
        raise FolderError("Invalid folder path", folder=path)
    return [_name(part) for part in parts]


def normalize_tree(folders, depth=0):
    """Validate a folder tree; strings are accepted as shorthand paths."""
    if not isinstance(folders, list):
        raise FolderError("folders must be a list of {name, children} objects or path strings")
    if depth > MAX_DEPTH:
        raise FolderError(f"Folders nest at most {MAX_DEPTH} levels")
    result = []
    for entry in folders:
        if isinstance(entry, str):
            ensure(result, split(entry))
            continue
        if not isinstance(entry, dict) or set(entry) - {"name", "children"}:
            raise FolderError("Each folder is {name, children}")
        name = _name(entry.get("name"))
        children = normalize_tree(entry.get("children", []), depth + 1)
        existing = next((node for node in result if node["name"] == name), None)
        if existing is not None:
            raise FolderError("Sibling folders need distinct names", name=name)
        result.append({"name": name, "children": children})
    return result


def paths(folders, prefix=""):
    """Every folder path, parents before children, in tree order."""
    result = []
    for node in folders:
        path = prefix + node["name"]
        result.append(path)
        result.extend(paths(node["children"], path + "/"))
    return result


def ensure(folders, parts):
    """Create the folder path ``parts`` (a list of names) inside ``folders``."""
    level = folders
    for name in parts:
        node = next((value for value in level if value["name"] == name), None)
        if node is None:
            node = {"name": name, "children": []}
            level.append(node)
        level = node["children"]
    return "/".join(parts) or None


def empty():
    return {"folders": [], "membership": {}}


def read(asm, instance_ids=None):
    """The stored structure; membership filtered to existing instances and folders."""
    raw = getattr(asm, PROPERTY, "") if asm is not None else ""
    try:
        data = json.loads(raw) if raw else empty()
        folders = normalize_tree(data.get("folders", []))
        membership = data.get("membership", {})
        if not isinstance(membership, dict):
            raise FolderError("membership must be an object")
    except (ValueError, AttributeError, TypeError):
        # A damaged property never blocks the assembly: everything shows at the root.
        return empty()
    known = set(paths(folders))
    ids = None if instance_ids is None else set(instance_ids)
    membership = {key: value for key, value in membership.items()
                  if isinstance(key, str) and value in known and (ids is None or key in ids)}
    return {"folders": folders, "membership": membership}


def write(asm, data):
    payload = json.dumps({"folders": data["folders"], "membership": dict(sorted(data["membership"].items()))},
                         sort_keys=True, separators=(",", ":"))
    if PROPERTY not in asm.PropertiesList:
        asm.addProperty("App::PropertyString", PROPERTY, "KurtShape Assembly")
        asm.setEditorMode(PROPERTY, 1)
    if getattr(asm, PROPERTY) != payload:
        setattr(asm, PROPERTY, payload)


def structure(folders, membership, instance_ids):
    """Validate a whole structure against the current instances."""
    folders = normalize_tree(folders)
    if membership is None:
        membership = {}
    if not isinstance(membership, dict):
        raise FolderError("membership must map instance ids to folder paths")
    known, ids = set(paths(folders)), set(instance_ids)
    result = {}
    for key, value in membership.items():
        if key not in ids:
            raise FolderError("Unknown assembly instance in membership", instance=key)
        if value is None or value == "":
            continue
        path = "/".join(split(value))
        if path not in known:
            raise FolderError("membership names a folder that is not in folders", instance=key, folder=value)
        result[key] = path
    return {"folders": folders, "membership": result}


def moved(data, instances, folder):
    """A copy with ``instances`` moved into ``folder`` (created when missing); None = root."""
    data = json.loads(json.dumps(data))
    path = ensure(data["folders"], split(folder))
    for identity in instances:
        if path is None:
            data["membership"].pop(identity, None)
        else:
            data["membership"][identity] = path
    return data


def renamed(data, path, name):
    """A copy with the folder at ``path`` renamed; members and subfolders follow."""
    data = json.loads(json.dumps(data))
    parts = split(path)
    if not parts:
        raise FolderError("Choose a folder to rename")
    name = _name(name)
    level = data["folders"]
    for part in parts[:-1]:
        level = next(node for node in level if node["name"] == part)["children"]
    node = next((value for value in level if value["name"] == parts[-1]), None)
    if node is None:
        raise FolderError("Unknown folder", folder=path)
    if name != node["name"] and any(value["name"] == name for value in level):
        raise FolderError("Sibling folders need distinct names", name=name)
    node["name"] = name
    new = "/".join(parts[:-1] + [name])
    for key, value in list(data["membership"].items()):
        if value == path or value.startswith(path + "/"):
            data["membership"][key] = new + value[len(path):]
    return data


def removed(data, path):
    """A copy without the folder at ``path``; its instances and subfolders move to its parent."""
    data = json.loads(json.dumps(data))
    parts = split(path)
    if not parts:
        raise FolderError("Choose a folder to remove")
    level = data["folders"]
    for part in parts[:-1]:
        level = next(node for node in level if node["name"] == part)["children"]
    node = next((value for value in level if value["name"] == parts[-1]), None)
    if node is None:
        raise FolderError("Unknown folder", folder=path)
    position = level.index(node)
    level.pop(position)
    for child in reversed(node["children"]):
        existing = next((value for value in level if value["name"] == child["name"]), None)
        if existing is None:
            level.insert(position, child)
        else:  # merge a same-named subfolder into the parent's folder
            existing["children"].extend(child["children"])
    parent = "/".join(parts[:-1]) or None
    for key, value in list(data["membership"].items()):
        if value == path:
            if parent is None:
                data["membership"].pop(key)
            else:
                data["membership"][key] = parent
        elif value.startswith(path + "/"):
            rest = value[len(path) + 1:]
            data["membership"][key] = (parent + "/" + rest) if parent else rest
    return data


def counts(data, instance_ids):
    """Instances per folder path, including those in subfolders."""
    result = {path: 0 for path in paths(data["folders"])}
    for identity in instance_ids:
        path = data["membership"].get(identity)
        while path:
            result[path] = result.get(path, 0) + 1
            path = path.rpartition("/")[0]
    return result


def forget(asm, identity):
    """Drop a removed instance's membership (an id may be reused later)."""
    if asm is None or PROPERTY not in asm.PropertiesList:
        return
    data = read(asm)
    if identity in data["membership"]:
        data["membership"].pop(identity)
        write(asm, data)
