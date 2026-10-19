"""Disposable indexes over native documents observed by DocumentState.

The native graph remains authoritative. Unobserved documents deliberately use
uncached reads; indexes never survive their observer or native document.
"""
from weakref import WeakValueDictionary


_INDEXES = WeakValueDictionary()
DOMAINS = frozenset({"structure", "history", "topology", "placement", "metadata"})
DERIVED_DOMAINS = DOMAINS - {"structure"}
_DEPENDENCIES = {
    "order": {"structure", "history"},
    "positions": {"structure", "history"},
    "part_states": {"structure", "history", "topology"},
    "selector_topology": {"structure", "topology"},
    "selector_contexts": {"structure", "history", "topology", "placement"},
    # Contract 3.2 F3a: the located parameter set (objects and markers), and usage counts (any change).
    "parameter_set": {"structure", "metadata"},
}


class DocumentIndex:
    def __init__(self, document):
        self.document = document
        # Native wrappers cannot expose properties after their document closes.
        self.document_name = document.Name
        self._objects = None
        self._bodies = None
        self._owners = None
        self.derived = {}
        self.generations = dict.fromkeys(DOMAINS, 0)
        self.counts = {"objects": 0, "ownership": 0, "history_steps": 0}

    def invalidate(self, structure=False, domains=None):
        """Unclassified changes remain conservative; membership changes are explicit."""
        domains = DERIVED_DOMAINS if domains is None else frozenset(domains)
        if not domains <= DOMAINS:
            raise ValueError("Unknown document invalidation domain")
        if structure or "structure" in domains:
            domains = DOMAINS
            self._objects = self._bodies = self._owners = None
        for domain in domains:
            self.generations[domain] += 1
        for key in tuple(self.derived):
            if domains & _DEPENDENCIES.get(key, DOMAINS):
                self.derived.pop(key, None)

    def token(self, *domains):
        return tuple(self.generations[domain] for domain in domains)

    def objects(self):
        if self._objects is None:
            self._objects = tuple(self.document.Objects)
            self.counts["objects"] += 1
        return self._objects

    def bodies(self):
        if self._bodies is None:
            self._bodies = tuple(obj for obj in self.objects() if obj.TypeId == "PartDesign::Body")
        return self._bodies

    def owner(self, obj):
        if obj is None or obj.Document != self.document:
            return None
        if self._owners is None:
            owners = {}
            for body in self.bodies():
                for member in (body, *body.Group, body.Origin, *body.Origin.OriginFeatures):
                    prior = owners.get(member.Name, body)
                    owners[member.Name] = body if prior == body else None
            self._owners = owners
            self.counts["ownership"] += 1
        return self._owners.get(obj.Name)


def bind(index):
    _INDEXES[index.document_name] = index


def get(doc):
    index = _INDEXES.get(doc.Name)
    return index if index is not None and index.document == doc else None


def unbind(index):
    name = index.document_name
    if _INDEXES.get(name) is index:
        _INDEXES.pop(name, None)


def local_dependencies(index):
    """Only local native graph edges are covered by this index's state token."""
    doc = index.document
    domains = tuple(sorted(DOMAINS))
    token = index.token(*domains)
    local = index.derived.get("local_dependencies")
    if local is None:
        local = True
        try:
            for obj in index.objects():
                dependencies = list(obj.OutList)
                linked = getattr(obj, "LinkedObject", None)
                if isinstance(linked, tuple):
                    linked = linked[0]
                if linked is not None:
                    dependencies.append(linked)
                if any(dependency.Document != doc for dependency in dependencies):
                    local = False
                    break
        except (AttributeError, RuntimeError, ReferenceError):
            local = False
    if get(doc) is not index or index.token(*domains) != token:
        return False
    index.derived["local_dependencies"] = local
    return local
