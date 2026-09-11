"""Tests for agent.agent_analytics."""

from __future__ import annotations

import time

from agent.agent_analytics import AgentAnalytics, AgentMetrics


class TestRecordTurn:
    def test_record_turn_appends_event(self) -> None:
        a = AgentAnalytics()
        a.record_turn(session_id="s1", turn_id=1, tool_calls=["a", "b"], tokens_used=10)
        m = a.get_metrics()
        assert m.total_turns == 1
        assert m.total_tool_calls == 2

    def test_default_metrics_are_zero(self) -> None:
        a = AgentAnalytics()
        m = a.get_metrics()
        assert isinstance(m, AgentMetrics)
        assert m.total_sessions == 0
        assert m.total_turns == 0
        assert m.successful_tool_calls == 0
        assert m.failed_tool_calls == 0
        assert m.avg_response_time_ms == 0.0
        assert m.avg_tokens_per_turn == 0.0
        assert m.avg_turns_per_session == 0.0

    def test_multiple_turns_accumulate(self) -> None:
        a = AgentAnalytics()
        for i in range(5):
            a.record_turn(session_id="s", turn_id=i)
        m = a.get_metrics()
        assert m.total_turns == 5


class TestTimeWindow:
    def test_since_filters_out_old_events(self) -> None:
        a = AgentAnalytics()
        a.record_turn(session_id="old", turn_id=0)
        # Use a far-future timestamp so the recorded event is excluded.
        m = a.get_metrics(since=time.time() + 100)
        assert m.total_turns == 0

    def test_until_zero_is_honored_as_zero(self) -> None:
        """``until=0`` must be respected as an explicit upper bound, not
        silently replaced by ``time.time()``.

        Regression-tests the previous ``until or time.time()`` bug where
        a literal ``0`` was treated as falsy and meant "no upper bound",
        which was inconsistent with the ``since=0.0`` sentinel. A user
        who explicitly passes ``0`` wants events with ``timestamp <= 0``
        which is empty by construction.
        """
        a = AgentAnalytics()
        a.record_turn(session_id="s", turn_id=1)
        m = a.get_metrics(since=0.0, until=0)
        assert m.total_turns == 0

    def test_window_matches_filtered_events(self) -> None:
        """Averages must reflect the *filtered* set, not the full list."""
        a = AgentAnalytics()
        a.record_turn(
            session_id="s", turn_id=1, response_time_ms=100, tokens_used=50
        )
        a.record_turn(
            session_id="s", turn_id=2, response_time_ms=200, tokens_used=70
        )
        a.record_turn(
            session_id="s", turn_id=3, response_time_ms=300, tokens_used=80
        )
        m = a.get_metrics()
        assert m.avg_response_time_ms == 200.0  # (100+200+300)/3
        assert m.avg_tokens_per_turn == 200 / 3  # (50+70+80)/3 = 66.66...


class TestSessionCounting:
    def test_unique_session_count(self) -> None:
        a = AgentAnalytics()
        a.record_turn(session_id="alpha", turn_id=1)
        a.record_turn(session_id="alpha", turn_id=2)
        a.record_turn(session_id="beta", turn_id=1)
        m = a.get_metrics()
        assert m.total_sessions == 2
        assert m.total_turns == 3

    def test_avg_turns_per_session(self) -> None:
        a = AgentAnalytics()
        for i in range(4):
            a.record_turn(session_id="s", turn_id=i)
        m = a.get_metrics()
        assert m.avg_turns_per_session == 4.0

    def test_avg_turns_per_session_multiple_sessions(self) -> None:
        a = AgentAnalytics()
        # 3 turns over 2 sessions -> 1.5
        a.record_turn(session_id="a", turn_id=1)
        a.record_turn(session_id="a", turn_id=2)
        a.record_turn(session_id="b", turn_id=1)
        m = a.get_metrics()
        assert m.avg_turns_per_session == 1.5


class TestSuccessFailure:
    def test_successful_and_failed_counted_separately(self) -> None:
        a = AgentAnalytics()
        a.record_turn(session_id="s", turn_id=1, success=True)
        a.record_turn(session_id="s", turn_id=2, success=False, error="boom")
        a.record_turn(session_id="s", turn_id=3, success=False, error="boom")
        m = a.get_metrics()
        assert m.successful_tool_calls == 1
        assert m.failed_tool_calls == 2

    def test_error_distribution_truncates_long_messages(self) -> None:
        a = AgentAnalytics()
        long_error = "x" * 200
        a.record_turn(
            session_id="s", turn_id=1, success=False, error=long_error
        )
        m = a.get_metrics()
        # 50-char key
        keys = list(m.error_distribution.keys())
        assert len(keys) == 1
        assert len(keys[0]) == 50


class TestToolUsage:
    def test_tool_usage_distribution(self) -> None:
        a = AgentAnalytics()
        a.record_turn(session_id="s", turn_id=1, tool_calls=["t1", "t2"])
        a.record_turn(session_id="s", turn_id=2, tool_calls=["t1"])
        m = a.get_metrics()
        assert m.tool_usage_distribution == {"t1": 2, "t2": 1}

    def test_tool_rankings_top_n(self) -> None:
        a = AgentAnalytics()
        for _ in range(5):
            a.record_turn(session_id="s", turn_id=1, tool_calls=["popular"])
        for _ in range(2):
            a.record_turn(session_id="s", turn_id=1, tool_calls=["rare"])
        top = a.get_tool_rankings(top_n=1)
        assert top == [("popular", 5)]


class TestCost:
    def test_total_cost_accumulates(self) -> None:
        a = AgentAnalytics()
        a.record_turn(session_id="s", turn_id=1, cost_usd=0.01)
        a.record_turn(session_id="s", turn_id=2, cost_usd=0.005)
        m = a.get_metrics()
        assert abs(m.total_cost_usd - 0.015) < 1e-9


class TestErrorRate:
    def test_empty_returns_zero(self) -> None:
        a = AgentAnalytics()
        assert a.get_error_rate() == 0.0

    def test_all_success(self) -> None:
        a = AgentAnalytics()
        a.record_turn(session_id="s", turn_id=1, success=True)
        a.record_turn(session_id="s", turn_id=2, success=True)
        assert a.get_error_rate() == 0.0

    def test_mixed(self) -> None:
        a = AgentAnalytics()
        a.record_turn(session_id="s", turn_id=1, success=True)
        a.record_turn(session_id="s", turn_id=2, success=False)
        a.record_turn(session_id="s", turn_id=3, success=True)
        a.record_turn(session_id="s", turn_id=4, success=False)
        assert abs(a.get_error_rate() - 0.5) < 1e-9


class TestReset:
    def test_reset_clears_events(self) -> None:
        a = AgentAnalytics()
        a.record_turn(session_id="s", turn_id=1)
        a.record_turn(session_id="s", turn_id=2)
        assert a.get_metrics().total_turns == 2
        a.reset()
        assert a.get_metrics().total_turns == 0
        assert a.get_metrics().total_sessions == 0