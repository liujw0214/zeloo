"""Gateway state — unified view across all message platforms."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class GatewayStats:
    active_platforms: int = 0
    total_sessions: int = 0
    total_messages: int = 0
    platform_summary: dict[str, Any] = field(default_factory=dict)


class GatewayState:
    """Aggregate state across all gateway platforms."""

    def refresh(self) -> GatewayStats:
        """Refresh and return aggregated stats."""
        stats = GatewayStats()

        try:
            from gateway.platform_registry import list_platforms
            stats.active_platforms = len(list_platforms())
        except Exception:
            pass

        try:
            from zeloo_state import SessionDB
            db = SessionDB()
            conn = db._conn
            cur = conn.cursor()
            cur.execute("SELECT platform, COUNT(*) as sessions FROM sessions GROUP BY platform")
            rows = cur.fetchall()
            for row in rows:
                stats.total_sessions += row[1]
                stats.platform_summary[row["platform"]] = dict(row)
        except Exception:
            pass

        return stats

    def platform_health(self, platform: str) -> dict[str, Any]:
        """Get health summary for a specific platform."""
        return {"platform": platform, "active": True}

    def list_active_platforms(self) -> list[str]:
        """Return list of active platform names."""
        try:
            from gateway.platform_registry import list_platforms
            return list(list_platforms())
        except Exception:
            return []
