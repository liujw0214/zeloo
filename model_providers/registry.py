"""Provider registry — discovery and lookup for model providers."""

from __future__ import annotations

import logging
from typing import Any

from model_providers.base import ProviderProfile

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, type[ProviderProfile]] = {}


def register_provider(name: str, cls: type[ProviderProfile]) -> None:
    """Register a provider class under *name*."""
    _REGISTRY[name.lower()] = cls
    logger.debug("Registered provider: %s", name)


def get_provider(name: str, **kwargs: Any) -> ProviderProfile | None:
    """Return an instance of the registered provider *name*, or None.

    Raises nothing — missing providers return None so callers can fall
    back to other strategies.
    """
    cls = _REGISTRY.get(name.lower())
    if cls is None:
        return None
    return cls(**kwargs)


def list_providers() -> list[str]:
    """Return the names of all registered providers."""
    return sorted(_REGISTRY.keys())


# Register built-in providers on import.
def _register_builtins() -> None:
    from model_providers.ai21 import AI21Provider
    from model_providers.ai_horde import AIHordeProvider
    from model_providers.amazon_bedrock import BedrockProvider
    from model_providers.anthropic import AnthropicProvider
    from model_providers.anyscale import AnyscaleProvider
    from model_providers.azure_openai import AzureOpenAIProvider
    from model_providers.cerebras import CerebrasProvider
    from model_providers.cloudflare import CloudflareProvider
    from model_providers.cohere import CohereProvider
    from model_providers.cohere_platform import CoherePlatformProvider
    from model_providers.copilot import GitHubCopilotProvider
    from model_providers.deepinfra import DeepInfraProvider
    from model_providers.deepseek import DeepSeekProvider
    from model_providers.deepseek_coder import DeepSeekCoderProvider
    from model_providers.deepseek_r1 import DeepSeekR1Provider
    from model_providers.featherless import FeatherlessProvider
    from model_providers.fireworks import FireworksProvider
    from model_providers.fireworks_inference import MistralNemoProvider
    from model_providers.gemini import GeminiProvider
    from model_providers.groq import GroqProvider
    from model_providers.groq_cloud import CohereCommandProvider
    from model_providers.huggingface import HuggingFaceProvider
    from model_providers.hyperbolic import HyperbolicProvider
    from model_providers.lepton import LeptonProvider
    from model_providers.localai import LocalAIProvider
    from model_providers.mistral import MistralProvider
    from model_providers.mistral_large import MistralLargeProvider
    from model_providers.monsterapi import MonsterAPIProvider
    from model_providers.novita import NovitaProvider
    from model_providers.ollama import OllamaProvider
    from model_providers.openai import OpenAIProvider
    from model_providers.openrouter import OpenRouterProvider
    from model_providers.perplexity_sonar import PerplexitySonarProvider
    from model_providers.portkey import PortkeyProvider
    from model_providers.qwen import QwenProvider
    from model_providers.replicate import ReplicateProvider
    from model_providers.samba import SambaNovaProvider
    from model_providers.together import TogetherProvider
    from model_providers.vllm import VLLMProvider
    from model_providers.watsonx import WatsonxProvider
    from model_providers.xai import XAIProvider
    from model_providers.zhipu import ZhipuProvider

    register_provider("deepseek", DeepSeekProvider)
    register_provider("gemini", GeminiProvider)
    register_provider("openrouter", OpenRouterProvider)
    register_provider("anthropic", AnthropicProvider)
    register_provider("xai", XAIProvider)
    register_provider("zhipu", ZhipuProvider)
    register_provider("huggingface", HuggingFaceProvider)
    register_provider("fireworks", FireworksProvider)
    register_provider("groq", GroqProvider)
    register_provider("cohere", CohereProvider)
    register_provider("mistral", MistralProvider)
    register_provider("azure_openai", AzureOpenAIProvider)
    register_provider("openai", OpenAIProvider)
    register_provider("together", TogetherProvider)
    register_provider("replicate", ReplicateProvider)
    register_provider("hyperbolic", HyperbolicProvider)
    register_provider("novita", NovitaProvider)
    register_provider("lepton", LeptonProvider)
    register_provider("cloudflare", CloudflareProvider)
    register_provider("deepinfra", DeepInfraProvider)
    register_provider("perplexity", PerplexitySonarProvider)
    register_provider("deepseek-r1", DeepSeekR1Provider)
    register_provider("cerebras", CerebrasProvider)
    register_provider("ollama", OllamaProvider)
    register_provider("ai21", AI21Provider)
    register_provider("localai", LocalAIProvider)
    register_provider("vllm", VLLMProvider)
    register_provider("anyscale", AnyscaleProvider)
    register_provider("featherless", FeatherlessProvider)
    register_provider("monsterapi", MonsterAPIProvider)
    register_provider("cohere-command", CohereCommandProvider)
    register_provider("mistral-nemo", MistralNemoProvider)
    register_provider("ai-horde", AIHordeProvider)
    register_provider("deepseek-coder", DeepSeekCoderProvider)
    register_provider("qwen", QwenProvider)
    register_provider("bedrock", BedrockProvider)
    register_provider("cohere-platform", CoherePlatformProvider)
    register_provider("copilot", GitHubCopilotProvider)
    register_provider("mistral-large", MistralLargeProvider)
    register_provider("portkey", PortkeyProvider)
    register_provider("sambanova", SambaNovaProvider)
    register_provider("watsonx", WatsonxProvider)


_register_builtins()
