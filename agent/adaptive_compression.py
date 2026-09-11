"""Adaptive compression scheduler.

Watches per-session token usage and triggers
:class:`agent.compression_facade.CompressionFacade` automatically
when usage crosses configured thresholds. Designed to plug into the
conversation loop so callers don't have to micromanage compression.

Features:

* **Per-session buckets** — track usage for multiple sessions concurrently
* **Tiered triggers** — soft (warn), medium (auto-summarize old turns),
  hard (truncate / drop oldest)
* **Cooldown** — don't re-compress the same window more than once per N seconds
* **Callbacks** — observe events for logging / metrics
* **Statistics** — total compressions, tokens saved, avg reduction ratio

Usage::

    scheduler = AdaptiveCompressionScheduler(
        context_window=128_000,
        soft_threshold=0.6,
        medium_threshold=0.8,
        hard_threshold=0.95,
    )
    scheduler.attach_facade(facade)

    # Each turn:
    action = scheduler.observe(session_id="s1", token_count=100_000)
    if action == CompressionAction.SUMMARIZE:
        new_messages = facade.compress(...)
        scheduler.record_compression(session_id="s1", ...)
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent.compression_facade import CompressionFacade, CompressionMode

logger = logging.getLogger(__name__)


class CompressionAction(str, Enum):  # noqa: UP042
    """Action that the scheduler recommends."""

    NONE = "none"  # within budget
    WARN = "warn"  # soft threshold crossed
    SUMMARIZE = "summarize"  # medium threshold — compress old turns
    TRUNCATE = "truncate"  # hard threshold — drop oldest messages


@dataclass
class SessionBucket:
    """Per-session compression tracking state."""

    session_id: str
    last_token_count: int = 0
    last_action: CompressionAction = CompressionAction.NONE
    last_action_at: float = 0.0
    last_compression_at: float = 0.0
    total_compressions: int = 0
    tokens_saved: int = 0
    peak_token_count: int = 0

    def record_compression(self, before: int, after: int) -> None:
        """Update stats after a successful compression."""
        self.total_compressions += 1
        saved = max(0, before - after)
        self.tokens_saved += saved
        now = time.time()
        self.last_compression_at = now
        self.last_action_at = now


@dataclass
class SchedulerConfig:
    """Configuration for the adaptive compression scheduler."""

    context_window: int = 128_000
    soft_threshold: float = 0.60  # warn only
    medium_threshold: float = 0.80  # auto-summarize
    hard_threshold: float = 0.95  # truncate
    cooldown_seconds: float = 30.0  # min interval between compressions


class AdaptiveCompressionScheduler:
    """Per-session adaptive compression scheduler."""

    def __init__(self, config: SchedulerConfig | None = None) -> None:
        self.config = config or SchedulerConfig()
        self._lock = threading.Lock()
        self._buckets: dict[str, SessionBucket] = {}
        self._facade: CompressionFacade | None = None
        self._on_action_callbacks: list[Any] = []

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------
    def attach_facade(self, facade: CompressionFacade) -> None:
        """Attach a :class:`CompressionFacade` for fallback compression."""
        self._facade = facade

    def on_action(self, callback: Any) -> None:
        """Register a callback invoked on every :meth:`observe` action.

        Callback signature: ``callback(session_id, action, token_count)``
        """
        self._on_action_callbacks.append(callback)

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------
    def observe(self, session_id: str, token_count: int) -> CompressionAction:
        """Record *token_count* for *session_id* and return the action to take.

        The action is determined by the threshold *token_count* falls in:

        * < soft_threshold     → :attr:`CompressionAction.NONE`
        * < medium_threshold   → :attr:`CompressionAction.WARN`
        * < hard_threshold     → :attr:`CompressionAction.SUMMARIZE`
        * >= hard_threshold    → :attr:`CompressionAction.TRUNCATE`
        """
        bucket = self._get_bucket(session_id)
        bucket.last_token_count = token_count
        bucket.peak_token_count = max(bucket.peak_token_count, token_count)

        ratio = token_count / max(1, self.config.context_window)

        if ratio >= self.config.hard_threshold:
            action = CompressionAction.TRUNCATE
        elif ratio >= self.config.medium_threshold:
            action = CompressionAction.SUMMARIZE
        elif ratio >= self.config.soft_threshold:
            action = CompressionAction.WARN
        else:
            action = CompressionAction.NONE

        # Cooldown: don't recommend the same compression action twice in
        # quick succession (use last_action_at, not last_compression_at).
        if action in (CompressionAction.SUMMARIZE, CompressionAction.TRUNCATE):
            elapsed = time.time() - bucket.last_action_at
            if (
                bucket.last_action == action
                and elapsed < self.config.cooldown_seconds
            ):
                # Don't escalate; skip redundant trigger.
                action = CompressionAction.WARN

        bucket.last_action = action
        bucket.last_action_at = time.time()

        # Fire callbacks (best effort, don't propagate errors).
        for cb in self._on_action_callbacks:
            try:
                cb(session_id, action, token_count)
            except Exception:  # noqa: BLE001
                logger.exception("compression scheduler callback failed")

        return action

    def record_compression(
        self,
        session_id: str,
        tokens_before: int,
        tokens_after: int,
    ) -> None:
        """Update bucket stats after the caller has performed compression."""
        bucket = self._get_bucket(session_id)
        bucket.record_compression(tokens_before, tokens_after)
        bucket.last_token_count = tokens_after

    def suggest_mode(self, session_id: str) -> CompressionMode:
        """Recommend a CompressionMode based on the session's last action."""
        from agent.compression_facade import CompressionMode

        bucket = self._get_bucket(session_id)
        action_to_mode = {
            CompressionAction.NONE: CompressionMode.DISABLED,
            CompressionAction.WARN: CompressionMode.SUMMARIZE,
            CompressionAction.SUMMARIZE: CompressionMode.HYBRID,
            CompressionAction.TRUNCATE: CompressionMode.TRUNCATE,
        }
        return action_to_mode.get(bucket.last_action, CompressionMode.DISABLED)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        """Return aggregate scheduler stats across all sessions."""
        with self._lock:
            buckets = list(self._buckets.values())
        total_compressions = sum(b.total_compressions for b in buckets)
        total_saved = sum(b.tokens_saved for b in buckets)
        return {
            "sessions_tracked": len(buckets),
            "total_compressions": total_compressions,
            "tokens_saved": total_saved,
            "config": {
                "context_window": self.config.context_window,
                "soft": self.config.soft_threshold,
                "medium": self.config.medium_threshold,
                "hard": self.config.hard_threshold,
            },
        }

    def session_status(self, session_id: str) -> dict[str, Any]:
        """Return per-session status."""
        bucket = self._get_bucket(session_id)
        ratio = bucket.last_token_count / max(1, self.config.context_window)
        return {
            "session_id": session_id,
            "last_token_count": bucket.last_token_count,
            "peak_token_count": bucket.peak_token_count,
            "ratio": round(ratio, 3),
            "last_action": bucket.last_action.value,
            "total_compressions": bucket.total_compressions,
            "tokens_saved": bucket.tokens_saved,
            "seconds_since_compression": (
                round(time.time() - bucket.last_compression_at, 1)
                if bucket.last_compression_at
                else None
            ),
        }

    def reset(self, session_id: str | None = None) -> None:
        """Clear bucket state for *session_id* (or all if None)."""
        with self._lock:
            if session_id is None:
                self._buckets.clear()
            else:
                self._buckets.pop(session_id, None)

    def _get_bucket(self, session_id: str) -> SessionBucket:
        with self._lock:
            bucket = self._buckets.get(session_id)
            if bucket is None:
                bucket = SessionBucket(session_id=session_id)
                self._buckets[session_id] = bucket
            return bucket