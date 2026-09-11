"""Tests for token counting evaluation suite."""

from __future__ import annotations

import pytest

from evals.token_counting.counter import (
    TokenCounter,
    count_tokens,
    estimate_cost,
)
from evals.token_counting.dataset import load_eval_prompts


class TestCountTokens:
    def test_count_string(self) -> None:
        result = count_tokens("Hello, world!")
        assert isinstance(result, int)
        assert result > 0

    def test_count_messages(self) -> None:
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hi"},
        ]
        result = count_tokens(messages, model="gpt-4o")
        assert isinstance(result, int)
        assert result > 0

    def test_count_consistency(self) -> None:
        text = "The quick brown fox jumps over the lazy dog."
        r1 = count_tokens(text)
        r2 = count_tokens(text)
        assert r1 == r2


class TestEstimateCost:
    def test_known_model(self) -> None:
        cost = estimate_cost(1_000_000, 1_000_000, "gpt-4o")
        assert cost == 12.50

    def test_unknown_model_uses_default(self) -> None:
        cost = estimate_cost(1_000_000, 1_000_000, "unknown-model")
        assert cost == 20.00


class TestTokenCounter:
    def test_record_usage(self) -> None:
        counter = TokenCounter(model="gpt-4o")
        counter.record_usage(input_tokens=100, output_tokens=50)
        assert counter.total_input_tokens == 100
        assert counter.total_output_tokens == 50
        assert counter.total_tokens() == 150
        assert counter.call_count == 1

    def test_summary(self) -> None:
        counter = TokenCounter(model="gpt-4o")
        counter.record_usage(input_tokens=1_000_000, output_tokens=500_000)
        summary = counter.summary()
        assert summary["model"] == "gpt-4o"
        assert summary["total_input_tokens"] == 1_000_000
        assert summary["total_output_tokens"] == 500_000
        assert summary["estimated_cost_usd"] == pytest.approx(7.5, rel=0.01)

    def test_cached_tokens(self) -> None:
        counter = TokenCounter(model="gpt-4o")
        counter.record_usage(input_tokens=800, output_tokens=400, cached_tokens=200)
        assert counter.total_cached_tokens == 200


class TestEvalPrompts:
    def test_load_default(self) -> None:
        prompts = load_eval_prompts("default")
        assert len(prompts) == 4

    def test_load_short(self) -> None:
        prompts = load_eval_prompts("short")
        assert len(prompts) == 4

    def test_load_long_context(self) -> None:
        prompts = load_eval_prompts("long_context")
        assert len(prompts) == 1
        tokens = count_tokens(prompts[0]["content"])
        assert tokens > 5000

    def test_fallback_to_default(self) -> None:
        prompts = load_eval_prompts("nonexistent")
        assert prompts == load_eval_prompts("default")
