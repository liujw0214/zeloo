"""Agent runtime helpers — shared utilities for conversation_loop and run_agent."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Any

from agent.zeloo_constants import DEFAULT_CONTEXT_MAX_MESSAGES

logger = logging.getLogger(__name__)

MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4-turbo": 128000,
    "gpt-4": 8192,
    "gpt-3.5-turbo": 16385,
    "claude-3-5-sonnet": 200000,
    "claude-3-5-haiku": 200000,
    "claude-3-opus": 200000,
    "claude-3-sonnet": 200000,
    "deepseek-chat": 64000,
    "gemini-1.5-flash": 1000000,
    "gemini-1.5-pro": 1000000,
    "o1-preview": 128000,
    "o1-mini": 128000,
}

_TOKEN_ESTIMATE_RATIO = 0.25


@dataclass
class ModelConfig:
    """Resolved model configuration."""

    provider: str
    model: str
    max_context_tokens: int
    supports_tools: bool
    supports_vision: bool
    base_url: str | None


def resolve_model_config(agent: Any) -> ModelConfig:
    """Resolve model configuration from an agent instance."""
    model = getattr(agent, "model", "gpt-4o")
    provider = getattr(agent, "provider", "openai")
    base_url = getattr(agent, "base_url", None)

    max_tokens = MODEL_CONTEXT_WINDOWS.get(model, 128000)
    supports_tools = provider not in ("o1-preview", "o1-mini")
    supports_vision = "vision" in model.lower() or "4o" in model or "claude-3" in model

    return ModelConfig(
        provider=provider,
        model=model,
        max_context_tokens=max_tokens,
        supports_tools=supports_tools,
        supports_vision=supports_vision,
        base_url=base_url,
    )


def build_tool_context(tools: list[Any]) -> dict[str, Any]:
    """Build tool context for system prompt injection."""
    if not tools:
        return {"tools": []}

    tool_schemas = []
    for tool in tools:
        schema: dict[str, Any] = {
            "type": "function",
            "function": {
                "name": getattr(tool, "name", "unknown"),
                "description": getattr(tool, "description", ""),
            },
        }
        schema["function"]["parameters"] = getattr(tool, "input_schema", {"type": "object"})
        tool_schemas.append(schema)

    return {"tools": tool_schemas}


def truncate_messages_for_context(
    messages: list[dict[str, Any]],
    max_tokens: int,
    model: str = "gpt-4o",
) -> list[dict[str, Any]]:
    """Truncate message list to fit within token budget."""
    if not messages:
        return []

    budget = min(MODEL_CONTEXT_WINDOWS.get(model, 128000), max_tokens)
    reserved = int(budget * 0.85)

    if sum(_compute_token_estimate(_message_to_text(m)) for m in messages) <= reserved:
        return messages

    result = list(messages)
    while result and _estimate_total(result) > reserved:
        result.pop(0)

    return result if result else [messages[-1]]


def resolve_session_id(platform: str, user_id: str) -> str:
    """Generate a stable session ID from platform and user identifiers."""
    return hashlib.sha256(f"{platform}:{user_id}".encode()).hexdigest()[:24]


def compute_token_estimate(text: str) -> int:
    """Estimate token count for a text string."""
    return _compute_token_estimate(text)


def should_compress_context(agent: Any) -> bool:
    """Determine whether the current conversation needs compression."""
    messages = getattr(agent, "messages", [])
    max_msgs = getattr(agent, "max_messages", DEFAULT_CONTEXT_MAX_MESSAGES)
    if len(messages) < max_msgs:
        return False

    total_chars = sum(len(_message_to_text(m)) for m in messages)
    if total_chars < 30000:
        return False

    return True


def _compute_token_estimate(text: str) -> int:
    """Internal token estimation using character count."""
    return max(1, int(len(text) * _TOKEN_ESTIMATE_RATIO)) if text else 0


def _message_to_text(message: dict[str, Any]) -> str:
    """Convert a message dict to a searchable text representation."""
    role = message.get("role", "user")
    content = message.get("content", "")
    if isinstance(content, list):
        content = " ".join(
            c.get("text", "") if isinstance(c, dict) else str(c) for c in content
        )
    return f"{role}: {content}"


def _estimate_total(messages: list[dict[str, Any]]) -> int:
    """Estimate total tokens for a message list."""
    return sum(_compute_token_estimate(_message_to_text(m)) for m in messages)


def parse_tool_calls_from_response(response_text: str) -> list[dict[str, Any]]:
    """Parse tool call blocks from a model response string."""
    calls = []

    xml_pattern = re.compile(
        r"<tool_call>\s*<name>(.*?)</name>\s*<args>(.*?)</args>\s*</tool_call>",
        re.DOTALL,
    )
    for match in xml_pattern.finditer(response_text):
        name = match.group(1).strip()
        args_raw = match.group(2).strip()
        try:
            import json

            args = json.loads(args_raw) if args_raw else {}
        except Exception:
            args = {"raw": args_raw}
        calls.append({"name": name, "arguments": args})

    if not calls:
        try:
            import json

            data = json.loads(response_text)
            if isinstance(data, dict) and "tool_calls" in data:
                for tc in data["tool_calls"]:
                    func = tc.get("function", {})
                    tc_args = tc.get("arguments") or func.get("arguments", {})
                    calls.append({
                        "name": tc.get("name") or func.get("name", ""),
                        "arguments": tc_args,
                    })
        except Exception:
            pass

    return calls


def extract_platform_hint(platform: str) -> str:
    """Return a platform-specific behavioral hint for the system prompt."""
    hints: dict[str, str] = {
        "telegram": "Keep responses concise (Telegram limit: 4096 chars). Use markdown sparingly.",
        "discord": "Use Discord markdown. Code blocks preferred for multi-line output.",
        "slack": "Use Slack message formatting. Thread replies when possible.",
        "feishu": "飞书消息格式，注意中文自然语言。",
        "dingtalk": "钉钉消息格式。",
        "wecom": "企业微信格式。",
        "teams": "Microsoft Teams format. Keep messages clear and structured.",
        "matrix": "Matrix/Element format. Use formatted text for readability.",
        "local": "Full response OK. This is a direct terminal session.",
    }
    return hints.get(platform.lower(), f"Platform: {platform}. Adapt format appropriately.")


def sanitize_api_key_for_log(key: str) -> str:
    """Mask an API key for safe logging output."""
    if not key:
        return "(empty)"
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}...{key[-4:]}"
