"""Compression facade — unified compression entry point.

Wraps ContextCompressor and ConversationCompressor with automatic
strategy selection based on conversation characteristics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Any

from agent.agent_runtime_helpers import compute_token_estimate
from agent.context_compressor import CompressionStrategy, ContextCompressor, Message
from agent.conversation_compression import ConversationCompressor

logger = logging.getLogger(__name__)

# Cache the ``CompressionMode -> CompressionStrategy`` mapping. The
# Enum members are hashable, the function is pure, and the mapping
# is consulted on every ``compress()`` call.
@lru_cache(maxsize=16)
def _mode_to_strategy_cached(mode: CompressionMode) -> CompressionStrategy:
    mapping = {
        CompressionMode.HYBRID: CompressionStrategy.HYBRID,
        CompressionMode.SUMMARIZE: CompressionStrategy.SUMMARIZE,
        CompressionMode.PRUNE: CompressionStrategy.PRUNE,
        CompressionMode.TRUNCATE: CompressionStrategy.TRUNCATE,
    }
    return mapping.get(mode, CompressionStrategy.HYBRID)


class CompressionMode(str, Enum):  # noqa: UP042
    """Compression mode selector."""

    AUTO = "auto"
    HYBRID = "hybrid"
    SUMMARIZE = "summarize"
    PRUNE = "prune"
    TRUNCATE = "truncate"
    DISABLED = "disabled"


@dataclass
class CompressionResult:
    """Result of a compression operation."""

    original_count: int
    compressed_count: int
    original_tokens: int
    compressed_tokens: int
    mode_used: str
    reduction_ratio: float
    messages: list[dict[str, Any]]


class CompressionFacade:
    """Unified compression facade.

    Provides a single entry point for context compression with:
    - Automatic strategy selection based on conversation state
    - Token budget management across multiple providers
    - Compression statistics tracking
    - Strategy override capability
    """

    def __init__(
        self,
        context_compressor: ContextCompressor | None = None,
        conversation_compressor: ConversationCompressor | None = None,
        default_mode: CompressionMode = CompressionMode.AUTO,
    ):
        self.context_compressor = context_compressor or ContextCompressor()
        self.conversation_compressor = conversation_compressor or ConversationCompressor()
        self.default_mode = default_mode
        self._override_strategy: CompressionStrategy | None = None
        self._stats: dict[str, int] = {
            "total_compressions": 0,
            "total_tokens_saved": 0,
        }

    def compress(
        self,
        messages: list[dict[str, Any]],
        mode: CompressionMode | str = CompressionMode.AUTO,
        model: str = "gpt-4o",
        force: bool = False,
    ) -> list[dict[str, Any]]:
        """Compress messages using automatic or specified strategy.

        Args:
            messages: Chat API message list.
            mode: Compression mode ("auto" picks the best strategy).
            model: Model name for context window sizing.
            force: Force compression even if under budget.

        Returns:
            Compressed message list.
        """
        if not messages:
            return []

        mode = CompressionMode(mode)
        if mode == CompressionMode.DISABLED:
            return list(messages)

        effective_mode = self._resolve_mode(mode, messages, model)

        parsed = [Message.from_dict(m) for m in messages]
        original_tokens = self._count_tokens(parsed)

        if not force and original_tokens < self._budget_for_model(model) * 0.7:
            return messages

        strategy = self._mode_to_strategy(effective_mode)
        compressed = self.conversation_compressor.compress_for_model(
            messages,
            model=model,
            strategy=strategy.value,
        )

        compressed_tokens = self._count_tokens_dict(compressed)
        saved = original_tokens - compressed_tokens

        self._stats["total_compressions"] += 1
        self._stats["total_tokens_saved"] += max(0, saved)

        logger.info(
            "Compressed %d msgs (%d→%d tokens, saved %d, mode=%s)",
            len(messages),
            original_tokens,
            compressed_tokens,
            saved,
            effective_mode.value,
        )

        return compressed

    def compress_from_objects(
        self,
        messages: list[Message],
        mode: CompressionMode | str = CompressionMode.AUTO,
    ) -> list[Message]:
        """Compress Message objects directly."""
        mode = CompressionMode(mode)
        if mode == CompressionMode.DISABLED:
            return list(messages)

        effective_mode = self._resolve_mode(
            mode,
            [{"role": m.role, "content": m.content} for m in messages],
            "gpt-4o",
        )
        strategy = self._mode_to_strategy(effective_mode)
        return self.context_compressor.compress(messages, strategy=strategy)

    def set_strategy(self, strategy: CompressionStrategy) -> None:
        """Manually override the compression strategy.

        Args:
            strategy: CompressionStrategy to use for all compressions.
        """
        self._override_strategy = strategy
        logger.info("Compression strategy overridden to: %s", strategy.value)

    def reset_strategy(self) -> None:
        """Reset to automatic strategy selection."""
        self._override_strategy = None
        logger.info("Compression strategy reset to auto")

    def estimate_savings(
        self,
        messages: list[dict[str, Any] | Message],
    ) -> float:
        """Estimate compression savings ratio without actually compressing.

        Args:
            messages: Message list to evaluate.

        Returns:
            Estimated reduction ratio (0.0 to 1.0).
        """
        if not messages:
            return 0.0

        parsed = [m.to_dict() if isinstance(m, Message) else m for m in messages]
        current_tokens = self._count_tokens_dict(parsed)

        compressed = self.conversation_compressor.compress_for_model(
            parsed,
            model="gpt-4o",
            strategy="hybrid",
        )
        compressed_tokens = self._count_tokens_dict(compressed)

        if current_tokens == 0:
            return 0.0
        return max(0.0, min(1.0, 1.0 - compressed_tokens / current_tokens))

    def get_stats(self) -> dict[str, Any]:
        """Return compression statistics."""
        return dict(self._stats)

    def _resolve_mode(
        self,
        mode: CompressionMode,
        messages: list[dict[str, Any]],
        model: str,
    ) -> CompressionMode:
        """Automatically select the best compression mode."""
        if mode != CompressionMode.AUTO:
            return mode

        if self._override_strategy:
            return self._strategy_to_mode(self._override_strategy)

        token_count = self._count_tokens_dict(messages)
        budget = self._budget_for_model(model)
        ratio = token_count / budget if budget else 1.0

        msg_count = len(messages)
        # Tool-call detection.
        #
        # The previous implementation checked ``m.get("content", "").startswith("invoke")``
        # which is wrong on both axes:
        # * role == "tool"  — content is the tool *result*, not a tool call,
        #   and rarely starts with the literal string "invoke"
        # * role == "assistant" — content is the model's natural-language reply
        #
        # The correct signal is: ``assistant`` messages carry a non-empty
        # ``tool_calls`` list (OpenAI / Anthropic chat API). We also fall
        # back to a substring scan for the older ``<invoke>`` XML tag, in
        # case the agent emits tool calls in legacy format.
        tool_call_count = 0
        for m in messages:
            role = m.get("role")
            if role == "assistant":
                tc = m.get("tool_calls")
                if tc and isinstance(tc, list) and len(tc) > 0:
                    tool_call_count += 1
                else:
                    content = m.get("content", "")
                    if isinstance(content, str) and "<invoke" in content:
                        tool_call_count += 1
            elif role == "tool":
                # tool role messages always represent a completed tool
                # invocation — they count as tool-call evidence too.
                tool_call_count += 1

        if ratio > 0.9:
            return CompressionMode.TRUNCATE
        elif ratio > 0.75:
            if tool_call_count > msg_count * 0.3:
                return CompressionMode.HYBRID
            return CompressionMode.SUMMARIZE
        elif ratio > 0.5:
            if tool_call_count > 5:
                return CompressionMode.HYBRID
            return CompressionMode.PRUNE
        else:
            return CompressionMode.DISABLED

    def _mode_to_strategy(self, mode: CompressionMode) -> CompressionStrategy:
        """Map CompressionMode to CompressionStrategy (cached)."""
        return _mode_to_strategy_cached(mode)

    def _strategy_to_mode(self, strategy: CompressionStrategy) -> CompressionMode:
        """Map CompressionStrategy to CompressionMode."""
        mapping = {
            CompressionStrategy.HYBRID: CompressionMode.HYBRID,
            CompressionStrategy.SUMMARIZE: CompressionMode.SUMMARIZE,
            CompressionStrategy.PRUNE: CompressionMode.PRUNE,
            CompressionStrategy.TRUNCATE: CompressionMode.TRUNCATE,
        }
        return mapping.get(strategy, CompressionMode.HYBRID)

    def _budget_for_model(self, model: str) -> int:
        """Get the effective context budget for a model."""
        from agent.agent_runtime_helpers import MODEL_CONTEXT_WINDOWS

        return MODEL_CONTEXT_WINDOWS.get(model, 128000)

    def _count_tokens(self, messages: list[Message]) -> int:
        """Count tokens for Message objects."""
        return sum(
            m.token_count if m.token_count else compute_token_estimate(m.content)
            for m in messages
        )

    def _count_tokens_dict(self, messages: list[dict[str, Any]]) -> int:
        """Count tokens for dict messages."""
        total = 0
        for m in messages:
            content = m.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    c.get("text", "") if isinstance(c, dict) else str(c)
                    for c in content
                )
            total += compute_token_estimate(content)
        return total
