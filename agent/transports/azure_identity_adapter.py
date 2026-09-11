"""Azure OpenAI transport adapter (with Entra ID / managed identity support)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from agent.transports.base import (
    AuthenticationError,
    RateLimitError,
    Response,
    TransportAdapter,
    TransportError,
)

logger = logging.getLogger(__name__)


class AzureIdentityAdapter(TransportAdapter):
    """Transport adapter for Azure OpenAI with Entra ID (Azure AD) authentication.

    Supports both API key auth and Entra ID / managed identity token auth.
    """

    name = "azure"
    supports_streaming = True
    supports_vision = True
    supports_tools = True
    max_context_tokens = 128000

    def __init__(
        self,
        endpoint: str,
        api_key: str | None = None,
        azure_ad_token: str | None = None,
        api_version: str = "2024-06-01",
        deployment_name: str | None = None,
        timeout: float = 60.0,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.azure_ad_token = azure_ad_token
        self.api_version = api_version
        self.deployment_name = deployment_name
        self.timeout = timeout

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> Response:
        deployment = model or self.deployment_name or "gpt-4o"
        payload = self._build_payload(messages, tools, **kwargs)
        try:
            raw = self._post(deployment, payload, stream=stream)
            return self._parse_response(raw, deployment)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise AuthenticationError("Invalid Azure credentials or Entra ID token") from e
            if e.response.status_code == 429:
                raise RateLimitError("Azure rate limit exceeded") from e
            raise TransportError(f"Azure OpenAI API error: {e}") from e

    def validate_credentials(self) -> bool:
        try:
            if self.azure_ad_token:
                return self._validate_ad_token()
            if self.api_key:
                return self._validate_api_key()
            return False
        except Exception as e:
            logger.warning("Azure credential validation failed: %s", e)
            return False

    def get_default_model(self) -> str:
        return self.deployment_name or "gpt-4o"

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "messages": list(messages),
            "temperature": kwargs.get("temperature", 0.0),
            "max_tokens": kwargs.get("max_tokens", 4096),
        }
        if tools:
            payload["tools"] = tools
            if kwargs.get("tool_choice"):
                payload["tool_choice"] = kwargs["tool_choice"]
        return payload

    def _parse_response(self, raw: dict[str, Any], model: str) -> Response:
        choice = raw.get("choices", [{}])[0]
        content = choice.get("message", {}).get("content", "")
        finish_reason = choice.get("finish_reason", "")
        tool_calls = choice.get("message", {}).get("tool_calls", [])

        usage = raw.get("usage", {})
        return Response(
            content=content,
            raw=raw,
            model=model,
            finish_reason=finish_reason,
            usage_in=usage.get("prompt_tokens", 0),
            usage_out=usage.get("completion_tokens", 0),
            tool_calls=tool_calls,
        )

    def _post(
        self,
        deployment: str,
        payload: dict[str, Any],
        stream: bool = False,
    ) -> dict[str, Any]:
        url = (
            f"{self.endpoint}/openai/deployments/{deployment}"
            f"/chat/completions?api-version={self.api_version}"
        )
        headers: dict[str, str] = {
            "content-type": "application/json",
        }
        if self.api_key:
            headers["api-key"] = self.api_key
        elif self.azure_ad_token:
            headers["Authorization"] = f"Bearer {self.azure_ad_token}"

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()

    def _validate_api_key(self) -> bool:
        try:
            url = (
                f"{self.endpoint}/openai/deployments/"
                f"{self.deployment_name or 'gpt-4o'}"
                f"/chat/completions?api-version={self.api_version}"
            )
            headers: dict[str, str] = {"api-key": self.api_key or ""}
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    url,
                    json={"messages": [{"role": "user", "content": "ping"}], "max_tokens": 1},
                    headers=headers,
                )
                return resp.status_code < 500
        except Exception:
            return False

    def _validate_ad_token(self) -> bool:
        return bool(self.azure_ad_token) and len(self.azure_ad_token) > 10
