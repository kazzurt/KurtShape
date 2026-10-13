"""Exclusive transient tool ownership, independent of Qt and FreeCAD."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ToolState:
    kind: str = "idle"
    value: object = None
    owner: object = None


class ToolSession:
    KINDS = frozenset({"idle", "native", "reference", "dimension"})

    def __init__(self):
        self.state = ToolState()
        self.generation = 0
        self.closed = False

    @property
    def active(self):
        return self.state.kind != "idle"

    def select(self, kind, value=None, owner=None):
        if self.closed:
            raise RuntimeError("Tool session is closed")
        if kind not in self.KINDS:
            raise ValueError("Unknown tool kind: " + str(kind))
        if kind == "idle":
            value = owner = None
        elif value is None or owner is None:
            raise ValueError("An active tool requires a value and owner")
        self.generation += 1
        self.state = ToolState(kind, value, owner)

    def clear(self, kind=None):
        if not self.active or kind is not None and self.state.kind != kind:
            return False
        self.select("idle")
        return True

    def invalidate_callbacks(self):
        self.generation += 1

    def current(self, generation):
        return not self.closed and generation == self.generation

    def close(self):
        if not self.closed:
            self.generation += 1
            self.state = ToolState()
            self.closed = True
