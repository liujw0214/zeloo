"""Gateway session manager — per-user/per-platform session isolation.

Wraps :class:`zeloo_state.SessionDB` to provide:
* Lookup of the active session for a (user_id, platform) pair.
* Creation of a fresh session when none exists.
* Idle-timeout eviction of stale agent instances.
* Optional per-user allow-list enforcement.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_IDLE_TIMEOUT = 3600  # seconds


@dataclass
class AgentEntry:
    """A cached AIAgent instance with last-used metadata."""

    agent: Any
    user_id: str
    platform: str
    session_id: str
    last_used: float = field(default_factory=time.time)

    def touch(self) -> None:
        """Update the last-used timestamp."""
        self.last_used = time.time()


class SessionManager:
    """Manages per-user/per-platform agent instances and session recovery."""

    def __init__(
        self,
        session_db: Any,
        idle_timeout: int = DEFAULT_IDLE_TIMEOUT,
        allowed_users: dict[str, list[str]] | None = None,
    ) -> None:
        self._db = session_db
        self._idle_timeout = idle_timeout
        # allowed_users: platform -> list of allowed user ids (None = allow all)
        self._allowed_users: dict[str, list[str] | None] = allowed_users or {}
        self._agents: dict[tuple[str, str], AgentEntry] = {}
        self._lock = threading.Lock()

    # ── Access control ──────────────────────────────────────────────

    def is_user_allowed(self, user_id: str, platform: str) -> bool:
        """Check if a user is allowed on the given platform."""
        allowed = self._allowed_users.get(platform)
        if allowed is None:
            return True  # No restriction for this platform
        return user_id in allowed

    # ── Session lifecycle ───────────────────────────────────────────

    def get_or_create_agent(
        self,
        user_id: str,
        platform: str,
        agent_factory: Callable[..., Any] | None = None,
        ) -> Any | None:
        """Return an existing agent for (user_id, platform) or create one.

        Args:
            user_id: The platform-specific user identifier.
            platform: Platform name (e.g. "telegram").
            agent_factory: Callable(session_id, platform, user_id) -> AIAgent.

        Returns:
            The AIAgent instance, or None if the user is not allowed.
        """
        if not self.is_user_allowed(user_id, platform):
            logger.warning("User %s not allowed on platform %s", user_id, platform)
            return None

        key = (user_id, platform)
        with self._lock:
            entry = self._agents.get(key)
            if entry is not None:
                entry.touch()
                return entry.agent

            # Try to recover an active session from the DB
            session_row = self._get_active_session(user_id, platform)
            if session_row is not None:
                session_id = session_row["session_id"]
                logger.info("Recovered session %s for %s/%s", session_id, user_id, platform)
            else:
                session_id = self._create_session(user_id, platform)
                logger.info("Created session %s for %s/%s", session_id, user_id, platform)

            agent = agent_factory(session_id=session_id, platform=platform, user_id=user_id)
            self._agents[key] = AgentEntry(
                agent=agent,
                user_id=user_id,
                platform=platform,
                session_id=session_id,
            )
            return agent

    def _get_active_session(self, user_id: str, platform: str) -> Any | None:
        """Look up the most recent session for a user/platform pair."""
        try:
            return self._db.get_active_session(user_id, platform)
        except Exception:
            logger.exception("Failed to look up active session")
            return None

    def _create_session(self, user_id: str, platform: str) -> str:
        """Create a new session row and return its ID."""
        import uuid
        from datetime import datetime

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_id = f"{ts}_{uuid.uuid4().hex[:8]}"
        self._db.create_session(session_id, user_id=user_id, platform=platform)
        return session_id

    # ── Eviction ────────────────────────────────────────────────────

    def evict_idle(self) -> int:
        """Evict agent instances idle longer than the timeout.

        Returns the number of evicted entries.
        """
        now = time.time()
        evicted = 0
        with self._lock:
            stale_keys = [
                key
                for key, entry in self._agents.items()
                if now - entry.last_used > self._idle_timeout
            ]
            for key in stale_keys:
                entry = self._agents.pop(key)
                try:
                    entry.agent.close()
                except Exception:
                    logger.exception("Failed to close agent for session %s", entry.session_id)
                evicted += 1
        if evicted:
            logger.info("Evicted %d idle agent(s)", evicted)
        return evicted

    def get_active_count(self) -> int:
        """Return the number of cached agent instances."""
        with self._lock:
            return len(self._agents)

    def iter_active_agents(self):
        """Yield all currently cached (user_id, platform, agent) tuples.

        Snapshots the agents dict under the lock so callers can iterate
        safely without holding it.
        """
        with self._lock:
            snapshot = list(self._agents.items())
        for (user_id, platform), entry in snapshot:
            yield user_id, platform, entry.agent
