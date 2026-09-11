"""Tests for agent.compression_facade."""

from __future__ import annotations

from agent.compression_facade import (
    CompressionFacade,
    CompressionMode,
    _mode_to_strategy_cached,
)
from agent.context_compressor import CompressionStrategy


class TestToolCallDetection:
    """The previous implementation falsely returned 0 tool calls because
    it checked ``content.startswith('invoke')``. The new implementation
    looks at the OpenAI/Anthropic ``tool_calls`` field on assistant
    messages and at role=='tool' message results."""

    def _mode_for_messages(self, msgs, model="gpt-4o"):
        facade = CompressionFacade()
        # gpt-4o budget is 128_000 tokens at 0.25 chars/token — we need
        # the budget ratio to be strictly > 0.75 (so we hit the
        # SUMMARIZE-vs-HYBRID branch), so use ~100k tokens = 400k chars.
        long_content = "x" * 400_000
        msgs = [{"role": "user", "content": long_content}, *msgs]
        return facade._resolve_mode(CompressionMode.AUTO, msgs, model)

    def test_no_tool_calls_returns_summarize(self) -> None:
        msgs = [{"role": "user", "content": "hi"}]
        assert self._mode_for_messages(msgs) == CompressionMode.SUMMARIZE

    def test_assistant_with_tool_calls_returns_hybrid(self) -> None:
        msgs = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "1", "type": "function", "function": {"name": "x"}}],
            }
        ]
        # 1/1 messages is 100% tool calls — well above the 30% threshold.
        assert self._mode_for_messages(msgs) == CompressionMode.HYBRID

    def test_tool_role_message_counts_as_tool_call(self) -> None:
        msgs = [
            {"role": "tool", "content": "result", "tool_call_id": "x"},
        ]
        assert self._mode_for_messages(msgs) == CompressionMode.HYBRID

    def test_legacy_invoke_tag_still_detected(self) -> None:
        """Older agents emit ``<invoke ...>...</invoke>`` XML — keep that
        code path alive so legacy sessions don't regress to SUMMARIZE."""
        msgs = [
            {"role": "assistant", "content": "<invoke name='x'/>"},
        ]
        assert self._mode_for_messages(msgs) == CompressionMode.HYBRID

    def test_empty_tool_calls_list_does_not_count(self) -> None:
        msgs = [
            {"role": "assistant", "content": "hi", "tool_calls": []},
        ]
        assert self._mode_for_messages(msgs) == CompressionMode.SUMMARIZE

    def test_non_string_content_does_not_crash(self) -> None:
        """An assistant message with a list-typed content (vision
        inputs, etc.) must not blow up the detector."""
        msgs = [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "looking at the image"},
                    {"type": "image", "image_url": "..."},
                ],
            }
        ]
        # Should not raise, should return SUMMARIZE (no tool_calls).
        assert self._mode_for_messages(msgs) == CompressionMode.SUMMARIZE


class TestModeMappingCache:
    def test_known_modes_map_correctly(self) -> None:
        # Reset cache to make sure we exercise the function body.
        _mode_to_strategy_cached.cache_clear()
        assert _mode_to_strategy_cached(CompressionMode.HYBRID) == CompressionStrategy.HYBRID
        assert _mode_to_strategy_cached(CompressionMode.SUMMARIZE) == CompressionStrategy.SUMMARIZE
        assert _mode_to_strategy_cached(CompressionMode.PRUNE) == CompressionStrategy.PRUNE
        assert _mode_to_strategy_cached(CompressionMode.TRUNCATE) == CompressionStrategy.TRUNCATE

    def test_unknown_mode_falls_back_to_hybrid(self) -> None:
        _mode_to_strategy_cached.cache_clear()
        assert _mode_to_strategy_cached(CompressionMode.AUTO) == CompressionStrategy.HYBRID

    def test_cache_returns_same_object(self) -> None:
        _mode_to_strategy_cached.cache_clear()
        a = _mode_to_strategy_cached(CompressionMode.HYBRID)
        b = _mode_to_strategy_cached(CompressionMode.HYBRID)
        # Enum members are singletons, so identity is preserved.
        assert a is b


class TestResolveModeOverride:
    def test_explicit_mode_bypasses_auto(self) -> None:
        facade = CompressionFacade()
        # Even with absurd messages, explicit HYBRID wins.
        msgs = [{"role": "user", "content": "x" * 1000000}]
        assert (
            facade._resolve_mode(CompressionMode.HYBRID, msgs, "gpt-4o")
            == CompressionMode.HYBRID
        )

    def test_disabled_returns_disabled(self) -> None:
        facade = CompressionFacade()
        msgs = [{"role": "user", "content": "tiny"}]
        assert (
            facade._resolve_mode(CompressionMode.AUTO, msgs, "gpt-4o")
            == CompressionMode.DISABLED
        )


class TestStrategyOverride:
    def test_set_strategy_bypasses_auto_resolution(self) -> None:
        facade = CompressionFacade()
        facade.set_strategy(CompressionStrategy.PRUNE)
        msgs = [{"role": "user", "content": "tiny"}]
        # Auto would return DISABLED but override forces PRUNE.
        result = facade._resolve_mode(CompressionMode.AUTO, msgs, "gpt-4o")
        assert result == CompressionMode.PRUNE

    def test_reset_strategy_clears_override(self) -> None:
        facade = CompressionFacade()
        facade.set_strategy(CompressionStrategy.PRUNE)
        facade.reset_strategy()
        msgs = [{"role": "user", "content": "tiny"}]
        assert (
            facade._resolve_mode(CompressionMode.AUTO, msgs, "gpt-4o")
            == CompressionMode.DISABLED
        )


class TestCompressStats:
    def test_total_compressions_increments(self) -> None:
        facade = CompressionFacade()
        before = facade.get_stats()["total_compressions"]
        # Force compression with an explicit mode so it doesn't bail
        # out of the budget check (the small input wouldn't otherwise
        # qualify).
        facade.compress(
            [{"role": "user", "content": "x" * 100}],
            model="gpt-4o",
            mode=CompressionMode.SUMMARIZE,
            force=True,
        )
        after = facade.get_stats()["total_compressions"]
        assert after == before + 1

    def test_short_messages_dont_increment(self) -> None:
        """When below the 70% threshold the facade short-circuits and
        returns messages unchanged without bumping stats — this is
        the expected behaviour, not a bug."""
        facade = CompressionFacade()
        before = facade.get_stats()["total_compressions"]
        facade.compress(
            [{"role": "user", "content": "tiny"}],
            model="gpt-4o",
        )
        after = facade.get_stats()["total_compressions"]
        assert after == before  # No bump — short-circuited.

    def test_empty_messages_returns_empty(self) -> None:
        facade = CompressionFacade()
        assert facade.compress([], model="gpt-4o") == []

    def test_disabled_returns_messages_unchanged(self) -> None:
        facade = CompressionFacade()
        msgs = [{"role": "user", "content": "hi"}]
        result = facade.compress(msgs, mode=CompressionMode.DISABLED)
        assert result == msgs