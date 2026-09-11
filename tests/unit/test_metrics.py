"""Tests for zeloo_cli.core.metrics."""

from __future__ import annotations

import threading

from zeloo_cli.core.metrics import HistogramStats, MetricsCollector


class TestHistogramStats:
    def test_empty_samples(self) -> None:
        stats = HistogramStats()
        stats.update_from([])
        assert stats.count == 0
        assert stats.sum == 0.0
        assert stats.mean == 0.0
        assert stats.p50 == 0.0
        assert stats.p95 == 0.0
        assert stats.p99 == 0.0

    def test_single_sample(self) -> None:
        """A single sample should equal every percentile."""
        stats = HistogramStats()
        stats.update_from([42.0])
        assert stats.count == 1
        assert stats.min == 42.0
        assert stats.max == 42.0
        assert stats.mean == 42.0
        assert stats.p50 == 42.0
        assert stats.p95 == 42.0
        assert stats.p99 == 42.0

    def test_known_distribution(self) -> None:
        """Verify nearest-rank percentile on a 0..99 sample set.

        samples = list(range(100)) → 0,1,...,99
        p50 idx = int(0.50 * 99) = 49 → 49.0
        p95 idx = int(0.95 * 99) = 94 → 94.0
        p99 idx = int(0.99 * 99) = 98 → 98.0
        """
        stats = HistogramStats()
        stats.update_from(list(range(100)))
        assert stats.count == 100
        assert stats.min == 0.0
        assert stats.max == 99.0
        assert stats.mean == 49.5
        assert stats.p50 == 49.0
        assert stats.p95 == 94.0
        assert stats.p99 == 98.0

    def test_unsorted_input_handled(self) -> None:
        stats = HistogramStats()
        stats.update_from([3, 1, 4, 1, 5, 9, 2, 6])
        assert stats.min == 1.0
        assert stats.max == 9.0
        assert stats.mean == 31 / 8

    def test_two_samples(self) -> None:
        """Edge case: n=2 → only index 0 and 1 are valid.

        q=0.50 → int(0.50 * 1) = 0 → first sample
        q=0.95 → int(0.95 * 1) = 0 → first sample (clamped to 0)
        q=0.99 → int(0.99 * 1) = 0 → first sample
        """
        stats = HistogramStats()
        stats.update_from([10.0, 20.0])
        assert stats.min == 10.0
        assert stats.max == 20.0
        assert stats.mean == 15.0
        assert stats.p50 == 10.0
        assert stats.p95 == 10.0
        assert stats.p99 == 10.0


class TestMetricsCollector:
    def test_counter_increments(self) -> None:
        c = MetricsCollector()
        c.counter("requests_total", 1.0)
        c.counter("requests_total", 2.0)
        assert c.get_counter("requests_total") == 3.0

    def test_gauge_sets_value(self) -> None:
        c = MetricsCollector()
        c.gauge("queue_size", 10.0)
        c.gauge("queue_size", 20.0)
        assert c.get_gauge("queue_size") == 20.0

    def test_histogram_capped(self) -> None:
        """Exceeding max samples must evict from the front, not append forever."""
        c = MetricsCollector()
        c._max_histogram_samples = 100
        for i in range(150):
            c.histogram("latency_ms", float(i))
        stats = c.get_histogram_stats("latency_ms")
        assert stats.count == 100
        # Oldest 50 entries (0..49) were dropped; newest are 50..149
        assert stats.min == 50.0
        assert stats.max == 149.0

    def test_histogram_labels_isolation(self) -> None:
        c = MetricsCollector()
        c.histogram("latency", 1.0, route="a")
        c.histogram("latency", 100.0, route="b")
        assert c.get_histogram_stats("latency", route="a").max == 1.0
        assert c.get_histogram_stats("latency", route="b").max == 100.0

    def test_labels_sort_is_deterministic(self) -> None:
        c = MetricsCollector()
        c.counter("hits", 1, region="us", route="/a")
        # Same labels, different order → same key
        assert c.get_counter("hits", route="/a", region="us") == 1.0

    def test_export_contains_all_metric_types(self) -> None:
        c = MetricsCollector()
        c.counter("counter_x", 1)
        c.gauge("gauge_x", 2.0)
        c.histogram("hist_x", 3.0)
        out = c.export()
        names = {m["name"] for m in out}
        assert names == {"counter_x", "gauge_x", "hist_x"}

    def test_thread_safety(self) -> None:
        c = MetricsCollector()
        threads = [
            threading.Thread(target=lambda: c.counter("req", 1))
            for _ in range(50)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert c.get_counter("req") == 50.0

    def test_max_history_ring(self) -> None:
        """``_max_history`` ring buffer must cap internal history length."""
        c = MetricsCollector()
        c._max_history = 10
        for _ in range(20):
            c.counter("c", 1)
        # History is internal; we just confirm the cap is enforced.
        assert len(c._history) <= 10