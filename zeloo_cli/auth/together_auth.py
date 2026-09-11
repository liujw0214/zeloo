"""Together AI authentication.

Together exposes an OpenAI-compatible REST surface at
``https://api.together.xyz/v1`` and authenticates with a single
static API key (``together-...``).

Key resolution
--------------

1. ``api_key`` keyword argument.
2. ``TOGETHER_API_KEY`` environment variable.
3. ``client_id`` (convenience for callers using the base class).

Together does not currently expose a public OAuth flow — only static
keys are supported.  The OAuth methods therefore raise
:class:`AuthConfigError` if invoked.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from zeloo_cli.auth.base import AuthConfigError, AuthError, BaseAuth, TokenResponse, UserInfo
from zeloo_cli.auth.registry import register_auth

logger = logging.getLogger(__name__)


class TogetherAuth(BaseAuth):
    """Authenticate with Together AI via static API key."""

    provider_name: str = "together"

    DEFAULT_API_BASE = "https://api.together.xyz/v1"

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        api_key: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(client_id=client_id, client_secret=client_secret, **kwargs)
        self.api_key: str = (
            api_key
            or os.environ.get("TOGETHER_API_KEY", "")
            or client_id
            or client_secret
        )
        self.api_base: str = self.config.get("api_base", self.DEFAULT_API_BASE)
        self.organization: str | None = self.config.get("organization")

    def _resolved_api_key(self) -> str:
        if self.api_key:
            return self.api_key
        from zeloo_cli.auth.token_store import TokenStore

        stored = TokenStore().load(self.provider_name)
        if stored and stored.get("access_token"):
            return str(stored["access_token"])
        raise AuthConfigError(
            "Together credentials not configured. "
            "Set TOGETHER_API_KEY or run `zeloo auth login together`."
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
        """OAuth is not supported by Together — raise an explicit error."""
        raise AuthConfigError(
            "Together AI does not expose a public OAuth flow. "
            "Use an API key (TOGETHER_API_KEY) instead."
        )

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenResponse:
        """OAuth is not supported by Together."""
        raise AuthConfigError(
            "Together AI does not support authorization-code exchange. "
            "Use an API key (TOGETHER_API_KEY) instead."
        )

    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        """Refresh tokens are not supported by Together static keys."""
        raise AuthConfigError(
            "Together AI does not support refresh tokens. "
            "Rotate the API key manually in the Together console."
        )

    async def get_user_info(self, access_token: str) -> UserInfo:
        """Return a minimal Together user profile.

        Together does not expose a stable ``/me`` endpoint, so this
        method always returns a placeholder profile.  Callers needing
        account metadata should query the billing API separately.
        """
        return UserInfo(
            provider=self.provider_name,
            user_id="together-user",
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
        """Convenience helper to make a signed Together REST call."""
        import httpx

        api_key = self._resolved_api_key()
        url = f"{self.api_base.rstrip('/')}{path}"
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {api_key}"
        headers.setdefault("Content-Type", "application/json")
        if self.organization:
            headers["X-Together-Organization"] = self.organization
        async with httpx.AsyncClient(timeout=kwargs.pop("timeout", 60.0)) as client:
            resp = await client.request(method, url, headers=headers, **kwargs)
        if resp.status_code >= 400:
            raise AuthError(f"Together API error: HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()
        except ValueError as exc:
            raise AuthError("Together API returned non-JSON") from exc


register_auth("together", TogetherAuth)


__all__ = ["TogetherAuth"]
