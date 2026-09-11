"""Google OAuth 2.0 authentication.

Implements Google's standard authorization-code flow as documented at
https://developers.google.com/identity/protocols/oauth2/web-server.

Supports arbitrary scope sets; common presets include ``openid email
profile`` for basic identity, plus ``https://www.googleapis.com/auth/gmail.modify``
and ``https://www.googleapis.com/auth/drive`` for Gmail / Drive APIs.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

from zeloo_cli.auth.base import AuthConfigError, AuthError, BaseAuth, TokenResponse, UserInfo
from zeloo_cli.auth.registry import register_auth

logger = logging.getLogger(__name__)


class GoogleAuth(BaseAuth):
    """Authenticate against Google's OAuth 2.0 endpoints."""

    provider_name: str = "google"

    DEFAULT_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    DEFAULT_TOKEN_URL = "https://oauth2.googleapis.com/token"
    DEFAULT_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
    DEFAULT_REVOKE_URL = "https://oauth2.googleapis.com/revoke"

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(client_id=client_id, client_secret=client_secret, **kwargs)
        self.userinfo_url: str = self.config.get(
            "userinfo_url", self.DEFAULT_USERINFO_URL
        )
        self.revoke_url: str = self.config.get("revoke_url", self.DEFAULT_REVOKE_URL)

    # ── Authorization URL ───────────────────────────────────────

    def get_auth_url(
        self,
        redirect_uri: str,
        state: str = "",
        **kwargs: Any,
    ) -> str:
        """Build the Google OAuth authorization URL.

        Args:
            redirect_uri: Must match a URI registered in the Google
                Cloud Console for this client.
            state: CSRF token.  Echoed back unchanged on redirect.
            **kwargs: Overrides for any of the standard OAuth params
                (``scope``, ``access_type``, ``prompt``, ``login_hint``).

        Returns:
            The fully formed authorization URL.
        """
        if not self.client_id:
            raise AuthConfigError(
                "Google OAuth requires a client_id. "
                "Configure OAuth 2.0 credentials in Google Cloud Console."
            )
        params: dict[str, str] = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": kwargs.pop(
                "scope",
                self.config.get("scope", "openid email profile"),
            ),
            "access_type": kwargs.pop("access_type", self.config.get("access_type", "offline")),
            "include_granted_scopes": kwargs.pop(
                "include_granted_scopes",
                self.config.get("include_granted_scopes", "true"),
            ),
        }
        if state:
            params["state"] = state
        prompt = kwargs.pop("prompt", self.config.get("prompt", "consent"))
        if prompt:
            params["prompt"] = prompt
        login_hint = kwargs.pop("login_hint", self.config.get("login_hint", ""))
        if login_hint:
            params["login_hint"] = login_hint
        params.update({k: str(v) for k, v in kwargs.items()})
        return f"{self.DEFAULT_AUTH_URL}?{urlencode(params)}"

    # ── Token endpoints ─────────────────────────────────────────

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenResponse:
        """Exchange a Google authorization code for tokens."""
        if not self.client_id or not self.client_secret:
            raise AuthConfigError(
                "Google OAuth requires both client_id and client_secret."
            )
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
        """Refresh a Google OAuth access token.

        Google does not issue a new refresh token on refresh; the
        existing one continues to work and is carried forward
        transparently.
        """
        if not self.client_id or not self.client_secret:
            raise AuthConfigError(
                "Google OAuth requires both client_id and client_secret."
            )
        data = await self._post_form(
            self.DEFAULT_TOKEN_URL,
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        token = self._parse_token_response(data)
        if not token.refresh_token:
            token.refresh_token = refresh_token
        return token

    # ── User info / revocation ──────────────────────────────────

    async def get_user_info(self, access_token: str) -> UserInfo:
        """Fetch the user's Google profile via the OpenID userinfo endpoint."""
        data = await self._get_json(self.userinfo_url, bearer=access_token)
        return UserInfo(
            provider=self.provider_name,
            user_id=str(data.get("sub", "")),
            email=data.get("email"),
            name=data.get("name"),
            username=None,
            avatar_url=data.get("picture"),
            raw=data,
        )

    async def revoke(self, token: str) -> bool:
        """Revoke an access (or refresh) token at Google.

        Returns True if Google acknowledged the revocation.
        """
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                self.revoke_url,
                params={"token": token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        return resp.status_code == 200

    # ── Gmail / Drive convenience helpers ───────────────────────

    async def gmail_profile(self, access_token: str) -> dict[str, Any]:
        """Return the Gmail send-as profile of the authenticated user."""
        return await self._get_json(
            "https://gmail.googleapis.com/gmail/v1/users/me/profile",
            bearer=access_token,
        )

    async def drive_about(self, access_token: str) -> dict[str, Any]:
        """Return Drive ``about`` metadata for the authenticated user."""
        return await self._get_json(
            "https://www.googleapis.com/drive/v3/about?fields=user,storageQuota",
            bearer=access_token,
        )

    # ── Internal helpers ─────────────────────────────────────────

    def _parse_token_response(self, data: dict[str, Any]) -> TokenResponse:
        access = data.get("access_token")
        if not access:
            raise AuthError(f"Google token response missing access_token: {data}")
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


register_auth("google", GoogleAuth)


__all__ = ["GoogleAuth"]
