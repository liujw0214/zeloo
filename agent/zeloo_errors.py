"""Zeloo unified error hierarchy and error codes.

All Zeloo-raised exceptions inherit from :class:`ZelooError` so that
upstream code can catch a single base type. Errors carry an optional
error code following the convention:

* E001: configuration errors
* E002: authentication / authorization
* E003: network / connectivity
* E004: provider / model errors
* E005: tool execution errors
* E006: memory / persistence errors
* E007: skill errors
* E008: cron / scheduling errors
* E009: MCP / protocol errors
* E010: gateway / API errors
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    """Stable error codes used across the Zeloo runtime."""

    CONFIG = "E001"
    AUTH = "E002"
    NETWORK = "E003"
    PROVIDER = "E004"
    TOOL = "E005"
    MEMORY = "E006"
    SKILL = "E007"
    CRON = "E008"
    MCP = "E009"
    GATEWAY = "E010"


class ZelooError(Exception):
    """Base class for all Zeloo-specific errors.

    Catching :class:`ZelooError` covers every error that the Zeloo
    runtime is allowed to raise, while still allowing callers to inspect
    the structured ``code`` and ``details`` fields.
    """

    code: ErrorCode = ErrorCode.CONFIG
    message: str = ""

    def __init__(
        self,
        message: str = "",
        *,
        code: ErrorCode | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        if message:
            self.message = message
        self.details: dict[str, Any] = details or {}
        if code is not None:
            self.code = code
        super().__init__(self._format())

    def _format(self) -> str:
        prefix = f"[{self.code.value}]" if self.code else ""
        msg = f"{prefix} {self.message}".strip()
        if self.details:
            msg += f" ({self.details})"
        return msg

    def to_dict(self) -> dict[str, Any]:
        """Return a structured representation suitable for JSON output."""
        return {
            "error_class": self.__class__.__name__,
            "code": self.code.value if self.code else None,
            "message": self.message,
            "details": self.details,
        }


class ConfigError(ZelooError):
    """Raised for invalid, missing or inconsistent configuration."""

    code = ErrorCode.CONFIG


class AuthError(ZelooError):
    """Raised when authentication or authorization fails."""

    code = ErrorCode.AUTH


class NetworkError(ZelooError):
    """Raised for connectivity failures (timeouts, DNS, refused connections)."""

    code = ErrorCode.NETWORK


class ProviderError(ZelooError):
    """Raised when a model provider returns an error or is unavailable."""

    code = ErrorCode.PROVIDER


class ToolError(ZelooError):
    """Raised when a tool execution fails or produces invalid output."""

    code = ErrorCode.TOOL


class MemoryError(ZelooError):
    """Raised for memory store failures (read/write/corruption)."""

    code = ErrorCode.MEMORY


class SkillError(ZelooError):
    """Raised for skill loading, parsing or execution errors."""

    code = ErrorCode.SKILL


class CronError(ZelooError):
    """Raised when scheduling, dispatching or persisting cron jobs fails."""

    code = ErrorCode.CRON


class MCPError(ZelooError):
    """Raised for MCP protocol or transport errors."""

    code = ErrorCode.MCP


class GatewayError(ZelooError):
    """Raised by gateway/API layers when handling requests fails."""

    code = ErrorCode.GATEWAY


__all__ = [
    "ErrorCode",
    "ZelooError",
    "ConfigError",
    "AuthError",
    "NetworkError",
    "ProviderError",
    "ToolError",
    "MemoryError",
    "SkillError",
    "CronError",
    "MCPError",
    "GatewayError",
]
