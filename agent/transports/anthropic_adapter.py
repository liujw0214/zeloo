"""Anthropic Claude API transport adapter."""

from __future__ import annotations

import json
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

ANTHROPIC_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"


class AnthropicAdapter(TransportAdapter):
    """Transport adapter for Anthropic Claude API.

    Handles message format conversion (OpenAI -> Anthropic) and
    response parsing (Anthropic -> standardized Response).
    """

    name = "anthropic"
    supports_streaming = True
    supports_vision = True
    supports_tools = True
    max_context_tokens = 200000

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        max_retries: int = 3,
        timeout: float = 60.0,
    ):
        self.api_key = api_key
        self.base_url = base_url or ANTHROPIC_BASE_URL
        self.max_retries = max_retries
        self.timeout = timeout

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str = "claude-3-5-sonnet-20241022",
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> Response:
        """Send a chat completion request to Anthropic API."""
        payload = self._build_payload(messages, model, tools, **kwargs)
        try:
            raw = self._post("/v1/messages", payload, stream=stream)
            return self._parse_response(raw, model)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise AuthenticationError("Invalid Anthropic API key") from e
            if e.response.status_code == 429:
                raise RateLimitError("Anthropic rate limit exceeded") from e
            raise TransportError(f"Anthropic API error: {e}") from e

    def validate_credentials(self) -> bool:
        """Validate the API key by making a lightweight request."""
        try:
            payload = {
                "model": "claude-3-5-haiku-20241022",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "ping"}],
            }
            self._post("/v1/messages", payload, stream=False)
            return True
        except Exception as e:
            logger.warning("Anthropic credential validation failed: %s", e)
            return False

    def get_default_model(self) -> str:
        return "claude-3-5-sonnet-20241022"

    def supports_feature(self, feature: str) -> bool:
        if feature == "vision":
            return True
        if feature == "tools":
            return True
        if feature == "streaming":
            return True
        return False

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": self._convert_messages(messages),
            "max_tokens": kwargs.get("max_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.0),
        }
        if tools:
            payload["tools"] = self._convert_tools(tools)
        if kwargs.get("system"):
            system_msg = {"role": "user", "content": f"System: {kwargs['system']}"}
            payload["messages"] = [system_msg] + payload["messages"]
        return payload

    def _convert_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                converted.append({"role": "user", "content": f"[System]\n{content}"})
            elif role == "tool":
                converted.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", ""),
                        "content": content,
                    }],
                })
            elif role == "assistant":
                tool_calls = msg.get("tool_calls", [])
                if tool_calls:
                    content_parts = [{"type": "text", "text": content}] if content else []
                    for tc in tool_calls:
                        content_parts.append({
                            "type": "tool_use",
                            "id": tc.get("id", ""),
                            "name": tc.get("function", {}).get("name", ""),
                            "input": tc.get("function", {}).get("arguments", {}),
                        })
                    converted.append({"role": "assistant", "content": content_parts})
                else:
                    converted.append({"role": "assistant", "content": content or ""})
            else:
                converted.append({"role": role, "content": content})
        return converted

    def _convert_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        anthropic_tools = []
        for tool in tools:
            func = tool.get("function", {})
            anthropic_tools.append({
                "name": func.get("name", tool.get("name", "")),
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
            })
        return anthropic_tools

    def _parse_response(self, raw: dict[str, Any], model: str) -> Response:
        content = ""
        tool_calls: list[dict[str, Any]] = []
        finish_reason = raw.get("stop_reason", "")

        for block in raw.get("content", []):
            if block.get("type") == "text":
                content += block.get("text", "")
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {})),
                    },
                })

        usage = raw.get("usage", {})
        return Response(
            content=content,
            raw=raw,
            model=model,
            finish_reason=finish_reason,
            usage_in=usage.get("input_tokens", 0),
            usage_out=usage.get("output_tokens", 0),
            tool_calls=tool_calls,
        )

    def _post(
        self,
        path: str,
        payload: dict[str, Any],
        stream: bool = False,
    ) -> dict[str, Any]:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        url = f"{self.base_url.rstrip('/')}{path}"
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return resp.json()
