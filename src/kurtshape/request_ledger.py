"""Session-scoped retry records. Transport threads never touch native objects."""
from collections import OrderedDict
import copy
import hashlib
import json
import threading
import time
import uuid


class RequestLedger:
    def __init__(self, limit=512):
        self.session_id = str(uuid.uuid4())
        self.limit = limit
        self.session_request_limit = limit * 8
        self.records = OrderedDict()
        self.expired = OrderedDict()
        self.lock = threading.RLock()

    def register(self, request, status):
        identifier = request.get("request_id")
        if not isinstance(identifier, str) or not 1 <= len(identifier) <= 128:
            return {"ok": False, "error": {"code": "invalid_request_id", "message": "request_id requires 1–128 characters"}}
        digest = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        with self.lock:
            if identifier in self.expired:
                return {"ok": False, "error": {"code": "request_expired", "message": "Result was evicted; inspect and reconcile before a new request"}}
            record = self.records.get(identifier)
            if record:
                if digest != record["digest"]:
                    return {"ok": False, "error": {"code": "request_id_reused", "message": "request_id already identifies a different payload"}}
                if "response" in record:
                    return copy.deepcopy(record["response"])
                if status == "started" and record["status"] == "queued":
                    record["status"] = status
                    return None
                return {"ok": False, "error": {"code": "request_pending", "message": "Request is already queued or started; use request_status", "status": record["status"]}}
            if len(self.records) + len(self.expired) >= self.session_request_limit:
                return {"ok": False, "error": {"code": "request_capacity_reached", "message": "Session retry capacity is full; reconcile and restart before new requests"}}
            self.records[identifier] = {"digest": digest, "status": status, "created": time.time()}
            return None

    def complete(self, identifier, response, status=None):
        with self.lock:
            record = self.records[identifier]
            record.update(status=status or ("completed" if response["ok"] else "failed"), response=copy.deepcopy(response))
            for key in list(self.records):
                if len(self.records) <= self.limit:
                    break
                if "response" in self.records[key]:
                    self.records.pop(key)
                    self.expired[key] = True

    def status(self, identifier):
        with self.lock:
            record = self.records.get(identifier)
            result = {"request_id": identifier, "session_id": self.session_id,
                      "status": record["status"] if record else ("expired" if identifier in self.expired else "not_recorded")}
            if record and "response" in record:
                result["response"] = copy.deepcopy(record["response"])
            return result


class RequestStatusLookup:
    """Opt-in, JSON-only lookup for the canonical Controller status request.

    Configuration is the supported owner's plain instance dictionary. Only
    ledger identity and primitive default_measure are read here; no owner
    method, descriptor, native document or timing collector is accessed.
    All other payloads retain the existing owner-thread validation path.
    """
    def __init__(self, ledger, configuration):
        if type(ledger) is not RequestLedger or type(configuration) is not dict:
            raise TypeError("Status lookup requires the plain session ledger and configuration")
        self.ledger = ledger
        self._configuration = configuration

    def _valid_configuration(self):
        value = self._configuration.get("default_measure")
        return (self._configuration.get("ledger") is self.ledger
                and (type(value) is bool or type(value) is str and value == "full"))

    def lookup(self, request):
        if (type(request) is not dict or set(request) != {"op", "request_id"}
                or request["op"] != "request_status"
                or type(request["request_id"]) is not str
                or not 1 <= len(request["request_id"]) <= 128
                or not self._valid_configuration()):
            return None
        result = RequestLedger.status(self.ledger, request["request_id"])
        if not self._valid_configuration():
            return None
        return {"ok": True, "result": result}
