"""Model provider plug-in package.

Provides the :class:`ProviderProfile` abstract base class alongside
concrete implementations for popular LLM providers (DeepSeek, Gemini,
etc.). Each provider wraps an HTTP-compatible chat completion endpoint
and exposes a uniform interface for credential validation, cost
estimation, and completion calls.
"""

from __future__ import annotations

from model_providers.ai21 import AI21Provider
from model_providers.ai_horde import AIHordeProvider
from model_providers.anthropic import AnthropicProvider
from model_providers.anyscale import AnyscaleProvider
from model_providers.azure_openai import AzureOpenAIProvider
from model_providers.base import (
    ChatResponse,
    ProviderProfile,
)
from model_providers.cerebras import CerebrasProvider
from model_providers.cloudflare import CloudflareProvider
from model_providers.cohere import CohereProvider
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
from model_providers.monsterapi import MonsterAPIProvider
from model_providers.novita import NovitaProvider
from model_providers.openai import OpenAIProvider
from model_providers.openrouter import OpenRouterProvider
from model_providers.perplexity_sonar import PerplexitySonarProvider
from model_providers.qwen import QwenProvider
from model_providers.registry import (
    get_provider,
    list_providers,
    register_provider,
)
from model_providers.replicate import ReplicateProvider
from model_providers.together import TogetherProvider
from model_providers.vllm import VLLMProvider
from model_providers.xai import XAIProvider
from model_providers.zhipu import ZhipuProvider

__all__ = [
    "ChatResponse",
    "ProviderProfile",
    "DeepSeekProvider",
    "GeminiProvider",
    "OpenRouterProvider",
    "AnthropicProvider",
    "XAIProvider",
    "ZhipuProvider",
    "HuggingFaceProvider",
    "FireworksProvider",
    "GroqProvider",
    "CohereProvider",
    "MistralProvider",
    "AzureOpenAIProvider",
    "OpenAIProvider",
    "TogetherProvider",
    "ReplicateProvider",
    "HyperbolicProvider",
    "NovitaProvider",
    "LeptonProvider",
    "CloudflareProvider",
    "DeepInfraProvider",
    "PerplexitySonarProvider",
    "DeepSeekR1Provider",
    "CerebrasProvider",
    "OllamaProvider",
    "AI21Provider",
    "LocalAIProvider",
    "VLLMProvider",
    "AnyscaleProvider",
    "FeatherlessProvider",
    "MonsterAPIProvider",
    "CohereCommandProvider",
    "GitHubCopilotProvider",
    "MistralNemoProvider",
    "AIHordeProvider",
    "DeepSeekCoderProvider",
    "QwenProvider",
    "get_provider",
    "list_providers",
    "register_provider",
]
