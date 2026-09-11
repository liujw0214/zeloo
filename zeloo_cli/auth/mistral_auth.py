"""Mistral AI authentication.

Mistral AI's La Plateforme exposes an OpenAI-compatible API that
supports both static API keys and a full OAuth 2.0 authorization-code
flow via ``auth.mistral.ai``.

Key resolution
--------------

1. ``api_key`` keyword argument.
2. ``MISTRAL_API_KEY`` environment variable.
3. ``client_id`` (convenience for callers using the base class).
4. ``client_secret`` (rare; enterprise proxy setups).
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


class MistralAuth(BaseAuth):
    """Authenticate with Mistral AI via API key or OAuth."""

    provider_name: str = "mistral"

    DEFAULT_AUTH_URL = "https://auth.mistral.ai/oauth/authorize"
    DEFAULT_TOKEN_URL = "https://auth.mistral.ai/oauth/token"
    DEFAULT_API_BASE = "https://api.mistral.ai/v1"

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        api_key: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Store Mistral credentials.

        Args:
            client_id: OAuth client ID issued by the Mistral developer
                console.  May be empty when using an API key.
            client_secret: OAuth client secret paired with ``client_id``.
            api_key: Explicit Mistral API key.  Falls back to
                ``MISTRAL_API_KEY`` when ``None``.
            **kwargs: Forwarded to :class:`BaseAuth`.
        """
        super().__init__(client_id=client_id, client_secret=client_secret, **kwargs)
        self.api_key: str = (
            api_key
            or os.environ.get("MISTRAL_API_KEY", "")
            or client_id
            or client_secret
        )
        self.api_base: str = self.config.get("api_base", self.DEFAULT_API_BASE)

    def _resolved_api_key(self) -> str:
        if self.api_key:
            return self.api_key
        from zeloo_cli.auth.token_store import TokenStore

        stored = TokenStore().load(self.provider_name)
        if stored and stored.get("access_token"):
            return str(stored["access_token"])
        raise AuthConfigError(
            "Mistral credentials not configured. "
            "Set MISTRAL_API_KEY or run `zeloo auth login mistral`."
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
        """Build the Mistral OAuth authorization URL."""
        if not self.client_id:
            raise AuthConfigError(
                "Mistral OAuth requires a client_id. "
                "Register an OAuth app in the Mistral AI console and "
                "set `auth.providers.mistral.client_id` in config.yaml."
            )
        scope: str = kwargs.pop("scope", self.config.get("scope", "openid profile api:read api:write"))
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
        """Exchange an authorization code for a Mistral access token."""
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
        """Refresh a Mistral OAuth token."""
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
        """Fetch the authenticated Mistral user profile."""
        data = await self._get_json(
            f"{self.api_base.rstrip('/')}/users/me",
            bearer=access_token,
        )
        return UserInfo(
            provider=self.provider_name,
            user_id=str(data.get("id", "mistral-user")),
            email=data.get("email"),
            name=data.get("name"),
            username=data.get("username"),
            avatar_url=data.get("picture") or data.get("avatar_url"),
            raw=data,
        )

    async def call_api(
        self,
        path: str,
        method: str = "POST",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Convenience helper to make a signed Mistral REST call."""
        import httpx

        api_key = self._resolved_api_key()
        url = f"{self.api_base.rstrip('/')}{path}"
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {api_key}"
        headers.setdefault("Content-Type", "application/json")
        headers.setdefault("Accept", "application/json")
        async with httpx.AsyncClient(timeout=kwargs.pop("timeout", 60.0)) as client:
            resp = await client.request(method, url, headers=headers, **kwargs)
        if resp.status_code >= 400:
            raise AuthError(
                f"Mistral API error: HTTP {resp.status_code}: {resp.text[:200]}"
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise AuthError("Mistral API returned non-JSON") from exc

    def _parse_token_response(self, data: dict[str, Any]) -> TokenResponse:
        access = data.get("access_token")
        if not access:
            raise AuthError(f"Mistral token response missing access_token: {data}")
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


register_auth("mistral", MistralAuth)


__all__ = ["MistralAuth"]
