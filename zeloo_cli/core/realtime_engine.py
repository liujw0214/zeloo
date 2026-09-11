"""Realtime push engine — WebSocket/SSE fan-out for live updates."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class SubscriptionChannel:
    """A channel subscription for realtime updates."""

    channel: str
    subscriber_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    callback: Callable[[dict], Any] = field(default_factory=lambda c: None)
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    created_at: float = field(default_factory=time.time)


class RealtimeEngine:
    """Pub/sub realtime engine for pushing live updates.

    Supports multiple channels with subscriber queues.
    Messages are dispatched to all subscribers of a channel.
    """

    def __init__(self) -> None:
        self._channels: dict[str, list[SubscriptionChannel]] = {}
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._started = False
        self._message_count = 0

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._loop_thread = threading.Thread(
            target=self._run_loop, daemon=True, name="RealtimeEngine"
        )
        self._loop_thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        if not self._started:
            return
        self._started = False
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(self._stop_async(), self._loop)
        if self._loop_thread is not None:
            self._loop_thread.join(timeout=timeout)

    def subscribe(
        self,
        channel: str,
        callback: Callable[[dict], Any] | None = None,
    ) -> SubscriptionChannel:
        """Subscribe to a channel."""
        sub = SubscriptionChannel(channel=channel, callback=callback)
        with self._lock:
            self._channels.setdefault(channel, []).append(sub)
        return sub

    def unsubscribe(self, subscription: SubscriptionChannel) -> bool:
        with self._lock:
            subs = self._channels.get(subscription.channel, [])
            if subscription in subs:
                subs.remove(subscription)
                return True
        return False

    def publish(
        self,
        channel: str,
        data: dict[str, Any],
    ) -> int:
        """Publish a message to all subscribers of a channel.

        Returns the number of subscribers notified.
        """
        with self._lock:
            subs = list(self._channels.get(channel, []))

        notified = 0
        for sub in subs:
            try:
                if sub.callback:
                    sub.callback(data)
                else:
                    try:
                        sub.queue.put_nowait(data)
                    except asyncio.QueueFull:
                        logger.warning("Subscriber queue full for %s", sub.subscriber_id)
                notified += 1
            except Exception as e:
                logger.exception("Subscriber error: %s", e)

        self._message_count += 1
        return notified

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total_subs = sum(len(s) for s in self._channels.values())
        return {
            "channels": len(self._channels),
            "total_subscribers": total_subs,
            "messages_published": self._message_count,
        }

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()

    async def _stop_async(self) -> None:
        if self._loop is not None:
            self._loop.stop()


__all__ = ["RealtimeEngine", "SubscriptionChannel"]