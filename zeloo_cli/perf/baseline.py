"""Performance baseline registry and regression detector.

A *baseline* is a captured set of measurements for a benchmark suite
at a point in time. We compare new measurements against the baseline
to detect regressions before they ship.

Why a custom registry instead of ``pytest-benchmark``'s storage?
  * We want a portable JSON format that lives in git so a PR can
    say "I changed the baseline, here's the diff."
    - pytest-benchmark stores binary JSON-ish blobs with absolute
      paths and host-specific metadata; ours strips everything but
      measurements + suite name + host class.
  * We want *severity levels* (warning / error / critical) tied
    to percentage thresholds so CI can choose what to do.
  * We want an *ignore list* — startup overhead on cold CI runners
    is expected noise and should not page anyone.

Conventions
-----------
* All time-based measurements use **seconds** as the unit.
* All size-based measurements use **bytes**.
* All rate measurements use **fraction in [0, 1]**.
* A *higher* measurement is always worse than a *lower* measurement
  for latency, but for hit-rate the opposite is true. The detector
  flips the comparison direction based on the unit string so callers
  don't have to remember which way is "up".
"""

from __future__ import annotations

import json
import logging
import os
import platform
import statistics
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── defaults ──────────────────────────────────────────────────────────


#: Default location for stored baselines (one file per suite).
DEFAULT_BASELINE_DIR = Path(
    os.environ.get("ZELOO_PERF_BASELINES", "~/.Zeloo/perf-baselines")
).expanduser()


#: Default regression thresholds (percentages).
#:
#: * ``warning`` — soft signal, log only.
#: * ``error`` — surface in the report; ``zeloo perf check`` exits non-zero.
#: * ``critical`` — block CI; same exit code but with a louder message.
DEFAULT_THRESHOLDS: Mapping[str, float] = {
    "warning": 10.0,
    "error": 25.0,
    "critical": 50.0,
}


#: Default unit lists — lower-is-better (latency) vs. higher-is-better
#: (hit-rate, throughput). Anything not listed falls back to
#: lower-is-better for safety (a slow regression is always bad).
LOWER_IS_BETTER_UNITS: frozenset[str] = frozenset(
    {"s", "ms", "us", "ns", "bytes", "kb", "mb", "count", "ops"}
)
HIGHER_IS_BETTER_UNITS: frozenset[str] = frozenset(
    {"ratio", "rate", "pct", "percent"}
)


# ── dataclasses ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class BenchmarkMeasurement:
    """A single named measurement.

    Attributes:
        name: Dotted name like ``"system_prompt.cold_build_ms"``.
        value: The observed value.
        unit: One of ``s``, ``ms``, ``ratio``, ``bytes``, …
        samples: Optional list of raw samples used to derive
            ``value`` (median is the canonical value).
    """

    name: str
    value: float
    unit: str = "ms"
    samples: tuple[float, ...] = ()


@dataclass
class BenchmarkSuite:
    """A named collection of measurements from one run."""

    suite_name: str
    measurements: list[BenchmarkMeasurement] = field(default_factory=list)
    host_class: str = ""
    recorded_at: float = 0.0

    def to_baseline(self, *, host: str = "") -> Baseline:
        """Promote this run to a :class:`Baseline` for storage."""
        return Baseline(
            suite_name=self.suite_name,
            measurements={
                m.name: {
                    "value": m.value,
                    "unit": m.unit,
                    "samples": list(m.samples),
                }
            for m in self.measurements
            },
            recorded_at=self.recorded_at or time.time(),
            host_class=host or self.host_class,
        )


@dataclass
class Baseline:
    """A captured set of reference measurements for a suite.

    Stored as JSON. The ``host_class`` field lets a CI matrix
    distinguish, e.g., "linux-x86_64-cpython-3.12" from
    "macos-arm64-cpython-3.13" — useful when comparing apples to
    apples across runners.
    """

    suite_name: str
    measurements: dict[str, dict[str, Any]]
    recorded_at: float
    host_class: str = ""


# ── registry ──────────────────────────────────────────────────────────


