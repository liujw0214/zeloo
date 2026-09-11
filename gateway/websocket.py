"""WebSocket gateway built on the ``websockets`` asyncio library.

Provides a small server that:

* Accepts JSON-encoded inbound messages shaped as
  ``{"action": "...", "channel": "...", "payload": {...}}``.
* Tracks per-client channel subscriptions.
* Supports server-initiated :meth:`WebSocketGateway.broadcast` to all
  subscribers of a given channel.

Authentication is delegated to an optional ``auth_handler`` callable
that receives ``(token: str)`` and returns ``True``/``False``. The server
exits cleanly on :meth:`stop` and exposes live stats via
:meth:`get_connected_clients` / :meth:`get_subscriptions`.

Requires the third-party ``websockets`` package (>=11.0). It is bundled
in the optional dev dependencies but not declared as a hard runtime
requirement — the constructor checks for availability at start time.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

try:  # pragma: no cover - import-time check
    import websockets  # type: ignore[import-not-found]
    from websockets.server import ServerConnection  # type: ignore[import-not-found]
    _HAS_WEBSOCKETS = True
except ImportError:  # pragma: no cover - exercised only when dep is missing
    websockets = None  # type: ignore[assignment]
    ServerConnection = Any  # type: ignore[misc,assignment]
    _HAS_WEBSOCKETS = False


AuthHandler = Callable[[str], bool]


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


class WebSocketGateway:
    """Lightweight pub/sub WebSocket gateway."""

    def __init__(self, host: str = "localhost", port: int = 8765) -> None:
        """Store bind address and prepare per-client state."""
        self._host = host
        self._port = int(port)
        self._server: Any = None
        self._server_task: asyncio.Task[None] | None = None
        # Map: client websocket → set of subscribed channels.
        self._clients: dict[Any, set[str]] = {}
        # Lock that guards mutations of ``_clients`` / ``_subscriptions``.
        self._lock = asyncio.Lock()

    # ── Public properties ────────────────────────────────────────────

    def get_connected_clients(self) -> int:
        """Return the number of currently connected clients."""
        return len(self._clients)

    def get_subscriptions(self) -> dict[str, int]:
        """Return a snapshot ``channel → subscriber_count``."""
        counts: dict[str, int] = {}
        for channels in self._clients.values():
            for ch in channels:
                counts[ch] = counts.get(ch, 0) + 1
        return counts

    # ── Lifecycle ────────────────────────────────────────────────────

    async def start(self, auth_handler: AuthHandler | None = None) -> None:
        """Bind and serve forever until :meth:`stop` is called.

        Args:
            auth_handler: Optional ``(token: str) -> bool`` predicate. When
                provided, every connection must send ``{"action":
                "auth", "token": "..."}`` as its first message. Any other
                first action causes the connection to be closed with code
                ``4401``.
        """
        if not _HAS_WEBSOCKETS:
            raise RuntimeError(
                "The 'websockets' package is required for WebSocketGateway. "
                "Install it with `pip install websockets`."
            )
        if self._server is not None:
            raise RuntimeError("WebSocketGateway already running")

        async def _connection_handler(ws: Any) -> None:
            await self._handle_connection(ws, auth_handler)

        self._server = await websockets.serve(_connection_handler, self._host, self._port)
        logger.info("WebSocket gateway listening on ws://%s:%d", self._host, self._port)

    async def stop(self) -> None:
        """Close every client connection and shut the server down."""
        if self._server is None:
            return
        try:
            # Close all active clients cleanly.
            async with self._lock:
                clients = list(self._clients.keys())
                self._clients.clear()
            for ws in clients:
                try:
                    await ws.close(code=1001, reason="server shutdown")
                except Exception:  # noqa: BLE001
                    logger.debug("Error closing client", exc_info=True)
            self._server.close()
            await self._server.wait_closed()
        finally:
            self._server = None
            if self._server_task is not None:
                self._server_task.cancel()
                self._server_task = None
            logger.info("WebSocket gateway stopped")

    # ── Broadcasting ─────────────────────────────────────────────────

    async def broadcast(self, channel: str, message: dict) -> int:
        """Send ``message`` to every subscriber of ``channel``.

        Returns:
            The number of clients the message was delivered to.
        """
        if self._server is None:
            logger.debug("broadcast() called on stopped gateway")
            return 0
        payload = json.dumps(
            {"channel": channel, "message": message}, ensure_ascii=False
        )
        delivered = 0
        async with self._lock:
            targets = [
                ws
                for ws, channels in self._clients.items()
                if channel in channels
            ]
        for ws in targets:
            try:
                await ws.send(payload)
                delivered += 1
            except Exception:  # noqa: BLE001
                logger.debug("Broadcast send failed", exc_info=True)
        return delivered

    # ── Internals ────────────────────────────────────────────────────

    async def _handle_connection(
        self,
        ws: Any,
        auth_handler: AuthHandler | None,
    ) -> None:
        """Drive one client connection: auth → subscribe loop → cleanup."""
        remote = getattr(ws, "remote_address", None)
        client_id = f"{remote[0]}:{remote[1]}" if remote else "unknown"
        try:
            if auth_handler is not None:
                raw = await ws.recv()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await ws.close(code=4400, reason="invalid auth payload")
                    return
                if msg.get("action") != "auth":
                    await ws.close(code=4401, reason="auth required")
                    return
                if not auth_handler(str(msg.get("token", ""))):
                    await ws.close(code=4401, reason="invalid token")
                    return

            async with self._lock:
                self._clients[ws] = set()

            async for raw in ws:
                await self._dispatch_message(ws, raw)
        except Exception:  # noqa: BLE001
            logger.debug("Connection %s error", client_id, exc_info=True)
        finally:
            async with self._lock:
                self._clients.pop(ws, None)

    async def _dispatch_message(self, ws: Any, raw: str | bytes) -> None:
        """Apply a client-initiated subscription / unsubscription."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            await ws.send(json.dumps({"error": "invalid_json"}))
            return
        if not isinstance(msg, dict):
            await ws.send(json.dumps({"error": "expected_object"}))
            return
        action = msg.get("action")
        channel = str(msg.get("channel", ""))
        if not channel:
            await ws.send(json.dumps({"error": "channel_required"}))
            return
        async with self._lock:
            channels = self._clients.get(ws)
            if channels is None:
                return
            if action == "subscribe":
                channels.add(channel)
                await ws.send(json.dumps({"status": "subscribed", "channel": channel}))
            elif action == "unsubscribe":
                channels.discard(channel)
                await ws.send(json.dumps({"status": "unsubscribed", "channel": channel}))
            elif action == "ping":
                await ws.send(json.dumps({"status": "pong"}))
            else:
                await ws.send(json.dumps({"error": "unknown_action", "action": action}))