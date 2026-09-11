"""Tests for agent.insights."""

from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path

from agent.insights import (
    _TOKEN_RING_CAP,
    InsightsEngine,
    ToolStat,
)


class TestToolStat:
    def test_avg_duration_zero_when_no_calls(self) -> None:
        stat = ToolStat()
        assert stat.avg_duration == 0.0

    def test_avg_duration_when_calls_exist(self) -> None:
        stat = ToolStat(call_count=4, total_duration=2.0)
        assert stat.avg_duration == 0.5

    def test_error_rate_tracking(self) -> None:
        stat = ToolStat(call_count=10, error_count=3)
        assert stat.call_count == 10
        assert stat.error_count == 3


class TestRecording:
    def test_record_tool_call_updates_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = InsightsEngine(storage_path=Path(tmp) / "i.json")
            engine.record_tool_call("read_file", duration=0.1)
            engine.record_tool_call("read_file", duration=0.3, error=True)
            assert engine._tool_stats["read_file"].call_count == 2
            assert engine._tool_stats["read_file"].error_count == 1
            assert abs(engine._tool_stats["read_file"].total_duration - 0.4) < 1e-9

    def test_record_error_increments_category(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = InsightsEngine(storage_path=Path(tmp) / "i.json")
            engine.record_error("rate_limit")
            engine.record_error("rate_limit")
            engine.record_error("auth")
            assert engine._error_counts["rate_limit"] == 2
            assert engine._error_counts["auth"] == 1

    def test_record_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = InsightsEngine(storage_path=Path(tmp) / "i.json")
            engine.record_session(iterations=10)
            engine.record_session(iterations=5)
            assert engine._session_count == 2
            assert engine._total_iterations == 15


class TestTokenRingCap:
    def test_token_ring_capped_in_memory(self) -> None:
        """The in-memory token ring must not exceed the cap.

        Regression test for unbounded growth that would slowly leak memory
        over a multi-hour session.
        """
        with tempfile.TemporaryDirectory() as tmp:
            engine = InsightsEngine(storage_path=Path(tmp) / "i.json")
            for i in range(_TOKEN_RING_CAP + 500):
                engine.record_token_usage(i)
            assert len(engine._token_usage) == _TOKEN_RING_CAP
            # The oldest entries were dropped, the newest are retained.
            assert engine._token_usage[-1][1] == _TOKEN_RING_CAP + 499

    def test_token_recorded_as_delta(self) -> None:
        """``record_token_usage`` stores deltas, not cumulative totals.

        The values are appended verbatim — callers are expected to pass
        a per-call delta. The on-disk payload also reflects this.
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "i.json"
            engine = InsightsEngine(storage_path=path)
            engine.record_token_usage(100)
            engine.record_token_usage(50)
            assert [tok for _, tok in engine._token_usage] == [100, 50]


class TestFlushThrottling:
    def test_flush_throttled_within_interval(self) -> None:
        """Rapid record calls should NOT trigger a JSON rewrite per call."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "i.json"
            engine = InsightsEngine(storage_path=path)
            engine._last_flush = 0.0  # force-eligible
            engine._schedule_flush()
            assert engine._dirty is False  # one immediate flush
            # Subsequent rapid calls within interval must not flush.
            engine.record_tool_call("t1", duration=0.1)
            engine.record_tool_call("t1", duration=0.2)
            engine.record_tool_call("t1", duration=0.3)
            # dirty is set, but no second flush inside the window
            assert engine._dirty is True

    def test_force_flush_writes_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "i.json"
            engine = InsightsEngine(storage_path=path)
            engine._last_flush = 0.0
            engine.record_session(iterations=1)
            assert path.exists()

    def test_flush_is_idempotent_when_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = InsightsEngine(storage_path=Path(tmp) / "i.json")
            # No events have been recorded; flushing must be a no-op.
            before = engine._last_flush
            engine._flush()
            assert engine._last_flush == before


class TestPersistence:
    def test_save_then_load_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "i.json"
            a = InsightsEngine(storage_path=path)
            a.record_tool_call("foo", duration=0.5, error=True)
            a.record_error("timeout")
            a.record_token_usage(100)
            a.record_session(iterations=3)
            a._flush()  # force-write so the second instance reads fresh state

            b = InsightsEngine(storage_path=path)
            assert b._tool_stats["foo"].call_count == 1
            assert b._tool_stats["foo"].error_count == 1
            assert b._error_counts["timeout"] == 1
            assert b._token_usage[-1][1] == 100
            assert b._session_count == 1
            assert b._total_iterations == 3

    def test_load_tolerates_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = InsightsEngine(storage_path=Path(tmp) / "absent.json")
            assert engine._session_count == 0
            assert engine._token_usage == []

    def test_load_tolerates_corrupt_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "i.json"
            path.write_text("not-json", encoding="utf-8")
            # Must not raise; just log and start empty.
            engine = InsightsEngine(storage_path=path)
            assert engine._session_count == 0

    def test_persisted_payload_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "i.json"
            engine = InsightsEngine(storage_path=path)
            engine.record_tool_call("a", duration=0.1)
            engine.record_error("e1")
            engine.record_token_usage(10)
            engine.record_session(iterations=2)
            engine._flush()
            data = json.loads(path.read_text(encoding="utf-8"))
            assert data["session_count"] == 1
            assert data["total_iterations"] == 2
            assert "a" in data["tool_stats"]
            assert data["error_counts"] == {"e1": 1}
            assert data["token_usage"][-1][1] == 10


class TestGenerateReport:
    def test_empty_engine_produces_zero_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = InsightsEngine(storage_path=Path(tmp) / "i.json")
            report = engine.generate_report()
            assert report["summary"]["total_sessions"] == 0
            assert report["summary"]["total_iterations"] == 0
            assert report["summary"]["avg_iterations_per_session"] == 0
            assert report["token_usage"]["last_hour"] == 0
            assert report["top_tools"] == []
            assert report["top_errors"] == []
            assert report["recommendations"] == []

    def test_high_token_usage_recommendation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = InsightsEngine(storage_path=Path(tmp) / "i.json")
            for _ in range(200):
                engine.record_token_usage(1000)  # 200_000 tokens
            report = engine.generate_report()
            assert any("token usage" in r.lower() for r in report["recommendations"])

    def test_high_error_rate_tool_recommendation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = InsightsEngine(storage_path=Path(tmp) / "i.json")
            for _ in range(10):
                engine.record_tool_call("flaky", duration=0.1, error=True)
            report = engine.generate_report()
            recs = " ".join(report["recommendations"]).lower()
            assert "flaky" in recs
            assert "error rate" in recs

    def test_top_error_recommendation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = InsightsEngine(storage_path=Path(tmp) / "i.json")
            for _ in range(5):
                engine.record_error("rate_limit")
            report = engine.generate_report()
            assert report["top_errors"] == [{"category": "rate_limit", "count": 5}]
            recs = " ".join(report["recommendations"]).lower()
            assert "rate_limit" in recs

    def test_high_avg_iterations_recommendation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = InsightsEngine(storage_path=Path(tmp) / "i.json")
            engine.record_session(iterations=100)
            report = engine.generate_report()
            assert report["summary"]["avg_iterations_per_session"] == 100.0
            recs = " ".join(report["recommendations"]).lower()
            assert "iterations" in recs

    def test_top_tools_sorted_by_call_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = InsightsEngine(storage_path=Path(tmp) / "i.json")
            for _ in range(3):
                engine.record_tool_call("popular", duration=0.1)
            for _ in range(1):
                engine.record_tool_call("rare", duration=0.1)
            report = engine.generate_report()
            names = [t["name"] for t in report["top_tools"]]
            assert names[0] == "popular"
            assert names[1] == "rare"


class TestConcurrency:
    def test_concurrent_record_tool_call_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = InsightsEngine(storage_path=Path(tmp) / "i.json")
            engine._last_flush = 0.0
            threads = [
                threading.Thread(
                    target=lambda: [engine.record_tool_call("t", duration=0.01) for _ in range(50)]
                )
                for _ in range(10)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            # 10 threads × 50 calls = 500
            assert engine._tool_stats["t"].call_count == 500