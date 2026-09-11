"""Cloudflare Workers AI provider — edge inference."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from model_providers.base import ChatResponse, ProviderProfile


@dataclass
class CloudflareProvider(ProviderProfile):
    """Cloudflare Workers AI provider.

    Provides fast edge inference using Cloudflare's global network.
    OpenAI-compatible API for @cf models.
    """

    name: str = "cloudflare"
    base_url: str = "https://api.cloudflare.com/client/v4/accounts"
    default_model: str = "@cf/meta/llama-3.1-70b-instruct"
    supports_vision: bool = False
    supports_function_calling: bool = False
    supports_streaming: bool = True

    MODELS = {
        "@cf/meta/llama-3.1-70b-instruct": "@cf/meta/llama-3.1-70b-instruct",
        "@cf/meta/llama-3.1-8b-instruct": "@cf/meta/llama-3.1-8b-instruct",
        "@cf/mistralai/mistral-7b-instruct-v0.2": "@cf/mistralai/mistral-7b-instruct-v0.2",
        "@cf/qwen/qwen2.5-72b-instruct-varsome": "@cf/qwen/qwen2.5-72b-instruct-varsome",
        "@cf/codellama/codellama-7b-instruct": "@cf/codellama/codellama-7b-instruct",
    }

    def __post_init__(self) -> None:
        account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
        if account_id:
            self.base_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai"

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        api_token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
        account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
        if not api_token or not account_id:
            raise ValueError(
                "CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID "
                "environment variables must be set"
            )

        model = model or self.default_model
        if not model.startswith("@cf/"):
            model = f"@cf/{model}"

        endpoint = f"{self.base_url}/v1/chat/completions"

        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
        }
        if kwargs.get("temperature"):
            body["temperature"] = kwargs["temperature"]
        if kwargs.get("max_tokens"):
            body["max_tokens"] = kwargs["max_tokens"]
        if kwargs.get("stream"):
            body["stream"] = True

        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=120.0) as client:
            response = client.post(endpoint, json=body, headers=headers)
            response.raise_for_status()
            data = response.json()

        return ChatResponse(
            content=data["choices"][0]["message"]["content"],
            model=data.get("model", model),
            provider=self.name,
            usage={
                "prompt_tokens": data.get("usage", {}).get("prompt_tokens", 0),
                "completion_tokens": data.get("usage", {}).get("completion_tokens", 0),
                "total_tokens": data.get("usage", {}).get("total_tokens", 0),
            },
            raw=data,
        )

    def validate_credentials(self) -> bool:
        api_token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
        account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
        if not api_token or not account_id:
            return False
        headers = {"Authorization": f"Bearer {api_token}"}
        try:
            with httpx.Client(timeout=10.0) as client:
                url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/models"
                resp = client.get(url, headers=headers)
                return resp.status_code == 200
        except Exception:
            return False

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return 0.0
