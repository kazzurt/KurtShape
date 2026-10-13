"""Cache native-property reads while preserving the full document hash contract."""
import hashlib
import json


class IntentCache:
    def __init__(self, document):
        self.document = document
        self.epoch = None
        self.records = {}
        self.object_reads = self.hits = 0
        self.last_read_names = ()

    def signature(self, doc, state, read_intent):
        for _ in range(3):
            serial = state["change_serial"]
            result = self._signature_once(doc, state, read_intent)
            if serial == state["change_serial"]:
                return result
        raise RuntimeError("Native document changed while reading intent; retry")

    def _signature_once(self, doc, state, read_intent):
        if doc != self.document:
            raise ValueError("Intent cache belongs to another native document")
        epoch = state["intent_epoch"]
        if epoch != self.epoch:
            self.records.clear()
            self.epoch = epoch
        objects = state["index"].objects()
        names = {obj.Name for obj in objects}
        for name in self.records.keys() - names:
            self.records.pop(name, None)
        digest = hashlib.sha256()
        digest.update(b'{"label": ')
        digest.update(json.dumps(doc.Label).encode())
        digest.update(b', "objects": [')
        first, read_names = True, []
        for obj in objects:
            version = state["intent_versions"].get(obj.Name, 0)
            stored = self.records.get(obj.Name)
            if stored is None or stored[0] != version:
                rows = read_intent(doc, [obj])
                payload = json.dumps(rows[0], sort_keys=True).encode() if rows else None
                stored = (version, payload)
                self.object_reads += 1
                read_names.append(obj.Name)
                if state["intent_epoch"] == epoch and state["intent_versions"].get(obj.Name, 0) == version:
                    self.records[obj.Name] = stored
            else:
                self.hits += 1
            if stored[1] is None:
                continue
            if not first:
                digest.update(b", ")
            digest.update(stored[1])
            first = False
        digest.update(b"]}")
        self.last_read_names = tuple(read_names)
        return digest.hexdigest()


def signature(doc, observer, read_intent):
    state = observer.state(doc)
    cache = state.get("intent_cache")
    if cache is None:
        cache = state["intent_cache"] = IntentCache(doc)
    return cache.signature(doc, state, read_intent)
