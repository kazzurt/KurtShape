"""Bounded local timing samples. Feedback and kernel time remain distinct."""
from collections import defaultdict, deque
import math
import statistics
import time


class Timings:
    def __init__(self):
        self.samples = defaultdict(lambda: deque(maxlen=512))

    def record(self, label, milliseconds):
        self.samples[label].append(milliseconds)

    def measure(self, label, function, *args, **kwargs):
        start = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            self.record(label, (time.perf_counter() - start) * 1000)

    def report(self):
        return {label: {"samples": len(values), "median_ms": round(statistics.median(values), 3),
                        "p95_ms": round(sorted(values)[math.ceil(len(values) * .95) - 1], 3),
                        "worst_ms": round(max(values), 3)} for label, values in self.samples.items() if values}
