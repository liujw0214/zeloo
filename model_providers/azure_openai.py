"""Azure OpenAI model provider — enterprise deployment with OpenAI-compatible API."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from model_providers.base import ChatResponse, ProviderProfile

logger = logging.getLogger(__name__)


class AzureOpenAIProvider(ProviderProfile):
    """Azure OpenAI Service provider (OpenAI-compatible API).

    Supports GPT-4o, GPT-4 Turbo, GPT-4, and GPT-3.5 Turbo deployments.
    Requires environment variables:
      AZURE_OPENAI_ENDPOINT   (e.g. https://<resource>.openai.azure.com)
      AZURE_OPENAI_API_KEY   (or Azure AD token via AZURE_OPENAI_TOKEN)
      AZURE_OPENAI_DEPLOYMENT (deployment name, e.g. gpt-4o)
      AZURE_OPENAI_API_VERSION (e.g. 2024-06-01)
    """

    name = "azure_openai"
    default_model = "gpt-4o"
    supports_vision = True
    supports_function_calling = True
    supports_streaming = True

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(api_key or os.environ.get("AZURE_OPENAI_API_KEY", ""), **kwargs)
        self.endpoint = os.environ.get(
            "AZURE_OPENAI_ENDPOINT",
            "https://<resource>.openai.azure.com",
        ).rstrip("/")
        self.deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
        self.api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-06-01")
        self.token = os.environ.get("AZURE_OPENAI_TOKEN")

    @property
    def base_url(self) -> str:
        return (
            f"{self.endpoint}/openai/deployments/{self.deployment}"
            f"/chat/completions?api-version={self.api_version}"
        )

    def _auth_headers(self) -> dict[str, str]:
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {"api-key": self.api_key or ""}

    def validate_credentials(self) -> bool:
        if not self.api_key and not self.token:
            return False
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(
                    f"{self.endpoint}/openai/deployments?api-version={self.api_version}",
                    headers=self._auth_headers(),
                )
                return resp.status_code < 500
        except httpx.RequestError:
            return False

    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str) -> float:
        rates = {
            "gpt-4o": (2.50, 10.00),
            "gpt-4-turbo": (10.00, 30.00),
            "gpt-4": (30.00, 60.00),
            "gpt-3.5-turbo": (0.50, 1.50),
        }
        r = rates.get(model, (5.00, 15.00))
        return input_tokens * r[0] / 1_000_000 + output_tokens * r[1] / 1_000_000

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        if not self.api_key and not self.token:
            raise RuntimeError(
                "Azure OpenAI credentials not set. Set AZURE_OPENAI_API_KEY "
                "or AZURE_OPENAI_TOKEN."
            )
        target_model = model or self.deployment
        payload: dict[str, Any] = {
            "messages": messages,
        }
        for key in ("temperature", "max_tokens", "top_p", "stop"):
            if key in kwargs:
                payload[key] = kwargs[key]

        tools = kwargs.get("tools")
        if tools:
            payload["tools"] = tools

        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                self.base_url,
                headers={
                    **self._auth_headers(),
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]
        msg = choice.get("message", {})
        usage = data.get("usage", {})
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))

        return ChatResponse(
            content=msg.get("content", "") or "",
            model=target_model,
            provider=self.name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            raw=data,
            finish_reason=choice.get("finish_reason", "stop"),
            cost_usd=self.estimate_cost(prompt_tokens, completion_tokens, target_model),
            tool_calls=msg.get("tool_calls"),
        )
