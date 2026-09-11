"""QQ Bot platform adapter.

Receives messages via QQ Bot webhook callbacks and replies via the QQ
Bot Open API. Access tokens are obtained from the ``getAppAccessToken``
endpoint with caching and automatic refresh. Requests are verified
using HMAC-SHA256 signatures in the ``X-Signature`` header.

Inherits from ``WebhookAdapter`` to reuse the standard webhook HTTP
server infrastructure.

Reference: https://bot.q.qq.com/wiki/
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time

from gateway.platforms.webhook_base import WebhookAdapter

logger = logging.getLogger(__name__)

QQBOT_TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
QQBOT_API_BASE = "https://api.sgroup.qq.com/v2"


class QQBotAdapter(WebhookAdapter):
    """QQ Bot adapter using webhook callbacks + Open API."""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        webhook_port: int = 9113,
    ) -> None:
        super().__init__(
            webhook_path="/qqbot/messages",
            webhook_port=webhook_port,
        )
        self._app_id = app_id
        self._app_secret = app_secret
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    # ── Auth ────────────────────────────────────────────────────────

    def _get_access_token(self) -> str:
        """Obtain (and cache) a QQ Bot access_token.

        The token is cached and refreshed 5 minutes before expiry.

        Returns:
            A valid ``access_token`` string.

        Raises:
            RuntimeError: If the token request fails or returns invalid
                data.
        """
        now = time.time()
        if self._access_token and now < self._token_expires_at:
            return self._access_token

        body = {"appId": self._app_id, "clientSecret": self._app_secret}
        status, resp = self._http_post(QQBOT_TOKEN_URL, json_body=body)
        if status != 200:
            raise RuntimeError(
                f"QQ Bot token request failed: {status} {resp[:200]}"
            )
        try:
            data = json.loads(resp)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"QQ Bot token response not JSON: {resp[:200]}"
            ) from e
        self._access_token = data.get("access_token")
        if not self._access_token:
            raise RuntimeError(f"QQ Bot token error: {data}")
        self._token_expires_at = now + data.get("expires_in", 7200) - 300
        return self._access_token

    # ── Signature verification ──────────────────────────────────────

    def verify_request(self, body: bytes, headers: dict[str, str]) -> bool:
        """Verify QQ Bot request signature.

        QQ Bot signs the raw request body with HMAC-SHA256 using the
        app secret as the key, and sends the result in the
        ``X-Signature`` header (hex-encoded).

        Args:
            body: Raw request body bytes.
            headers: Request headers (lower-cased keys).

        Returns:
            True if the signature is valid (or if no secret is
            configured), False otherwise.
        """
        if not self._app_secret:
            return True
        signature = headers.get("x-signature", "")
        if not signature:
            return False
        expected = hmac.new(
            self._app_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    # ── Parsing ─────────────────────────────────────────────────────

    def parse_incoming(
        self, body: bytes, headers: dict[str, str]
    ) -> tuple[str, str] | None:
        """Parse a QQ Bot C2C_MESSAGE_CREATE event payload.

        Extracts the sender's openid and message content from the event
        data. Only ``C2C_MESSAGE_CREATE`` events with text content are
        processed.

        Args:
            body: Raw request body bytes.
            headers: Request headers (lower-cased keys).

        Returns:
            A ``(user_openid, message_text)`` tuple, or None if the
            payload is not a text C2C message.
        """
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return None

        # Check event type (support both camelCase and short forms)
        event_type = payload.get("eventType") or payload.get("t", "")
        if event_type != "C2C_MESSAGE_CREATE":
            return None

        data = payload.get("data") or payload.get("d", {})
        author = data.get("author", {})
        user_id = author.get("user_openid") or author.get("member_openid", "")
        content = (data.get("content") or "").strip()
        if not user_id or not content:
            return None
        return user_id, content

    # ── Outgoing ────────────────────────────────────────────────────

    def send_message(self, user_id: str, text: str) -> None:
        """Send a text reply to a QQ Bot user via the Open API.

        Uses the ``/v2/users/{openid}/messages`` endpoint with the
        cached access_token.

        Args:
            user_id: Recipient's openid.
            text: Reply text content.
        """
        token = self._get_access_token()
        url = f"{QQBOT_API_BASE}/users/{user_id}/messages"
        headers = {"Authorization": f"QQBot {token}"}
        body = {"content": text[:2000], "msg_type": 0}
        status, resp = self._http_post(url, json_body=body, headers=headers)
        if status != 200:
            logger.error("QQ Bot send failed: %s %s", status, resp[:200])
