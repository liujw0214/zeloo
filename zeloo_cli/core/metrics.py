"""Metrics collection — counters, gauges, histograms."""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class HistogramStats:
    """Histogram statistics summary."""

    count: int = 0
    sum: float = 0.0
    min: float = float("inf")
    max: float = float("-inf")
    mean: float = 0.0
    p50: float = 0.0
    p95: float = 0.0
    p99: float = 0.0

    def update_from(self, samples: list[float]) -> None:
        """Recompute ``mean``, ``min``, ``max``, ``p50``, ``p95``, ``p99``.

        Uses the nearest-rank method so a single sample returns itself as
        every percentile (matches NumPy's default linear interpolation at
        index ``int(p * (n-1))``).

        The previous implementation only updated ``mean`` and computed the
        percentiles at the call site with an off-by-one index that always
        returned ``max`` for small sample sets.
        """
        if not samples:
            self.count = 0
            self.sum = 0.0
            self.min = float("inf")
            self.max = float("-inf")
            self.mean = 0.0
            self.p50 = 0.0
            self.p95 = 0.0
            self.p99 = 0.0
            return

        ordered = sorted(samples)
        n = len(ordered)
        self.count = n
        self.sum = float(sum(ordered))
        self.min = ordered[0]
        self.max = ordered[-1]
        self.mean = self.sum / n
        self.p50 = _percentile(ordered, 0.50)
        self.p95 = _percentile(ordered, 0.95)
        self.p99 = _percentile(ordered, 0.99)


def _percentile(sorted_samples: list[float], q: float) -> float:
    """Return the nearest-rank percentile of *sorted_samples*.

    Equivalent to ``statistics.quantiles(n=100)`` semantics with the
    minimal extra cost (O(1) given the already-sorted input).
    """
    n = len(sorted_samples)
    if n == 1:
        return sorted_samples[0]
    idx = max(0, min(n - 1, int(q * (n - 1))))
    return sorted_samples[idx]


@dataclass
class MetricPoint:
    """A single metric data point."""

    name: str
    value: float
    timestamp: float = field(default_factory=time.time)
    labels: dict[str, str] = field(default_factory=dict)


class MetricsCollector:
    """Collect counters, gauges, and histograms.

    Usage::
        metrics = MetricsCollector()
        metrics.counter("requests_total", 1)
        metrics.gauge("queue_size", 42)
        metrics.histogram("response_ms", 123.4)
    """

    def __init__(self) -> None:
        self._counters: dict[str, float] = defaultdict(float)
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = defaultdict(list)
        self._history: list[MetricPoint] = []
        self._max_history = 5000
        self._max_histogram_samples = 1000
        self._lock = threading.Lock()

    def counter(self, name: str, value: float = 1.0, **labels: Any) -> None:
        """Increment a counter."""
        key = self._make_key(name, labels)
        with self._lock:
            self._counters[key] += value
            self._record(name, self._counters[key], labels)

    def gauge(self, name: str, value: float, **labels: Any) -> None:
        """Set a gauge value."""
        key = self._make_key(name, labels)
        with self._lock:
            self._gauges[key] = value
            self._record(name, value, labels)

    def histogram(self, name: str, value: float, **labels: Any) -> None:
        """Record a histogram value."""
        key = self._make_key(name, labels)
        with self._lock:
            samples = self._histograms[key]
            samples.append(value)
            if len(samples) > self._max_histogram_samples:
                self._histograms[key] = samples[-self._max_histogram_samples:]
            self._record(name, value, labels)

    def get_counter(self, name: str, **labels: Any) -> float:
        key = self._make_key(name, labels)
        with self._lock:
            return self._counters.get(key, 0.0)

    def get_gauge(self, name: str, **labels: Any) -> float:
        key = self._make_key(name, labels)
        with self._lock:
            return self._gauges.get(key, 0.0)

    def get_histogram_stats(
        self, name: str, **labels: Any
    ) -> HistogramStats:
        key = self._make_key(name, labels)
        with self._lock:
            samples = list(self._histograms.get(key, []))
        stats = HistogramStats()
        stats.update_from(samples)
        return stats

    def export(self) -> list[dict[str, Any]]:
        """Export all metrics as list of dicts."""
        out: list[dict[str, Any]] = []
        with self._lock:
            for key, value in self._counters.items():
                out.append(self._key_to_metric(key, value, "counter"))
            for key, value in self._gauges.items():
                out.append(self._key_to_metric(key, value, "gauge"))
            for key, samples in self._histograms.items():
                if samples:
                    out.append(self._key_to_metric(
                        key, sum(samples) / len(samples), "histogram"
                    ))
        return out

    def _make_key(self, name: str, labels: dict[str, Any]) -> str:
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"

    def _key_to_metric(
        self, key: str, value: float, type_: str
    ) -> dict[str, Any]:
        if "{" in key:
            name, labels_str = key.split("{", 1)
            labels_str = labels_str.rstrip("}")
            labels = dict(
                pair.split("=", 1)
                for pair in labels_str.split(",")
                if "=" in pair
            )
        else:
            name = key
            labels = {}
        return {
            "name": name,
            "value": value,
            "type": type_,
            "labels": labels,
            "timestamp": time.time(),
        }

    def _record(
        self, name: str, value: float, labels: dict[str, Any]
    ) -> None:
        point = MetricPoint(name=name, value=value, labels=labels)
        self._history.append(point)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]


__all__ = ["MetricsCollector", "MetricPoint", "HistogramStats"]