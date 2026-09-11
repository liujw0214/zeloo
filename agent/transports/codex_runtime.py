"""OpenAI Codex runtime transport adapter."""

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

CODEX_BASE_URL = "https://api.openai.com"


class CodexRuntime(TransportAdapter):
    """Transport adapter for OpenAI Codex (chat/completions endpoint).

    Codex uses the same API as OpenAI chat completions but with
    code-specialized models (gpt-4o, gpt-4o-mini, etc.).
    """

    name = "codex"
    supports_streaming = True
    supports_vision = False
    supports_tools = True
    max_context_tokens = 128000

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        organization: str | None = None,
        timeout: float = 60.0,
    ):
        self.api_key = api_key
        self.base_url = base_url or CODEX_BASE_URL
        self.organization = organization
        self.timeout = timeout

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str = "gpt-4o",
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> Response:
        payload = self._build_payload(messages, model, tools, **kwargs)
        try:
            raw = self._post("/v1/chat/completions", payload, stream=stream)
            return self._parse_response(raw, model)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise AuthenticationError("Invalid OpenAI API key") from e
            if e.response.status_code == 429:
                raise RateLimitError("OpenAI rate limit exceeded") from e
            raise TransportError(f"OpenAI API error: {e}") from e

    def validate_credentials(self) -> bool:
        try:
            payload = {
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            }
            self._post("/v1/chat/completions", payload, stream=False)
            return True
        except Exception as e:
            logger.warning("Codex credential validation failed: %s", e)
            return False

    def get_default_model(self) -> str:
        return "gpt-4o"

    def supports_feature(self, feature: str) -> bool:
        if feature == "json_mode":
            return True
        return super().supports_feature(feature)

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": list(messages),
            "temperature": kwargs.get("temperature", 0.0),
            "max_tokens": kwargs.get("max_tokens", 4096),
        }
        if tools:
            payload["tools"] = tools
        if kwargs.get("response_format"):
            payload["response_format"] = kwargs["response_format"]
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
        path: str,
        payload: dict[str, Any],
        stream: bool = False,
    ) -> dict[str, Any]:
        headers: dict[str, str] = {
            "Authorization": f"Bearer {self.api_key}",
            "content-type": "application/json",
        }
        if self.organization:
            headers["OpenAI-Organization"] = self.organization
        url = f"{self.base_url.rstrip('/')}{path}"
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()
