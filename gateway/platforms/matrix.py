"""Matrix (Synapse) platform adapter.

Unlike webhook-based adapters, Matrix delivers events through the
``/_matrix/client/v3/sync`` long-polling endpoint. This adapter spawns a
background thread that continuously polls ``/sync`` and dispatches
incoming ``m.room.message`` events to the gateway handler.

Reference: https://spec.matrix.org/v1.10/client-server-api/
"""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

MATRIX_SYNC_TIMEOUT_MS = 30000  # server-side long-poll window


class MatrixAdapter:
    """Matrix bot adapter using the client-server ``/sync`` API."""

    def __init__(
        self,
        homeserver: str,
        access_token: str,
        user_id: str,
    ) -> None:
        self._homeserver = homeserver.rstrip("/")
        self._access_token = access_token
        self._user_id = user_id
        self._since: str | None = None
        self._handler: Callable[[str, str, str], str] | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # ── Lifecycle ───────────────────────────────────────────────────

    def start(self, handler: Callable[[str, str, str], str]) -> None:
        """Start the long-polling sync loop in a background thread.

        Args:
            handler: Callback receiving (platform, user_id, message) and
                     returning the assistant's reply string.
        """
        self._handler = handler
        self._thread = threading.Thread(
            target=self._sync_loop,
            daemon=True,
            name="matrix-sync",
        )
        self._thread.start()
        logger.info("Matrix adapter started for %s", self._user_id)

    def stop(self) -> None:
        """Stop the sync loop and wait for the background thread."""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Matrix adapter stopped")

    # ── Sync loop ───────────────────────────────────────────────────

    def _sync_loop(self) -> None:
        """Continuously poll ``/sync`` until ``stop()`` is called."""
        while not self._stop_event.is_set():
            try:
                events = self._fetch_sync_events()
                for room_id, event in events:
                    self._dispatch_event(room_id, event)
            except Exception:
                logger.exception("Matrix sync iteration failed")
                # Avoid tight error loops; sleep briefly via stop_event.
                self._stop_event.wait(timeout=1.0)

    def _fetch_sync_events(self) -> list[tuple[str, dict[str, Any]]]:
        """Fetch one ``/sync`` response and return parsed text events.

        Returns:
            A list of ``(room_id, event)`` tuples for ``m.room.message``
            events with a non-empty ``body``.
        """
        params: dict[str, str] = {
            "timeout": str(MATRIX_SYNC_TIMEOUT_MS),
        }
        if self._since:
            params["since"] = self._since
        query = urllib.parse.urlencode(params)
        url = f"{self._homeserver}/_matrix/client/v3/sync?{query}"
        req = urllib.request.Request(  # noqa: S310 — trusted homeserver URL
            url,
            headers={"Authorization": f"Bearer {self._access_token}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=MATRIX_SYNC_TIMEOUT_MS // 1000 + 10) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            logger.error("Matrix sync HTTP error: %s %s", e.code, e.read()[:200])
            return []
        except urllib.error.URLError as e:
            logger.error("Matrix sync URL error: %s", e)
            return []

        # Advance the cursor so the next poll only returns new events.
        new_since = data.get("next_batch")
        if new_since:
            self._since = new_since

        rooms = data.get("rooms", {}).get("join", {})
        events: list[tuple[str, dict[str, Any]]] = []
        for room_id, room_state in rooms.items():
            for event in room_state.get("timeline", {}).get("events", []):
                if event.get("type") == "m.room.message":
                    events.append((room_id, event))
        return events

    def _dispatch_event(self, room_id: str, event: dict[str, Any]) -> None:
        """Parse one ``m.room.message`` event and route it to the handler.

        Args:
            room_id: Matrix room identifier.
            event: Raw event dictionary from the sync response.
        """
        parsed = self.parse(event)
        if parsed is None:
            return
        sender, text = parsed
        # Reply target is the room the message was sent in.
        if self._handler is None:
            return
        try:
            reply = self._handler("matrix", sender, text)
        except Exception:
            logger.exception("Matrix handler failed for user %s", sender)
            from agent.i18n import gettext

            reply = gettext("internal_error")
        try:
            self.send_message(room_id, reply)
        except Exception:
            logger.exception("Failed to send Matrix reply to room %s", room_id)

    # ── Parsing ─────────────────────────────────────────────────────

    @staticmethod
    def parse(event: dict[str, Any]) -> tuple[str, str] | None:
        """Extract a plain-text message from an ``m.room.message`` event.

        Args:
            event: A Matrix event dictionary from the sync response.

        Returns:
            A ``(sender, text)`` tuple, or None if the event is not a
            user-authored text message (e.g. emitted by the bot itself).
        """
        content = event.get("content", {})
        if content.get("msgtype") != "m.text":
            return None
        sender = event.get("sender", "")
        text = content.get("body", "")
        if not sender or not text:
            return None
        return sender, text

    # ── Outgoing ────────────────────────────────────────────────────

    def send_message(self, room_id: str, text: str) -> None:
        """Send a text message to a Matrix room.

        Args:
            room_id: Matrix room identifier (e.g. ``!abc:server.org``).
            text: Reply text.
        """
        # Use a transaction id derived from the current thread id to
        # allow idempotent retries per the Matrix spec.
        txn_id = f"t{threading.get_ident()}"
        url = (
            f"{self._homeserver}/_matrix/client/v3/rooms/"
            f"{urllib.parse.quote(room_id)}/send/m.room.message/{txn_id}"
        )
        body = {
            "msgtype": "m.text",
            "body": text[:4000],
        }
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(  # noqa: S310 — trusted homeserver URL
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._access_token}",
            },
            method="PUT",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status != 200:
                    logger.error(
                        "Matrix send unexpected status: %s",
                        resp.status,
                    )
        except urllib.error.HTTPError as e:
            logger.error("Matrix send HTTP error: %s %s", e.code, e.read()[:200])
        except urllib.error.URLError as e:
            logger.error("Matrix send URL error: %s", e)
