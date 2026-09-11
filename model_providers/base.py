"""ProviderProfile abstract base class.

Defines the uniform contract every model provider must implement so
the agent can swap providers transparently.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ChatResponse:
    """Structured response returned by :meth:`ProviderProfile.chat_completion`."""

    content: str
    model: str
    provider: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str = "stop"
    raw: Any = None
    cost_usd: float = 0.0
    tool_calls: list[dict[str, Any]] | None = None


class ProviderProfile(ABC):
    """Abstract base for all model providers.

    Subclasses must set :attr:`name`, :attr:`base_url`, and implement
    :meth:`chat_completion` and :meth:`validate_credentials`.
    """

    name: str = "base"
    base_url: str = ""
    default_model: str = ""
    supports_streaming: bool = True
    supports_vision: bool = False
    supports_function_calling: bool = True

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        self.api_key = api_key
        self.config = kwargs

    @abstractmethod
    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """Send a chat completion request and return a :class:`ChatResponse`."""

    @abstractmethod
    def validate_credentials(self) -> bool:
        """Return True if the configured API key is usable, False otherwise."""

    def estimate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str | None = None,
    ) -> float:
        """Estimate the cost in USD for a given token usage.

        Default implementation returns 0.0 — providers should override
        with their real pricing.
        """
        return 0.0

    def __repr__(self) -> str:  # pragma: no cover — debug helper
        return f"<{self.__class__.__name__} provider={self.name} model={self.default_model}>"
