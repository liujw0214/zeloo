"""Security utilities — input sanitization and rate limiting.

* :func:`sanitize_input` — clean user input before it reaches the LLM.
* :class:`RateLimiter` — token-bucket rate limiter for API endpoints.
* :func:`validate_output` — redact secrets from assistant output.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from tools.threat_patterns import scan_for_threats
from utils import redact_secrets

logger = logging.getLogger(__name__)

# Default input limits
MAX_INPUT_LENGTH = 16000  # characters
MAX_TOOL_RESULT_LENGTH = 12000

# Injection patterns that should be stripped from user input
_INJECTION_STRIP = [
    # Remove null bytes and control chars (except newline/tab)
    (r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", ""),
]


@dataclass
class SanitizedInput:
    """Result of input sanitization."""

    text: str
    threats: list[str] = field(default_factory=list)
    truncated: bool = False

    @property
    def is_safe(self) -> bool:
        """True if no critical threats were detected."""
        critical = {"system-prompt-leak-attempt", "role-hijack", "instruction-override"}
        return not (set(self.threats) & critical)


def sanitize_input(text: str, max_length: int = MAX_INPUT_LENGTH) -> SanitizedInput:
    """Sanitize user input before sending to the LLM.

    Steps:
    1. Strip control characters and null bytes.
    2. Truncate to max_length.
    3. Scan for prompt-injection threats.

    Returns a :class:`SanitizedInput` with the cleaned text and findings.
    """
    import re

    if not isinstance(text, str):
        text = str(text)

    # Strip dangerous control characters
    for pattern, replacement in _INJECTION_STRIP:
        text = re.sub(pattern, replacement, text)

    # Truncate
    truncated = False
    if len(text) > max_length:
        text = text[:max_length]
        truncated = True

    # Scan for threats
    threats = scan_for_threats(text, scope="context")

    return SanitizedInput(text=text, threats=threats, truncated=truncated)


def validate_output(text: str) -> str:
    """Sanitize assistant output before returning to the user.

    Redacts secrets and strips control characters.
    """
    import re

    text = redact_secrets(text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return text


class RateLimiter:
    """Token-bucket rate limiter.

    Each identifier (e.g. user ID or IP) has its own bucket. Tokens refill
    at ``rate`` tokens per second up to ``capacity``. Each call consumes
    one token.

    Example::

        limiter = RateLimiter(capacity=10, rate=1.0)
        if limiter.allow("user-123"):
            handle_request()
        else:
            return 429
    """

    def __init__(self, capacity: int = 10, rate: float = 1.0) -> None:
        self._capacity = capacity
        self._rate = rate  # tokens per second
        self._buckets: dict[str, dict[str, float]] = {}

    def allow(self, identifier: str, tokens: int = 1) -> bool:
        """Return True if *identifier* is allowed to consume *tokens*.

        Refills the bucket based on elapsed time before checking.
        """
        now = time.time()
        bucket = self._buckets.get(identifier)
        if bucket is None:
            bucket = {"tokens": float(self._capacity), "last": now}
            self._buckets[identifier] = bucket

        # Refill
        elapsed = now - bucket["last"]
        bucket["tokens"] = min(
            self._capacity,
            bucket["tokens"] + elapsed * self._rate,
        )
        bucket["last"] = now

        if bucket["tokens"] >= tokens:
            bucket["tokens"] -= tokens
            return True
        return False

    def reset(self, identifier: str | None = None) -> None:
        """Reset a specific bucket (or all if identifier is None)."""
        if identifier is None:
            self._buckets.clear()
        else:
            self._buckets.pop(identifier, None)

    def remaining(self, identifier: str) -> int:
        """Return the number of tokens remaining for *identifier*."""
        bucket = self._buckets.get(identifier)
        if bucket is None:
            return self._capacity
        return int(bucket["tokens"])
