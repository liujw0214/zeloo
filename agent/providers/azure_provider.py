"""Azure OpenAI Service provider.

Uses Azure-specific endpoint format and API version headers.
Supports GPT-4o, GPT-4 Turbo, and other Azure OpenAI models through
the Azure OpenAI API endpoint format with deployment names instead
of model names.

Configuration keys (in ``config`` dict):

* ``azure_endpoint`` (str) — Azure OpenAI endpoint URL, e.g.
  ``https://my-resource.openai.azure.com``. Falls back to
  ``AZURE_OPENAI_ENDPOINT``.
* ``azure_deployment`` (str) — Deployment name, e.g. ``gpt-4o``.
  Falls back to ``AZURE_OPENAI_DEPLOYMENT``.
* ``api_version`` (str) — API version string, e.g. ``2024-06-01``.
  Defaults to ``2024-06-01``.
* ``api_key`` (str) — Azure OpenAI API key. Falls back to
  ``AZURE_OPENAI_API_KEY``. Can also use ``azure_ad_token`` for
  Microsoft Entra ID (Bearer token) authentication.
* ``azure_ad_token`` (str) — Microsoft Entra ID Bearer token.
  Falls back to ``AZURE_OPENAI_AD_TOKEN``.
* ``default_model`` (str) — Defaults to ``gpt-4o``.
* ``timeout`` (float) — Request timeout in seconds.

The provider registers itself as ``"azure"`` on import.
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


_DEFAULT_API_VERSION = "2024-06-01"
_DEFAULT_MODEL = "gpt-4o"
_KEY_ENVS: tuple[tuple[str, str], ...] = (
    ("azure_endpoint", "AZURE_OPENAI_ENDPOINT"),
    ("azure_deployment", "AZURE_OPENAI_DEPLOYMENT"),
    ("api_key", "AZURE_OPENAI_API_KEY"),
    ("azure_ad_token", "AZURE_OPENAI_AD_TOKEN"),
)

_O1_REASONING_PREFIXES: tuple[str, ...] = ("o1-", "o1", "o3-", "o3", "o4-")


class AzureProvider(BaseProvider):
    """Azure OpenAI Service provider.

    Communicates with Azure OpenAI endpoints using the deployment-name
    format and API version query parameter. Supports both API key and
    Microsoft Entra ID (Azure AD) authentication.
    """

    name = "azure"
    default_model = _DEFAULT_MODEL
    supports_vision = True
    supports_function_calling = True
    supports_streaming = True

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        for config_key, env_name in _KEY_ENVS:
            if not self.config.get(config_key):
                env_val = os.environ.get(env_name, "")
                if env_val:
                    self.config[config_key] = env_val
        if not self.config.get("api_version"):
            self.config["api_version"] = _DEFAULT_API_VERSION
        if not self.default_model:
            self.config["default_model"] = _DEFAULT_MODEL

    @property
    def azure_endpoint(self) -> str:
        return str(self.config.get("azure_endpoint") or "")

    @property
    def azure_deployment(self) -> str:
        return str(self.config.get("azure_deployment") or "")

    @property
    def api_version(self) -> str:
        return str(self.config.get("api_version") or _DEFAULT_API_VERSION)

    @property
    def azure_ad_token(self) -> str:
        return str(self.config.get("azure_ad_token") or "")

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.azure_ad_token:
            headers["Authorization"] = f"Bearer {self.azure_ad_token}"
        elif self.api_key:
            headers["api-key"] = self.api_key
        return headers

    def _build_url(self, path: str = "/chat/completions") -> str:
        base = self.azure_endpoint.rstrip("/")
        deployment = self.azure_deployment
        version = self.api_version
        return f"{base}/openai/deployments/{deployment}{path}?api-version={version}"

    def _is_reasoning_model(self, model: str) -> bool:
        m = (model or "").lower()
        return any(m.startswith(prefix) for prefix in _O1_REASONING_PREFIXES)

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if not self.azure_endpoint:
            return build_error_response(
                provider=self.name,
                error="Azure endpoint not configured (set azure_endpoint or AZURE_OPENAI_ENDPOINT)",
                status=400,
            )
        if not self.azure_deployment:
            return build_error_response(
                provider=self.name,
                error="Azure deployment not configured (set azure_deployment or AZURE_OPENAI_DEPLOYMENT)",
                status=400,
            )
        if not self.api_key and not self.azure_ad_token:
            return build_error_response(
                provider=self.name,
                error="Azure API key or Azure AD token not configured",
                status=401,
            )

        target_model = model or self.default_model
        payload: dict[str, Any] = {
            "messages": messages,
        }
        if self._is_reasoning_model(target_model):
            payload["max_completion_tokens"] = int(max_tokens)
        else:
            payload["temperature"] = float(temperature)
            payload["max_tokens"] = int(max_tokens)

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

        url = self._build_url("/chat/completions")
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
        fallback = [
            "gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4",
            "gpt-4-32k", "gpt-35-turbo", "gpt-35-turbo-16k",
        ]
        if not self.azure_endpoint or not self.azure_deployment:
            return fallback
        try:
            url = self._build_url("/models")
            result = sync_get_json(
                url,
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
        if not self.azure_endpoint or not self.azure_deployment:
            return False
        if not self.api_key and not self.azure_ad_token:
            return False
        try:
            url = self._build_url("/models")
            result = sync_get_json(
                url,
                headers=self._headers(),
                timeout=min(self.timeout, 5.0),
            )
            return bool(result.get("ok"))
        except Exception:
            return False


register_provider("azure", AzureProvider)


__all__ = ["AzureProvider"]
