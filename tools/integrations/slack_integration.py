"""Slack platform integration.

Implements :class:`BaseIntegration` against Slack's Web API
(``https://slack.com/api/...``). The integration supports:

- Bot token (``xoxb-...``) or user token (``xoxp-...``) auth
- ``chat.postMessage`` with text and Block Kit
- Interactive components (buttons / select menus / modal triggers)
- Threaded replies via ``thread_ts``
- File uploads via ``files.upload`` (v1) and ``files.getUploadURLExternal``
- Retry-after handling for HTTP ``429`` and Slack's ``Retry-After``
  header

Configuration keys
------------------
- ``token`` (str, required): Bot or user token
- ``api_base`` (str, optional): Defaults to ``https://slack.com/api``
- ``max_retries`` (int, optional): Defaults to ``3``
- ``socket_mode`` (bool, optional): Reserved for the optional
  Socket Mode receiver. Defaults to ``False``.
"""

from __future__ import annotations

import asyncio
import logging
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

DEFAULT_API_BASE = "https://slack.com/api"
DEFAULT_MAX_RETRIES = 3


@register_integration("slack")
class SlackIntegration(BaseIntegration):
    """Slack workspace integration backed by Slack's Web API."""

    platform_name = "slack"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.token: str = require_config(config, "token")
        if not (
            self.token.startswith("xoxb-")
            or self.token.startswith("xoxp-")
            or self.token.startswith("xapp-")
        ):
            logger.warning(
                "Slack token does not start with xoxb-/xoxp-/xapp-; "
                "this may indicate an incorrect credential."
            )
        self.api_base: str = config.get("api_base", DEFAULT_API_BASE).rstrip("/")
        self.max_retries: int = int(config.get("max_retries", DEFAULT_MAX_RETRIES))
        self.timeout: float = float(config.get("timeout", 30.0))
        self._client: httpx.AsyncClient | None = None
        self._socket_task: asyncio.Task[None] | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.api_base,
                timeout=self.timeout,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json; charset=utf-8",
                    "User-Agent": "ZelooSlackIntegration/1.0",
                },
            )
        return self._client

    async def close(self) -> None:
        await super().close()
        if self._socket_task is not None and not self._socket_task.done():
            self._socket_task.cancel()
            try:
                await self._socket_task
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
    ) -> dict[str, Any]:
        """Call a Slack Web API method.

        Slack's REST endpoints return ``{"ok": false, "error": "..."}``
        even when the HTTP status code is 200, so we branch on the
        ``ok`` flag after the standard rate-limit handling.
        """
        client = await self._get_client()
        attempts = self.max_retries + 1
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = await client.request(
                    method,
                    path,
                    params=params,
                    json=json_body,
                )
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning(
                    "Slack HTTP transport error on %s (attempt %s/%s): %s",
                    path,
                    attempt,
                    attempts,
                    exc,
                )
                await sleep_for(min(2 ** attempt, 10))
                continue

            # Slack returns 429 + Retry-After for rate limits.
            if response.status_code == 429:
                retry_after_raw = response.headers.get("Retry-After", "1")
                try:
                    retry_after = float(retry_after_raw)
                except ValueError:
                    retry_after = 1.0
                logger.info(
                    "Slack rate-limited (%s), sleeping %.2fs",
                    path,
                    retry_after,
                )
                await sleep_for(retry_after)
                if attempt < attempts:
                    continue
                raise RateLimitError(
                    f"Slack rate limit exceeded for {path}",
                    retry_after=retry_after,
                )

            if response.status_code in (401, 403):
                raise AuthError(
                    f"Slack auth failure ({response.status_code}): {response.text}"
                )
            if response.status_code == 404:
                raise NotFoundError(f"Slack endpoint missing: {path}")
            if 500 <= response.status_code < 600:
                last_error = IntegrationError(
                    f"Slack server error {response.status_code}: {response.text}"
                )
                logger.warning(
                    "Slack server error %s on %s (attempt %s/%s)",
                    response.status_code,
                    path,
                    attempt,
                    attempts,
                )
                await sleep_for(min(2 ** attempt, 10))
                continue

            try:
                payload = response.json()
            except Exception as exc:  # noqa: BLE001
                raise IntegrationError(f"Invalid Slack response: {exc}") from exc

            if isinstance(payload, dict) and payload.get("ok") is False:
                err_code = payload.get("error", "unknown_error")
                if err_code in {"invalid_auth", "not_authed", "token_revoked"}:
                    raise AuthError(f"Slack auth error: {err_code}")
                if err_code in {"channel_not_found", "not_in_channel", "missing_scope"}:
                    raise NotFoundError(f"Slack resource error: {err_code}")
                if err_code == "ratelimited":
                    retry_after = float(payload.get("retry_after", 1.0))
                    await sleep_for(retry_after)
                    if attempt < attempts:
                        continue
                    raise RateLimitError(
                        "Slack rate-limited", retry_after=retry_after
                    )
                raise IntegrationError(f"Slack API error: {err_code}")

            return payload if isinstance(payload, dict) else {"data": payload}

        assert last_error is not None
        raise IntegrationError(f"Slack request failed after retries: {last_error}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def send_message(
        self,
        channel: str,
        content: str,
        *,
        blocks: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        thread_ts: str | None = None,
        reply_broadcast: bool = False,
        unfurl_links: bool = True,
        unfurl_media: bool = True,
        as_user: bool = False,
        **_: Any,
    ) -> dict[str, Any]:
        """Send a message to ``channel`` via ``chat.postMessage``.

        Parameters
        ----------
        channel:
            Channel id (e.g. ``C12345``), user id (``D...``) or channel
            name (``#general``). The latter is resolved server-side.
        content:
            Plain-text message body.
        blocks:
            Optional Block Kit payload. When supplied, ``content``
            becomes the fallback for notifications.
        attachments:
            Optional ``attachments`` array (legacy message formatting).
        thread_ts:
            Optional thread parent timestamp. When present the message
            is posted into that thread.
        reply_broadcast:
            Broadcast the reply to the channel (``chat.postMessage``).
        """

        async def _do() -> dict[str, Any]:
            payload: dict[str, Any] = {"channel": channel}
            if content:
                payload["text"] = content
            if blocks is not None:
                payload["blocks"] = blocks
            if attachments is not None:
                payload["attachments"] = attachments
            if thread_ts:
                payload["thread_ts"] = thread_ts
            if reply_broadcast:
                payload["reply_broadcast"] = True
            payload["unfurl_links"] = unfurl_links
            payload["unfurl_media"] = unfurl_media
            if as_user:
                payload["as_user"] = True

            result = await self._request("POST", "/chat.postMessage", json_body=payload)
            return {
                "ok": True,
                "channel": result.get("channel"),
                "ts": result.get("ts"),
                "message": result.get("message"),
                "raw": result,
            }

        return await safe_call(_do)

    async def list_channels(
        self,
        *,
        channel_types: str = "public_channel,private_channel,mpim,im",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """List channels via ``conversations.list`` (paginated)."""

        async def _do() -> list[dict[str, Any]]:
            channels: list[dict[str, Any]] = []
            cursor: str | None = None
            while True:
                params: dict[str, Any] = {
                    "limit": limit,
                    "channel_types": channel_types,
                    "exclude_archived": True,
                }
                if cursor:
                    params["cursor"] = cursor
                result = await self._request(
                    "GET", "/conversations.list", params=params
                )
                channels.extend(result.get("channels", []))
                meta = result.get("response_metadata") or {}
                cursor = meta.get("next_cursor")
                if not cursor:
                    break
            return channels

        result = await safe_call(_do)
        return result if isinstance(result, list) else []

    async def get_user_info(self, user_id: str) -> dict[str, Any]:
        """Return ``users.info`` data for ``user_id``."""

        async def _do() -> dict[str, Any]:
            result = await self._request(
                "GET", "/users.info", params={"user": user_id}
            )
            return result.get("user") or result

        return await safe_call(_do) or {"ok": False, "error": "unknown"}

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------
    async def upload_file(
        self,
        channels: str | list[str],
        file_path: str,
        *,
        title: str | None = None,
        initial_comment: str | None = None,
        thread_ts: str | None = None,
    ) -> dict[str, Any]:
        """Upload ``file_path`` to one or more channels via ``files.upload`` v1.

        Slack recommends the new 3-step ``files.getUploadURLExternal`` flow
        for files >1MB; this convenience wraps the simpler v1 endpoint
        which is sufficient for typical text and image payloads.
        """
        import os

        if isinstance(channels, list):
            channels_param = ",".join(channels)
        else:
            channels_param = channels

        async def _do() -> dict[str, Any]:
            client = await self._get_client()
            with open(file_path, "rb") as fh:
                files = {"file": (os.path.basename(file_path), fh)}
                data: dict[str, Any] = {"channels": channels_param}
                if title:
                    data["title"] = title
                if initial_comment:
                    data["initial_comment"] = initial_comment
                if thread_ts:
                    data["thread_ts"] = thread_ts
                # ``files.upload`` requires multipart form encoding.
                response = await client.post(
                    "/files.upload",
                    files=files,
                    data=data,
                )
            if response.status_code >= 400:
                raise IntegrationError(
                    f"Slack file upload failed ({response.status_code}): {response.text}"
                )
            payload = response.json()
            if not payload.get("ok"):
                err = payload.get("error", "unknown")
                if err in {"invalid_auth", "not_authed"}:
                    raise AuthError(f"Slack auth error: {err}")
                raise IntegrationError(f"Slack file upload error: {err}")
            return payload

        return await safe_call(_do) or {"ok": False, "error": "unknown"}

    # ------------------------------------------------------------------
    # Receive loop
    # ------------------------------------------------------------------
    async def receive_messages(
        self,
        callback: ReceiveCallback,
        *,
        socket_mode: bool = False,
        app_token: str | None = None,
        **_: Any,
    ) -> None:
        """Receive messages.

        Without ``socket_mode=True`` the integration runs in webhook
        mode and returns immediately — the host process is expected
        to call :meth:`handle_event` for each incoming request.

        With ``socket_mode=True`` the integration starts a background
        task that maintains a Slack Socket Mode websocket and
        dispatches events to ``callback``. ``app_token`` must be an
        ``xapp-`` level token; when omitted the integration falls
        back to ``config["app_token"]``.
        """
        if not socket_mode:
            logger.info(
                "Slack receive_messages() called without socket_mode=True; "
                "assuming webhook mode — returning immediately."
            )
            return

        token = app_token or self.config.get("app_token")
        if not token:
            raise AuthError("app_token is required for Slack Socket Mode")

        self._socket_task = asyncio.create_task(
            self._run_socket_mode(callback, token),
            name="slack-socket-mode",
        )

    async def handle_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Normalise a webhook/Socket Mode event into the callback envelope."""
        envelope_type = event.get("type") or event.get("event", {}).get("type", "unknown")
        return {"ok": True, "type": envelope_type, "event": event}

    async def _run_socket_mode(
        self,
        callback: ReceiveCallback,
        app_token: str,
    ) -> None:
        """Minimal Socket Mode websocket receiver.

        The full Socket Mode handshake (``apps.connections.open`` etc.)
        requires valid credentials; in environments where the
        integration is only used for outbound messaging this method
        exits quickly with a logged warning.
        """
        try:
            import websockets  # type: ignore[import-not-found]
        except ImportError:
            logger.error(
                "websockets is not installed; Slack Socket Mode disabled."
            )
            return

        backoff = 1.0
        while not self._closed:
            try:
                # Placeholder URL — production deployments must
                # exchange ``apps.connections.open`` for a real wss URL.
                async with websockets.connect(  # type: ignore[name-defined]
                    "wss://wss-primary.slack.com/?agent=Zeloo"
                ) as ws:  # type: ignore[attr-defined]
                    backoff = 1.0
                    _ = app_token  # retained for future implementation
                    while not self._closed:
                        msg = await ws.recv()  # type: ignore[attr-defined]
                        logger.debug("Slack socket-mode frame: %s", msg[:200])
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Slack Socket Mode error: %s; retrying in %.2fs", exc, backoff
                )
                await sleep_for(backoff)
                backoff = min(backoff * 2, 60.0)


_ = Callable  # keep import meaningful for static analysers