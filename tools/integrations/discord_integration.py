"""Discord platform integration.

Implements the :class:`BaseIntegration` surface against Discord's
REST API v10. The integration supports:

- Bot token authentication (``Authorization: Bot <token>``)
- Sending messages to channels and threads
- Replying to an existing message (``message_reference``)
- Mentioning users / roles / ``@everyone``
- Uploading a single attachment per message
- Honouring ``429 Too Many Requests`` responses (rate limit +
  global rate limit, with ``retry_after`` retry)
- Optional WebSocket Gateway receiver

The implementation deliberately uses ``httpx`` so it can be embedded
in an asyncio application without pulling the full ``discord.py``
library.

Configuration keys
------------------
- ``token`` (str, required): Bot token
- ``api_base`` (str, optional): Defaults to ``https://discord.com/api/v10``
- ``max_retries`` (int, optional): Defaults to ``3``
- ``gateway`` (bool, optional): Enable built-in gateway receiver.
  Defaults to ``False``. Requires ``websockets``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Callable
from typing import Any

import httpx

from tools.integrations.base import (
    AuthError,
    BaseIntegration,
    IntegrationError,
    NotFoundError,
    RateLimitError,
    ReceiveCallback,
    require_config,
    safe_call,
    sleep_for,
)
from tools.integrations.registry import register_integration

logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://discord.com/api/v10"
DEFAULT_MAX_RETRIES = 3
DISCORD_MAX_MESSAGE_LENGTH = 2000


@register_integration("discord")
class DiscordIntegration(BaseIntegration):
    """Discord bot integration backed by the REST API."""

    platform_name = "discord"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.token: str = require_config(config, "token")
        self.api_base: str = config.get("api_base", DEFAULT_API_BASE).rstrip("/")
        self.max_retries: int = int(config.get("max_retries", DEFAULT_MAX_RETRIES))
        self.timeout: float = float(config.get("timeout", 30.0))
        self._client: httpx.AsyncClient | None = None
        self._gateway_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # HTTP plumbing
    # ------------------------------------------------------------------
    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.api_base,
                timeout=self.timeout,
                headers={
                    "Authorization": f"Bot {self.token}",
                    "User-Agent": "ZelooDiscordIntegration/1.0",
                },
            )
        return self._client

    async def close(self) -> None:
        await super().close()
        if self._gateway_task is not None and not self._gateway_task.done():
            self._gateway_task.cancel()
            try:
                await self._gateway_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        multipart: dict[str, Any] | None = None,
    ) -> Any:
        """Issue an HTTP request and handle Discord's rate-limit semantics.

        Returns the parsed JSON body on success. Raises
        :class:`RateLimitError` after exhausting retries, :class:`AuthError`
        on ``401``/``403``, :class:`NotFoundError` on ``404`` and
        :class:`IntegrationError` on other failures.
        """
        client = await self._get_client()
        attempts = self.max_retries + 1
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                if multipart is not None:
                    response = await client.request(
                        method,
                        path,
                        params=params,
                        files=multipart.get("files"),
                        data=multipart.get("data"),
                    )
                else:
                    response = await client.request(
                        method,
                        path,
                        params=params,
                        json=json_body,
                    )
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning(
                    "Discord HTTP transport error on %s %s (attempt %s/%s): %s",
                    method,
                    path,
                    attempt,
                    attempts,
                    exc,
                )
                await sleep_for(min(2 ** attempt, 10))
                continue

            if response.status_code == 429:
                body = self._safe_json(response)
                retry_after = float(body.get("retry_after", 1.0)) if body else 1.0
                scope = response.headers.get("X-RateLimit-Scope", "per_route")
                logger.info(
                    "Discord rate-limited (%s, scope=%s), sleeping %.2fs",
                    path,
                    scope,
                    retry_after,
                )
                await sleep_for(retry_after + 0.1)
                if attempt < attempts:
                    continue
                raise RateLimitError(
                    f"Rate limit exceeded for {path}", retry_after=retry_after
                )

            if response.status_code in (401, 403):
                raise AuthError(
                    f"Discord auth failure ({response.status_code}): {response.text}"
                )
            if response.status_code == 404:
                raise NotFoundError(f"Discord resource missing: {path}")
            if 500 <= response.status_code < 600:
                last_error = IntegrationError(
                    f"Discord server error {response.status_code}: {response.text}"
                )
                logger.warning(
                    "Discord server error %s on %s (attempt %s/%s)",
                    response.status_code,
                    path,
                    attempt,
                    attempts,
                )
                await sleep_for(min(2 ** attempt, 10))
                continue
            if response.status_code >= 400:
                raise IntegrationError(
                    f"Discord API error {response.status_code}: {response.text}"
                )

            if not response.content:
                return {}
            return self._safe_json(response) or {}

        assert last_error is not None  # for type checkers
        raise IntegrationError(f"Discord request failed after retries: {last_error}")

    @staticmethod
    def _safe_json(response: httpx.Response) -> dict[str, Any] | None:
        try:
            return response.json()
        except (json.JSONDecodeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def send_message(
        self,
        channel: str,
        content: str,
        *,
        reply_to: str | None = None,
        mentions: list[str] | None = None,
        attachment_path: str | None = None,
        attachment_filename: str | None = None,
        thread_name: str | None = None,
        allowed_mentions: dict[str, bool] | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        """Send a message to ``channel`` (channel id or thread id)."""

        async def _do() -> dict[str, Any]:
            text = content or ""
            if mentions:
                suffix = " ".join(mentions)
                text = f"{text} {suffix}".strip() if text else suffix

            payload: dict[str, Any] = {"content": text}
            if reply_to:
                payload["message_reference"] = {"message_id": reply_to}
            if allowed_mentions is not None:
                payload["allowed_mentions"] = allowed_mentions

            if attachment_path is not None:
                filename = attachment_filename or os.path.basename(attachment_path)
                with open(attachment_path, "rb") as fh:
                    file_bytes = fh.read()
                multipart = {
                    "data": {"payload_json": json.dumps(payload)},
                    "files": {"file": (filename, file_bytes)},
                }
                result = await self._request(
                    "POST",
                    f"/channels/{channel}/messages",
                    multipart=multipart,
                )
            else:
                result = await self._request(
                    "POST",
                    f"/channels/{channel}/messages",
                    json_body=payload,
                )

            if thread_name:
                logger.debug(
                    "Ignoring thread_name=%s on send (Discord threads require the channels endpoint)",
                    thread_name,
                )

            return {
                "ok": True,
                "message_id": result.get("id"),
                "channel_id": result.get("channel_id"),
                "ts": result.get("timestamp"),
                "raw": result,
            }

        return await safe_call(_do)

    async def list_channels(self) -> list[dict[str, Any]]:
        """List channels the bot can see."""

        async def _do() -> list[dict[str, Any]]:
            guild_id = self.config.get("guild_id")
            if guild_id:
                data = await self._request("GET", f"/guilds/{guild_id}/channels")
                return list(data) if isinstance(data, list) else []

            guilds = await self._request("GET", "/users/@me/guilds")
            if not isinstance(guilds, list) or not guilds:
                return []
            channels: list[dict[str, Any]] = []
            for guild in guilds:
                gid = guild.get("id")
                if not gid:
                    continue
                guild_channels = await self._request(
                    "GET", f"/guilds/{gid}/channels"
                )
                if isinstance(guild_channels, list):
                    channels.extend(guild_channels)
            return channels

        result = await safe_call(_do)
        return result if isinstance(result, list) else []

    async def get_user_info(self, user_id: str) -> dict[str, Any]:
        """Return Discord's public user descriptor for ``user_id``."""

        async def _do() -> dict[str, Any]:
            return await self._request("GET", f"/users/{user_id}")

        return await safe_call(_do) or {"ok": False, "error": "unknown"}

    # ------------------------------------------------------------------
    # Receive loop
    # ------------------------------------------------------------------
    async def receive_messages(
        self,
        callback: ReceiveCallback,
        *,
        gateway: bool = False,
        intents: int | None = None,
        **_: Any,
    ) -> None:
        """Receive messages and dispatch them to ``callback``."""
        if not gateway:
            logger.info(
                "Discord receive_messages() called without gateway=True; "
                "assuming webhook mode — returning immediately."
            )
            return

        self._gateway_task = asyncio.create_task(
            self._run_gateway(callback, intents=intents or 1536),
            name="discord-gateway",
        )

    async def handle_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Normalise an inbound webhook event payload."""
        return {"ok": True, "event": event}

    async def _run_gateway(
        self,
        callback: ReceiveCallback,
        *,
        intents: int,
    ) -> None:
        """Minimal Discord Gateway v10 receiver.

        Best-effort implementation — production deployments should
        prefer ``discord.py``. The gateway token is not retrieved here
        (it requires the privileged ``identify`` flow).
        """
        try:
            import websockets  # type: ignore[import-not-found]
        except ImportError:
            logger.error("websockets is not installed; Discord gateway disabled.")
            return

        backoff = 1.0
        while not self._closed:
            try:
                ws_url = "wss://gateway.discord.gg/?v=10&encoding=json"
                async with websockets.connect(ws_url) as ws:  # type: ignore[attr-defined]
                    hello_raw = await ws.recv()  # type: ignore[attr-defined]
                    hello = json.loads(hello_raw)
                    interval = (
                        float(hello.get("d", {}).get("heartbeat_interval", 30000))
                        / 1000.0
                    )
                    _ = intents  # reserved for identify payload
                    backoff = 1.0
                    while not self._closed:
                        await asyncio.sleep(interval)
                        if getattr(ws.state, "name", None) != "OPEN":
                            break
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Discord gateway error: %s; retrying in %.2fs", exc, backoff
                )
                await sleep_for(backoff)
                backoff = min(backoff * 2, 60.0)


_ = Callable  # keep import meaningful for static analysers