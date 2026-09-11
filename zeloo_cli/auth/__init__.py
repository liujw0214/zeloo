"""OAuth authentication subsystem for Zeloo CLI.

This package provides a pluggable OAuth framework supporting multiple
identity providers (OpenAI, Anthropic, Google, GitHub, Discord, …).

Public entry points:

* :class:`BaseAuth` — abstract OAuth provider base class.
* :func:`register_auth` / :func:`get_auth` — provider registry helpers.
* :class:`TokenStore` — encrypted on-disk token storage.
* :class:`DeviceFlowClient` — RFC 8628 device authorization grant client.

Importing :mod:`zeloo_cli.auth` performs eager registration of the
built-in providers; this means callers only need to ``import
zeloo_cli.auth`` once and the registry is populated automatically.
"""

from __future__ import annotations

from zeloo_cli.auth.base import AuthError, BaseAuth, TokenResponse, UserInfo
from zeloo_cli.auth.device_flow import DeviceFlowClient, DeviceFlowResult
from zeloo_cli.auth.registry import (
    AUTH_REGISTRY,
    get_auth,
    list_auth_providers,
    register_auth,
)
from zeloo_cli.auth.token_store import TokenStore

__all__ = [
    "AUTH_REGISTRY",
    "AuthError",
    "BaseAuth",
    "DeviceFlowClient",
    "DeviceFlowResult",
    "TokenResponse",
    "TokenStore",
    "UserInfo",
    "get_auth",
    "list_auth_providers",
    "register_auth",
]

# Eagerly import concrete providers so their ``@register_auth`` decorators
# run before any caller inspects the registry. Keep the imports inside
# the package init so circular dependencies between providers and the
# registry resolve cleanly.
import zeloo_cli.auth.openai_auth  # noqa: F401, E402
import zeloo_cli.auth.anthropic_auth  # noqa: F401, E402
import zeloo_cli.auth.google_auth  # noqa: F401, E402
import zeloo_cli.auth.github_auth  # noqa: F401, E402
import zeloo_cli.auth.discord_auth  # noqa: F401, E402
import zeloo_cli.auth.xai_auth  # noqa: F401, E402
import zeloo_cli.auth.deepseek_auth  # noqa: F401, E402
import zeloo_cli.auth.groq_auth  # noqa: F401, E402
import zeloo_cli.auth.mistral_auth  # noqa: F401, E402
import zeloo_cli.auth.ollama_auth  # noqa: F401, E402
import zeloo_cli.auth.openrouter_auth  # noqa: F401, E402
import zeloo_cli.auth.azure_auth  # noqa: F401, E402
import zeloo_cli.auth.fireworks_auth  # noqa: F401, E402
import zeloo_cli.auth.together_auth  # noqa: F401, E402
import zeloo_cli.auth.bedrock_auth  # noqa: F401, E402
import zeloo_cli.auth.local_auth  # noqa: F401, E402
