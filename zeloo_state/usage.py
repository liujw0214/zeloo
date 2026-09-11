"""Usage tracking for model API calls and token consumption."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Per-1M-token cost rates in USD, keyed by model prefix.
# Format: (input_rate, output_rate) per 1M tokens.
_MODEL_RATES: dict[str, tuple[float, float]] = {
    "deepseek-chat": (0.27, 1.10),
    "deepseek-coder": (0.27, 1.10),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-1.5-flash": (0.035, 0.14),
    "gemini-1.5-pro": (1.25, 5.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (2.50, 10.00),
    "gpt-4o": (2.50, 10.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    "claude-3-5-haiku": (0.80, 4.00),
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-3-opus": (15.00, 75.00),
}

_DEFAULT_RATE: tuple[float, float] = (1.00, 4.00)


@dataclass
class UsageRecord:
    """A single API usage event."""

    session_id: str
    platform: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float
    latency_ms: float
    timestamp: float
    metadata: dict[str, Any] = field(default_factory=dict)


class UsageTracker:
    """Track API usage per session and aggregate across the database."""

    def __init__(self, db_path: str | None = None) -> None:
        import os

        if db_path:
            self.db_path = str(db_path)
        else:
            env = os.environ.get("zeloo_HOME")
            if env:
                self.db_path = os.path.join(env, "state.db")
            else:
                self.db_path = os.path.join(
                    os.path.expanduser("~"), ".Zeloo", "state.db"
                )
        self._ensure_table()

    def _ensure_table(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS usage_records ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "session_id TEXT NOT NULL,"
            "platform TEXT,"
            "model TEXT,"
            "input_tokens INTEGER DEFAULT 0,"
            "output_tokens INTEGER DEFAULT 0,"
            "total_tokens INTEGER DEFAULT 0,"
            "cost_usd REAL DEFAULT 0.0,"
            "latency_ms REAL DEFAULT 0.0,"
            "timestamp REAL NOT NULL,"
            "metadata TEXT"
            ")"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_usage_session_id "
            "ON usage_records(session_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_usage_timestamp "
            "ON usage_records(timestamp)"
        )
        conn.commit()
        conn.close()

    def record(
        self,
        session_id: str,
        platform: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
        metadata: dict[str, Any] | None = None,
        cost_usd: float | None = None,
    ) -> None:
        total_tokens = input_tokens + output_tokens
        cost = (
            cost_usd
            if cost_usd is not None
            else self._estimate_cost(model, input_tokens, output_tokens)
        )
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO usage_records "
            "(session_id, platform, model, input_tokens, output_tokens, "
            "total_tokens, cost_usd, latency_ms, timestamp, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                platform,
                model,
                input_tokens,
                output_tokens,
                total_tokens,
                cost,
                latency_ms,
                datetime.now(UTC).timestamp(),
                str(metadata or {}),
            ),
        )
        conn.commit()
        conn.close()

    def _estimate_cost(
        self, model: str, input_tokens: int, output_tokens: int
    ) -> float:
        """Return cost estimate in USD using the current pricing table."""
        m = model.lower()
        rate_in = _DEFAULT_RATE[0]
        rate_out = _DEFAULT_RATE[1]

        for prefix, (r_in, r_out) in _MODEL_RATES.items():
            if prefix in m:
                rate_in, rate_out = r_in, r_out
                break

        in_cost = input_tokens / 1_000_000 * rate_in
        out_cost = output_tokens / 1_000_000 * rate_out
        return round(in_cost + out_cost, 8)

    def get_session_usage(self, session_id: str) -> dict[str, Any]:
        """Get usage for a specific session."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT * FROM usage_records "
            "WHERE session_id = ? ORDER BY timestamp DESC",
            (session_id,),
        )
        rows = cur.fetchall()
        conn.close()
        if not rows:
            return {
                "session_id": session_id,
                "calls": [],
                "total_tokens": 0,
                "total_cost": 0.0,
            }
        total_tokens = sum(r["total_tokens"] for r in rows)
        total_cost = round(sum(r["cost_usd"] for r in rows), 8)
        return {
            "session_id": session_id,
            "calls": [dict(r) for r in rows],
            "total_tokens": total_tokens,
            "total_cost": total_cost,
        }

    def get_platform_usage(
        self, platform: str | None = None
    ) -> dict[str, Any]:
        """Get usage aggregated by platform/model."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        if platform:
            cur = conn.execute(
                "SELECT platform, model, COUNT(*) as calls, "
                "COALESCE(SUM(input_tokens),0) as total_in, "
                "COALESCE(SUM(output_tokens),0) as total_out, "
                "COALESCE(SUM(total_tokens),0) as total_tokens, "
                "COALESCE(SUM(cost_usd),0.0) as total_cost "
                "FROM usage_records "
                "WHERE platform = ? "
                "GROUP BY platform, model",
                (platform,),
            )
        else:
            cur = conn.execute(
                "SELECT platform, model, COUNT(*) as calls, "
                "COALESCE(SUM(input_tokens),0) as total_in, "
                "COALESCE(SUM(output_tokens),0) as total_out, "
                "COALESCE(SUM(total_tokens),0) as total_tokens, "
                "COALESCE(SUM(cost_usd),0.0) as total_cost "
                "FROM usage_records "
                "GROUP BY platform, model"
            )
        rows = cur.fetchall()
        conn.close()
        return {"breakdown": [dict(r) for r in rows]}

    def get_total_usage(self) -> dict[str, Any]:
        """Get total usage across all sessions."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT "
            "COUNT(*) as calls, "
            "COALESCE(SUM(input_tokens),0) as total_in, "
            "COALESCE(SUM(output_tokens),0) as total_out, "
            "COALESCE(SUM(total_tokens),0) as total_tokens, "
            "COALESCE(SUM(cost_usd),0.0) as total_cost "
            "FROM usage_records"
        )
        row = cur.fetchone()
        conn.close()
        if row is None:
            return {"calls": 0, "total_in": 0, "total_out": 0, "total_tokens": 0, "total_cost": 0.0}
        result = dict(row)
        result["total_cost"] = round(result["total_cost"], 8)
        return result
