"""OpenRouter authentication.

OpenRouter exposes an OpenAI-compatible API that is authenticated
with a static API key (``sk-or-...``).  OpenRouter does not publish
an OAuth flow, so the OAuth methods are stubbed for forward
compatibility.

In addition to the bearer token, OpenRouter expects every request
to carry ``HTTP-Referer`` and ``X-Title`` headers so the platform
can attribute traffic to the originating application.

Key resolution
--------------

1. ``api_key`` keyword argument.
2. ``OPENROUTER_API_KEY`` environment variable.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlencode

from zeloo_cli.auth.base import (
    AuthConfigError,
    AuthError,
    BaseAuth,
    TokenResponse,
    UserInfo,
)
from zeloo_cli.auth.registry import register_auth

logger = logging.getLogger(__name__)


class OpenRouterAuth(BaseAuth):
    """Authenticate with OpenRouter via API key (OAuth stubbed)."""

    provider_name: str = "openrouter"

    DEFAULT_AUTH_URL = "https://openrouter.ai/oauth/authorize"
    DEFAULT_TOKEN_URL = "https://openrouter.ai/oauth/token"
    DEFAULT_API_BASE = "https://openrouter.ai/api/v1"

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        api_key: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Store the OpenRouter API key and attribution headers.

        Args:
            client_id: Reserved for future OAuth support.
            client_secret: Reserved for future OAuth support.
            api_key: Explicit OpenRouter API key (``sk-or-...``).
                Falls back to ``OPENROUTER_API_KEY`` when ``None``.
            **kwargs: Forwarded to :class:`BaseAuth`.  Recognised
                keys: ``app_referer`` (HTTP-Referer header) and
                ``app_title`` (X-Title header).
        """
        super().__init__(client_id=client_id, client_secret=client_secret, **kwargs)
        self.api_key: str = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self.api_base: str = self.config.get("api_base", self.DEFAULT_API_BASE)
        self.app_referer: str = self.config.get(
            "app_referer", "https://github.com/zeloo/zeloo"
        )
        self.app_title: str = self.config.get("app_title", "Zeloo CLI")

    def _resolved_api_key(self) -> str:
        if self.api_key:
            return self.api_key
        from zeloo_cli.auth.token_store import TokenStore

        stored = TokenStore().load(self.provider_name)
        if stored and stored.get("access_token"):
            return str(stored["access_token"])
        raise AuthConfigError(
            "OpenRouter credentials not configured. "
            "Set OPENROUTER_API_KEY or run `zeloo auth login openrouter`."
        )

    def is_authenticated(self) -> bool:
        if self.api_key:
            return True
        return super().is_authenticated()

    def get_auth_url(
        self,
        redirect_uri: str,
        state: str = "",
        **kwargs: Any,
    ) -> str:
        """Build a placeholder OpenRouter OAuth URL."""
        params: dict[str, str] = {
            "response_type": "code",
            "client_id": self.client_id or "openrouter-cli",
            "redirect_uri": redirect_uri,
            "scope": kwargs.pop("scope", "api:read api:write"),
        }
        if state:
            params["state"] = state
        params.update({k: str(v) for k, v in kwargs.items()})
        return f"{self.DEFAULT_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenResponse:
        """Exchange an authorization code for an OpenRouter token (stubbed)."""
        return TokenResponse(
            access_token=code,
            token_type="Bearer",
            refresh_token=None,
            expires_in=None,
            scope="api:read api:write",
            extras={"stub": True, "redirect_uri": redirect_uri},
        )

    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        """Refresh an OpenRouter token (not supported, raises)."""
        raise AuthError("OpenRouter does not support OAuth refresh tokens")

    async def get_user_info(self, access_token: str) -> UserInfo:
        """Return a minimal user record for OpenRouter."""
        return UserInfo(
            provider=self.provider_name,
            user_id="openrouter-user",
            email=None,
            name=None,
            username=None,
            avatar_url=None,
            raw={},
        )

    async def call_api(
        self,
        path: str,
        method: str = "POST",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Convenience helper to make a signed OpenRouter REST call.

        OpenRouter requires every request to advertise its origin via
        ``HTTP-Referer`` and ``X-Title`` headers.  Both are injected
        automatically but may be overridden by callers via
        ``headers={"HTTP-Referer": ...}``.
        """
        import httpx

        api_key = self._resolved_api_key()
        url = f"{self.api_base.rstrip('/')}{path}"
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {api_key}"
        headers.setdefault("Content-Type", "application/json")
        headers.setdefault("HTTP-Referer", self.app_referer)
        headers.setdefault("X-Title", self.app_title)
        async with httpx.AsyncClient(timeout=kwargs.pop("timeout", 60.0)) as client:
            resp = await client.request(method, url, headers=headers, **kwargs)
        if resp.status_code >= 400:
            raise AuthError(
                f"OpenRouter API error: HTTP {resp.status_code}: {resp.text[:200]}"
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise AuthError("OpenRouter API returned non-JSON") from exc


register_auth("openrouter", OpenRouterAuth)


__all__ = ["OpenRouterAuth"]
