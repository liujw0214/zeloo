"""Event bus — publish/subscribe event system for inter-module communication."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """Event published on the bus."""

    topic: str
    data: Any = None
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    timestamp: float = field(default_factory=time.time)
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Subscription:
    """An event subscription."""

    topic: str
    handler: Callable[[Event], Any]
    subscription_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    async_mode: bool = False
    filter_func: Callable[[Event], bool] | None = None


class EventBus:
    """In-process publish/subscribe event bus.

    Supports:
    - Synchronous handlers
    - Async handlers (run in thread pool)
    - Topic-based routing (with wildcard support)
    - Event filtering
    - Synchronous or fire-and-forget publishing
    """

    def __init__(self, max_workers: int = 4) -> None:
        self._subscriptions: dict[str, list[Subscription]] = defaultdict(list)
        self._lock = threading.Lock()
        self._executor: ThreadPoolExecutor | None = None
        self._history: list[Event] = []
        self._max_history = 1000
        self._max_workers = max_workers

    def subscribe(
        self,
        topic: str,
        handler: Callable[[Event], Any],
        async_mode: bool = False,
        filter_func: Callable[[Event], bool] | None = None,
    ) -> Subscription:
        """Subscribe to events on a topic (supports `*` wildcard)."""
        sub = Subscription(
            topic=topic,
            handler=handler,
            async_mode=async_mode,
            filter_func=filter_func,
        )
        with self._lock:
            self._subscriptions[topic].append(sub)
        logger.debug("Subscribed handler to %s (id=%s)", topic, sub.subscription_id)
        return sub

    def unsubscribe(self, subscription: Subscription) -> bool:
        """Unsubscribe a handler."""
        with self._lock:
            subs = self._subscriptions.get(subscription.topic, [])
            if subscription in subs:
                subs.remove(subscription)
                return True
        return False

    def publish(
        self,
        topic: str,
        data: Any = None,
        source: str = "",
        metadata: dict[str, Any] | None = None,
        synchronous: bool = False,
    ) -> Event:
        """Publish an event.

        Args:
            topic: Event topic (supports `*` wildcard subscription).
            data: Event payload.
            source: Originating module/component.
            metadata: Optional event metadata.
            synchronous: If True, wait for all handlers to complete.
        """
        event = Event(
            topic=topic,
            data=data,
            source=source,
            metadata=metadata or {},
        )

        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        all_subs = []
        with self._lock:
            for pattern, subs in self._subscriptions.items():
                if self._match(pattern, topic):
                    all_subs.extend(subs)

        logger.debug(
            "Publishing %s (id=%s): %d handlers",
            topic, event.event_id, len(all_subs),
        )

        if synchronous:
            for sub in all_subs:
                if sub.filter_func and not sub.filter_func(event):
                    continue
                try:
                    sub.handler(event)
                except Exception as e:
                    logger.exception("Handler error in %s: %s", sub.subscription_id, e)
        else:
            self._ensure_executor()
            if self._executor is not None:
                for sub in all_subs:
                    if sub.filter_func and not sub.filter_func(event):
                        continue
                    self._executor.submit(
                        self._safe_handler, sub, event,
                    )

        return event

    async def publish_async(
        self,
        topic: str,
        data: Any = None,
        source: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> Event:
        """Async publish that awaits all handlers."""
        event = Event(topic=topic, data=data, source=source, metadata=metadata or {})
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        all_subs = []
        with self._lock:
            for pattern, subs in self._subscriptions.items():
                if self._match(pattern, topic):
                    all_subs.extend(subs)

        tasks = []
        for sub in all_subs:
            if sub.filter_func and not sub.filter_func(event):
                continue
            if asyncio.iscoroutinefunction(sub.handler):
                tasks.append(sub.handler(event))
            else:
                tasks.append(asyncio.to_thread(sub.handler, event))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        return event

    def _safe_handler(self, sub: Subscription, event: Event) -> None:
        try:
            sub.handler(event)
        except Exception as e:
            logger.exception("Handler error in %s: %s", sub.subscription_id, e)

    def _ensure_executor(self) -> None:
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=self._max_workers)

    def _match(self, pattern: str, topic: str) -> bool:
        if pattern == topic:
            return True
        if pattern == "*":
            return True
        if pattern.endswith(".*") and topic.startswith(pattern[:-1]):
            return True
        if pattern.startswith("*.") and topic.endswith(pattern[1:]):
            return True
        return False

    def history(self, topic: str | None = None, limit: int = 100) -> list[Event]:
        """Get recent event history."""
        events = self._history
        if topic:
            events = [e for e in events if e.topic == topic]
        return events[-limit:]

    def close(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None


__all__ = ["Event", "EventBus", "Subscription"]