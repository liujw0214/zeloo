"""Conversation compression — message-format-aware compression layer.

This layer focuses on chat API message format compatibility and protocol
conformance, delegating core algorithms to ContextCompressor.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from agent.agent_runtime_helpers import (
    MODEL_CONTEXT_WINDOWS,
    extract_platform_hint,
    truncate_messages_for_context,
)
from agent.context_compressor import CompressionStrategy, ContextCompressor, Message

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ConversationCompressor:
    """Conversation-level compression with model-aware formatting.

    Wraps ContextCompressor and adds:
    - Model-specific context window handling
    - Tool call pattern extraction for prompt injection
    - Recent-turn preservation (always keep last N turns verbatim)
    - Platform hint injection
    """

    def __init__(
        self,
        compressor: ContextCompressor | None = None,
        min_recent_turns: int = 3,
    ):
        self.compressor = compressor or ContextCompressor()
        self.min_recent_turns = min_recent_turns

    def compress_for_model(
        self,
        messages: list[dict[str, Any]],
        model: str,
        strategy: str = "hybrid",
    ) -> list[dict[str, Any]]:
        """Compress conversation for a specific model's context window.

        Args:
            messages: Chat API message list.
            model: Model name (e.g. "gpt-4o", "claude-3-5-sonnet").
            strategy: Compression strategy name.

        Returns:
            Compressed message list ready for the model.
        """
        max_ctx = MODEL_CONTEXT_WINDOWS.get(model, 128000)
        strategy_enum = CompressionStrategy(strategy)

        parsed = [Message.from_dict(m) for m in messages]

        recent, older = self._split_recent(parsed)

        if not older:
            return messages

        compressed_older = self.compressor.compress(
            older, strategy=strategy_enum
        )

        result = compressed_older + recent
        result = self._ensure_budget(result, max_ctx)

        return [m.to_dict() for m in result]

    def preserve_recent_turns(
        self,
        messages: list[dict[str, Any]],
        min_recent_turns: int | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Split messages into recent (protected) and older (compressible) groups.

        A "turn" is a user message + assistant response pair.

        Args:
            messages: Full message list.
            min_recent_turns: Minimum recent turns to protect. Defaults to self.min_recent_turns.

        Returns:
            Tuple of (older_messages, recent_messages). Recent is always returned
            last so callers can prepend older.
        """
        n = min_recent_turns or self.min_recent_turns
        parsed = [Message.from_dict(m) for m in messages]

        if len(parsed) <= n * 2:
            return [], parsed

        recent_count = n * 2
        older = list(parsed[:-recent_count])
        recent = list(parsed[-recent_count:])

        return older, recent

    def extract_tool_call_patterns(
        self,
        messages: list[dict[str, Any]],
    ) -> list[str]:
        """Extract distinct tool call patterns for prompt injection.

        Groups tool calls by name and returns a summary of each distinct
        pattern used in the conversation.

        Args:
            messages: Chat API message list.

        Returns:
            List of tool call pattern descriptions.
        """
        patterns: dict[str, int] = {}

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "assistant" and content:
                tc_blocks = self._extract_tool_calls_from_content(content)
                for tc in tc_blocks:
                    name = tc.get("name", "unknown")
                    patterns[name] = patterns.get(name, 0) + 1

            elif role == "tool":
                tool_name = msg.get("name", "")
                if tool_name:
                    patterns[tool_name] = patterns.get(tool_name, 0) + 1

        result = []
        for name, count in sorted(patterns.items(), key=lambda x: x[1], reverse=True):
            result.append(f"- {name} (used {count}x)")

        return result

    def build_enhanced_system_prompt(
        self,
        base_prompt: str,
        messages: list[dict[str, Any]],
        platform: str | None = None,
    ) -> str:
        """Build an enhanced system prompt with context-aware additions.

        Args:
            base_prompt: Base system prompt.
            messages: Current conversation for context.
            platform: Platform name for hint injection.

        Returns:
            Enhanced system prompt string.
        """
        parts = [base_prompt]

        if platform:
            hint = extract_platform_hint(platform)
            parts.append(f"\n\n## Platform Context\n{hint}")

        patterns = self.extract_tool_call_patterns(messages)
        if patterns:
            parts.append(
                "\n\n## Observed Tool Patterns\n"
                + "\n".join(patterns[:10])
            )

        tool_count = len(patterns)
        if tool_count > 0:
            parts.append(
                f"\n\nNote: {tool_count} distinct tool patterns have been used "
                "in this conversation."
            )

        return "\n".join(parts)

    def format_messages_for_provider(
        self,
        messages: list[dict[str, Any]],
        provider: str,
    ) -> list[dict[str, Any]]:
        """Reformat messages for provider-specific quirks.

        Args:
            messages: Standard message list.
            provider: Provider name ("openai", "anthropic", "deepseek", etc.).

        Returns:
            Provider-adapted message list.
        """
        formatted = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            name = msg.get("name")

            if provider == "anthropic" and role == "system":
                role = "user"

            if provider in ("deepseek", "gemini") and role == "assistant":
                if isinstance(content, list):
                    text_parts = [
                        c.get("text", "") if isinstance(c, dict) else str(c)
                        for c in content
                    ]
                    content = "".join(text_parts)

            entry: dict[str, Any] = {"role": role, "content": content}
            if name and role == "assistant":
                entry["name"] = name

            formatted.append(entry)

        return formatted

    def _split_recent(
        self, messages: list[Message]
    ) -> tuple[list[Message], list[Message]]:
        """Split into (older, recent) based on min_recent_turns."""
        n = self.min_recent_turns * 2
        if len(messages) <= n:
            return [], list(messages)
        return list(messages[:-n]), list(messages[-n:])

    def _ensure_budget(
        self, messages: list[Message], max_tokens: int
    ) -> list[Message]:
        """Final safety truncation if still over budget."""
        total = sum(
            m.token_count or int(len(m.content) * 0.25) for m in messages
        )
        if total <= int(max_tokens * 0.9):
            return messages
        result = truncate_messages_for_context(
            [m.to_dict() for m in messages],
            int(max_tokens * 0.85),
        )
        return [Message.from_dict(m) for m in result]

    def _extract_tool_calls_from_content(
        self, content: str
    ) -> list[dict[str, Any]]:
        """Extract tool call blocks from assistant message content."""
        calls = []

        xml_pattern = re.compile(
            r"<tool_call>\s*<name>(.*?)</name>\s*<args>(.*?)</args>\s*</tool_call>",
            re.DOTALL,
        )
        for match in xml_pattern.finditer(content):
            name = match.group(1).strip()
            args_raw = match.group(2).strip()
            try:
                import json
                args = json.loads(args_raw) if args_raw else {}
            except Exception:
                args = {"raw": args_raw}
            calls.append({"name": name, "arguments": args})

        return calls
