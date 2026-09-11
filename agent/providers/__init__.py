"""LLM Provider package for the Zeloo Agent runtime.

This package contains the async-first provider implementations that
front LLM APIs (OpenAI, Anthropic, Google Gemini, Groq, Mistral,
DeepSeek, OpenRouter, and Ollama). Every concrete provider:

* Inherits from :class:`agent.providers.base.BaseProvider`,
* Registers itself with :mod:`agent.providers.registry` on import,
* Returns the unified response dict documented in :mod:`_http`,
* Handles errors gracefully — callers always see
  ``{"ok": False, "error": ...}`` rather than exceptions.

Importing the package triggers registration of every concrete
provider. The runtime therefore only needs to import
:mod:`agent.providers` once at startup; thereafter
``agent.providers.registry.get_provider(name, config)`` is enough to
obtain a working provider instance.

Example
-------
>>> from agent.providers import list_providers, get_provider
>>> sorted(list_providers())  # doctest: +ELLIPSIS
['anthropic', 'deepseek', 'gemini', 'google', 'groq', 'mistral', 'ollama', 'openai', 'openrouter']
>>> p = get_provider("openai", {"api_key": "sk-..."})
>>> p.name
'openai'
"""

from __future__ import annotations

from typing import Any

# Base classes and registry primitives.
from agent.providers.base import BaseProvider
from agent.providers.registry import (
    PROVIDER_REGISTRY,
    get_provider,
    list_providers,
    register_provider,
    unregister_provider,
)

# Concrete provider classes (imports trigger ``register_provider``
# side-effects so the registry is populated as part of package
# import).
from agent.providers.openai_provider import OpenAIProvider
from agent.providers.anthropic_provider import AnthropicProvider
from agent.providers.google_provider import GoogleProvider
from agent.providers.groq_provider import GroqProvider
from agent.providers.mistral_provider import MistralProvider
from agent.providers.deepseek_provider import DeepSeekProvider
from agent.providers.openrouter_provider import OpenRouterProvider
from agent.providers.ollama_provider import OllamaProvider
from agent.providers.azure_provider import AzureProvider
from agent.providers.fireworks_provider import FireworksProvider
from agent.providers.together_provider import TogetherProvider
from agent.providers.bedrock_provider import BedrockProvider
from agent.providers.local_provider import LocalProvider


__all__ = [
    "BaseProvider",
    "PROVIDER_REGISTRY",
    "register_provider",
    "unregister_provider",
    "get_provider",
    "list_providers",
    # Concrete providers
    "OpenAIProvider",
    "AnthropicProvider",
    "GoogleProvider",
    "GroqProvider",
    "MistralProvider",
    "DeepSeekProvider",
    "OpenRouterProvider",
    "OllamaProvider",
    "AzureProvider",
    "FireworksProvider",
    "TogetherProvider",
    "BedrockProvider",
    "LocalProvider",
]


def build_provider(name: str, config: dict[str, Any] | None = None) -> BaseProvider | None:
    """Convenience wrapper around :func:`agent.providers.registry.get_provider`.

    Returns ``None`` when *name* is not registered so callers can fall
    back to other strategies (e.g. surfacing a configuration error to
    the user or trying a different provider).
    """
    return get_provider(name, config)


def available_providers() -> list[str]:
    """Return the names of providers whose :meth:`is_available` returns True."""
    available: list[str] = []
    for name in list_providers():
        instance = get_provider(name)
        if instance is not None and instance.is_available():
            available.append(name)
    return available
