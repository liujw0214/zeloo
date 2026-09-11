"""LINE Messaging API platform adapter.

Receives messages via the LINE webhook (Messaging API) and replies either
via the ``reply`` endpoint (using a ``reply_token`` captured during
``parse_incoming``) or the ``push`` endpoint (using a ``user_id``).

Signature verification uses HMAC-SHA256 over the raw request body with the
``channel_secret`` as the key, matching the ``X-Line-Signature`` header.

Reference: https://developers.line.biz/en/docs/messaging-api/
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from typing import Any

from gateway.platforms.webhook_base import WebhookAdapter

logger = logging.getLogger(__name__)

LINE_API_BASE = "https://api.line.me/v2/bot"


class LINEAdapter(WebhookAdapter):
    """LINE bot adapter using the Messaging API webhook + REST endpoints."""

    def __init__(
        self,
        channel_access_token: str,
        webhook_port: int = 9113,
        channel_secret: str | None = None,
    ) -> None:
        super().__init__(webhook_path="/line/webhook", webhook_port=webhook_port)
        self._channel_access_token = channel_access_token
        self._channel_secret = channel_secret

    # ── Verification ─────────────────────────────────────────────────

    def verify_request(self, body: bytes, headers: dict[str, str]) -> bool:
        """Verify the ``X-Line-Signature`` header.

        LINE signs the raw request body with HMAC-SHA256 using
        ``channel_secret`` as the key and base64-encodes the digest. When
        no ``channel_secret`` is configured, verification is skipped.
        """
        if not self._channel_secret:
            return True
        signature = headers.get("x-line-signature")
        if not signature:
            return False
        expected = base64.b64encode(
            hmac.new(
                self._channel_secret.encode("utf-8"),
                body,
                hashlib.sha256,
            ).digest()
        ).decode("utf-8")
        return hmac.compare_digest(expected, signature)

    # ── Incoming ─────────────────────────────────────────────────────

    def parse_incoming(self, body: bytes, headers: dict[str, str]) -> tuple[str, str] | None:
        """Parse a LINE webhook events payload.

        Iterates over ``events[]`` and returns the first
        ``message`` event of ``type == "text"``. The returned ``user_id``
        is actually the LINE ``reply_token`` (valid for ~1 minute), so
        callers should reply promptly via ``send_message``.

        Returns:
            ``(reply_token, text)`` tuple, or ``None`` if no text
            message event is present.
        """
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return None

        events = payload.get("events", [])
        for event in events:
            if event.get("type") != "message":
                continue
            message = event.get("message", {})
            if message.get("type") != "text":
                continue
            reply_token = event.get("reply_token", "")
            text = message.get("text", "")
            if not reply_token or not text:
                continue
            return reply_token, text
        return None

    # ── Outgoing ─────────────────────────────────────────────────────

    def send_message(self, user_id: str, text: str) -> None:
        """Send a reply via the LINE Messaging API.

        The ``user_id`` parameter holds whatever ``parse_incoming``
        returned, which by convention is the ``reply_token`` for LINE.
        When the token is recognisable as a LINE ``reply_token`` (short,
        opaque) we use the ``/reply`` endpoint; otherwise we fall back
        to ``/push`` with a user ID.
        """
        headers = {
            "Authorization": f"Bearer {self._channel_access_token}",
        }
        messages = [{"type": "text", "text": text[:5000]}]

        # reply_token is short-lived and opaque (no U/prefix); a user_id
        # starts with "U". We route accordingly.
        if user_id.startswith("U"):
            url = f"{LINE_API_BASE}/message/push"
            body: dict[str, Any] = {"to": user_id, "messages": messages}
        else:
            url = f"{LINE_API_BASE}/message/reply"
            body = {"replyToken": user_id, "messages": messages}

        status, resp = self._http_post(url, json_body=body, headers=headers)
        if status != 200:
            logger.error("LINE send failed: %s %s", status, resp[:200])
