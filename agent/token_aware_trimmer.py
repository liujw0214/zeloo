"""Token-aware trimmer — rolling window trim using a real tokenizer when possible."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Reserved overhead per message for role tags, tool metadata, etc.
_MSG_OVERHEAD_TOKENS = 8

# Default fallback when tiktoken isn't usable for the model.
DEFAULT_FALLBACK_CHARS_PER_TOKEN = 4


class TokenAwareTrimmer:
    """Token-based rolling window trim.

    Prefers the ``tiktoken`` library for accurate counts when the model
    is recognised. Otherwise falls back to a deterministic
    ``chars / N`` heuristic. The active backend can be inspected at
    runtime with :py:meth:`get_tokenizer_status`.
    """

    def __init__(
        self,
        model: str = "gpt-4o",
        fallback_chars_per_token: int = DEFAULT_FALLBACK_CHARS_PER_TOKEN,
    ) -> None:
        self.model = model
        self.fallback_chars_per_token = fallback_chars_per_token
        self._encoding = None
        self._backend = "fallback"
        self._init_tokenizer()

    # ------------------------------------------------------------------
    # Tokenizer bootstrap
    # ------------------------------------------------------------------

    def _init_tokenizer(self) -> None:
        try:
            import tiktoken  # type: ignore[import-not-found]

            try:
                self._encoding = tiktoken.encoding_for_model(self.model)
                self._backend = "tiktoken"
                return
            except KeyError:
                # Unknown model name — pick the closest family encoding.
                self._encoding = tiktoken.get_encoding("cl100k_base")
                self._backend = "tiktoken:cl100k_base"
        except ImportError:
            logger.debug("tiktoken not installed, falling back to chars/%d", self.fallback_chars_per_token)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("tiktoken initialisation failed: %s", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_tokenizer_status(self) -> str:
        """Return a human-readable description of the active backend."""
        if self._backend == "fallback":
            return f"chars/{self.fallback_chars_per_token} (fallback)"
        return f"tiktoken[{self._backend}]"

    def count_tokens(self, text: str) -> int:
        """Count tokens in a single string."""
        if not text:
            return 0
        if self._encoding is not None:
            return len(self._encoding.encode(text))
        # Fallback: chars-per-token heuristic. CJK characters are wider; pad up.
        chars = len(text)
        cjk = sum(1 for c in text if ord(c) > 0x2E80)
        effective_chars = chars + cjk  # rough widening for CJK
        return max(1, (effective_chars + self.fallback_chars_per_token - 1) // self.fallback_chars_per_token)

    def trim_message(self, message: dict[str, Any], max_tokens: int) -> dict[str, Any]:
        """Trim a single message in-place-style, returning a new dict.

        Strategy:
          * System messages are never trimmed (return a shallow copy).
          * Tool messages get the *tail* preserved (most recent context).
          * User / assistant messages get the *head* preserved (intent first).
        """
        if max_tokens <= 0:
            return {"role": message.get("role", "user"), "content": ""}

        if message.get("role") == "system":
            return dict(message)

        content = message.get("content")
        if isinstance(content, list):
            # Multimodal content — count every text block and trim the longest.
            text_blocks = [(i, b) for i, b in enumerate(content) if isinstance(b, dict) and b.get("type") == "text"]
            if not text_blocks:
                return dict(message)
            # Concatenate text blocks into a single string for trimming.
            joined = "\n".join(b.get("text", "") for _, b in text_blocks)
            trimmed = self._truncate_text(joined, max_tokens - _MSG_OVERHEAD_TOKENS, prefer_tail=(message.get("role") == "tool"))
            new_blocks = []
            text_iter = iter([trimmed])
            joined_block = next(text_iter, "")
            for b in content:
                if isinstance(b, dict) and b.get("type") == "text":
                    new_blocks.append({"type": "text", "text": joined_block})
                    joined_block = ""
                else:
                    new_blocks.append(b)
            new_msg = dict(message)
            new_msg["content"] = new_blocks
            return new_msg

        if not isinstance(content, str):
            return dict(message)

        prefer_tail = message.get("role") == "tool"
        trimmed_text = self._truncate_text(
            content,
            max_tokens - _MSG_OVERHEAD_TOKENS,
            prefer_tail=prefer_tail,
        )
        new_msg = dict(message)
        new_msg["content"] = trimmed_text
        return new_msg

    def trim_messages(
        self,
        messages: list[dict[str, Any]],
        total_budget: int,
    ) -> list[dict[str, Any]]:
        """Trim ``messages`` so the total token count fits within ``total_budget``.

        The system message (if present at index 0) is always preserved.
        Older non-system messages are dropped first; the remaining
        messages are individually trimmed to fit any residual budget.
        """
        if not messages:
            return []

        system_msg: dict[str, Any] | None = None
        body: list[dict[str, Any]] = []
        if messages[0].get("role") == "system":
            system_msg = messages[0]
            body = list(messages[1:])
        else:
            body = list(messages)

        sys_tokens = self.count_tokens(system_msg.get("content", "")) + _MSG_OVERHEAD_TOKENS if system_msg else 0
        available = max(0, total_budget - sys_tokens)

        # Drop oldest until under budget, then trim each.
        while body and self._body_tokens(body) > available:
            body.pop(0)

        per_msg_budget = max(32, available // max(1, len(body))) if body else available
        trimmed_body = [self.trim_message(m, per_msg_budget) for m in body]

        result: list[dict[str, Any]] = []
        if system_msg is not None:
            result.append(system_msg)
        result.extend(trimmed_body)
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _body_tokens(self, messages: list[dict[str, Any]]) -> int:
        total = 0
        for m in messages:
            total += self._message_tokens(m)
        return total

    def _message_tokens(self, message: dict[str, Any]) -> int:
        content = message.get("content")
        if isinstance(content, str):
            return self.count_tokens(content) + _MSG_OVERHEAD_TOKENS
        if isinstance(content, list):
            joined = "".join(
                b.get("text", "") if isinstance(b, dict) else str(b) for b in content
            )
            return self.count_tokens(joined) + _MSG_OVERHEAD_TOKENS
        return _MSG_OVERHEAD_TOKENS

    def _truncate_text(
        self,
        text: str,
        max_tokens: int,
        prefer_tail: bool = False,
    ) -> str:
        if max_tokens <= 0:
            return ""
        if self.count_tokens(text) <= max_tokens:
            return text

        # Binary search the cut-point using token counts.
        if self._encoding is not None:
            tokens = self._encoding.encode(text)
            if prefer_tail:
                tokens = tokens[-max_tokens:]
                return self._encoding.decode(tokens)
            tokens = tokens[:max_tokens]
            return self._encoding.decode(tokens)

        # Fallback: binary search on character offsets.
        low, high = 0, len(text)
        while low < high:
            mid = (low + high + 1) // 2
            candidate = text[-mid:] if prefer_tail else text[:mid]
            if self.count_tokens(candidate) <= max_tokens:
                low = mid
            else:
                high = mid - 1

        snippet = text[-low:] if prefer_tail else text[:low]
        marker = "\n\n[... trimmed ...]\n\n"
        return (marker + snippet) if prefer_tail else (snippet + marker)