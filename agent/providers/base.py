"""Provider abstract base class for the Zeloo Agent runtime.

This module defines :class:`BaseProvider`, the uniform contract every LLM
provider must implement. The agent runtime interacts with providers
exclusively through this interface so it can swap providers transparently.

Concrete providers live in dedicated submodules (openai_provider,
anthropic_provider, …) and register themselves with the
:mod:`agent.providers.registry` registry on import.

Design notes
------------

* Async-first — providers expose ``async`` ``chat_completion`` so the agent
  loop can issue concurrent calls without blocking the event loop.
* Streaming is supported through the ``stream=True`` parameter. When the
  flag is set, providers must return a response whose ``stream`` field
  is an async iterator of partial chunks (dicts with ``delta`` and
  ``finish_reason`` keys).
* Vision and function calling are provider-specific capabilities that
  the base class exposes as boolean flags; subclasses set them.
* No external dependencies beyond the standard library plus
  ``httpx`` (already used elsewhere in the runtime) are required.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseProvider(ABC):
    """LLM Provider 抽象基类.

    Subclasses **must** implement :meth:`chat_completion`,
    :meth:`list_models`, and :meth:`is_available`. They should also set
    the class-level :attr:`name` attribute to a unique lower-case
    identifier and call :func:`register_provider` from
    :mod:`agent.providers.registry` so the runtime can discover them.

    Attributes:
        name: Unique lower-case provider identifier (e.g. ``"openai"``).
            Used as the registry key.
        supports_vision: Whether the provider can accept image inputs.
        supports_function_calling: Whether the provider supports tools.
        supports_streaming: Whether the provider can stream completions.
        default_model: The recommended default model identifier.
    """

    name: str = ""
    supports_vision: bool = False
    supports_function_calling: bool = True
    supports_streaming: bool = True
    default_model: str = ""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """Initialize the provider with a configuration mapping.

        Args:
            config: Free-form provider configuration. Recognised keys
                depend on the concrete subclass but commonly include
                ``api_key``, ``base_url``, ``timeout``,
                ``default_model``, ``organization`` etc.
        """
        self.config: dict[str, Any] = dict(config or {})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        """Return a config value or *default* if not present."""
        return self.config.get(key, default)

    @property
    def api_key(self) -> str:
        """Convenience accessor for ``config['api_key']``."""
        return str(self.config.get("api_key") or "")

    @property
    def base_url(self) -> str:
        """Convenience accessor for ``config['base_url']``."""
        return str(self.config.get("base_url") or "")

    @property
    def timeout(self) -> float:
        """Return the request timeout in seconds."""
        try:
            return float(self.config.get("timeout", 60.0))
        except (TypeError, ValueError):
            return 60.0

    # ------------------------------------------------------------------
    # Required interface
    # ------------------------------------------------------------------
    @abstractmethod
    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """调用 chat completion API.

        Args:
            messages: OpenAI-style message list. Each entry is a dict
                with at least ``role`` and ``content`` keys.
            model: Model identifier (provider-specific).
            temperature: Sampling temperature, ``0.0``–``2.0``.
            max_tokens: Maximum number of tokens to generate.
            stream: If ``True``, return an async iterator in
                ``response['stream']`` instead of a single payload.
            **kwargs: Provider-specific passthrough (tools, vision
                payloads, response format, …).

        Returns:
            A dict containing at least ``content`` (str), ``model``
            (str), ``finish_reason`` (str), and ``usage`` (dict with
            ``prompt_tokens``/``completion_tokens`` keys). When the
            request fails the dict should include ``error`` (str) and
            the caller can inspect ``response['ok']`` (bool).
        """

    @abstractmethod
    def list_models(self) -> list[str]:
        """Return a list of model identifiers supported by this provider.

        Implementations may perform a lightweight network probe when the
        model list cannot be statically enumerated. They must never
        raise — on error, return a list containing at least
        :attr:`default_model` if it is set.
        """

    @abstractmethod
    def is_available(self) -> bool:
        """检查 provider 是否可用.

        Implementations should check that credentials are present and
        that the upstream endpoint is reachable when feasible. They
        must never raise — return ``False`` on any failure.
        """

    # ------------------------------------------------------------------
    # Optional helpers
    # ------------------------------------------------------------------
    def validate_config(self) -> tuple[bool, str]:
        """验证配置.

        Default implementation requires ``api_key`` to be a non-empty
        string. Subclasses may override to add provider-specific
        constraints (e.g. require ``base_url`` for self-hosted
        variants).
        """
        if not self.api_key and self.name not in {"ollama"}:
            return False, f"missing api_key for provider '{self.name}'"
        return True, ""

    def supports_feature(self, feature: str) -> bool:
        """Return whether the provider supports *feature*.

        Supported features: ``vision``, ``function_calling``,
        ``streaming``.
        """
        mapping: dict[str, bool] = {
            "vision": self.supports_vision,
            "function_calling": self.supports_function_calling,
            "streaming": self.supports_streaming,
        }
        return bool(mapping.get(feature, False))

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} model={self.default_model!r}>"


__all__ = ["BaseProvider"]
