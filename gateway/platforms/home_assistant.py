"""Home Assistant platform adapter.

Home Assistant communicates with the agent via a webhook registered as a
custom ``webhook`` integration in HA. HA pushes JSON payloads containing
an ``event_type``, ``message`` and ``user_id`` field; the agent replies
through the HA REST API ``/api/services/notify/notify`` endpoint using a
long-lived bearer token.

This is an independent class (does not inherit ``WebhookAdapter``) because
the HA integration is a custom webhook with its own payload shape, and a
standalone implementation keeps the contract explicit.

Reference: https://developers.home-assistant.io/docs/api/rest/
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

logger = logging.getLogger(__name__)


class HomeAssistantAdapter:
    """Home Assistant bot adapter using custom webhook + REST API."""

    def __init__(
        self,
        ha_url: str,
        ha_token: str,
        webhook_port: int = 9113,
    ) -> None:
        self._ha_url = ha_url.rstrip("/")
        self._ha_token = ha_token
        self._webhook_port = webhook_port
        self._handler: Callable[[str, str, str], str] | None = None
        self._server: HTTPServer | None = None
        self._server_thread: threading.Thread | None = None

    # ── Lifecycle ───────────────────────────────────────────────────

    def start(self, handler: Callable[[str, str, str], str]) -> None:
        """Start the HTTP webhook server to receive HA callbacks.

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

                try:
                    parsed = adapter.parse_incoming(body, headers)
                except Exception:
                    logger.exception("Failed to parse Home Assistant webhook")
                    self.send_error(400)
                    return

                if parsed is None:
                    self.send_response(200)
                    self.end_headers()
                    return

                user_id, text = parsed
                try:
                    reply = adapter._handler("home-assistant", user_id, text)  # type: ignore[misc]
                except Exception:
                    logger.exception("Handler failed for user %s", user_id)
                    from agent.i18n import gettext

                    reply = gettext("internal_error")
                try:
                    adapter.send_message(user_id, reply)
                except Exception:
                    logger.exception("Failed to send Home Assistant reply to %s", user_id)
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args: Any) -> None:
                pass  # quiet default logging

        self._server = HTTPServer(("0.0.0.0", self._webhook_port), _Handler)
        self._server_thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name=f"homeassistant-{self._webhook_port}",
        )
        self._server_thread.start()
        logger.info("Home Assistant adapter listening on port %d", self._webhook_port)

    def stop(self) -> None:
        """Stop the webhook HTTP server."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            self._server_thread = None
            logger.info("Home Assistant adapter stopped")

    # ── Incoming ─────────────────────────────────────────────────────

    def parse_incoming(self, body: bytes, headers: dict[str, str]) -> tuple[str, str] | None:
        """Parse a Home Assistant webhook JSON payload.

        Expects a JSON object with ``event_type``, ``message`` and
        ``user_id`` fields. Only ``event_type == "message"`` payloads
        are treated as user messages; other event types are ignored.

        Returns:
            ``(user_id, message_text)`` tuple, or ``None`` when the
            payload is not a message event or is missing required
            fields.
        """
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return None

        if payload.get("event_type", "message") != "message":
            return None

        message = payload.get("message", "")
        user_id = payload.get("user_id", "")
        if not message or not user_id:
            return None
        return str(user_id), str(message)

    # ── Outgoing ─────────────────────────────────────────────────────

    def send_message(self, user_id: str, text: str) -> None:
        """Send a reply via the Home Assistant REST notify service.

        Args:
            user_id: Sender identifier captured during ``parse_incoming``.
                     Forwarded as ``data.user_id`` so the HA notify
                     action can route to the correct conversation.
            text: Reply text.
        """
        url = f"{self._ha_url}/api/services/notify/notify"
        headers = {
            "Authorization": f"Bearer {self._ha_token}",
        }
        body: dict[str, Any] = {
            "message": text[:5000],
            "data": {"user_id": user_id},
        }
        status, resp = self._http_post(url, json_body=body, headers=headers)
        if status != 200:
            logger.error("Home Assistant send failed: %s %s", status, resp[:200])

    # ── HTTP helper ─────────────────────────────────────────────────

    @staticmethod
    def _http_post(
        url: str,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> tuple[int, str]:
        """Perform an HTTP POST using stdlib (no external deps).

        Returns ``(status_code, response_text)``.
        """
        import urllib.error
        import urllib.request

        data = json.dumps(json_body).encode("utf-8") if json_body else b""
        req_headers = {"Content-Type": "application/json"}
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", errors="replace")
