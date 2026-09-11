"""Zeloo Agent utility helpers."""

from __future__ import annotations

import os
import re
from typing import Any

_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Estimate the number of tokens in *text*."""
    if not text:
        return 0
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return max(1, len(text) // _CHARS_PER_TOKEN)


def count_message_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate total tokens across a list of chat messages."""
    total = 0
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    total += estimate_tokens(str(part.get("text", "")))
        total += 4
    return total


def is_truthy_value(value: Any) -> bool:
    """Return True if *value* should be treated as truthy."""
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def redact_secrets(text: str) -> str:
    """Redact common secret patterns from text.

    This is a thin convenience wrapper around
    :mod:`agent.secret_scanner` — the scanner covers more patterns
    (GitHub/GitLab/Slack/Stripe/AWS/JWT/Google) and the API is more
    discoverable. We keep this helper so callers that ``import utils``
    directly continue to work unchanged.
    """
    try:
        from agent.secret_scanner import redact_text as _scanner_redact

        return _scanner_redact(text)
    except Exception:
        # Graceful fallback — keep the original regex set so we still
        # catch the most common patterns even if the scanner import fails.
        patterns = [
            (r"sk-[a-zA-Z0-9]{20,}", "[REDACTED_API_KEY]"),
            (
                r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
                "[REDACTED_KEY]",
            ),
            (r"(?i)(password|secret|token|api_key)\s*[=:]\s*\S+", r"\1=[REDACTED]"),
        ]
        for pattern, replacement in patterns:
            text = re.sub(pattern, replacement, text, flags=re.DOTALL)
        return text


def atomic_json_write(path: str, data: Any) -> None:
    """Write JSON to *path* atomically via a temp file + rename."""
    import json
    import tempfile
    tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path) or ".")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
