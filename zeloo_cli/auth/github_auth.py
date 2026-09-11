"""GitHub OAuth authentication.

Supports two flows:

* **OAuth Web Flow** — standard authorization-code flow for CLI tools
  that can host a local callback server.
* **Device Flow** — RFC 8628 device-authorization flow for headless
  environments (CI, SSH sessions, Docker).  Reuses
  :class:`DeviceFlowClient` so the polling logic stays in one place.

Default scopes: ``repo``, ``read:user``, ``user:email`` — enough for
the most common Zeloo use cases (read/write repos, fetch user info,
and verify the primary email).
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

from zeloo_cli.auth.base import AuthConfigError, AuthError, BaseAuth, TokenResponse, UserInfo
from zeloo_cli.auth.device_flow import DeviceFlowClient
from zeloo_cli.auth.registry import register_auth

logger = logging.getLogger(__name__)


class GitHubAuth(BaseAuth):
    """Authenticate against the GitHub OAuth endpoints."""

    provider_name: str = "github"

    DEFAULT_AUTH_URL = "https://github.com/login/oauth/authorize"
    DEFAULT_TOKEN_URL = "https://github.com/login/oauth/access_token"
    DEFAULT_DEVICE_URL = "https://github.com/login/device/code"
    DEFAULT_API_BASE = "https://api.github.com"

    DEFAULT_SCOPES = "repo read:user user:email"

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(client_id=client_id, client_secret=client_secret, **kwargs)
        self.api_base: str = self.config.get("api_base", self.DEFAULT_API_BASE)
        self.default_scope: str = self.config.get("scope", self.DEFAULT_SCOPES)
        self.allow_signup: bool = bool(self.config.get("allow_signup", True))

    # ── Web flow ────────────────────────────────────────────────

    def get_auth_url(
        self,
        redirect_uri: str,
        state: str = "",
        **kwargs: Any,
    ) -> str:
        """Build the GitHub OAuth authorization URL."""
        if not self.client_id:
            raise AuthConfigError(
                "GitHub OAuth requires a client_id. "
                "Register an OAuth App at https://github.com/settings/developers."
            )
        params: dict[str, str] = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": kwargs.pop("scope", self.default_scope),
            "allow_signup": kwargs.pop(
                "allow_signup", "true" if self.allow_signup else "false"
            ),
        }
        if state:
            params["state"] = state
        params.update({k: str(v) for k, v in kwargs.items()})
        return f"{self.DEFAULT_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenResponse:
        """Exchange a GitHub authorization code for an access token.

        GitHub requires the ``Accept: application/json`` header for
        token responses; otherwise it returns URL-encoded bodies
        that are awkward to parse.
        """
        if not self.client_id:
            raise AuthConfigError("client_id is required for GitHub OAuth")
        data = await self._post_form(
            self.DEFAULT_TOKEN_URL,
            {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
        return self._parse_token_response(data)

    async def refresh_token(self, refresh_token: str) -> TokenResponse:
        """GitHub does not support refresh tokens for OAuth Apps.

        Raises :class:`AuthError` so the caller knows to re-run the
        full device / web flow.
        """
        raise AuthError(
            "GitHub OAuth Apps do not support refresh tokens. "
            "Re-run the login flow to obtain a new access token."
        )

    # ── Device flow ─────────────────────────────────────────────

    def device_flow_client(self, scope: str | None = None) -> DeviceFlowClient:
        """Return a :class:`DeviceFlowClient` configured for GitHub."""
        return DeviceFlowClient(
            device_authorization_url=self.DEFAULT_DEVICE_URL,
            token_url=self.DEFAULT_TOKEN_URL,
            client_id=self.client_id,
            default_scope=scope or self.default_scope,
        )

    async def device_login(
        self,
        scope: str | None = None,
        timeout: int = 600,
    ) -> TokenResponse:
        """Run the GitHub device flow end-to-end.

        Args:
            scope: Space-separated scopes.  Defaults to
                ``self.default_scope``.
            timeout: Polling budget in seconds.

        Returns:
            The :class:`TokenResponse` containing the issued token.
        """
        if not self.client_id:
            raise AuthConfigError(
                "GitHub device flow requires a client_id. "
                "Register a GitHub App with device-flow enabled."
            )
        client = self.device_flow_client(scope=scope)
        token = await client.run(timeout=timeout)
        self.save_token(token)
        return token

    # ── User info ───────────────────────────────────────────────

    async def get_user_info(self, access_token: str) -> UserInfo:
        """Fetch the GitHub profile of the authenticated user.

        GitHub exposes ``/user`` for profile data and ``/user/emails``
        for the primary email.  We hit both in parallel and merge the
        results.
        """
        import asyncio

        user_url = f"{self.api_base.rstrip('/')}/user"
        emails_url = f"{self.api_base.rstrip('/')}/user/emails"

        async def _both() -> tuple[dict[str, Any], list[dict[str, Any]]]:
            async_calls: list[Any] = []
            # Defer the asyncio.gather until we're inside the loop.
            user_task = asyncio.create_task(self._get_json(user_url, bearer=access_token))
            emails_task = asyncio.create_task(self._get_json(emails_url, bearer=access_token))
            return await asyncio.gather(user_task, emails_task)

        user_data, emails_data = await _both()
        primary_email: str | None = None
        for entry in emails_data if isinstance(emails_data, list) else []:
            if isinstance(entry, dict) and entry.get("primary"):
                primary_email = entry.get("email")
                break
        if primary_email is None and isinstance(user_data, dict):
            primary_email = user_data.get("email")
        return UserInfo(
            provider=self.provider_name,
            user_id=str(user_data.get("id", "")),
            email=primary_email,
            name=user_data.get("name"),
            username=user_data.get("login"),
            avatar_url=user_data.get("avatar_url"),
            raw={"user": user_data, "emails": emails_data},
        )

    async def list_emails(self, access_token: str) -> list[dict[str, Any]]:
        """Return all verified email addresses for the user."""
        emails = await self._get_json(
            f"{self.api_base.rstrip('/')}/user/emails",
            bearer=access_token,
        )
        return emails if isinstance(emails, list) else []

    # ── Internal helpers ─────────────────────────────────────────

    def _parse_token_response(self, data: dict[str, Any]) -> TokenResponse:
        access = data.get("access_token")
        if not access:
            raise AuthError(
                f"GitHub token response missing access_token: {data}"
            )
        # GitHub's ``scope`` field is space-separated; ``scope`` may be
        # absent on response (it lives in the auth URL).  Keep it as-is.
        scope = data.get("scope", "")
        expires_in = data.get("expires_in")
        return TokenResponse(
            access_token=access,
            token_type=data.get("token_type", "bearer"),
            refresh_token=None,  # not issued for OAuth Apps
            expires_in=int(expires_in) if expires_in is not None else None,
            scope=scope,
            extras={
                k: v
                for k, v in data.items()
                if k
                not in {
                    "access_token",
                    "token_type",
                    "scope",
                    "expires_in",
                }
            },
        )


register_auth("github", GitHubAuth)


__all__ = ["GitHubAuth"]
