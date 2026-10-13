"""Bounded GUI test waits; product preview acceptance never blocks like this."""
import time


def wait_for_exact(adapter, timeout_ms=30000):
    from PySide6 import QtTest
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        result = adapter.result
        if result is not None and not result.provisional:
            return result
        if adapter.closed or adapter.evaluator is None:
            raise AssertionError("Preview task closed before an exact result")
        QtTest.QTest.qWait(20)
    raise AssertionError("Exact preview did not finish within " + str(timeout_ms) + " ms")
