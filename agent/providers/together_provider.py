"""Together AI provider.

Aggregated inference platform with open models.
Together AI provides access to a wide range of open-source and
proprietary models through an OpenAI-compatible API.

Configuration keys (in ``config`` dict):

* ``api_key`` (str) — Together AI API key. Falls back to ``TOGETHER_API_KEY``.
* ``base_url`` (str) — API base URL. Defaults to
  ``https://api.together.xyz/v1``.
* ``default_model`` (str) — Defaults to ``meta-llama/Llama-3-8b-chat-hf``.
* ``timeout`` (float) — Request timeout in seconds.

The provider registers itself as ``"together"`` on import.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from agent.providers._http import (
    async_post_json,
    build_error_response,
    build_success_response,
    sync_get_json,
)
from agent.providers.base import BaseProvider
from agent.providers.registry import register_provider

logger = logging.getLogger(__name__)


_DEFAULT_BASE_URL = "https://api.together.xyz/v1"
_DEFAULT_MODEL = "meta-llama/Llama-3-8b-chat-hf"
_KEY_ENV = "TOGETHER_API_KEY"

_KNOWN_TOGETHER_MODELS: tuple[str, ...] = (
    "meta-llama/Llama-3-8b-chat-hf",
    "meta-llama/Llama-3-70b-chat-hf",
    "meta-llama/Llama-3-8b-instruct",
    "meta-llama/Llama-3-70b-instruct",
    "meta-llama/Llama-3.1-8b-instruct",
    "meta-llama/Llama-3.1-70b-instruct",
    "meta-llama/Llama-3.1-405b-instruct",
    "mistralai/Mixtral-8x7B-Instruct-v0.1",
    "mistralai/Mixtral-8x22B-Instruct-v0.1",
    "mistralai/Mistral-7B-Instruct-v0.3",
    "Qwen/Qwen2-72B-Instruct",
    "Qwen/Qwen2-7B-Instruct",
    "Qwen/Qwen2.5-72B-Instruct",
    "Qwen/Qwen2.5-7B-Instruct",
    "deepseek-ai/DeepSeek-V3",
    "deepseek-ai/DeepSeek-Coder-V2",
    "google/gemma-2-27b-it",
    "google/gemma-2-9b-it",
    "NousResearch/Nous-Hermes-2-Mistral-8x7B-DPO",
    " NousResearch/Nous-Hermes-2-Yi-34B",
    "WizardLM/WizardLM-2-8x22B",
    "WizardLM/WizardLM-2-7B",
    "allenai/OLMo-7B-Instruct",
    "togethercomputer/alpaca-7b",
    "togethercomputer/llama-2-7b-chat",
    "togethercomputer/llama-2-70b-chat",
)


class TogetherProvider(BaseProvider):
    """Together AI provider.

    Provides access to aggregated inference with open models through
    the Together AI API. Uses OpenAI-compatible endpoints.
    """

    name = "together"
    default_model = _DEFAULT_MODEL
    base_url = _DEFAULT_BASE_URL
    supports_vision = False
    supports_function_calling = True
    supports_streaming = True

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        if not self.api_key:
            self.config["api_key"] = os.environ.get(_KEY_ENV, "")
        if not self.base_url:
            self.config["base_url"] = _DEFAULT_BASE_URL
        if not self.default_model:
            self.config["default_model"] = _DEFAULT_MODEL

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not self.api_key:
            return build_error_response(
                provider=self.name,
                error="Together AI API key not configured (set TOGETHER_API_KEY)",
                status=401,
            )

        target_model = model or self.default_model
        payload: dict[str, Any] = {
            "model": target_model,
            "messages": messages,
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
        }

        passthrough_keys = (
            "tools",
            "tool_choice",
            "response_format",
            "top_p",
            "frequency_penalty",
            "presence_penalty",
            "stop",
            "user",
            "seed",
            "n",
            "parallel_tool_calls",
        )
        for key in passthrough_keys:
            if key in kwargs and kwargs[key] is not None:
                payload[key] = kwargs[key]

        if stream:
            payload["stream"] = True

        url = f"{self.base_url.rstrip('/')}/chat/completions"
        result = await async_post_json(
            url,
            headers=self._headers(),
            json_payload=payload,
            timeout=self.timeout,
        )

        if not result.get("ok"):
            return build_error_response(
                provider=self.name,
                error=str(result.get("error", "unknown error")),
                status=int(result.get("status", 0)),
                raw=result.get("raw"),
            )

        body: dict[str, Any] = result.get("data", {})
        choice = (body.get("choices") or [{}])[0]
        message = choice.get("message", {}) if isinstance(choice, dict) else {}
        usage = body.get("usage", {}) or {}

        tool_calls = message.get("tool_calls") or []
        return build_success_response(
            provider=self.name,
            content=str(message.get("content") or ""),
            model=body.get("model", target_model),
            finish_reason=str(choice.get("finish_reason", "stop") if isinstance(choice, dict) else "stop"),
            usage={
                "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
                "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
                "total_tokens": int(usage.get("total_tokens", 0) or 0),
            },
            raw=body,
            tool_calls=tool_calls if isinstance(tool_calls, list) else [],
        )

    def list_models(self) -> list[str]:
        fallback = list(_KNOWN_TOGETHER_MODELS)
        if not self.api_key:
            return fallback
        try:
            result = sync_get_json(
                f"{self.base_url.rstrip('/')}/models",
                headers=self._headers(),
                timeout=min(self.timeout, 10.0),
            )
            if not result.get("ok"):
                return fallback
            data = result.get("data", {})
            models = data.get("data", []) if isinstance(data, dict) else []
            ids = sorted(
                m.get("id") for m in models if isinstance(m, dict) and m.get("id")
            )
            return ids or fallback
        except Exception:
            return fallback

    def is_available(self) -> bool:
        if not self.api_key:
            return False
        try:
            result = sync_get_json(
                f"{self.base_url.rstrip('/')}/models",
                headers=self._headers(),
                timeout=min(self.timeout, 5.0),
            )
            return bool(result.get("ok"))
        except Exception:
            return False


register_provider("together", TogetherProvider)


__all__ = ["TogetherProvider"]
