"""Bounded disposable feature summaries over observed native document state.

Entries contain plain inspection data, never editable geometry. Each read gets
an independent copy because the controller adds history and helper diagnostics.
"""
from collections import OrderedDict
from copy import deepcopy


class FeatureSummaryCache:
    def __init__(self, limit=4096):
        self.limit = limit
        self.entries = OrderedDict()
        self.builds = 0
        self.hits = 0

    @staticmethod
    def token(obj, state):
        if "summary_epoch" not in state or "summary_versions" not in state:
            return None
        versions = state["summary_versions"]
        dependencies = []
        for source in obj.OutList:
            if source.Document != obj.Document:
                # Unobserved external document changes have no local clock.
                return None
            dependencies.append((source.Name, versions.get(source.Name, 0), tuple(source.State)))
        tool = getattr(obj, "KurtShapeTool", None)
        if tool is not None:
            if tool.Document != obj.Document:
                return None
            dependencies.append((tool.Name, versions.get(tool.Name, 0), tuple(tool.State)))
        # Reference diagnostics can depend on geometry beyond authored links.
        reference_generation = state["generation"] if obj.TypeId == "Sketcher::SketchObject" else None
        return (state["summary_epoch"], versions.get(obj.Name, 0), tuple(obj.State),
                tuple(dependencies), reference_generation)

    def get(self, obj, state, build):
        token = self.token(obj, state)
        cached = self.entries.get(obj.Name)
        if token is not None and cached is not None and cached[0] == token:
            self.entries.move_to_end(obj.Name)
            self.hits += 1
            return deepcopy(cached[1])
        result = build(obj)
        self.builds += 1
        # A native getter can publish changes. Never store a result under a
        # token that became obsolete while its fields were being read.
        if token is not None and token == self.token(obj, state):
            self.entries[obj.Name] = (token, deepcopy(result))
            self.entries.move_to_end(obj.Name)
            while len(self.entries) > self.limit:
                self.entries.popitem(last=False)
        else:
            self.entries.pop(obj.Name, None)
        return result


def feature_summary(obj, observer, build):
    state = observer.state(obj.Document)
    cache = state.get("feature_summary_cache")
    if cache is None:
        cache = state["feature_summary_cache"] = FeatureSummaryCache()
    return cache.get(obj, state, build)
