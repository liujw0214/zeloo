"""Tests for CostTracker.format_cost() and summary_zh()."""

from __future__ import annotations

from agent.cost_tracker import CostTracker


def test_format_cost_default_usd():
    """format_cost() without args returns a USD string."""
    tracker = CostTracker(model="gpt-4o-mini")
    tracker.record_usage({"prompt_tokens": 1000, "completion_tokens": 500})
    result = tracker.format_cost()
    assert result.startswith("$")
    assert "." in result


def test_format_cost_cny():
    """CNY format should include ¥ and scale by rate."""
    tracker = CostTracker(model="gpt-4o-mini")
    tracker.record_usage({"prompt_tokens": 1000, "completion_tokens": 500})
    result = tracker.format_cost(currency="CNY")
    assert "¥" in result


def test_format_cost_eur():
    """EUR format should include €."""
    tracker = CostTracker(model="gpt-4o-mini")
    tracker.record_usage({"prompt_tokens": 1000, "completion_tokens": 500})
    result = tracker.format_cost(currency="EUR")
    assert "€" in result


def test_format_cost_gbp():
    """GBP format should include £."""
    tracker = CostTracker(model="gpt-4o-mini")
    tracker.record_usage({"prompt_tokens": 1000, "completion_tokens": 500})
    result = tracker.format_cost(currency="GBP")
    assert "£" in result


def test_format_cost_jpy_no_decimals():
    """JPY format should be an integer (no decimal places)."""
    tracker = CostTracker(model="gpt-4o-mini")
    tracker.record_usage({"prompt_tokens": 1000, "completion_tokens": 500})
    result = tracker.format_cost(currency="JPY")
    assert "¥" in result
    assert "." not in result


def test_format_cost_unknown_currency_falls_back_to_usd():
    """Unknown currency codes fall back to USD."""
    tracker = CostTracker(model="gpt-4o-mini")
    tracker.record_usage({"prompt_tokens": 100, "completion_tokens": 50})
    result = tracker.format_cost(currency="XYZ")
    assert result.startswith("$")


def test_format_cost_locale_de():
    """locale arg should not raise; best-effort formatting."""
    tracker = CostTracker(model="gpt-4o-mini")
    tracker.record_usage({"prompt_tokens": 1000, "completion_tokens": 500})
    result = tracker.format_cost(currency="EUR", locale="de_DE.UTF-8")
    assert "€" in result


def test_summary_zh_contains_chinese():
    """summary_zh() should contain Chinese characters."""
    tracker = CostTracker(model="gpt-4o-mini")
    tracker.record_usage({"prompt_tokens": 1000, "completion_tokens": 500})
    result = tracker.summary_zh()
    assert "令牌" in result
    assert "费用" in result
    assert "¥" in result
    assert "输入" in result
    assert "输出" in result


def test_summary_zh_matches_english_logic():
    """Both summary() and summary_zh() describe the same underlying data."""
    tracker = CostTracker(model="gpt-4o-mini")
    tracker.record_usage({"prompt_tokens": 2000, "completion_tokens": 1000})
    en = tracker.summary()
    zh = tracker.summary_zh()
    assert "3,000" in en
    assert "3,000" in zh
    assert "2,000" in en and "1,000" in en
