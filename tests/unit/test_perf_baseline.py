"""Tests for ``zeloo_cli.perf.baseline`` — registry + regression detector."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from zeloo_cli.perf.baseline import (
    DEFAULT_THRESHOLDS,
    HIGHER_IS_BETTER_UNITS,
    LOWER_IS_BETTER_UNITS,
    Baseline,
    BaselineRegistry,
    BenchmarkMeasurement,
    BenchmarkSuite,
    RegressionDetector,
    RegressionSeverity,
    capture_host_class,
    median_measurement,
)

# ── helpers ────────────────────────────────────────────────────────────


def _make_baseline(suite: str = "smoke", **overrides) -> Baseline:
    """Build a baseline with three representative measurements."""
    return Baseline(
        suite_name=suite,
        measurements={
            "cold_build_ms": {"value": 412.0, "unit": "ms", "samples": []},
            "warm_cache_hit_ratio": {"value": 0.85, "unit": "ratio", "samples": []},
            "tool_discovery_ms": {"value": 75.0, "unit": "ms", "samples": []},
            **overrides,
        },
        recorded_at=1_700_000_000.0,
        host_class="test-host",
    )


def _make_suite(suite: str = "smoke", **overrides) -> BenchmarkSuite:
    measurements = [
        BenchmarkMeasurement(name="cold_build_ms", value=412.0, unit="ms"),
        BenchmarkMeasurement(name="warm_cache_hit_ratio", value=0.85, unit="ratio"),
        BenchmarkMeasurement(name="tool_discovery_ms", value=75.0, unit="ms"),
    ]
    for k, v in overrides.items():
        measurements.append(BenchmarkMeasurement(name=k, value=v[0], unit=v[1]))
    return BenchmarkSuite(
        suite_name=suite,
        measurements=measurements,
        recorded_at=1_700_000_100.0,
        host_class="test-host",
    )


def _make_overrides_suite(measurements: dict[str, tuple[float, str]]) -> BenchmarkSuite:
    return BenchmarkSuite(
        suite_name="smoke",
        measurements=[
            BenchmarkMeasurement(name=k, value=v[0], unit=v[1])
            for k, v in measurements.items()
        ],
        recorded_at=1_700_000_100.0,
    )


# ── registry ───────────────────────────────────────────────────────────


class TestBaselineRegistry:
    def test_save_and_load_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            reg = BaselineRegistry(base_dir=tmp)
            baseline = _make_baseline()
            path = reg.save(baseline)
            assert path.exists()
            # File is JSON.
            data = json.loads(path.read_text())
            assert data["suite_name"] == "smoke"
            # Roundtrip.
            loaded = reg.load("smoke")
            assert loaded.suite_name == "smoke"
            assert loaded.recorded_at == 1_700_000_000.0
            assert loaded.measurements["cold_build_ms"]["value"] == 412.0

    def test_save_creates_dir(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw) / "nested" / "baselines"
            reg = BaselineRegistry(base_dir=tmp)
            assert not tmp.exists()
            reg.save(_make_baseline())
            assert tmp.exists()

    def test_load_missing_raises(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            reg = BaselineRegistry(base_dir=Path(raw))
            with pytest.raises(FileNotFoundError):
                reg.load("no-such")

    def test_save_uses_atomic_rename(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            reg = BaselineRegistry(base_dir=tmp)
            reg.save(_make_baseline())
            # No .partial file should be left over.
            partials = list(tmp.glob("*.partial"))
            assert partials == []

    def test_list_suites_alphabetical(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            reg = BaselineRegistry(base_dir=tmp)
            reg.save(_make_baseline("zulu"))
            reg.save(_make_baseline("alpha"))
            reg.save(_make_baseline("mike"))
            assert reg.list_suites() == ["alpha", "mike", "zulu"]

    def test_delete_removes_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            reg = BaselineRegistry(base_dir=tmp)
            reg.save(_make_baseline())
            assert reg.exists("smoke")
            assert reg.delete("smoke") is True
            assert not reg.exists("smoke")
            # Idempotent.
            assert reg.delete("smoke") is False

    def test_path_traversal_blocked(self) -> None:
        """Suite names with path separators are sanitised so they
        can't escape the registry directory."""
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            reg = BaselineRegistry(base_dir=tmp)
            # Empty name is invalid.
            with pytest.raises(ValueError):
                reg._path_for("")
            # Bare ".." is invalid.
            with pytest.raises(ValueError):
                reg._path_for("..")
            # Path separators get flattened into a single filename
            # component — the result is always a direct child of base_dir.
            escaped = reg._path_for("../escape")
            assert escaped.parent == tmp
            assert "/" not in escaped.name
            assert "\\" not in escaped.name
            # Absolute paths are also flattened.
            abs_path = reg._path_for("/abs/path")
            assert abs_path.parent == tmp
            assert "/" not in abs_path.name

    def test_exists(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            reg = BaselineRegistry(base_dir=tmp)
            assert not reg.exists("smoke")
            reg.save(_make_baseline())
            assert reg.exists("smoke")


# ── BenchmarkMeasurement / Suite helpers ──────────────────────────────


class TestBenchmarkHelpers:
    def test_median_measurement_uses_median(self) -> None:
        m = median_measurement("foo", [1, 5, 3, 4, 2], unit="ms")
        assert m.value == 3.0
        assert m.unit == "ms"
        assert m.samples == (1, 5, 3, 4, 2)

    def test_median_measurement_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            median_measurement("foo", [], unit="ms")

    def test_to_baseline_copies_measurements(self) -> None:
        suite = BenchmarkSuite(
            suite_name="x",
            measurements=[
                BenchmarkMeasurement(name="a", value=1.0, unit="ms"),
                BenchmarkMeasurement(name="b", value=2.0, unit="ms"),
            ],
            recorded_at=1_700_000_000.0,
            host_class="h",
        )
        baseline = suite.to_baseline(host="override")
        assert baseline.suite_name == "x"
        assert baseline.host_class == "override"
        assert baseline.recorded_at == 1_700_000_000.0
        assert baseline.measurements["a"]["value"] == 1.0

    def test_capture_host_class(self) -> None:
        s = capture_host_class()
        # Should contain a dash-separated platform/arch/python triplet.
        parts = s.split("-")
        assert len(parts) >= 2


# ── RegressionDetector ─────────────────────────────────────────────────


class TestRegressionDetector:
    def test_no_change(self) -> None:
        baseline = _make_baseline()
        suite = _make_suite()
        report = RegressionDetector().compare(baseline, suite)
        assert report.overall_ok is True
        assert report.max_severity == RegressionSeverity.NONE
        for entry in report.regressions.values():
            assert entry["severity"] == RegressionSeverity.NONE.value

    def test_warning_severity_15pct_latency(self) -> None:
        # 412 → 478 = +16% → warning (10-25)
        baseline = _make_baseline()
        suite = _make_overrides_suite(
            {
                "cold_build_ms": (478.0, "ms"),
                "warm_cache_hit_ratio": (0.85, "ratio"),
                "tool_discovery_ms": (75.0, "ms"),
            }
        )
        report = RegressionDetector().compare(baseline, suite)
        assert report.max_severity == RegressionSeverity.WARNING
        assert report.overall_ok is True  # warning is still ok
        cold = report.regressions["cold_build_ms"]
        assert cold["severity"] == "warning"
        assert cold["delta_pct"] > 10.0

    def test_error_severity_30pct_latency(self) -> None:
        # 412 → 540 = +31% → error (25-50)
        baseline = _make_baseline()
        suite = _make_overrides_suite(
            {
                "cold_build_ms": (540.0, "ms"),
                "warm_cache_hit_ratio": (0.85, "ratio"),
                "tool_discovery_ms": (75.0, "ms"),
            }
        )
        report = RegressionDetector().compare(baseline, suite)
        assert report.max_severity == RegressionSeverity.ERROR
        assert report.overall_ok is False

    def test_critical_severity_60pct_latency(self) -> None:
        # 412 → 660 = +60% → critical
        baseline = _make_baseline()
        suite = _make_overrides_suite(
            {
                "cold_build_ms": (660.0, "ms"),
                "warm_cache_hit_ratio": (0.85, "ratio"),
                "tool_discovery_ms": (75.0, "ms"),
            }
        )
        report = RegressionDetector().compare(baseline, suite)
        assert report.max_severity == RegressionSeverity.CRITICAL

    def test_higher_is_better_direction(self) -> None:
        # Hit-rate drops → regression even though number is smaller.
        baseline = _make_baseline()
        suite = _make_overrides_suite(
            {
                "cold_build_ms": (412.0, "ms"),
                "warm_cache_hit_ratio": (0.50, "ratio"),  # 0.85 → 0.50 = -41%
                "tool_discovery_ms": (75.0, "ms"),
            }
        )
        report = RegressionDetector().compare(baseline, suite)
        assert report.max_severity == RegressionSeverity.ERROR
        ratio = report.regressions["warm_cache_hit_ratio"]
        assert ratio["direction"] == "higher"
        assert ratio["severity"] == "error"

    def test_improvement_is_not_regression(self) -> None:
        # Latency drops 50% — that's improvement, not regression.
        baseline = _make_baseline()
        suite = _make_overrides_suite(
            {
                "cold_build_ms": (206.0, "ms"),  # 412 → 206 = -50%
                "warm_cache_hit_ratio": (0.85, "ratio"),
                "tool_discovery_ms": (75.0, "ms"),
            }
        )
        report = RegressionDetector().compare(baseline, suite)
        assert report.max_severity == RegressionSeverity.NONE
        cold = report.regressions["cold_build_ms"]
        assert cold["status"] == "improved"
        assert cold["severity"] == "none"

    def test_ignore_list_skips_measurement(self) -> None:
        baseline = _make_baseline()
        suite = _make_overrides_suite(
            {
                "cold_build_ms": (660.0, "ms"),  # would be critical
                "warm_cache_hit_ratio": (0.85, "ratio"),
                "tool_discovery_ms": (75.0, "ms"),
            }
        )
        det = RegressionDetector(ignore=["cold_build_ms"])
        report = det.compare(baseline, suite)
        assert "cold_build_ms" not in report.regressions
        assert report.max_severity == RegressionSeverity.NONE

    def test_ignore_prefix_pattern(self) -> None:
        baseline = _make_baseline()
        suite = _make_overrides_suite(
            {
                "cold_build_ms": (660.0, "ms"),
                "warm_cache_hit_ratio": (0.85, "ratio"),
                "tool_discovery_ms": (75.0, "ms"),
            }
        )
        det = RegressionDetector(ignore=["cold_*"])
        report = det.compare(baseline, suite)
        assert "cold_build_ms" not in report.regressions

    def test_missing_measurement(self) -> None:
        baseline = _make_baseline()
        suite = _make_overrides_suite(
            {
                "cold_build_ms": (412.0, "ms"),
                "warm_cache_hit_ratio": (0.85, "ratio"),
                # tool_discovery_ms missing
            }
        )
        report = RegressionDetector().compare(baseline, suite)
        assert "tool_discovery_ms" in report.regressions
        assert report.regressions["tool_discovery_ms"]["status"] == "missing"

    def test_new_measurement_reported(self) -> None:
        baseline = _make_baseline()
        baseline.measurements.pop("tool_discovery_ms")  # only 2 in baseline
        suite = _make_suite()  # 3 measurements, tool_discovery_ms is "new"
        report = RegressionDetector().compare(baseline, suite)
        tool = report.regressions["tool_discovery_ms"]
        assert tool["status"] == "new"
        assert tool["current_value"] == 75.0

    def test_custom_thresholds(self) -> None:
        baseline = _make_baseline()
        suite = _make_overrides_suite(
            {
                "cold_build_ms": (450.0, "ms"),  # +9%
                "warm_cache_hit_ratio": (0.85, "ratio"),
                "tool_discovery_ms": (75.0, "ms"),
            }
        )
        # Tighter thresholds: 5/10/20 → +9% should be "warning".
        tight = RegressionDetector(thresholds={"warning": 5.0, "error": 10.0, "critical": 20.0})
        report = tight.compare(baseline, suite)
        assert report.max_severity == RegressionSeverity.WARNING

        # Looser thresholds: 20/40/60 → +9% should be "none".
        loose = RegressionDetector(thresholds={"warning": 20.0, "error": 40.0, "critical": 60.0})
        report2 = loose.compare(baseline, suite)
        assert report2.max_severity == RegressionSeverity.NONE

    def test_zero_baseline_no_crash(self) -> None:
        baseline = Baseline(
            suite_name="x",
            measurements={"foo_ms": {"value": 0.0, "unit": "ms", "samples": []}},
            recorded_at=0.0,
        )
        suite = BenchmarkSuite(
            suite_name="x",
            measurements=[BenchmarkMeasurement(name="foo_ms", value=10.0, unit="ms")],
            recorded_at=0.0,
        )
        # Should not raise / divide-by-zero.
        report = RegressionDetector().compare(baseline, suite)
        assert "foo_ms" in report.regressions

    def test_message_includes_summary(self) -> None:
        baseline = _make_baseline()
        suite = _make_suite()
        report = RegressionDetector().compare(baseline, suite)
        assert "[smoke]" in report.message
        assert "max=" in report.message

    def test_report_to_dict_serialisable(self) -> None:
        baseline = _make_baseline()
        suite = _make_suite()
        report = RegressionDetector().compare(baseline, suite)
        d = report.to_dict()
        # Round-trip via JSON to confirm everything is JSON-safe.
        json.dumps(d)

    def test_threshold_defaults_sane(self) -> None:
        assert DEFAULT_THRESHOLDS["warning"] < DEFAULT_THRESHOLDS["error"]
        assert DEFAULT_THRESHOLDS["error"] < DEFAULT_THRESHOLDS["critical"]
        assert "ms" in LOWER_IS_BETTER_UNITS
        assert "ratio" in HIGHER_IS_BETTER_UNITS