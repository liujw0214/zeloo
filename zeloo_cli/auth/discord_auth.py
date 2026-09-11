"""Discord authentication.

Discord supports two distinct authentication models:

* **Bot Token** — long-lived tokens issued by the Developer Portal.
  These bypass the OAuth dance entirely.  This is the recommended
  flow for the Zeloo CLI because it avoids hosting a callback server.
* **OAuth2 Authorization Code** — for user-context operations
  (sending messages on behalf of a user, accessing user guilds).
  Implemented below for completeness.

The bot token also enables a thin wrapper around the bot-message REST
endpoints so callers can ``send_message(channel_id, content)`` without
re-implementing the auth headers.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlencode

from zeloo_cli.auth.base import AuthConfigError, AuthError, BaseAuth, TokenResponse, UserInfo
from zeloo_cli.auth.registry import register_auth

logger = logging.getLogger(__name__)


class DiscordAuth(BaseAuth):
    """Authenticate with Discord via bot token or OAuth2 user flow."""

    provider_name: str = "discord"

    DEFAULT_AUTH_URL = "https://discord.com/oauth2/authorize"
    DEFAULT_TOKEN_URL = "https://discord.com/api/oauth2/token"
    DEFAULT_REVOKE_URL = "https://discord.com/api/oauth2/token/revoke"
    DEFAULT_API_BASE = "https://discord.com/api/v10"

    # Default OAuth scopes for a "send messages on behalf of user" bot.
    DEFAULT_SCOPES = "identify email guilds bot messages.read"

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        bot_token: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(client_id=client_id, client_secret=client_secret, **kwargs)
        # Resolution order for the bot token: explicit kwarg > env > client_secret.
        self.bot_token: str = (
            bot_token
            or os.environ.get("DISCORD_BOT_TOKEN", "")
            or self.client_secret
        )
        self.api_base: str = self.config.get("api_base", self.DEFAULT_API_BASE)
        self.default_scope: str = self.config.get("scope", self.DEFAULT_SCOPES)

    # ── Authentication helpers ──────────────────────────────────

    def _resolved_token(self) -> str:
        """Return the bot token or a stored user-OAuth access token."""
        if self.bot_token:
            return self.bot_token
        from zeloo_cli.auth.token_store import TokenStore

        stored = TokenStore().load(self.provider_name)
        if stored and stored.get("access_token"):
            return str(stored["access_token"])
        raise AuthConfigError(
            "Discord credentials not configured. "
            "Set DISCORD_BOT_TOKEN or pass bot_token=. "
            "For user OAuth, run `zeloo auth login discord`."
        )

    def is_authenticated(self) -> bool:
        if self.bot_token:
            return True
        return super().is_authenticated()

    # ── OAuth2 user flow ────────────────────────────────────────

    def get_auth_url(
        self,
        redirect_uri: str,
        state: str = "",
        **kwargs: Any,
    ) -> str:
        """Build the Discord OAuth authorization URL."""
        if not self.client_id:
            raise AuthConfigError(
                "Discord OAuth requires a client_id. "
                "Register an application at https://discord.com/developers/applications."
            )
        scope: str = kwargs.pop("scope", self.default_scope)
        params: dict[str, str] = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
        }
        if state:
            params["state"] = state
        # Optional ``permissions`` integer for the bot scope.
        permissions = kwargs.pop("permissions", self.config.get("permissions"))
        if permissions is not None:
            params["permissions"] = str(permissions)
        params.update({k: str(v) for k, v in kwargs.items()})
        return f"{self.DEFAULT_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> TokenResponse:
        """Exchange an authorization code for a Discord access token."""
        if not self.client_id or not self.client_secret:
            raise AuthConfigError(
                "Discord OAuth requires both client_id and client_secret."
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
        """Refresh a Discord OAuth access token."""
        if not self.client_id or not self.client_secret:
            raise AuthConfigError(
                "Discord OAuth requires both client_id and client_secret."
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
        return self._parse_token_response(data)

    async def revoke(self, token: str) -> bool:
        """Revoke a Discord OAuth token."""
        if not self.client_id or not self.client_secret:
            raise AuthConfigError(
                "Discord token revocation requires client credentials."
            )
        data = await self._post_form(
            self.DEFAULT_REVOKE_URL,
            {
                "token": token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        # Discord returns an empty 200 on success.
        return True

    # ── User info ───────────────────────────────────────────────

    async def get_user_info(self, access_token: str) -> UserInfo:
        """Fetch the Discord ``@me`` profile.

        Uses the ``users/@me`` endpoint, which works for both bot
        tokens (returns the bot user) and user OAuth tokens.
        """
        data = await self._get_json(
            f"{self.api_base.rstrip('/')}/users/@me",
            bearer=access_token,
        )
        username = data.get("username", "")
        discriminator = data.get("discriminator", "0")
        # Discord migrated to unique usernames (Pomelo) so we keep
        # both forms in ``raw`` for callers that care.
        full_username = (
            f"{username}#{discriminator}"
            if discriminator and discriminator != "0"
            else username
        )
        return UserInfo(
            provider=self.provider_name,
            user_id=str(data.get("id", "")),
            email=data.get("email"),
            name=data.get("global_name") or username or None,
            username=full_username or None,
            avatar_url=self._avatar_url(data),
            raw=data,
        )

    @staticmethod
    def _avatar_url(user: dict[str, Any]) -> str | None:
        """Build a Discord CDN URL for the user's avatar, if any."""
        user_id = user.get("id")
        avatar = user.get("avatar")
        if not user_id or not avatar:
            return None
        ext = "gif" if str(avatar).startswith("a_") else "png"
        return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar}.{ext}"

    # ── Bot REST helpers ────────────────────────────────────────

    async def send_message(
        self,
        channel_id: str,
        content: str,
        *,
        embed: dict[str, Any] | None = None,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        """Send a message to a channel via the bot token.

        Args:
            channel_id: Target text channel ID.
            content: Plain-text content (max 2000 chars).
            embed: Optional embed object.
            timeout: Request timeout in seconds.

        Returns:
            The created message payload.

        Raises:
            AuthError: On HTTP failure or missing bot token.
        """
        import httpx

        token = self._resolved_token()
        payload: dict[str, Any] = {"content": content}
        if embed:
            payload["embed"] = embed
        url = f"{self.api_base.rstrip('/')}/channels/{channel_id}/messages"
        headers = {
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code == 429:
            # Rate-limited — surface the retry-after hint in the error.
            retry_after = resp.headers.get("retry-after", "?")
            raise AuthError(
                f"Discord rate limit hit; retry after {retry_after}s"
            )
        if resp.status_code >= 400:
            raise AuthError(
                f"Discord send_message failed: HTTP {resp.status_code}: {resp.text[:200]}"
            )
        return resp.json()

    async def list_guilds(self, access_token: str | None = None) -> list[dict[str, Any]]:
        """List the guilds the authenticated user/bot is in."""
        token = access_token or self._resolved_token()
        data = await self._get_json(
            f"{self.api_base.rstrip('/')}/users/@me/guilds",
            bearer=token,
        )
        return data if isinstance(data, list) else []

    # ── Internal helpers ─────────────────────────────────────────

    def _parse_token_response(self, data: dict[str, Any]) -> TokenResponse:
        access = data.get("access_token")
        if not access:
            raise AuthError(f"Discord token response missing access_token: {data}")
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


register_auth("discord", DiscordAuth)


__all__ = ["DiscordAuth"]
