"""Feishu (Lark) platform adapter.

Receives messages via Feishu Event Subscription (HTTP webhook) and replies
via the Feishu Open API ``im/v1/messages`` endpoint. Supports the
``url_verification`` challenge handshake required during event subscription
setup.

Reference: https://open.feishu.cn/document/server-docs/event-subscription-guide
"""

from __future__ import annotations

import json
import logging
import time

from gateway.platforms.webhook_base import WebhookAdapter

logger = logging.getLogger(__name__)

FEISHU_API_BASE = "https://open.feishu.cn/open-apis"
FEISHU_TOKEN_TTL = 5400  # tenant_access_token valid for ~7200s, refresh early


class FeishuAdapter(WebhookAdapter):
    """Feishu bot adapter using Event Subscription + Open API."""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        webhook_port: int = 9113,
        encrypt_key: str | None = None,
        verification_token: str | None = None,
    ) -> None:
        super().__init__(webhook_path="/feishu/events", webhook_port=webhook_port)
        self._app_id = app_id
        self._app_secret = app_secret
        self._encrypt_key = encrypt_key
        self._verification_token = verification_token
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    # ── Auth ────────────────────────────────────────────────────────

    def _get_tenant_access_token(self) -> str:
        """Obtain (and cache) a ``tenant_access_token``.

        Tokens are cached and refreshed 5 minutes before expiry to avoid
        race conditions near the TTL boundary.
        """
        now = time.time()
        if self._token and now < self._token_expires_at:
            return self._token

        url = f"{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal"
        body = {"app_id": self._app_id, "app_secret": self._app_secret}
        status, resp = self._http_post(url, json_body=body)
        if status != 200:
            raise RuntimeError(f"Feishu token request failed: {status} {resp[:200]}")
        try:
            data = json.loads(resp)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Feishu token response not JSON: {resp[:200]}") from e
        if data.get("code") != 0:
            raise RuntimeError(f"Feishu token error: {data.get('msg')}")
        self._token = data["tenant_access_token"]
        self._token_expires_at = now + data.get("expire", FEISHU_TOKEN_TTL) - 300
        return self._token

    # ── Incoming ────────────────────────────────────────────────────

    def verify_request(self, body: bytes, headers: dict[str, str]) -> bool:
        """Verify the request using the configured verification token.

        Feishu sends ``X-Lark-Request-Timestamp`` and ``X-Lark-Signature``
        headers when an encrypt key is configured. Here we perform a
        lightweight token check; full HMAC verification can be layered on
        top if ``encrypt_key`` is provided.
        """
        if not self._verification_token:
            return True
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return False
        token = payload.get("token") or payload.get("header", {}).get("token")
        return token == self._verification_token

    def get_verification_response(
        self, body: bytes, headers: dict[str, str]
    ) -> tuple[str, str] | None:
        """Respond to Feishu's URL verification challenge.

        During event subscription setup Feishu sends a ``url_verification``
        payload; we must echo the ``challenge`` field back as JSON.
        """
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return None
        if payload.get("type") == "url_verification":
            challenge = payload.get("challenge", "")
            return "application/json", json.dumps({"challenge": challenge})
        return None

    def parse_incoming(self, body: bytes, headers: dict[str, str]) -> tuple[str, str] | None:
        """Parse a Feishu v2.0 event payload."""
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return None

        # URL verification handled separately
        if payload.get("type") == "url_verification":
            return None

        schema = payload.get("schema")
        event = payload.get("event", {})

        # v2.0 schema wraps events in "header" + "event"
        if schema == "2.0":
            header = payload.get("header", {})
            event_type = header.get("event_type", "")
            if event_type != "im.message.receive_v1":
                return None
            message = event.get("message", {})
            sender = event.get("sender", {})
            sender_id = sender.get("sender_id", {})
            user_id = sender_id.get("open_id") or sender_id.get("user_id")
            text = self._extract_text(message)
        else:
            # v1.0 fallback
            event_type = payload.get("event", {}).get("type")
            if event_type != "message":
                return None
            user_id = event.get("open_id") or ""
            text = self._extract_text(event)

        if not user_id or not text:
            return None
        return user_id, text

    @staticmethod
    def _extract_text(message: dict) -> str:
        """Extract plain text from a Feishu message object."""
        msg_type = message.get("message_type") or message.get("msg_type", "")
        if msg_type == "text":
            try:
                content = json.loads(message.get("content", "{}"))
                return content.get("text", "")
            except json.JSONDecodeError:
                return ""
        return ""

    # ── Outgoing ────────────────────────────────────────────────────

    def send_message(self, user_id: str, text: str) -> None:
        """Send a reply via Feishu Open API.

        Uses ``receive_id_type=open_id`` to direct the message at the
        sender. Text longer than 30k chars is truncated (Feishu limit).
        """
        token = self._get_tenant_access_token()
        url = f"{FEISHU_API_BASE}/im/v1/messages?receive_id_type=open_id"
        headers = {"Authorization": f"Bearer {token}"}
        truncated = text[:30000]
        body = {
            "receive_id": user_id,
            "msg_type": "text",
            "content": json.dumps({"text": truncated}),
        }
        status, resp = self._http_post(url, json_body=body, headers=headers)
        if status != 200:
            logger.error("Feishu send failed: %s %s", status, resp[:200])
