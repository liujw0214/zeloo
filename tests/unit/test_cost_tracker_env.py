"""Tests that CostTracker honours environment-variable threshold overrides.

Env vars:
    zeloo_COST_WARN_THRESHOLD  (USD, float, default 10.0)
    zeloo_COST_ABORT_THRESHOLD (USD, float, default 100.0)
"""
from __future__ import annotations

import pytest

from agent.cost_tracker import CostLimitExceeded, CostTracker


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Make sure no leftover env vars leak into tests."""
    monkeypatch.delenv("zeloo_COST_WARN_THRESHOLD", raising=False)
    monkeypatch.delenv("zeloo_COST_ABORT_THRESHOLD", raising=False)


def test_defaults_when_env_missing(monkeypatch):
    """Without env vars, thresholds should keep their dataclass defaults."""
    monkeypatch.delenv("zeloo_COST_WARN_THRESHOLD", raising=False)
    monkeypatch.delenv("zeloo_COST_ABORT_THRESHOLD", raising=False)
    tracker = CostTracker()
    assert tracker.warn_threshold_usd == 10.0
    assert tracker.abort_threshold_usd == 100.0


def test_env_warn_threshold_overrides(monkeypatch):
    """zeloo_COST_WARN_THRESHOLD should override the default."""
    monkeypatch.setenv("zeloo_COST_WARN_THRESHOLD", "1.5")
    tracker = CostTracker()
    assert tracker.warn_threshold_usd == 1.5
    assert tracker.abort_threshold_usd == 100.0


def test_env_abort_threshold_overrides(monkeypatch):
    """zeloo_COST_ABORT_THRESHOLD should override the default."""
    monkeypatch.setenv("zeloo_COST_ABORT_THRESHOLD", "42.5")
    tracker = CostTracker()
    assert tracker.abort_threshold_usd == 42.5


def test_both_env_vars_overrides(monkeypatch):
    """Both env vars should be honoured simultaneously."""
    monkeypatch.setenv("zeloo_COST_WARN_THRESHOLD", "2.0")
    monkeypatch.setenv("zeloo_COST_ABORT_THRESHOLD", "20.0")
    tracker = CostTracker()
    assert tracker.warn_threshold_usd == 2.0
    assert tracker.abort_threshold_usd == 20.0


def test_invalid_env_value_keeps_default(monkeypatch):
    """A non-numeric env value should fall back to default without raising."""
    monkeypatch.setenv("zeloo_COST_WARN_THRESHOLD", "not-a-number")
    tracker = CostTracker()
    assert tracker.warn_threshold_usd == 10.0


def test_invalid_abort_env_value_keeps_default(monkeypatch):
    """Invalid abort threshold keeps the default."""
    monkeypatch.setenv("zeloo_COST_ABORT_THRESHOLD", "")
    tracker = CostTracker()
    assert tracker.abort_threshold_usd == 100.0


def test_warn_threshold_actually_triggers(monkeypatch):
    """Threshold configured via env should fire when cost exceeds it."""
    monkeypatch.setenv("zeloo_COST_WARN_THRESHOLD", "0.001")
    tracker = CostTracker(model="gpt-4o")
    warn_fired: list[float] = []
    tracker.register_warn_callback(lambda level, cost: warn_fired.append(cost))
    # Record usage that exceeds the warn threshold
    tracker.record_usage({"prompt_tokens": 10_000, "completion_tokens": 0})
    assert warn_fired, "warn callback should have fired"


def test_abort_threshold_actually_raises(monkeypatch):
    """Threshold configured via env should raise CostLimitExceeded when exceeded."""
    monkeypatch.setenv("zeloo_COST_ABORT_THRESHOLD", "0.001")
    tracker = CostTracker(model="gpt-4o")
    with pytest.raises(CostLimitExceeded):
        tracker.record_usage({"prompt_tokens": 10_000, "completion_tokens": 0})


def test_snapshot_includes_env_thresholds(monkeypatch):
    """snapshot() should reflect the env-derived thresholds."""
    monkeypatch.setenv("zeloo_COST_WARN_THRESHOLD", "3.0")
    monkeypatch.setenv("zeloo_COST_ABORT_THRESHOLD", "30.0")
    tracker = CostTracker()
    snap = tracker.snapshot()
    assert snap["warn_threshold"] == 3.0
    assert snap["abort_threshold"] == 30.0


def test_invalid_abort_below_warn_logs_warning(monkeypatch, caplog):
    """If abort < warn, the constructor should emit a warning."""
    import logging

    monkeypatch.setenv("zeloo_COST_WARN_THRESHOLD", "5.0")
    monkeypatch.setenv("zeloo_COST_ABORT_THRESHOLD", "1.0")
    with caplog.at_level(logging.WARNING, logger="agent.cost_tracker"):
        CostTracker()
    assert any("abort threshold" in r.message.lower() for r in caplog.records)