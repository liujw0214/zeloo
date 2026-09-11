"""Generic webhook-based platform adapter base class.

Provides a lightweight HTTP server (stdlib only) to receive incoming
webhook payloads from messaging platforms, plus a uniform interface for
sending replies. Subclasses implement ``parse_incoming`` and
``send_message``.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_WEBHOOK_PORT = 9113


class WebhookAdapter:
    """Base class for HTTP-webhook-based platform adapters."""

    def __init__(
        self,
        webhook_path: str = "/webhook",
        webhook_port: int = _DEFAULT_WEBHOOK_PORT,
        verify_token: str | None = None,
    ) -> None:
        self._webhook_path = webhook_path
        self._webhook_port = webhook_port
        self._verify_token = verify_token
        self._handler: Callable[[str, str, str], str] | None = None
        self._server: HTTPServer | None = None
        self._server_thread: threading.Thread | None = None

    # ── Subclass hooks ──────────────────────────────────────────────

    def parse_incoming(self, body: bytes, headers: dict[str, str]) -> tuple[str, str] | None:
        """Parse an incoming webhook body.

        Args:
            body: Raw request body.
            headers: Request headers (lower-cased keys).

        Returns:
            A ``(user_id, message_text)`` tuple, or None if the payload
            should be ignored.
        """
        raise NotImplementedError

    def send_message(self, user_id: str, text: str) -> None:
        """Send a reply message to the user.

        Args:
            user_id: Platform-specific user identifier.
            text: Reply text.
        """
        raise NotImplementedError

    def verify_request(self, body: bytes, headers: dict[str, str]) -> bool:
        """Verify the incoming request signature/token.

        Default implementation checks the ``X-Verify-Token`` header
        against ``verify_token`` if configured. Subclasses can override.
        """
        if not self._verify_token:
            return True
        return headers.get("x-verify-token") == self._verify_token

    def get_verification_response(
        self, body: bytes, headers: dict[str, str]
    ) -> tuple[str, str] | None:
        """Return a custom response body for verification-style payloads.

        Some platforms (e.g. Slack) send a one-time verification payload
        that must be acknowledged with a specific JSON body rather than
        being treated as a message. Subclasses override this to return
        ``(content_type, body)`` for such payloads; returning ``None``
        falls through to normal message parsing.
        """
        return None

    # ── Public API ──────────────────────────────────────────────────

    def start(self, handler: Callable[[str, str, str], str]) -> None:
        """Start the webhook HTTP server in a background thread."""
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
                if not adapter.verify_request(body, headers):
                    self.send_error(403, "Invalid token")
                    return
                # Allow platforms to return a custom verification response
                # (e.g. Slack's url_verification challenge).
                verification = adapter.get_verification_response(body, headers)
                if verification is not None:
                    content_type, resp_body = verification
                    self.send_response(200)
                    self.send_header("Content-Type", content_type)
                    self.end_headers()
                    self.wfile.write(resp_body.encode("utf-8"))
                    return
                try:
                    parsed = adapter.parse_incoming(body, headers)
                except Exception:
                    logger.exception("Failed to parse incoming webhook")
                    self.send_error(400)
                    return
                if parsed is None:
                    self.send_response(200)
                    self.end_headers()
                    return
                user_id, text = parsed
                try:
                    reply = adapter._handler("webhook", user_id, text)  # type: ignore[misc]
                except Exception:
                    logger.exception("Handler failed for user %s", user_id)
                    from agent.i18n import gettext

                    reply = gettext("internal_error")
                try:
                    adapter.send_message(user_id, reply)
                except Exception:
                    logger.exception("Failed to send reply to %s", user_id)
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args: Any) -> None:
                pass  # quiet default logging

        self._server = HTTPServer(("0.0.0.0", self._webhook_port), _Handler)
        self._server_thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name=f"webhook-{self._webhook_port}",
        )
        self._server_thread.start()
        logger.info(
            "Webhook adapter listening on port %d%s",
            self._webhook_port,
            self._webhook_path,
        )

    def stop(self) -> None:
        """Stop the webhook HTTP server."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
            logger.info("Webhook adapter stopped")

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
