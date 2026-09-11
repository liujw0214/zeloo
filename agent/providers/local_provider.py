"""Local model provider (LM Studio, Ollama API-compatible, TextGen WebUI).

Wraps any OpenAI-compatible local server including LM Studio, Ollama
(with OpenAI compatibility layer), TextGen WebUI, Jan, and other
local inference servers that expose an OpenAI-compatible API.

Configuration keys (in ``config`` dict):

* ``base_url`` (str) — Base URL of the local server. Defaults to
  ``http://localhost:1234/v1``. Falls back to ``LOCAL_PROVIDER_BASE_URL``.
* ``api_key`` (str) — API key for authentication. Most local servers
  do not require an API key (can be empty string). Falls back to
  ``LOCAL_PROVIDER_API_KEY``.
* ``default_model`` (str) — Default model identifier. Falls back to
  ``LOCAL_PROVIDER_DEFAULT_MODEL``. If not set, will attempt to
  auto-detect from the server.
* ``timeout`` (float) — Request timeout in seconds. Defaults to 120s
  for local servers which may be slower than cloud APIs.

The provider registers itself as ``"local"`` on import.

Note: Local servers typically don't require API keys, but some (like
LM Studio with authentication enabled) may need one. Set ``api_key``
to an empty string if no authentication is required.
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


_DEFAULT_BASE_URL = "http://localhost:1234/v1"
_DEFAULT_TIMEOUT = 120.0
_KEY_ENVS: tuple[tuple[str, str], ...] = (
    ("base_url", "LOCAL_PROVIDER_BASE_URL"),
    ("api_key", "LOCAL_PROVIDER_API_KEY"),
    ("default_model", "LOCAL_PROVIDER_DEFAULT_MODEL"),
)

_KNOWN_LOCAL_PRESETS: tuple[str, ...] = (
    "llama-3.1-8b",
    "llama-3.1-70b",
    "llama-3-8b",
    "llama-3-70b",
    "llama-2-7b",
    "llama-2-13b",
    "llama-2-70b",
    "mistral-7b",
    "mixtral-8x7b",
    "mixtral-8x22b",
    "codellama-7b",
    "codellama-13b",
    "codellama-34b",
    "qwen2-7b",
    "qwen2-72b",
    "phi-3-mini",
    "phi-3-medium",
    "gemma-2-9b",
    "gemma-2-27b",
    "deepseek-coder-6.7b",
    "deepseek-coder-33b",
    "wizardcoder-7b",
    "wizardcoder-13b",
    "wizardcoder-34b",
)


class LocalProvider(BaseProvider):
    """Local/OpenAI-compatible model provider.

    Provides a unified interface for connecting to local inference
    servers that expose an OpenAI-compatible API. Compatible with:

    * LM Studio
    * Ollama (with OpenAI compatibility layer enabled)
    * TextGen WebUI (extras/openai)
    * Jan
    * LocalAI
    * oobabooga's text-generation-webui
    * And any other server implementing the OpenAI Chat Completions API

    Local servers typically don't require API keys, but the option
    is provided for servers that have authentication enabled.
    """

    name = "local"
    default_model = ""
    base_url = _DEFAULT_BASE_URL
    supports_vision = False
    supports_function_calling = True
    supports_streaming = True

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        for config_key, env_name in _KEY_ENVS:
            if not self.config.get(config_key):
                env_val = os.environ.get(env_name, "")
                if env_val:
                    self.config[config_key] = env_val
        if not self.base_url:
            self.config["base_url"] = _DEFAULT_BASE_URL
        if self.timeout == 60.0:
            self.config["timeout"] = _DEFAULT_TIMEOUT

    @property
    def timeout(self) -> float:
        try:
            return float(self.config.get("timeout", _DEFAULT_TIMEOUT))
        except (TypeError, ValueError):
            return _DEFAULT_TIMEOUT

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not self.base_url:
            return build_error_response(
                provider=self.name,
                error="Local server URL not configured (set base_url or LOCAL_PROVIDER_BASE_URL)",
                status=400,
            )

        target_model = model or self.default_model
        if not target_model:
            return build_error_response(
                provider=self.name,
                error="Model not specified and no default_model configured",
                status=400,
            )

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
        fallback = list(_KNOWN_LOCAL_PRESETS)
        if not self.base_url:
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
            if ids:
                return ids
            return fallback
        except Exception:
            return fallback

    def is_available(self) -> bool:
        if not self.base_url:
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

    def detect_model(self) -> str | None:
        try:
            result = sync_get_json(
                f"{self.base_url.rstrip('/')}/models",
                headers=self._headers(),
                timeout=min(self.timeout, 10.0),
            )
            if result.get("ok"):
                data = result.get("data", {})
                models = data.get("data", []) if isinstance(data, dict) else []
                if models and isinstance(models[0], dict):
                    return str(models[0].get("id", ""))
        except Exception:
            pass
        return None


register_provider("local", LocalProvider)


__all__ = ["LocalProvider"]
