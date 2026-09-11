"""Anthropic authentication.

Anthropic uses static API keys (``sk-ant-...``) for normal Claude API
access.  An optional Console OAuth flow is supported for users with
Anthropic Console accounts that want to provision keys programmatically.

Key resolution
--------------

1. ``api_key`` keyword argument.
2. ``ANTHROPIC_API_KEY`` environment variable.
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


class AnthropicAuth(BaseAuth):
    """Authenticate with Anthropic via API key or Console OAuth."""

    provider_name: str = "anthropic"

    DEFAULT_AUTH_URL = "https://console.anthropic.com/oauth/authorize"
    DEFAULT_TOKEN_URL = "https://console.anthropic.com/oauth/token"
    DEFAULT_API_BASE = "https://api.anthropic.com"

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
            or os.environ.get("ANTHROPIC_API_KEY", "")
            or client_id
            or client_secret
        )
        self.api_base: str = self.config.get("api_base", self.DEFAULT_API_BASE)
        # Optional per-request beta toggles (e.g. prompt-caching).
        self.beta_headers: list[str] = list(self.config.get("beta_headers", []))

    # ── API-key helpers ─────────────────────────────────────────

    def _resolved_api_key(self) -> str:
        if self.api_key:
            return self.api_key
        from zeloo_cli.auth.token_store import TokenStore

        stored = TokenStore().load(self.provider_name)
        if stored and stored.get("access_token"):
            return str(stored["access_token"])
        raise AuthConfigError(
            "Anthropic credentials not configured. "
            "Set ANTHROPIC_API_KEY or run `zeloo auth login anthropic`."
        )

    def is_authenticated(self) -> bool:
        if self.api_key:
            return True
        return super().is_authenticated()

    # ── OAuth authorization-code flow (Console) ──────────────────

    def get_auth_url(
        self,
        redirect_uri: str,
        state: str = "",
        **kwargs: Any,
    ) -> str:
        """Build the Anthropic Console OAuth authorization URL."""
        if not self.client_id:
            raise AuthConfigError(
                "Anthropic Console OAuth requires a client_id. "
                "Register an OAuth app in the Anthropic Console and "
                "set `auth.providers.anthropic.client_id` in config.yaml."
            )
        scope: str = kwargs.pop("scope", self.config.get("scope", "org:create_api_key"))
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
        """Exchange an authorization code for an Anthropic access token."""
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
        """Refresh an Anthropic OAuth token."""
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

    # ── User info ───────────────────────────────────────────────

    async def get_user_info(self, access_token: str) -> UserInfo:
        """Best-effort user profile for the Anthropic Console.

        Anthropic does not currently expose a generic ``/me`` endpoint
        for OAuth tokens, so we return a synthetic profile derived
        from the access-token metadata (sub-claim of a JWT if
        available) and stash the raw response in ``raw`` so callers
        can introspect.
        """
        import base64
        import json as _json

        sub: str | None = None
        email: str | None = None
        name: str | None = None
        try:
            parts = access_token.split(".")
            if len(parts) == 3:
                padded = parts[1] + "=" * (-len(parts[1]) % 4)
                payload = _json.loads(base64.urlsafe_b64decode(padded))
                sub = payload.get("sub")
                email = payload.get("email")
                name = payload.get("name")
        except Exception:
            logger.debug("Could not decode Anthropic access token JWT", exc_info=True)

        return UserInfo(
            provider=self.provider_name,
            user_id=sub or "anthropic-user",
            email=email,
            name=name,
            username=None,
            avatar_url=None,
            raw={"token_sub": sub, "token_email": email},
        )

    # ── REST helper ─────────────────────────────────────────────

    async def call_api(
        self,
        path: str,
        method: str = "POST",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Convenience helper to make a signed Anthropic REST call."""
        import httpx

        api_key = self._resolved_api_key()
        url = f"{self.api_base.rstrip('/')}{path}"
        headers = dict(kwargs.pop("headers", {}))
        headers["x-api-key"] = api_key
        headers.setdefault("anthropic-version", "2023-06-01")
        for beta in self.beta_headers:
            headers.setdefault("anthropic-beta", beta)
        async with httpx.AsyncClient(timeout=kwargs.pop("timeout", 30.0)) as client:
            resp = await client.request(method, url, headers=headers, **kwargs)
        if resp.status_code >= 400:
            raise AuthError(f"Anthropic API error: HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            return resp.json()
        except ValueError as exc:
            raise AuthError("Anthropic API returned non-JSON") from exc

    # ── Internal helpers ─────────────────────────────────────────

    def _parse_token_response(self, data: dict[str, Any]) -> TokenResponse:
        access = data.get("access_token")
        if not access:
            raise AuthError(f"Anthropic token response missing access_token: {data}")
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


register_auth("anthropic", AnthropicAuth)


__all__ = ["AnthropicAuth"]
