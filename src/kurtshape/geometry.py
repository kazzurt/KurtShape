"""Transient geometry facts and explicit checks over native result shapes."""
from __future__ import annotations

from collections import OrderedDict, defaultdict
import math
import time
import weakref


LEVELS = {False: (), True: ("bbox", "volume", "area"),
          "full": ("bbox", "volume", "area", "center_of_mass")}
_PROVIDERS = weakref.WeakValueDictionary()


def provider(doc):
    cache = _PROVIDERS.get(doc.Name)
    return cache if cache is not None and cache._documents.get(doc.Name) == doc else None


def bounding_box(shape):
    box = shape.BoundBox
    return {"min": [box.XMin, box.YMin, box.ZMin],
            "max": [box.XMax, box.YMax, box.ZMax],
            "size": [box.XLength, box.YLength, box.ZLength]}


def center_of_mass(shape):
    solids = shape.Solids
    if not solids:
        return None
    if len(solids) == 1:
        point = solids[0].CenterOfMass
        return [point.x, point.y, point.z]
    masses = [(solid.Volume, solid.CenterOfMass) for solid in solids]
    volume = sum(value for value, _ in masses)
    return [sum(value * getattr(point, axis) for value, point in masses) / volume
            for axis in ("x", "y", "z")] if volume else None


def scalar(shape, field):
    if field == "center_of_mass":
        if shape.Solids:
            return center_of_mass(shape)
        point = shape.CenterOfMass
        return [point.x, point.y, point.z]
    return float(getattr(shape, {"volume": "Volume", "area": "Area", "length": "Length"}[field]))


def bboxes_overlap(first, second, tolerance=1e-7):
    return all(first["max"][axis] + tolerance >= second["min"][axis]
               and second["max"][axis] + tolerance >= first["min"][axis] for axis in range(3))


def bbox_distance(first, second):
    return sum(max(0.0, first["min"][axis] - second["max"][axis],
                   second["min"][axis] - first["max"][axis]) ** 2 for axis in range(3)) ** 0.5


def common_volume(first, second):
    return scalar(first.common(second), "volume")


def distance(first, second):
    return float(first.distToShape(second)[0])


def check_shape(shape, details=True):
    began = time.perf_counter()
    valid = bool(shape.isValid())
    issues = []
    if not valid and details:
        try:
            result = shape.check(False)
            if result:
                issues = [str(item) for item in result]
        except ValueError as exc:
            issues = [line.strip() for line in str(exc).splitlines()
                      if line.strip() and "no error" not in line.lower()]
    return {"valid": valid, "issues": issues, "ms": (time.perf_counter() - began) * 1000}


COMPUTE = {"bbox": bounding_box, "volume": lambda shape: scalar(shape, "volume"),
           "area": lambda shape: scalar(shape, "area"), "center_of_mass": center_of_mass}


def measurement_dict(facts, check=None):
    return {"valid": check["valid"] if check is not None else None,
            "solid_count": facts["solid_count"], "volume_mm3": facts.get("volume"),
            "area_mm2": facts.get("area"), "bbox_mm": facts.get("bbox"),
            "center_of_mass_mm": facts.get("center_of_mass")}


def aggregate(facts_list, checks):
    facts = {"solid_count": sum(row["solid_count"] for row in facts_list)}
    for field in ("volume", "area"):
        if all(field in row for row in facts_list):
            facts[field] = sum(row[field] for row in facts_list)
    if all("bbox" in row for row in facts_list):
        low = [min(row["bbox"]["min"][axis] for row in facts_list) for axis in range(3)]
        high = [max(row["bbox"]["max"][axis] for row in facts_list) for axis in range(3)]
        facts["bbox"] = {"min": low, "max": high, "size": [b - a for a, b in zip(low, high)]}
    if all("center_of_mass" in row and "volume" in row for row in facts_list):
        volume = facts["volume"]
        facts["center_of_mass"] = [sum(row["volume"] * row["center_of_mass"][axis]
                                          for row in facts_list if row["center_of_mass"] is not None) / volume
                                   for axis in range(3)] if volume else None
    verdict = {"valid": False} if any(check is not None and not check["valid"] for check in checks) else (
        {"valid": True} if all(check is not None for check in checks) else None)
    return measurement_dict(facts, verdict)


def measurements(shape):
    facts = {field: compute(shape) for field, compute in COMPUTE.items()}
    facts["solid_count"] = len(shape.Solids)
    return measurement_dict(facts, check_shape(shape))


def source_of(obj):
    seen = set()
    while getattr(obj, "LinkedObject", None) is not None:
        key = (obj.Document.Name, obj.Name)
        if key in seen:
            break
        seen.add(key)
        linked = obj.LinkedObject
        obj = linked[0] if isinstance(linked, tuple) else linked
    if obj.TypeId == "PartDesign::Body" and obj.Tip is not None:
        return obj.Tip
    return obj


