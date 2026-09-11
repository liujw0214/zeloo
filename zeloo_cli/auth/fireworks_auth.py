"""Fireworks AI authentication.

Fireworks exposes an OpenAI-compatible REST surface at
``https://api.fireworks.ai/inference/v1`` and authenticates with a
single static API key (``fw_...``).

Key resolution
--------------

1. ``api_key`` keyword argument.
2. ``FIREWORKS_API_KEY`` environment variable.
3. ``client_id`` (convenience for callers using the base class).

The provider does not currently expose a public OAuth flow — only
static keys are supported.  The OAuth methods therefore raise
:class:`AuthConfigError` if invoked, mirroring the behaviour of other
key-only providers.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from zeloo_cli.auth.base import AuthConfigError, AuthError, BaseAuth, TokenResponse, UserInfo
from zeloo_cli.auth.registry import register_auth

logger = logging.getLogger(__name__)


class FireworksAuth(BaseAuth):
    """Authenticate with Fireworks AI via static API key."""

    provider_name: str = "fireworks"

    DEFAULT_API_BASE = "https://api.fireworks.ai/inference/v1"

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
            or os.environ.get("FIREWORKS_API_KEY", "")
            or client_id
            or client_secret
        )
        self.api_base: str = self.config.get("api_base", self.DEFAULT_API_BASE)
        self.account_id: str | None = self.config.get("account_id")

    def _resolved_api_key(self) -> str:
        if self.api_key:
            return self.api_key
        from zeloo_cli.auth.token_store import TokenStore

        stored = TokenStore().load(self.provider_name)
        if stored and stored.get("access_token"):
            return str(stored["access_token"])
        raise AuthConfigError(
            "Fireworks credentials not configured. "
            "Set FIREWORKS_API_KEY or run `zeloo auth login fireworks`."
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
        """OAuth is not supported by Fireworks — raise an explicit error."""
        raise AuthConfigError(
            "Fireworks AI does not expose a public OAuth flow. "
            "Use an API key (FIREWORKS_API_KEY) instead."
        )

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenResponse:
        """OAuth is not supported by Fireworks."""
        raise AuthConfigError(
            "Fireworks AI does not support authorization-code exchange. "
            "Use an API key (FIREWORKS_API_KEY) instead."
        )

    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        """Refresh tokens are not supported by Fireworks static keys."""
        raise AuthConfigError(
            "Fireworks AI does not support refresh tokens. "
            "Rotate the API key manually in the Fireworks console."
        )

    async def get_user_info(self, access_token: str) -> UserInfo:
        """Return a minimal Fireworks user profile from the /account endpoint."""
        import httpx

        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{self.api_base.rstrip('/')}/account",
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            logger.debug("Fireworks /account request failed: %s", exc)
            return UserInfo(
                provider=self.provider_name,
                user_id="fireworks-user",
                email=None,
                name=None,
                username=None,
                avatar_url=None,
                raw={},
            )
        if resp.status_code >= 400:
            logger.debug("Fireworks /account returned HTTP %s", resp.status_code)
            return UserInfo(
                provider=self.provider_name,
                user_id="fireworks-user",
                email=None,
                name=None,
                username=None,
                avatar_url=None,
                raw={},
            )
        try:
            data = resp.json()
        except ValueError:
            data = {}
        return UserInfo(
            provider=self.provider_name,
            user_id=str(data.get("id", data.get("account_id", "fireworks-user"))),
            email=data.get("email"),
            name=data.get("name") or data.get("display_name"),
            username=data.get("name") or data.get("account_id"),
            avatar_url=data.get("avatar_url") or data.get("picture"),
            raw=data,
        )

    async def call_api(
        self,
        path: str,
        method: str = "POST",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Convenience helper to make a signed Fireworks REST call."""
        import httpx

        api_key = self._resolved_api_key()
        url = f"{self.api_base.rstrip('/')}{path}"
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {api_key}"
        headers.setdefault("Content-Type", "application/json")
        if self.account_id:
            headers["X-Fireworks-Account"] = self.account_id
        async with httpx.AsyncClient(timeout=kwargs.pop("timeout", 60.0)) as client:
            resp = await client.request(method, url, headers=headers, **kwargs)
        if resp.status_code >= 400:
            raise AuthError(f"Fireworks API error: HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()
        except ValueError as exc:
            raise AuthError("Fireworks API returned non-JSON") from exc


register_auth("fireworks", FireworksAuth)


__all__ = ["FireworksAuth"]
