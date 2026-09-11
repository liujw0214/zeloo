"""Chat completion helpers — provider-agnostic request/response handling."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CompletionRequest:
    """Normalized chat completion request."""

    model: str
    messages: list[dict[str, Any]]
    temperature: float = 0.7
    max_tokens: int | None = None
    top_p: float | None = None
    stop: list[str] | None = None
    stream: bool = False
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class CompletionResponse:
    """Normalized chat completion response."""

    content: str
    model: str
    finish_reason: str
    usage: dict[str, int] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to standard dict format."""
        return {
            "content": self.content,
            "model": self.model,
            "finish_reason": self.finish_reason,
            "usage": self.usage,
            "tool_calls": self.tool_calls,
        }


def build_chat_request(
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    **kwargs: Any,
) -> CompletionRequest:
    """Build a normalized CompletionRequest from parameters.

    Args:
        model: Model identifier.
        messages: Chat message list.
        tools: Optional tool definitions.
        **kwargs: Additional provider-specific parameters.

    Returns:
        Normalized CompletionRequest.
    """
    return CompletionRequest(
        model=model,
        messages=list(messages),
        tools=list(tools) if tools else None,
        temperature=kwargs.get("temperature", 0.7),
        max_tokens=kwargs.get("max_tokens"),
        top_p=kwargs.get("top_p"),
        stop=kwargs.get("stop"),
        stream=kwargs.get("stream", False),
        tool_choice=kwargs.get("tool_choice"),
        extra=kwargs,
    )


def parse_openai_response(response_data: dict[str, Any]) -> CompletionResponse:
    """Parse an OpenAI-compatible API response.

    Args:
        response_data: Raw JSON response dict.

    Returns:
        Normalized CompletionResponse.
    """
    choices = response_data.get("choices", [])
    choice = choices[0] if choices else {}

    message = choice.get("message", {})

    content = message.get("content", "") or ""
    if isinstance(content, list):
        content = "".join(
            c.get("text", "") if isinstance(c, dict) else str(c) for c in content
        )

    tool_calls = []
    for tc in message.get("tool_calls", []):
        func = tc.get("function", {})
        tool_calls.append({
            "id": tc.get("id", ""),
            "name": func.get("name", ""),
            "arguments": func.get("arguments", ""),
        })

    return CompletionResponse(
        content=content,
        model=response_data.get("model", ""),
        finish_reason=choice.get("finish_reason", ""),
        usage=response_data.get("usage", {}),
        tool_calls=tool_calls,
        raw=response_data,
    )


def parse_anthropic_response(response_data: dict[str, Any]) -> CompletionResponse:
    """Parse an Anthropic Claude API response into CompletionResponse format.

    Args:
        response_data: Raw Anthropic response dict.

    Returns:
        Normalized CompletionResponse.
    """
    content_blocks = response_data.get("content", [])
    content_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []

    for block in content_blocks:
        if block.get("type") == "text":
            content_parts.append(block.get("text", ""))
        elif block.get("type") == "tool_use":
            tool_calls.append({
                "id": block.get("id", ""),
                "name": block.get("name", ""),
                "arguments": block.get("input", {}),
            })

    content = "".join(content_parts)
    stop_reason = response_data.get("stop_reason", "")
    anthropic_to_openai = {
        "end_turn": "stop",
        "max_tokens": "length",
        "tool_use": "tool_calls",
    }
    finish_reason = anthropic_to_openai.get(stop_reason, stop_reason)

    return CompletionResponse(
        content=content,
        model=response_data.get("model", ""),
        finish_reason=finish_reason,
        usage={
            "input_tokens": response_data.get("usage", {}).get("input_tokens", 0),
            "output_tokens": response_data.get("usage", {}).get("output_tokens", 0),
        },
        tool_calls=tool_calls,
        raw=response_data,
    )


def build_openai_payload(request: CompletionRequest) -> dict[str, Any]:
    """Build an OpenAI-compatible API request payload.

    Args:
        request: Normalized CompletionRequest.

    Returns:
        Dict ready for POST body.
    """
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": _normalize_messages(request.messages),
        "temperature": request.temperature,
        "stream": request.stream,
    }
    if request.max_tokens is not None:
        payload["max_tokens"] = request.max_tokens
    if request.top_p is not None:
        payload["top_p"] = request.top_p
    if request.stop:
        payload["stop"] = request.stop
    if request.tools:
        payload["tools"] = request.tools
        if request.tool_choice:
            payload["tool_choice"] = request.tool_choice

    for key in ("frequency_penalty", "presence_penalty", "seed"):
        if key in request.extra:
            payload[key] = request.extra[key]

    return payload


