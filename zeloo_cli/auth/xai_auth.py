"""xAI (Grok) authentication.

xAI uses static API keys (``xai-...``) for the Grok API.
An optional OAuth flow is available for xAI Platform users.

Key resolution
--------------

1. ``api_key`` keyword argument.
2. ``XAI_API_KEY`` environment variable.
3. ``client_id`` (if it looks like a key — convenience for callers
   that pass ``client_id`` because they're using the base class).
4. ``client_secret`` (rare; used by enterprise proxy setups).
"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlencode

from zeloo_cli.auth.base import AuthConfigError, AuthError, BaseAuth, TokenResponse, UserInfo
from zeloo_cli.auth.registry import register_auth

logger = logging.getLogger(__name__)


class XAIAuth(BaseAuth):
    """Authenticate with xAI / Grok via API key or OAuth."""

    provider_name: str = "xai"

    DEFAULT_AUTH_URL = "https://x.ai/oauth/authorize"
    DEFAULT_TOKEN_URL = "https://x.ai/oauth/token"
    DEFAULT_API_BASE = "https://api.x.ai/v1"

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
            or os.environ.get("XAI_API_KEY", "")
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
            "xAI credentials not configured. "
            "Set XAI_API_KEY or run `zeloo auth login xai`."
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
        """Build the xAI OAuth authorization URL."""
        if not self.client_id:
            raise AuthConfigError(
                "xAI OAuth requires a client_id. "
                "Register an OAuth app in the xAI Developer Console and "
                "set `auth.providers.xai.client_id` in config.yaml."
            )
        scope: str = kwargs.pop("scope", self.config.get("scope", "api:read api:write"))
        params: dict[str, str] = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
        }
        if state:
            params["state"] = state
        params.update({k: str(v) for k, v in kwargs.items()})
        return f"{self.DEFAULT_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenResponse:
        """Exchange an authorization code for an xAI access token."""
        if not self.client_id:
            raise AuthConfigError("client_id is required for the OAuth flow")
        data = await self._post_form(
            self.DEFAULT_TOKEN_URL,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        return self._parse_token_response(data)

    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        """Refresh an xAI OAuth token."""
        if not self.client_id:
            raise AuthConfigError("client_id is required for the OAuth flow")
        data = await self._post_form(
            self.DEFAULT_TOKEN_URL,
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        return self._parse_token_response(data)

    async def get_user_info(self, access_token: str) -> UserInfo:
        """Fetch xAI user profile from the Grok API."""
        import httpx

        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.api_base.rstrip('/')}/me",
                headers=headers,
            )
        if resp.status_code >= 400:
            logger.debug("xAI /me request failed: HTTP %s", resp.status_code)
            return UserInfo(
                provider=self.provider_name,
                user_id="xai-user",
                email=None,
                name=None,
                username=None,
                avatar_url=None,
                raw={},
            )
        try:
            data = resp.json()
        except Exception:
            data = {}
        return UserInfo(
            provider=self.provider_name,
            user_id=str(data.get("id", "xai-user")),
            email=data.get("email"),
            name=data.get("name"),
            username=data.get("username"),
            avatar_url=data.get("avatar_url") or data.get("picture"),
            raw=data,
        )

    async def call_api(
        self,
        path: str,
        method: str = "POST",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Convenience helper to make a signed xAI REST call."""
        import httpx

        api_key = self._resolved_api_key()
        url = f"{self.api_base.rstrip('/')}{path}"
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {api_key}"
        headers.setdefault("Content-Type", "application/json")
        if self.organization:
            headers["X-AI-Organization"] = self.organization
        async with httpx.AsyncClient(timeout=kwargs.pop("timeout", 60.0)) as client:
            resp = await client.request(method, url, headers=headers, **kwargs)
        if resp.status_code >= 400:
            raise AuthError(f"xAI API error: HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()
        except ValueError as exc:
            raise AuthError("xAI API returned non-JSON") from exc

    def _parse_token_response(self, data: dict[str, Any]) -> TokenResponse:
        access = data.get("access_token")
        if not access:
            raise AuthError(f"xAI token response missing access_token: {data}")
        expires_in = data.get("expires_in")
        return TokenResponse(
            access_token=access,
            token_type=data.get("token_type", "Bearer"),
            refresh_token=data.get("refresh_token"),
            expires_in=int(expires_in) if expires_in is not None else None,
            scope=data.get("scope", ""),
            extras={
                k: v
                for k, v in data.items()
                if k
                not in {
                    "access_token",
                    "token_type",
                    "refresh_token",
                    "expires_in",
                    "scope",
                }
            },
        )


register_auth("xai", XAIAuth)


__all__ = ["XAIAuth"]
