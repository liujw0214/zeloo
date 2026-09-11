"""Transport adapter abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class TransportError(Exception):
    """Base exception for transport adapter errors."""

    pass


class AuthenticationError(TransportError):
    """API credentials are invalid or expired."""

    pass


class RateLimitError(TransportError):
    """Provider rate limit exceeded."""

    pass


class ModelUnavailableError(TransportError):
    """Requested model is not available for this provider."""

    pass


@dataclass
class Response:
    """Standardized chat completion response."""

    content: str
    raw: dict[str, Any] = field(default_factory=dict)
    model: str = ""
    finish_reason: str = ""
    usage_in: int = 0
    usage_out: int = 0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    @property
    def total_tokens(self) -> int:
        return self.usage_in + self.usage_out


class TransportAdapter(ABC):
    """Abstract base class for all transport adapters.

    All concrete adapters must implement:
    - chat_completion()
    - validate_credentials()

    Subclasses can optionally override:
    - supports_feature()
    - get_default_model()
    """

    name: str = "base"
    supports_streaming: bool = True
    supports_vision: bool = False
    supports_tools: bool = True
    max_context_tokens: int = 128000

    @abstractmethod
    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> Response:
        """Send a chat completion request and return a standardized response.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            model: Model identifier string.
            tools: Optional list of tool definitions.
            stream: If True, yield streaming chunks (not implemented in base).
            **kwargs: Provider-specific options (temperature, max_tokens, etc.)

        Returns:
            Response object with standardized fields.
        """

    @abstractmethod
    def validate_credentials(self) -> bool:
        """Check whether the API credentials are valid.

        Returns:
            True if credentials are valid, False otherwise.
        """

    def supports_feature(self, feature: str) -> bool:
        """Query whether this adapter supports a given feature.

        Args:
            feature: Feature name ("streaming", "vision", "tools", "json_mode").

        Returns:
            True if the feature is supported.
        """
        feature_map: dict[str, bool] = {
            "streaming": self.supports_streaming,
            "vision": self.supports_vision,
            "tools": self.supports_tools,
        }
        return feature_map.get(feature, False)

    def get_default_model(self) -> str:
        """Return the recommended default model for this adapter."""
        return ""

    def format_error(self, raw_error: Any) -> str:
        """Convert a provider-specific error to a user-friendly message."""
        return str(raw_error)
