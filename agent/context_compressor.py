"""Context compression — algorithm core for managing long conversations."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class CompressionStrategy(str, Enum):  # noqa: UP042
    """Available compression strategies."""

    HYBRID = "hybrid"
    SUMMARIZE = "summarize"
    PRUNE = "prune"
    TRUNCATE = "truncate"


@dataclass
class Message:
    """Simplified message representation for compression."""

    role: str
    content: str
    token_count: int = 0
    importance_score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to chat API message format."""
        return {"role": self.role, "content": self.content}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        """Create from chat API message dict."""
        content = data.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                c.get("text", "") if isinstance(c, dict) else str(c)
                for c in content
            )
        return cls(
            role=data.get("role", "user"),
            content=content,
            token_count=data.get("token_count", 0),
            importance_score=data.get("importance_score", 0.0),
            metadata=data.get("metadata", {}),
        )


class ContextCompressor:
    """Context compression engine.

    Handles token budget management, message importance scoring,
    deduplication, and hybrid compression strategies.
    """

    def __init__(
        self,
        max_tokens: int = 128000,
        reserved_tokens: int = 4096,
        llm_summarizer: Any | None = None,
    ):
        self.max_tokens = max_tokens
        self.reserved_tokens = reserved_tokens
        self.llm_summarizer = llm_summarizer

    def compress(
        self,
        messages: list[Message],
        strategy: CompressionStrategy = CompressionStrategy.HYBRID,
    ) -> list[Message]:
        """Compress a message list using the specified strategy.

        Args:
            messages: List of Message objects to compress.
            strategy: Which compression strategy to apply.

        Returns:
            Compressed message list.
        """
        if not messages:
            return []

        working = list(messages)
        budget = self.max_tokens - self.reserved_tokens

        if self._total_tokens(working) <= budget:
            return working

        if strategy == CompressionStrategy.TRUNCATE:
            return self._truncate(working, budget)
        elif strategy == CompressionStrategy.PRUNE:
            return self._prune(working, budget)
        elif strategy == CompressionStrategy.SUMMARIZE:
            return self._summarize(working, budget)
        else:
            return self._hybrid_compress(working, budget)

    def compress_from_dicts(
        self,
        messages: list[dict[str, Any]],
        strategy: CompressionStrategy = CompressionStrategy.HYBRID,
    ) -> list[dict[str, Any]]:
        """Compress messages provided as dicts (chat API format).

        Args:
            messages: List of message dicts from chat API.
            strategy: Compression strategy.

        Returns:
            List of compressed message dicts.
        """
        parsed = [Message.from_dict(m) for m in messages]
        compressed = self.compress(parsed, strategy)
        return [m.to_dict() for m in compressed]

    def summarize_messages(
        self,
        messages: list[Message],
        target_tokens: int,
    ) -> list[Message]:
        """Summarize a message list to fit within target token budget.

        If an LLM summarizer is configured, uses it for semantic summarization.
        Otherwise falls back to simple extraction of key content.

        Args:
            messages: Messages to summarize.
            target_tokens: Target token count for the output.

        Returns:
            Summarized message list.
        """
        if not messages:
            return []

        total = self._total_tokens(messages)
        if total <= target_tokens:
            return messages

        if self.llm_summarizer is not None:
            return self._llm_summarize(messages, target_tokens)

        return self._simple_summarize(messages, target_tokens)

    def deduplicate_tool_calls(
        self,
        messages: list[Message],
    ) -> list[Message]:
        """Remove duplicate and near-duplicate tool calls.

        Tool calls are considered duplicates if they have the same name
        and similar arguments within the last N messages.

        Args:
            messages: Input message list.

        Returns:
            Deduplicated message list.
        """
        if not messages:
            return []

        seen: dict[str, list[tuple[int, Message]]] = {}
        result: list[Message] = []

        for i, msg in enumerate(messages):
            if msg.role != "tool" and msg.role != "assistant":
                result.append(msg)
                continue

            key = self._tool_call_key(msg)
            if key:
                if key not in seen:
                    seen[key] = []
                seen[key].append((i, msg))

                window = seen[key][-5:]
                if len(window) <= 1:
                    result.append(msg)
                else:
                    prev = window[-2][1]
                    if self._is_duplicate(prev, msg):
                        logger.debug("Deduplicating tool call: %s", key)
                        continue
                    result.append(msg)
            else:
                result.append(msg)

        return result

    def score_message_importance(self, message: Message) -> float:
        """Score a message's importance from 0.0 to 1.0.

        Higher scores indicate messages that should be preserved during compression.

        Args:
            message: Message to score.

        Returns:
            Importance score (0.0 to 1.0).
        """
        score = 0.5

        if message.role == "system":
            score = 1.0
        elif message.role == "user":
            score = 0.8
        elif message.role == "assistant":
            if any(
                k in message.content.lower()
                for k in ["error", "fail", "cannot", "unable"]
            ):
                score = 0.9
            elif message.content.strip().startswith("```"):
                score = 0.6
            else:
                score = 0.7
        elif message.role == "tool":
            if message.metadata.get("tool_name") in (
                "browser.navigate",
                "shell",
                "code_execution",
            ):
                score = 0.8
            elif message.metadata.get("success") is False:
                score = 0.9
            else:
                score = 0.4

        length_penalty = min(len(message.content) / 2000, 1.0)
        score = score * (0.7 + 0.3 * length_penalty)

        return min(max(score, 0.0), 1.0)

    def get_compression_stats(
        self,
        before: list[Message],
        after: list[Message],
    ) -> dict[str, Any]:
        """Return statistics about a compression operation."""
        before_tokens = self._total_tokens(before)
        after_tokens = self._total_tokens(after)
        return {
            "before_count": len(before),
            "after_count": len(after),
            "before_tokens": before_tokens,
            "after_tokens": after_tokens,
            "reduction_ratio": (
                1.0 - after_tokens / before_tokens if before_tokens else 0.0
            ),
        }

    def _truncate(self, messages: list[Message], budget: int) -> list[Message]:
        """Simple truncation: keep most recent messages until budget is met."""
        result: list[Message] = []
        tokens = 0
        for msg in reversed(messages):
            if tokens + msg.token_count <= budget:
                result.insert(0, msg)
                tokens += msg.token_count
            else:
                break
        if not result:
            return [messages[-1]]
        return result

    def _prune(self, messages: list[Message], budget: int) -> list[Message]:
        """Prune by importance score: keep high-value messages."""
        scored = [(self.score_message_importance(m), m) for m in messages]
        scored.sort(key=lambda x: x[0], reverse=True)

        result: list[Message] = []
        tokens = 0
        for _score, msg in scored:
            if tokens + msg.token_count <= budget:
                result.append(msg)
                tokens += msg.token_count
        result.sort(key=lambda m: messages.index(m))
        return result if result else [messages[-1]]

    def _summarize(self, messages: list[Message], budget: int) -> list[Message]:
        """Summarize: compress older messages into a summary."""
        if len(messages) <= 2:
            return self._truncate(messages, budget)
        recent = messages[-2:]
        older = messages[:-2]
        summary = self._make_summary(older)
        return [summary] + recent

    def _hybrid_compress(self, messages: list[Message], budget: int) -> list[Message]:
        """Hybrid: deduplicate first, then summarize, then truncate."""
        deduped = self.deduplicate_tool_calls(messages)
        if self._total_tokens(deduped) <= budget:
            return deduped
        summarized = self._summarize(deduped, budget)
        if self._total_tokens(summarized) <= budget:
            return summarized
        return self._truncate(summarized, budget)

    def _llm_summarize(
        self, messages: list[Message], target_tokens: int
    ) -> list[Message]:
        """Use the configured LLM summarizer for semantic summarization."""
        if self.llm_summarizer is None:
            return self._simple_summarize(messages, target_tokens)

        prompt = self._build_summary_prompt(messages, target_tokens)
        try:
            response = self.llm_summarizer(prompt)
            summary_content = response.get("content", "")
            summary_msg = Message(
                role="system",
                content=f"[Earlier conversation summary]\n{summary_content}",
                token_count=int(target_tokens * 0.75),
                importance_score=0.9,
                metadata={"type": "compressed_summary"},
            )
            return [summary_msg] + messages[-2:]
        except Exception as e:
            logger.warning("LLM summarization failed: %s, falling back", e)
            return self._simple_summarize(messages, target_tokens)

    def _simple_summarize(
        self, messages: list[Message], target_tokens: int
    ) -> list[Message]:
        """Simple extraction-based summarization without LLM."""
        topics = []
        for msg in messages:
            first_line = msg.content.strip().split("\n")[0][:100]
            if first_line:
                topics.append(f"- {msg.role}: {first_line}")

        summary_text = (
            "[Earlier conversation summary — "
            f"{len(messages)} messages]\n"
            + "\n".join(topics[:10])
        )
        summary_msg = Message(
            role="system",
            content=summary_text,
            token_count=int(len(summary_text) * 0.25),
            importance_score=0.9,
            metadata={"type": "compressed_summary"},
        )
        return [summary_msg] + messages[-2:]

    def _make_summary(self, messages: list[Message]) -> Message:
        """Create a summary message from older messages."""
        topics = []
        for msg in messages:
            if msg.role == "user":
                first = msg.content.strip().split("\n")[0][:120]
                topics.append(f"User: {first}")
            elif msg.role == "assistant" and msg.content:
                first = msg.content.strip().split("\n")[0][:120]
                topics.append(f"Assistant: {first}")

        content = (
            f"[Earlier conversation — {len(messages)} messages]\n"
            + "\n".join(topics[:8])
        )
        return Message(
            role="system",
            content=content,
            token_count=int(len(content) * 0.25),
            importance_score=0.85,
            metadata={"type": "compressed_summary"},
        )

    def _build_summary_prompt(
        self, messages: list[Message], target_tokens: int
    ) -> str:
        """Build a prompt for LLM-based summarization."""
        return (
            f"Summarize the following conversation in approximately "
            f"{target_tokens} tokens. Preserve key facts, decisions, "
            f"and any unresolved issues:\n\n"
            + "\n---\n".join(f"{m.role}: {m.content[:500]}" for m in messages)
        )

    def _total_tokens(self, messages: list[Message]) -> int:
        """Sum token counts, estimating if not set."""
        total = 0
        for m in messages:
            if m.token_count:
                total += m.token_count
            else:
                total += int(len(m.content) * 0.25)
        return total

    def _tool_call_key(self, message: Message) -> str | None:
        """Extract a deduplication key from a tool message."""
        if message.role not in ("tool", "assistant"):
            return None
        tool_name = message.metadata.get("tool_name", "")
        if not tool_name and message.content.startswith("invoke"):
            parts = message.content.split()
            if len(parts) > 1:
                tool_name = parts[1]
        return tool_name or None

    def _is_duplicate(self, prev: Message, curr: Message) -> bool:
        """Check if two tool messages are near-duplicates."""
        if prev.metadata.get("tool_name") != curr.metadata.get("tool_name"):
            return False
        similarity = self._content_similarity(prev.content, curr.content)
        return similarity > 0.85

    def _content_similarity(self, a: str, b: str) -> float:
        """Simple similarity score between two strings."""
        if not a or not b:
            return 0.0
        a_set = set(a.lower().split())
        b_set = set(b.lower().split())
        intersection = len(a_set & b_set)
        union = len(a_set | b_set)
        return intersection / union if union else 0.0
