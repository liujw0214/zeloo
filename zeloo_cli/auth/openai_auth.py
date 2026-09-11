"""OpenAI authentication.

The common case is a static ``sk-...`` API key.  OpenAI also exposes
a ChatGPT/Codex OAuth device flow for users without API keys; this
module supports both.

Resolution order for the API key
--------------------------------

1. ``client_id`` keyword argument (if it looks like ``sk-...``).
2. ``OPENAI_API_KEY`` environment variable.
3. ``client_secret`` keyword argument (rare; used in custom proxies).
4. Existing token in :class:`TokenStore` (from a previous device flow).

Sub-class :class:`BaseAuth` so it participates in the unified
:data:`zeloo_cli.auth.registry.AUTH_REGISTRY` lookup.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from zeloo_cli.auth.base import AuthConfigError, AuthError, BaseAuth, TokenResponse, UserInfo
from zeloo_cli.auth.device_flow import DeviceFlowClient
from zeloo_cli.auth.registry import register_auth

logger = logging.getLogger(__name__)


class OpenAIAuth(BaseAuth):
    """Authenticate with OpenAI via API key or OAuth device flow."""

    provider_name: str = "openai"

    DEFAULT_AUTH_URL = "https://auth.openai.com/authorize"
    DEFAULT_TOKEN_URL = "https://auth.openai.com/oauth/token"
    DEFAULT_DEVICE_URL = "https://auth.openai.com/oauth/device/code"
    DEFAULT_API_BASE = "https://api.openai.com/v1"

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        api_key: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(client_id=client_id, client_secret=client_secret, **kwargs)
        # Resolve the API key with the documented precedence.
        self.api_key: str = (
            api_key
            or os.environ.get("OPENAI_API_KEY", "")
            or client_id
            or client_secret
        )
        self.api_base: str = self.config.get("api_base", self.DEFAULT_API_BASE)

    # ── API-key helpers ─────────────────────────────────────────

    def _resolved_api_key(self) -> str:
        """Return a usable API key or raise :class:`AuthConfigError`."""
        if self.api_key:
            return self.api_key
        # Fall back to the token store (e.g. a Codex device-flow token
        # that was previously saved).
        from zeloo_cli.auth.token_store import TokenStore

        stored = TokenStore().load(self.provider_name)
        if stored and stored.get("access_token"):
            return str(stored["access_token"])
        raise AuthConfigError(
            "OpenAI credentials not configured. "
            "Set OPENAI_API_KEY or pass api_key=. "
            "Run `zeloo auth login openai` for the device flow."
        )

    def is_authenticated(self) -> bool:
        """True if either an API key or stored token is present."""
        if self.api_key:
            return True
        return super().is_authenticated()

    # ── OAuth authorization-code flow ────────────────────────────

    def get_auth_url(
        self,
        redirect_uri: str,
        state: str = "",
        **kwargs: Any,
    ) -> str:
        """Build the OpenAI OAuth authorization URL."""
        from urllib.parse import urlencode

        if not self.client_id:
            raise AuthConfigError(
                "OpenAI OAuth requires a client_id (configure it under "
                "`auth.providers.openai.client_id` in config.yaml)."
            )
        scope: str = kwargs.pop("scope", self.config.get("scope", "openid profile email offline_access"))
        params: dict[str, str] = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
        }
        if state:
            params["state"] = state
        audience = kwargs.pop("audience", self.config.get("audience", "https://api.openai.com/v1"))
        if audience:
            params["audience"] = audience
        params.update({k: str(v) for k, v in kwargs.items()})
        return f"{self.DEFAULT_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenResponse:
        """Exchange an authorization code for an OpenAI access token."""
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
        """Refresh an OpenAI OAuth token."""
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

    # ── Device flow (Codex) ─────────────────────────────────────

    def device_flow_client(self) -> DeviceFlowClient:
        """Return a configured :class:`DeviceFlowClient` for OpenAI."""
        return DeviceFlowClient(
            device_authorization_url=self.DEFAULT_DEVICE_URL,
            token_url=self.DEFAULT_TOKEN_URL,
            client_id=self.client_id or "auth0-openai-client",
            audience=self.config.get("audience", "https://api.openai.com/v1"),
            default_scope=self.config.get("scope", "openid profile email offline_access"),
        )

    async def device_login(self, timeout: int = 600) -> TokenResponse:
        """Run the full device-flow login for OpenAI Codex accounts."""
        if not self.client_id:
            raise AuthConfigError(
                "OpenAI device flow requires a client_id. "
                "Set `auth.providers.openai.client_id` in config.yaml."
            )
        client = self.device_flow_client()
        token = await client.run(timeout=timeout)
        self.save_token(token)
        return token

    # ── User info ───────────────────────────────────────────────

    async def get_user_info(self, access_token: str) -> UserInfo:
        """Fetch the OpenAI user profile.

        The OpenAI REST API does not expose a public ``/me`` endpoint,
        so we hit ``/models`` and return a synthetic profile.  When a
        provider-side profile endpoint becomes available callers can
        override this method.
        """
        data = await self._get_json(
            f"{self.api_base.rstrip('/')}/models",
            bearer=access_token,
        )
        # ``data`` is a list-shaped response with ``data: [...]``.
        # We synthesise a user-id from the response or fall back to
        # a deterministic placeholder so callers always get something
        # back.
        models = data.get("data") if isinstance(data, dict) else None
        user_id = "openai"
        return UserInfo(
            provider=self.provider_name,
            user_id=user_id,
            email=None,
            name="OpenAI User",
            username=None,
            avatar_url=None,
            raw={"models_count": len(models) if isinstance(models, list) else 0},
        )

    # ── Internal helpers ─────────────────────────────────────────

    def _parse_token_response(self, data: dict[str, Any]) -> TokenResponse:
        """Convert a raw OpenAI token dict into :class:`TokenResponse`."""
        access = data.get("access_token")
        if not access:
            raise AuthError(f"OpenAI token response missing access_token: {data}")
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

    async def call_api(
        self,
        path: str,
        method: str = "GET",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Convenience helper to make a signed OpenAI REST call."""
        import httpx

        api_key = self._resolved_api_key()
        url = f"{self.api_base.rstrip('/')}{path}"
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {api_key}"
        async with httpx.AsyncClient(timeout=kwargs.pop("timeout", 30.0)) as client:
            resp = await client.request(method, url, headers=headers, **kwargs)
        if resp.status_code >= 400:
            raise AuthError(f"OpenAI API error: HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()
        except ValueError as exc:
            raise AuthError("OpenAI API returned non-JSON") from exc


register_auth("openai", OpenAIAuth)


__all__ = ["OpenAIAuth"]
