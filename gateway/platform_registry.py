"""Platform registry — maps platform names to their adapter classes.

Adapters are registered lazily (on first access) to avoid importing
optional SDKs at module load time. Use :func:`get_platform` to resolve
a name to its adapter class, or :func:`list_platforms` for discovery.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Maps platform name → (module_path, class_name) for lazy import.
_PLATFORM_REGISTRY: dict[str, tuple[str, str]] = {
    "telegram": ("gateway.platforms.telegram", "TelegramAdapter"),
    "discord": ("gateway.platforms.discord", "DiscordAdapter"),
    "slack": ("gateway.platforms.slack", "SlackAdapter"),
    "whatsapp": ("gateway.platforms.whatsapp", "WhatsAppAdapter"),
    "signal": ("gateway.platforms.signal", "SignalAdapter"),
    "email": ("gateway.platforms.email_adapter", "EmailAdapter"),
    "feishu": ("gateway.platforms.feishu", "FeishuAdapter"),
    "dingtalk": ("gateway.platforms.dingtalk", "DingTalkAdapter"),
    "wecom": ("gateway.platforms.wecom", "WeComAdapter"),
    "teams": ("gateway.platforms.teams", "TeamsAdapter"),
    "matrix": ("gateway.platforms.matrix", "MatrixAdapter"),
    "google_chat": ("gateway.platforms.google_chat", "GoogleChatAdapter"),
    "sms": ("gateway.platforms.sms", "SMSAdapter"),
    "qqbot": ("gateway.platforms.qqbot", "QQBotAdapter"),
    "irc": ("gateway.platforms.irc", "IRCAdapter"),
    "line": ("gateway.platforms.line", "LINEAdapter"),
    "mattermost": ("gateway.platforms.mattermost", "MattermostAdapter"),
    "home_assistant": (
        "gateway.platforms.home_assistant",
        "HomeAssistantAdapter",
    ),
}


def register_platform(name: str, adapter_cls: Any) -> None:
    """Register a platform adapter class directly.

    Args:
        name: Platform identifier (e.g. ``"telegram"``).
        adapter_cls: The adapter class (not an instance).
    """
    _PLATFORM_REGISTRY[name] = ("", "")  # placeholder
    # Store the actual class in a separate mapping
    globals().setdefault("_DIRECT_REGISTRY", {})[name] = adapter_cls


def get_platform(name: str) -> Any | None:
    """Get a platform adapter class by name (lazy import).

    Returns ``None`` if the platform is not registered or the SDK
    is not installed.
    """
    direct = globals().get("_DIRECT_REGISTRY", {}).get(name)
    if direct is not None:
        return direct

    entry = _PLATFORM_REGISTRY.get(name)
    if entry is None:
        return None
    module_path, class_name = entry
    try:
        module = importlib.import_module(module_path)
        return getattr(module, class_name, None)
    except Exception:
        logger.debug("Platform %s not available", name, exc_info=True)
        return None


def list_platforms() -> list[str]:
    """List all registered platform names."""
    return sorted(_PLATFORM_REGISTRY.keys())
