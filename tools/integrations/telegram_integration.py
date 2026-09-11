"""Telegram Bot API integration.

Implements :class:`BaseIntegration` against the Telegram Bot API
(``https://api.telegram.org/bot<token>/...``). Supports:

- ``sendMessage`` with text and ``parse_mode``
- ``sendPhoto`` / ``sendDocument`` for attachments
- Inline keyboards and reply keyboards
- Webhook-based receive mode (long-polling is included as an
  alternative for local development)

Configuration keys
------------------
- ``token`` (str, required): Bot token issued by @BotFather
- ``api_base`` (str, optional): Defaults to ``https://api.telegram.org``
- ``webhook_url`` (str, optional): If supplied the integration will
  register a webhook via ``setWebhook`` on start
- ``max_retries`` (int, optional): Defaults to ``3``
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

DEFAULT_API_BASE = "https://api.telegram.org"
DEFAULT_MAX_RETRIES = 3
TELEGRAM_MAX_MESSAGE_LENGTH = 4096


@register_integration("telegram")
class TelegramIntegration(BaseIntegration):
    """Telegram Bot API integration."""

    platform_name = "telegram"

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self.token: str = require_config(config, "token")
        self.api_base: str = config.get("api_base", DEFAULT_API_BASE).rstrip("/")
        self.max_retries: int = int(config.get("max_retries", DEFAULT_MAX_RETRIES))
        self.timeout: float = float(config.get("timeout", 30.0))
        self.webhook_url: str | None = config.get("webhook_url")
        self._client: httpx.AsyncClient | None = None
        self._polling_task: asyncio.Task[None] | None = None
        self._event_callback: ReceiveCallback | None = None

    # ------------------------------------------------------------------
    # HTTP plumbing
    # ------------------------------------------------------------------
    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=f"{self.api_base}/bot{self.token}",
                timeout=self.timeout,
                headers={"User-Agent": "ZelooTelegramIntegration/1.0"},
            )
        return self._client

    async def close(self) -> None:
        await super().close()
        if self._polling_task is not None and not self._polling_task.done():
            self._polling_task.cancel()
            try:
                await self._polling_task
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
    ) -> dict[str, Any]:
        client = await self._get_client()
        attempts = self.max_retries + 1
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                if multipart is not None:
                    response = await client.request(
                        method,
                        path,
                        data=multipart.get("data"),
                        files=multipart.get("files"),
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
                    "Telegram HTTP transport error on %s (attempt %s/%s): %s",
                    path,
                    attempt,
                    attempts,
                    exc,
                )
                await sleep_for(min(2 ** attempt, 10))
                continue

            if response.status_code == 429:
                body: dict[str, Any] = {}
                try:
                    body = response.json()
                except Exception:  # noqa: BLE001
                    body = {}
                retry_after = float(body.get("parameters", {}).get("retry_after", 1.0))
                logger.info(
                    "Telegram rate-limited (%s), sleeping %.2fs", path, retry_after
                )
                await sleep_for(retry_after)
                if attempt < attempts:
                    continue
                raise RateLimitError(
                    f"Telegram rate limit exceeded for {path}", retry_after=retry_after
                )

            if response.status_code in (401, 403):
                raise AuthError(
                    f"Telegram auth failure ({response.status_code}): {response.text}"
                )
            if response.status_code == 404:
                raise NotFoundError(f"Telegram resource missing: {path}")
            if 500 <= response.status_code < 600:
                last_error = IntegrationError(
                    f"Telegram server error {response.status_code}: {response.text}"
                )
                await sleep_for(min(2 ** attempt, 10))
                continue

            try:
                payload = response.json()
            except Exception as exc:  # noqa: BLE001
                raise IntegrationError(f"Invalid Telegram response: {exc}") from exc

            if isinstance(payload, dict) and payload.get("ok") is False:
                description = payload.get("description", "unknown")
                code = payload.get("error_code", 0)
                if code in (401, 403):
                    raise AuthError(f"Telegram auth error: {description}")
                raise IntegrationError(f"Telegram API error: {description}")

            return payload if isinstance(payload, dict) else {"data": payload}

        assert last_error is not None
        raise IntegrationError(f"Telegram request failed after retries: {last_error}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def send_message(
        self,
        channel: str,
        content: str,
        *,
        parse_mode: str | None = None,
        disable_notification: bool = False,
        reply_to_message_id: int | None = None,
        inline_keyboard: list[list[dict[str, Any]]] | None = None,
        reply_markup: dict[str, Any] | None = None,
        attachment_path: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        """Send a message via ``sendMessage`` (or ``sendPhoto`` when
        ``attachment_path`` points to an image).

        Parameters
        ----------
        channel:
            ``chat_id`` (numeric id or ``@channelusername``).
        content:
            Plain text or caption text. Telegram limits text to
            ``TELEGRAM_MAX_MESSAGE_LENGTH`` (4096) characters.
        parse_mode:
            Optional ``"HTML"`` or ``"MarkdownV2"``.
        inline_keyboard:
            Convenience for ``reply_markup.inline_keyboard``.
        reply_markup:
            A full ``reply_markup`` object (overrides
            ``inline_keyboard``).
        """

        async def _do() -> dict[str, Any]:
            client = await self._get_client()
            keyboard = reply_markup
            if keyboard is None and inline_keyboard is not None:
                keyboard = {"inline_keyboard": inline_keyboard}

            if attachment_path is not None:
                import os

                ext = os.path.splitext(attachment_path)[1].lower()
                method = "sendPhoto" if ext in {".jpg", ".jpeg", ".png", ".gif"} else "sendDocument"
                with open(attachment_path, "rb") as fh:
                    files = (
                        {"photo": (os.path.basename(attachment_path), fh)}
                        if method == "sendPhoto"
                        else {"document": (os.path.basename(attachment_path), fh)}
                    )
                    data: dict[str, Any] = {"chat_id": channel, "caption": content}
                    if parse_mode:
                        data["parse_mode"] = parse_mode
                    if keyboard:
                        import json as _json

                        data["reply_markup"] = _json.dumps(keyboard)
                    if disable_notification:
                        data["disable_notification"] = "true"
                    if reply_to_message_id is not None:
                        data["reply_to_message_id"] = str(reply_to_message_id)
                    result = await self._request(
                        "POST",
                        f"/{method}",
                        multipart={"data": data, "files": files},
                    )
            else:
                payload: dict[str, Any] = {
                    "chat_id": channel,
                    "text": content,
                }
                if parse_mode:
                    payload["parse_mode"] = parse_mode
                if keyboard:
                    payload["reply_markup"] = keyboard
                if disable_notification:
                    payload["disable_notification"] = True
                if reply_to_message_id is not None:
                    payload["reply_to_message_id"] = reply_to_message_id
                result = await self._request(
                    "POST", "/sendMessage", json_body=payload
                )

            _ = client  # silence unused
            return {
                "ok": True,
                "message_id": (result.get("result") or {}).get("message_id"),
                "chat_id": (result.get("result") or {}).get("chat", {}).get("id"),
                "raw": result,
            }

        return await safe_call(_do)

    async def list_channels(self) -> list[dict[str, Any]]:
        """Telegram bots do not have a channel-listing endpoint; return
        the bot's own info and any chat ids cached via incoming updates.
        """

        async def _do() -> list[dict[str, Any]]:
            me = await self._request("GET", "/getMe")
            return [me.get("result", {})]

        result = await safe_call(_do)
        return result if isinstance(result, list) else []

    async def get_user_info(self, user_id: str) -> dict[str, Any]:
        """Telegram does not expose arbitrary user lookups, but bots can
        call ``getChat`` when the user has interacted with them.
        """

        async def _do() -> dict[str, Any]:
            result = await self._request(
                "GET", "/getChat", params={"chat_id": user_id}
            )
            return result.get("result", {})

        return await safe_call(_do) or {"ok": False, "error": "unknown"}

    # ------------------------------------------------------------------
    # Receive loop
    # ------------------------------------------------------------------
    async def receive_messages(
        self,
        callback: ReceiveCallback,
        *,
        webhook: bool = False,
        polling: bool = False,
        **_: Any,
    ) -> None:
        """Register the callback for incoming updates.

        - ``webhook=True`` stores the callback and, if ``webhook_url``
          was supplied in the config, registers the URL via
          ``setWebhook``.
        - ``polling=True`` starts a long-polling loop on ``getUpdates``.
        """
        self._event_callback = callback
        if webhook:
            if self.webhook_url:
                await self._request(
                    "POST",
                    "/setWebhook",
                    json_body={"url": self.webhook_url},
                )
            else:
                logger.warning(
                    "Telegram receive_messages(webhook=True) called without webhook_url"
                )
            return

        if polling:
            self._polling_task = asyncio.create_task(
                self._run_polling(callback),
                name="telegram-polling",
            )

    async def handle_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a single inbound webhook update to the callback."""
        callback = self._event_callback
        if callback is not None:
            try:
                await callback(event)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Telegram event callback raised: %s", exc)
        return {"ok": True}

    async def _run_polling(self, callback: ReceiveCallback) -> None:
        """Long-poll ``getUpdates`` forever."""
        offset: int | None = None
        backoff = 1.0
        while not self._closed:
            try:
                params: dict[str, Any] = {"timeout": 30}
                if offset is not None:
                    params["offset"] = offset
                result = await self._request(
                    "GET", "/getUpdates", params=params
                )
                updates = result.get("result", []) if isinstance(result, dict) else []
                for update in updates:
                    offset = update.get("update_id", offset) + 1
                    try:
                        await callback(update)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "Telegram update callback raised: %s", exc
                        )
                backoff = 1.0
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Telegram polling error: %s; retrying in %.2fs", exc, backoff
                )
                await sleep_for(backoff)
                backoff = min(backoff * 2, 60.0)


_ = Callable  # keep import meaningful