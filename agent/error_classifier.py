"""Error classifier — structured categorization of runtime errors.

This module transforms raw
exceptions and LLM error responses into structured categories with
recommended handling strategies (retry, fallback, escalate, abort).

Categories:
- AUTH: API key invalid/expired (401/403)
- RATE_LIMIT: Too many requests (429)
- TIMEOUT: Request timed out
- SERVER_ERROR: Provider-side error (5xx)
- CONTEXT_OVERFLOW: Context window exceeded
- CONTENT_FILTER: Content policy violation
- NETWORK: Connectivity issues
- TOOL_ERROR: Tool execution failure
- VALIDATION: Input/schema validation error
- UNKNOWN: Unclassified

Usage::

    from agent.error_classifier import classify_error, ErrorCategory

    result = classify_error(exc, provider="openai")
    if result.retryable:
        ...
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class ErrorCategory(StrEnum):
    """Structured error categories."""

    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    SERVER_ERROR = "server_error"
    CONTEXT_OVERFLOW = "context_overflow"
    CONTENT_FILTER = "content_filter"
    NETWORK = "network"
    TOOL_ERROR = "tool_error"
    VALIDATION = "validation"
    UNKNOWN = "unknown"


@dataclass
class ErrorClassification:
    """Result of error classification with handling guidance."""

    category: ErrorCategory
    message: str
    retryable: bool
    retry_delay_seconds: float
    should_fallback_provider: bool
    should_escalate: bool
    status_code: int | None = None
    raw_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "category": self.category.value,
            "message": self.message,
            "retryable": self.retryable,
            "retry_delay_seconds": self.retry_delay_seconds,
            "should_fallback_provider": self.should_fallback_provider,
            "should_escalate": self.should_escalate,
            "status_code": self.status_code,
        }


# Regex patterns for context overflow detection
_CONTEXT_OVERFLOW_PATTERNS = [
    re.compile(r"context length", re.IGNORECASE),
    re.compile(r"maximum context", re.IGNORECASE),
    re.compile(r"context window", re.IGNORECASE),
    re.compile(r"too many tokens", re.IGNORECASE),
    re.compile(r"input.*exceeds.*limit", re.IGNORECASE),
]

# Regex patterns for content filter detection
_CONTENT_FILTER_PATTERNS = [
    re.compile(r"content policy", re.IGNORECASE),
    re.compile(r"content filter", re.IGNORECASE),
    re.compile(r"prompt.*violat", re.IGNORECASE),
    re.compile(r"unsafe content", re.IGNORECASE),
    re.compile(r"harmful content", re.IGNORECASE),
]

# Regex patterns for rate limit detection
_RATE_LIMIT_PATTERNS = [
    re.compile(r"rate limit", re.IGNORECASE),
    re.compile(r"too many requests", re.IGNORECASE),
    re.compile(r"quota", re.IGNORECASE),
    re.compile(r"requests per minute", re.IGNORECASE),
]


def classify_error(
    error: Exception | str,
    provider: str = "",
    status_code: int | None = None,
) -> ErrorClassification:
    """Classify an error into a structured category.

    Args:
        error: The exception instance or error message string.
        provider: The LLM provider name (for logging).
        status_code: HTTP status code if available.

    Returns:
        An :class:`ErrorClassification` with retry/fallback guidance.
    """
    message = str(error)
    raw_error = repr(error) if isinstance(error, Exception) else error

    # 1. Check status code first (most reliable signal)
    if status_code is not None:
        classification = _classify_by_status(status_code, message)
        if classification is not None:
            classification.raw_error = raw_error
            return classification

    # 2. Check for known exception types
    if isinstance(error, Exception):
        classification = _classify_by_exception_type(error, message)
        if classification is not None:
            classification.raw_error = raw_error
            classification.status_code = status_code
            return classification

    # 3. Check error message patterns
    classification = _classify_by_message(message)
    if classification is not None:
        classification.raw_error = raw_error
        classification.status_code = status_code
        return classification

    # 4. Fallback to unknown
    return ErrorClassification(
        category=ErrorCategory.UNKNOWN,
        message=message[:500],
        retryable=True,
        retry_delay_seconds=1.0,
        should_fallback_provider=False,
        should_escalate=False,
        status_code=status_code,
        raw_error=raw_error,
    )


def _classify_by_status(
    status_code: int, message: str
) -> ErrorClassification | None:
    """Classify based on HTTP status code."""
    if status_code in (401, 403):
        return ErrorClassification(
            category=ErrorCategory.AUTH,
            message=f"Authentication failed ({status_code}): {message[:200]}",
            retryable=False,
            retry_delay_seconds=0,
            should_fallback_provider=True,
            should_escalate=True,
            status_code=status_code,
        )
    if status_code == 429:
        return ErrorClassification(
            category=ErrorCategory.RATE_LIMIT,
            message=f"Rate limited (429): {message[:200]}",
            retryable=True,
            retry_delay_seconds=30.0,
            should_fallback_provider=True,
            should_escalate=False,
            status_code=status_code,
        )
    if status_code in (400, 422):
        # Could be validation or context overflow
        for pattern in _CONTEXT_OVERFLOW_PATTERNS:
            if pattern.search(message):
                return ErrorClassification(
                    category=ErrorCategory.CONTEXT_OVERFLOW,
                    message=f"Context overflow ({status_code}): {message[:200]}",
                    retryable=True,
                    retry_delay_seconds=0,
                    should_fallback_provider=False,
                    should_escalate=False,
                    status_code=status_code,
                )
        return ErrorClassification(
            category=ErrorCategory.VALIDATION,
            message=f"Validation error ({status_code}): {message[:200]}",
            retryable=False,
            retry_delay_seconds=0,
            should_fallback_provider=False,
            should_escalate=False,
            status_code=status_code,
        )
    if status_code >= 500:
        return ErrorClassification(
            category=ErrorCategory.SERVER_ERROR,
            message=f"Server error ({status_code}): {message[:200]}",
            retryable=True,
            retry_delay_seconds=5.0,
            should_fallback_provider=True,
            should_escalate=False,
            status_code=status_code,
        )
    return None


def _classify_by_exception_type(
    error: Exception, message: str
) -> ErrorClassification | None:
    """Classify based on exception type."""
    error_name = type(error).__name__.lower()

    if "timeout" in error_name or "timeout" in message.lower():
        return ErrorClassification(
            category=ErrorCategory.TIMEOUT,
            message=f"Request timed out: {message[:200]}",
            retryable=True,
            retry_delay_seconds=10.0,
            should_fallback_provider=True,
            should_escalate=False,
        )
    if "connection" in error_name or "network" in error_name:
        return ErrorClassification(
            category=ErrorCategory.NETWORK,
            message=f"Network error: {message[:200]}",
            retryable=True,
            retry_delay_seconds=5.0,
            should_fallback_provider=True,
            should_escalate=False,
        )
    return None


def _classify_by_message(message: str) -> ErrorClassification | None:
    """Classify based on error message text patterns."""
    msg_lower = message.lower()

    for pattern in _CONTEXT_OVERFLOW_PATTERNS:
        if pattern.search(msg_lower):
            return ErrorClassification(
                category=ErrorCategory.CONTEXT_OVERFLOW,
                message=f"Context overflow: {message[:200]}",
                retryable=True,
                retry_delay_seconds=0,
                should_fallback_provider=False,
                should_escalate=False,
            )

    for pattern in _CONTENT_FILTER_PATTERNS:
        if pattern.search(msg_lower):
            return ErrorClassification(
                category=ErrorCategory.CONTENT_FILTER,
                message=f"Content filter: {message[:200]}",
                retryable=False,
                retry_delay_seconds=0,
                should_fallback_provider=False,
                should_escalate=True,
            )

    for pattern in _RATE_LIMIT_PATTERNS:
        if pattern.search(msg_lower):
            return ErrorClassification(
                category=ErrorCategory.RATE_LIMIT,
                message=f"Rate limited: {message[:200]}",
                retryable=True,
                retry_delay_seconds=30.0,
                should_fallback_provider=True,
                should_escalate=False,
            )

    if "invalid api key" in msg_lower or "unauthorized" in msg_lower:
        return ErrorClassification(
            category=ErrorCategory.AUTH,
            message=f"Auth error: {message[:200]}",
            retryable=False,
            retry_delay_seconds=0,
            should_fallback_provider=True,
            should_escalate=True,
        )

    return None
