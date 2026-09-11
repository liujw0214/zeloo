"""Prometheus-format metrics collector for the HTTP gateway.

Records:

* HTTP request counts and latency histograms.
* Provider invocation counts and token usage totals.
* Error counts by ``error_type``.
* Active connection gauge.

Both a Prometheus text export (``get_metrics_text``) and a plain-dict
snapshot (``get_snapshot``) are exposed. The collector is thread-safe and
keeps all state in process memory — no external dependencies are used.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

# Default histogram buckets (seconds-ish — caller converts from ms).
_LATENCY_BUCKETS: tuple[float, ...] = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0,
)


class _Histogram:
    """Bucketed cumulative counter used by :class:`GatewayMetricsCollector`."""

    __slots__ = ("_counts", "_sum", "_count")

    def __init__(self, buckets: Iterable[float]) -> None:
        """Initialise empty buckets."""
        self._counts: dict[float, float] = {b: 0.0 for b in buckets}
        self._sum = 0.0
        self._count = 0.0

    def observe(self, value: float) -> None:
        """Record a single observation."""
        self._count += 1
        self._sum += value
        for boundary in self._counts:
            if value <= boundary:
                self._counts[boundary] += 1


class GatewayMetricsCollector:
    """In-process Prometheus-shaped metrics registry."""

    def __init__(self) -> None:
        """Create the empty registry."""
        self._lock = threading.Lock()
        # Requests: count + latency histogram, labelled by path/status.
        self._request_counts: dict[tuple[str, int], float] = defaultdict(float)
        self._request_latency: dict[tuple[str, int], _Histogram] = defaultdict(
            lambda: _Histogram(_LATENCY_BUCKETS)
        )
        # Provider calls and token totals, labelled by provider/model.
        self._provider_calls: dict[tuple[str, str], float] = defaultdict(float)
        self._provider_tokens: dict[tuple[str, str], float] = defaultdict(float)
        # Errors labelled by type.
        self._errors: dict[str, float] = defaultdict(float)
        # Active connection gauge.
        self._active_connections: float = 0.0
        # Process start time in seconds since epoch (for uptime metric).
        import time as _t
        self._start_time: float = _t.time()

    # ── Increment helpers ────────────────────────────────────────────

    def increment_request(self, path: str, status: int, duration_ms: float) -> None:
        """Record a single HTTP request + its latency."""
        key = (path, int(status))
        with self._lock:
            self._request_counts[key] += 1
            # Convert milliseconds → seconds so the buckets align with the
            # standard histogram convention used by Prometheus.
            self._request_latency[key].observe(max(0.0, duration_ms) / 1000.0)

    def increment_provider_call(self, provider: str, model: str, tokens: int) -> None:
        """Record a single upstream provider call + its token usage."""
        key = (provider, model)
        with self._lock:
            self._provider_calls[key] += 1
            self._provider_tokens[key] += max(0, int(tokens))

    def increment_error(self, error_type: str) -> None:
        """Bump the counter for ``error_type`` (e.g. ``"rate_limit"``)."""
        if not error_type:
            return
        with self._lock:
            self._errors[error_type] += 1

    def set_active_connections(self, count: int) -> None:
        """Set the active-connections gauge to ``count``."""
        with self._lock:
            self._active_connections = max(0, int(count))

    # ── Export helpers ───────────────────────────────────────────────

    def _format_labels(self, labels: dict[str, Any]) -> str:
        """Render a Prometheus label set inside curly braces."""
        if not labels:
            return ""
        parts = ",".join(
            f'{k}="{str(v).replace(chr(92), "\\\\").replace(chr(34), "\\\"")}"'
            for k, v in sorted(labels.items())
        )
        return "{" + parts + "}"

    def get_metrics_text(self) -> str:
        """Return the metrics registry in Prometheus text exposition format."""
        lines: list[str] = []
        with self._lock:
            # ── gateway_requests_total ─────────────────────────────────
            lines.append("# HELP gateway_requests_total Total HTTP requests served.")
            lines.append("# TYPE gateway_requests_total counter")
            for (path, status), count in sorted(self._request_counts.items()):
                labels = self._format_labels({"path": path, "status": status})
                lines.append(f"gateway_requests_total{labels} {count}")

            # ── gateway_request_duration_seconds ───────────────────────
            lines.append("# HELP gateway_request_duration_seconds Request latency histogram.")
            lines.append("# TYPE gateway_request_duration_seconds histogram")
            for (path, status), hist in sorted(self._request_latency.items()):
                labels_base = {"path": path, "status": status}
                for boundary in sorted(hist._counts):
                    le = "Inf" if boundary == float("inf") else str(boundary)
                    labels = self._format_labels({**labels_base, "le": le})
                    lines.append(
                        f'gateway_request_duration_seconds_bucket{labels} {hist._counts[boundary]}'
                    )
                lines.append(
                    f'gateway_request_duration_seconds_count{self._format_labels(labels_base)} '
                    f"{hist._count}"
                )
                lines.append(
                    f'gateway_request_duration_seconds_sum{self._format_labels(labels_base)} '
                    f"{hist._sum}"
                )

            # ── gateway_provider_calls_total ───────────────────────────
            lines.append("# HELP gateway_provider_calls_total Total upstream provider calls.")
            lines.append("# TYPE gateway_provider_calls_total counter")
            for (provider, model), count in sorted(self._provider_calls.items()):
                labels = self._format_labels({"provider": provider, "model": model})
                lines.append(f"gateway_provider_calls_total{labels} {count}")

            # ── gateway_provider_tokens_total ─────────────────────────
            lines.append("# HELP gateway_provider_tokens_total Total tokens billed by provider.")
            lines.append("# TYPE gateway_provider_tokens_total counter")
            for (provider, model), total in sorted(self._provider_tokens.items()):
                labels = self._format_labels({"provider": provider, "model": model})
                lines.append(f"gateway_provider_tokens_total{labels} {total}")

            # ── gateway_errors_total ───────────────────────────────────
            lines.append("# HELP gateway_errors_total Total errors by type.")
            lines.append("# TYPE gateway_errors_total counter")
            for error_type, count in sorted(self._errors.items()):
                labels = self._format_labels({"type": error_type})
                lines.append(f"gateway_errors_total{labels} {count}")

            # ── gateway_active_connections ─────────────────────────────
            lines.append("# HELP gateway_active_connections Currently open client connections.")
            lines.append("# TYPE gateway_active_connections gauge")
            lines.append(f"gateway_active_connections {self._active_connections}")

            # ── gateway_uptime_seconds ─────────────────────────────────
            import time as _t
            uptime = _t.time() - self._start_time
            lines.append("# HELP gateway_uptime_seconds Process uptime in seconds.")
            lines.append("# TYPE gateway_uptime_seconds gauge")
            lines.append(f"gateway_uptime_seconds {uptime:.3f}")

        return "\n".join(lines) + "\n"

    def get_snapshot(self) -> dict[str, Any]:
        """Return a plain-dict view of every metric for dashboards / tests."""
        snapshot: dict[str, Any] = {
            "requests": {},
            "request_latency": {},
            "provider_calls": {},
            "provider_tokens": {},
            "errors": dict(self._errors),
            "active_connections": self._active_connections,
        }
        with self._lock:
            for (path, status), count in self._request_counts.items():
                snapshot["requests"][f"{path}|{status}"] = count
            for (path, status), hist in self._request_latency.items():
                snapshot["request_latency"][f"{path}|{status}"] = {
                    "count": hist._count,
                    "sum": hist._sum,
                    "buckets": dict(hist._counts),
                }
            for (provider, model), count in self._provider_calls.items():
                snapshot["provider_calls"][f"{provider}|{model}"] = count
            for (provider, model), total in self._provider_tokens.items():
                snapshot["provider_tokens"][f"{provider}|{model}"] = total
        return snapshot