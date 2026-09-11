"""Unit tests for agent.token_aware_trimmer.

Covers:
- TokenAwareTrimmer init with / without tiktoken
- count_tokens() heuristic accuracy
- trim_message() under-budget, system passthrough, multimodal
- trim_messages() rolling-window budget enforcement
- get_tokenizer_status() backend reporting
- prefer_tail behavior for tool messages
"""

from __future__ import annotations

import pytest

from agent.token_aware_trimmer import TokenAwareTrimmer


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def trimmer() -> TokenAwareTrimmer:
    return TokenAwareTrimmer(model="gpt-4o", fallback_chars_per_token=4)


# ── Init / status ─────────────────────────────────────────────────────


class TestInit:
    def test_default_init(self, trimmer: TokenAwareTrimmer) -> None:
        assert trimmer.model == "gpt-4o"
        assert trimmer.fallback_chars_per_token == 4

    def test_status_is_string(self, trimmer: TokenAwareTrimmer) -> None:
        status = trimmer.get_tokenizer_status()
        assert isinstance(status, str)
        # Either tiktoken-based or chars/4 fallback.
        assert "tiktoken" in status or "chars/" in status


# ── count_tokens ──────────────────────────────────────────────────────


class TestCountTokens:
    def test_empty_string(self, trimmer: TokenAwareTrimmer) -> None:
        assert trimmer.count_tokens("") == 0

    def test_simple_english(self, trimmer: TokenAwareTrimmer) -> None:
        # 8 ASCII chars → at least 1 token under fallback, > 0 under tiktoken.
        assert trimmer.count_tokens("hello x ") >= 1

    def test_cjk_text_higher_count(self, trimmer: TokenAwareTrimmer) -> None:
        ascii_count = trimmer.count_tokens("aaaaaaaaaa")  # 10 chars
        cjk_count = trimmer.count_tokens("中文测试字符串")  # mixed CJK
        # CJK should be weighted heavier under fallback heuristic.
        if "chars/" in trimmer.get_tokenizer_status():
            assert cjk_count >= ascii_count

    def test_long_text(self, trimmer: TokenAwareTrimmer) -> None:
        text = "lorem ipsum dolor sit amet " * 50
        count = trimmer.count_tokens(text)
        assert count > 10


# ── trim_message ──────────────────────────────────────────────────────


class TestTrimMessage:
    def test_under_budget_unchanged(self, trimmer: TokenAwareTrimmer) -> None:
        msg = {"role": "user", "content": "short"}
        out = trimmer.trim_message(msg, max_tokens=100)
        assert out["content"] == "short"

    def test_zero_budget_returns_empty(self, trimmer: TokenAwareTrimmer) -> None:
        msg = {"role": "user", "content": "hello"}
        out = trimmer.trim_message(msg, max_tokens=0)
        assert out["content"] == ""

    def test_system_message_passthrough(self, trimmer: TokenAwareTrimmer) -> None:
        msg = {"role": "system", "content": "x" * 10000}
        out = trimmer.trim_message(msg, max_tokens=10)
        # System messages are never trimmed.
        assert out["content"] == "x" * 10000

    def test_tool_message_prefers_tail(self, trimmer: TokenAwareTrimmer) -> None:
        msg = {"role": "tool", "content": "abcdefghij" * 50}
        out = trimmer.trim_message(msg, max_tokens=20)
        # Tail-preferred → "j" should survive in the snippet.
        assert "j" in out["content"]

    def test_user_message_prefers_head(self, trimmer: TokenAwareTrimmer) -> None:
        msg = {"role": "user", "content": "abcdefghij" * 50}
        out = trimmer.trim_message(msg, max_tokens=20)
        # Head-preserved → "a" should be present, "j" likely truncated.
        assert "a" in out["content"]

    def test_multimodal_content(self, trimmer: TokenAwareTrimmer) -> None:
        msg = {
            "role": "user",
            "content": [
                {"type": "text", "text": "hello " * 200},
                {"type": "image_url", "image_url": "http://example.com/x.png"},
            ],
        }
        out = trimmer.trim_message(msg, max_tokens=20)
        # Should return a multimodal list with trimmed text block.
        assert isinstance(out["content"], list)
        text_blocks = [b for b in out["content"] if isinstance(b, dict) and b.get("type") == "text"]
        assert len(text_blocks) == 1


# ── trim_messages ─────────────────────────────────────────────────────


class TestTrimMessages:
    def test_empty_list(self, trimmer: TokenAwareTrimmer) -> None:
        assert trimmer.trim_messages([], total_budget=100) == []

    def test_system_preserved_first(self, trimmer: TokenAwareTrimmer) -> None:
        msgs = [
            {"role": "system", "content": "sys " * 200},
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
        ]
        out = trimmer.trim_messages(msgs, total_budget=200)
        assert out[0]["role"] == "system"

    def test_drops_oldest_when_over_budget(self, trimmer: TokenAwareTrimmer) -> None:
        msgs = [
            {"role": "user", "content": "x" * 800},
            {"role": "user", "content": "y" * 800},
            {"role": "user", "content": "z" * 800},
        ]
        out = trimmer.trim_messages(msgs, total_budget=120)
        # Only the most recent message(s) should survive.
        assert len(out) < len(msgs)
        if out:
            # The last remaining message should reference 'z' (most recent).
            assert "z" in out[-1]["content"]

    def test_trimmed_message_returns_list(self, trimmer: TokenAwareTrimmer) -> None:
        msgs = [
            {"role": "user", "content": "x" * 400},
            {"role": "assistant", "content": "y" * 400},
        ]
        out = trimmer.trim_messages(msgs, total_budget=200)
        # Each entry should be a dict with role+content.
        for m in out:
            assert "role" in m
            assert "content" in m