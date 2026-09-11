"""Tests for zeloo_cli/observability."""

from __future__ import annotations

from pathlib import Path

from zeloo_cli.observability.health import (
    HealthStatus,
    check_all,
    check_api_keys,
    check_dependencies,
    check_python_version,
)


class TestHealthChecks:
    def test_python_version(self) -> None:
        result = check_python_version()
        assert result.status == HealthStatus.OK
        assert "Python" in result.message

    def test_dependencies(self) -> None:
        result = check_dependencies()
        assert result.status in (HealthStatus.OK, HealthStatus.ERROR)

    def test_api_keys(self) -> None:
        result = check_api_keys()
        assert result.status in (HealthStatus.OK, HealthStatus.WARNING)

    def test_check_all(self) -> None:
        results = check_all()
        assert len(results) >= 4
        for r in results:
            assert isinstance(r.status, HealthStatus)


class TestUsageTracker:
    def test_record_and_summary(self, tmp_path: Path) -> None:
        from zeloo_cli.observability.usage import UsageTracker

        tracker = UsageTracker(db_path=tmp_path / "usage.db")
        tracker.record("openai", "gpt-4o", input_tokens=1000, output_tokens=500)
        summary = tracker.get_summary("all")
        tracker.close()
        assert summary.total_calls == 1
        assert summary.total_input_tokens == 1000

    def test_summary_no_data(self, tmp_path: Path) -> None:
        from zeloo_cli.observability.usage import UsageTracker

        tracker = UsageTracker(db_path=tmp_path / "empty.db")
        summary = tracker.get_summary("all")
        tracker.close()
        assert summary.total_calls == 0