class GeometryCache:
    CHECK_LIMIT = 1024
    PAIR_LIMIT = 4096

    def __init__(self, observer=None, shape_of=None, dependencies_of=None):
        self.observer = observer
        self.shape_of = shape_of or (lambda obj: obj.Shape)
        self.dependencies_of = dependencies_of or (lambda obj: ())
        self._documents = {}
        self._facts = {}
        self._checks = OrderedDict()
        self._pairs = OrderedDict()
        self.stats = {"computed": {field: 0 for field in (*COMPUTE, "check")},
                      "memo": defaultdict(int)}

    def bind(self, doc):
        self._documents[doc.Name] = doc
        _PROVIDERS[doc.Name] = self

    def documents(self):
        return tuple(self._documents)

    def _version(self, obj, shape_only=False):
        if self.observer is None:
            return 0
        return self.observer.version(obj.Document, obj.Name, shape_only=shape_only)

    def key(self, obj):
        source = source_of(obj)
        inputs = [obj, source, *self.dependencies_of(obj)]
        versions = tuple((item.Document.Name, item.Name, self._version(item)) for item in inputs)
        return versions, source.Shape.hashCode()

    def check_key(self, obj):
        source = source_of(obj)
        return source.Document.Name, source.Name, self._version(source, shape_only=True), source.Shape.hashCode()

    def facts(self, obj, fields):
        self.bind(obj.Document)
        key = self.key(obj)
        slot = (obj.Document.Name, obj.Name)
        stored = self._facts.get(slot)
        if stored is None or stored[0] != key:
            stored = (key, {"solid_count": len(source_of(obj).Shape.Solids)})
            self._facts[slot] = stored
        facts = stored[1]
        missing = [field for field in fields if field not in facts]
        if missing:
            shape = self.shape_of(obj)
            for field in missing:
                facts[field] = COMPUTE[field](shape)
                self.stats["computed"][field] += 1
        return {"solid_count": facts["solid_count"], **{field: facts[field] for field in fields}}

    def seed(self, obj, field, value):
        self.facts(obj, ())
        self._facts[(obj.Document.Name, obj.Name)][1][field] = value

    def check(self, obj, compute=False):
        self.bind(obj.Document)
        key = self.check_key(obj)
        if key not in self._checks and compute:
            # Native checks may update a modeled shape's serialization cache.
            # Keep the original source token, but check detached topology.
            self._checks[key] = check_shape(source_of(obj).Shape.copy())
            self.stats["computed"]["check"] += 1
            while len(self._checks) > self.CHECK_LIMIT:
                self._checks.popitem(last=False)
        value = self._checks.get(key)
        if value is not None:
            self._checks.move_to_end(key)
        return None if value is None else dict(value, issues=list(value["issues"]))

    def accept_checks(self, entries):
        """Atomically import detached verdicts under validated parent keys.

        The controller owns native identity/topology validation. This method
        validates every payload before touching the cache and never substitutes
        worker-process topology hashes for the captured parent keys.
        """
        prepared = []
        for key, value in entries:
            if (type(value.get("valid")) is not bool or not isinstance(value.get("issues"), list)
                    or any(not isinstance(issue, str) for issue in value["issues"])
                    or type(value.get("ms")) not in (int, float)
                    or not math.isfinite(value["ms"]) or value["ms"] < 0):
                raise ValueError("Invalid geometry check verdict")
            hash(key)
            prepared.append((key, {"valid": value["valid"], "issues": list(value["issues"]), "ms": value["ms"]}))
        receipt = []
        for key, value in prepared:
            receipt.append((key, self._checks.get(key), value))
            self._checks[key] = value
            self._checks.move_to_end(key)
        while len(self._checks) > self.CHECK_LIMIT:
            self._checks.popitem(last=False)
        return receipt

    def discard_accepted_checks(self, receipt):
        """Undo only this import if native status reads invalidate its owner."""
        for key, previous, inserted in reversed(receipt):
            if self._checks.get(key) is inserted:
                if previous is None:
                    del self._checks[key]
                else:
                    self._checks[key] = previous

    def memo(self, kind, objects, parameters, compute):
        key = kind, tuple(self.key(obj) for obj in objects), parameters
        if key not in self._pairs:
            self._pairs[key] = compute()
            self.stats["memo"][kind] += 1
            while len(self._pairs) > self.PAIR_LIMIT:
                self._pairs.popitem(last=False)
        self._pairs.move_to_end(key)
        return self._pairs[key]

    def drop_object(self, doc, name):
        self._facts.pop((doc.Name, name), None)

    def drop_document(self, name):
        name = name.Name if hasattr(name, "Name") else name
        self._documents.pop(name, None)
        if _PROVIDERS.get(name) is self:
            _PROVIDERS.pop(name, None)
        self._facts = {key: value for key, value in self._facts.items() if key[0] != name}
        self._checks = OrderedDict((key, value) for key, value in self._checks.items() if key[0] != name)
        self._pairs = OrderedDict((key, value) for key, value in self._pairs.items()
                                  if all(doc_name != name for token in key[1] for doc_name, _, _ in token[0]))

    def close(self):
        for name in tuple(self._documents):
            self.drop_document(name)
