"""Feature flags — runtime feature toggling and A/B testing."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class FlagState(StrEnum):
    """Feature flag states."""

    ENABLED = "enabled"
    DISABLED = "disabled"
    PERCENTAGE = "percentage"
    USER_LIST = "user_list"


@dataclass
class FeatureFlag:
    """A feature flag definition."""

    name: str
    state: FlagState = FlagState.DISABLED
    description: str = ""
    percentage: float = 0.0  # For PERCENTAGE state
    allowed_users: list[str] = field(default_factory=list)
    denied_users: list[str] = field(default_factory=list)
    rules: list[Callable[[str], bool]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


class FeatureFlagManager:
    """Manage feature flags for runtime toggling and gradual rollouts.

    Supports:
    - Simple boolean flags (enabled/disabled)
    - Percentage-based rollouts
    - User-list targeting (allow/deny)
    - Custom rule evaluation
    """

    def __init__(self) -> None:
        self._flags: dict[str, FeatureFlag] = {}
        self._lock = threading.Lock()
        self._history: list[dict[str, Any]] = []

    def create_flag(
        self,
        name: str,
        state: FlagState = FlagState.DISABLED,
        description: str = "",
        percentage: float = 0.0,
    ) -> FeatureFlag:
        flag = FeatureFlag(
            name=name,
            state=state,
            description=description,
            percentage=percentage,
        )
        with self._lock:
            self._flags[name] = flag
            self._history.append({
                "action": "create",
                "name": name,
                "state": state.value,
                "timestamp": time.time(),
            })
        logger.info("Created feature flag %s (%s)", name, state.value)
        return flag

    def enable(self, name: str) -> bool:
        return self._set_state(name, FlagState.ENABLED)

    def disable(self, name: str) -> bool:
        return self._set_state(name, FlagState.DISABLED)

    def set_percentage(self, name: str, percentage: float) -> bool:
        flag = self._flags.get(name)
        if flag is None:
            return False
        with self._lock:
            flag.state = FlagState.PERCENTAGE
            flag.percentage = percentage
            flag.updated_at = time.time()
            self._history.append({
                "action": "set_percentage",
                "name": name,
                "percentage": percentage,
                "timestamp": time.time(),
            })
        return True

    def is_enabled(
        self, name: str, user_id: str = ""
    ) -> bool:
        flag = self._flags.get(name)
        if flag is None:
            return False
        return self._evaluate(flag, user_id)

    def _evaluate(
        self, flag: FeatureFlag, user_id: str
    ) -> bool:
        if user_id in flag.denied_users:
            return False
        if flag.allowed_users and user_id not in flag.allowed_users:
            return False
        if flag.state == FlagState.ENABLED:
            return True
        if flag.state == FlagState.DISABLED:
            return False
        if flag.state == FlagState.PERCENTAGE:
            if not user_id:
                return False
            return self._hash_bucket(user_id, flag.name) < flag.percentage
        if flag.state == FlagState.USER_LIST:
            return user_id in flag.allowed_users
        for rule in flag.rules:
            try:
                if rule(user_id):
                    return True
            except Exception as e:
                logger.warning("Flag rule error: %s", e)
        return False

    def _hash_bucket(self, user_id: str, flag_name: str) -> float:
        bucket_str = f"{flag_name}:{user_id}"
        hash_int = int(uuid.uuid5(uuid.NAMESPACE_DNS, bucket_str).hex[:8], 16)
        return (hash_int % 10_000) / 100.0

    def _set_state(self, name: str, state: FlagState) -> bool:
        flag = self._flags.get(name)
        if flag is None:
            return False
        with self._lock:
            flag.state = state
            flag.updated_at = time.time()
            self._history.append({
                "action": f"set_{state.value}",
                "name": name,
                "timestamp": time.time(),
            })
        return True

    def list_flags(self) -> list[FeatureFlag]:
        with self._lock:
            return list(self._flags.values())

    def delete(self, name: str) -> bool:
        with self._lock:
            return self._flags.pop(name, None) is not None

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._history[-limit:])


__all__ = ["FeatureFlag", "FeatureFlagManager", "FlagState"]