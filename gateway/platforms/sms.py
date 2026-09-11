"""SMS (Twilio) platform adapter.

Receives inbound SMS messages via Twilio webhook callbacks and sends
replies via the Twilio REST API ``Messages`` endpoint. Authentication
uses HTTP Basic Auth with the Account SID as username and the Auth
Token as password.

Independent class (does not inherit WebhookAdapter) because SMS is
passively received via Twilio webhook callbacks with a different
payload format (form-urlencoded, not JSON).

Reference: https://www.twilio.com/docs/messaging/guides/webhook
"""

from __future__ import annotations

import base64
import logging
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

logger = logging.getLogger(__name__)

TWILIO_API_BASE = "https://api.twilio.com/2010-04-01/Accounts"


class SMSAdapter:
    """SMS adapter using Twilio webhook + REST API.

    Uses stdlib only (no external dependencies). HTTP requests are
    performed via ``urllib.request``.
    """

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        from_number: str,
        webhook_port: int = 9113,
        webhook_path: str = "/sms/webhook",
    ) -> None:
        self._account_sid = account_sid
        self._auth_token = auth_token
        self._from_number = from_number
        self._webhook_port = webhook_port
        self._webhook_path = webhook_path
        self._handler: Callable[[str, str, str], str] | None = None
        self._server: HTTPServer | None = None
        self._server_thread: threading.Thread | None = None

    # ── Webhook server ──────────────────────────────────────────────

    def start(self, handler: Callable[[str, str, str], str]) -> None:
        """Start the Twilio webhook HTTP server in a background thread.

        Args:
            handler: Callback receiving ``(platform, user_id, message)``
                     and returning the assistant's reply string.
        """
        self._handler = handler
        adapter = self

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length else b""
                headers = {k.lower(): v for k, v in self.headers.items()}
                if self.path != adapter._webhook_path:
                    self.send_error(404)
                    return
                try:
                    parsed = adapter.parse_incoming(body, headers)
                except Exception:
                    logger.exception("Failed to parse Twilio webhook")
                    self.send_error(400)
                    return
                if parsed is None:
                    self._respond_empty()
                    return
                user_id, text = parsed
                try:
                    reply = adapter._handler("sms", user_id, text)  # type: ignore[misc]
                except Exception:
                    logger.exception("Handler failed for user %s", user_id)
                    from agent.i18n import gettext

                    reply = gettext("internal_error")
                try:
                    adapter.send_message(user_id, reply)
                except Exception:
                    logger.exception("Failed to send SMS reply to %s", user_id)
                self._respond_empty()

            def _respond_empty(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "application/xml")
                self.end_headers()
                self.wfile.write(b"<Response/>")

            def log_message(self, *args: Any) -> None:
                pass

        self._server = HTTPServer(("0.0.0.0", self._webhook_port), _Handler)
        self._server_thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name=f"sms-{self._webhook_port}",
        )
        self._server_thread.start()
        logger.info("SMS adapter listening on port %d", self._webhook_port)

    def stop(self) -> None:
        """Stop the webhook HTTP server."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            logger.info("SMS adapter stopped")

    # ── Parsing ─────────────────────────────────────────────────────

    @staticmethod
    def parse_incoming(
        body: bytes, headers: dict[str, str]
    ) -> tuple[str, str] | None:
        """Parse a Twilio webhook form-urlencoded payload.

        Twilio sends inbound SMS callbacks as
        ``application/x-www-form-urlencoded`` with ``Body`` (message text)
        and ``From`` (sender phone number) fields.

        Args:
            body: Raw request body bytes.
            headers: Request headers (lower-cased keys).

        Returns:
            A ``(from_number, message_text)`` tuple, or None if the
            payload should be ignored.
        """
        try:
            parsed = urllib.parse.parse_qs(body.decode("utf-8", errors="replace"))
        except Exception:
            return None
        body_values = parsed.get("Body", [])
        from_values = parsed.get("From", [])
        if not body_values or not from_values:
            return None
        text = body_values[0]
        sender = from_values[0]
        if not text or not sender:
            return None
        return sender, text

    # ── Outgoing ────────────────────────────────────────────────────

    def send_message(self, user_id: str, text: str) -> None:
        """Send an SMS reply via the Twilio Messages REST API.

        Uses HTTP Basic Auth with the Account SID and Auth Token.

        Args:
            user_id: Recipient phone number (E.164 format).
            text: Reply text content.
        """
        url = f"{TWILIO_API_BASE}/{self._account_sid}/Messages.json"
        data = urllib.parse.urlencode(
            {
                "From": self._from_number,
                "To": user_id,
                "Body": text[:1600],
            }
        ).encode()
        credentials = base64.b64encode(
            f"{self._account_sid}:{self._auth_token}".encode()
        ).decode()
        headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp.read()
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            logger.error("Twilio send failed: %s %s", e.code, err_body[:200])
