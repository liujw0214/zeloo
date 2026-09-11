"""Performance baseline + regression detection.

Two complementary concerns live in this package:

1. **Baseline registry** — store and load named *performance baselines*
   (a snapshot of measurements keyed by suite name) so a CI run can
   compare its measurements to a known-good reference instead of
   always running against hard-coded thresholds.

2. **Regression detector** — diff current measurements against the
   baseline and emit a structured report with three severity levels
   (warning / error / critical) so the build can fail loudly on
   regressions while still tolerating normal CI noise.

The default location for baselines is ``~/.Zeloo/perf-baselines/`` —
one file per ``suite_name``. Baselines are JSON so they're diffable
in git and reviewable in pull requests.
"""

from __future__ import annotations

from zeloo_cli.perf.baseline import (
    DEFAULT_BASELINE_DIR,
    DEFAULT_THRESHOLDS,
    Baseline,
    BaselineRegistry,
    BenchmarkMeasurement,
    BenchmarkSuite,
    RegressionDetector,
    RegressionReport,
    RegressionSeverity,
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
]