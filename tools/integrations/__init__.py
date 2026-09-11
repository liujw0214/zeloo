"""Zeloo platform integrations.

Each integration is an async subclass of
:class:`tools.integrations.base.BaseIntegration`. Use
:func:`tools.integrations.registry.get_integration` to look one up by
name, or import the concrete class directly.
"""

from __future__ import annotations

from tools.integrations.base import (
    AuthError,
    BaseIntegration,
    IntegrationError,
    NotFoundError,
    RateLimitError,
    ReceiveCallback,
    safe_call,
)
from tools.integrations.discord_integration import DiscordIntegration
from tools.integrations.feishu_integration import FeishuIntegration
from tools.integrations.registry import (
    INTEGRATION_REGISTRY,
    get_integration,
    list_integrations,
    register_integration,
    unregister_integration,
)
from tools.integrations.slack_integration import SlackIntegration
from tools.integrations.telegram_integration import TelegramIntegration

__all__ = [
    # Base
    "BaseIntegration",
    "IntegrationError",
    "AuthError",
    "NotFoundError",
    "RateLimitError",
    "ReceiveCallback",
    "safe_call",
    # Concrete integrations
    "DiscordIntegration",
    "SlackIntegration",
    "FeishuIntegration",
    "TelegramIntegration",
    # Registry helpers
    "INTEGRATION_REGISTRY",
    "register_integration",
    "get_integration",
    "list_integrations",
    "unregister_integration",
]