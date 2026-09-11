"""Context engine — orchestrates the full context lifecycle."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from agent.agent_runtime_helpers import MODEL_CONTEXT_WINDOWS
from agent.compression_facade import CompressionFacade, CompressionMode, CompressionResult
from agent.context_breakdown import breakdown_by_turns
from agent.context_compressor import Message
from agent.conversation_compression import ConversationCompressor

logger = logging.getLogger(__name__)


@dataclass
class ContextConfig:
    """Configuration for the context engine."""

    model: str = "gpt-4o"
    max_context_tokens: int = 128000
    compression_mode: str = "auto"
    preserve_recent_turns: int = 3
    compression_threshold: float = 0.75
    enable_semantic_split: bool = False
    chunk_turns: int = 10


class ContextEngine:
    """High-level context management engine.

    Orchestrates the complete context lifecycle:
    1. Token budget tracking
    2. Automatic compression triggering
    3. Message grouping and breakdown
    4. Provider-specific formatting
    """

    def __init__(
        self,
        config: ContextConfig | None = None,
        compressor: CompressionFacade | None = None,
    ):
        self.config = config or self._default_config()
        self.compressor = compressor or CompressionFacade()
        self._conversation = ConversationCompressor(
            min_recent_turns=self.config.preserve_recent_turns,
        )
        self._message_cache: list[dict[str, Any]] = []
        self._last_compression_stats: dict[str, Any] = {}

    def _default_config(self) -> ContextConfig:
        return ContextConfig(
            max_context_tokens=MODEL_CONTEXT_WINDOWS.get("gpt-4o", 128000)
        )

    def add_message(self, message: dict[str, Any]) -> None:
        """Add a message to the context and trigger compression if needed.

        Args:
            message: Chat API message dict.
        """
        self._message_cache.append(message)
        self._check_and_compress()

    def add_messages(self, messages: list[dict[str, Any]]) -> None:
        """Add multiple messages.

        Args:
            messages: List of chat API message dicts.
        """
        self._message_cache.extend(messages)
        self._check_and_compress()

    def get_messages(
        self,
        compressed: bool = True,
    ) -> list[dict[str, Any]]:
        """Get current message list.

        Args:
            compressed: If True, return compressed messages.
                       If False, return raw messages (after any pending compression).

        Returns:
            Message list ready for the model.
        """
        if not compressed:
            return list(self._message_cache)

        return self.compressor.compress(
            list(self._message_cache),
            mode=self.config.compression_mode,
            model=self.config.model,
        )

    def get_message_groups(
        self,
    ) -> list[list[dict[str, Any]]]:
        """Get messages split into groups for parallel processing.

        Returns:
            List of message groups.
        """
        msgs = self.get_messages(compressed=False)
        parsed = [Message.from_dict(m) for m in msgs]
        groups = breakdown_by_turns(parsed, chunk_turns=self.config.chunk_turns)
        return [[m.to_dict() if isinstance(m, Message) else m for m in g] for g in groups]

    def force_compress(self) -> CompressionResult:
        """Force immediate compression of the current context.

        Returns:
            CompressionResult with statistics.
        """
        original = list(self._message_cache)
        original_count = len(original)
        original_tokens = self._count_tokens(original)

        compressed = self.compressor.compress(
            original,
            mode=self.config.compression_mode,
            model=self.config.model,
            force=True,
        )
        compressed_count = len(compressed)
        compressed_tokens = self._count_tokens(compressed)

        self._message_cache = compressed

        result = CompressionResult(
            original_count=original_count,
            compressed_count=compressed_count,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            mode_used=self.config.compression_mode,
            reduction_ratio=(
                1.0 - compressed_tokens / original_tokens
                if original_tokens else 0.0
            ),
            messages=compressed,
        )
        self._last_compression_stats = {
            "ratio": result.reduction_ratio,
            "saved": original_tokens - compressed_tokens,
        }

        return result

    def get_token_budget(self) -> dict[str, int]:
        """Return current token budget status.

        Returns:
            Dict with budget info: total, used, remaining, utilization %.
        """
        budget = self.config.max_context_tokens
        used = self._count_tokens(self._message_cache)
        remaining = max(0, budget - used)
        utilization = round(used / budget, 4) if budget else 0.0

        return {
            "budget_total": budget,
            "budget_used": used,
            "budget_remaining": remaining,
            "utilization": utilization,
        }

    def clear(self) -> None:
        """Clear all cached messages."""
        self._message_cache.clear()
        self._last_compression_stats.clear()

    def get_stats(self) -> dict[str, Any]:
        """Return context engine statistics."""
        return {
            "message_count": len(self._message_cache),
            "compression_stats": self.compressor.get_stats(),
            "last_compression": self._last_compression_stats,
            "token_budget": self.get_token_budget(),
        }

    def set_model(self, model: str) -> None:
        """Update the model (adjusts budget accordingly)."""
        self.config.model = model
        self.config.max_context_tokens = MODEL_CONTEXT_WINDOWS.get(model, 128000)
        logger.info("Context engine model updated to %s", model)

    def set_compression_mode(self, mode: str) -> None:
        """Update the compression mode.

        Args:
            mode: One of "auto", "hybrid", "summarize", "prune", "truncate", "disabled"
        """
        self.config.compression_mode = mode
        self.compressor.default_mode = CompressionMode(mode)
        logger.info("Compression mode updated to %s", mode)

    def _check_and_compress(self) -> None:
        """Check if compression is needed and trigger if so."""
        budget = self.config.max_context_tokens
        used = self._count_tokens(self._message_cache)
        utilization = used / budget if budget else 0.0

        if utilization >= self.config.compression_threshold:
            self.force_compress()

    def _count_tokens(self, messages: list[dict[str, Any]]) -> int:
        """Estimate total tokens for messages."""
        from agent.agent_runtime_helpers import compute_token_estimate

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
