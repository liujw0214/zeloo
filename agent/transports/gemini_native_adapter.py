"""Google Gemini native protocol transport adapter."""

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

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com"


class GeminiNativeAdapter(TransportAdapter):
    """Transport adapter for Google Gemini API using the native REST protocol."""

    name = "gemini"
    supports_streaming = True
    supports_vision = True
    supports_tools = True
    max_context_tokens = 128000

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        timeout: float = 60.0,
    ):
        self.api_key = api_key
        self.base_url = base_url or GEMINI_BASE_URL

    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str = "gemini-2.0-flash",
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> Response:
        payload = self._build_payload(messages, model, tools, **kwargs)
        try:
            raw = self._post(model, payload, stream=stream)
            return self._parse_response(raw, model)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise AuthenticationError("Invalid Gemini API key") from e
            if e.response.status_code == 429:
                raise RateLimitError("Gemini rate limit exceeded") from e
            raise TransportError(f"Gemini API error: {e}") from e

    def validate_credentials(self) -> bool:
        try:
            payload = {"contents": [{"role": "user", "parts": [{"text": "ping"}]}]}
            self._post("gemini-2.0-flash", payload, stream=False)
            return True
        except Exception as e:
            logger.warning("Gemini credential validation failed: %s", e)
            return False

    def get_default_model(self) -> str:
        return "gemini-2.0-flash"

    def _build_payload(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        contents = []
        for msg in messages:
            role = msg.get("role", "user")
            gemini_role = "user" if role in ("user", "system") else "model"
            content = msg.get("content", "")
            if isinstance(content, list):
                parts = []
                for c in content:
                    if isinstance(c, dict):
                        if c.get("type") == "text":
                            parts.append({"text": c.get("text", "")})
                        elif c.get("type") == "image_url":
                            parts.append({
                                "inlineData": {
                                    "mimeType": "image/png",
                                    "data": c["image_url"]["url"].split(",")[-1],
                                }
                            })
                    else:
                        parts.append({"text": str(c)})
                contents.append({"role": gemini_role, "parts": parts})
            else:
                contents.append({"role": gemini_role, "parts": [{"text": content}]})

        generation_config: dict[str, Any] = {
            "temperature": kwargs.get("temperature", 0.0),
            "maxOutputTokens": kwargs.get("max_tokens", 8192),
        }

        payload: dict[str, Any] = {"contents": contents, "generationConfig": generation_config}
        if tools:
            payload["tools"] = self._convert_tools(tools)
        return payload

    def _convert_tools(self, tools: list[dict[str, Any]]) -> dict[str, Any]:
        declarations = []
        for tool in tools:
            func = tool.get("function", {})
            declarations.append({
                "functionDeclarations": [{
                    "name": func.get("name", tool.get("name", "")),
                    "description": func.get("description", ""),
                    "parameters": func.get("parameters", {"type": "object", "properties": {}}),
                }],
            })
        return {"functionDeclarations": declarations} if declarations else {}

    def _parse_response(self, raw: dict[str, Any], model: str) -> Response:
        content = ""
        tool_calls: list[dict[str, Any]] = []
        finish_reason = ""

        candidates = raw.get("candidates", [])
        if candidates:
            candidate = candidates[0]
            finish_reason = str(candidate.get("finishReason", ""))
            for part in candidate.get("content", {}).get("parts", []):
                if "text" in part:
                    content += part["text"]
                elif "functionCall" in part:
                    fc = part["functionCall"]
                    tool_calls.append({
                        "id": f"call_{fc.get('name', '')}_{id(fc)}",
                        "type": "function",
                        "function": {
                            "name": fc.get("name", ""),
                            "arguments": str(fc.get("args", {})),
                        },
                    })

        usage = raw.get("usageMetadata", {})
        return Response(
            content=content,
            raw=raw,
            model=model,
            finish_reason=finish_reason,
            usage_in=usage.get("promptTokenCount", 0),
            usage_out=usage.get("candidatesTokenCount", 0),
            tool_calls=tool_calls,
        )

    def _post(
        self, model: str, payload: dict[str, Any], stream: bool = False
    ) -> dict[str, Any]:
        url = (
            f"{self.base_url}/v1beta/models/{model}:generateContent"
            f"?key={self.api_key}"
        )
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