def build_anthropic_payload(
    request: CompletionRequest, api_key: str | None = None
) -> dict[str, Any]:
    """Build an Anthropic Claude API request payload.

    Args:
        request: Normalized CompletionRequest.
        api_key: Optional explicit API key (otherwise from env).

    Returns:
        Dict ready for Anthropic messages API POST body.
    """
    msgs = _normalize_messages(request.messages)
    system_parts: list[str] = []
    conversation: list[dict[str, str]] = []

    for msg in msgs:
        role = msg["role"]
        content = msg["content"]
        if isinstance(content, list):
            content = " ".join(
                c.get("text", "") if isinstance(c, dict) else str(c)
                for c in content
            )
        if role == "system":
            system_parts.append(content)
        else:
            conversation.append({"role": role, "content": content})

    max_tokens = request.max_tokens or 4096

    payload: dict[str, Any] = {
        "model": request.model,
        "messages": conversation,
        "max_tokens": max_tokens,
    }
    if system_parts:
        payload["system"] = "\n".join(system_parts)
    if request.temperature != 0.7:
        payload["temperature"] = request.temperature
    if request.extra.get("top_p"):
        payload["top_p"] = request.extra["top_p"]
    if request.tools:
        payload["tools"] = _to_anthropic_tools(request.tools)
        payload["tool_choice"] = _to_anthropic_tool_choice(request.tool_choice)

    return payload


def convert_messages_for_provider(
    messages: list[dict[str, Any]],
    source: str,
    target: str,
) -> list[dict[str, Any]]:
    """Convert message format between providers.

    Args:
        messages: Source message list.
        source: Source provider name.
        target: Target provider name.

    Returns:
        Converted message list.
    """
    if source == target:
        return list(messages)

    converted = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if target == "anthropic":
            if role == "system":
                role = "user"
            if isinstance(content, list):
                parts = []
                for c in content:
                    if isinstance(c, dict):
                        if c.get("type") == "text":
                            parts.append(c.get("text", ""))
                        elif c.get("type") == "image_url":
                            parts.append("[image]")
                content = " ".join(parts)

        elif target in ("deepseek", "gemini"):
            if isinstance(content, list):
                text_parts = [
                    c.get("text", "") if isinstance(c, dict) else str(c)
                    for c in content
                ]
                content = "\n".join(text_parts)

        converted.append({"role": role, "content": content, **msg})

    return converted


def merge_usage_stats(usage_list: list[dict[str, int]]) -> dict[str, int]:
    """Merge usage statistics from multiple API calls.

    Args:
        usage_list: List of usage dicts from responses.

    Returns:
        Merged usage dict with summed values.
    """
    merged: dict[str, int] = {}
    for usage in usage_list:
        for key, value in usage.items():
            merged[key] = merged.get(key, 0) + value
    return merged


def _normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ensure messages are in a consistent format."""
    result = []
    for msg in messages:
        normalized: dict[str, Any] = {
            "role": msg.get("role", "user"),
            "content": msg.get("content", ""),
        }
        if "name" in msg and msg["role"] == "assistant":
            normalized["name"] = msg["name"]
        result.append(normalized)
    return result


def _to_anthropic_tools(
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert OpenAI tool schema to Anthropic tool schema."""
    anthropic_tools = []
    for tool in tools:
        func = tool.get("function", {})
        anthropic_tools.append({
            "name": func.get("name", ""),
            "description": func.get("description", ""),
            "input_schema": func.get("parameters", {}),
        })
    return anthropic_tools


def _to_anthropic_tool_choice(
    choice: str | dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Convert OpenAI tool_choice to Anthropic format."""
    if choice is None:
        return None
    if isinstance(choice, str):
        return {"type": "auto"} if choice == "auto" else {"type": "any"}
    if isinstance(choice, dict):
        func = choice.get("function", {})
        return {"type": "tool", "name": func.get("name", "")}
    return None