class BaselineRegistry:
    """Persist baselines on disk, one JSON file per suite.

    Files live in :data:`DEFAULT_BASELINE_DIR` by default. The
    directory is created lazily on first write.

    File layout::

            {dir}/system_prompt.json
            {dir}/cache_e2e.json

    Each file::

            {
                "suite_name": "system_prompt",
                "host_class": "linux-x86_64",
                "recorded_at": 1700000000.0,
                "measurements": {
                    "cold_build_ms": {"value": 412.0, "unit": "ms", "samples": []}
                }
            }
    """

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self.base_dir = Path(
            base_dir if base_dir is not None else DEFAULT_BASELINE_DIR
        ).expanduser()

    # ── read / write ─────────────────────────────────────────────

    def save(self, baseline: Baseline) -> Path:
        """Persist a baseline. Returns the path it was written to."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        path = self._path_for(baseline.suite_name)
        payload = {
            "suite_name": baseline.suite_name,
            "host_class": baseline.host_class,
            "recorded_at": baseline.recorded_at,
            "measurements": baseline.measurements,
        }
        tmp = path.with_suffix(path.suffix + ".partial")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        # ``Path.replace`` is cross-platform (handles Windows where
        # ``os.replace`` may be denied inside sandboxes).
        Path(tmp).replace(path)
        logger.info("baseline saved: %s (%d measurements)", path.name, len(baseline.measurements))
        return path

    def load(self, suite_name: str) -> Baseline:
        """Load a baseline by suite name. Raises FileNotFoundError."""
        path = self._path_for(suite_name)
        if not path.exists():
            raise FileNotFoundError(f"no baseline for suite {suite_name!r}: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return Baseline(
            suite_name=payload["suite_name"],
            measurements=payload.get("measurements", {}),
            recorded_at=float(payload.get("recorded_at", 0.0)),
            host_class=str(payload.get("host_class", "")),
        )

    def exists(self, suite_name: str) -> bool:
        return self._path_for(suite_name).exists()

    def list_suites(self) -> list[str]:
        """Return all stored suite names, sorted alphabetically."""
        if not self.base_dir.exists():
            return []
        return sorted(p.stem for p in self.base_dir.glob("*.json"))

    def delete(self, suite_name: str) -> bool:
        """Delete a baseline. Returns True if anything was deleted."""
        path = self._path_for(suite_name)
        if not path.exists():
            return False
        path.unlink()
        return True

    # ── helpers ─────────────────────────────────────────────────

    def _path_for(self, suite_name: str) -> Path:
        # Sanitise so a malicious suite name can't escape the dir.
        # Replace path separators, ".." traversal sequences, and any
        # other characters that aren't filename-safe.
        cleaned = "".join(
            c if (c.isalnum() or c in "._-") else "_"
            for c in suite_name.strip()
        )
        if not cleaned or cleaned in (".", ".."):
            raise ValueError(f"invalid suite_name: {suite_name!r}")
        return self.base_dir / f"{cleaned}.json"


# ── regression detector ───────────────────────────────────────────────


class RegressionSeverity(StrEnum):
    """How serious a detected regression is."""

    NONE = "none"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class RegressionReport:
    """Result of comparing a run against a baseline.

    Attributes:
        suite_name: Which suite this report covers.
        regressions: Per-measurement results, keyed by measurement name.
            Each entry has ``baseline_value``, ``current_value``,
            ``delta_pct``, ``severity``, and ``unit``.
        max_severity: The highest severity seen across all measurements.
        overall_ok: True if there are no error/critical regressions.
        message: Human-readable summary suitable for CI logs.
    """

    suite_name: str
    regressions: dict[str, dict[str, Any]]
    max_severity: RegressionSeverity
    overall_ok: bool
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_name": self.suite_name,
            "regressions": self.regressions,
            "max_severity": self.max_severity.value,
            "overall_ok": self.overall_ok,
            "message": self.message,
        }


class RegressionDetector:
    """Compare a :class:`BenchmarkSuite` against a :class:`Baseline`.

    The detector classifies each measurement into one of four
    severity buckets:

    =============  ==========================================
    Severity       Trigger
    =============  ==========================================
    ``none``       |delta| < warning threshold
    ``warning``    warning ≤ |delta| < error
    ``error``      error ≤ |delta| < critical
    ``critical``   |delta| ≥ critical threshold
    =============  ==========================================

    The *direction* of the comparison depends on the unit:
    higher latency → regression, lower hit-rate → regression.

    Args:
        thresholds: Optional override for the warning/error/critical
            percentages. Defaults to :data:`DEFAULT_THRESHOLDS`.
        ignore: Iterable of measurement names (or name prefixes
            ending in ``*``) that should be excluded from the report.
            Useful for noisy startup overhead on cold runners.
        lower_is_better: Set of units where lower = better. Defaults
            to :data:`LOWER_IS_BETTER_UNITS`.
    """

    def __init__(
        self,
        *,
        thresholds: Mapping[str, float] | None = None,
        ignore: Iterable[str] | None = None,
        lower_is_better: Iterable[str] | None = None,
        higher_is_better: Iterable[str] | None = None,
    ) -> None:
        self.thresholds: dict[str, float] = dict(thresholds or DEFAULT_THRESHOLDS)
        self.ignore: tuple[str, ...] = tuple(ignore or ())
        self.lower_is_better: frozenset[str] = frozenset(
            lower_is_better if lower_is_better is not None else LOWER_IS_BETTER_UNITS
        )
        self.higher_is_better: frozenset[str] = frozenset(
            higher_is_better if higher_is_better is not None else HIGHER_IS_BETTER_UNITS
        )

    # ── public API ──────────────────────────────────────────────

    def compare(
        self,
        baseline: Baseline,
        suite: BenchmarkSuite,
    ) -> RegressionReport:
        """Compare the suite against the baseline.

        Measurements present in the suite but missing from the
        baseline are reported as ``new`` (no regression). Measurements
        in the baseline but missing from the suite are reported as
        ``missing`` (might be a removed test, never a regression).
        """
        regressions: dict[str, dict[str, Any]] = {}
        max_severity = RegressionSeverity.NONE

        baseline_msmts = baseline.measurements
        current_by_name = {m.name: m for m in suite.measurements}

        # Compare present-in-both measurements.
        for name, base_data in baseline_msmts.items():
            if self._is_ignored(name):
                continue
            base_value = float(base_data.get("value", 0.0))
            unit = str(base_data.get("unit", "ms"))
            if name not in current_by_name:
                # Test was removed; not a regression, but worth noting.
                regressions[name] = {
                    "status": "missing",
                    "baseline_value": base_value,
                    "current_value": None,
                    "delta_pct": 0.0,
                    "severity": RegressionSeverity.NONE.value,
                    "unit": unit,
                    "direction": _direction_for(unit, self.lower_is_better, self.higher_is_better),
                }
                continue
            current = current_by_name[name]
            delta_pct, direction = _compute_delta(
                base_value, current.value, unit, self.lower_is_better, self.higher_is_better
            )
            severity = self._classify(delta_pct, direction)
            if severity == RegressionSeverity.NONE and delta_pct == 0.0 and current.value == base_value:
                status = "unchanged"
            elif severity == RegressionSeverity.NONE:
                # Movement in the good direction is improvement;
                # movement in the bad direction (but below threshold) is within_noise.
                if (direction == "lower" and delta_pct < 0) or (
                    direction == "higher" and delta_pct > 0
                ):
                    status = "improved"
                else:
                    status = "within_noise"
            else:
                status = "regression"
            regressions[name] = {
                "status": status,
                "baseline_value": base_value,
                "current_value": current.value,
                "delta_pct": round(delta_pct, 2),
                "severity": severity.value,
                "unit": unit,
                "direction": direction,
            }
            if _severity_rank(severity) > _severity_rank(max_severity):
                max_severity = severity

        # Mark new measurements as not-in-baseline.
        for name, m in current_by_name.items():
            if name in regressions or self._is_ignored(name):
                continue
            unit = m.unit
            direction = _direction_for(unit, self.lower_is_better, self.higher_is_better)
            regressions[name] = {
                "status": "new",
                "baseline_value": None,
                "current_value": m.value,
                "delta_pct": 0.0,
                "severity": RegressionSeverity.NONE.value,
                "unit": unit,
                "direction": direction,
            }

        overall_ok = max_severity not in (RegressionSeverity.ERROR, RegressionSeverity.CRITICAL)
        message = _build_message(suite.suite_name, regressions, max_severity)
        return RegressionReport(
            suite_name=suite.suite_name,
            regressions=regressions,
            max_severity=max_severity,
            overall_ok=overall_ok,
            message=message,
        )

    # ── helpers ─────────────────────────────────────────────────

    def _is_ignored(self, name: str) -> bool:
        for pattern in self.ignore:
            if pattern.endswith("*") and name.startswith(pattern[:-1]):
                return True
            if pattern == name:
                return True
        return False

    def _classify(self, delta_pct: float, direction: str) -> RegressionSeverity:
        """Classify a delta into a severity bucket.

        A *regression* is a movement in the wrong direction (latency
        up, hit-rate down). Movement in the right direction is always
        ``none`` regardless of magnitude.

        ``delta_pct`` is signed: positive means *current > baseline*,
        negative means *current < baseline*.

        For ``direction == "lower"`` (latency) the bad direction is
        ``delta_pct > 0`` (latency went up). For ``direction ==
        "higher"`` (hit-rate) the bad direction is ``delta_pct < 0``.
        """
        if direction == "lower":
            # Latency up = regression. delta_pct > 0 = regression.
            if delta_pct <= 0:
                return RegressionSeverity.NONE
            pct = delta_pct
        elif direction == "higher":
            # Hit-rate down = regression. delta_pct < 0 = regression.
            if delta_pct >= 0:
                return RegressionSeverity.NONE
            pct = -delta_pct
        else:
            # Unknown direction → cannot judge; treat as none.
            return RegressionSeverity.NONE
        if pct >= self.thresholds.get("critical", 50.0):
            return RegressionSeverity.CRITICAL
        if pct >= self.thresholds.get("error", 25.0):
            return RegressionSeverity.ERROR
        if pct >= self.thresholds.get("warning", 10.0):
            return RegressionSeverity.WARNING
        return RegressionSeverity.NONE


# ── module-level helpers ──────────────────────────────────────────────


def _direction_for(
    unit: str,
    lower_is_better: frozenset[str],
    higher_is_better: frozenset[str],
) -> str:
    if unit in higher_is_better:
        return "higher"
    if unit in lower_is_better:
        return "lower"
    # Unknown unit → assume lower-is-better for safety.
    return "lower"


def _compute_delta(
    baseline: float,
    current: float,
    unit: str,
    lower_is_better: frozenset[str],
    higher_is_better: frozenset[str],
) -> tuple[float, str]:
    direction = _direction_for(unit, lower_is_better, higher_is_better)
    if baseline == 0:
        # Avoid div-by-zero. Return 0 (treated as no change) so the
        # measurement is reported but never classified as a regression.
        return 0.0, direction
    delta_pct = ((current - baseline) / baseline) * 100.0
    return delta_pct, direction


def _severity_rank(severity: RegressionSeverity) -> int:
    return {
        RegressionSeverity.NONE: 0,
        RegressionSeverity.WARNING: 1,
        RegressionSeverity.ERROR: 2,
        RegressionSeverity.CRITICAL: 3,
    }[severity]


def _build_message(
    suite_name: str,
    regressions: Mapping[str, Mapping[str, Any]],
    max_severity: RegressionSeverity,
) -> str:
    """Compose a one-line summary suitable for CI logs."""
    if not regressions:
        return f"[{suite_name}] no measurements"
    counts = {"regression": 0, "improved": 0, "new": 0, "missing": 0, "unchanged": 0}
    for entry in regressions.values():
        status = entry.get("status", "")
        if status == "regression":
            counts["regression"] += 1
        elif status == "improved":
            counts["improved"] += 1
        elif status == "new":
            counts["new"] += 1
        elif status == "missing":
            counts["missing"] += 1
        else:
            counts["unchanged"] += 1
    parts = [
        f"[{suite_name}]",
        f"max={max_severity.value}",
        f"regressions={counts['regression']}",
        f"improved={counts['improved']}",
        f"new={counts['new']}",
        f"missing={counts['missing']}",
    ]
    return " ".join(parts)


# ── convenience: capture host class ───────────────────────────────────


def capture_host_class() -> str:
    """Return a stable, short identifier of the host."""
    return f"{platform.system().lower()}-{platform.machine()}-{platform.python_version()}"


# ── convenience: compute median of repeated samples ───────────────────


def median_measurement(
    name: str,
    samples: Iterable[float],
    *,
    unit: str = "ms",
) -> BenchmarkMeasurement:
    """Build a :class:`BenchmarkMeasurement` from raw samples.

    Median is the canonical "value" because it's robust to one-off
    spikes (unlike mean) and never undershoots a percentile (unlike
    min). 5+ samples recommended.
    """
    samples_list = tuple(float(s) for s in samples)
    if not samples_list:
        raise ValueError("at least one sample is required")
    value = statistics.median(samples_list)
    return BenchmarkMeasurement(
        name=name,
        value=value,
        unit=unit,
        samples=samples_list,
    )


__all__ = [
    "Baseline",
    "BaselineRegistry",
    "BenchmarkMeasurement",
    "BenchmarkSuite",
    "RegressionDetector",
    "RegressionReport",
    "RegressionSeverity",
    "DEFAULT_BASELINE_DIR",
    "DEFAULT_THRESHOLDS",
    "LOWER_IS_BETTER_UNITS",
    "HIGHER_IS_BETTER_UNITS",
    "capture_host_class",
    "median_measurement",
]